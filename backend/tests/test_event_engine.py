"""Unit tests for detection-to-event transformations."""

import json
import tempfile
import unittest
from pathlib import Path

from app.events.engine import EventDataError, generate_events


class EventEngineTests(unittest.TestCase):
    def test_groups_real_detection_records_by_frame_and_class(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            detections = root / "detections.jsonl"
            events = root / "events.jsonl"
            frames = [
                {
                    "timestamp_seconds": 1.25,
                    "frame_number": 7,
                    "detections": [
                        {"class": "person", "confidence": 0.9, "bbox": {"x1": 1, "y1": 2, "x2": 3, "y2": 4}},
                        {"class": "person", "confidence": 0.7, "bbox": {"x1": 5, "y1": 6, "x2": 7, "y2": 8}},
                        {"class": "car", "confidence": 0.8, "bbox": {"x1": 9, "y1": 10, "x2": 11, "y2": 12}},
                    ],
                },
                {"timestamp_seconds": 1.45, "frame_number": 8, "detections": []},
            ]
            detections.write_text("".join(json.dumps(frame) + "\n" for frame in frames))

            self.assertEqual(generate_events(detections, events, "video-1"), 2)
            records = [json.loads(line) for line in events.read_text().splitlines()]

        person, car = records
        self.assertEqual(person["event_type"], "object_detected")
        self.assertEqual(person["object_class"], "person")
        self.assertEqual(person["count"], 2)
        self.assertEqual(person["confidence"], 0.8)
        self.assertEqual(person["timestamp_seconds"], 1.25)
        self.assertEqual(person["metadata"]["frame_number"], 7)
        self.assertEqual(len(person["metadata"]["detections"]), 2)
        self.assertEqual(car["object_class"], "car")
        self.assertTrue(person["event_id"])
        self.assertNotEqual(person["event_id"], car["event_id"])

    def test_event_identifiers_are_reproducible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            detections = root / "detections.jsonl"
            payload = {
                "timestamp_seconds": 0.0,
                "frame_number": 1,
                "detections": [
                    {"class": "person", "confidence": 0.9, "bbox": {"x1": 1, "y1": 2, "x2": 3, "y2": 4}}
                ],
            }
            detections.write_text(json.dumps(payload) + "\n")
            first = root / "first.jsonl"
            second = root / "second.jsonl"
            generate_events(detections, first, "video-1")
            generate_events(detections, second, "video-1")
            first_id = json.loads(first.read_text())["event_id"]
            second_id = json.loads(second.read_text())["event_id"]

        self.assertEqual(first_id, second_id)

    def test_detection_centroid_is_assigned_to_configured_zone(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            detections = root / "detections.jsonl"
            events = root / "events.jsonl"
            detections.write_text(json.dumps({
                "timestamp_seconds": 0.0,
                "frame_number": 1,
                "frame_width": 100,
                "frame_height": 100,
                "detections": [
                    {"class": "person", "confidence": 0.9, "bbox": {"x1": 10, "y1": 10, "x2": 30, "y2": 30}}
                ],
            }) + "\n")
            zones = [{
                "zone_id": "west",
                "name": "West entrance",
                "polygon": [[0, 0], [0.5, 0], [0.5, 1], [0, 1]],
            }]

            self.assertEqual(generate_events(detections, events, "video-1", zones), 1)
            event = json.loads(events.read_text())

        self.assertEqual(event["zone_id"], "west")
        self.assertEqual(event["zone_name"], "West entrance")

    def test_invalid_detection_record_fails_without_partial_event_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            detections = root / "detections.jsonl"
            events = root / "events.jsonl"
            detections.write_text("not json\n")

            with self.assertRaises(EventDataError):
                generate_events(detections, events, "video-1")

            self.assertFalse(events.exists())
            self.assertFalse((root / ".events.jsonl.partial").exists())


if __name__ == "__main__":
    unittest.main()
