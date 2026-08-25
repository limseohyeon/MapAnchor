from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from backend.models.drawing import DrawingMetadata


class CoordinateConvertRequest(BaseModel):
    longitude: float = Field(..., description="EPSG:4326 longitude")
    latitude: float = Field(..., description="EPSG:4326 latitude")
    display_name: str | None = None


class CoordinateConvertResponse(BaseModel):
    display_name: str | None = None
    longitude: float
    latitude: float
    coordinate_system: str
    x_m: float
    y_m: float
    x_mm: float
    y_mm: float
    in_bounds: bool
    message: str


class CoordinateSettingsRequest(BaseModel):
    coordinate_system: str | None = Field(
        default=None, description="Drawing CRS, e.g. EPSG:5179"
    )
    coordinate_scale: int | None = Field(
        default=None, description="Drawing unit scale: 1 (meter) or 1000 (millimeter)"
    )

    @model_validator(mode="after")
    def require_at_least_one_setting(self) -> CoordinateSettingsRequest:
        if self.coordinate_system is None and self.coordinate_scale is None:
            raise ValueError(
                "coordinate_system 또는 coordinate_scale 중 하나는 필요합니다."
            )
        return self


class CoordinateSettingsResponse(BaseModel):
    drawing: DrawingMetadata
    message: str
    changed: bool


class CoordinateFromDrawingRequest(BaseModel):
    x_mm: float = Field(..., description="Drawing X in model units (mm scale applied)")
    y_mm: float = Field(..., description="Drawing Y in model units (mm scale applied)")


class CoordinateFromDrawingResponse(BaseModel):
    coordinate_system: str
    x_m: float
    y_m: float
    x_mm: float
    y_mm: float
    in_bounds: bool
    message: str
