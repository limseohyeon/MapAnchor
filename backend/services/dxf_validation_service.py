from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import ezdxf

from backend.exceptions import ConversionError


@dataclass(frozen=True)
class DxfValidationResult:
    version: str
    entity_count: int
    size_bytes: int


def validate_dxf(path: Path) -> DxfValidationResult:
    if not path.is_file() or path.stat().st_size == 0:
        raise ConversionError(
            "DXF 변환 결과 파일이 생성되지 않았습니다.", "dxf_not_created"
        )
    try:
        document = ezdxf.readfile(path)
        entity_count = len(document.modelspace())
    except (OSError, ezdxf.DXFError) as exc:
        raise ConversionError(
            "생성된 DXF 파일을 읽을 수 없습니다.", "invalid_dxf"
        ) from exc
    if entity_count == 0:
        raise ConversionError(
            "생성된 DXF에 도면 객체가 없습니다.", "empty_dxf"
        )
    return DxfValidationResult(
        version=document.dxfversion,
        entity_count=entity_count,
        size_bytes=path.stat().st_size,
    )
