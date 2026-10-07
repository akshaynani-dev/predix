"""Evidence-linked, conservative recommendations from evaluated forecasts."""

from typing import Any

from app.prediction.forecast import evaluate_and_predict_activity_rate


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = (len(ordered) - 1) * fraction
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    weight = index - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def build_decision_support(sessions: list[dict[str, Any]]) -> dict[str, Any]:
    """Compare a qualified forecast with the matching historical distribution."""
    forecast = evaluate_and_predict_activity_rate(sessions)
    if forecast["status"] != "available":
        return {
            "data_kind": "decision_support",
            "status": "insufficient_data",
            "message": "Insufficient data for reliable prediction; no recommendation generated.",
            "recommendations": [],
            "forecast_status": forecast["status"],
        }

    config = forecast["model_configuration"]
    expected_fields = ("model", "confidence_threshold", "frame_stride", "image_size")
    expected_config = tuple(config[field] for field in expected_fields)
    rates = []
    for session in sessions:
        summary = session.get("summary") or {}
        if any(summary.get(field) is None for field in expected_fields):
            continue
        inference_frames = int(summary.get("inference_frames") or 0)
        if inference_frames <= 0:
            continue
        if tuple(summary[field] for field in expected_fields) != expected_config:
            continue
        rates.append({
            "video_id": session["video_id"],
            "rate": summary["total_detection_instances"] / inference_frames,
        })

    rates.sort(key=lambda item: item["rate"])
    threshold = _percentile([item["rate"] for item in rates], 0.75)
    predicted = forecast["prediction"]["expected_value"]
    recommendation = []
    if predicted > threshold:
        recommendation.append({
            "type": "review_resource_plan",
            "level": "consider",
            "message": "Consider reviewing the next session's resource plan: estimated activity is above the 75th percentile of compatible historical sessions.",
            "basis": {
                "target": "object_instances_per_sampled_frame",
                "predicted_value": predicted,
                "historical_75th_percentile": round(threshold, 4),
                "historical_session_count": len(rates),
                "supporting_video_ids": [row["video_id"] for row in rates],
            },
        })
    return {
        "data_kind": "decision_support",
        "status": "available",
        "message": (
            "Review this suggestion alongside local context; it is not an operational directive."
            if recommendation else
            "Current evidence does not indicate activity above the compatible historical 75th percentile."
        ),
        "recommendations": recommendation,
        "forecast": forecast,
        "comparison": {
            "method": "compatible_session_activity_rate_75th_percentile",
            "historical_75th_percentile": round(threshold, 4),
            "historical_session_count": len(rates),
        },
    }
