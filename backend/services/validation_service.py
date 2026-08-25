from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import ezdxf

from backend.exceptions import InvalidDwgError


DWG_VERSIONS = {
    "AC1015": "AutoCAD 2000",
    "AC1018": "AutoCAD 2004",
    "AC1021": "AutoCAD 2007",
    "AC1024": "AutoCAD 2010",
    "AC1027": "AutoCAD 2013",
    "AC1032": "AutoCAD 2018",
}

ALLOWED_UPLOAD_EXTENSIONS = {".dwg", ".dxf"}


@dataclass(frozen=True)
class DwgValidationResult:
    header: str
    version: str


@dataclass(frozen=True)
class DxfUploadValidationResult:
    header: str
    version: str
    entity_count: int
    size_bytes: int


def normalize_filename(filename: str | None) -> str:
    if not filename:
        raise InvalidDwgError("파일명이 없습니다.", "missing_filename")
    normalized = filename.replace("\\", "/").split("/")[-1].strip()
    if not normalized:
        raise InvalidDwgError("파일명이 없습니다.", "missing_filename")
    suffix = Path(normalized).suffix.lower()
    if suffix not in ALLOWED_UPLOAD_EXTENSIONS:
        raise InvalidDwgError(
            "DWG 또는 DXF 파일만 업로드할 수 있습니다.", "invalid_extension"
        )
    return normalized


def source_extension(filename: str) -> str:
    return Path(filename).suffix.lower()


def validate_dwg_header(header_bytes: bytes) -> DwgValidationResult:
    if len(header_bytes) < 6:
        raise InvalidDwgError("파일 내용이 없거나 손상되었습니다.", "empty_file")
    header = header_bytes[:6].decode("ascii", errors="ignore")
    if len(header) != 6 or not header.startswith("AC") or not header[2:].isdigit():
        raise InvalidDwgError(
            "올바른 DWG 파일 헤더를 찾을 수 없습니다.", "invalid_dwg_header"
        )
    return DwgValidationResult(
        header=header,
        version=DWG_VERSIONS.get(header, f"알 수 없는 DWG 버전 ({header})"),
    )


def validate_dxf_upload(path: Path) -> DxfUploadValidationResult:
    if not path.is_file() or path.stat().st_size == 0:
        raise InvalidDwgError("파일 내용이 없거나 손상되었습니다.", "empty_file")
    try:
        document = ezdxf.readfile(path)
        entity_count = len(document.modelspace())
    except (OSError, ezdxf.DXFError) as exc:
        raise InvalidDwgError(
            "올바른 DXF 파일을 읽을 수 없습니다.", "invalid_dxf"
        ) from exc
    if entity_count == 0:
        raise InvalidDwgError(
            "DXF에 도면 객체가 없습니다.", "empty_dxf"
        )
    header = document.dxfversion
    version_label = DWG_VERSIONS.get(header, f"DXF ({header})")
    return DxfUploadValidationResult(
        header=header,
        version=version_label,
        entity_count=entity_count,
        size_bytes=path.stat().st_size,
    )
