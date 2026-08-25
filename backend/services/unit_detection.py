from __future__ import annotations

import math
from dataclasses import dataclass

from pyproj import Transformer

from backend.crs import is_allowed_coordinate_system

# Rough mainland + nearby islands envelope for Korea CRS drawings.
KOREA_LON_MIN = 124.0
KOREA_LON_MAX = 132.5
KOREA_LAT_MIN = 33.0
KOREA_LAT_MAX = 39.5

ALLOWED_SCALES: frozenset[int] = frozenset({1, 1000})

UNIT_METER = "meter"
UNIT_MILLIMETER = "millimeter"

DETECTION_METER = "meter"
DETECTION_MILLIMETER = "millimeter"
DETECTION_AMBIGUOUS = "ambiguous"
DETECTION_SKIPPED = "skipped"

SCALE_TO_UNIT: dict[int, str] = {
    1: UNIT_METER,
    1000: UNIT_MILLIMETER,
}

_REVERSE_TRANSFORMERS: dict[str, Transformer] = {}


def get_reverse_transformer(coordinate_system: str) -> Transformer:
    if not is_allowed_coordinate_system(coordinate_system):
        raise ValueError(f"unsupported_coordinate_system:{coordinate_system}")
    transformer = _REVERSE_TRANSFORMERS.get(coordinate_system)
    if transformer is None:
        transformer = Transformer.from_crs(
            coordinate_system, "EPSG:4326", always_xy=True
        )
        _REVERSE_TRANSFORMERS[coordinate_system] = transformer
    return transformer


def is_in_korea(longitude: float, latitude: float) -> bool:
    if not math.isfinite(longitude) or not math.isfinite(latitude):
        return False
    return (
        KOREA_LON_MIN <= longitude <= KOREA_LON_MAX
        and KOREA_LAT_MIN <= latitude <= KOREA_LAT_MAX
    )


def _hypothesis_in_korea(
    x: float,
    y: float,
    coordinate_system: str,
) -> bool:
    if not math.isfinite(x) or not math.isfinite(y):
        return False
    try:
        lon, lat = get_reverse_transformer(coordinate_system).transform(x, y)
    except Exception:
        return False
    return is_in_korea(float(lon), float(lat))


@dataclass(frozen=True)
class UnitDetectionResult:
    detection: str
    coordinate_scale: int | None
    drawing_unit: str | None

    @property
    def is_clear(self) -> bool:
        return self.detection in {DETECTION_METER, DETECTION_MILLIMETER}


def detect_drawing_unit(
    *,
    extents_min_x: float,
    extents_min_y: float,
    extents_max_x: float,
    extents_max_y: float,
    coordinate_system: str,
) -> UnitDetectionResult:
    """Score meter vs millimeter hypotheses against Korea under the drawing CRS."""
    if not is_allowed_coordinate_system(coordinate_system):
        return UnitDetectionResult(
            detection=DETECTION_AMBIGUOUS,
            coordinate_scale=None,
            drawing_unit=None,
        )

    center_x = (extents_min_x + extents_max_x) / 2.0
    center_y = (extents_min_y + extents_max_y) / 2.0

    meter_ok = _hypothesis_in_korea(center_x, center_y, coordinate_system)
    millimeter_ok = _hypothesis_in_korea(
        center_x / 1000.0, center_y / 1000.0, coordinate_system
    )

    if meter_ok and not millimeter_ok:
        return UnitDetectionResult(
            detection=DETECTION_METER,
            coordinate_scale=1,
            drawing_unit=UNIT_METER,
        )
    if millimeter_ok and not meter_ok:
        return UnitDetectionResult(
            detection=DETECTION_MILLIMETER,
            coordinate_scale=1000,
            drawing_unit=UNIT_MILLIMETER,
        )
    return UnitDetectionResult(
        detection=DETECTION_AMBIGUOUS,
        coordinate_scale=None,
        drawing_unit=None,
    )


def apply_unit_detection(
    metadata: object,
    result: UnitDetectionResult,
    *,
    force: bool = False,
) -> bool:
    """Apply a clear detection onto metadata when allowed.

    Returns True when metadata fields were changed.
    """
    unit_source = getattr(metadata, "unit_source", "default")
    if not force and unit_source == "manual":
        if getattr(metadata, "unit_detection", None) != DETECTION_SKIPPED:
            metadata.unit_detection = DETECTION_SKIPPED  # type: ignore[attr-defined]
            return True
        return False

    changed = False
    if getattr(metadata, "unit_detection", None) != result.detection:
        metadata.unit_detection = result.detection  # type: ignore[attr-defined]
        changed = True

    if not result.is_clear:
        return changed

    assert result.coordinate_scale is not None
    assert result.drawing_unit is not None
    if getattr(metadata, "coordinate_scale", None) != result.coordinate_scale:
        metadata.coordinate_scale = result.coordinate_scale  # type: ignore[attr-defined]
        changed = True
    if getattr(metadata, "drawing_unit", None) != result.drawing_unit:
        metadata.drawing_unit = result.drawing_unit  # type: ignore[attr-defined]
        changed = True
    if unit_source != "auto":
        metadata.unit_source = "auto"  # type: ignore[attr-defined]
        changed = True
    return changed


def maybe_detect_and_apply(metadata: object) -> bool:
    """Run detection when extents exist and unit is not manually locked."""
    unit_source = getattr(metadata, "unit_source", "default")
    if unit_source == "manual":
        return False

    min_x = getattr(metadata, "extents_min_x", None)
    min_y = getattr(metadata, "extents_min_y", None)
    max_x = getattr(metadata, "extents_max_x", None)
    max_y = getattr(metadata, "extents_max_y", None)
    if min_x is None or min_y is None or max_x is None or max_y is None:
        return False

    coordinate_system = getattr(metadata, "coordinate_system", None)
    if not isinstance(coordinate_system, str):
        return False

    result = detect_drawing_unit(
        extents_min_x=float(min_x),
        extents_min_y=float(min_y),
        extents_max_x=float(max_x),
        extents_max_y=float(max_y),
        coordinate_system=coordinate_system,
    )
    return apply_unit_detection(metadata, result)
