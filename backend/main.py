from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from backend.api.addresses import router as addresses_router
from backend.api.drawings import router as drawings_router
from backend.config import PROJECT_ROOT, settings
from backend.exceptions import DrawingError
from backend.models.drawing import HealthResponse
from backend.services.conversion_service import conversion_service
from backend.services.prepare_service import prepare_service


logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

STATIC_DIR = PROJECT_ROOT / "frontend" / "static"


class StaticCacheMiddleware(BaseHTTPMiddleware):
    """Long-cache hashed static assets (viewer bundle). Content itself is versioned via ?v=."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        path = request.url.path
        if path.startswith("/static/") and response.status_code == 200:
            if request.query_params.get("v"):
                response.headers["Cache-Control"] = (
                    "public, max-age=31536000, immutable"
                )
            else:
                response.headers.setdefault(
                    "Cache-Control", "public, max-age=3600"
                )
        return response


app = FastAPI(title="DWG Map API", version="0.1.0")
app.add_middleware(StaticCacheMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["*"],
    expose_headers=["ETag", "Content-Encoding", "Cache-Control"],
)
app.include_router(drawings_router)
app.include_router(addresses_router)

STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount(
    "/static",
    StaticFiles(directory=str(STATIC_DIR)),
    name="static",
)


@app.on_event("startup")
def prepare_storage() -> None:
    settings.ensure_directories()
    conversion_service.recover_interrupted_conversions()
    prepare_service.recover_interrupted_prepares()


@app.exception_handler(DrawingError)
async def handle_drawing_error(
    request: Request, exc: DrawingError
) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.message, "code": exc.code},
    )


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")
