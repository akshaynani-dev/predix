"""Integration tests for historical session and time-range endpoints."""

import json
import tempfile
import unittest
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from app.database.instance import repository
from app.main import app
from database_test_support import IsolatedDatabaseTestCase


class HistoryApiTests(IsolatedDatabaseTestCase):
    def test_session_events_and_time_range_queries(self) -> None:
        video_id = str(uuid.uuid4())
        original_database_path = repository.database_path
        with tempfile.TemporaryDirectory() as directory:
            repository.database_path = Path(directory) / "history.sqlite3"
            self.addCleanup(setattr, repository, "database_path", original_database_path)
            repository.initialize()
            events_path = Path(directory) / "events.jsonl"
            events_path.write_text(json.dumps({
                "event_id": f"event-{video_id}",
                "timestamp_seconds": 5.0,
                "event_type": "object_detected",
                "object_class": "person",
                "count": 2,
                "confidence": 0.9,
                "zone_id": "entry",
                "zone_name": "Entry",
                "metadata": {"frame_number": 10},
            }) + "\n")
            repository.create_session(
                video_id=video_id,
                filename="history.mp4",
                stored_filename=f"{video_id}_history.mp4",
                content_type="video/mp4",
                size_bytes=123,
                metadata={"duration_seconds": 10, "width": 64, "height": 48, "fps": 5, "frame_count": 50},
            )
            repository.set_status(video_id, "analyzing")
            summary = {
                "model": "yolo11n.pt", "device": "mps", "confidence_threshold": 0.25,
                "frames_processed": 50, "total_frames": 50,
                "total_detection_instances": 2, "total_events": 1,
                "processing_time_seconds": 2.0, "processing_fps": 25.0,
                "zones_configured": 1,
            }
            temporal = {
                "aggregation": {"bucket_seconds": 15, "timeline": [{
                    "bucket_start_seconds": 0, "bucket_end_seconds": 15,
                    "observed_frames": 50, "detection_instances": 2,
                    "average_instances_per_observed_frame": 0.04,
                    "counts_by_class": {"person": 2},
                }]}
            }
            spatial = {"zones": [{
                "zone_id": "entry", "name": "Entry", "timeline": [{
                    "bucket_start_seconds": 0, "bucket_end_seconds": 15,
                    "observed_frames": 50, "event_count": 1,
                    "detection_instances": 2, "counts_by_class": {"person": 2},
                }],
                "occupancy": {
                    "configured_capacity": 10,
                    "status_thresholds": {"low": 0.5, "moderate": 0.75, "high": 0.9, "critical": 1.0},
                    "timeline": [{
                        "bucket_start_seconds": 0, "bucket_end_seconds": 15,
                        "estimated_mean_visible_people": 3.0,
                    }],
                },
            }]}
            repository.save_completed(video_id, summary, temporal, spatial, events_path)

            try:
                with TestClient(app) as client:
                    listing = client.get("/api/history/sessions?limit=100")
                    listing.raise_for_status()
                    self.assertIn(video_id, {item["video_id"] for item in listing.json()["sessions"]})

                    detail = client.get(f"/api/history/sessions/{video_id}")
                    detail.raise_for_status()
                    self.assertEqual(detail.json()["data_kind"], "historical_session")

                    events = client.get(f"/api/history/sessions/{video_id}/events")
                    events.raise_for_status()
                    self.assertEqual(events.json()["events"][0]["metadata"]["frame_number"], 10)

                    activity = client.get(
                        f"/api/history/sessions/{video_id}/activity?start_seconds=0&end_seconds=10"
                    )
                    activity.raise_for_status()
                    self.assertEqual(activity.json()["statistics"]["mean_instances_per_observed_frame"], 0.04)

                    zones = client.get(f"/api/history/sessions/{video_id}/zones?start_seconds=0&end_seconds=10")
                    zones.raise_for_status()
                    self.assertEqual(zones.json()["measurements"][0]["zone_id"], "entry")

                    occupancy = client.get(f"/api/history/sessions/{video_id}/occupancy/entry?start_seconds=0&end_seconds=10")
                    occupancy.raise_for_status()
                    self.assertEqual(occupancy.json()["status"], "available")
                    self.assertEqual(occupancy.json()["measurements"][0]["estimated_mean_visible_people"], 3.0)

                    forecast = client.get("/api/history/predictions/activity-rate")
                    forecast.raise_for_status()
                    self.assertEqual(forecast.json()["status"], "insufficient_data")
                    self.assertEqual(
                        forecast.json()["message"],
                        "Insufficient data for reliable prediction.",
                    )

                    decision = client.get("/api/history/decision-support")
                    decision.raise_for_status()
                    self.assertEqual(decision.json()["status"], "insufficient_data")
                    self.assertEqual(decision.json()["recommendations"], [])

                    invalid_range = client.get(
                        f"/api/history/sessions/{video_id}/activity?start_seconds=8&end_seconds=3"
                    )
                    self.assertEqual(invalid_range.status_code, 422)
            finally:
                repository.delete_session(video_id)


if __name__ == "__main__":
    unittest.main()
