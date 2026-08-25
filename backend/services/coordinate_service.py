from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime
from zoneinfo import ZoneInfo

from pyproj import Transformer

from backend.config import Settings, settings
from backend.crs import (
    ALLOWED_COORDINATE_SYSTEMS,
    is_allowed_coordinate_system,
)
from backend.exceptions import CoordinateError, DrawingNotFoundError
from backend.models.coordinate import (
    CoordinateConvertRequest,
    CoordinateConvertResponse,
    CoordinateFromDrawingRequest,
    CoordinateFromDrawingResponse,
    CoordinateSettingsRequest,
    CoordinateSettingsResponse,
)
from backend.models.drawing import DrawingMetadata
from backend.services.metadata_service import load_metadata, write_metadata_atomic
from backend.services.storage_service import drawing_directory
from backend.services.unit_detection import (
    ALLOWED_SCALES,
    DETECTION_AMBIGUOUS,
    SCALE_TO_UNIT,
    maybe_detect_and_apply,
)
from backend.services.upload_service import upload_service


DrawingLookup = Callable[[str], DrawingMetadata | None]

KST = ZoneInfo("Asia/Seoul")
DRAWING_ID_PATTERN = re.compile(r"^[0-9a-f]{64}$")

# always_xy=True: input/output order is longitude/X then latitude/Y.
_TRANSFORMERS: dict[str, Transformer] = {}


def get_transformer(coordinate_system: str) -> Transformer:
    if not is_allowed_coordinate_system(coordinate_system):
        raise CoordinateError(
            f"지원하지 않는 좌표계입니다: {coordinate_system}",
            "unsupported_coordinate_system",
        )
    transformer = _TRANSFORMERS.get(coordinate_system)
    if transformer is None:
        transformer = Transformer.from_crs(
            "EPSG:4326", coordinate_system, always_xy=True
        )
        _TRANSFORMERS[coordinate_system] = transformer
    return transformer


def transform_wgs84_to_projected(
    longitude: float,
    latitude: float,
    coordinate_system: str,
) -> tuple[float, float]:
    x_m, y_m = get_transformer(coordinate_system).transform(longitude, latitude)
    return float(x_m), float(y_m)


def to_drawing_millimeters(
    x_m: float, y_m: float, *, scale: int
) -> tuple[float, float]:
    return x_m * scale, y_m * scale


def is_within_extents(
    x_mm: float,
    y_mm: float,
    metadata: DrawingMetadata,
) -> bool:
    if (
        metadata.extents_min_x is None
        or metadata.extents_min_y is None
        or metadata.extents_max_x is None
        or metadata.extents_max_y is None
    ):
        raise CoordinateError(
            "도면 범위가 없어 좌표를 검사할 수 없습니다. 도면 준비를 먼저 완료해 주세요.",
            "extents_unavailable",
        )
    return (
        metadata.extents_min_x <= x_mm <= metadata.extents_max_x
        and metadata.extents_min_y <= y_mm <= metadata.extents_max_y
    )


def _unit_label(metadata: DrawingMetadata) -> str:
    scale = metadata.coordinate_scale or 1000
    unit = metadata.drawing_unit or SCALE_TO_UNIT.get(scale, "millimeter")
    if unit == "meter" or scale == 1:
        return "meter(×1)"
    return "millimeter(×1000)"


def _bounds_message(metadata: DrawingMetadata, *, in_bounds: bool) -> str:
    label = _unit_label(metadata)
    if in_bounds:
        message = f"도면 범위 안의 좌표입니다. (도면 단위 {label})"
    else:
        message = (
            "변환된 좌표가 도면 범위 밖입니다. "
            f"마커를 표시하지 않습니다. (도면 단위 {label})"
        )
    if metadata.unit_detection == DETECTION_AMBIGUOUS:
        message += " 도면 단위가 모호합니다. 툴바에서 미터/밀리미터를 선택해 주세요."
    return message


class CoordinateService:
    def __init__(
        self,
        app_settings: Settings | None = None,
        get_drawing: DrawingLookup | None = None,
    ) -> None:
        self.settings = app_settings or settings
        self.get_drawing = get_drawing or upload_service.get_drawing

    def _persist_unit_detection_if_needed(
        self, drawing_id: str, metadata: DrawingMetadata
    ) -> DrawingMetadata:
        """Legacy/auto correction when extents exist but unit was never resolved."""
        if metadata.unit_source == "manual":
            return metadata
        if metadata.unit_source == "auto" and metadata.unit_detection in {
            "meter",
            "millimeter",
            DETECTION_AMBIGUOUS,
        }:
            return metadata

        if not maybe_detect_and_apply(metadata):
            return metadata

        directory = drawing_directory(drawing_id, self.settings)
        if not (directory / "metadata.json").is_file():
            return metadata
        metadata.updated_at = datetime.now(KST)
        write_metadata_atomic(directory, metadata)
        return metadata

    def _load_mutable_metadata(self, drawing_id: str) -> DrawingMetadata:
        if not DRAWING_ID_PATTERN.fullmatch(drawing_id):
            raise DrawingNotFoundError(
                "등록된 도면을 찾을 수 없습니다.", "drawing_not_found"
            )
        directory = drawing_directory(drawing_id, self.settings)
        if not (directory / "metadata.json").is_file():
            raise DrawingNotFoundError(
                "등록된 도면을 찾을 수 없습니다.", "drawing_not_found"
            )
        return load_metadata(directory)

    def convert(
        self, drawing_id: str, request: CoordinateConvertRequest
    ) -> CoordinateConvertResponse:
        metadata = self.get_drawing(drawing_id)
        if metadata is None:
            raise DrawingNotFoundError(
                "등록된 도면을 찾을 수 없습니다.", "drawing_not_found"
            )
        metadata = self._persist_unit_detection_if_needed(drawing_id, metadata)

        coordinate_system = metadata.coordinate_system
        if not is_allowed_coordinate_system(coordinate_system):
            raise CoordinateError(
                f"지원하지 않는 좌표계입니다: {coordinate_system}",
                "unsupported_coordinate_system",
            )

        x_m, y_m = transform_wgs84_to_projected(
            request.longitude,
            request.latitude,
            coordinate_system,
        )
        scale = metadata.coordinate_scale or self.settings.coordinate_scale
        x_mm, y_mm = to_drawing_millimeters(x_m, y_m, scale=scale)
        in_bounds = is_within_extents(x_mm, y_mm, metadata)
        message = _bounds_message(metadata, in_bounds=in_bounds)

        return CoordinateConvertResponse(
            display_name=request.display_name,
            longitude=request.longitude,
            latitude=request.latitude,
            coordinate_system=coordinate_system,
            x_m=x_m,
            y_m=y_m,
            x_mm=x_mm,
            y_mm=y_mm,
            in_bounds=in_bounds,
            message=message,
        )

    def from_drawing(
        self, drawing_id: str, request: CoordinateFromDrawingRequest
    ) -> CoordinateFromDrawingResponse:
        metadata = self.get_drawing(drawing_id)
        if metadata is None:
            raise DrawingNotFoundError(
                "등록된 도면을 찾을 수 없습니다.", "drawing_not_found"
            )
        metadata = self._persist_unit_detection_if_needed(drawing_id, metadata)

        coordinate_system = metadata.coordinate_system
        if not is_allowed_coordinate_system(coordinate_system):
            raise CoordinateError(
                f"지원하지 않는 좌표계입니다: {coordinate_system}",
                "unsupported_coordinate_system",
            )

        if (
            metadata.extents_min_x is None
            or metadata.extents_min_y is None
            or metadata.extents_max_x is None
            or metadata.extents_max_y is None
        ):
            raise CoordinateError(
                "도면 범위가 없어 좌표를 검사할 수 없습니다. 도면 준비를 먼저 완료해 주세요.",
                "extents_unavailable",
            )

        x_mm = float(request.x_mm)
        y_mm = float(request.y_mm)
        scale = metadata.coordinate_scale or self.settings.coordinate_scale
        if scale <= 0:
            raise CoordinateError(
                "좌표 배율이 올바르지 않습니다.",
                "invalid_coordinate_scale",
            )
        x_m = x_mm / scale
        y_m = y_mm / scale
        in_bounds = is_within_extents(x_mm, y_mm, metadata)
        if in_bounds:
            message = f"도면 범위 안의 좌표입니다. (도면 단위 {_unit_label(metadata)})"
        else:
            message = (
                "클릭한 위치가 도면 모델 범위 밖입니다. "
                f"(도면 단위 {_unit_label(metadata)})"
            )

        return CoordinateFromDrawingResponse(
            coordinate_system=coordinate_system,
            x_m=x_m,
            y_m=y_m,
            x_mm=x_mm,
            y_mm=y_mm,
            in_bounds=in_bounds,
            message=message,
        )

    def update_coordinate_system(
        self, drawing_id: str, request: CoordinateSettingsRequest
    ) -> CoordinateSettingsResponse:
        # Backward-compatible alias used by older tests/call sites.
        return self.update_coordinate_settings(drawing_id, request)

    def update_coordinate_settings(
        self, drawing_id: str, request: CoordinateSettingsRequest
    ) -> CoordinateSettingsResponse:
        if request.coordinate_system is not None:
            if request.coordinate_system not in ALLOWED_COORDINATE_SYSTEMS:
                raise CoordinateError(
                    f"지원하지 않는 좌표계입니다: {request.coordinate_system}",
                    "unsupported_coordinate_system",
                )
        if request.coordinate_scale is not None:
            if request.coordinate_scale not in ALLOWED_SCALES:
                raise CoordinateError(
                    "지원하지 않는 도면 단위 배율입니다. 1 또는 1000만 사용할 수 있습니다.",
                    "unsupported_coordinate_scale",
                )

        metadata = self._load_mutable_metadata(drawing_id)
        directory = drawing_directory(drawing_id, self.settings)

        changed = False
        messages: list[str] = []

        if (
            request.coordinate_system is not None
            and metadata.coordinate_system != request.coordinate_system
        ):
            metadata.coordinate_system = request.coordinate_system
            changed = True
            messages.append("좌표계를 저장했습니다.")
            if metadata.unit_source != "manual":
                if maybe_detect_and_apply(metadata):
                    if metadata.unit_detection == DETECTION_AMBIGUOUS:
                        messages.append(
                            "도면 단위가 모호합니다. 툴바에서 미터/밀리미터를 선택해 주세요."
                        )
                    else:
                        messages.append(
                            f"도면 단위를 자동 판정했습니다: {_unit_label(metadata)}."
                        )

        if request.coordinate_scale is not None:
            unit = SCALE_TO_UNIT[request.coordinate_scale]
            scale_changed = (
                metadata.coordinate_scale != request.coordinate_scale
                or metadata.drawing_unit != unit
                or metadata.unit_source != "manual"
            )
            if scale_changed:
                metadata.coordinate_scale = request.coordinate_scale
                metadata.drawing_unit = unit
                metadata.unit_source = "manual"
                metadata.unit_detection = None
                changed = True
                messages.append(
                    f"도면 단위를 저장했습니다: {_unit_label(metadata)}. "
                    "이후 주소 검색부터 적용됩니다."
                )

        if not changed:
            return CoordinateSettingsResponse(
                drawing=metadata,
                message="좌표 설정이 이미 적용되어 있습니다.",
                changed=False,
            )

        metadata.updated_at = datetime.now(KST)
        write_metadata_atomic(directory, metadata)

        if not messages:
            messages.append("좌표 설정을 저장했습니다. 이후 주소 검색부터 적용됩니다.")
        elif "이후 주소 검색부터 적용됩니다." not in " ".join(messages):
            messages.append("이후 주소 검색부터 적용됩니다.")

        return CoordinateSettingsResponse(
            drawing=metadata,
            message=" ".join(messages),
            changed=True,
        )


coordinate_service = CoordinateService()
