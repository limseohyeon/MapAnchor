from __future__ import annotations

import json
import logging
import os
import re
import shutil
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from backend.config import Settings, settings
from backend.exceptions import (
    ConversionError,
    ConversionInProgressError,
    DrawingError,
    DrawingNotFoundError,
    InsufficientStorageError,
)
from backend.models.drawing import (
    ConversionResponse,
    DrawingMetadata,
)
from backend.services.dxf_validation_service import DxfValidationResult, validate_dxf
from backend.services.metadata_service import load_metadata, write_metadata_atomic
from backend.services.oda_service import (
    OdaConversionResult,
    converter_version,
    find_oda_converter,
    run_oda_converter,
)
from backend.services.storage_service import drawing_directory


LOGGER = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")
DRAWING_ID_PATTERN = re.compile(r"^[0-9a-f]{64}$")
ACTIVE_STATUSES = {"queued", "checking", "converting", "validating"}
BLOCKED_CODES = {"oda_not_found", "insufficient_storage"}

OdaRunner = Callable[[Path, Path, Path, Settings], OdaConversionResult]
DxfValidator = Callable[[Path], DxfValidationResult]


class ConversionService:
    def __init__(
        self,
        app_settings: Settings = settings,
        oda_runner: OdaRunner = run_oda_converter,
        dxf_validator: DxfValidator = validate_dxf,
    ) -> None:
        self.settings = app_settings
        self.oda_runner = oda_runner
        self.dxf_validator = dxf_validator
        self._state_lock = threading.Lock()

    def _directory(self, drawing_id: str) -> Path:
        if not DRAWING_ID_PATTERN.fullmatch(drawing_id):
            raise DrawingNotFoundError(
                "등록된 도면을 찾을 수 없습니다.", "drawing_not_found"
            )
        directory = drawing_directory(drawing_id, self.settings)
        if not (directory / "metadata.json").is_file():
            raise DrawingNotFoundError(
                "등록된 도면을 찾을 수 없습니다.", "drawing_not_found"
            )
        return directory

    def get_status(self, drawing_id: str) -> DrawingMetadata:
        return load_metadata(self._directory(drawing_id))

    def queue(self, drawing_id: str, force: bool = False) -> ConversionResponse:
        with self._state_lock:
            directory = self._directory(drawing_id)
            metadata = load_metadata(directory)
            final_dxf = directory / "converted" / "drawing.dxf"

            if metadata.conversion_status in ACTIVE_STATUSES:
                raise ConversionInProgressError(
                    "이 도면은 이미 DXF 변환 중입니다.",
                    "conversion_in_progress",
                )
            if (
                not force
                and metadata.conversion_status == "completed"
                and final_dxf.is_file()
                and final_dxf.stat().st_size > 0
            ):
                return ConversionResponse(
                    drawing=metadata,
                    started=False,
                    message="기존 DXF 변환 결과를 사용합니다.",
                )

            metadata.conversion_status = "queued"
            metadata.conversion_error = None
            metadata.updated_at = datetime.now(KST)
            write_metadata_atomic(directory, metadata)
            return ConversionResponse(
                drawing=metadata,
                started=True,
                message="DXF 변환 작업을 등록했습니다.",
            )

    def convert(self, drawing_id: str) -> DrawingMetadata:
        directory = self._directory(drawing_id)
        lock_path = directory / "conversion.lock"
        job_directory: Path | None = None
        lock_created = False
        started_monotonic = time.monotonic()

        try:
            lock_descriptor = os.open(
                lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY
            )
            lock_created = True
            with os.fdopen(lock_descriptor, "w", encoding="utf-8") as lock_file:
                json.dump(
                    {
                        "drawing_id": drawing_id,
                        "process_id": os.getpid(),
                        "started_at": datetime.now(KST).isoformat(),
                    },
                    lock_file,
                    ensure_ascii=False,
                )

            metadata = load_metadata(directory)
            metadata.conversion_status = "checking"
            metadata.conversion_started_at = datetime.now(KST)
            metadata.converted_at = None
            metadata.conversion_error = None
            metadata.updated_at = datetime.now(KST)
            write_metadata_atomic(directory, metadata)

            converter = find_oda_converter(self.settings)
            if converter is None:
                raise ConversionError(
                    "ODA File Converter를 찾을 수 없습니다.", "oda_not_found"
                )

            source = directory / metadata.source_path
            if not source.is_file():
                raise ConversionError(
                    "변환할 원본 DWG 파일이 없습니다.", "source_not_found"
                )

            free_space = shutil.disk_usage(directory).free
            required_space = (
                source.stat().st_size * self.settings.conversion_space_multiplier
                + self.settings.minimum_free_space
            )
            if free_space < required_space:
                raise InsufficientStorageError(
                    "DXF 변환에 필요한 디스크 공간이 부족합니다.",
                    "insufficient_storage",
                )

            metadata.conversion_status = "converting"
            metadata.converter_name = "ODA File Converter"
            metadata.converter_version = converter_version(converter)
            metadata.updated_at = datetime.now(KST)
            write_metadata_atomic(directory, metadata)

            job_directory = (
                self.settings.conversion_temporary_root / uuid.uuid4().hex
            )
            input_directory = job_directory / "input"
            output_directory = job_directory / "output"
            input_directory.mkdir(parents=True, exist_ok=True)
            output_directory.mkdir(parents=True, exist_ok=True)
            job_source = input_directory / "original.dwg"
            try:
                os.link(source, job_source)
            except OSError:
                shutil.copy2(source, job_source)

            result = self.oda_runner(
                converter, input_directory, output_directory, self.settings
            )
            self._write_conversion_log(directory, converter, result)
            if not result.success:
                raise ConversionError(
                    f"ODA File Converter가 오류 코드 {result.exit_code}로 종료됐습니다.",
                    "converter_exit_error",
                )

            generated_files = [
                path
                for path in output_directory.iterdir()
                if path.is_file() and path.suffix.lower() == ".dxf"
            ]
            if len(generated_files) != 1:
                raise ConversionError(
                    "DXF 변환 결과 파일을 식별하지 못했습니다.",
                    "dxf_not_created",
                )

            metadata.conversion_status = "validating"
            metadata.updated_at = datetime.now(KST)
            write_metadata_atomic(directory, metadata)
            validation = self.dxf_validator(generated_files[0])

            converted_directory = directory / "converted"
            converted_directory.mkdir(parents=True, exist_ok=True)
            staged_dxf = converted_directory / "drawing.dxf.tmp"
            final_dxf = converted_directory / "drawing.dxf"
            shutil.copy2(generated_files[0], staged_dxf)
            os.replace(staged_dxf, final_dxf)

            metadata.conversion_status = "completed"
            metadata.dxf_path = "converted/drawing.dxf"
            metadata.dxf_size_bytes = validation.size_bytes
            metadata.dxf_version = validation.version
            metadata.dxf_entity_count = validation.entity_count
            metadata.converted_at = datetime.now(KST)
            metadata.conversion_duration_seconds = round(
                time.monotonic() - started_monotonic, 3
            )
            metadata.conversion_error = None
            metadata.updated_at = datetime.now(KST)
            write_metadata_atomic(directory, metadata)
            return metadata
        except FileExistsError:
            raise ConversionInProgressError(
                "이 도면은 이미 DXF 변환 중입니다.",
                "conversion_in_progress",
            )
        except DrawingError as exc:
            return self._record_failure(
                directory, exc, started_monotonic, exc.code in BLOCKED_CODES
            )
        except Exception as exc:
            LOGGER.exception("Unexpected conversion failure for %s", drawing_id)
            error = ConversionError(
                "DXF 변환 중 예상하지 못한 오류가 발생했습니다.",
                "unexpected_conversion_error",
            )
            return self._record_failure(directory, error, started_monotonic, False)
        finally:
            if job_directory is not None:
                shutil.rmtree(job_directory, ignore_errors=True)
            if lock_created:
                lock_path.unlink(missing_ok=True)

    def recover_interrupted_conversions(self) -> None:
        self.settings.ensure_directories()
        for metadata_path in self.settings.storage_root.glob("*/metadata.json"):
            try:
                directory = metadata_path.parent
                metadata = load_metadata(directory)
                if metadata.conversion_status not in ACTIVE_STATUSES:
                    continue
                metadata.conversion_status = "failed"
                metadata.conversion_error = (
                    "interrupted: 서버 종료로 변환 작업이 중단되었습니다."
                )
                metadata.updated_at = datetime.now(KST)
                write_metadata_atomic(directory, metadata)
                (directory / "conversion.lock").unlink(missing_ok=True)
            except Exception:
                LOGGER.exception("Failed to recover conversion metadata: %s", metadata_path)

    def _record_failure(
        self,
        directory: Path,
        error: DrawingError,
        started_monotonic: float,
        blocked: bool,
    ) -> DrawingMetadata:
        metadata = load_metadata(directory)
        metadata.conversion_status = "blocked" if blocked else "failed"
        metadata.conversion_error = f"{error.code}: {error.message}"
        metadata.conversion_duration_seconds = round(
            time.monotonic() - started_monotonic, 3
        )
        metadata.updated_at = datetime.now(KST)
        write_metadata_atomic(directory, metadata)
        return metadata

    @staticmethod
    def _write_conversion_log(
        directory: Path,
        converter: Path,
        result: OdaConversionResult,
    ) -> None:
        log_path = directory / "converted" / "conversion.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            "\n".join(
                [
                    f"converter={converter}",
                    f"exit_code={result.exit_code}",
                    f"duration_seconds={result.duration_seconds:.3f}",
                    "stdout:",
                    result.stdout,
                    "stderr:",
                    result.stderr,
                ]
            ),
            encoding="utf-8",
        )


conversion_service = ConversionService()
