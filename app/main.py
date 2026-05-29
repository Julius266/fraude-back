import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from googleapiclient.errors import HttpError

from app.api.v1.router import api_router
from app.core.bootstrap import bootstrap_runtime_files
from app.core.config import get_settings
from app.core.exceptions import http_error_handler, unhandled_exception_handler
from app.core.logging_config import setup_logging

bootstrap_runtime_files()
settings = get_settings()
setup_logging()
logger = logging.getLogger(__name__)

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="API de detección de fraude en siniestros (Gmail, scoring, webhooks).",
    docs_url="/swagger",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    swagger_ui_parameters={
        "persistAuthorization": True,
        "displayRequestDuration": True,
        "filter": True,
    },
)

_cors_kwargs: dict[str, object] = {
    "allow_credentials": True,
    "allow_methods": ["*"],
    "allow_headers": ["*"],
    "allow_origins": settings.allowed_origins_list,
}
if _cors_regex := settings.cors_origin_regex_pattern:
    _cors_kwargs["allow_origin_regex"] = _cors_regex
    logger.info("CORS regex activo: %s", _cors_regex)

app.add_middleware(CORSMiddleware, **_cors_kwargs)

app.add_exception_handler(HttpError, http_error_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

app.include_router(api_router, prefix=settings.api_v1_str)


@app.on_event("startup")
def on_startup() -> None:
    base_url = settings.resolved_app_base_url
    logger.info("API lista: %s", base_url)
    logger.info("Swagger: %s/swagger", base_url)
    logger.info("ReDoc: %s/redoc", base_url)
    logger.info("OpenAPI JSON: %s/openapi.json", base_url)
    logger.info("Health: %s/health", base_url)
    logger.info("Base API v1: %s%s", base_url, settings.api_v1_str)


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/swagger")


@app.get("/health", tags=["Sistema"])
def health() -> dict[str, str]:
    return {"status": "ok", "app": settings.app_name}
