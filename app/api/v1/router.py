from fastapi import APIRouter

from app.api.v1.endpoints.gmail import router as gmail_router
from app.api.v1.endpoints.siniestros import router as siniestros_router
from app.api.v1.endpoints.webhooks import router as webhooks_router

api_router = APIRouter()
api_router.include_router(siniestros_router)
api_router.include_router(gmail_router)
api_router.include_router(webhooks_router)
