from __future__ import annotations

import json
import os
from pathlib import Path

from backend.exceptions import MetadataError
from backend.models.drawing import DrawingMetadata


def metadata_path(drawing_directory: Path) -> Path:
    return drawing_directory / "metadata.json"


def load_metadata(drawing_directory: Path) -> DrawingMetadata:
    path = metadata_path(drawing_directory)
    try:
        return DrawingMetadata.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise MetadataError(
            f"도면 메타데이터를 읽지 못했습니다: {drawing_directory.name}",
            "metadata_read_failed",
        ) from exc


def write_metadata_atomic(
    drawing_directory: Path, metadata: DrawingMetadata
) -> None:
    path = metadata_path(drawing_directory)
    temporary_path = path.with_suffix(".json.tmp")
    payload = json.dumps(
        metadata.model_dump(mode="json"), ensure_ascii=False, indent=2
    )
    try:
        temporary_path.write_text(payload, encoding="utf-8")
        os.replace(temporary_path, path)
    except OSError as exc:
        temporary_path.unlink(missing_ok=True)
        raise MetadataError(
            "도면 메타데이터를 저장하지 못했습니다.",
            "metadata_write_failed",
        ) from exc
