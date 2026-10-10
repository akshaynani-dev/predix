"""Tests for bounded live occupancy aggregation and validated forecasts."""

import unittest

from app.prediction.live_occupancy import LiveOccupancyForecaster


class LiveOccupancyForecasterTests(unittest.TestCase):
    def test_completed_bucket_is_reported_once_with_aggregate_evidence(self):
        forecaster = LiveOccupancyForecaster()
        forecaster.reset(["entry"])
        forecaster.observe("entry", 0, 1)
        forecaster.observe("entry", 14, 3)
        self.assertIsNone(forecaster.take_completed_bucket("entry"))
        forecaster.observe("entry", 15, 4)
        self.assertEqual(forecaster.take_completed_bucket("entry"), {
            "bucket_start_seconds": 0,
            "bucket_end_seconds": 15,
            "observation_count": 2,
            "estimated_mean_visible_people": 2,
        })
        self.assertIsNone(forecaster.take_completed_bucket("entry"))

    def test_requires_six_minutes_for_a_validated_one_minute_live_forecast(self):
        forecaster = LiveOccupancyForecaster()
        forecaster.reset(["entry"])

        forecast = None
        for elapsed in range(361):
            # A repeatable, measured sample series used only as a test fixture.
            estimate = [0, 2, 4, 0][(elapsed // 15) % 4]
            forecast = forecaster.observe("entry", elapsed, estimate)

        minute = next(item for item in forecast["forecasts"] if item["horizon_seconds"] == 60)
        five_minutes = next(item for item in forecast["forecasts"] if item["horizon_seconds"] == 300)
        self.assertEqual(minute["status"], "available")
        self.assertEqual(minute["supporting_observations"], 24)
        self.assertEqual(minute["evaluation"]["validation_windows"], 3)
        self.assertEqual(minute["target"], "mean_estimated_visible_people_in_zone")
        self.assertEqual(minute["evaluation"]["validation"], "chronological non-overlapping rolling-origin windows")
        self.assertEqual(five_minutes["status"], "insufficient_data")
        self.assertIsNone(five_minutes["forecast"])

    def test_missing_time_buckets_do_not_become_zero_occupancy(self):
        forecaster = LiveOccupancyForecaster()
        forecaster.reset(["entry"])
        forecast = None
        for elapsed in range(0, 361, 15):
            if 120 <= elapsed < 180:
                continue
            forecast = forecaster.observe("entry", elapsed, 2)

        self.assertEqual(forecast["status"], "insufficient_data")
        self.assertIn("continuous occupancy timeline", forecast["reason"])
        self.assertEqual(forecast["forecasts"], [])

    def test_zone_reconfiguration_clears_prior_forecast_history(self):
        forecaster = LiveOccupancyForecaster()
        forecaster.reset(["entry"])
        for elapsed in range(0, 361, 15):
            previous = forecaster.observe("entry", elapsed, 2)
        forecaster.reset(["entry"])
        current = forecaster.observe("entry", 0, 5)
        self.assertEqual(previous["status"], "available")
        self.assertEqual(current["status"], "insufficient_data")
        self.assertEqual(current["as_of_session_seconds"], 0)

    def test_rejects_negative_and_out_of_order_samples(self):
        forecaster = LiveOccupancyForecaster()
        forecaster.reset(["entry"])
        forecaster.observe("entry", 20, 1)
        with self.assertRaises(ValueError):
            forecaster.observe("entry", 19, 1)
        with self.assertRaises(ValueError):
            forecaster.observe("entry", 20, -1)


if __name__ == "__main__":
    unittest.main()
