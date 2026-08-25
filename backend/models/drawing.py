from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class DrawingMetadata(BaseModel):
    drawing_id: str
    original_filename: str
    aliases: list[str] = Field(default_factory=list)
    sha256: str
    size_bytes: int
    dwg_header: str
    dwg_version: str
    coordinate_system: str
    drawing_unit: str = "millimeter"
    coordinate_scale: int = 1000
    unit_source: str = "default"
    unit_detection: str | None = None
    upload_status: str
    conversion_status: str
    source_path: str
    dxf_path: str | None = None
    dxf_size_bytes: int | None = None
    dxf_version: str | None = None
    dxf_entity_count: int | None = None
    preview_path: str | None = None
    preview_width: int | None = None
    preview_height: int | None = None
    preview_source_hash: str | None = None
    preview_status: str = "idle"
    preview_quality: str = "none"
    preview_error: str | None = None
    preview_phase: str | None = None
    preview_progress: int | None = None
    preview_started_at: datetime | None = None
    prepare_status: str = "idle"
    prepare_source_hash: str | None = None
    prepare_error: str | None = None
    extents_source: str | None = None
    extents_min_x: float | None = None
    extents_min_y: float | None = None
    extents_max_x: float | None = None
    extents_max_y: float | None = None
    conversion_error: str | None = None
    conversion_started_at: datetime | None = None
    converted_at: datetime | None = None
    conversion_duration_seconds: float | None = None
    converter_name: str | None = None
    converter_version: str | None = None
    uploaded_at: datetime
    updated_at: datetime


class DrawingUploadResponse(BaseModel):
    drawing: DrawingMetadata
    duplicate: bool
    message: str


class DrawingDeleteResponse(BaseModel):
    drawing_id: str
    message: str


class HealthResponse(BaseModel):
    status: str


class ConversionRequest(BaseModel):
    force: bool = False


class ConversionResponse(BaseModel):
    drawing: DrawingMetadata
    started: bool
    message: str


class PreviewRequest(BaseModel):
    """Legacy request body; prepare endpoint accepts the same shape."""

    force: bool = False


class PrepareRequest(BaseModel):
    force: bool = False


class PrepareInfoResponse(BaseModel):
    drawing: DrawingMetadata
    prepared: bool
    message: str


class PreviewInfoResponse(BaseModel):
    """Kept for older clients; prefer PrepareInfoResponse."""

    drawing: DrawingMetadata
    generated: bool
    started: bool = False
    message: str
    image_url: str = ""
