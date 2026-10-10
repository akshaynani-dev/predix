"""Rolling-origin moving-average forecast for next-session activity rate."""

import math
from collections import defaultdict
from typing import Any

MINIMUM_SESSIONS = 6
WINDOW_SESSIONS = 3


def evaluate_and_predict_activity_rate(sessions: list[dict[str, Any]]) -> dict[str, Any]:
    """Evaluate a trailing mean chronologically before issuing a forecast."""
    usable = []
    for session in sessions:
        summary = session.get("summary") or {}
        inference_frames = int(summary.get("inference_frames") or 0)
        if inference_frames <= 0:
            continue
        expected_fields = ("model", "confidence_threshold", "frame_stride", "image_size")
        if any(summary.get(field) is None for field in expected_fields):
            continue
        usable.append({
            "video_id": session["video_id"],
            "created_at": session["created_at"],
            "summary": summary,
            "activity_rate": summary["total_detection_instances"] / inference_frames,
            "configuration": (
                summary["model"],
                summary["confidence_threshold"],
                summary["frame_stride"],
                summary["image_size"],
            ),
        })

    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for session in usable:
        groups[session["configuration"]].append(session)
    if groups:
        group = sorted(groups.values(), key=lambda items: (-len(items), str(items[0]["configuration"])))[0]
        group.sort(key=lambda item: (item["created_at"], item["video_id"]))
    else:
        group = []

    if len(group) < MINIMUM_SESSIONS:
        return {
            "data_kind": "prediction",
            "status": "insufficient_data",
            "message": "Insufficient data for reliable prediction.",
            "observed_sessions": len(group),
            "minimum_sessions": MINIMUM_SESSIONS,
            "prediction": None,
            "evaluation": None,
        }

    values = [float(session["activity_rate"]) for session in group]
    actuals: list[float] = []
    estimates: list[float] = []
    for target_index in range(WINDOW_SESSIONS, len(values)):
        prior = values[max(0, target_index - WINDOW_SESSIONS):target_index]
        estimates.append(sum(prior) / len(prior))
        actuals.append(values[target_index])

    errors = [estimate - actual for estimate, actual in zip(estimates, actuals)]
    absolute_errors = [abs(error) for error in errors]
    mae = sum(absolute_errors) / len(absolute_errors)
    mse = sum(error * error for error in errors) / len(errors)
    actual_mean = sum(actuals) / len(actuals)
    total_variation = sum((actual - actual_mean) ** 2 for actual in actuals)
    r_squared = (
        1 - sum(error * error for error in errors) / total_variation
        if total_variation > 0 else None
    )
    nonzero_actuals = [(actual, estimate) for actual, estimate in zip(actuals, estimates) if actual != 0]
    mape = (
        sum(abs(estimate - actual) / abs(actual) for actual, estimate in nonzero_actuals)
        / len(nonzero_actuals) * 100
        if nonzero_actuals else None
    )

    final_window = values[-WINDOW_SESSIONS:]
    expected_rate = sum(final_window) / len(final_window)
    training_ids = [session["video_id"] for session in group[-WINDOW_SESSIONS:]]
    model_name = f"Trailing mean of previous {WINDOW_SESSIONS} sessions"
    return {
        "data_kind": "prediction",
        "status": "available",
        "prediction": {
            "target": "object_instances_per_sampled_frame",
            "expected_value": round(expected_rate, 4),
            "period": "next observed session",
            "model": model_name,
            "supporting_session_count": len(group),
            "supporting_video_ids": training_ids,
            "uncertainty": {
                "method": "rolling_origin_mean_absolute_error",
                "mae": round(mae, 4),
                "estimated_range": {
                    "minimum": round(max(0.0, expected_rate - mae), 4),
                    "maximum": round(expected_rate + mae, 4),
                },
                "calibrated_probability": False,
            },
        },
        "evaluation": {
            "validation": "rolling_origin_time_ordered",
            "test_windows": len(actuals),
            "mae": round(mae, 4),
            "mse": round(mse, 4),
            "rmse": round(math.sqrt(mse), 4),
            "r_squared": round(r_squared, 4) if r_squared is not None else None,
            "mape_percent": round(mape, 4) if mape is not None else None,
            "mape_samples": len(nonzero_actuals),
            "mape_zero_actuals_excluded": len(actuals) - len(nonzero_actuals),
            "window_sessions": WINDOW_SESSIONS,
            "evaluated_sessions": [session["video_id"] for session in group[WINDOW_SESSIONS:]],
        },
        "observed_sessions": len(group),
        "model_configuration": {
            "model": group[-1]["summary"]["model"],
            "confidence_threshold": group[-1]["summary"]["confidence_threshold"],
            "frame_stride": group[-1]["summary"]["frame_stride"],
            "image_size": group[-1]["summary"]["image_size"],
        },
    }
