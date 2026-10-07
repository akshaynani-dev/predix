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


if __name__ == "__main__":
    unittest.main()
