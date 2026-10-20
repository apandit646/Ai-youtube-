"""FastAPI application factory."""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1 import analytics, auth, content, jobs, publishing, research, settings, system, videos, youtube
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.logging import configure_logging
from app.services.llm.base import LLMUnavailableError
from app.services.youtube.client import YouTubeAPIError, YouTubeAuthError, YouTubeQuotaError

log = logging.getLogger("api")


def create_app() -> FastAPI:
    s = get_settings()
    configure_logging(s.log_level)
    s.media_root.mkdir(parents=True, exist_ok=True)
    if s.is_production and s.secret_key.startswith("change-me"):
        raise RuntimeError("SECRET_KEY must be set in production")
    app = FastAPI(
        title=f"{s.app_name} API",
        version="1.0.0",
        description="Automation platform for original Hindi & English kids' rhyme videos. Multi-model AI (Grok, "
                    "ChatGPT, Gemini), FFmpeg rendering and official YouTube APIs.",
        openapi_url="/api/v1/openapi.json",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
    )
    app.add_middleware(CORSMiddleware, allow_origins=s.cors_origin_list, allow_credentials=False,
                       allow_methods=["GET", "POST", "PUT", "DELETE"], allow_headers=["Authorization", "Content-Type"])

    @app.exception_handler(AppError)
    async def app_error(_: Request, exc: AppError):
        return JSONResponse(status_code=exc.status_code,
                            content={"error": exc.code, "detail": exc.message, "details": exc.details})

    @app.exception_handler(LLMUnavailableError)
    async def llm_error(_: Request, exc: LLMUnavailableError):
        return JSONResponse(status_code=503, content={"error": "ai_unavailable", "detail": str(exc),
                                                      "details": {"attempts": exc.attempts}})

    @app.exception_handler(YouTubeAPIError)
    async def yt_error(_: Request, exc: YouTubeAPIError):
        code = 429 if isinstance(exc, YouTubeQuotaError) else 401 if isinstance(exc, YouTubeAuthError) else 502
        return JSONResponse(status_code=code, content={"error": "youtube_error", "detail": str(exc),
                                                       "details": {"reason": exc.reason}})

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        errors = [{"loc": e["loc"], "msg": e["msg"]} for e in exc.errors()]
        return JSONResponse(status_code=422, content={"error": "validation_error", "detail": "Invalid request",
                                                      "details": {"errors": errors}})

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception):
        log.exception("Unhandled error")
        return JSONResponse(status_code=500, content={"error": "internal_error", "detail": "Internal server error"})

    for r in (system.router, auth.router, settings.router, youtube.router, research.router, content.router,
              videos.router, jobs.router, publishing.router, analytics.router):
        app.include_router(r, prefix="/api/v1")
    return app


app = create_app()
