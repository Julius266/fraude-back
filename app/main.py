import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import engine

settings = get_settings()

logger = logging.getLogger("uvicorn")
base_url = os.getenv("APP_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.app_env == "development" and settings.enable_schema_sync:
        logger.warning("DB schema sync enabled (development only).")
        Base.metadata.create_all(bind=engine)

    logger.info("Swagger UI: %s/docs", base_url)
    logger.info("OpenAPI JSON: %s/openapi.json", base_url)
    logger.info("ReDoc: %s/redoc", base_url)
    yield


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)
app.include_router(api_router, prefix=settings.api_v1_str)


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "fraude-back listo"}
