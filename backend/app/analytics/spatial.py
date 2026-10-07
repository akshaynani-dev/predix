"""Aggregate observed object activity by configured image-space zones."""

import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

from app.analytics.temporal import AnalyticsDataError


def build_spatial_analytics(
    detections_path: Path,
    events_path: Path,
    zones: list[dict[str, Any]],
    bucket_seconds: int,
) -> dict[str, Any]:
    """Compare configured zones using detector-centroid assignments."""
    if bucket_seconds < 1:
        raise ValueError("Time bucket must be at least one second.")
    if not detections_path.is_file() or not events_path.is_file():
        raise FileNotFoundError("Detection or event records were not found.")

    observed_frames: dict[int, int] = defaultdict(int)
    sampled_frames = 0
    try:
        with detections_path.open("r", encoding="utf-8") as records:
            for line_number, line in enumerate(records, start=1):
                try:
                    record = json.loads(line)
                    timestamp = float(record["timestamp_seconds"])
                    if not math.isfinite(timestamp) or timestamp < 0:
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
                observed_frames[bucket_index] += 1
                sampled_frames += 1

        zone_records: dict[str, dict[str, Any]] = {}
        for zone in zones:
            zone_records[zone["zone_id"]] = {
                "zone_id": zone["zone_id"],
                "name": zone["name"],
                "event_count": 0,
                "detection_instances": 0,
                "confidence_weighted_sum": 0.0,
                "counts_by_class": defaultdict(int),
                "timeline": defaultdict(lambda: {
                    "event_count": 0,
                    "detection_instances": 0,
                    "counts_by_class": defaultdict(int),
                }),
            }
        unassigned: dict[str, Any] = {
            "event_count": 0,
            "detection_instances": 0,
            "counts_by_class": defaultdict(int),
        }

        with events_path.open("r", encoding="utf-8") as records:
            for line_number, line in enumerate(records, start=1):
                try:
                    event = json.loads(line)
                    timestamp = float(event["timestamp_seconds"])
                    count = int(event["count"])
                    confidence = float(event["confidence"])
                    object_class = str(event["object_class"])
                    zone_id = event.get("zone_id")
                    if (
                        not math.isfinite(timestamp)
                        or timestamp < 0
                        or count < 1
                        or not 0 <= confidence <= 1
                        or not object_class
                    ):
                        raise ValueError
                except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                    raise AnalyticsDataError(f"Invalid event record at line {line_number}.") from exc

                bucket_index = int(timestamp // bucket_seconds)
                target = zone_records.get(zone_id) if zone_id else None
                if target is None:
                    target = unassigned
                target["event_count"] += 1
                target["detection_instances"] += count
                target["counts_by_class"][object_class] += count
                if target is not unassigned:
                    target["confidence_weighted_sum"] += confidence * count
                    bucket = target["timeline"][bucket_index]
                    bucket["event_count"] += 1
                    bucket["detection_instances"] += count
                    bucket["counts_by_class"][object_class] += count
    except OSError as exc:
        raise AnalyticsDataError("Could not read stored spatial observations.") from exc

    zone_summaries = []
    for zone in zone_records.values():
        zone_timeline = []
        for bucket_index, bucket in sorted(observed_frames.items()):
            measured = zone["timeline"].get(bucket_index)
            zone_timeline.append({
                "bucket_start_seconds": bucket_index * bucket_seconds,
                "bucket_end_seconds": (bucket_index + 1) * bucket_seconds,
                "observed_frames": observed_frames[bucket_index],
                "event_count": measured["event_count"] if measured else 0,
                "detection_instances": measured["detection_instances"] if measured else 0,
                "counts_by_class": dict(sorted(measured["counts_by_class"].items())) if measured else {},
            })
        zone_summaries.append({
            "zone_id": zone["zone_id"],
            "name": zone["name"],
            "event_count": zone["event_count"],
            "detection_instances": zone["detection_instances"],
            "average_confidence": (
                round(zone["confidence_weighted_sum"] / zone["detection_instances"], 4)
                if zone["detection_instances"] else None
            ),
            "counts_by_class": dict(sorted(zone["counts_by_class"].items())),
            "timeline": zone_timeline,
        })

    zone_summaries.sort(key=lambda item: (-item["detection_instances"], item["name"].casefold()))
    comparison_total = sum(zone["detection_instances"] for zone in zone_summaries)
    comparison = [
        {
            "zone_id": zone["zone_id"],
            "name": zone["name"],
            "detection_instances": zone["detection_instances"],
            "share_percent": round(zone["detection_instances"] * 100 / comparison_total, 2)
            if comparison_total else 0.0,
        }
        for zone in zone_summaries
    ]

    return {
        "observation_source": "stored_frame_detections_and_events",
        "coordinate_system": "normalized_frame",
        "bucket_seconds": bucket_seconds,
        "sampled_frames": sampled_frames,
        "configured_zones": len(zones),
        "active_zones": sum(zone["detection_instances"] > 0 for zone in zone_summaries),
        "zones": zone_summaries,
        "zone_comparison": comparison,
        "unassigned": {
            "event_count": unassigned["event_count"],
            "detection_instances": unassigned["detection_instances"],
            "counts_by_class": dict(sorted(unassigned["counts_by_class"].items())),
        },
    }
