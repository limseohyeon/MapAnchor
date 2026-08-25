from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Iterable

from ezdxf.addons import iterdxf
from ezdxf.entities import DXFGraphic


LOGGER = logging.getLogger(__name__)

BINARY_DXF_MAGIC = b"AutoCAD Binary DXF"
_ABSURD_ABS = 1.0e15

StreamExtents = tuple[float, float, float, float]

# Entity types scanned without full document load / block expansion.
STREAM_EXTENT_TYPES: tuple[str, ...] = (
    "LINE",
    "LWPOLYLINE",
    "POLYLINE",
    "POINT",
    "CIRCLE",
    "ARC",
    "ELLIPSE",
    "SPLINE",
    "TEXT",
    "MTEXT",
    "INSERT",
    "SOLID",
    "3DFACE",
)

_LOG_EVERY = 25_000


def _is_usable(value: float) -> bool:
    return math.isfinite(value) and abs(value) < _ABSURD_ABS


def _add_xy(
    points: list[tuple[float, float]], x: float, y: float
) -> None:
    if _is_usable(x) and _is_usable(y):
        points.append((float(x), float(y)))


def _add_vec(points: list[tuple[float, float]], value: object) -> None:
    try:
        x = float(value[0])  # type: ignore[index]
        y = float(value[1])  # type: ignore[index]
    except (TypeError, ValueError, IndexError, KeyError):
        return
    _add_xy(points, x, y)


def _collect_entity_points(entity: DXFGraphic) -> list[tuple[float, float]]:
    """Approximate 2D points contributing to model extents."""
    points: list[tuple[float, float]] = []
    kind = entity.dxftype()
    try:
        if kind == "LINE":
            _add_vec(points, entity.dxf.start)
            _add_vec(points, entity.dxf.end)
        elif kind == "POINT":
            _add_vec(points, entity.dxf.location)
        elif kind == "INSERT":
            # Insert point only — no block expansion (speed over exactness).
            _add_vec(points, entity.dxf.insert)
        elif kind in {"TEXT", "MTEXT"}:
            insert = getattr(entity.dxf, "insert", None)
            if insert is not None:
                _add_vec(points, insert)
        elif kind in {"CIRCLE", "ARC"}:
            center = entity.dxf.center
            radius = float(entity.dxf.radius)
            if _is_usable(radius):
                cx, cy = float(center[0]), float(center[1])
                _add_xy(points, cx - radius, cy - radius)
                _add_xy(points, cx + radius, cy + radius)
        elif kind == "ELLIPSE":
            center = entity.dxf.center
            major = entity.dxf.major_axis
            ratio = float(entity.dxf.ratio)
            mx, my = float(major[0]), float(major[1])
            major_len = math.hypot(mx, my)
            minor_len = major_len * abs(ratio)
            span = max(major_len, minor_len)
            if _is_usable(span):
                cx, cy = float(center[0]), float(center[1])
                _add_xy(points, cx - span, cy - span)
                _add_xy(points, cx + span, cy + span)
        elif kind == "LWPOLYLINE":
            for item in entity.get_points("xy"):
                _add_vec(points, item)
        elif kind == "POLYLINE":
            for vertex in entity.points():
                _add_vec(points, vertex)
        elif kind == "SPLINE":
            control_points = getattr(entity, "control_points", None)
            if control_points is not None:
                for item in control_points:
                    _add_vec(points, item)
            else:
                fit_points = getattr(entity, "fit_points", None)
                if fit_points is not None:
                    for item in fit_points:
                        _add_vec(points, item)
        elif kind in {"SOLID", "3DFACE"}:
            for attr in ("vtx0", "vtx1", "vtx2", "vtx3"):
                if hasattr(entity.dxf, attr):
                    _add_vec(points, getattr(entity.dxf, attr))
    except Exception:
        LOGGER.debug("Skipping entity points for %s", kind, exc_info=True)
    return points


def _reduce_points(points: Iterable[tuple[float, float]]) -> StreamExtents | None:
    min_x = min_y = math.inf
    max_x = max_y = -math.inf
    count = 0
    for x, y in points:
        if x < min_x:
            min_x = x
        if y < min_y:
            min_y = y
        if x > max_x:
            max_x = x
        if y > max_y:
            max_y = y
        count += 1
    if count == 0:
        return None
    if not all(_is_usable(v) for v in (min_x, min_y, max_x, max_y)):
        return None
    if max_x <= min_x or max_y <= min_y:
        return None
    return (float(min_x), float(min_y), float(max_x), float(max_y))


def try_extents_from_dxf_stream(path: Path) -> StreamExtents | None:
    """Scan modelspace entities without loading the full DXF document.

    Returns None for binary DXF, empty geometry, or I/O/parse failures.
    """
    try:
        with path.open("rb") as handle:
            magic = handle.read(len(BINARY_DXF_MAGIC))
        if magic.startswith(BINARY_DXF_MAGIC) or b"\x00" in magic[:64]:
            return None
    except OSError as exc:
        LOGGER.info("Could not open DXF for stream extents %s: %s", path, exc)
        return None

    collected: list[tuple[float, float]] = []
    try:
        for index, entity in enumerate(
            iterdxf.modelspace(path, types=STREAM_EXTENT_TYPES), start=1
        ):
            collected.extend(_collect_entity_points(entity))
            if index % _LOG_EVERY == 0:
                LOGGER.info(
                    "Stream extents progress for %s: %s entities",
                    path.name,
                    index,
                )
    except Exception:
        LOGGER.info("Stream extents failed for %s", path, exc_info=True)
        return None

    return _reduce_points(collected)
