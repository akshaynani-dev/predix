"""Time-based aggregation of sampled frame detections."""

import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

from app.analytics.anomalies import detect_activity_deviations


class AnalyticsDataError(ValueError):
    """Raised when persisted observations are invalid or too large to aggregate."""


def build_temporal_analytics(
    detections_path: Path,
    bucket_seconds: int,
    *,
    activity_baseline_buckets: int = 6,
    activity_mad_multiplier: float = 3.0,
    activity_minimum_increase: float = 1.0,
) -> dict[str, Any]:
    """Aggregate observed object counts into video-relative time buckets."""
    if bucket_seconds < 1:
        raise ValueError("Time bucket must be at least one second.")
    if not detections_path.is_file():
        raise FileNotFoundError("Frame-level detection results were not found.")

    buckets: dict[int, dict[str, Any]] = {}
    sampled_frames = 0
    total_detections = 0
    counts_by_class: dict[str, int] = defaultdict(int)
    confidence_bin_labels = ["0.00–0.24", "0.25–0.49", "0.50–0.74", "0.75–1.00"]
    confidence_bins = [0, 0, 0, 0]
    try:
        with detections_path.open("r", encoding="utf-8") as source:
            for line_number, line in enumerate(source, start=1):
                try:
                    record = json.loads(line)
                    timestamp = float(record["timestamp_seconds"])
                    detections = record["detections"]
                    if not math.isfinite(timestamp) or timestamp < 0 or not isinstance(detections, list):
                        raise ValueError
                except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                    raise AnalyticsDataError(
                        f"Invalid detection record at line {line_number}."
                    ) from exc

                bucket_index = int(timestamp // bucket_seconds)
                if bucket_index >= 10_000:
                    raise AnalyticsDataError(
                        "The requested time bucket creates too many periods; increase bucket_seconds."
                    )
                bucket = buckets.setdefault(bucket_index, {
                    "observed_frames": 0,
                    "detection_instances": 0,
                    "counts_by_class": defaultdict(int),
                })
                bucket["observed_frames"] += 1
                sampled_frames += 1
                for detection in detections:
                    try:
                        object_class = str(detection["class"])
                        confidence = float(detection["confidence"])
                        if not object_class or not math.isfinite(confidence) or not 0 <= confidence <= 1:
                            raise ValueError
                    except (KeyError, TypeError, ValueError) as exc:
                        raise AnalyticsDataError(
                            f"Invalid detection in record at line {line_number}."
                        ) from exc
                    bucket["detection_instances"] += 1
                    bucket["counts_by_class"][object_class] += 1
                    total_detections += 1
                    counts_by_class[object_class] += 1
                    confidence_bins[min(int(confidence * 4), 3)] += 1
    except OSError as exc:
        raise AnalyticsDataError("Could not read stored detection observations.") from exc

    timeline = []
    for bucket_index, bucket in sorted(buckets.items()):
        average = bucket["detection_instances"] / bucket["observed_frames"]
        timeline.append({
            "bucket_start_seconds": bucket_index * bucket_seconds,
            "bucket_end_seconds": (bucket_index + 1) * bucket_seconds,
            "observed_frames": bucket["observed_frames"],
            "detection_instances": bucket["detection_instances"],
            "average_instances_per_observed_frame": round(average, 4),
            "counts_by_class": dict(sorted(bucket["counts_by_class"].items())),
        })

    activity_deviation = detect_activity_deviations(
        timeline,
        bucket_seconds=bucket_seconds,
        baseline_buckets=activity_baseline_buckets,
        mad_multiplier=activity_mad_multiplier,
        minimum_increase=activity_minimum_increase,
    )

    if timeline:
        peak = max(timeline, key=lambda item: item["average_instances_per_observed_frame"])
        quiet = min(timeline, key=lambda item: item["average_instances_per_observed_frame"])
        bucket_averages = [item["average_instances_per_observed_frame"] for item in timeline]
        statistics: dict[str, Any] = {
            "minimum_bucket_average": round(min(bucket_averages), 4),
            "maximum_bucket_average": round(max(bucket_averages), 4),
            "mean_instances_per_observed_frame": round(
                total_detections / sampled_frames, 4
            ),
            "peak_period": {
                "bucket_start_seconds": peak["bucket_start_seconds"],
                "bucket_end_seconds": peak["bucket_end_seconds"],
                "average_instances_per_observed_frame": peak[
                    "average_instances_per_observed_frame"
                ],
            },
            "quiet_period": {
                "bucket_start_seconds": quiet["bucket_start_seconds"],
                "bucket_end_seconds": quiet["bucket_end_seconds"],
                "average_instances_per_observed_frame": quiet[
                    "average_instances_per_observed_frame"
                ],
            },
        }
    else:
        statistics = {
            "minimum_bucket_average": None,
            "maximum_bucket_average": None,
            "mean_instances_per_observed_frame": None,
            "peak_period": None,
            "quiet_period": None,
        }

    return {
        "observation_source": "stored_frame_detections",
        "time_basis": "video_seconds",
        "sampled_frames": sampled_frames,
        "total_detection_instances": total_detections,
        "counts_by_class": dict(sorted(counts_by_class.items())),
        "confidence_distribution": [
            {"range": label, "count": count}
            for label, count in zip(confidence_bin_labels, confidence_bins)
        ],
        "aggregation": {
            "bucket_seconds": bucket_seconds,
            "timeline": timeline,
            "statistics": statistics,
        },
        "activity_deviation": activity_deviation,
    }
