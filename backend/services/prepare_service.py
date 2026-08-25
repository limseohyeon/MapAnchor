from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import ezdxf
from ezdxf import bbox as ezdxf_bbox
from ezdxf.document import Drawing
from ezdxf.entities import DXFGraphic

from backend.config import Settings, settings
from backend.exceptions import DrawingError, DrawingNotFoundError, PreviewError
from backend.models.drawing import DrawingMetadata, PrepareInfoResponse
from backend.services.metadata_service import load_metadata, write_metadata_atomic
from backend.services.storage_service import drawing_directory
from backend.services.unit_detection import maybe_detect_and_apply
from backend.services.dxf_delivery import ensure_dxf_gzip
from backend.services.dxf_header_extents import try_extents_from_dxf_header_file
from backend.services.dxf_stream_extents import try_extents_from_dxf_stream


LOGGER = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")
DRAWING_ID_PATTERN = re.compile(r"^[0-9a-f]{64}$")
EXTENTS_SKIP_ENTITY_TYPES = frozenset({"HATCH", "OLE2FRAME", "IMAGE", "WIPEOUT"})
_PREPARE_SOURCE_MESSAGES = {
    "header": "도면 헤더 범위로 준비를 완료했습니다.",
    "streamed": "스트리밍 범위로 준비를 완료했습니다.",
    "computed": "도면 범위 준비를 완료했습니다.",
}


@dataclass(frozen=True)
class DrawingExtents:
    min_x: float
    min_y: float
    max_x: float
    max_y: float

    @property
    def width(self) -> float:
        return self.max_x - self.min_x

    @property
    def height(self) -> float:
        return self.max_y - self.min_y


def dxf_fingerprint(path: Path) -> str:
    stat = path.stat()
    return f"{stat.st_size}:{stat.st_mtime_ns}"


def load_dxf_document(path: Path) -> Drawing:
    try:
        return ezdxf.readfile(path)
    except (OSError, ezdxf.DXFError) as exc:
        raise PreviewError(
            "도면 DXF 파일을 읽을 수 없습니다.", "invalid_dxf"
        ) from exc


def _drawing_extents_from_bbox(extents: ezdxf_bbox.BoundingBox) -> DrawingExtents:
    if not extents.has_data:
        raise PreviewError(
            "도면에 표시할 객체 범위가 없습니다.", "empty_extents"
        )
    min_x, min_y, _ = extents.extmin
    max_x, max_y, _ = extents.extmax
    if max_x <= min_x or max_y <= min_y:
        raise PreviewError(
            "도면 범위가 올바르지 않습니다.", "invalid_extents"
        )
    return DrawingExtents(
        min_x=float(min_x),
        min_y=float(min_y),
        max_x=float(max_x),
        max_y=float(max_y),
    )


def _iter_extents_entities(
    document: Drawing,
    skip_entity_types: frozenset[str],
) -> list[DXFGraphic]:
    return [
        entity
        for entity in document.modelspace()
        if entity.dxftype() not in skip_entity_types
    ]


def calculate_extents(
    document: Drawing,
    *,
    skip_entity_types: frozenset[str] | None = None,
    fallback_to_all: bool = True,
    app_settings: Settings | None = None,
) -> DrawingExtents:
    """Compute model-space extents for marker bounds and unit detection."""
    cfg = app_settings if app_settings is not None else settings
    if skip_entity_types is None:
        skip_entity_types = (
            EXTENTS_SKIP_ENTITY_TYPES
            if cfg.preview_extents_skip_heavy
            else frozenset()
        )

    try:
        if skip_entity_types:
            filtered = _iter_extents_entities(document, skip_entity_types)
            if filtered:
                try:
                    return _drawing_extents_from_bbox(
                        ezdxf_bbox.extents(filtered, fast=True)
                    )
                except PreviewError:
                    if not fallback_to_all:
                        raise
                    LOGGER.info(
                        "Filtered extents empty; falling back to full modelspace"
                    )
            elif not fallback_to_all:
                raise PreviewError(
                    "도면에 표시할 객체 범위가 없습니다.", "empty_extents"
                )
            else:
                LOGGER.info(
                    "No drawable entities for extents; falling back to full modelspace"
                )
        return _drawing_extents_from_bbox(
            ezdxf_bbox.extents(document.modelspace(), fast=True)
        )
    except PreviewError:
        raise
    except Exception as exc:
        raise PreviewError(
            "도면 범위를 계산하지 못했습니다.", "extents_failed"
        ) from exc


class PrepareService:
    def __init__(self, app_settings: Settings | None = None) -> None:
        self.settings = app_settings or settings

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

    def _dxf_path(self, metadata: DrawingMetadata, directory: Path) -> Path:
        relative = metadata.dxf_path or "converted/drawing.dxf"
        path = directory / relative
        if not path.is_file():
            raise PreviewError(
                "변환된 DXF 파일이 없습니다.", "dxf_not_found"
            )
        return path

    def has_usable_extents(self, metadata: DrawingMetadata) -> bool:
        return (
            metadata.extents_min_x is not None
            and metadata.extents_min_y is not None
            and metadata.extents_max_x is not None
            and metadata.extents_max_y is not None
        )

    def get_prepare_info(self, drawing_id: str) -> PrepareInfoResponse:
        directory = self._directory(drawing_id)
        metadata = load_metadata(directory)
        ready = (
            self.has_usable_extents(metadata)
            and metadata.prepare_status == "completed"
        )
        return PrepareInfoResponse(
            drawing=metadata,
            prepared=ready,
            message=(
                "도면 준비가 완료되었습니다."
                if ready
                else "도면 범위 준비가 필요합니다."
            ),
        )

    def get_dxf_file(self, drawing_id: str) -> Path:
        directory = self._directory(drawing_id)
        metadata = load_metadata(directory)
        if metadata.conversion_status != "completed":
            raise PreviewError(
                "DXF 변환이 완료된 도면만 표출할 수 있습니다.",
                "conversion_not_completed",
            )
        return self._dxf_path(metadata, directory)

    def ensure_gzip_cache(self, drawing_id: str) -> Path | None:
        """Build drawing.dxf.gz for transport compression; DXF bytes unchanged."""
        try:
            dxf_path = self.get_dxf_file(drawing_id)
            return ensure_dxf_gzip(dxf_path)
        except Exception:
            LOGGER.exception("Failed to build DXF gzip cache for %s", drawing_id)
            return None

    def begin_prepare(
        self, drawing_id: str, *, force: bool = False
    ) -> PrepareInfoResponse:
        """Mark prepare as in-progress without doing heavy DXF work.

        Used by the async API path so the UI can open the viewer immediately.
        """
        directory = self._directory(drawing_id)
        metadata = load_metadata(directory)
        if metadata.conversion_status != "completed":
            raise PreviewError(
                "DXF 변환이 완료된 뒤에 도면을 준비할 수 있습니다.",
                "conversion_not_completed",
            )

        dxf_path = self._dxf_path(metadata, directory)
        fingerprint = dxf_fingerprint(dxf_path)
        if not force and self.has_usable_extents(metadata):
            hash_ok = (
                metadata.prepare_source_hash is None
                or metadata.prepare_source_hash == fingerprint
            )
            if hash_ok:
                if (
                    metadata.prepare_status != "completed"
                    or metadata.prepare_source_hash != fingerprint
                ):
                    metadata.prepare_status = "completed"
                    metadata.prepare_source_hash = fingerprint
                    metadata.prepare_error = None
                    metadata.updated_at = datetime.now(KST)
                    write_metadata_atomic(directory, metadata)
                return PrepareInfoResponse(
                    drawing=metadata,
                    prepared=True,
                    message="이미 준비된 도면 범위를 재사용합니다.",
                )

        if metadata.prepare_status == "preparing" and not force:
            return PrepareInfoResponse(
                drawing=metadata,
                prepared=False,
                message="도면 범위 준비가 진행 중입니다.",
            )

        metadata.prepare_status = "preparing"
        metadata.prepare_error = None
        metadata.updated_at = datetime.now(KST)
        write_metadata_atomic(directory, metadata)
        return PrepareInfoResponse(
            drawing=metadata,
            prepared=False,
            message="도면 범위 준비를 시작했습니다.",
        )

    def prepare(
        self, drawing_id: str, *, force: bool = False
    ) -> PrepareInfoResponse:
        directory = self._directory(drawing_id)
        metadata = load_metadata(directory)

        if metadata.conversion_status != "completed":
            raise PreviewError(
                "DXF 변환이 완료된 뒤에 도면을 준비할 수 있습니다.",
                "conversion_not_completed",
            )

        dxf_path = self._dxf_path(metadata, directory)
        fingerprint = dxf_fingerprint(dxf_path)
        if not force and self.has_usable_extents(metadata):
            hash_ok = (
                metadata.prepare_source_hash is None
                or metadata.prepare_source_hash == fingerprint
            )
            if hash_ok:
                if (
                    metadata.prepare_status != "completed"
                    or metadata.prepare_source_hash != fingerprint
                ):
                    metadata.prepare_status = "completed"
                    metadata.prepare_source_hash = fingerprint
                    metadata.prepare_error = None
                    metadata.updated_at = datetime.now(KST)
                    write_metadata_atomic(directory, metadata)
                return PrepareInfoResponse(
                    drawing=metadata,
                    prepared=True,
                    message="이미 준비된 도면 범위를 재사용합니다.",
                )

        metadata.prepare_status = "preparing"
        metadata.prepare_error = None
        metadata.updated_at = datetime.now(KST)
        write_metadata_atomic(directory, metadata)

        try:
            extents, extents_source = self._resolve_extents(
                dxf_path, force=force
            )
            metadata.extents_min_x = extents.min_x
            metadata.extents_min_y = extents.min_y
            metadata.extents_max_x = extents.max_x
            metadata.extents_max_y = extents.max_y
            metadata.extents_source = extents_source
            metadata.prepare_source_hash = fingerprint
            metadata.prepare_status = "completed"
            metadata.prepare_error = None
            # Clear legacy PNG preview gate fields so UI does not wait on them.
            metadata.preview_status = "idle"
            metadata.preview_quality = "none"
            metadata.preview_error = None
            metadata.preview_phase = None
            metadata.preview_progress = None
            maybe_detect_and_apply(metadata)
            metadata.updated_at = datetime.now(KST)
            write_metadata_atomic(directory, metadata)
            return PrepareInfoResponse(
                drawing=metadata,
                prepared=True,
                message=_PREPARE_SOURCE_MESSAGES.get(
                    extents_source, _PREPARE_SOURCE_MESSAGES["computed"]
                ),
            )
        except DrawingError as exc:
            metadata = load_metadata(directory)
            metadata.prepare_status = "failed"
            metadata.prepare_error = f"{exc.code}: {exc.message}"
            metadata.updated_at = datetime.now(KST)
            write_metadata_atomic(directory, metadata)
            raise
        except Exception as exc:
            LOGGER.exception("Unexpected prepare failure for %s", drawing_id)
            metadata = load_metadata(directory)
            metadata.prepare_status = "failed"
            metadata.prepare_error = (
                "unexpected_prepare_error: 도면 준비 중 오류가 발생했습니다."
            )
            metadata.updated_at = datetime.now(KST)
            write_metadata_atomic(directory, metadata)
            raise PreviewError(
                "도면 준비 중 예상하지 못한 오류가 발생했습니다.",
                "unexpected_prepare_error",
            ) from exc

    def _resolve_extents(
        self, dxf_path: Path, *, force: bool
    ) -> tuple[DrawingExtents, str]:
        header_extents = try_extents_from_dxf_header_file(dxf_path)
        if header_extents is not None:
            min_x, min_y, max_x, max_y = header_extents
            LOGGER.info("Using DXF header extents for %s", dxf_path.name)
            return (
                DrawingExtents(
                    min_x=min_x, min_y=min_y, max_x=max_x, max_y=max_y
                ),
                "header",
            )

        stream_extents = try_extents_from_dxf_stream(dxf_path)
        if stream_extents is not None:
            min_x, min_y, max_x, max_y = stream_extents
            LOGGER.info("Using streamed DXF extents for %s", dxf_path.name)
            return (
                DrawingExtents(
                    min_x=min_x, min_y=min_y, max_x=max_x, max_y=max_y
                ),
                "streamed",
            )

        size_bytes = dxf_path.stat().st_size
        max_computed = self.settings.extents_computed_max_bytes
        if size_bytes > max_computed and not force:
            raise PreviewError(
                "대용량 도면에서 빠른 범위 계산에 실패했습니다. "
                "다시 표시로 전체 계산을 시도할 수 있습니다.",
                "extents_stream_empty",
            )

        LOGGER.info(
            "Falling back to full ezdxf extents for %s (force=%s, size=%s)",
            dxf_path.name,
            force,
            size_bytes,
        )
        document = load_dxf_document(dxf_path)
        extents = calculate_extents(document, app_settings=self.settings)
        return extents, "computed"

    def recover_interrupted_prepares(self) -> None:
        """Mark leftover preparing jobs as failed after process restart."""
        self.settings.ensure_directories()
        for metadata_path in self.settings.storage_root.glob("*/metadata.json"):
            try:
                directory = metadata_path.parent
                metadata = load_metadata(directory)
                if metadata.prepare_status != "preparing":
                    continue
                if self.has_usable_extents(metadata):
                    metadata.prepare_status = "completed"
                    metadata.prepare_error = None
                else:
                    metadata.prepare_status = "failed"
                    metadata.prepare_error = (
                        "interrupted_prepare: 서버 종료로 도면 범위 준비가 "
                        "중단되었습니다."
                    )
                metadata.updated_at = datetime.now(KST)
                write_metadata_atomic(directory, metadata)
            except Exception:
                LOGGER.exception(
                    "Failed to recover prepare metadata: %s", metadata_path
                )


prepare_service = PrepareService()
