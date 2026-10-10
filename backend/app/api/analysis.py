"""Analysis API router for PREDIX Phase 3.

Provides endpoints for asynchronous object detection, status polling,
result retrieval, and serving the annotated output video.
"""

import logging
import json
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, Optional
from itertools import islice

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import FileResponse

from app.analytics.temporal import AnalyticsDataError, build_temporal_analytics
from app.analytics.spatial import build_spatial_analytics
from app.core.config import settings
from app.cv.detector import ObjectDetector
from app.cv.runtime import get_detector, release_pipeline, reserve_pipeline
from app.database.instance import repository
from app.events.engine import generate_events
from app.spatial.config import load_zones
from app.prediction.zone_occupancy import forecast_zone_occupancy

logger = logging.getLogger(__name__)

router = APIRouter()

# In-memory job state: keyed by video_id
# Structure: { video_id: { job_id, status, progress_percentage, ... } }
_analysis_jobs: Dict[str, Dict[str, Any]] = {}
_jobs_lock = threading.Lock()

def _get_detector() -> ObjectDetector:
    return get_detector()


def _find_source_video(video_id: str) -> Optional[Path]:
    """Find source uploaded video matching {video_id}_* in uploads directory."""
    prefix = f"{video_id}_"
    if not settings.upload_dir.is_dir():
        return None
    matches = [f for f in settings.upload_dir.iterdir() if f.is_file() and f.name.startswith(prefix)]
    return matches[0] if matches else None


def _load_saved_result(video_id: str) -> Optional[dict]:
    try:
        session = repository.get_session(video_id)
    except sqlite3.Error:
        logger.exception("Could not read saved analysis summary for video %s", video_id)
        return None
    if session and session["status"] == "completed":
        return session.get("summary")
    return None


def _run_analysis_worker(
    job_id: str,
    video_id: str,
    source_path: Path,
    output_path: Path,
    zones: list[dict[str, Any]],
) -> None:
    """Worker function running in a background thread."""
    detections_path = settings.analysis_dir / f"{video_id}_detections.jsonl"
    events_path = settings.analysis_dir / f"{video_id}_events.jsonl"

    def on_progress(frames_processed: int, total_frames: int, detection_count: int, elapsed: float) -> None:
        percent = min(int((frames_processed / max(total_frames, 1)) * 100), 99)
        with _jobs_lock:
            if video_id in _analysis_jobs:
                _analysis_jobs[video_id].update({
                    "progress_percentage": percent,
                    "frames_processed": frames_processed,
                    "total_frames": total_frames,
                    "elapsed_time_seconds": round(elapsed, 1),
                })

    try:
        detector = _get_detector()
        result = detector.process_video(
            video_id=video_id,
            input_path=source_path,
            output_path=output_path,
            detection_output_path=detections_path,
            progress_callback=on_progress,
        )
        total_events = generate_events(detections_path, events_path, video_id, zones)
        temporal_summary = build_temporal_analytics(detections_path, bucket_seconds=15)
        spatial_summary = build_spatial_analytics(
            detections_path, events_path, zones, bucket_seconds=15
        )

        result_payload = {
            "video_id": result.video_id,
            "model": result.model,
            "device": result.device,
            "device_name": result.device_name,
            "confidence_threshold": result.confidence_threshold,
            "frames_processed": result.frames_processed,
            "total_frames": result.total_frames,
            "total_detection_instances": result.total_detection_instances,
            "average_instances_per_frame": result.average_instances_per_frame,
            "detection_instances_by_class": result.detection_instances_by_class,
            "processing_time_seconds": result.processing_time_seconds,
            "processing_fps": result.processing_fps,
            "output_filename": result.output_filename,
            "inference_frames": result.inference_frames,
            "frame_stride": result.frame_stride,
            "image_size": result.image_size,
            "occupancy_peak_estimate": result.occupancy_peak_estimate,
            "occupancy_mean_estimate": result.occupancy_mean_estimate,
            "total_events": total_events,
            "zones_configured": len(zones),
            "detection_results_endpoint": f"/api/video/{video_id}/analysis/detections",
            "events_endpoint": f"/api/video/{video_id}/analysis/events",
            "temporal_summary_endpoint": f"/api/video/{video_id}/analysis/temporal",
            "spatial_summary_endpoint": f"/api/video/{video_id}/analysis/spatial",
        }
        repository.save_completed(
            video_id,
            result_payload,
            temporal_summary,
            spatial_summary,
            events_path,
        )

        with _jobs_lock:
            if video_id in _analysis_jobs:
                _analysis_jobs[video_id].update({
                    "status": "completed",
                    "progress_percentage": 100,
                    "frames_processed": result.frames_processed,
                    "total_frames": result.total_frames,
                    "elapsed_time_seconds": result.processing_time_seconds,
                    "result": result_payload,
                })
        logger.info("Analysis completed successfully for video %s in %ss", video_id, result.processing_time_seconds)

    except Exception:
        logger.exception("Analysis failed for video %s", video_id)
        for artifact in (
            settings.analysis_dir / f"{video_id}_annotated.mp4",
            settings.analysis_dir / f"{video_id}_detections.jsonl",
            settings.analysis_dir / f"{video_id}_events.jsonl",
        ):
            artifact.unlink(missing_ok=True)
        try:
            repository.set_status(video_id, "error")
        except (sqlite3.Error, LookupError):
            logger.exception("Could not persist failed analysis status for video %s", video_id)
        with _jobs_lock:
            if video_id in _analysis_jobs:
                _analysis_jobs[video_id].update({
                    "status": "error",
                    "error": "Video analysis failed. Check backend logs and retry.",
                })
    finally:
        release_pipeline(f"upload:{video_id}")


@router.post("/video/{video_id}/analyze", tags=["Computer Vision"], status_code=status.HTTP_200_OK)
async def analyze_video(video_id: str) -> dict:
    """
    Trigger asynchronous object detection on a previously uploaded video.
    Returns immediately with job_id and status='analyzing'.
    """
    try:
        uuid.UUID(video_id, version=4)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid video ID format.")

    source_path = _find_source_video(video_id)
    if not source_path or not source_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Uploaded source video not found.")

    try:
        detector = _get_detector()
    except Exception as exc:
        logger.exception("Could not initialize the configured AI engine")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The configured AI engine is unavailable.",
        ) from exc

    with _jobs_lock:
        current_job = _analysis_jobs.get(video_id)
        if current_job and current_job.get("status") == "analyzing":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Analysis is already in progress for this video.",
            )
        if any(
            key != video_id and value.get("status") == "analyzing"
            for key, value in _analysis_jobs.items()
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Another video analysis is already in progress.",
            )
        try:
            zones = load_zones(video_id)
        except (OSError, ValueError):
            logger.exception("Could not load zone configuration for video %s", video_id)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not read the video zone configuration.",
            )

        job_id = str(uuid.uuid4())
        pipeline_owner = f"upload:{video_id}"
        if not reserve_pipeline(pipeline_owner):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Another video or live analysis is already using the AI engine.",
            )
        output_filename = f"{video_id}_annotated.mp4"
        output_path = settings.analysis_dir / output_filename
        output_path.unlink(missing_ok=True)
        (settings.analysis_dir / f"{video_id}_detections.jsonl").unlink(missing_ok=True)
        (settings.analysis_dir / f"{video_id}_events.jsonl").unlink(missing_ok=True)

        try:
            repository.set_status(video_id, "analyzing")
        except (sqlite3.Error, LookupError):
            release_pipeline(pipeline_owner)
            logger.exception("Could not mark session as analyzing for video %s", video_id)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not start video analysis.",
            )

        _analysis_jobs[video_id] = {
            "job_id": job_id,
            "video_id": video_id,
            "status": "analyzing",
            "progress_percentage": 0,
            "frames_processed": 0,
            "total_frames": 0,
            "elapsed_time_seconds": 0.0,
            "device": detector.device,
            "device_name": detector.device_name,
            "model": detector.model_name,
            "confidence_threshold": detector.conf_threshold,
            "result": None,
            "error": None,
        }

    # Start background processing thread
    thread = threading.Thread(
        target=_run_analysis_worker,
        args=(job_id, video_id, source_path, output_path, zones),
        daemon=True,
    )
    try:
        thread.start()
    except RuntimeError as exc:
        release_pipeline(pipeline_owner)
        logger.exception("Could not start analysis worker for video %s", video_id)
        try:
            repository.set_status(video_id, "error")
        except (sqlite3.Error, LookupError):
            logger.exception("Could not persist analysis worker startup failure for video %s", video_id)
        with _jobs_lock:
            _analysis_jobs[video_id].update({
                "status": "error",
                "error": "Video analysis could not be started. Please retry.",
            })
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Video analysis could not be started. Please retry.",
        ) from exc

    return {
        "job_id": job_id,
        "video_id": video_id,
        "status": "analyzing",
        "device": detector.device,
        "device_name": detector.device_name,
        "model": detector.model_name,
    }


@router.get("/video/{video_id}/analysis/status", tags=["Computer Vision"])
async def get_analysis_status(video_id: str) -> dict:
    """Return the current progress or outcome of the analysis job."""
    try:
        uuid.UUID(video_id, version=4)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid video ID format.")

    with _jobs_lock:
        job = _analysis_jobs.get(video_id)

    if not job:
        saved_result = _load_saved_result(video_id)
        if saved_result:
            return {
                "video_id": video_id,
                "status": "completed",
                "progress_percentage": 100,
                "frames_processed": saved_result["frames_processed"],
                "total_frames": saved_result["total_frames"],
                "model": saved_result["model"],
                "device": saved_result["device"],
                "device_name": saved_result["device_name"],
            }
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No analysis job found for this video. Please click Analyze Video.",
        )

    return {
        "job_id": job["job_id"],
        "video_id": job["video_id"],
        "status": job["status"],
        "progress_percentage": job["progress_percentage"],
        "frames_processed": job["frames_processed"],
        "total_frames": job["total_frames"],
        "elapsed_time_seconds": job["elapsed_time_seconds"],
        "device": job["device"],
        "device_name": job["device_name"],
        "model": job["model"],
        "confidence_threshold": job["confidence_threshold"],
        "error": job.get("error"),
    }


@router.get("/video/{video_id}/analysis/result", tags=["Computer Vision"])
async def get_analysis_result(video_id: str) -> dict:
    """Return the full detection statistics payload for a completed job."""
    try:
        uuid.UUID(video_id, version=4)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid video ID format.")

    with _jobs_lock:
        job = _analysis_jobs.get(video_id)

    if not job:
        saved_result = _load_saved_result(video_id)
        if saved_result:
            return saved_result
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis result not found.")

    if job["status"] == "error":
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Analysis failed: {job.get('error', 'Unknown error')}",
        )

    if job["status"] != "completed" or not job.get("result"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Analysis is still in progress. Please wait for completion.",
        )

    return job["result"]


@router.get("/video/{video_id}/analysis/detections", tags=["Computer Vision"])
async def get_analysis_detections(
    video_id: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=1000),
) -> dict:
    """Return paginated frame-level detections without loading the full file."""
    try:
        uuid.UUID(video_id, version=4)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid video ID format.")

    with _jobs_lock:
        job = _analysis_jobs.get(video_id)
    has_saved_result = _load_saved_result(video_id) is not None
    if job:
        has_completed_result = job.get("status") == "completed"
    else:
        has_completed_result = has_saved_result
    if not has_completed_result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Completed detection results were not found.",
        )

    detections_path = settings.analysis_dir / f"{video_id}_detections.jsonl"
    if not detections_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Frame-level detection results were not found.",
        )

    try:
        with detections_path.open("r", encoding="utf-8") as records:
            page = list(islice(records, offset, offset + limit + 1))
        frames = [json.loads(line) for line in page[:limit]]
    except (OSError, json.JSONDecodeError):
        logger.exception("Could not read detection results for video %s", video_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not read detection results.",
        )

    return {
        "video_id": video_id,
        "offset": offset,
        "limit": limit,
        "frames": frames,
        "has_more": len(page) > limit,
    }


@router.get("/video/{video_id}/analysis/events", tags=["Events"])
async def get_analysis_events(
    video_id: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=1000),
) -> dict:
    """Return paginated events derived from the video's stored detections."""
    try:
        uuid.UUID(video_id, version=4)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid video ID format.")

    with _jobs_lock:
        job = _analysis_jobs.get(video_id)
    has_saved_result = _load_saved_result(video_id) is not None
    is_complete = job.get("status") == "completed" if job else has_saved_result
    if not is_complete:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Completed events were not found.",
        )

    try:
        events, has_more = repository.get_events(video_id, limit=limit, offset=offset)
    except sqlite3.Error:
        logger.exception("Could not read events for video %s", video_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not read event results.",
        )

    return {
        "video_id": video_id,
        "offset": offset,
        "limit": limit,
        "events": events,
        "has_more": has_more,
    }


@router.get("/video/{video_id}/analysis/temporal", tags=["Analytics"])
async def get_temporal_analytics(
    video_id: str,
    bucket_seconds: int = Query(default=15, ge=1, le=86_400),
    activity_baseline_buckets: int = Query(default=6, ge=2, le=100),
    activity_mad_multiplier: float = Query(default=3.0, gt=0, le=10),
    activity_minimum_increase: float = Query(default=1.0, ge=0, le=100_000),
) -> dict:
    """Return observed object timelines, statistics, and a configurable activity-deviation signal."""
    try:
        uuid.UUID(video_id, version=4)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid video ID format.")

    with _jobs_lock:
        job = _analysis_jobs.get(video_id)
    has_saved_result = _load_saved_result(video_id) is not None
    is_complete = job.get("status") == "completed" if job else has_saved_result
    if not is_complete:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Completed temporal analytics were not found.",
        )

    detections_path = settings.analysis_dir / f"{video_id}_detections.jsonl"
    try:
        analytics = build_temporal_analytics(
            detections_path,
            bucket_seconds,
            activity_baseline_buckets=activity_baseline_buckets,
            activity_mad_multiplier=activity_mad_multiplier,
            activity_minimum_increase=activity_minimum_increase,
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Frame-level detection results were not found.",
        ) from exc
    except AnalyticsDataError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    return {"video_id": video_id, **analytics}


@router.get("/video/{video_id}/analysis/spatial", tags=["Spatial Intelligence"])
async def get_spatial_analytics(
    video_id: str,
    bucket_seconds: int = Query(default=15, ge=1, le=86_400),
) -> dict:
    """Return observed activity grouped by the configured image-space zones."""
    try:
        uuid.UUID(video_id, version=4)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid video ID format.")

    with _jobs_lock:
        job = _analysis_jobs.get(video_id)
    has_saved_result = _load_saved_result(video_id) is not None
    is_complete = job.get("status") == "completed" if job else has_saved_result
    if not is_complete:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Completed spatial analytics were not found.",
        )

    try:
        zones = load_zones(video_id)
        analytics = build_spatial_analytics(
            settings.analysis_dir / f"{video_id}_detections.jsonl",
            settings.analysis_dir / f"{video_id}_events.jsonl",
            zones,
            bucket_seconds,
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Detection or event records were not found.",
        ) from exc
    except (AnalyticsDataError, OSError, ValueError) as exc:
        logger.exception("Could not compute spatial analytics for video %s", video_id)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Could not compute spatial analytics from stored observations.",
        ) from exc

    return {"video_id": video_id, **analytics}


@router.get("/video/{video_id}/analysis/zones/{zone_id}/forecast", tags=["Predictive Intelligence"])
async def get_zone_occupancy_forecast(video_id: str, zone_id: str) -> dict:
    """Forecast zone occupancy at 1/5/10 minutes only when rolling validation is possible."""
    try:
        uuid.UUID(video_id, version=4)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid video ID format.") from exc
    with _jobs_lock:
        job = _analysis_jobs.get(video_id)
    is_complete = job.get("status") == "completed" if job else _load_saved_result(video_id) is not None
    if not is_complete:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Completed zone observations were not found.")
    try:
        zones = load_zones(video_id)
        zone = next((item for item in zones if item["zone_id"] == zone_id), None)
        if zone is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Configured zone was not found.")
        analytics = build_spatial_analytics(
            settings.analysis_dir / f"{video_id}_detections.jsonl",
            settings.analysis_dir / f"{video_id}_events.jsonl",
            zones,
            bucket_seconds=15,
        )
        zone_observations = next(item for item in analytics["zones"] if item["zone_id"] == zone_id)
        forecast = forecast_zone_occupancy(zone_observations["occupancy"], bucket_seconds=15)
    except HTTPException:
        raise
    except (FileNotFoundError, AnalyticsDataError, OSError, ValueError) as exc:
        logger.exception("Could not forecast occupancy for video %s zone %s", video_id, zone_id)
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Could not forecast from stored zone observations.") from exc
    return {"video_id": video_id, "zone_id": zone_id, "zone_name": zone["name"], **forecast}


@router.get("/video/{video_id}/annotated", tags=["Computer Vision"])
async def get_annotated_video(video_id: str):
    """
    Serve the generated annotated MP4 file using standard FastAPI FileResponse.
    Does not introduce custom Range media servers.
    """
    try:
        uuid.UUID(video_id, version=4)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid video ID format.")

    with _jobs_lock:
        job = _analysis_jobs.get(video_id)
    if (job and job.get("status") != "completed") or (not job and not _load_saved_result(video_id)):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Annotated video not found. Please analyze the video first.",
        )

    output_path = settings.analysis_dir / f"{video_id}_annotated.mp4"
    if not output_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Annotated video not found. Please analyze the video first.",
        )

    return FileResponse(
        path=str(output_path),
        media_type="video/mp4",
        filename=output_path.name,
    )
