"""Integration tests for browser-camera frame ingestion and cleanup."""

import cv2
import base64
import json
import numpy as np
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from app.api.live import get_live_status
from app.cv.detector import Detection
from app.cv.runtime import active_pipeline, release_pipeline, reserve_pipeline
from app.database.instance import repository
from app.main import app
from app.video_processing.sources import VideoSourceError
from database_test_support import IsolatedDatabaseTestCase


def jpeg_frame() -> bytes:
    ok, encoded = cv2.imencode(".jpg", np.zeros((48, 64, 3), dtype=np.uint8))
    if not ok:
        raise RuntimeError("Could not create test frame")
    return encoded.tobytes()


class LiveApiTests(IsolatedDatabaseTestCase):
    def test_live_occupancy_carries_short_misses_and_reports_raw_detections_separately(self):
        frame = np.zeros((48, 64, 3), dtype=np.uint8)
        detector = SimpleNamespace(
            model_name="test-model",
            device="cpu",
            detect_frame=Mock(side_effect=[
                ([Detection("person", 0.9, [1, 2, 30, 40])], frame.copy()),
                ([], frame.copy()),
                ([], frame.copy()),
                ([], frame.copy()),
            ]),
        )
        with patch("app.api.live.get_detector", return_value=detector), \
             patch("app.api.live.settings.LIVE_MIN_FRAME_INTERVAL_MS", 0):
            with TestClient(app) as client:
                with client.websocket_connect("/api/live/ws", headers={"origin": "http://localhost:5173"}) as socket:
                    results = []
                    for _ in range(4):
                        socket.send_bytes(jpeg_frame())
                        results.append(socket.receive_json())
                    self.assertEqual([row["occupancy"]["count"] for row in results], [1, 1, 1, 0])
                    self.assertEqual([row["occupancy"]["raw_person_detection_instances"] for row in results], [1, 0, 0, 0])
                    self.assertEqual([row["occupancy"]["temporally_carried_track_count"] for row in results], [0, 1, 1, 0])

    def test_live_zone_history_endpoint_returns_persisted_aggregate_rows(self):
        session_id = "7c19717f-4c4e-4ceb-9e8a-6cfcbe7d47a1"
        with TestClient(app) as client:
            repository.create_live_session(session_id)
            repository.save_live_occupancy_bucket(
                session_id, "entry", bucket_start_seconds=0, bucket_end_seconds=15,
                observation_count=4, estimated_mean_visible_people=1.5,
                configured_capacity=20, capacity_ratio=0.075, capacity_status="NORMAL",
            )
            response = client.get(f"/api/live/sessions/{session_id}/zones/entry/occupancy")
            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(body["data_kind"], "live_zone_occupancy_history")
            self.assertEqual(body["observations"][0]["observation_count"], 4)
            self.assertEqual(body["predictions"], [])
            missing = client.get(f"/api/live/sessions/{session_id}/zones/unknown/occupancy")
            self.assertEqual(missing.json()["observations"], [])
            repository.delete_live_session(session_id)

    def test_rtsp_frames_use_shared_pipeline_and_release_on_disconnect(self):
        frame = np.zeros((48, 64, 3), dtype=np.uint8)
        source = SimpleNamespace(
            open=lambda: None,
            read=lambda: (True, frame.copy()),
            release=Mock(),
        )
        detector = SimpleNamespace(
            model_name="yolo11n.pt",
            device="cpu",
            detect_frame=lambda received: ([Detection("person", 0.9, [1, 2, 30, 40])], received),
        )
        with patch("app.api.live.RTSPVideoSource", return_value=source) as create_source, \
             patch("app.api.live.get_detector", return_value=detector), \
             patch("app.api.live.settings.LIVE_MIN_FRAME_INTERVAL_MS", 0), \
             patch("app.api.live.settings.RTSP_ALLOWED_HOSTS", "camera.example"):
            with TestClient(app) as client:
                with client.websocket_connect("/api/live/ws", headers={"origin": "http://localhost:5173"}) as socket:
                    socket.send_json({"type": "start_rtsp", "url": "rtsp://camera.example/live"})
                    self.assertEqual(socket.receive_json()["type"], "source_ready")
                    socket.send_json({"type": "next_frame"})
                    observation = socket.receive_json()
                    self.assertEqual(observation["source_kind"], "rtsp")
                    self.assertEqual(observation["detections"][0]["class"], "person")
                    self.assertTrue(base64.b64decode(observation["preview_jpeg"]).startswith(b"\xff\xd8"))
                    session_id = observation["session_id"]
                    socket.send_json({"type": "stop"})
                    self.assertEqual(socket.receive_json()["type"], "session_stopped")
                source.release.assert_called_once()
                history = client.get(f"/api/live/sessions/{session_id}").json()["session"]
                self.assertIsNotNone(history["summary"], history)
                self.assertEqual(history["summary"]["frames_processed"], 1)
                client.delete(f"/api/live/sessions/{session_id}")
        create_source.assert_called_once()

    def test_rtsp_allowlist_rejection_does_not_load_model_or_echo_url(self):
        sensitive_url = "rtsp://user:secret@untrusted.example/private"
        with patch("app.api.live.get_detector") as load_detector, \
             patch("app.api.live.settings.RTSP_ALLOWED_HOSTS", ""):
            with TestClient(app) as client:
                with client.websocket_connect("/api/live/ws", headers={"origin": "http://localhost:5173"}) as socket:
                    socket.send_json({"type": "start_rtsp", "url": sensitive_url})
                    result = socket.receive_json()
                    self.assertEqual(result["type"], "source_error")
                    self.assertNotIn("secret", result["detail"])
                    self.assertNotIn("untrusted.example", result["detail"])
                session_id = get_live_status()["session_id"]
                repository.delete_live_session(session_id)
        load_detector.assert_not_called()

    def test_rtsp_open_failure_returns_safe_error_and_releases_source(self):
        source = SimpleNamespace(open=Mock(side_effect=VideoSourceError("private endpoint")), release=Mock())
        with patch("app.api.live.RTSPVideoSource", return_value=source), \
             patch("app.api.live.settings.RTSP_ALLOWED_HOSTS", "camera.example"), \
             patch("app.api.live.get_detector") as load_detector:
            with TestClient(app) as client:
                with client.websocket_connect("/api/live/ws", headers={"origin": "http://localhost:5173"}) as socket:
                    socket.send_json({"type": "start_rtsp", "url": "rtsp://user:secret@camera.example/live"})
                    result = socket.receive_json()
                    self.assertEqual(result["type"], "source_error")
                    self.assertNotIn("secret", result["detail"])
                    self.assertNotIn("private endpoint", result["detail"])
                session_id = get_live_status()["session_id"]
                repository.delete_live_session(session_id)
        source.release.assert_called_once()
        load_detector.assert_not_called()

    def test_camera_frame_uses_shared_detector_and_disconnect_releases_session(self):
        boxes = iter(([1, 2, 30, 40], [3, 2, 32, 40]))
        detector = SimpleNamespace(
            model_name="yolo11n.pt",
            device="cpu",
            detect_frame=lambda frame: ([Detection("person", 0.91, next(boxes))], frame),
        )
        with patch("app.api.live.get_detector", return_value=detector), patch("app.api.live.settings.LIVE_MIN_FRAME_INTERVAL_MS", 0):
            with TestClient(app) as client:
                with client.websocket_connect(
                    "/api/live/ws", headers={"origin": "http://localhost:5173"}
                ) as socket:
                    socket.send_bytes(jpeg_frame())
                    observation = socket.receive_json()
                    session_id = observation["session_id"]
                    self.assertEqual(observation["type"], "observation")
                    self.assertGreaterEqual(observation["session_elapsed_seconds"], 0)
                    self.assertEqual(observation["detection_count"], 1)
                    self.assertEqual(observation["detections"][0]["confidence"], 0.91)
                    self.assertEqual(observation["detections"][0]["class"], "person")
                    self.assertTrue(observation["detections"][0]["track_id"])
                    self.assertIsNone(observation["detections"][0]["direction"])
                    self.assertEqual(observation["detections"][0]["dwell_seconds"], 0.0)
                    self.assertEqual(observation["occupancy"]["count"], 1)
                    self.assertEqual(observation["occupancy"]["data_kind"], "estimated_active_person_tracks")
                    self.assertEqual(observation["occupancy"]["raw_person_detection_instances"], 1)
                    self.assertEqual(observation["occupancy"]["temporally_carried_track_count"], 0)
                    self.assertIn("inference_latency_ms", observation)
                    time.sleep(0.01)
                    socket.send_bytes(jpeg_frame())
                    next_observation = socket.receive_json()
                    self.assertEqual(next_observation["detections"][0]["track_id"], observation["detections"][0]["track_id"])
                    self.assertEqual(next_observation["detections"][0]["direction"]["dx_pixels"], 2.0)
                    self.assertGreater(next_observation["detections"][0]["dwell_seconds"], 0)
                    self.assertEqual(client.get("/api/live/status").json()["status"], "live")
                self.assertEqual(active_pipeline(), None)
                self.assertEqual(get_live_status()["status"], "offline")
                history = client.get(f"/api/live/sessions/{session_id}")
                self.assertEqual(history.status_code, 200)
                persisted = history.json()["session"]
                self.assertEqual(persisted["status"], "disconnected")
                self.assertEqual(persisted["summary"]["frames_processed"], 2)
                self.assertEqual(persisted["summary"]["total_detection_instances"], 2)
                self.assertNotIn("track_id", json.dumps(persisted))
                self.assertEqual(client.get("/api/live/sessions?limit=1").json()["sessions"][0]["session_id"], session_id)
                self.assertEqual(client.delete(f"/api/live/sessions/{session_id}").status_code, 200)

    def test_non_image_frame_returns_error_without_stopping_session(self):
        detector = SimpleNamespace(model_name="yolo11n.pt", device="cpu", detect_frame=lambda frame: ([], frame))
        with patch("app.api.live.get_detector", return_value=detector):
            with TestClient(app) as client:
                with client.websocket_connect(
                    "/api/live/ws", headers={"origin": "http://localhost:5173"}
                ) as socket:
                    socket.send_bytes(b"not an image")
                    result = socket.receive_json()
                    self.assertEqual(result["type"], "error")
                    self.assertIn("could not be decoded", result["detail"])
                repository.delete_live_session(get_live_status()["session_id"])

    def test_inference_failure_is_persisted_and_releases_the_pipeline(self):
        detector = SimpleNamespace(
            model_name="yolo11n.pt", device="cpu",
            detect_frame=lambda frame: (_ for _ in ()).throw(RuntimeError("inference failed")),
        )
        with patch("app.api.live.get_detector", return_value=detector):
            with TestClient(app) as client:
                with client.websocket_connect("/api/live/ws", headers={"origin": "http://localhost:5173"}) as socket:
                    socket.send_bytes(jpeg_frame())
                    error = socket.receive_json()
                    self.assertEqual(error["type"], "error")
                    self.assertIn("inference failed", error["detail"])
                session_id = get_live_status()["session_id"]
                history = client.get(f"/api/live/sessions/{session_id}").json()["session"]
                self.assertEqual(history["status"], "failed")
                self.assertEqual(history["summary"]["frames_processed"], 0)
                self.assertIsNone(active_pipeline())
                client.delete(f"/api/live/sessions/{session_id}")

    def test_live_zone_configuration_produces_capacity_status(self):
        detector = SimpleNamespace(
            model_name="yolo11n.pt", device="cpu",
            detect_frame=lambda frame: ([Detection("person", 0.91, [1, 2, 30, 40])], frame),
        )
        zone = {
            "zone_id": "entry", "name": "Entry", "polygon": [[0, 0], [0.6, 0], [0.6, 1], [0, 1]],
            "occupancy_capacity": 1,
        }
        with patch("app.api.live.get_detector", return_value=detector):
            with TestClient(app) as client:
                with client.websocket_connect("/api/live/ws", headers={"origin": "http://localhost:5173"}) as socket:
                    socket.send_json({"type": "configure_zones", "zones": [zone]})
                    self.assertEqual(socket.receive_json()["type"], "zones_configured")
                    socket.send_bytes(jpeg_frame())
                    observation = socket.receive_json()
                    self.assertEqual(observation["zone_occupancy"][0]["current_estimate"], 1)
                    self.assertEqual(observation["zone_occupancy"][0]["capacity_status"], "CRITICAL")
                    self.assertEqual(observation["zone_occupancy"][0]["security_attention"]["status"], "capacity_review")
                    self.assertEqual(observation["occupancy_alerts"][0]["severity"], "CRITICAL")
                    alert_snapshot = client.get("/api/live/alerts").json()
                    self.assertEqual(alert_snapshot["active_count"], 1)
                    self.assertEqual(alert_snapshot["security_alerts"]["status"], "unavailable")
                    self.assertEqual(observation["zone_occupancy"][0]["occupancy_forecast"]["status"], "insufficient_data")
                    self.assertEqual(observation["current_zones"], ["Entry"])
                    self.assertEqual(observation["security_alerts"]["status"], "unavailable")
                    session_id = observation["session_id"]
                history = client.get(f"/api/live/sessions/{session_id}").json()["session"]
                self.assertEqual(history["summary"]["occupancy_alerts"][0]["alert_id"], "occupancy:entry")
                alert_history = client.get(f"/api/live/sessions/{session_id}/alerts").json()
                self.assertEqual(alert_history["data_kind"], "live_occupancy_alert_history")
                self.assertEqual(len(alert_history["alerts"]), 1)
                self.assertEqual(alert_history["alerts"][0]["status"], "session_ended")
                self.assertEqual(alert_history["alerts"][0]["zone_id"], "entry")
                self.assertEqual(client.get("/api/live/alerts").json()["active_count"], 0)
                repository.delete_live_session(session_id)

    def test_browser_hls_session_is_labeled_without_sending_playlist_url_to_backend(self):
        detector = SimpleNamespace(
            model_name="yolo11n.pt", device="cpu",
            detect_frame=lambda frame: ([Detection("person", 0.91, [1, 2, 30, 40])], frame),
        )
        with patch("app.api.live.get_detector", return_value=detector):
            with TestClient(app) as client:
                with client.websocket_connect("/api/live/ws", headers={"origin": "http://localhost:5173"}) as socket:
                    socket.send_json({"type": "select_browser_source", "source_kind": "hls"})
                    ready = socket.receive_json()
                    self.assertEqual(ready, {"type": "source_ready", "source_kind": "hls"})
                    socket.send_bytes(jpeg_frame())
                    observation = socket.receive_json()
                    self.assertEqual(observation["source_kind"], "hls")
                    session_id = observation["session_id"]
                history = client.get(f"/api/live/sessions/{session_id}").json()["session"]
                self.assertEqual(history["summary"]["source_kind"], "hls")
                client.delete(f"/api/live/sessions/{session_id}")

    def test_browser_hls_handshake_rejects_a_playlist_url(self):
        with TestClient(app) as client:
            with client.websocket_connect("/api/live/ws", headers={"origin": "http://localhost:5173"}) as socket:
                socket.send_json({
                    "type": "select_browser_source",
                    "source_kind": "hls",
                    "url": "https://camera.example/live.m3u8?secret=should-not-be-sent",
                })
                self.assertEqual(socket.receive_json()["type"], "source_error")
                session_id = get_live_status()["session_id"]
                socket.send_json({"type": "stop"})
                self.assertEqual(socket.receive_json()["type"], "session_stopped")
            client.delete(f"/api/live/sessions/{session_id}")

    def test_live_zone_reports_observed_entry_and_exit_for_continuing_track(self):
        boxes = iter((
            [30, 10, 54, 40],  # Starts outside the left-half zone.
            [25, 10, 49, 40],
            [18, 10, 42, 40],  # Enters the zone.
            [24, 10, 48, 40],  # Exits the zone.
        ))
        detector = SimpleNamespace(
            model_name="yolo11n.pt", device="cpu",
            detect_frame=lambda frame: ([Detection("person", 0.91, next(boxes))], frame),
        )
        zone = {"zone_id": "left", "name": "Left", "polygon": [[0, 0], [0.5, 0], [0.5, 1], [0, 1]]}
        with patch("app.api.live.get_detector", return_value=detector), patch("app.api.live.settings.LIVE_MIN_FRAME_INTERVAL_MS", 0):
            with TestClient(app) as client:
                with client.websocket_connect("/api/live/ws", headers={"origin": "http://localhost:5173"}) as socket:
                    socket.send_json({"type": "configure_zones", "zones": [zone]})
                    self.assertEqual(socket.receive_json()["type"], "zones_configured")
                    observations = []
                    for _ in range(4):
                        socket.send_bytes(jpeg_frame())
                        observations.append(socket.receive_json())
                    first, enter, inside, exit_zone = [item["zone_occupancy"][0] for item in observations]
                    self.assertEqual(first["observed_entries"], 0)
                    self.assertEqual(enter["entries_this_frame"], 0)
                    self.assertEqual(inside["entries_this_frame"], 1)
                    self.assertEqual(inside["observed_entries"], 1)
                    self.assertEqual(exit_zone["exits_this_frame"], 1)
                    self.assertEqual(exit_zone["observed_exits"], 1)
                    status = client.get("/api/live/status").json()
                    self.assertEqual(status["zone_occupancy"][0]["observed_entries"], 1)
                    self.assertEqual(status["zone_occupancy"][0]["observed_exits"], 1)
                    session_id = observations[-1]["session_id"]
                repository.delete_live_session(session_id)

    def test_live_early_warning_requires_capacity_and_recent_occupancy_deviation(self):
        calls = 0

        def detect_frame(frame):
            nonlocal calls
            calls += 1
            detections = [] if calls <= 6 else [
                Detection("person", 0.91, [2, 2, 18, 30]),
                Detection("person", 0.90, [34, 2, 50, 30]),
            ]
            return detections, frame

        detector = SimpleNamespace(model_name="yolo11n.pt", device="cpu", detect_frame=detect_frame)
        zone = {
            "zone_id": "entry", "name": "Entry", "polygon": [[0, 0], [1, 0], [1, 1], [0, 1]],
            "occupancy_capacity": 2,
        }
        with patch("app.api.live.get_detector", return_value=detector), patch("app.api.live.settings.LIVE_MIN_FRAME_INTERVAL_MS", 0):
            with TestClient(app) as client:
                with client.websocket_connect("/api/live/ws", headers={"origin": "http://localhost:5173"}) as socket:
                    socket.send_json({"type": "configure_zones", "zones": [zone]})
                    self.assertEqual(socket.receive_json()["type"], "zones_configured")
                    for _ in range(6):
                        socket.send_bytes(jpeg_frame())
                        observation = socket.receive_json()
                        live_zone = observation["zone_occupancy"][0]
                        self.assertEqual(live_zone["early_warning"]["status"], "insufficient_data")
                    socket.send_bytes(jpeg_frame())
                    observation = socket.receive_json()
                    live_zone = observation["zone_occupancy"][0]
                    self.assertEqual(live_zone["current_estimate"], 2)
                    self.assertEqual(live_zone["occupancy_anomaly"]["status"], "deviation_signal")
                    self.assertEqual(live_zone["early_warning"]["status"], "elevated")
                    self.assertIsNone(live_zone["early_warning"]["risk_score"])
                    session_id = observation["session_id"]
                history = client.get(f"/api/live/sessions/{session_id}").json()["session"]
                persisted_zone = history["summary"]["zone_occupancy"][0]
                self.assertEqual(persisted_zone["early_warning"]["status"], "elevated")
                client.delete(f"/api/live/sessions/{session_id}")

    def test_invalid_live_zone_configuration_does_not_break_stream(self):
        detector = SimpleNamespace(model_name="yolo11n.pt", device="cpu", detect_frame=lambda frame: ([], frame))
        with patch("app.api.live.get_detector", return_value=detector):
            with TestClient(app) as client:
                with client.websocket_connect("/api/live/ws", headers={"origin": "http://localhost:5173"}) as socket:
                    socket.send_json({"type": "configure_zones", "zones": [{"zone_id": "bad", "name": "Bad", "polygon": [[0, 0], [1, 1]]}]})
                    self.assertEqual(socket.receive_json()["type"], "zone_config_error")
                    socket.send_bytes(jpeg_frame())
                    observation = socket.receive_json()
                    self.assertEqual(observation["type"], "observation")
                    session_id = observation["session_id"]
                repository.delete_live_session(session_id)

    def test_live_source_is_rejected_when_upload_pipeline_owns_model(self):
        owner = "upload:test-reservation"
        self.assertTrue(reserve_pipeline(owner))
        self.addCleanup(release_pipeline, owner)
        with TestClient(app) as client:
            with client.websocket_connect(
                "/api/live/ws", headers={"origin": "http://localhost:5173"}
            ) as socket:
                rejected = socket.receive_json()
                self.assertEqual(rejected["type"], "rejected")
                self.assertIn("processing another source", rejected["detail"])


if __name__ == "__main__":
    unittest.main()
