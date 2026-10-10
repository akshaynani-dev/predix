import unittest
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from database_test_support import IsolatedDatabaseTestCase


class ZoneForecastApiTests(IsolatedDatabaseTestCase):
    def test_endpoint_returns_evaluated_forecasts_for_completed_zone(self):
        video_id = str(uuid.uuid4())
        points = [0, 2, 4, 0] * 6
        occupancy = {
            "estimation_status": "estimated",
            "timeline": [
                {"bucket_start_seconds": i * 15, "estimated_mean_visible_people": value}
                for i, value in enumerate(points)
            ],
        }
        spatial = {"zones": [{"zone_id": "entrance", "occupancy": occupancy}]}
        with patch("app.api.analysis._load_saved_result", return_value={"status": "completed"}), \
             patch("app.api.analysis.load_zones", return_value=[{"zone_id": "entrance", "name": "Entrance"}]), \
             patch("app.api.analysis.build_spatial_analytics", return_value=spatial):
            with TestClient(app) as client:
                response = client.get(f"/api/video/{video_id}/analysis/zones/entrance/forecast")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["forecasts"][0]["status"], "available")
        self.assertEqual(data["forecasts"][0]["supporting_observations"], 24)
        self.assertEqual(data["forecasts"][0]["as_of_seconds"], 360)
        self.assertEqual(data["forecasts"][1]["status"], "insufficient_data")
        self.assertEqual(data["forecasts"][2]["status"], "insufficient_data")


if __name__ == "__main__":
    unittest.main()
