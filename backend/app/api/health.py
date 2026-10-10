"""Health check endpoint for PREDIX API."""

from fastapi import APIRouter
import logging
import cv2
import sys
from pathlib import Path
from app.core.config import settings
from app.core.resource_metrics import process_resource_metrics
from app.cv.config import cv_settings
from app.cv.runtime import get_detector
from app.database.instance import repository
from app.api.live import get_live_status

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/health", tags=["System"])
async def health_check() -> dict:
    """
    Returns the current health status of the PREDIX backend service.
    """
    components = {
        "backend": {"status": "ONLINE"},
        "database": {"status": "ONLINE"},
        "ai_engine": {"status": "ONLINE", "model": cv_settings.MODEL_NAME, "model_state": "NOT_LOADED"},
        "video_engine": {"status": "ONLINE", "opencv_version": cv2.__version__},
        "live_stream_engine": {"status": "ONLINE", "stream_status": get_live_status().get("status", "offline").upper()},
    }
    try:
        if not repository.health_check():
            raise RuntimeError("Database health query returned an unexpected result.")
    except Exception:
        logger.exception("Health probe could not reach the configured database")
        components["database"] = {"status": "OFFLINE"}
    device = None
    detector = None
    try:
        detector = get_detector()
        device = detector.device
        components["ai_engine"] = {
            "status": "ONLINE",
            "model": detector.model_name,
            "model_state": "READY" if detector._model is not None else "NOT_LOADED",
            "device": detector.device,
        }
    except Exception:
        logger.exception("Health probe could not initialize the configured AI engine")
        components["ai_engine"] = {"status": "DEGRADED", "model": cv_settings.MODEL_NAME, "model_state": "UNAVAILABLE"}

    model_name = detector.model_name if detector is not None else cv_settings.MODEL_NAME
    configured_model = Path(model_name).expanduser()
    if not configured_model.is_absolute():
        configured_model = Path(__file__).resolve().parents[2] / configured_model
    if detector is not None and detector._model is not None:
        model_component = {
            "status": "ONLINE",
            "model": model_name,
            "model_state": "READY",
            "class_count": len(getattr(detector._model, "names", {}) or {}),
        }
    elif detector is not None and detector._model_load_error:
        model_component = {
            "status": "DEGRADED",
            "model": model_name,
            "model_state": "LOAD_FAILED",
            "failure_type": detector._model_load_error,
            "detail": "The configured model failed to load; see backend logs for diagnostics.",
        }
    elif configured_model.is_file():
        model_component = {
            "status": "ONLINE",
            "model": model_name,
            "model_state": "NOT_LOADED",
            "detail": "Local checkpoint is available; weights load on first inference.",
        }
    else:
        model_component = {
            "status": "DEGRADED",
            "model": model_name,
            "model_state": "CHECKPOINT_NOT_FOUND",
            "detail": "Configured checkpoint is not present locally; health checks do not download model weights.",
        }
    components["detection_model"] = model_component

    process_resources = process_resource_metrics(
        device=device,
        torch_module=sys.modules.get("torch") if device == "mps" else None,
    )
    overall = "online" if all(component["status"] == "ONLINE" for component in components.values()) else "degraded"
    return {
        "status": overall,
        "service": settings.SERVICE_NAME,
        "version": settings.SERVICE_VERSION,
        "components": components,
        "process_resources": process_resources,
    }
