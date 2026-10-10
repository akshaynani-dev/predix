"""Browser-camera WebSocket ingestion using the shared detector runtime."""

import asyncio
import base64
import json
import logging
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any, Literal
from pydantic import BaseModel, ValidationError

import cv2
import numpy as np
from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect

from app.analytics.anomalies import detect_occupancy_deviations
from app.analytics.occupancy_alerts import build_occupancy_signal_alerts
from app.core.config import settings
from app.cv.frame_processing import process_frame
from app.cv.runtime import get_detector, release_pipeline, reserve_pipeline
from app.cv.tracking import estimate_tracked_zone_occupancy
from app.cv.tracker_factory import create_anonymous_tracker
from app.database.instance import repository
from app.prediction.early_warning import build_crowd_early_warning
from app.prediction.live_occupancy import LiveOccupancyForecaster
from app.prediction.zone_attention import recommend_zone_attention
from app.spatial.config import ZoneConfiguration, classify_capacity
from app.video_processing.sources import RTSPVideoSource, VideoSourceError

logger = logging.getLogger(__name__)
router = APIRouter()


class LiveOccupancySignalAlert(BaseModel):
    alert_id: str
    deduplication_key: str
    severity: Literal["WATCH", "WARNING", "CRITICAL"]
    timestamp: datetime
    zone_id: str
    zone: str
    signal: str
    confidence: float | None
    confidence_note: str
    supporting_evidence: list[dict[str, Any]]
    recommendation: str
    status: Literal["active"]
    category: Literal["occupancy_signal_not_incident_alert"]
    limitations: str


class LiveOccupancySignalAlertsResponse(BaseModel):
    data_kind: Literal["live_occupancy_signal_alerts"]
    session_id: str | None
    source_kind: Literal["browser_camera", "rtsp", "hls"] | None
    live_status: str
    active_count: int
    alerts: list[LiveOccupancySignalAlert]
    security_alerts: dict[str, str]


class LiveOccupancyAlertEpisode(BaseModel):
    episode_id: str
    alert_id: str
    zone_id: str
    zone: str
    first_seen_at: datetime
    last_seen_at: datetime
    ended_at: datetime | None
    severity: Literal["WATCH", "WARNING", "CRITICAL"]
    signal: str
    supporting_evidence: list[dict[str, Any]]
    recommendation: str
    status: Literal["active", "resolved", "session_ended"]


class LiveOccupancyAlertHistoryResponse(BaseModel):
    data_kind: Literal["live_occupancy_alert_history"]
    session_id: str
    alerts: list[LiveOccupancyAlertEpisode]


class LiveOccupancyBucket(BaseModel):
    session_id: str
    zone_id: str
    bucket_start_seconds: float
    bucket_end_seconds: float
    observation_count: int
    estimated_mean_visible_people: float
    configured_capacity: int | None
    capacity_ratio: float | None
    capacity_status: str


class LiveCrowdPrediction(BaseModel):
    session_id: str
    zone_id: str
    as_of_session_seconds: float
    horizon_seconds: int
    forecast: float
    uncertainty_mae: float | None
    model: str
    evaluation: dict[str, Any]


class LiveZoneOccupancyHistoryResponse(BaseModel):
    data_kind: Literal["live_zone_occupancy_history"]
    session_id: str
    zone_id: str
    observations: list[LiveOccupancyBucket]
    predictions: list[LiveCrowdPrediction]


_status_lock = threading.Lock()
_live_status: dict = {
    "status": "offline",
    "session_id": None,
    "source_fps": 0.0,
    "inference_fps": 0.0,
    "inference_latency_ms": None,
    "detection_count": 0,
    "frames_processed": 0,
    "zone_occupancy": [],
    "occupancy_alerts": [],
    "current_zones": [],
    "zone_to_zone_transitions": [],
    "history_persistence_status": "available",
    "ai_engine": "idle",
    "source_kind": None,
    "error": None,
}


def get_live_status() -> dict:
    """Return a copy of the latest live-session status for health/UI routes."""
    with _status_lock:
        return dict(_live_status)


def _set_live_status(**values: object) -> None:
    with _status_lock:
        _live_status.update(values)


def _rate(timestamps: deque[float]) -> float:
    if len(timestamps) < 2:
        return 0.0
    span = timestamps[-1] - timestamps[0]
    return round((len(timestamps) - 1) / span, 2) if span > 0 else 0.0


def _point_in_polygon(point: tuple[float, float], polygon: list[list[float]]) -> bool:
    x, y = point
    inside = False
    previous = polygon[-1]
    for current in polygon:
        x1, y1 = previous
        x2, y2 = current
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
        previous = current
    return inside


@router.get("/live/status", tags=["Live Video"])
def live_status() -> dict:
    """Return current browser-camera session metrics without exposing frames."""
    return {"data_kind": "live_session_status", **get_live_status()}


@router.get(
    "/live/alerts",
    tags=["Live Video", "Alerts"],
    response_model=LiveOccupancySignalAlertsResponse,
)
def live_alerts() -> dict:
    """Return the latest evidence-linked occupancy signals for the active live session."""
    snapshot = get_live_status()
    alerts = snapshot.get("occupancy_alerts", []) if snapshot.get("status") == "live" else []
    return {
        "data_kind": "live_occupancy_signal_alerts",
        "session_id": snapshot.get("session_id") if snapshot.get("status") == "live" else None,
        "source_kind": snapshot.get("source_kind") if snapshot.get("status") == "live" else None,
        "live_status": snapshot.get("status", "offline"),
        "active_count": len(alerts),
        "alerts": alerts,
        "security_alerts": {
            "status": "unavailable",
            "reason": "No validated suspicious-object model is configured.",
        },
    }


def _validate_live_session_id(session_id: str) -> None:
    try:
        uuid.UUID(session_id, version=4)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid live session ID format.") from exc


@router.get("/live/sessions", tags=["Live Video", "History"])
def list_live_sessions(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """List durable aggregate summaries for browser-camera sessions."""
    try:
        sessions = repository.list_live_sessions(limit=limit, offset=offset)
    except Exception as exc:
        logger.exception("Could not list live sessions")
        raise HTTPException(status_code=500, detail="Could not list live sessions.") from exc
    return {"data_kind": "live_sessions", "limit": limit, "offset": offset, "sessions": sessions}


@router.get("/live/sessions/{session_id}", tags=["Live Video", "History"])
def get_live_session(session_id: str) -> dict:
    """Read one live session's aggregate metrics without frame/track data."""
    _validate_live_session_id(session_id)
    try:
        session = repository.get_live_session(session_id)
    except Exception as exc:
        logger.exception("Could not read live session %s", session_id)
        raise HTTPException(status_code=500, detail="Could not read live session.") from exc
    if session is None:
        raise HTTPException(status_code=404, detail="Live session not found.")
    return {"data_kind": "live_session", "session": session}


@router.get(
    "/live/sessions/{session_id}/alerts",
    tags=["Live Video", "Alerts", "History"],
    response_model=LiveOccupancyAlertHistoryResponse,
)
def get_live_occupancy_alert_history(
    session_id: str,
    limit: int = Query(default=100, ge=1, le=500),
) -> dict:
    """Read deduplicated occupancy-signal alert episodes for one live session."""
    _validate_live_session_id(session_id)
    try:
        if repository.get_live_session(session_id) is None:
            raise HTTPException(status_code=404, detail="Live session not found.")
        alerts = repository.get_live_occupancy_alerts(session_id, limit=limit)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Could not read live occupancy-alert history for %s", session_id)
        raise HTTPException(status_code=500, detail="Could not read live occupancy-alert history.") from exc
    return {"data_kind": "live_occupancy_alert_history", "session_id": session_id, "alerts": alerts}


@router.get(
    "/live/sessions/{session_id}/zones/{zone_id}/occupancy",
    tags=["Live Video", "History"],
    response_model=LiveZoneOccupancyHistoryResponse,
)
def get_live_zone_occupancy_history(session_id: str, zone_id: str) -> dict:
    """Read aggregate live occupancy buckets and available evaluated forecasts."""
    _validate_live_session_id(session_id)
    if not zone_id or len(zone_id) > 128:
        raise HTTPException(status_code=400, detail="Invalid zone ID.")
    try:
        session = repository.get_live_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Live session not found.")
        history = repository.get_live_zone_observations(session_id, zone_id)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Could not read live zone history for %s", session_id)
        raise HTTPException(status_code=500, detail="Could not read live zone history.") from exc
    return {
        "data_kind": "live_zone_occupancy_history",
        "session_id": session_id,
        "zone_id": zone_id,
        **history,
    }


@router.delete("/live/sessions/{session_id}", tags=["Live Video", "History"])
def delete_live_session(session_id: str) -> dict:
    """Delete a stored live-session aggregate summary."""
    _validate_live_session_id(session_id)
    try:
        deleted = repository.delete_live_session(session_id)
    except Exception as exc:
        logger.exception("Could not delete live session %s", session_id)
        raise HTTPException(status_code=500, detail="Could not delete live session.") from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Live session not found.")
    return {"data_kind": "live_session_deleted", "session_id": session_id, "deleted": True}


@router.websocket("/live/ws")
async def live_camera(websocket: WebSocket) -> None:
    """Receive sampled JPEG frames and return real detections over one socket."""
    origin = websocket.headers.get("origin")
    if origin and origin not in settings.cors_origins:
        await websocket.close(code=1008)
        return

    await websocket.accept()
    session_id = str(uuid.uuid4())
    owner = f"live:{session_id}"
    if not reserve_pipeline(owner):
        await websocket.send_json({
            "type": "rejected",
            "detail": "The AI engine is processing another source. Try again when it is idle.",
        })
        await websocket.close(code=1013)
        return

    session_persisted = False
    history_persistence_status = "available"
    try:
        repository.create_live_session(session_id)
        session_persisted = True
    except Exception:
        history_persistence_status = "degraded"
        logger.exception("Could not persist live-session start for %s", session_id)

    _set_live_status(
        status="connecting",
        session_id=session_id,
        source_fps=0.0,
        inference_fps=0.0,
        inference_latency_ms=None,
        detection_count=0,
        frames_processed=0,
        zone_occupancy=[],
        occupancy_alerts=[],
        current_zones=[],
        zone_to_zone_transitions=[],
        history_persistence_status=history_persistence_status,
        ai_engine="loading",
        source_kind=None,
        error=None,
    )
    source_times: deque[float] = deque(maxlen=20)
    inference_times: deque[float] = deque(maxlen=20)
    frame_count = 0
    last_frame_started = 0.0
    session_started = time.perf_counter()
    tracker = create_anonymous_tracker()
    zones: list[dict] = []
    zone_history: dict[str, deque[int]] = {}
    zone_forecaster = LiveOccupancyForecaster()
    previous_track_zones: dict[str, set[str]] = {}
    zone_transition_totals: dict[str, dict[str, int]] = {}
    zone_edge_totals: dict[tuple[str, str], int] = {}
    total_detection_instances = 0
    peak_estimated_visible_people = 0
    last_source_fps = 0.0
    last_inference_fps = 0.0
    last_inference_latency_ms: float | None = None
    model_name: str | None = None
    device_name: str | None = None
    last_zone_occupancy: list[dict] = []
    last_occupancy_alerts: list[dict] = []
    session_outcome = "disconnected"

    source: RTSPVideoSource | None = None
    detector = None
    source_kind = "browser_camera"
    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break
            frame_from_source = None
            if message.get("text") is not None:
                try:
                    if len(message["text"]) > 65536:
                        raise ValueError("Live zone configuration exceeds the size limit.")
                    payload = json.loads(message["text"])
                    if not isinstance(payload, dict):
                        raise ValueError("Unsupported live configuration message.")
                    if payload.get("type") == "stop":
                        await websocket.send_json({"type": "session_stopped", "session_id": session_id})
                        break
                    if payload.get("type") == "select_browser_source":
                        if (
                            source is not None or frame_count
                            or payload.get("source_kind") != "hls"
                            or set(payload) != {"type", "source_kind"}
                        ):
                            await websocket.send_json({"type": "source_error", "detail": "Unsupported browser video source selection."})
                            continue
                        source_kind = "hls"
                        _set_live_status(status="connecting", source_kind=source_kind, error=None)
                        await websocket.send_json({"type": "source_ready", "source_kind": source_kind})
                        continue
                    if payload.get("type") == "start_rtsp":
                        if source is not None or frame_count:
                            raise ValueError("RTSP source must be selected before requesting frames.")
                        url = payload.get("url")
                        if not isinstance(url, str) or len(url) > 4096:
                            raise ValueError("The configured RTSP source is invalid.")
                        try:
                            source = RTSPVideoSource(
                                url,
                                allowed_hosts=settings.rtsp_allowed_hosts,
                                open_timeout_ms=settings.RTSP_OPEN_TIMEOUT_MS,
                                read_timeout_ms=settings.RTSP_READ_TIMEOUT_MS,
                            )
                        except VideoSourceError:
                            await websocket.send_json({
                                "type": "source_error",
                                "detail": "The configured RTSP source is invalid or its host is not allowlisted.",
                            })
                            continue
                        source_kind = "rtsp"
                        try:
                            await asyncio.to_thread(source.open)
                        except VideoSourceError:
                            source.release()
                            source = None
                            await websocket.send_json({
                                "type": "source_error",
                                "detail": "Could not open the configured RTSP source. Check the host allowlist and camera availability.",
                            })
                            continue
                        _set_live_status(status="connecting", source_kind=source_kind, error=None)
                        await websocket.send_json({"type": "source_ready", "source_kind": source_kind})
                        continue
                    if payload.get("type") == "configure_zones":
                        if source is not None and payload.get("url") is not None:
                            raise ValueError("Unsupported live configuration message.")
                    elif payload.get("type") != "next_frame" or source is None:
                        raise ValueError("Unsupported live configuration message.")
                    if payload.get("type") == "next_frame":
                        if source is None:
                            raise ValueError("Select an RTSP source before requesting frames.")
                        now = time.perf_counter()
                        if last_frame_started and (now - last_frame_started) * 1000 < settings.LIVE_MIN_FRAME_INTERVAL_MS:
                            await websocket.send_json({"type": "error", "detail": "Live frame rate exceeds the configured limit."})
                            continue
                        last_frame_started = now
                        ok, rtsp_frame = await asyncio.to_thread(source.read)
                        if not ok or rtsp_frame is None:
                            session_outcome = "failed"
                            _set_live_status(status="degraded", error="RTSP stream disconnected.")
                            await websocket.send_json({"type": "stream_disconnected", "detail": "The RTSP stream stopped returning frames."})
                            await websocket.close(code=1011)
                            break
                        frame_from_source = rtsp_frame
                    else:
                        frame_from_source = None
                    if payload.get("type") == "configure_zones":
                        config = ZoneConfiguration.model_validate({"zones": payload.get("zones", [])})
                        zones = [zone.model_dump(mode="json") for zone in config.zones]
                        zone_history = {zone["zone_id"]: zone_history.get(zone["zone_id"], deque(maxlen=40)) for zone in zones}
                        zone_forecaster.reset([zone["zone_id"] for zone in zones])
                        previous_track_zones.clear()
                        zone_transition_totals = {zone["zone_id"]: {"entries": 0, "exits": 0} for zone in zones}
                        zone_edge_totals.clear()
                        await websocket.send_json({"type": "zones_configured", "zones": zones})
                        continue
                except (ValueError, TypeError, json.JSONDecodeError, ValidationError):
                    await websocket.send_json({"type": "zone_config_error", "detail": "Live zone configuration is invalid."})
                if frame_from_source is None:
                    continue
            encoded = message.get("bytes")
            if not encoded and frame_from_source is None:
                await websocket.send_json({"type": "error", "detail": "Send a JPEG frame as binary data."})
                continue
            if encoded and len(encoded) > settings.LIVE_MAX_FRAME_BYTES:
                await websocket.send_json({"type": "error", "detail": "Live frame exceeds the configured size limit."})
                await websocket.close(code=1009)
                break

            now = time.perf_counter()
            if frame_from_source is not None:
                frame = frame_from_source
            else:
                if last_frame_started and (now - last_frame_started) * 1000 < settings.LIVE_MIN_FRAME_INTERVAL_MS:
                    await websocket.send_json({"type": "error", "detail": "Live frame rate exceeds the configured limit."})
                    continue
                last_frame_started = now
                try:
                    frame = cv2.imdecode(np.frombuffer(encoded, dtype=np.uint8), cv2.IMREAD_COLOR)
                except cv2.error:
                    frame = None
            if frame is None:
                await websocket.send_json({"type": "error", "detail": "Live frame could not be decoded."})
                continue

            height, width = frame.shape[:2]
            if width > settings.LIVE_MAX_FRAME_WIDTH or height > settings.LIVE_MAX_FRAME_HEIGHT:
                await websocket.send_json({
                    "type": "error",
                    "detail": "Live frame dimensions exceed the configured limit.",
                })
                await websocket.close(code=1009)
                break

            inference_started = time.perf_counter()
            preview_jpeg = None
            if source_kind == "rtsp":
                try:
                    preview_frame = frame
                    if width > 640:
                        preview_frame = cv2.resize(
                            frame,
                            (640, max(1, round(height * 640 / width))),
                            interpolation=cv2.INTER_AREA,
                        )
                    encoded_preview, preview_buffer = cv2.imencode(
                        ".jpg", preview_frame, [cv2.IMWRITE_JPEG_QUALITY, 72]
                    )
                    if encoded_preview:
                        preview_jpeg = base64.b64encode(preview_buffer).decode("ascii")
                except cv2.error:
                    logger.warning("Could not encode RTSP preview for live session %s", session_id)
            try:
                if detector is None:
                    detector = await asyncio.to_thread(get_detector)
                    model_name = detector.model_name
                    device_name = detector.device
                    _set_live_status(status="live", ai_engine="online", source_kind=source_kind)
                detections, tracked_detections, _ = await asyncio.to_thread(
                    process_frame,
                    detector,
                    tracker,
                    frame,
                    now - session_started,
                )
            except Exception:
                session_outcome = "failed"
                logger.exception("Live detection failed for session %s", session_id)
                _set_live_status(status="degraded", ai_engine="error", error="Live inference failed.")
                await websocket.send_json({"type": "error", "detail": "Live inference failed. Check backend logs."})
                await websocket.close(code=1011)
                break

            inference_finished = time.perf_counter()
            active_track_ids = tracker.active_track_ids
            previous_track_zones = {
                track_id: memberships
                for track_id, memberships in previous_track_zones.items()
                if track_id in active_track_ids
            }
            observed_track_zones: dict[str, set[str]] = {}
            for tracked in tracked_detections:
                if tracked["class"] != "person":
                    continue
                x1, y1, x2, y2 = tracked["bbox"]
                center = ((x1 + x2) / (2 * width), (y1 + y2) / (2 * height))
                memberships = {
                    zone["zone_id"] for zone in zones
                    if _point_in_polygon(center, zone["polygon"])
                }
                observed_track_zones[tracked["track_id"]] = memberships
            transition_frame = {zone["zone_id"]: {"entries": 0, "exits": 0} for zone in zones}
            for track_id, memberships in observed_track_zones.items():
                previous_memberships = previous_track_zones.get(track_id)
                if previous_memberships is not None:
                    newly_entered = memberships - previous_memberships
                    newly_exited = previous_memberships - memberships
                    for zone_id in newly_entered:
                        transition_frame[zone_id]["entries"] += 1
                        zone_transition_totals[zone_id]["entries"] += 1
                    for zone_id in newly_exited:
                        transition_frame[zone_id]["exits"] += 1
                        zone_transition_totals[zone_id]["exits"] += 1
                    for source_id in newly_exited:
                        for target_id in newly_entered:
                            edge = (source_id, target_id)
                            zone_edge_totals[edge] = zone_edge_totals.get(edge, 0) + 1
                previous_track_zones[track_id] = memberships
            active_zone_occupancy = estimate_tracked_zone_occupancy(
                tracker.active_tracks,
                observed_track_zones,
                previous_track_zones,
            )
            zone_occupancy = []
            for zone in zones:
                occupancy = active_zone_occupancy.get(
                    zone["zone_id"], {"count": 0, "observed_count": 0, "carried_count": 0}
                )
                estimate = occupancy["count"]
                history = zone_history[zone["zone_id"]]
                history.append(estimate)
                thresholds = zone["status_thresholds"]
                capacity_status, capacity_ratio = classify_capacity(
                    estimate, zone.get("occupancy_capacity"), thresholds
                )
                occupancy_anomaly = detect_occupancy_deviations(
                    list(history)[-7:],
                    mad_multiplier=zone.get("anomaly_mad_multiplier", 3.0),
                    minimum_increase=zone.get("anomaly_minimum_increase", 1.0),
                )
                early_warning = build_crowd_early_warning(
                    {
                        "estimation_status": "estimated",
                        "status": capacity_status,
                        "current_estimate": estimate,
                        "configured_capacity": zone.get("occupancy_capacity"),
                        "capacity_ratio": capacity_ratio,
                    },
                    occupancy_anomaly,
                )
                security_attention = recommend_zone_attention(
                    {
                        "estimation_status": "estimated",
                        "status": capacity_status,
                        "current_estimate": estimate,
                        "configured_capacity": zone.get("occupancy_capacity"),
                        "capacity_ratio": capacity_ratio,
                    },
                    occupancy_anomaly,
                )
                occupancy_forecast = zone_forecaster.observe(
                    zone["zone_id"], now - session_started, estimate
                )
                completed_bucket = zone_forecaster.take_completed_bucket(zone["zone_id"])
                if completed_bucket is not None and session_persisted:
                    bucket_status, bucket_ratio = classify_capacity(
                        completed_bucket["estimated_mean_visible_people"],
                        zone.get("occupancy_capacity"), thresholds,
                    )
                    try:
                        repository.save_live_occupancy_bucket(
                            session_id,
                            zone["zone_id"],
                            **completed_bucket,
                            configured_capacity=zone.get("occupancy_capacity"),
                            capacity_ratio=bucket_ratio,
                            capacity_status=bucket_status,
                        )
                        repository.save_live_crowd_predictions(
                            session_id, zone["zone_id"], occupancy_forecast
                        )
                    except Exception:
                        history_persistence_status = "degraded"
                        logger.exception("Could not persist live occupancy history for %s", session_id)
                zone_occupancy.append({
                    "zone_id": zone["zone_id"], "name": zone["name"],
                    "current_estimate": estimate, "capacity_status": capacity_status,
                    "capacity_ratio": capacity_ratio,
                    "trend_change": history[-1] - history[0] if len(history) > 1 else 0,
                    "observed_entries": zone_transition_totals[zone["zone_id"]]["entries"],
                    "observed_exits": zone_transition_totals[zone["zone_id"]]["exits"],
                    "entries_this_frame": transition_frame[zone["zone_id"]]["entries"],
                    "exits_this_frame": transition_frame[zone["zone_id"]]["exits"],
                    "data_kind": "estimated_active_person_tracks",
                    "observed_track_count": occupancy["observed_count"],
                    "temporally_carried_track_count": occupancy["carried_count"],
                    "retention_limit_missed_frames": tracker.max_missed_frames,
                    "occupancy_anomaly": occupancy_anomaly,
                    "early_warning": early_warning,
                    "security_attention": security_attention,
                    "occupancy_forecast": occupancy_forecast,
                })
            current_zones = [item["name"] for item in zone_occupancy if item["current_estimate"] > 0]
            source_times.append(now)
            inference_times.append(inference_finished)
            frame_count += 1
            inference_latency_ms = round((inference_finished - inference_started) * 1000, 1)
            total_detection_instances += len(detections)
            peak_estimated_visible_people = max(
                peak_estimated_visible_people,
                sum(track["class"] == "person" for track in tracker.active_tracks.values()),
            )
            last_inference_latency_ms = inference_latency_ms
            last_zone_occupancy = zone_occupancy
            alert_observed_at = datetime.now(timezone.utc).isoformat()
            occupancy_alerts = build_occupancy_signal_alerts(
                zone_occupancy,
                observed_at=alert_observed_at,
            )
            last_occupancy_alerts = occupancy_alerts
            if session_persisted:
                try:
                    repository.update_live_occupancy_alerts(
                        session_id, occupancy_alerts, observed_at=alert_observed_at
                    )
                except Exception:
                    history_persistence_status = "degraded"
                    logger.exception("Could not persist live occupancy-alert state for %s", session_id)
            response = {
                "type": "observation",
                "session_id": session_id,
                "source_kind": source_kind,
                **({"preview_jpeg": preview_jpeg} if preview_jpeg is not None else {}),
                "frame_number": frame_count,
                "session_elapsed_seconds": round(now - session_started, 3),
                "frame_width": width,
                "frame_height": height,
                "source_fps": _rate(source_times),
                "inference_fps": _rate(inference_times),
                "inference_latency_ms": inference_latency_ms,
                "detection_count": len(detections),
                "detections": [
                    {
                        "class": detection.class_name,
                        "confidence": detection.confidence,
                        "track_id": tracked_detections[index]["track_id"],
                        "direction": tracked_detections[index]["direction"],
                        "dwell_seconds": tracked_detections[index]["dwell_seconds"],
                        "bbox": {
                            "x1": detection.bbox[0], "y1": detection.bbox[1],
                            "x2": detection.bbox[2], "y2": detection.bbox[3],
                        },
                    }
                    for index, detection in enumerate(detections)
                ],
                "occupancy": {
                    "data_kind": "estimated_active_person_tracks",
                    "count": sum(track["class"] == "person" for track in tracker.active_tracks.values()),
                    "raw_person_detection_instances": sum(item.class_name == "person" for item in detections),
                    "observed_track_count": sum(item["class"] == "person" for item in tracked_detections),
                    "temporally_carried_track_count": sum(
                        track["class"] == "person" and track["missed_frames"] > 0
                        for track in tracker.active_tracks.values()
                    ),
                    "retention_limit_missed_frames": tracker.max_missed_frames,
                    "method": "short-lived anonymous IoU tracks observed now or retained for up to the configured missed-frame limit",
                    "limitations": "May miss or double-count people under occlusion, camera motion, track fragmentation, or detector error. A briefly missed track may remain counted in its last observed zone. This is not a unique-person count.",
                },
                "zone_occupancy": zone_occupancy,
                "occupancy_alerts": occupancy_alerts,
                "current_zones": current_zones,
                "zone_to_zone_transitions": [{
                    "from_zone_id": source_id,
                    "to_zone_id": target_id,
                    "observed_count": count,
                } for (source_id, target_id), count in sorted(zone_edge_totals.items())],
                "security_alerts": {
                    "status": "unavailable",
                    "reason": "No validated suspicious-object model is configured.",
                    "items": [],
                },
                "model": detector.model_name,
                "device": detector.device,
            }
            last_source_fps = response["source_fps"]
            last_inference_fps = response["inference_fps"]
            _set_live_status(
                status="live",
                source_kind=source_kind,
                source_fps=response["source_fps"],
                inference_fps=response["inference_fps"],
                inference_latency_ms=inference_latency_ms,
                detection_count=len(detections),
                frames_processed=frame_count,
                zone_occupancy=zone_occupancy,
                occupancy_alerts=occupancy_alerts,
                current_zones=current_zones,
                zone_to_zone_transitions=response["zone_to_zone_transitions"],
                history_persistence_status=history_persistence_status,
                ai_engine="online",
            )
            await websocket.send_json(response)
    except WebSocketDisconnect:
        pass
    except Exception:
        session_outcome = "failed"
        logger.exception("Live camera session failed for %s", session_id)
        _set_live_status(status="degraded", ai_engine="error", error="Live camera session failed.")
        try:
            await websocket.send_json({"type": "error", "detail": "Live camera session failed. Check backend logs."})
        except RuntimeError:
            pass
    finally:
        if source is not None:
            await asyncio.to_thread(source.release)
        if session_persisted:
            try:
                repository.finish_live_session(
                    session_id,
                    status=session_outcome,
                    summary={
                        "source_kind": source_kind,
                        "frames_processed": frame_count,
                        "total_detection_instances": total_detection_instances,
                        "peak_estimated_visible_people": peak_estimated_visible_people,
                        "last_source_fps": last_source_fps,
                        "last_inference_fps": last_inference_fps,
                        "last_inference_latency_ms": last_inference_latency_ms,
                        "model": model_name,
                        "device": device_name,
                        "zone_occupancy": last_zone_occupancy,
                        "occupancy_alerts": last_occupancy_alerts,
                        "zone_to_zone_transitions": [{
                            "from_zone_id": source_id,
                            "to_zone_id": target_id,
                            "observed_count": count,
                        } for (source_id, target_id), count in sorted(zone_edge_totals.items())],
                        "security_alerts_status": "unavailable",
                    },
                )
            except Exception:
                history_persistence_status = "degraded"
                logger.exception("Could not persist live-session summary for %s", session_id)
        release_pipeline(owner)
        current = get_live_status()
        if current.get("session_id") == session_id:
            _set_live_status(
                status="offline",
                source_fps=0.0,
                inference_fps=0.0,
                inference_latency_ms=None,
                detection_count=0,
                ai_engine="idle",
                source_kind=None,
                zone_occupancy=[],
                occupancy_alerts=[],
                current_zones=[],
                zone_to_zone_transitions=[],
                history_persistence_status=history_persistence_status,
            )
