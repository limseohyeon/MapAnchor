from __future__ import annotations

# Korea 2000 (GRS80) CRS whitelist for local map drawings.
ALLOWED_COORDINATE_SYSTEMS: frozenset[str] = frozenset(
    {
        "EPSG:5179",
        "EPSG:5181",
        "EPSG:5185",
        "EPSG:5186",
        "EPSG:5187",
        "EPSG:5188",
    }
)

DEFAULT_COORDINATE_SYSTEM = "EPSG:5179"

COORDINATE_SYSTEM_LABELS: dict[str, str] = {
    "EPSG:5179": "EPSG:5179 — UTM-K (통합)",
    "EPSG:5181": "EPSG:5181 — 중부원점",
    "EPSG:5185": "EPSG:5185 — 서부원점 (2010)",
    "EPSG:5186": "EPSG:5186 — 중부원점 (2010)",
    "EPSG:5187": "EPSG:5187 — 동부원점 (2010)",
    "EPSG:5188": "EPSG:5188 — 동해원점 (2010)",
}

# Stable UI order: default first, then remaining codes.
COORDINATE_SYSTEM_OPTIONS: tuple[str, ...] = (
    "EPSG:5179",
    "EPSG:5181",
    "EPSG:5185",
    "EPSG:5186",
    "EPSG:5187",
    "EPSG:5188",
)


def is_allowed_coordinate_system(coordinate_system: str) -> bool:
    return coordinate_system in ALLOWED_COORDINATE_SYSTEMS
