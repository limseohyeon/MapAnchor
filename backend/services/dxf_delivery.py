from __future__ import annotations

import gzip
import logging
import os
import shutil
from pathlib import Path


LOGGER = logging.getLogger(__name__)
DXF_CACHE_CONTROL_IMMUTABLE = "public, max-age=31536000, immutable"
DXF_CACHE_CONTROL_REVALIDATE = "public, max-age=0, must-revalidate"


def dxf_gzip_path(dxf_path: Path) -> Path:
    return Path(f"{dxf_path}.gz")


def gzip_is_fresh(dxf_path: Path, gz_path: Path | None = None) -> bool:
    target = gz_path or dxf_gzip_path(dxf_path)
    if not dxf_path.is_file() or not target.is_file():
        return False
    dxf_stat = dxf_path.stat()
    gz_stat = target.stat()
    return gz_stat.st_size > 0 and gz_stat.st_mtime_ns >= dxf_stat.st_mtime_ns


def ensure_dxf_gzip(dxf_path: Path, *, compresslevel: int = 6) -> Path:
    """Create drawing.dxf.gz next to the DXF without changing DXF contents.

    Uses atomic replace. Reuses an existing gzip when it is newer than the DXF.
    """
    if not dxf_path.is_file():
        raise FileNotFoundError(str(dxf_path))

    gz_path = dxf_gzip_path(dxf_path)
    if gzip_is_fresh(dxf_path, gz_path):
        return gz_path

    gz_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = gz_path.with_name(f"{gz_path.name}.{os.getpid()}.part")
    try:
        with dxf_path.open("rb") as source:
            with gzip.open(tmp_path, "wb", compresslevel=compresslevel) as target:
                shutil.copyfileobj(source, target, length=1024 * 1024)
        os.replace(tmp_path, gz_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
    LOGGER.info(
        "Created DXF gzip cache path=%s bytes=%s",
        gz_path,
        gz_path.stat().st_size,
    )
    return gz_path


def client_accepts_gzip(accept_encoding: str | None) -> bool:
    if not accept_encoding:
        return False
    return "gzip" in accept_encoding.lower()


def dxf_cache_headers(
    *,
    fingerprint: str,
    version_token: str | None,
    content_encoding: str | None = None,
) -> dict[str, str]:
    """Build cache headers for DXF delivery.

    When the client URL version token matches the file fingerprint, browsers may
    keep the response indefinitely. Content is never altered—only transport.
    """
    etag = f'"{fingerprint}"'
    if version_token and version_token == fingerprint:
        cache_control = DXF_CACHE_CONTROL_IMMUTABLE
    else:
        cache_control = DXF_CACHE_CONTROL_REVALIDATE
    headers = {
        "Cache-Control": cache_control,
        "ETag": etag,
        "Vary": "Accept-Encoding",
    }
    if content_encoding:
        headers["Content-Encoding"] = content_encoding
    return headers
