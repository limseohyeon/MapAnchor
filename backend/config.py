from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_env_file(path: Path | None = None) -> None:
    """Load KEY=VALUE pairs from a local .env file into os.environ.

    Default path is the relative `.env` in the process working directory
    (project root when started via run scripts). Absolute machine paths are
    not used. Existing environment variables are not overwritten.
    """
    env_path = path if path is not None else Path(".env")
    if not env_path.is_file():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key or key in os.environ:
            continue
        cleaned = value.strip()
        if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {'"', "'"}:
            cleaned = cleaned[1:-1]
        os.environ[key] = cleaned


load_env_file()


@dataclass(frozen=True)
class Settings:
    storage_root: Path = Path(
        os.getenv("DWG_STORAGE_ROOT", PROJECT_ROOT / "data" / "drawings")
    )
    temporary_root: Path = Path(
        os.getenv("DWG_TEMP_ROOT", PROJECT_ROOT / "data" / "temporary")
    )
    chunk_size: int = int(os.getenv("DWG_UPLOAD_CHUNK_SIZE", 8 * 1024 * 1024))
    minimum_free_space: int = int(
        os.getenv("DWG_MINIMUM_FREE_SPACE", 128 * 1024 * 1024)
    )
    coordinate_system: str = os.getenv("DWG_COORDINATE_SYSTEM", "EPSG:5179")
    drawing_unit: str = "millimeter"
    coordinate_scale: int = 1000
    oda_converter_path: Path | None = (
        Path(os.environ["ODA_FILE_CONVERTER_PATH"])
        if os.getenv("ODA_FILE_CONVERTER_PATH")
        else None
    )
    conversion_timeout_seconds: int = int(
        os.getenv("DWG_CONVERSION_TIMEOUT", 30 * 60)
    )
    conversion_space_multiplier: int = int(
        os.getenv("DWG_CONVERSION_SPACE_MULTIPLIER", 6)
    )
    dxf_output_version: str = os.getenv("DWG_DXF_VERSION", "ACAD2018")
    preview_max_edge_px: int = int(os.getenv("DWG_PREVIEW_MAX_EDGE", 2048))
    preview_draft_max_edge_px: int = int(
        os.getenv("DWG_PREVIEW_DRAFT_MAX_EDGE", 1024)
    )
    preview_dpi: int = int(os.getenv("DWG_PREVIEW_DPI", 100))
    preview_simplify: bool = os.getenv("DWG_PREVIEW_SIMPLIFY", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }
    # When true, continue draft→final unless DXF exceeds preview_auto_final_max_mb.
    preview_auto_final: bool = os.getenv("DWG_PREVIEW_AUTO_FINAL", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }
    preview_auto_final_max_mb: int = int(
        os.getenv("DWG_PREVIEW_AUTO_FINAL_MAX_MB", "80")
    )
    # Negative disables the size cap. Zero skips final for any non-empty DXF.
    preview_draft_skip_text: bool = os.getenv(
        "DWG_PREVIEW_DRAFT_SKIP_TEXT", "1"
    ).strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }
    # Exclude HATCH/IMAGE/OLE/WIPEOUT from extents (same types skipped at draw).
    preview_extents_skip_heavy: bool = os.getenv(
        "DWG_PREVIEW_EXTENTS_SKIP_HEAVY", "1"
    ).strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }
    # Overview visibility: min stroke + limited supersample for sparse/wide maps.
    preview_visibility_boost: bool = os.getenv(
        "DWG_PREVIEW_VISIBILITY_BOOST", "1"
    ).strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }
    # Trigger boost when drawing units per display pixel exceed this value.
    preview_visibility_units_per_px: float = float(
        os.getenv("DWG_PREVIEW_VISIBILITY_UNITS_PER_PX", "30")
    )
    # Internal render scale (2–4). 1 disables supersample while boost can still
    # thicken strokes.
    preview_supersample: int = int(os.getenv("DWG_PREVIEW_SUPERSAMPLE", "4"))
    preview_supersample_max_edge_px: int = int(
        os.getenv("DWG_PREVIEW_SUPERSAMPLE_MAX_EDGE", "8192")
    )
    # ezdxf Configuration.min_lineweight (1/300 inch); matplotlib treats it as
    # approximate point width. None keeps backend defaults unless boost applies.
    preview_min_lineweight: float | None = (
        float(os.environ["DWG_PREVIEW_MIN_LINEWEIGHT"])
        if os.getenv("DWG_PREVIEW_MIN_LINEWEIGHT", "").strip()
        else None
    )
    kakao_rest_api_key: str | None = (
        os.getenv("KAKAO_REST_API_KEY", "").strip() or None
    )
    address_search_timeout_seconds: float = float(
        os.getenv("DWG_ADDRESS_SEARCH_TIMEOUT", "10")
    )
    address_search_size: int = int(os.getenv("DWG_ADDRESS_SEARCH_SIZE", "10"))
    # Above this DXF size, prepare skips full ezdxf.readfile unless force=true
    # after header/stream extents both fail (avoids multi-minute hangs).
    extents_computed_max_bytes: int = int(
        os.getenv("DWG_EXTENTS_COMPUTED_MAX_BYTES", str(80 * 1024 * 1024))
    )

    def ensure_directories(self) -> None:
        self.storage_root.mkdir(parents=True, exist_ok=True)
        self.temporary_root.mkdir(parents=True, exist_ok=True)

    @property
    def conversion_temporary_root(self) -> Path:
        return self.temporary_root / "conversion"


settings = Settings()
