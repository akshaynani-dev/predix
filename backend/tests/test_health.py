"""Smoke tests for the Phase 1 FastAPI foundation."""

import unittest

from fastapi.testclient import TestClient

from app.main import app


class HealthEndpointTests(unittest.TestCase):
    def test_health_endpoint_reports_service(self) -> None:
        with TestClient(app) as client:
            response = client.get("/api/health")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "online")
        self.assertEqual(payload["service"], "PREDIX")
        self.assertTrue(payload["version"])

    def test_root_endpoint_is_available(self) -> None:
        with TestClient(app) as client:
            response = client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("PREDIX", response.json()["message"])


if __name__ == "__main__":
    unittest.main()
