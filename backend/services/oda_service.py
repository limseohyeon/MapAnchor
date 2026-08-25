from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from backend.config import Settings
from backend.exceptions import ConversionError


@dataclass(frozen=True)
class OdaConversionResult:
    success: bool
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float


def find_oda_converter(settings: Settings) -> Path | None:
    candidates: list[Path] = []
    if settings.oda_converter_path:
        candidates.append(settings.oda_converter_path)

    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data:
        oda_root = Path(local_app_data) / "Programs" / "ODA"
        if oda_root.exists():
            candidates.extend(
                sorted(
                    oda_root.glob("ODAFileConverter */ODAFileConverter.exe"),
                    reverse=True,
                )
            )

    for environment_name in ("ProgramFiles", "ProgramFiles(x86)"):
        program_files = os.getenv(environment_name)
        if program_files:
            oda_root = Path(program_files) / "ODA"
            if oda_root.exists():
                candidates.extend(
                    sorted(
                        oda_root.glob("ODAFileConverter */ODAFileConverter.exe"),
                        reverse=True,
                    )
                )

    path_command = shutil.which("ODAFileConverter.exe")
    if path_command:
        candidates.append(Path(path_command))

    return next((path for path in candidates if path.is_file()), None)


def converter_version(converter_path: Path) -> str:
    name = converter_path.parent.name
    prefix = "ODAFileConverter "
    return name[len(prefix) :] if name.startswith(prefix) else "unknown"


def run_oda_converter(
    converter_path: Path,
    source_directory: Path,
    output_directory: Path,
    settings: Settings,
) -> OdaConversionResult:
    output_directory.mkdir(parents=True, exist_ok=True)
    arguments = [
        str(converter_path),
        str(source_directory),
        str(output_directory),
        settings.dxf_output_version,
        "DXF",
        "0",
        "1",
        "*.dwg",
    ]
    creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    started = time.monotonic()
    try:
        completed = subprocess.run(
            arguments,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=settings.conversion_timeout_seconds,
            check=False,
            shell=False,
            creationflags=creation_flags,
        )
    except subprocess.TimeoutExpired as exc:
        raise ConversionError(
            "DXF 변환 제한 시간을 초과했습니다.", "conversion_timeout"
        ) from exc
    except OSError as exc:
        raise ConversionError(
            "ODA File Converter를 실행하지 못했습니다.", "oda_execution_failed"
        ) from exc

    duration = time.monotonic() - started
    return OdaConversionResult(
        success=completed.returncode == 0,
        exit_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        duration_seconds=duration,
    )

