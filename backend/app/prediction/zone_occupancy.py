"""Chronological moving-average forecasts for measured zone occupancy."""

import math
from typing import Any

HORIZONS_SECONDS = (60, 300, 600)
MIN_VALIDATION_WINDOWS = 3
TRAINING_WINDOWS = 3


def _errors(actual: list[float], predicted: list[float]) -> dict[str, float | int | None]:
    differences = [estimate - observed for estimate, observed in zip(predicted, actual)]
    mae = sum(abs(value) for value in differences) / len(differences)
    rmse = math.sqrt(sum(value * value for value in differences) / len(differences))
    mean = sum(actual) / len(actual)
    variance = sum((value - mean) ** 2 for value in actual)
    r_squared = 1 - sum(value * value for value in differences) / variance if variance > 0 else None
    nonzero_actuals = [(observed, estimate) for observed, estimate in zip(actual, predicted) if observed != 0]
    mape = (
        sum(abs(estimate - observed) / abs(observed) for observed, estimate in nonzero_actuals)
        / len(nonzero_actuals) * 100
        if nonzero_actuals else None
    )
    return {
        "mae": round(mae, 4),
        "rmse": round(rmse, 4),
        "r_squared": round(r_squared, 4) if r_squared is not None else None,
        "mape_percent": round(mape, 4) if mape is not None else None,
        "mape_samples": len(nonzero_actuals),
        "mape_zero_actuals_excluded": len(actual) - len(nonzero_actuals),
    }


def forecast_zone_occupancy(
    occupancy: dict[str, Any],
    *,
    bucket_seconds: int,
    horizons: tuple[int, ...] = HORIZONS_SECONDS,
) -> dict[str, Any]:
    """Forecast only complete tracked timelines with rolling-origin validation.

    A trailing horizon-window mean is compared against a persistence baseline.
    Forecasts require at least three training windows and three chronological
    validation windows; ties select the persistence baseline.
    """
    if bucket_seconds < 1 or any(horizon < 1 or horizon % bucket_seconds for horizon in horizons):
        raise ValueError("Forecast horizons must be positive multiples of bucket_seconds.")
    if occupancy.get("estimation_status") != "estimated":
        return {"status": "insufficient_data", "reason": "Complete track-aware occupancy observations are unavailable.", "forecasts": []}

    points = occupancy.get("timeline") or []
    indices: list[int] = []
    values: list[float] = []
    for point in points:
        value = point.get("estimated_mean_visible_people")
        start = point.get("bucket_start_seconds")
        if value is None or start is None or not math.isfinite(float(value)) or float(value) < 0:
            return {"status": "insufficient_data", "reason": "The occupancy timeline contains missing or invalid observations.", "forecasts": []}
        indices.append(int(start // bucket_seconds))
        values.append(float(value))
    if not values or any(right != left + 1 for left, right in zip(indices, indices[1:])):
        return {"status": "insufficient_data", "reason": "A continuous occupancy timeline is required.", "forecasts": []}

    as_of_seconds = round((indices[-1] + 1) * bucket_seconds, 3)

    forecasts = []
    for horizon in horizons:
        window = horizon // bucket_seconds
        origin = TRAINING_WINDOWS * window
        actuals: list[float] = []
        candidate_values: list[float] = []
        baseline_values: list[float] = []
        for start in range(origin, len(values) - window + 1, window):
            candidate_values.append(sum(values[start - window:start]) / window)
            baseline_values.append(values[start - 1])
            actuals.append(sum(values[start:start + window]) / window)
        if len(actuals) < MIN_VALIDATION_WINDOWS:
            forecasts.append({
                "horizon_seconds": horizon,
                "status": "insufficient_data",
                "reason": f"At least {TRAINING_WINDOWS + MIN_VALIDATION_WINDOWS} complete horizon windows are required for evaluation.",
                "validation_windows": len(actuals),
                "supporting_observations": len(values),
                "as_of_seconds": as_of_seconds,
                "forecast": None,
                "evaluation": None,
            })
            continue

        candidate_metrics = _errors(actuals, candidate_values)
        baseline_metrics = _errors(actuals, baseline_values)
        choose_candidate = candidate_metrics["mae"] < baseline_metrics["mae"]
        selected_metrics = candidate_metrics if choose_candidate else baseline_metrics
        latest = sum(values[-window:]) / window if choose_candidate else values[-1]
        forecasts.append({
            "horizon_seconds": horizon,
            "status": "available",
            "forecast": round(latest, 2),
            "target": "mean_estimated_visible_people_in_zone",
            "unit": "estimated visible people",
            "model": "trailing horizon-window mean" if choose_candidate else "persistence baseline (last observed occupancy)",
            "evaluation": {
                "validation": "chronological non-overlapping rolling-origin windows",
                "validation_windows": len(actuals),
                "selected_model": selected_metrics,
                "candidate_model": candidate_metrics,
                "baseline_model": baseline_metrics,
                "candidate_selected_only_if_mae_improves": True,
            },
            "uncertainty": {
                "method": "selected model rolling-origin MAE",
                "mae": selected_metrics["mae"],
                "range": [round(max(0.0, latest - selected_metrics["mae"]), 2), round(latest + selected_metrics["mae"], 2)],
                "probability_calibrated": False,
            },
            "supporting_observations": len(values),
            "as_of_seconds": as_of_seconds,
            "limitations": "This is a short-horizon estimate from one session, not a guarantee. Track errors propagate into occupancy and forecast error; validation is within-session and may not generalize to other days or camera conditions.",
        })

    return {
        "status": "available" if any(item["status"] == "available" for item in forecasts) else "insufficient_data",
        "data_kind": "zone_occupancy_forecast",
        "observed_bucket_seconds": bucket_seconds,
        "forecast_method": "rolling-origin comparison of trailing mean against persistence baseline",
        "forecasts": forecasts,
    }
