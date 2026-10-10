import unittest

from app.prediction.zone_occupancy import _errors, forecast_zone_occupancy


def occupancy(values, status="estimated"):
    return {
        "estimation_status": status,
        "timeline": [
            {"bucket_start_seconds": index * 15, "estimated_mean_visible_people": value}
            for index, value in enumerate(values)
        ],
    }


class ZoneOccupancyForecastTests(unittest.TestCase):
    def test_forecasts_use_rolling_validation_and_choose_improving_candidate(self):
        values = [0, 2, 4, 0] * 6
        result = forecast_zone_occupancy(occupancy(values), bucket_seconds=15, horizons=(60,))
        forecast = result["forecasts"][0]
        self.assertEqual(forecast["status"], "available")
        self.assertEqual(forecast["model"], "trailing horizon-window mean")
        self.assertEqual(forecast["evaluation"]["candidate_model"]["mae"], 0.0)
        self.assertEqual(forecast["evaluation"]["candidate_model"]["rmse"], 0.0)
        self.assertIsNone(forecast["evaluation"]["candidate_model"]["r_squared"])
        self.assertEqual(forecast["evaluation"]["baseline_model"]["rmse"], 1.5)
        self.assertIsNone(forecast["evaluation"]["baseline_model"]["r_squared"])
        self.assertEqual(forecast["evaluation"]["baseline_model"]["mae"], 1.5)
        self.assertEqual(forecast["target"], "mean_estimated_visible_people_in_zone")
        self.assertEqual(forecast["supporting_observations"], 24)
        self.assertEqual(forecast["as_of_seconds"], 360)

    def test_insufficient_or_unavailable_observations_do_not_forecast(self):
        short = forecast_zone_occupancy(occupancy([1] * 20), bucket_seconds=15, horizons=(60,))
        legacy = forecast_zone_occupancy(occupancy([1] * 30, status="unavailable"), bucket_seconds=15, horizons=(60,))
        self.assertEqual(short["forecasts"][0]["status"], "insufficient_data")
        self.assertIsNone(short["forecasts"][0]["forecast"])
        self.assertEqual(legacy["status"], "insufficient_data")

    def test_equal_candidate_and_baseline_error_selects_baseline(self):
        result = forecast_zone_occupancy(occupancy([3] * 24), bucket_seconds=15, horizons=(60,))
        forecast = result["forecasts"][0]
        self.assertEqual(forecast["status"], "available")
        self.assertEqual(forecast["model"], "persistence baseline (last observed occupancy)")
        self.assertEqual(forecast["forecast"], 3.0)

    def test_r_squared_is_undefined_for_constant_validation_actuals(self):
        result = forecast_zone_occupancy(occupancy([3] * 24), bucket_seconds=15, horizons=(60,))
        forecast = result["forecasts"][0]
        self.assertEqual(forecast["evaluation"]["selected_model"]["mae"], 0.0)
        self.assertEqual(forecast["evaluation"]["selected_model"]["rmse"], 0.0)
        self.assertIsNone(forecast["evaluation"]["selected_model"]["r_squared"])

    def test_validation_metrics_report_rmse_r_squared_and_mape(self):
        metrics = _errors([1, 2, 3], [1, 2, 4])
        self.assertEqual(metrics["mae"], 0.3333)
        self.assertEqual(metrics["rmse"], 0.5774)
        self.assertEqual(metrics["r_squared"], 0.5)
        self.assertEqual(metrics["mape_percent"], 11.1111)
        self.assertEqual(metrics["mape_samples"], 3)

    def test_mape_omits_zero_actuals_and_reports_denominator(self):
        result = forecast_zone_occupancy(occupancy([0, 2, 4, 0] * 6), bucket_seconds=15, horizons=(60,))
        metrics = result["forecasts"][0]["evaluation"]["candidate_model"]
        self.assertEqual(metrics["mape_percent"], 0.0)
        self.assertEqual(metrics["mape_samples"], 3)
        self.assertEqual(metrics["mape_zero_actuals_excluded"], 0)

    def test_mape_is_undefined_when_all_actuals_are_zero(self):
        result = forecast_zone_occupancy(occupancy([0] * 24), bucket_seconds=15, horizons=(60,))
        metrics = result["forecasts"][0]["evaluation"]["candidate_model"]
        self.assertIsNone(metrics["mape_percent"])
        self.assertEqual(metrics["mape_samples"], 0)
        self.assertGreater(metrics["mape_zero_actuals_excluded"], 0)


if __name__ == "__main__":
    unittest.main()
