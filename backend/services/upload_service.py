from __future__ import annotations

import asyncio
import hashlib
import os
import re
import shutil
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import UploadFile

from backend.config import Settings, settings
from backend.exceptions import ConversionInProgressError, DrawingNotFoundError
from backend.models.drawing import (
    DrawingDeleteResponse,
    DrawingMetadata,
    DrawingUploadResponse,
)
from backend.services.conversion_service import ACTIVE_STATUSES
from backend.services.metadata_service import load_metadata, write_metadata_atomic
from backend.services.storage_service import (
    create_temporary_path,
    drawing_directory,
    ensure_chunk_can_be_stored,
    finalize_source_file,
)
from backend.services.validation_service import (
    normalize_filename,
    source_extension,
    validate_dwg_header,
    validate_dxf_upload,
)


KST = ZoneInfo("Asia/Seoul")
DRAWING_ID_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class UploadService:
    def __init__(self, app_settings: Settings = settings) -> None:
        self.settings = app_settings
        self._finalize_lock = asyncio.Lock()

    async def save(self, upload_file: UploadFile) -> DrawingUploadResponse:
        original_filename = normalize_filename(upload_file.filename)
        extension = source_extension(original_filename)
        temporary_path = create_temporary_path(self.settings)
        hasher = hashlib.sha256()
        size_bytes = 0
        header_bytes = bytearray()

        try:
            with temporary_path.open("wb") as output:
                while True:
                    chunk = await upload_file.read(self.settings.chunk_size)
                    if not chunk:
                        break
                    ensure_chunk_can_be_stored(
                        self.settings.temporary_root, len(chunk), self.settings
                    )
                    output.write(chunk)
                    hasher.update(chunk)
                    size_bytes += len(chunk)
                    if len(header_bytes) < 6:
                        header_bytes.extend(chunk[: 6 - len(header_bytes)])

            file_hash = hasher.hexdigest()
            now = datetime.now(KST)

            if extension == ".dxf":
                dxf_validation = validate_dxf_upload(temporary_path)
                source_name = "original.dxf"
                source_path = "source/original.dxf"
                conversion_status = "completed"
                message = "DXF 업로드가 완료되었습니다."
                metadata_kwargs = {
                    "dwg_header": dxf_validation.header,
                    "dwg_version": dxf_validation.version,
                    "dxf_path": "converted/drawing.dxf",
                    "dxf_size_bytes": dxf_validation.size_bytes,
                    "dxf_version": dxf_validation.header,
                    "dxf_entity_count": dxf_validation.entity_count,
                    "converted_at": now,
                    "converter_name": "direct-dxf-upload",
                }
            else:
                dwg_validation = validate_dwg_header(bytes(header_bytes))
                source_name = "original.dwg"
                source_path = "source/original.dwg"
                conversion_status = "pending"
                message = "DWG 업로드가 완료되었습니다."
                metadata_kwargs = {
                    "dwg_header": dwg_validation.header,
                    "dwg_version": dwg_validation.version,
                }

            async with self._finalize_lock:
                existing_directory = drawing_directory(file_hash, self.settings)
                if (existing_directory / "metadata.json").exists():
                    temporary_path.unlink(missing_ok=True)
                    existing = load_metadata(existing_directory)
                    if original_filename not in existing.aliases:
                        existing.aliases.append(original_filename)
                        existing.updated_at = datetime.now(KST)
                        write_metadata_atomic(existing_directory, existing)
                    return DrawingUploadResponse(
                        drawing=existing,
                        duplicate=True,
                        message="동일한 도면이 이미 등록되어 있습니다.",
                    )

                directory, source_file = finalize_source_file(
                    temporary_path,
                    file_hash,
                    self.settings,
                    source_name=source_name,
                )
                if extension == ".dxf":
                    converted_directory = directory / "converted"
                    converted_directory.mkdir(parents=True, exist_ok=True)
                    staged_dxf = converted_directory / "drawing.dxf.tmp"
                    final_dxf = converted_directory / "drawing.dxf"
                    shutil.copy2(source_file, staged_dxf)
                    os.replace(staged_dxf, final_dxf)

                metadata = DrawingMetadata(
                    drawing_id=file_hash,
                    original_filename=original_filename,
                    aliases=[original_filename],
                    sha256=file_hash,
                    size_bytes=size_bytes,
                    coordinate_system=self.settings.coordinate_system,
                    drawing_unit=self.settings.drawing_unit,
                    coordinate_scale=self.settings.coordinate_scale,
                    upload_status="uploaded",
                    conversion_status=conversion_status,
                    source_path=source_path,
                    uploaded_at=now,
                    updated_at=now,
                    **metadata_kwargs,
                )
                write_metadata_atomic(directory, metadata)

            return DrawingUploadResponse(
                drawing=metadata,
                duplicate=False,
                message=message,
            )
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise
        finally:
            await upload_file.close()

    def list_drawings(self) -> list[DrawingMetadata]:
        self.settings.ensure_directories()
        drawings: list[DrawingMetadata] = []
        for path in self.settings.storage_root.glob("*/metadata.json"):
            try:
                drawings.append(load_metadata(path.parent))
            except Exception:
                continue
        return sorted(drawings, key=lambda item: item.uploaded_at, reverse=True)

    def get_drawing(self, drawing_id: str) -> DrawingMetadata | None:
        directory = drawing_directory(drawing_id, self.settings)
        if not (directory / "metadata.json").exists():
            return None
        return load_metadata(directory)

    def delete(self, drawing_id: str) -> DrawingDeleteResponse:
        if not DRAWING_ID_PATTERN.fullmatch(drawing_id):
            raise DrawingNotFoundError(
                "등록된 도면을 찾을 수 없습니다.", "drawing_not_found"
            )
        directory = drawing_directory(drawing_id, self.settings)
        if not (directory / "metadata.json").is_file():
            raise DrawingNotFoundError(
                "등록된 도면을 찾을 수 없습니다.", "drawing_not_found"
            )

        metadata = load_metadata(directory)
        lock_path = directory / "conversion.lock"
        if metadata.conversion_status in ACTIVE_STATUSES or lock_path.is_file():
            raise ConversionInProgressError(
                "변환 중인 도면은 삭제할 수 없습니다.",
                "drawing_delete_in_progress",
            )

        shutil.rmtree(directory)
        return DrawingDeleteResponse(
            drawing_id=drawing_id,
            message="도면을 삭제했습니다.",
        )


upload_service = UploadService()
