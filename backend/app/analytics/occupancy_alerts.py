"""Convert current measured zone signals into grouped operator-facing alerts."""

from datetime import datetime, timezone
from typing import Any


def build_occupancy_signal_alerts(
    zones: list[dict[str, Any]], *, observed_at: str | None = None
) -> list[dict[str, Any]]:
    """Return at most one active, evidence-linked occupancy alert per zone."""
    timestamp = observed_at or datetime.now(timezone.utc).isoformat()
    alerts = []
    for zone in zones:
        occupancy = zone.get("occupancy") or {}
        capacity_status = zone.get("capacity_status") or occupancy.get("status")
        current_estimate = zone.get("current_estimate", occupancy.get("current_estimate"))
        capacity = zone.get("configured_capacity", occupancy.get("configured_capacity"))
        capacity_ratio = zone.get("capacity_ratio", occupancy.get("capacity_ratio"))
        anomaly = zone.get("occupancy_anomaly") or zone.get("anomaly") or {}
        early_warning = zone.get("early_warning") or {}
        attention = zone.get("security_attention") or {}

        capacity_signal = capacity_status in {"HIGH", "CRITICAL"}
        deviation_signal = anomaly.get("status") == "deviation_signal" and bool(anomaly.get("latest_signal"))
        combined_signal = early_warning.get("status") == "elevated" and capacity_signal and deviation_signal
        if not (capacity_signal or deviation_signal):
            continue

        if combined_signal:
            severity = "CRITICAL" if capacity_status == "CRITICAL" else "WARNING"
            signal = "configured_capacity_and_occupancy_deviation"
        elif capacity_status == "CRITICAL":
            severity = "CRITICAL"
            signal = "configured_capacity_level"
        elif capacity_status == "HIGH":
            severity = "WARNING"
            signal = "configured_capacity_level"
        else:
            severity = "WATCH"
            signal = "recent_occupancy_deviation"

        evidence = []
        if capacity_signal:
            evidence.append({
                "signal": "configured_capacity_level",
                "status": capacity_status,
                "estimated_occupancy": current_estimate,
                "configured_capacity": capacity,
                "capacity_ratio": capacity_ratio,
                "description": (
                    f"Estimated visible-person occupancy {current_estimate} against "
                    f"operator-configured capacity {capacity} ({capacity_ratio:.0%})."
                    if isinstance(capacity_ratio, (int, float)) else
                    f"Estimated visible-person occupancy is {current_estimate}; configured capacity status is {capacity_status}."
                ),
            })
        if deviation_signal:
            latest = anomaly["latest_signal"]
            evidence.append({
                "signal": "recent_occupancy_deviation",
                "description": latest.get("evidence", "Configured occupancy-deviation rule signaled."),
                "baseline_median": latest.get("baseline_median"),
                "observed_occupancy": latest.get("observed_occupancy"),
                "increase_over_baseline": latest.get("increase_over_baseline"),
            })

        recommendation = attention.get("recommendation")
        if not recommendation:
            recommendation = (
                "Human review recommended against the operator-configured occupancy capacity."
                if capacity_signal else
                "Review the measured occupancy deviation against local operating conditions."
            )
        zone_id = str(zone.get("zone_id", "unknown"))
        alerts.append({
            "alert_id": f"occupancy:{zone_id}",
            "deduplication_key": f"occupancy:{zone_id}",
            "severity": severity,
            "timestamp": timestamp,
            "zone_id": zone_id,
            "zone": zone.get("name", zone_id),
            "signal": signal,
            "confidence": None,
            "confidence_note": "Not applicable: this is a configured occupancy rule, not a probabilistic model output.",
            "supporting_evidence": evidence,
            "recommendation": recommendation,
            "status": "active",
            "category": "occupancy_signal_not_incident_alert",
            "limitations": "A track-based occupancy estimate and configured rule can be wrong. This alert does not identify a threat, establish an emergency, or predict an incident.",
        })
    return alerts
