"""Health check endpoint for PREDIX API."""

from fastapi import APIRouter
from app.core.config import settings

router = APIRouter()


@router.get("/health", tags=["System"])
async def health_check() -> dict:
    """
    Returns the current health status of the PREDIX backend service.
    """
    return {
        "status": "online",
        "service": settings.SERVICE_NAME,
        "version": settings.SERVICE_VERSION,
    }
