"""Tests for evaluated, time-ordered moving-average predictions."""

import unittest

from app.prediction.forecast import evaluate_and_predict_activity_rate


def make_session(index: int, rate: int, *, model: str = "yolo11n.pt") -> dict:
    return {
        "video_id": f"session-{index}",
        "created_at": f"2026-01-{index + 1:02d}T00:00:00+00:00",
        "summary": {
            "model": model,
            "confidence_threshold": 0.25,
            "frame_stride": 1,
            "image_size": 640,
            "inference_frames": 10,
            "total_detection_instances": rate * 10,
        },
        "spatial_summary": {"zones": []},
    }


class ActivityForecastTests(unittest.TestCase):
    def test_insufficient_history_does_not_generate_a_forecast(self) -> None:
        result = evaluate_and_predict_activity_rate([make_session(i, i) for i in range(5)])

        self.assertEqual(result["status"], "insufficient_data")
        self.assertIsNone(result["prediction"])
        self.assertEqual(result["message"], "Insufficient data for reliable prediction.")

    def test_forecast_uses_trailing_window_and_rolling_origin_metrics(self) -> None:
        result = evaluate_and_predict_activity_rate([make_session(i, i * 2) for i in range(6)])

        self.assertEqual(result["status"], "available")
        self.assertEqual(result["prediction"]["expected_value"], 8.0)
        self.assertEqual(result["prediction"]["period"], "next observed session")
        self.assertEqual(result["prediction"]["uncertainty"]["mae"], 4.0)
        self.assertEqual(result["evaluation"]["validation"], "rolling_origin_time_ordered")
        self.assertEqual(result["evaluation"]["test_windows"], 3)
        self.assertEqual(result["evaluation"]["rmse"], 4.0)
        self.assertEqual(result["evaluation"]["mape_percent"], 52.2222)
        self.assertEqual(result["evaluation"]["mape_samples"], 3)
        self.assertEqual(result["prediction"]["uncertainty"]["calibrated_probability"], False)

    def test_incompatible_model_configurations_are_not_mixed(self) -> None:
        sessions = [make_session(i, i, model="yolo11n.pt" if i < 5 else "another.pt") for i in range(6)]

        result = evaluate_and_predict_activity_rate(sessions)

        self.assertEqual(result["status"], "insufficient_data")
        self.assertEqual(result["observed_sessions"], 5)

    def test_mape_is_undefined_when_validation_actuals_are_zero(self) -> None:
        result = evaluate_and_predict_activity_rate([make_session(i, 0) for i in range(6)])
        self.assertIsNone(result["evaluation"]["mape_percent"])
        self.assertEqual(result["evaluation"]["mape_samples"], 0)
        self.assertEqual(result["evaluation"]["mape_zero_actuals_excluded"], 3)


if __name__ == "__main__":
    unittest.main()
