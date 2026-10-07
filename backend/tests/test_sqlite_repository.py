"""Tests for durable session, event, and aggregate persistence."""

import json
import tempfile
import unittest
from pathlib import Path

from app.database.sqlite_repository import SessionNotFoundError, SQLiteRepository


class SQLiteRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name)
        self.repository = SQLiteRepository(self.root / "predix.sqlite3")
        self.repository.initialize()
        self.repository.create_session(
            video_id="video-1",
            filename="sample.mp4",
            stored_filename="opaque_sample.mp4",
            content_type="video/mp4",
            size_bytes=123,
            metadata={"duration_seconds": 2.0, "width": 64, "height": 48, "fps": 5.0, "frame_count": 10},
        )

    def test_session_events_and_aggregates_round_trip_and_delete(self) -> None:
        self.repository.set_status("video-1", "analyzing")
        event_path = self.root / "events.jsonl"
        event_path.write_text("".join(json.dumps(event) + "\n" for event in [
            {
                "event_id": "event-1",
                "timestamp_seconds": 0.5,
                "event_type": "object_detected",
                "object_class": "person",
                "count": 1,
                "confidence": 0.9,
                "zone_id": "entrance",
                "zone_name": "Entrance",
                "metadata": {"frame_number": 3},
            },
            {
                "event_id": "event-2",
                "timestamp_seconds": 1.5,
                "event_type": "object_detected",
                "object_class": "car",
                "count": 1,
                "confidence": 0.8,
                "zone_id": None,
                "zone_name": None,
                "metadata": {},
            },
        ]))
        summary = {
            "model": "yolo11n.pt",
            "device": "mps",
            "confidence_threshold": 0.25,
            "frames_processed": 10,
            "total_frames": 10,
            "total_detection_instances": 2,
            "total_events": 2,
            "processing_time_seconds": 1.0,
            "processing_fps": 10.0,
            "zones_configured": 1,
        }
        temporal = {
            "aggregation": {
                "bucket_seconds": 15,
                "timeline": [{
                    "bucket_start_seconds": 0,
                    "bucket_end_seconds": 15,
                    "observed_frames": 10,
                    "detection_instances": 2,
                    "average_instances_per_observed_frame": 0.2,
                    "counts_by_class": {"person": 1, "car": 1},
                }],
            }
        }
        spatial = {"zones": [{
            "zone_id": "entrance",
            "name": "Entrance",
            "timeline": [{
                "bucket_start_seconds": 0,
                "bucket_end_seconds": 15,
                "observed_frames": 10,
                "event_count": 1,
                "detection_instances": 1,
                "counts_by_class": {"person": 1},
            }],
        }]}

        self.repository.save_completed("video-1", summary, temporal, spatial, event_path)

        session = self.repository.get_session("video-1")
        self.assertEqual(session["status"], "completed")
        self.assertEqual(session["metadata"]["width"], 64)
        self.assertEqual(session["summary"]["total_events"], 2)
        events, has_more = self.repository.get_events("video-1", limit=1, offset=0)
        self.assertEqual(len(events), 1)
        self.assertTrue(has_more)
        self.assertEqual(events[0]["metadata"]["frame_number"], 3)
        activity = self.repository.get_activity("video-1", start_seconds=0, end_seconds=10)
        self.assertEqual(activity[0]["detection_instances"], 2)
        zone_activity = self.repository.get_zone_activity("video-1", start_seconds=None, end_seconds=None)
        self.assertEqual(zone_activity[0]["zone_id"], "entrance")

        self.repository.delete_session("video-1")
        self.assertIsNone(self.repository.get_session("video-1"))
        self.assertEqual(self.repository.get_events("video-1", limit=10, offset=0), ([], False))

    def test_status_update_requires_an_existing_session(self) -> None:
        with self.assertRaises(SessionNotFoundError):
            self.repository.set_status("missing", "analyzing")

    def test_failed_completion_rolls_back_database_changes(self) -> None:
        self.repository.set_status("video-1", "analyzing")
        summary = {
            "model": "yolo11n.pt", "device": "cpu", "confidence_threshold": 0.25,
            "frames_processed": 1, "total_frames": 1, "total_detection_instances": 0,
            "total_events": 0, "processing_time_seconds": 0.1, "processing_fps": 10.0,
            "zones_configured": 0,
        }
        temporal = {"aggregation": {"bucket_seconds": 15, "timeline": []}}
        spatial = {"zones": []}
        with self.assertRaises(FileNotFoundError):
            self.repository.save_completed(
                "video-1", summary, temporal, spatial, self.root / "missing-events.jsonl"
            )
        session = self.repository.get_session("video-1")
        self.assertEqual(session["status"], "analyzing")
        self.assertIsNone(session["summary"])


if __name__ == "__main__":
    unittest.main()
