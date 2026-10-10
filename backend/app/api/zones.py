"""Per-video region configuration endpoints."""

import logging
import uuid

from fastapi import APIRouter, HTTPException, status

from app.api.analysis import _analysis_jobs, _find_source_video, _jobs_lock, _load_saved_result
from app.spatial.config import (
    ZoneConfiguration,
    load_zones,
    save_zones,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _validate_video_id(video_id: str) -> None:
    try:
        uuid.UUID(video_id, version=4)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid video ID format.",
        ) from exc


@router.get("/video/{video_id}/zones", tags=["Spatial Intelligence"])
async def get_video_zones(video_id: str) -> dict:
    """Return configured normalized-coordinate zones for an uploaded video."""
    _validate_video_id(video_id)
    if not _find_source_video(video_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Uploaded source video not found.")
    try:
        zones = load_zones(video_id)
    except (OSError, ValueError):
        logger.exception("Could not read zone configuration for video %s", video_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not read the video zone configuration.",
        )
    return {"video_id": video_id, "coordinate_system": "normalized_frame", "zones": zones}


@router.put("/video/{video_id}/zones", tags=["Spatial Intelligence"])
async def put_video_zones(video_id: str, configuration: ZoneConfiguration) -> dict:
    """Store zones before processing so every derived result uses one layout."""
    _validate_video_id(video_id)
    if not _find_source_video(video_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Uploaded source video not found.")

    with _jobs_lock:
        job = _analysis_jobs.get(video_id)
        is_busy_or_complete = bool(job and job.get("status") in {"analyzing", "completed"})
        if is_busy_or_complete or _load_saved_result(video_id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Zones are locked after analysis starts. Configure zones before analysis.",
            )

        try:
            save_zones(video_id, configuration)
        except OSError:
            logger.exception("Could not save zone configuration for video %s", video_id)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not save the video zone configuration.",
            )

    return {
        "video_id": video_id,
        "coordinate_system": "normalized_frame",
        "zones": [zone.model_dump(mode="json") for zone in configuration.zones],
    }
