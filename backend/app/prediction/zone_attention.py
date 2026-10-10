"""Explainable operator-review cues based on configured zone observations."""

from typing import Any


def recommend_zone_attention(occupancy: dict[str, Any], anomaly: dict[str, Any]) -> dict[str, Any]:
    """Recommend human review from capacity and deviation rules, never staffing actions."""
    if (
        occupancy.get("estimation_status") != "estimated"
        or occupancy.get("status") in {"UNAVAILABLE", "UNCONFIGURED"}
        or not occupancy.get("configured_capacity")
    ):
        return {
            "status": "unavailable",
            "signals": [],
            "recommendation": None,
            "basis": "Track-aware occupancy and an operator-configured capacity are required.",
            "limitation": "This advisory does not determine safety or allocate security resources.",
        }

    signals = []
    capacity_status = occupancy.get("status")
    if capacity_status in {"HIGH", "CRITICAL"}:
        signals.append({
            "signal": "configured_capacity_level",
            "status": capacity_status,
            "occupancy_estimate": occupancy.get("current_estimate"),
            "configured_capacity": occupancy.get("configured_capacity"),
            "capacity_ratio": occupancy.get("capacity_ratio"),
        })

    if anomaly.get("status") not in {"deviation_signal", "no_deviation_signal"}:
        if signals:
            return {
                "status": "capacity_review",
                "signals": signals,
                "recommendation": "Review this zone against its operator-configured occupancy capacity; the occupancy-deviation baseline is insufficient.",
                "basis": "Operator-configured capacity threshold; the deviation rule has not accumulated enough history.",
                "validation_status": "Rule has not been validated against labeled incidents or site-specific outcomes.",
                "limitation": "Decision support for human review only; unavailable anomaly history must not be interpreted as absence of risk.",
            }
        return {
            "status": "insufficient_data",
            "signals": [],
            "recommendation": None,
            "basis": "The occupancy-deviation rule has not accumulated enough history to assess changes from baseline.",
            "limitation": "No recommendation is made from incomplete anomaly history; this does not mean the zone is safe.",
        }

    latest_deviation = anomaly.get("latest_signal")
    if anomaly.get("status") == "deviation_signal" and latest_deviation:
        signals.append({
            "signal": "recent_occupancy_deviation",
            "evidence": latest_deviation.get("evidence"),
            "increase_over_baseline": latest_deviation.get("increase_over_baseline"),
        })

    if len(signals) == 2:
        status = "priority_review"
        recommendation = "Human review for security attention is recommended: configured capacity and recent occupancy-deviation signals coincide."
    elif signals and signals[0]["signal"] == "configured_capacity_level":
        status = "capacity_review"
        recommendation = "Review this zone against its operator-configured occupancy capacity."
    elif signals:
        status = "occupancy_change_review"
        recommendation = "Review the recent occupancy increase against local operating conditions."
    else:
        status = "no_configured_trigger"
        recommendation = "No configured occupancy rule currently calls for additional attention; this does not mean the zone is safe."

    return {
        "status": status,
        "signals": signals,
        "recommendation": recommendation,
        "basis": "Operator-configured capacity thresholds and the configured trailing-median/scaled-MAD occupancy-deviation rule.",
        "validation_status": "Rule has not been validated against labeled incidents or site-specific outcomes.",
        "limitation": "Decision support for human review only; it does not assess intent, determine an emergency, prescribe staffing, or allocate security resources.",
    }
