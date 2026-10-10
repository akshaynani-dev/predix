"""Declare available intelligence capabilities and their evidence limits."""

from fastapi import APIRouter
from app.cv.config import cv_settings
from app.cv.runtime import loaded_model_class_names
from app.core.config import settings

router = APIRouter()


@router.get("/capabilities", tags=["Capabilities"])
def capabilities() -> dict:
    model_classes = loaded_model_class_names()
    potentially_sensitive_labels = {"knife", "handgun", "pistol", "rifle", "gun", "baseball bat", "baton", "rod"}
    return {
        "data_kind": "configured_capabilities",
        "general_object_detection": {
            "status": "available",
            "model": cv_settings.MODEL_NAME,
            "configuration": {
                "confidence_threshold": cv_settings.DEFAULT_CONF_THRESHOLD,
                "image_size": cv_settings.DEFAULT_IMAGE_SIZE,
                "frame_stride": cv_settings.FRAME_STRIDE,
                "device": cv_settings.DEVICE,
            },
            "class_vocabulary": {
                "status": "available" if model_classes is not None else "not_loaded",
                "classes": model_classes,
                "potentially_sensitive_label_matches": sorted(set(model_classes or []) & potentially_sensitive_labels),
                "interpretation": "Model labels are generic detections, not validated suspicious-object signals or alerts.",
            },
        },
        "anonymous_live_tracking": {
            "status": "available",
            "method": "short-lived greedy IoU box association",
            "configuration": {
                "iou_threshold": cv_settings.TRACK_IOU_THRESHOLD,
                "max_missed_frames": cv_settings.TRACK_MAX_MISSED_FRAMES,
                "update_cadence": "every inferred frame; FRAME_STRIDE controls uploaded-video inference cadence and the frontend live frame interval controls live-source cadence",
            },
        },
        "rtsp_source_adapter": {
            "status": "configured" if settings.rtsp_allowed_hosts else "disabled",
            "allowlisted_host_count": len(settings.rtsp_allowed_hosts),
            "open_timeout_ms": settings.RTSP_OPEN_TIMEOUT_MS,
            "read_timeout_ms": settings.RTSP_READ_TIMEOUT_MS,
            "session_gateway": "available_via_live_websocket_when_host_is_allowlisted",
            "frontend": "available_in_live_camera_view",
            "protocol": "start_rtsp JSON message followed by next_frame requests on /api/live/ws",
            "note": "RTSP sessions share the detector pipeline; the UI uses bounded reconnect attempts and releases the source on stop or disconnect.",
        },
        "hls_source_adapter": {
            "status": "available_when_browser_supports_native_hls",
            "delivery": "The operator browser plays HTTPS HLS directly; PREDIX samples the video element and sends frames to the shared live-analysis WebSocket.",
            "backend_fetches_playlist": False,
            "requirements": ["native HLS playback", "HTTPS .m3u8 URL", "anonymous CORS permission for canvas frame sampling"],
            "limitations": "No server-side HLS gateway is implemented. The source URL remains in page memory and is not persisted in session history.",
        },
        "live_visible_person_estimate": {
            "status": "available",
            "method": f"anonymous active person tracks, retained for at most {cv_settings.TRACK_MAX_MISSED_FRAMES} missed sampled frames; raw detections and briefly carried tracks are reported separately",
            "unique_person_count": False,
        },
        "uploaded_zone_occupancy": {"status": "available_when_track_data_and_polygon_exist", "capacity_status": "requires_operator_configured_capacity"},
        "zone_occupancy_forecast": {"status": "available_when_chronological_validation_is_sufficient", "horizons_seconds": [60, 300, 600]},
        "live_zone_occupancy_forecast": {"status": "available_when_continuous_live_history_supports_rolling_validation", "bucket_seconds": 15, "horizons_seconds": [60, 300, 600], "minimum_observation_spans_seconds": {"60": 360, "300": 1800, "600": 3600}, "missing_buckets": "forecast unavailable until a continuous validation timeline is available"},
        "occupancy_deviation_signal": {"status": "available_when_baseline_history_is_sufficient", "validation": "not evaluated against labeled anomaly events"},
        "detector_activity_deviation": {
            "status": "available_when_consecutive_temporal_buckets_support_a_baseline",
            "metric": "average detector instances per sampled frame",
            "default_configuration": {"bucket_seconds": 15, "baseline_buckets": 6, "mad_multiplier": 3.0, "minimum_increase": 1.0},
            "configurable_via": "/api/video/{video_id}/analysis/temporal query parameters",
            "missing_bucket_policy": "breaks the baseline; no imputation",
            "interpretation": "detector output volume only; not occupancy, incident risk, or a future-event prediction",
            "validation": "not evaluated against labeled activity anomalies",
        },
        "live_zone_occupancy": {"status": "available_when_operator_configures_polygon", "persistence": "aggregate_session_summaries_in_sqlite; live_track_membership_and_zone_settings_remain_in_memory", "capacity_status": "requires_operator_configured_capacity"},
        "live_occupancy_deviation": {"status": "available_after_seven_consecutive_zone_observations", "method": "trailing median and scaled MAD; not validated against labeled anomaly events"},
        "live_occupancy_signal_alerts": {"status": "available_for_high_configured_capacity_or_occupancy_deviation", "deduplication": "one current alert per zone, grouped across concurrent occupancy signals", "confidence": "not_applicable_rule_based", "not_a_security_or_incident_alert": True},
        "suspicious_object_detection": {"status": "unavailable", "reason": "No validated, configured suspicious-object model and representative evaluation dataset are present."},
        "security_alerts": {"status": "unavailable", "reason": "No validated suspicious-object signal is configured; generic object labels do not trigger security alerts."},
        "risk_classification": {"status": "unavailable", "reason": "No validated risk model or policy is configured."},
        "early_warning": {"status": "available_when_configured_capacity_and_occupancy_deviation_cooccur", "validation": "Rule output has not been validated against labeled incidents; it provides no risk score or emergency determination."},
        "security_recommendations": {"status": "zone_review_advisory_when_capacity_is_configured", "basis": "Operator-configured occupancy capacity and trailing occupancy-deviation rules.", "validation": "Not validated against labeled incidents or site-specific outcomes; recommends human review only and does not prescribe staffing or allocate security resources."},
        "human_review_required": True,
    }
