from __future__ import annotations

from pydantic import BaseModel, Field


class AddressSearchResult(BaseModel):
    display_name: str
    road_address: str | None = None
    jibun_address: str | None = None
    longitude: float
    latitude: float


class AddressSearchResponse(BaseModel):
    query: str
    results: list[AddressSearchResult] = Field(default_factory=list)
