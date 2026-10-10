"""Historical session, event, and aggregated measurement APIs."""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status

from app.analytics.patterns import discover_patterns
from app.prediction.forecast import evaluate_and_predict_activity_rate
from app.prediction.decision_support import build_decision_support
from app.database.instance import repository

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/history/patterns", tags=["Pattern Analysis"])
def get_historical_patterns() -> dict:
    """Find recurring observations without extrapolating future activity."""
    try:
        sessions = repository.list_completed_summaries(limit=100)
        return discover_patterns(sessions)
    except Exception as exc:
        logger.exception("Could not analyze historical patterns")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not analyze historical patterns.",
        ) from exc


@router.get("/history/predictions/activity-rate", tags=["Predictive Intelligence"])
def get_next_session_activity_prediction() -> dict:
    """Forecast normalized activity for the next session only when backtestable."""
    try:
        sessions = repository.list_completed_summaries(limit=100)
        return evaluate_and_predict_activity_rate(sessions)
    except Exception as exc:
        logger.exception("Could not evaluate historical activity forecast")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not evaluate a historical activity forecast.",
        ) from exc


@router.get("/history/decision-support", tags=["Decision Support"])
def get_decision_support() -> dict:
    """Return cautious evidence-linked recommendations when a forecast qualifies."""
    try:
        sessions = repository.list_completed_summaries(limit=100)
        return build_decision_support(sessions)
    except Exception as exc:
        logger.exception("Could not build historical decision support")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not build historical decision support.",
        ) from exc


def _validate_video_id(video_id: str) -> None:
    try:
        uuid.UUID(video_id, version=4)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid video ID format.") from exc


def _get_session_or_404(video_id: str) -> dict[str, Any]:
    try:
        session = repository.get_session(video_id)
    except Exception as exc:
        logger.exception("Could not read historical session %s", video_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not read historical session data.",
        ) from exc
    if not session:
        raise HTTPException(status_code=404, detail="Historical session not found.")
    return session


def _time_range(start_seconds: float | None, end_seconds: float | None) -> dict[str, float | None]:
    if start_seconds is not None and end_seconds is not None and end_seconds <= start_seconds:
        raise HTTPException(status_code=422, detail="end_seconds must be greater than start_seconds.")
    return {"start_seconds": start_seconds, "end_seconds": end_seconds}


def _statistics(measurements: list[dict[str, Any]]) -> dict[str, Any]:
    if not measurements:
        return {
            "minimum_bucket_average": None,
            "maximum_bucket_average": None,
            "mean_instances_per_observed_frame": None,
            "peak_period": None,
            "quiet_period": None,
        }
    peak = max(measurements, key=lambda item: item["average_instances_per_observed_frame"])
    quiet = min(measurements, key=lambda item: item["average_instances_per_observed_frame"])
    averages = [item["average_instances_per_observed_frame"] for item in measurements]
    observed_frames = sum(item["observed_frames"] for item in measurements)
    instances = sum(item["detection_instances"] for item in measurements)

    def period(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "bucket_start_seconds": row["bucket_start_seconds"],
            "bucket_end_seconds": row["bucket_end_seconds"],
            "average_instances_per_observed_frame": row["average_instances_per_observed_frame"],
        }

    return {
        "minimum_bucket_average": min(averages),
        "maximum_bucket_average": max(averages),
        "mean_instances_per_observed_frame": round(instances / observed_frames, 4),
        "peak_period": period(peak),
        "quiet_period": period(quiet),
    }


@router.get("/history/sessions", tags=["History"])
def list_historical_sessions(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    start_at: datetime | None = None,
    end_at: datetime | None = None,
) -> dict:
    """List stored sessions, optionally filtered by upload timestamp."""
    if start_at and start_at.tzinfo is None or end_at and end_at.tzinfo is None:
        raise HTTPException(status_code=422, detail="Time filters must include a timezone.")
    if start_at and end_at and end_at < start_at:
        raise HTTPException(status_code=422, detail="end_at must be at or after start_at.")
    try:
        sessions = repository.list_sessions(
            limit=limit,
            offset=offset,
            start_at=start_at.astimezone(timezone.utc).isoformat() if start_at else None,
            end_at=end_at.astimezone(timezone.utc).isoformat() if end_at else None,
        )
    except Exception as exc:
        logger.exception("Could not list historical sessions")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not list historical sessions.",
        ) from exc
    return {"data_kind": "historical_sessions", "limit": limit, "offset": offset, "sessions": sessions}


@router.get("/history/sessions/{video_id}", tags=["History"])
def get_historical_session(video_id: str) -> dict:
    """Return one session with its stored observations and aggregate summaries."""
    _validate_video_id(video_id)
    return {"data_kind": "historical_session", "session": _get_session_or_404(video_id)}


@router.get("/history/sessions/{video_id}/events", tags=["History"])
def get_historical_events(
    video_id: str,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """Page persisted events for a historical session."""
    _validate_video_id(video_id)
    session = _get_session_or_404(video_id)
    if session["status"] != "completed":
        raise HTTPException(status_code=409, detail="Events are available after analysis completes.")
    try:
        events, has_more = repository.get_events(video_id, limit=limit, offset=offset)
    except Exception as exc:
        logger.exception("Could not read historical events for session %s", video_id)
        raise HTTPException(status_code=500, detail="Could not read historical events.") from exc
    return {
        "data_kind": "historical_events",
        "video_id": video_id,
        "limit": limit,
        "offset": offset,
        "events": events,
        "has_more": has_more,
    }


@router.get("/history/sessions/{video_id}/activity", tags=["History"])
def get_historical_activity(
    video_id: str,
    start_seconds: float | None = Query(default=None, ge=0),
    end_seconds: float | None = Query(default=None, gt=0),
) -> dict:
    """Query stored aggregate measurements over a video-relative time range."""
    _validate_video_id(video_id)
    session = _get_session_or_404(video_id)
    if session["status"] != "completed":
        raise HTTPException(status_code=409, detail="Measurements are available after analysis completes.")
    time_range = _time_range(start_seconds, end_seconds)
    try:
        measurements = repository.get_activity(
            video_id, start_seconds=start_seconds, end_seconds=end_seconds
        )
    except Exception as exc:
        logger.exception("Could not query historical activity for session %s", video_id)
        raise HTTPException(status_code=500, detail="Could not query historical activity.") from exc
    return {
        "data_kind": "historical_aggregate",
        "time_basis": "video_seconds",
        "video_id": video_id,
        "time_range": time_range,
        "measurements": measurements,
        "statistics": _statistics(measurements),
    }


@router.get("/history/sessions/{video_id}/zones", tags=["History"])
def get_historical_zone_activity(
    video_id: str,
    start_seconds: float | None = Query(default=None, ge=0),
    end_seconds: float | None = Query(default=None, gt=0),
) -> dict:
    """Query persisted zone measurements over a video-relative time range."""
    _validate_video_id(video_id)
    session = _get_session_or_404(video_id)
    if session["status"] != "completed":
        raise HTTPException(status_code=409, detail="Zone measurements are available after analysis completes.")
    time_range = _time_range(start_seconds, end_seconds)
    try:
        measurements = repository.get_zone_activity(
            video_id, start_seconds=start_seconds, end_seconds=end_seconds
        )
    except Exception as exc:
        logger.exception("Could not query historical zone data for session %s", video_id)
        raise HTTPException(status_code=500, detail="Could not query historical zone data.") from exc
    return {
        "data_kind": "historical_zone_aggregate",
        "time_basis": "video_seconds",
        "video_id": video_id,
        "time_range": time_range,
        "zones": session["spatial_summary"]["zones"],
        "measurements": measurements,
    }


@router.get("/history/sessions/{video_id}/occupancy/{zone_id}", tags=["History"])
def get_historical_zone_occupancy(
    video_id: str,
    zone_id: str,
    start_seconds: float | None = Query(default=None, ge=0),
    end_seconds: float | None = Query(default=None, gt=0),
) -> dict:
    """Query persisted track-based visible-person estimates for one zone."""
    _validate_video_id(video_id)
    session = _get_session_or_404(video_id)
    if session["status"] != "completed":
        raise HTTPException(status_code=409, detail="Occupancy observations are available after analysis completes.")
    time_range = _time_range(start_seconds, end_seconds)
    zones = (session.get("spatial_summary") or {}).get("zones", [])
    if not any(zone.get("zone_id") == zone_id for zone in zones):
        raise HTTPException(status_code=404, detail="Zone was not found in this session.")
    try:
        observations = repository.get_zone_occupancy(
            video_id, zone_id, start_seconds=start_seconds, end_seconds=end_seconds
        )
    except Exception as exc:
        logger.exception("Could not query historical occupancy for session %s zone %s", video_id, zone_id)
        raise HTTPException(status_code=500, detail="Could not query historical occupancy.") from exc
    return {
        "data_kind": "historical_zone_occupancy",
        "time_basis": "video_seconds",
        "video_id": video_id,
        "zone_id": zone_id,
        "time_range": time_range,
        "status": "available" if observations else "unavailable",
        "reason": None if observations else "No persisted track-aware occupancy observations exist for this zone.",
        "measurements": observations,
    }
