"""Tests for zone configuration and spatial aggregates."""

import json
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from app.analytics.spatial import build_spatial_analytics
from app.spatial.config import ZoneConfiguration


class ZoneConfigurationTests(unittest.TestCase):
    def test_normalized_polygons_are_accepted(self) -> None:
        config = ZoneConfiguration.model_validate({
            "zones": [{
                "zone_id": "entrance-a",
                "name": "Entrance A",
                "polygon": [[0, 0], [0.5, 0], [0.5, 1], [0, 1]],
            }]
        })

        self.assertEqual(config.zones[0].name, "Entrance A")

    def test_invalid_coordinates_and_duplicate_ids_are_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            ZoneConfiguration.model_validate({
                "zones": [{"zone_id": "bad", "name": "Bad", "polygon": [[-1, 0], [0, 0], [0, 1]]}]
            })
        with self.assertRaises(ValidationError):
            ZoneConfiguration.model_validate({
                "zones": [
                    {"zone_id": "same", "name": "A", "polygon": [[0, 0], [1, 0], [1, 1]]},
                    {"zone_id": "same", "name": "B", "polygon": [[0, 0], [0, 1], [1, 1]]},
                ]
            })

    def test_occupancy_thresholds_must_be_ordered_and_capacity_positive(self) -> None:
        zone = {"zone_id": "z", "name": "Zone", "polygon": [[0, 0], [1, 0], [1, 1]]}
        with self.assertRaises(ValidationError):
            ZoneConfiguration.model_validate({"zones": [{**zone, "occupancy_capacity": 0}]})
        with self.assertRaises(ValidationError):
            ZoneConfiguration.model_validate({"zones": [{
                **zone,
                "occupancy_capacity": 20,
                "status_thresholds": {"low": 0.8, "moderate": 0.7, "high": 0.9, "critical": 1.0},
            }]})


class SpatialAnalyticsTests(unittest.TestCase):
    def test_zone_comparison_and_timeline_use_stored_observations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            detections = root / "detections.jsonl"
            events = root / "events.jsonl"
            detections.write_text("".join(json.dumps(record) + "\n" for record in [
                {"timestamp_seconds": 0.0, "frame_number": 1, "detections": []},
                {"timestamp_seconds": 1.0, "frame_number": 2, "detections": []},
                {"timestamp_seconds": 5.0, "frame_number": 3, "detections": []},
            ]))
            events.write_text("".join(json.dumps(event) + "\n" for event in [
                {
                    "timestamp_seconds": 0.0,
                    "event_type": "object_detected",
                    "object_class": "person",
                    "count": 2,
                    "confidence": 0.8,
                    "zone_id": "entrance",
                },
                {
                    "timestamp_seconds": 5.0,
                    "event_type": "object_detected",
                    "object_class": "car",
                    "count": 1,
                    "confidence": 0.9,
                    "zone_id": None,
                },
            ]))
            zones = [
                {"zone_id": "entrance", "name": "Entrance", "polygon": []},
                {"zone_id": "hall", "name": "Hall", "polygon": []},
            ]

            result = build_spatial_analytics(detections, events, zones, bucket_seconds=5)

        self.assertEqual(result["sampled_frames"], 3)
        self.assertEqual(result["configured_zones"], 2)
        self.assertEqual(result["active_zones"], 1)
        entrance = next(zone for zone in result["zones"] if zone["zone_id"] == "entrance")
        hall = next(zone for zone in result["zones"] if zone["zone_id"] == "hall")
        self.assertEqual(entrance["detection_instances"], 2)
        self.assertEqual(entrance["timeline"][0]["observed_frames"], 2)
        self.assertEqual(entrance["timeline"][1]["detection_instances"], 0)
        self.assertEqual(hall["detection_instances"], 0)
        self.assertEqual(result["unassigned"]["detection_instances"], 1)

    def test_zone_occupancy_uses_distinct_tracks_not_raw_detection_totals(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            detections = root / "detections.jsonl"
            events = root / "events.jsonl"
            detections.write_text("".join(json.dumps(record) + "\n" for record in [
                {"timestamp_seconds": 0.0, "frame_number": 1, "frame_width": 100, "frame_height": 100,
                 "tracking_available": True, "detections": [{"class": "person", "track_id": "temp-1", "bbox": {"x1": 20, "y1": 20, "x2": 40, "y2": 40}}]},
                {"timestamp_seconds": 5.0, "frame_number": 2, "frame_width": 100, "frame_height": 100,
                 "tracking_available": True, "detections": [
                     {"class": "person", "track_id": "temp-1", "bbox": {"x1": 20, "y1": 20, "x2": 40, "y2": 40}},
                     {"class": "person", "track_id": "temp-2", "bbox": {"x1": 25, "y1": 20, "x2": 45, "y2": 40}},
                 ]},
            ]))
            events.write_text("")
            zones = [{"zone_id": "entrance", "name": "Entrance", "polygon": [[0, 0], [0.5, 0], [0.5, 0.5], [0, 0.5]], "occupancy_capacity": 2}]
            result = build_spatial_analytics(detections, events, zones, bucket_seconds=5)
        occupancy = result["zones"][0]["occupancy"]
        self.assertEqual(occupancy["estimation_status"], "estimated")
        self.assertEqual(occupancy["peak_estimate"], 2)
        self.assertEqual(occupancy["current_estimate"], 2.0)
        self.assertEqual(occupancy["trend"]["change"], 1.0)
        self.assertEqual(occupancy["status"], "CRITICAL")
        self.assertEqual(result["tracking_coverage"], 1.0)

    def test_legacy_detection_files_do_not_claim_zone_occupancy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            detections = root / "detections.jsonl"
            events = root / "events.jsonl"
            detections.write_text('{"timestamp_seconds": 0, "detections": []}\n')
            events.write_text("")
            zones = [{"zone_id": "entrance", "name": "Entrance", "polygon": [[0, 0], [1, 0], [1, 1]]}]
            result = build_spatial_analytics(detections, events, zones, bucket_seconds=5)
        self.assertEqual(result["zones"][0]["occupancy"]["estimation_status"], "unavailable")
        self.assertIsNone(result["zones"][0]["occupancy"]["current_estimate"])
        self.assertEqual(result["zones"][0]["transitions"]["status"], "unavailable")

    def test_track_zone_entries_exits_and_zone_to_zone_transitions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            detections = root / "detections.jsonl"
            events = root / "events.jsonl"
            records = []
            for index, box in enumerate(([10, 10, 30, 30], [60, 10, 80, 30], [90, 10, 100, 30])):
                records.append({
                    "timestamp_seconds": float(index),
                    "frame_number": index + 1,
                    "frame_width": 100,
                    "frame_height": 100,
                    "tracking_available": True,
                    "detections": [{
                        "class": "person", "track_id": "anon-track",
                        "bbox": {"x1": box[0], "y1": box[1], "x2": box[2], "y2": box[3]},
                    }],
                })
            detections.write_text("".join(json.dumps(record) + "\n" for record in records))
            events.write_text("")
            zones = [
                {"zone_id": "left", "name": "Left", "polygon": [[0, 0], [0.4, 0], [0.4, 1], [0, 1]]},
                {"zone_id": "right", "name": "Right", "polygon": [[0.5, 0], [0.9, 0], [0.9, 1], [0.5, 1]]},
            ]
            result = build_spatial_analytics(detections, events, zones, bucket_seconds=1)

        left, right = result["zones"]
        self.assertEqual(left["transitions"]["status"], "estimated")
        self.assertEqual(left["transitions"]["observed_entries"], 0)
        self.assertEqual(left["transitions"]["observed_exits"], 1)
        self.assertEqual(right["transitions"]["observed_entries"], 1)
        self.assertEqual(right["transitions"]["observed_exits"], 1)
        self.assertEqual(left["zone_to_zone_transitions"], [{
            "from_zone_id": "left", "to_zone_id": "right", "observed_count": 1,
        }])
        self.assertEqual(right["timeline"][1]["zone_entries"], 1)

    def test_configured_capacity_and_deviation_combine_into_explainable_cue(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            detections = root / "detections.jsonl"
            events = root / "events.jsonl"
            frames = []
            for index in range(7):
                people = [] if index < 6 else [
                    {"class": "person", "track_id": f"p{person}", "bbox": {"x1": person, "y1": 1, "x2": person + 10, "y2": 10}}
                    for person in range(3)
                ]
                frames.append({
                    "timestamp_seconds": index * 15,
                    "frame_number": index + 1,
                    "frame_width": 100,
                    "frame_height": 100,
                    "tracking_available": True,
                    "detections": people,
                })
            detections.write_text("".join(json.dumps(frame) + "\n" for frame in frames))
            events.write_text("")
            zones = [{
                "zone_id": "entrance", "name": "Entrance",
                "polygon": [[0, 0], [0.5, 0], [0.5, 0.5], [0, 0.5]],
                "occupancy_capacity": 2,
            }]
            result = build_spatial_analytics(detections, events, zones, bucket_seconds=15)
        zone = result["zones"][0]
        self.assertEqual(zone["occupancy"]["status"], "CRITICAL")
        self.assertEqual(zone["occupancy_anomaly"]["status"], "deviation_signal")
        self.assertEqual(zone["early_warning"]["status"], "elevated")
        self.assertEqual(zone["security_attention"]["status"], "priority_review")
        self.assertEqual(len(zone["security_attention"]["signals"]), 2)
        self.assertIsNone(zone["risk_assessment"]["risk_score"])
        self.assertEqual(zone["early_warning"]["recommendation"], "Human verification recommended for the combined occupancy signals.")


if __name__ == "__main__":
    unittest.main()
