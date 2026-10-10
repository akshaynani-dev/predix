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

    def test_schema_version_is_recorded_without_losing_sessions(self) -> None:
        with self.repository._connection() as connection:
            connection.execute("DROP TABLE occupancy_observations")
            connection.execute("DROP TABLE live_sessions")
            connection.execute("PRAGMA user_version = 1")
        self.repository.initialize()
        session = self.repository.get_session("video-1")
        with self.repository._connection() as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            table = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'occupancy_observations'").fetchone()
        self.assertEqual(version, 6)
        self.assertIsNotNone(table)
        self.assertEqual(session["filename"], "sample.mp4")

    def test_health_check_uses_repository_connection(self) -> None:
        self.assertTrue(self.repository.health_check())
        with self.repository._connection() as connection:
            live_table = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'live_sessions'").fetchone()
        self.assertIsNotNone(live_table)
        with self.repository._connection() as connection:
            self.assertIsNotNone(connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='live_occupancy_observations'").fetchone())
            self.assertIsNotNone(connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='live_crowd_predictions'").fetchone())
            self.assertIsNotNone(connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='live_occupancy_alert_episodes'").fetchone())

    def test_schema_six_migrates_schema_five_alert_episodes_and_backfills_zone_name(self) -> None:
        with self.repository._connection() as connection:
            connection.execute("DROP TABLE live_occupancy_alert_episodes")
            connection.execute("""CREATE TABLE live_occupancy_alert_episodes (
                episode_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                alert_id TEXT NOT NULL,
                zone_id TEXT NOT NULL,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                ended_at TEXT,
                severity TEXT NOT NULL,
                signal TEXT NOT NULL,
                supporting_evidence_json TEXT NOT NULL,
                recommendation TEXT NOT NULL,
                status TEXT NOT NULL
            )""")
            connection.execute("""INSERT INTO live_occupancy_alert_episodes
                VALUES ('episode', 'live-session', 'occupancy:entry', 'entry', 'first', 'last', NULL,
                        'WARNING', 'configured_capacity_level', '[]', 'Review', 'active')""")
            connection.execute("PRAGMA user_version = 5")

        self.repository.initialize()

        history = self.repository.get_live_occupancy_alerts("live-session")
        self.assertEqual(history[0]["zone"], "entry")
        with self.repository._connection() as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 6)

    def test_live_occupancy_and_forecast_history_round_trip_and_cascade(self) -> None:
        self.repository.create_live_session("live-history")
        self.repository.save_live_occupancy_bucket(
            "live-history", "entry", bucket_start_seconds=0, bucket_end_seconds=15,
            observation_count=5, estimated_mean_visible_people=2.4,
            configured_capacity=10, capacity_ratio=0.24, capacity_status="NORMAL",
        )
        self.repository.save_live_crowd_predictions("live-history", "entry", {
            "as_of_session_seconds": 375,
            "forecasts": [{
                "status": "available", "horizon_seconds": 60, "forecast": 2.1,
                "uncertainty": {"mae": 0.4}, "model": "trailing_mean",
                "evaluation": {"validation_windows": 3},
            }, {"status": "insufficient_data", "horizon_seconds": 300}],
        })
        history = self.repository.get_live_zone_observations("live-history", "entry")
        self.assertEqual(len(history["observations"]), 1)
        self.assertEqual(history["observations"][0]["observation_count"], 5)
        self.assertEqual(len(history["predictions"]), 1)
        self.assertEqual(history["predictions"][0]["evaluation"], {"validation_windows": 3})
        self.repository.delete_live_session("live-history")
        self.assertEqual(self.repository.get_live_zone_observations("live-history", "entry"), {"observations": [], "predictions": []})

    def test_live_session_aggregate_round_trip_and_delete(self) -> None:
        self.repository.create_live_session("live-session-1")
        active = self.repository.get_live_session("live-session-1")
        self.assertEqual(active["status"], "connecting")
        self.assertIsNone(active["ended_at"])
        self.assertIsNone(active["summary"])

        summary = {
            "frames_processed": 12,
            "total_detection_instances": 4,
            "peak_estimated_visible_people": 2,
            "zone_occupancy": [{"zone_id": "entry", "current_estimate": 1}],
        }
        self.repository.finish_live_session(
            "live-session-1", status="disconnected", summary=summary
        )
        completed = self.repository.get_live_session("live-session-1")
        self.assertEqual(completed["status"], "disconnected")
        self.assertIsNotNone(completed["ended_at"])
        self.assertEqual(completed["summary"], summary)
        self.assertEqual(self.repository.list_live_sessions()[0]["session_id"], "live-session-1")
        self.assertTrue(self.repository.delete_live_session("live-session-1"))
        self.assertIsNone(self.repository.get_live_session("live-session-1"))

    def test_live_occupancy_alerts_deduplicate_resolve_restart_and_end_with_session(self) -> None:
        self.repository.create_live_session("live-alert-session")
        active_alert = {
            "alert_id": "occupancy:entry",
            "zone_id": "entry",
            "zone": "Main Entrance",
            "severity": "WARNING",
            "signal": "configured_capacity_level",
            "supporting_evidence": [{"signal": "configured_capacity_level", "description": "Measured occupancy is high."}],
            "recommendation": "Review the zone.",
        }
        self.repository.update_live_occupancy_alerts(
            "live-alert-session", [active_alert], observed_at="2026-01-01T00:00:00+00:00"
        )
        first = self.repository.get_live_occupancy_alerts("live-alert-session")
        self.assertEqual(len(first), 1)
        self.assertEqual(first[0]["status"], "active")
        self.assertEqual(first[0]["zone"], "Main Entrance")
        self.assertEqual(first[0]["supporting_evidence"][0]["signal"], "configured_capacity_level")

        self.repository.update_live_occupancy_alerts(
            "live-alert-session", [active_alert], observed_at="2026-01-01T00:00:02+00:00"
        )
        repeated = self.repository.get_live_occupancy_alerts("live-alert-session")
        self.assertEqual(len(repeated), 1)
        self.assertEqual(repeated[0]["episode_id"], first[0]["episode_id"])

        self.repository.update_live_occupancy_alerts(
            "live-alert-session", [], observed_at="2026-01-01T00:00:03+00:00"
        )
        resolved = self.repository.get_live_occupancy_alerts("live-alert-session")
        self.assertEqual(resolved[0]["status"], "resolved")
        self.assertEqual(resolved[0]["ended_at"], "2026-01-01T00:00:03+00:00")

        self.repository.update_live_occupancy_alerts(
            "live-alert-session", [active_alert], observed_at="2026-01-01T00:00:04+00:00"
        )
        restarted = self.repository.get_live_occupancy_alerts("live-alert-session")
        self.assertEqual(len(restarted), 2)
        self.assertNotEqual(restarted[0]["episode_id"], first[0]["episode_id"])
        self.repository.finish_live_session("live-alert-session", status="disconnected", summary={})
        ended = self.repository.get_live_occupancy_alerts("live-alert-session")
        self.assertEqual(ended[0]["status"], "session_ended")
        self.assertTrue(self.repository.delete_live_session("live-alert-session"))
        self.assertEqual(self.repository.get_live_occupancy_alerts("live-alert-session"), [])

    def test_live_occupancy_alerts_deduplicate_resolve_restart_and_end_with_session(self) -> None:
        self.repository.create_live_session("live-alert-session")
        initial = [{
            "alert_id": "occupancy:entry",
            "zone_id": "entry",
            "severity": "WARNING",
            "signal": "configured_capacity_level",
            "supporting_evidence": [{"signal": "configured_capacity_level", "description": "Measured occupancy is high."}],
            "recommendation": "Review the zone.",
        }]
        self.repository.update_live_occupancy_alerts(
            "live-alert-session", initial, observed_at="2026-01-01T00:00:00+00:00"
        )
        first = self.repository.get_live_occupancy_alerts("live-alert-session")
        self.assertEqual(len(first), 1)
        self.assertEqual(first[0]["status"], "active")
        self.assertEqual(first[0]["supporting_evidence"][0]["signal"], "configured_capacity_level")

        self.repository.update_live_occupancy_alerts(
            "live-alert-session", initial, observed_at="2026-01-01T00:00:02+00:00"
        )
        repeated = self.repository.get_live_occupancy_alerts("live-alert-session")
        self.assertEqual(len(repeated), 1)
        self.assertEqual(repeated[0]["episode_id"], first[0]["episode_id"])

        self.repository.update_live_occupancy_alerts(
            "live-alert-session", [], observed_at="2026-01-01T00:00:03+00:00"
        )
        resolved = self.repository.get_live_occupancy_alerts("live-alert-session")
        self.assertEqual(resolved[0]["status"], "resolved")
        self.assertEqual(resolved[0]["ended_at"], "2026-01-01T00:00:03+00:00")

        self.repository.update_live_occupancy_alerts(
            "live-alert-session", initial, observed_at="2026-01-01T00:00:04+00:00"
        )
        restarted = self.repository.get_live_occupancy_alerts("live-alert-session")
        self.assertEqual(len(restarted), 2)
        self.assertNotEqual(restarted[0]["episode_id"], first[0]["episode_id"])
        self.repository.finish_live_session("live-alert-session", status="disconnected", summary={})
        ended = self.repository.get_live_occupancy_alerts("live-alert-session")
        self.assertEqual(ended[0]["status"], "session_ended")

    def test_initialize_marks_orphaned_live_session_interrupted(self) -> None:
        self.repository.create_live_session("live-session-orphan")
        self.repository.initialize()
        session = self.repository.get_live_session("live-session-orphan")
        self.assertEqual(session["status"], "interrupted")
        self.assertIsNotNone(session["ended_at"])

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
            "occupancy": {
                "configured_capacity": 10,
                "status_thresholds": {"low": 0.5, "moderate": 0.75, "high": 0.9, "critical": 1.0},
                "timeline": [{
                    "bucket_start_seconds": 0,
                    "bucket_end_seconds": 15,
                    "estimated_mean_visible_people": 3.0,
                }],
            },
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
        occupancy = self.repository.get_zone_occupancy("video-1", "entrance", start_seconds=None, end_seconds=None)
        self.assertEqual(occupancy[0]["estimated_mean_visible_people"], 3.0)
        self.assertEqual(occupancy[0]["capacity_status"], "NORMAL")

        self.repository.delete_session("video-1")
        self.assertIsNone(self.repository.get_session("video-1"))
        self.assertEqual(self.repository.get_events("video-1", limit=10, offset=0), ([], False))
        self.assertEqual(self.repository.get_zone_occupancy("video-1", "entrance", start_seconds=None, end_seconds=None), [])

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
