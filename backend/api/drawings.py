from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, File, Request, UploadFile
from fastapi.responses import FileResponse, Response

from backend.exceptions import ConversionInProgressError, DrawingNotFoundError
from backend.models.drawing import (
    ConversionRequest,
    ConversionResponse,
    DrawingDeleteResponse,
    DrawingMetadata,
    DrawingUploadResponse,
    PrepareInfoResponse,
    PrepareRequest,
)
from backend.models.coordinate import (
    CoordinateConvertRequest,
    CoordinateConvertResponse,
    CoordinateFromDrawingRequest,
    CoordinateFromDrawingResponse,
    CoordinateSettingsRequest,
    CoordinateSettingsResponse,
)
from backend.services.conversion_service import ACTIVE_STATUSES, conversion_service
from backend.services.coordinate_service import coordinate_service
from backend.services.dxf_delivery import (
    client_accepts_gzip,
    dxf_cache_headers,
    dxf_gzip_path,
    gzip_is_fresh,
)
from backend.services.prepare_service import dxf_fingerprint, prepare_service
from backend.services.upload_service import upload_service


router = APIRouter(prefix="/api/drawings", tags=["drawings"])


def _queue_conversion_after_upload(
    response: DrawingUploadResponse,
    background_tasks: BackgroundTasks,
) -> DrawingUploadResponse:
    drawing = response.drawing
    if drawing.conversion_status == "completed":
        background_tasks.add_task(_prepare_then_gzip, drawing.drawing_id)
        return response
    if drawing.conversion_status in ACTIVE_STATUSES:
        return response
    try:
        conversion = conversion_service.queue(drawing.drawing_id, force=False)
    except ConversionInProgressError:
        return response
    if conversion.started:
        background_tasks.add_task(
            _convert_then_prepare, drawing.drawing_id
        )
    return DrawingUploadResponse(
        drawing=conversion.drawing,
        duplicate=response.duplicate,
        message=response.message,
    )


def _prepare_then_gzip(drawing_id: str, *, force: bool = False) -> None:
    prepare_service.prepare(drawing_id, force=force)
    prepare_service.ensure_gzip_cache(drawing_id)


def _convert_then_prepare(drawing_id: str) -> None:
    conversion_service.convert(drawing_id)
    try:
        _prepare_then_gzip(drawing_id)
    except Exception:
        import logging

        logging.getLogger(__name__).exception(
            "Prepare failed after conversion for %s", drawing_id
        )


@router.post("", response_model=DrawingUploadResponse)
async def upload_drawing(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
) -> DrawingUploadResponse:
    response = await upload_service.save(file)
    return _queue_conversion_after_upload(response, background_tasks)


@router.get("", response_model=list[DrawingMetadata])
def list_drawings() -> list[DrawingMetadata]:
    return upload_service.list_drawings()


@router.get("/{drawing_id}", response_model=DrawingMetadata)
def get_drawing(drawing_id: str) -> DrawingMetadata:
    drawing = upload_service.get_drawing(drawing_id)
    if drawing is None:
        raise DrawingNotFoundError(
            "등록된 도면을 찾을 수 없습니다.", "drawing_not_found"
        )
    return drawing


@router.delete("/{drawing_id}", response_model=DrawingDeleteResponse)
def delete_drawing(drawing_id: str) -> DrawingDeleteResponse:
    return upload_service.delete(drawing_id)


@router.post("/{drawing_id}/convert", response_model=ConversionResponse)
def convert_drawing(
    drawing_id: str,
    request: ConversionRequest,
    background_tasks: BackgroundTasks,
) -> ConversionResponse:
    response = conversion_service.queue(drawing_id, force=request.force)
    if response.started:
        background_tasks.add_task(_convert_then_prepare, drawing_id)
    return response


@router.get("/{drawing_id}/conversion", response_model=DrawingMetadata)
def get_conversion_status(drawing_id: str) -> DrawingMetadata:
    return conversion_service.get_status(drawing_id)


@router.post("/{drawing_id}/prepare", response_model=PrepareInfoResponse)
def prepare_drawing(
    drawing_id: str,
    request: PrepareRequest,
    background_tasks: BackgroundTasks,
    wait: bool = False,
) -> PrepareInfoResponse:
    """Prepare drawing extents.

    Default (wait=false): queue work in the background and return status quickly
    so the UI can show the DXF viewer without blocking. Tests/tools may pass
    wait=true for synchronous completion.
    """
    if wait or request.force:
        # force still runs immediately so callers get a definitive result.
        if not wait and request.force:
            background_tasks.add_task(
                _prepare_then_gzip, drawing_id, force=True
            )
            info = prepare_service.begin_prepare(drawing_id, force=True)
            return info
        response = prepare_service.prepare(drawing_id, force=request.force)
        background_tasks.add_task(prepare_service.ensure_gzip_cache, drawing_id)
        return response

    info = prepare_service.get_prepare_info(drawing_id)
    if info.prepared:
        background_tasks.add_task(prepare_service.ensure_gzip_cache, drawing_id)
        return info

    started = prepare_service.begin_prepare(drawing_id, force=False)
    if started.drawing.prepare_status == "preparing":
        background_tasks.add_task(_prepare_then_gzip, drawing_id, force=False)
    return started


@router.get("/{drawing_id}/prepare", response_model=PrepareInfoResponse)
def get_prepare_info(drawing_id: str) -> PrepareInfoResponse:
    return prepare_service.get_prepare_info(drawing_id)


@router.get("/{drawing_id}/dxf")
def get_drawing_dxf(
    drawing_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    v: str | None = None,
) -> Response:
    path = prepare_service.get_dxf_file(drawing_id)
    fingerprint = dxf_fingerprint(path)
    etag = f'"{fingerprint}"'
    if_none_match = request.headers.get("if-none-match")
    if if_none_match and if_none_match.strip() == etag:
        headers = dxf_cache_headers(
            fingerprint=fingerprint,
            version_token=v,
        )
        return Response(status_code=304, headers=headers)

    accept_encoding = request.headers.get("accept-encoding")
    use_gzip = client_accepts_gzip(accept_encoding)
    gz_path = dxf_gzip_path(path)
    if use_gzip and gzip_is_fresh(path, gz_path):
        headers = dxf_cache_headers(
            fingerprint=fingerprint,
            version_token=v,
            content_encoding="gzip",
        )
        return FileResponse(
            gz_path,
            media_type="application/dxf",
            filename="drawing.dxf",
            headers=headers,
        )

    if use_gzip and not gzip_is_fresh(path, gz_path):
        background_tasks.add_task(prepare_service.ensure_gzip_cache, drawing_id)

    headers = dxf_cache_headers(
        fingerprint=fingerprint,
        version_token=v,
    )
    return FileResponse(
        path,
        media_type="application/dxf",
        filename="drawing.dxf",
        headers=headers,
    )


@router.patch(
    "/{drawing_id}/coordinate-settings",
    response_model=CoordinateSettingsResponse,
)
def update_coordinate_settings(
    drawing_id: str, request: CoordinateSettingsRequest
) -> CoordinateSettingsResponse:
    return coordinate_service.update_coordinate_settings(drawing_id, request)


@router.post(
    "/{drawing_id}/coordinates/convert",
    response_model=CoordinateConvertResponse,
)
def convert_coordinates(
    drawing_id: str, request: CoordinateConvertRequest
) -> CoordinateConvertResponse:
    return coordinate_service.convert(drawing_id, request)


@router.post(
    "/{drawing_id}/coordinates/from-drawing",
    response_model=CoordinateFromDrawingResponse,
)
def coordinates_from_drawing(
    drawing_id: str, request: CoordinateFromDrawingRequest
) -> CoordinateFromDrawingResponse:
    return coordinate_service.from_drawing(drawing_id, request)
