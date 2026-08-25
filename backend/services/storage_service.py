from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path

from backend.config import Settings
from backend.exceptions import InsufficientStorageError


def create_temporary_path(settings: Settings) -> Path:
    settings.ensure_directories()
    return settings.temporary_root / f"{uuid.uuid4().hex}.part"


def ensure_chunk_can_be_stored(
    target_directory: Path, incoming_bytes: int, settings: Settings
) -> None:
    free_space = shutil.disk_usage(target_directory).free
    if free_space < incoming_bytes + settings.minimum_free_space:
        raise InsufficientStorageError(
            "파일을 저장할 디스크 공간이 부족합니다.",
            "insufficient_storage",
        )


def drawing_directory(drawing_id: str, settings: Settings) -> Path:
    return settings.storage_root / drawing_id


def finalize_source_file(
    temporary_path: Path,
    drawing_id: str,
    settings: Settings,
    *,
    source_name: str = "original.dwg",
) -> tuple[Path, Path]:
    directory = drawing_directory(drawing_id, settings)
    source_directory = directory / "source"
    source_directory.mkdir(parents=True, exist_ok=True)
    (directory / "converted").mkdir(parents=True, exist_ok=True)
    (directory / "preview").mkdir(parents=True, exist_ok=True)
    destination = source_directory / source_name
    os.replace(temporary_path, destination)
    return directory, destination


