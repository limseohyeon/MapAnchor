from __future__ import annotations

from fastapi import APIRouter, Query

from backend.models.address import AddressSearchResponse
from backend.services.address_service import address_search_service


router = APIRouter(prefix="/api/addresses", tags=["addresses"])


@router.get("/search", response_model=AddressSearchResponse)
def search_addresses(
    query: str = Query(..., min_length=1, description="도로명 또는 지번 주소"),
) -> AddressSearchResponse:
    return address_search_service.search(query)
