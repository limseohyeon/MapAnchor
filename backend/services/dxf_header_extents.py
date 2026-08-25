from __future__ import annotations

import logging
import math
from pathlib import Path


LOGGER = logging.getLogger(__name__)
BINARY_DXF_MAGIC = b"AutoCAD Binary DXF"
# Sentinel / absurd header values often left by CAD when extents were never updated.
_ABSURD_ABS = 1.0e15

HeaderExtents = tuple[float, float, float, float]


def _is_finite_number(value: float) -> bool:
    return math.isfinite(value) and abs(value) < _ABSURD_ABS


def _parse_header_point(lines: list[str], start: int) -> tuple[float, float, int] | None:
    """Parse DXF point groups 10/20 after a $EXTMIN/$EXTMAX tag. Returns (x, y, next_index)."""
    x: float | None = None
    y: float | None = None
    i = start
    while i + 1 < len(lines) and (x is None or y is None):
        code = lines[i].strip()
        raw = lines[i + 1].strip()
        i += 2
        if code == "10":
            try:
                x = float(raw)
            except ValueError:
                return None
        elif code == "20":
            try:
                y = float(raw)
            except ValueError:
                return None
        elif code == "30":
            continue
        elif code in {"9", "0"}:
            i -= 2
            break
    if x is None or y is None:
        return None
    return x, y, i


def try_extents_from_dxf_header_bytes(data: bytes) -> HeaderExtents | None:
    """Extract $EXTMIN/$EXTMAX from an ASCII DXF HEADER without entity parsing."""
    if data.startswith(BINARY_DXF_MAGIC):
        return None
    sample = data[:64]
    if b"\x00" in sample:
        return None

    text = data.decode("utf-8", errors="ignore")
    upper = text.upper()
    header_at = upper.find("\n2\nHEADER\n")
    if header_at < 0:
        header_at = upper.find("\n2\r\nHEADER\r\n")
    if header_at < 0:
        header_at = upper.find("2\nHEADER\n")
    if header_at < 0:
        return None
    endsec = upper.find("\n0\nENDSEC\n", header_at)
    if endsec < 0:
        endsec = upper.find("\n0\r\nENDSEC\r\n", header_at)
    header_text = text[header_at : endsec if endsec > 0 else header_at + 200_000]
    lines = header_text.splitlines()

    extmin: tuple[float, float] | None = None
    extmax: tuple[float, float] | None = None
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line == "9" and i + 1 < len(lines):
            name = lines[i + 1].strip().upper()
            if name == "$EXTMIN":
                parsed = _parse_header_point(lines, i + 2)
                if parsed is None:
                    return None
                extmin = (parsed[0], parsed[1])
                i = parsed[2]
                continue
            if name == "$EXTMAX":
                parsed = _parse_header_point(lines, i + 2)
                if parsed is None:
                    return None
                extmax = (parsed[0], parsed[1])
                i = parsed[2]
                continue
        i += 1

    if extmin is None or extmax is None:
        return None
    min_x, min_y = extmin
    max_x, max_y = extmax
    if not all(_is_finite_number(v) for v in (min_x, min_y, max_x, max_y)):
        return None
    if max_x <= min_x or max_y <= min_y:
        return None
    return (float(min_x), float(min_y), float(max_x), float(max_y))


def try_extents_from_dxf_header_file(
    path: Path, *, max_header_bytes: int = 2_000_000
) -> HeaderExtents | None:
    """Read only the beginning of a DXF file to recover HEADER extents."""
    try:
        with path.open("rb") as handle:
            data = handle.read(max_header_bytes)
            if b"$EXTMIN" not in data and b"$extmin" not in data:
                data += handle.read(max_header_bytes)
            if b"ENDSEC" not in data.upper() and (
                b"$EXTMAX" in data or b"$extmax" in data
            ):
                data += handle.read(max_header_bytes)
    except OSError as exc:
        LOGGER.info("Could not read DXF header from %s: %s", path, exc)
        return None
    return try_extents_from_dxf_header_bytes(data)
