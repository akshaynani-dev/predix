"""Explainable crowd early-warning cues from configured occupancy evidence."""

import math
from typing import Any


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def build_crowd_early_warning(occupancy: dict[str, Any], anomaly: dict[str, Any]) -> dict[str, Any]:
    """Combine capacity status and a recent occupancy deviation without risk scores."""
    if (
        occupancy.get("estimation_status") != "estimated"
        or occupancy.get("status") not in {"LOW", "MODERATE", "HIGH", "CRITICAL"}
    ):
        return {
            "status": "insufficient_data",
            "signals": [],
            "recommendation": None,
            "interpretation": "Complete tracked occupancy and an operator-configured zone capacity are required.",
        }
    anomaly_status = anomaly.get("status")
    latest_signal = anomaly.get("latest_signal")
    complete_deviation = (
        isinstance(latest_signal, dict)
        and all(_finite_number(latest_signal.get(key)) for key in (
            "observed_occupancy", "baseline_median", "increase_over_baseline",
        ))
        and isinstance(latest_signal.get("evidence"), str)
        and bool(latest_signal["evidence"])
    )
    if (
        anomaly_status == "insufficient_data"
        or anomaly_status not in {"deviation_signal", "no_deviation_signal"}
        or (anomaly_status == "deviation_signal" and not complete_deviation)
    ):
        return {
            "status": "insufficient_data",
            "signals": [],
            "recommendation": None,
            "interpretation": "A valid, sufficient occupancy baseline result is required for the configured deviation check.",
        }

    signals = []
    capacity_status = occupancy["status"]
    if capacity_status in {"HIGH", "CRITICAL"}:
        if (
            not _finite_number(occupancy.get("current_estimate"))
            or not _finite_number(occupancy.get("configured_capacity"))
            or occupancy["configured_capacity"] <= 0
            or not _finite_number(occupancy.get("capacity_ratio"))
        ):
            return {
                "status": "insufficient_data",
                "signals": [],
                "recommendation": None,
                "interpretation": "Complete occupancy and configured-capacity evidence is required for an early-warning assessment.",
            }
        signals.append({
            "signal": "configured_capacity_level",
            "status": capacity_status,
            "occupancy_estimate": occupancy["current_estimate"],
            "configured_capacity": occupancy["configured_capacity"],
            "capacity_ratio": occupancy["capacity_ratio"],
        })
    if anomaly_status == "deviation_signal":
        signals.append({"signal": "recent_occupancy_deviation", **latest_signal})

    elevated = len(signals) >= 2
    return {
        "status": "elevated" if elevated else "no_combined_signal",
        "signals": signals,
        "recommendation": "Human verification recommended for the combined occupancy signals." if elevated else None,
        "risk_score": None,
        "confidence": None,
        "interpretation": (
            "Two configured occupancy signals co-occurred. This is an early-warning cue for human review, not an emergency determination or a prediction that an event will occur."
            if elevated else
            "The configured occupancy conditions did not combine in these observations; this is not evidence that an incident will or will not occur."
        ),
        "policy_validation": "Rule output is explainable but has not been validated against labeled incidents or site-specific outcomes.",
    }
