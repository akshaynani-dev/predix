"""Evidence-only occupancy deviations against a trailing local baseline."""

from statistics import median
import math
from typing import Any


def detect_occupancy_deviations(
    values: list[float],
    *,
    baseline_buckets: int = 6,
    mad_multiplier: float = 3.0,
    minimum_increase: float = 1.0,
) -> dict[str, Any]:
    """Flag large upward deviations; this is not an emergency or risk model."""
    if baseline_buckets < 2 or mad_multiplier <= 0 or minimum_increase < 0:
        raise ValueError("Invalid occupancy anomaly configuration.")
    if len(values) <= baseline_buckets:
        return {
            "status": "insufficient_data",
            "message": f"At least {baseline_buckets + 1} consecutive occupancy buckets are required.",
            "signals": [],
        }

    signals = []
    for index in range(baseline_buckets, len(values)):
        baseline = values[index - baseline_buckets:index]
        center = median(baseline)
        mad = median([abs(value - center) for value in baseline])
        robust_scale = 1.4826 * mad
        cutoff = center + mad_multiplier * robust_scale
        current = values[index]
        increase = current - center
        if current > cutoff and increase >= minimum_increase:
            signals.append({
                "bucket_index": index,
                "observed_occupancy": round(current, 2),
                "baseline_median": round(center, 2),
                "baseline_mad": round(mad, 2),
                "robust_upper_cutoff": round(cutoff, 2),
                "increase_over_baseline": round(increase, 2),
                "evidence": f"Observed estimate {current:.2f} exceeded trailing median {center:.2f} plus {mad_multiplier:g} scaled MAD and minimum increase {minimum_increase:g}.",
            })
    return {
        "status": "deviation_signal" if signals else "no_deviation_signal",
        "baseline_method": f"median and scaled MAD of preceding {baseline_buckets} occupancy buckets",
        "baseline_buckets": baseline_buckets,
        "mad_multiplier": mad_multiplier,
        "minimum_increase": minimum_increase,
        "signals": signals,
        "latest_signal": signals[-1] if signals else None,
        "interpretation": "A statistical deviation from recent occupancy observations only; not evidence of an emergency, crime, intent, or future event.",
        "validation_status": "not evaluated against labeled anomaly events",
    }


def detect_activity_deviations(
    timeline: list[dict[str, Any]],
    *,
    bucket_seconds: int,
    baseline_buckets: int = 6,
    mad_multiplier: float = 3.0,
    minimum_increase: float = 1.0,
) -> dict[str, Any]:
    """Flag increases in detector instances per sampled frame against a contiguous local baseline.

    This measures model output volume, not people, unique objects, or incident risk.
    Missing or malformed buckets break a baseline run and are never treated as zero.
    """
    if (
        bucket_seconds < 1
        or baseline_buckets < 2
        or mad_multiplier <= 0
        or minimum_increase < 0
        or not math.isfinite(mad_multiplier)
        or not math.isfinite(minimum_increase)
    ):
        raise ValueError("Invalid activity-deviation configuration.")

    runs: list[list[tuple[int, float]]] = []
    current_run: list[tuple[int, float]] = []
    previous_index: int | None = None
    for bucket in timeline:
        start = bucket.get("bucket_start_seconds")
        value = bucket.get("average_instances_per_observed_frame")
        observed_frames = bucket.get("observed_frames")
        valid = (
            isinstance(start, (int, float))
            and not isinstance(start, bool)
            and math.isfinite(start)
            and start >= 0
            and start % bucket_seconds == 0
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
            and value >= 0
            and isinstance(observed_frames, int)
            and not isinstance(observed_frames, bool)
            and observed_frames > 0
        )
        if not valid:
            if current_run:
                runs.append(current_run)
                current_run = []
            previous_index = None
            continue

        bucket_index = int(start // bucket_seconds)
        if previous_index is not None and bucket_index != previous_index + 1:
            runs.append(current_run)
            current_run = []
        current_run.append((bucket_index, float(value)))
        previous_index = bucket_index
    if current_run:
        runs.append(current_run)

    signals = []
    evaluated_windows = 0
    for run in runs:
        values = [value for _, value in run]
        for position in range(baseline_buckets, len(values)):
            baseline = values[position - baseline_buckets:position]
            center = median(baseline)
            mad = median([abs(value - center) for value in baseline])
            cutoff = center + mad_multiplier * 1.4826 * mad
            observed = values[position]
            increase = observed - center
            evaluated_windows += 1
            if observed > cutoff and increase >= minimum_increase:
                signals.append({
                    "bucket_start_seconds": run[position][0] * bucket_seconds,
                    "observed_instances_per_frame": round(observed, 4),
                    "baseline_median_instances_per_frame": round(center, 4),
                    "baseline_mad": round(mad, 4),
                    "robust_upper_cutoff": round(cutoff, 4),
                    "increase_over_baseline": round(increase, 4),
                    "evidence": (
                        f"Observed detector output {observed:.2f} instances per sampled frame exceeded "
                        f"the preceding {baseline_buckets}-bucket median {center:.2f} plus "
                        f"{mad_multiplier:g} scaled MAD and the configured minimum increase {minimum_increase:g}."
                    ),
                })

    if evaluated_windows == 0:
        return {
            "status": "insufficient_data",
            "metric": "average_instances_per_observed_frame",
            "bucket_seconds": bucket_seconds,
            "baseline_buckets": baseline_buckets,
            "required_consecutive_buckets": baseline_buckets + 1,
            "signals": [],
            "latest_signal": None,
            "interpretation": "A contiguous observed activity baseline is required; missing buckets are not imputed.",
            "validation_status": "not evaluated against labeled activity anomalies",
        }

    return {
        "status": "deviation_signal" if signals else "no_deviation_signal",
        "metric": "average_instances_per_observed_frame",
        "bucket_seconds": bucket_seconds,
        "baseline_method": f"median and scaled MAD of preceding {baseline_buckets} consecutive observed buckets",
        "baseline_buckets": baseline_buckets,
        "mad_multiplier": mad_multiplier,
        "minimum_increase": minimum_increase,
        "evaluated_windows": evaluated_windows,
        "signals": signals,
        "latest_signal": signals[-1] if signals else None,
        "interpretation": "A deviation in detector output volume only; it is not an occupancy estimate, incident determination, or future-event prediction.",
        "validation_status": "not evaluated against labeled activity anomalies",
    }
