import unittest

from app.prediction.early_warning import build_crowd_early_warning


class EarlyWarningTests(unittest.TestCase):
    def setUp(self):
        self.occupancy = {
            "estimation_status": "estimated", "status": "HIGH",
            "current_estimate": 9, "configured_capacity": 10, "capacity_ratio": 0.9,
        }
        self.anomaly = {"status": "deviation_signal", "latest_signal": {
            "observed_occupancy": 9, "baseline_median": 3, "increase_over_baseline": 6,
            "evidence": "Observed occupancy exceeded the trailing baseline.",
        }}

    def test_combined_signals_have_explainable_human_review_cue(self):
        result = build_crowd_early_warning(self.occupancy, self.anomaly)
        self.assertEqual(result["status"], "elevated")
        self.assertEqual(len(result["signals"]), 2)
        self.assertEqual(result["recommendation"], "Human verification recommended for the combined occupancy signals.")
        self.assertIsNone(result["risk_score"])

    def test_single_signal_does_not_create_elevated_early_warning(self):
        result = build_crowd_early_warning(self.occupancy, {"status": "no_deviation_signal"})
        self.assertEqual(result["status"], "no_combined_signal")
        self.assertIsNone(result["recommendation"])

    def test_missing_capacity_or_tracking_returns_insufficient_data(self):
        occupancy = {**self.occupancy, "status": "UNCONFIGURED"}
        result = build_crowd_early_warning(occupancy, self.anomaly)
        self.assertEqual(result["status"], "insufficient_data")
        self.assertEqual(result["signals"], [])

    def test_missing_or_unknown_anomaly_state_is_not_reported_as_no_signal(self):
        for anomaly in (
            {}, {"status": "model_unavailable"}, {"status": "deviation_signal"},
            {"status": "deviation_signal", "latest_signal": {}},
        ):
            with self.subTest(anomaly=anomaly):
                result = build_crowd_early_warning(self.occupancy, anomaly)
                self.assertEqual(result["status"], "insufficient_data")
                self.assertEqual(result["signals"], [])
                self.assertIsNone(result["recommendation"])

    def test_unknown_occupancy_state_is_not_reported_as_no_signal(self):
        result = build_crowd_early_warning(
            {**self.occupancy, "status": "UNKNOWN"},
            {"status": "no_deviation_signal"},
        )
        self.assertEqual(result["status"], "insufficient_data")
        self.assertEqual(result["signals"], [])

    def test_incomplete_capacity_evidence_withholds_early_warning(self):
        occupancy = {**self.occupancy, "capacity_ratio": None}
        result = build_crowd_early_warning(occupancy, {"status": "no_deviation_signal"})
        self.assertEqual(result["status"], "insufficient_data")
        self.assertEqual(result["signals"], [])


if __name__ == "__main__":
    unittest.main()
