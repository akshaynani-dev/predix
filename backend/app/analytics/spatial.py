"""Aggregate observed object activity by configured image-space zones."""

import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

from app.analytics.temporal import AnalyticsDataError
from app.analytics.anomalies import detect_occupancy_deviations
from app.prediction.early_warning import build_crowd_early_warning
from app.prediction.zone_attention import recommend_zone_attention
from app.spatial.config import classify_capacity


def _contains_point(x: float, y: float, polygon: list[list[float]]) -> bool:
    inside = False
    previous = len(polygon) - 1
    for current, (x1, y1) in enumerate(polygon):
        x2, y2 = polygon[previous]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
        previous = current
    return inside


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
    occupancy_counts: dict[str, dict[int, list[int]]] = defaultdict(lambda: defaultdict(list))
    transition_counts: dict[str, dict[int, dict[str, int]]] = defaultdict(
        lambda: defaultdict(lambda: {"entries": 0, "exits": 0})
    )
    zone_edge_counts: dict[tuple[str, str], int] = defaultdict(int)
    previous_track_zones: dict[str, set[str]] = {}
    tracking_observed_frames = 0
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
                if record.get("tracking_available") is True:
                    tracking_observed_frames += 1
                    frame_width = int(record.get("frame_width", 0))
                    frame_height = int(record.get("frame_height", 0))
                    frame_zones = {zone["zone_id"]: zone for zone in zones if len(zone.get("polygon", [])) >= 3}
                    occupants: dict[str, set[str]] = {zone_id: set() for zone_id in frame_zones}
                    track_zones: dict[str, set[str]] = defaultdict(set)
                    for detection in record.get("detections", []):
                        if detection.get("class") != "person" or not detection.get("track_id"):
                            continue
                        bbox = detection.get("bbox", {})
                        if frame_width <= 0 or frame_height <= 0:
                            continue
                        track_id = str(detection["track_id"])
                        track_zones.setdefault(track_id, set())
                        center_x = (float(bbox["x1"]) + float(bbox["x2"])) / (2 * frame_width)
                        center_y = (float(bbox["y1"]) + float(bbox["y2"])) / (2 * frame_height)
                        for zone_id, zone in frame_zones.items():
                            if _contains_point(center_x, center_y, zone["polygon"]):
                                occupants[zone_id].add(track_id)
                                track_zones[track_id].add(zone_id)
                    for zone_id in frame_zones:
                        occupancy_counts[zone_id][bucket_index].append(len(occupants[zone_id]))
                    for track_id, current_zones in track_zones.items():
                        previous_zones = previous_track_zones.get(track_id)
                        if previous_zones is not None:
                            for zone_id in current_zones - previous_zones:
                                transition_counts[zone_id][bucket_index]["entries"] += 1
                            for zone_id in previous_zones - current_zones:
                                transition_counts[zone_id][bucket_index]["exits"] += 1
                            for source_id in previous_zones - current_zones:
                                for target_id in current_zones - previous_zones:
                                    zone_edge_counts[(source_id, target_id)] += 1
                        previous_track_zones[track_id] = current_zones

        zone_records: dict[str, dict[str, Any]] = {}
        for zone in zones:
            zone_records[zone["zone_id"]] = {
                "zone_id": zone["zone_id"],
                "name": zone["name"],
                "occupancy_capacity": zone.get("occupancy_capacity"),
                "status_thresholds": zone.get("status_thresholds"),
                "anomaly_mad_multiplier": zone.get("anomaly_mad_multiplier", 3.0),
                "anomaly_minimum_increase": zone.get("anomaly_minimum_increase", 1.0),
                "event_count": 0,
                "detection_instances": 0,
                "confidence_weighted_sum": 0.0,
                "counts_by_class": defaultdict(int),
            "timeline": defaultdict(lambda: {
                "event_count": 0,
                "detection_instances": 0,
                "counts_by_class": defaultdict(int),
                "zone_entries": 0,
                "zone_exits": 0,
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

    tracking_complete = sampled_frames > 0 and tracking_observed_frames == sampled_frames
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
                "zone_entries": transition_counts[zone["zone_id"]][bucket_index]["entries"] if tracking_complete else None,
                "zone_exits": transition_counts[zone["zone_id"]][bucket_index]["exits"] if tracking_complete else None,
            })
        zone_bucket_counts = occupancy_counts.get(zone["zone_id"], {})
        occupancy_values = [value for _, values in sorted(zone_bucket_counts.items()) for value in values]
        occupancy_by_bucket = {
            index: round(sum(values) / len(values), 2) for index, values in zone_bucket_counts.items() if values
        }
        occupancy_timeline = [{
            "bucket_start_seconds": index * bucket_seconds,
            "bucket_end_seconds": (index + 1) * bucket_seconds,
            "estimated_mean_visible_people": occupancy_by_bucket.get(index) if tracking_complete else None,
        } for index in sorted(observed_frames)]
        bucket_values = [occupancy_by_bucket[index] for index in sorted(occupancy_by_bucket)]
        current_estimate = bucket_values[-1] if tracking_complete and bucket_values else None
        capacity = zone.get("occupancy_capacity")
        thresholds = zone.get("status_thresholds") or {"low": 0.5, "moderate": 0.75, "high": 0.9, "critical": 1.0}
        capacity_status, capacity_ratio = classify_capacity(current_estimate, capacity, thresholds)
        anomaly = detect_occupancy_deviations(
            occupancy_values if tracking_complete else [],
            mad_multiplier=zone.get("anomaly_mad_multiplier", 3.0),
            minimum_increase=zone.get("anomaly_minimum_increase", 1.0),
        )
        occupancy_payload = {
            "estimation_status": "estimated" if tracking_complete and zone["zone_id"] in occupancy_counts else "unavailable",
            "status": capacity_status,
            "current_estimate": current_estimate,
            "configured_capacity": capacity,
            "capacity_ratio": round(capacity_ratio, 4) if capacity_ratio is not None else None,
        }
        early_warning = build_crowd_early_warning(occupancy_payload, anomaly)
        attention = recommend_zone_attention(occupancy_payload, anomaly)
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
            "occupancy": {
                **occupancy_payload,
                "method": "distinct anonymous person tracks whose bounding-box centers fall inside the normalized polygon per analyzed frame",
                "current_estimate": current_estimate,
                "mean_estimate": round(sum(occupancy_values) / len(occupancy_values), 2) if tracking_complete and occupancy_values else None,
                "peak_estimate": max(occupancy_values) if tracking_complete and occupancy_values else None,
                "configured_capacity": capacity,
                "capacity_ratio": round(capacity_ratio, 4) if capacity_ratio is not None else None,
                "status_thresholds": thresholds,
                "trend": {
                    "first_bucket_mean": bucket_values[0],
                    "last_bucket_mean": bucket_values[-1],
                    "change": round(bucket_values[-1] - bucket_values[0], 2),
                } if tracking_complete and bucket_values else None,
                "timeline": occupancy_timeline,
                "limitation": "Track association can fragment or merge people; estimates are not ground-truth counts.",
            },
            "transitions": {
                "status": "estimated" if tracking_complete else "unavailable",
                "observed_entries": sum(value["entries"] for value in transition_counts[zone["zone_id"]].values()) if tracking_complete else None,
                "observed_exits": sum(value["exits"] for value in transition_counts[zone["zone_id"]].values()) if tracking_complete else None,
                "timeline": [{
                    "bucket_start_seconds": index * bucket_seconds,
                    "bucket_end_seconds": (index + 1) * bucket_seconds,
                    "observed_entries": transition_counts[zone["zone_id"]][index]["entries"],
                    "observed_exits": transition_counts[zone["zone_id"]][index]["exits"],
                } for index in sorted(observed_frames)] if tracking_complete else [],
                "limitation": "Only transitions between observed samples for a continuing anonymous track are counted. Track fragmentation, missed detections, and clip boundaries can omit or misattribute transitions.",
            },
            "zone_to_zone_transitions": [{
                "from_zone_id": source_id,
                "to_zone_id": target_id,
                "observed_count": zone_edge_counts[(source_id, target_id)],
            } for source_id, target_id in sorted(zone_edge_counts) if tracking_complete and zone["zone_id"] in {source_id, target_id}],
            "occupancy_anomaly": anomaly,
            "early_warning": early_warning,
            "security_attention": attention,
            "risk_assessment": {
                "status": "not_configured",
                "risk_score": None,
                "reason": "No validated incident-risk model or site policy is configured.",
            },
            "security_recommendation": {
                "status": "unavailable",
                "recommendation": None,
                "reason": "PREDIX has no validated security-resource allocation policy; an early-warning cue recommends human verification only.",
            },
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
        "tracking_coverage": tracking_observed_frames / sampled_frames if sampled_frames else 0.0,
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
