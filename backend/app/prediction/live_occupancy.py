"""Bounded, session-local occupancy history for live zone forecasts."""

from collections import deque
from typing import Any

from app.prediction.zone_occupancy import HORIZONS_SECONDS, forecast_zone_occupancy

LIVE_OCCUPANCY_BUCKET_SECONDS = 15
MAX_LIVE_OCCUPANCY_BUCKETS = max(HORIZONS_SECONDS) // LIVE_OCCUPANCY_BUCKET_SECONDS


class LiveOccupancyForecaster:
    """Aggregate live estimates into buckets and reuse the validated forecaster.

    Only completed buckets participate in forecasts. A missing bucket remains a
    visible gap in the timeline, causing the forecast service to return
    insufficient data rather than treating the missing period as zero people.
    """

    def __init__(self) -> None:
        self._zones: dict[str, dict[str, Any]] = {}

    def reset(self, zone_ids: list[str]) -> None:
        """Start fresh forecast histories after a zone-configuration change."""
        self._zones = {
            zone_id: {
                "active_bucket": None,
                "last_elapsed_seconds": None,
                "bucket_total": 0,
                "bucket_observations": 0,
                "last_completed_bucket": None,
                "timeline": deque(maxlen=MAX_LIVE_OCCUPANCY_BUCKETS),
                "forecast": self._insufficient_forecast(0),
            }
            for zone_id in zone_ids
        }

    @staticmethod
    def _insufficient_forecast(as_of_seconds: float) -> dict[str, Any]:
        result = forecast_zone_occupancy(
            {"estimation_status": "estimated", "timeline": []},
            bucket_seconds=LIVE_OCCUPANCY_BUCKET_SECONDS,
        )
        result["as_of_session_seconds"] = round(max(0.0, as_of_seconds), 2)
        return result

    def observe(self, zone_id: str, elapsed_seconds: float, estimate: int) -> dict[str, Any]:
        """Add one sampled estimate and return the latest validated forecast."""
        if elapsed_seconds < 0 or estimate < 0:
            raise ValueError("Live occupancy observations must be non-negative.")
        state = self._zones.get(zone_id)
        if state is None:
            self.reset([*self._zones, zone_id])
            state = self._zones[zone_id]
        last_elapsed = state["last_elapsed_seconds"]
        if last_elapsed is not None and elapsed_seconds < last_elapsed:
            raise ValueError("Live occupancy observations must be chronological.")
        state["last_elapsed_seconds"] = elapsed_seconds
        state["last_completed_bucket"] = None

        bucket_index = int(elapsed_seconds // LIVE_OCCUPANCY_BUCKET_SECONDS)
        active_bucket = state["active_bucket"]
        if active_bucket is None:
            state["active_bucket"] = bucket_index
        elif bucket_index > active_bucket:
            if state["bucket_observations"]:
                completed = {
                    "bucket_start_seconds": active_bucket * LIVE_OCCUPANCY_BUCKET_SECONDS,
                    "bucket_end_seconds": (active_bucket + 1) * LIVE_OCCUPANCY_BUCKET_SECONDS,
                    "observation_count": state["bucket_observations"],
                    "estimated_mean_visible_people": state["bucket_total"] / state["bucket_observations"],
                }
                state["last_completed_bucket"] = completed
                state["timeline"].append({
                    "bucket_start_seconds": active_bucket * LIVE_OCCUPANCY_BUCKET_SECONDS,
                    "estimated_mean_visible_people": completed["estimated_mean_visible_people"],
                })
            state["active_bucket"] = bucket_index
            state["bucket_total"] = 0
            state["bucket_observations"] = 0
            state["forecast"] = forecast_zone_occupancy(
                {"estimation_status": "estimated", "timeline": list(state["timeline"])},
                bucket_seconds=LIVE_OCCUPANCY_BUCKET_SECONDS,
            )
        elif bucket_index < active_bucket:
            raise ValueError("Live occupancy observations must be chronological.")

        state["bucket_total"] += estimate
        state["bucket_observations"] += 1
        result = dict(state["forecast"])
        result["as_of_session_seconds"] = round(elapsed_seconds, 2)
        return result

    def take_completed_bucket(self, zone_id: str) -> dict[str, Any] | None:
        """Return the latest bucket closed by observe(), exactly once."""
        state = self._zones.get(zone_id)
        if state is None:
            return None
        completed = state["last_completed_bucket"]
        state["last_completed_bucket"] = None
        return dict(completed) if completed is not None else None
