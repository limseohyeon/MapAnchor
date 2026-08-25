from __future__ import annotations

import logging
from typing import Any, Callable, Protocol

import httpx

from backend.config import Settings, settings
from backend.exceptions import AddressSearchError
from backend.models.address import AddressSearchResponse, AddressSearchResult


LOGGER = logging.getLogger(__name__)

KAKAO_ADDRESS_SEARCH_URL = "https://dapi.kakao.com/v2/local/search/address.json"
KAKAO_KEYWORD_SEARCH_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"


class KakaoHttpResponse(Protocol):
    status_code: int
    text: str

    def json(self) -> Any: ...


KakaoHttpGet = Callable[[str, dict[str, str], dict[str, str], float], KakaoHttpResponse]


def _default_http_get(
    url: str,
    headers: dict[str, str],
    params: dict[str, str],
    timeout: float,
) -> KakaoHttpResponse:
    with httpx.Client(timeout=timeout) as client:
        return client.get(url, headers=headers, params=params)


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_kakao_address_document(
    document: dict[str, Any],
) -> AddressSearchResult | None:
    try:
        longitude = float(document["x"])
        latitude = float(document["y"])
    except (KeyError, TypeError, ValueError):
        return None

    road = document.get("road_address") or {}
    jibun = document.get("address") or {}
    road_address = (
        _optional_text(road.get("address_name")) if isinstance(road, dict) else None
    )
    jibun_address = (
        _optional_text(jibun.get("address_name")) if isinstance(jibun, dict) else None
    )
    display_name = (
        road_address
        or jibun_address
        or _optional_text(document.get("address_name"))
    )
    if display_name is None:
        return None

    return AddressSearchResult(
        display_name=display_name,
        road_address=road_address,
        jibun_address=jibun_address,
        longitude=longitude,
        latitude=latitude,
    )


def _parse_kakao_keyword_document(
    document: dict[str, Any],
) -> AddressSearchResult | None:
    try:
        longitude = float(document["x"])
        latitude = float(document["y"])
    except (KeyError, TypeError, ValueError):
        return None

    place_name = _optional_text(document.get("place_name"))
    road_address = _optional_text(document.get("road_address_name"))
    jibun_address = _optional_text(document.get("address_name"))
    if place_name and (road_address or jibun_address):
        display_name = f"{place_name} ({road_address or jibun_address})"
    else:
        display_name = place_name or road_address or jibun_address
    if display_name is None:
        return None

    return AddressSearchResult(
        display_name=display_name,
        road_address=road_address,
        jibun_address=jibun_address,
        longitude=longitude,
        latitude=latitude,
    )


class AddressSearchService:
    def __init__(
        self,
        app_settings: Settings | None = None,
        http_get: KakaoHttpGet | None = None,
    ) -> None:
        self.settings = app_settings or settings
        self.http_get = http_get or _default_http_get

    def search(self, query: str) -> AddressSearchResponse:
        cleaned = query.strip()
        if not cleaned:
            raise AddressSearchError(
                "검색할 주소를 입력해 주세요.",
                "empty_address_query",
                status_code=422,
            )

        api_key = self.settings.kakao_rest_api_key
        if not api_key:
            raise AddressSearchError(
                "주소 검색 API 키가 설정되지 않았습니다.",
                "address_api_not_configured",
                status_code=503,
            )

        size = max(1, min(self.settings.address_search_size, 30))
        headers = {"Authorization": f"KakaoAK {api_key}"}
        params = {"query": cleaned, "size": str(size)}

        address_docs = self._fetch_documents(
            KAKAO_ADDRESS_SEARCH_URL, headers, params
        )
        results = self._parse_documents(address_docs, _parse_kakao_address_document)
        if results:
            return AddressSearchResponse(query=cleaned, results=results)

        # Place names like "충북도청" are not formal addresses; use keyword search.
        keyword_docs = self._fetch_documents(
            KAKAO_KEYWORD_SEARCH_URL, headers, params
        )
        results = self._parse_documents(keyword_docs, _parse_kakao_keyword_document)
        return AddressSearchResponse(query=cleaned, results=results)

    def _fetch_documents(
        self,
        url: str,
        headers: dict[str, str],
        params: dict[str, str],
    ) -> list[Any]:
        try:
            response = self.http_get(
                url,
                headers,
                params,
                self.settings.address_search_timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            LOGGER.warning("Kakao search timed out (%s): %s", url, exc)
            raise AddressSearchError(
                "주소 검색 응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요.",
                "address_api_timeout",
                status_code=504,
            ) from exc
        except httpx.HTTPError as exc:
            LOGGER.warning("Kakao search request failed (%s): %s", url, exc)
            raise AddressSearchError(
                "주소 검색 서비스에 연결하지 못했습니다.",
                "address_api_unreachable",
                status_code=502,
            ) from exc

        if response.status_code >= 400:
            kakao_message = ""
            try:
                error_payload = response.json()
                if isinstance(error_payload, dict):
                    kakao_message = str(error_payload.get("message") or "").strip()
            except ValueError:
                kakao_message = ""
            LOGGER.warning(
                "Kakao search returned HTTP %s (%s): %s",
                response.status_code,
                url,
                kakao_message or response.text[:200],
            )
            if response.status_code in {401, 403}:
                raise AddressSearchError(
                    "카카오 주소 검색 권한이 없습니다. "
                    "카카오 디벨로퍼스에서 앱의 카카오맵/로컬(Local) API를 활성화하고 "
                    "REST API 키를 확인해 주세요.",
                    "address_api_unauthorized",
                    status_code=502,
                )
            raise AddressSearchError(
                "주소 검색에 실패했습니다.",
                "address_api_failed",
                status_code=502,
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise AddressSearchError(
                "주소 검색 응답을 해석하지 못했습니다.",
                "address_api_invalid_response",
                status_code=502,
            ) from exc

        documents = payload.get("documents") if isinstance(payload, dict) else None
        if not isinstance(documents, list):
            raise AddressSearchError(
                "주소 검색 응답 형식이 올바르지 않습니다.",
                "address_api_invalid_response",
                status_code=502,
            )
        return documents

    @staticmethod
    def _parse_documents(
        documents: list[Any],
        parser: Callable[[dict[str, Any]], AddressSearchResult | None],
    ) -> list[AddressSearchResult]:
        results: list[AddressSearchResult] = []
        for document in documents:
            if not isinstance(document, dict):
                continue
            parsed = parser(document)
            if parsed is not None:
                results.append(parsed)
        return results


address_search_service = AddressSearchService()
