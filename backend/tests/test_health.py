"""Smoke tests for the Phase 1 FastAPI foundation."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from database_test_support import IsolatedDatabaseTestCase


class HealthEndpointTests(IsolatedDatabaseTestCase):
    def test_database_failure_is_reported_as_offline(self) -> None:
        with patch("app.api.health.repository.health_check", side_effect=RuntimeError("db unavailable")):
            with TestClient(app) as client:
                response = client.get("/api/health")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["components"]["database"]["status"], "OFFLINE")
        self.assertEqual(payload["status"], "degraded")

    def test_unavailable_resource_telemetry_does_not_degrade_service_health(self) -> None:
        with patch("app.api.health.process_resource_metrics", return_value={"status": "unavailable"}):
            with TestClient(app) as client:
                response = client.get("/api/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "online")
        self.assertEqual(response.json()["process_resources"]["status"], "unavailable")

    def test_health_endpoint_reports_service(self) -> None:
        with TestClient(app) as client:
            response = client.get("/api/health")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "online")
        self.assertEqual(payload["service"], "PREDIX")
        self.assertTrue(payload["version"])
        self.assertEqual(payload["components"]["backend"]["status"], "ONLINE")
        self.assertIn(payload["components"]["database"]["status"], {"ONLINE", "OFFLINE"})
        self.assertIn(payload["components"]["ai_engine"]["model_state"], {"READY", "NOT_LOADED", "UNAVAILABLE"})
        self.assertIn(payload["components"]["detection_model"]["status"], {"ONLINE", "DEGRADED"})
        self.assertIn(payload["components"]["detection_model"]["model_state"], {"READY", "NOT_LOADED", "CHECKPOINT_NOT_FOUND", "LOAD_FAILED"})
        self.assertIn("live_stream_engine", payload["components"])
        self.assertIn(payload["process_resources"]["status"], {"available", "unavailable"})
        self.assertIn("process_peak_rss_mb_since_start", payload["process_resources"])
        self.assertIn("measurement_notes", payload["process_resources"])

    def test_detection_model_reports_missing_local_checkpoint_without_downloading(self) -> None:
        detector = SimpleNamespace(model_name="missing-model.pt", device="cpu", _model=None, _model_load_error=None)
        with patch("app.api.health.get_detector", return_value=detector):
            with TestClient(app) as client:
                response = client.get("/api/health")

        self.assertEqual(response.status_code, 200)
        model = response.json()["components"]["detection_model"]
        self.assertEqual(model["status"], "DEGRADED")
        self.assertEqual(model["model_state"], "CHECKPOINT_NOT_FOUND")
        self.assertIn("do not download", model["detail"])

    def test_loaded_detection_model_reports_class_count(self) -> None:
        model = SimpleNamespace(names={0: "person", 1: "car"})
        detector = SimpleNamespace(model_name="local-model.pt", device="cpu", _model=model, _model_load_error=None)
        with patch("app.api.health.get_detector", return_value=detector):
            with TestClient(app) as client:
                response = client.get("/api/health")

        self.assertEqual(response.json()["components"]["detection_model"]["status"], "ONLINE")
        self.assertEqual(response.json()["components"]["detection_model"]["model_state"], "READY")
        self.assertEqual(response.json()["components"]["detection_model"]["class_count"], 2)

    def test_health_reports_previous_model_load_failure_as_degraded(self) -> None:
        detector = SimpleNamespace(model_name="yolo11n.pt", device="cpu", _model=None, _model_load_error="RuntimeError")
        with patch("app.api.health.get_detector", return_value=detector):
            with TestClient(app) as client:
                response = client.get("/api/health")

        model = response.json()["components"]["detection_model"]
        self.assertEqual(model["status"], "DEGRADED")
        self.assertEqual(model["model_state"], "LOAD_FAILED")
        self.assertEqual(model["failure_type"], "RuntimeError")
        self.assertNotIn("weights missing", model["detail"])

    def test_root_endpoint_is_available(self) -> None:
        with TestClient(app) as client:
            response = client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("PREDIX", response.json()["message"])


if __name__ == "__main__":
    unittest.main()
