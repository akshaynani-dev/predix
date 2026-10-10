import unittest

from app.analytics.anomalies import detect_occupancy_deviations


class OccupancyAnomalyTests(unittest.TestCase):
    def test_requires_a_prior_baseline(self):
        result = detect_occupancy_deviations([0, 1, 0, 1, 0, 1])
        self.assertEqual(result["status"], "insufficient_data")
        self.assertEqual(result["signals"], [])

    def test_stable_activity_does_not_emit_deviation(self):
        result = detect_occupancy_deviations([3] * 8)
        self.assertEqual(result["status"], "no_deviation_signal")

    def test_large_increase_reports_measured_evidence_not_risk(self):
        result = detect_occupancy_deviations([2] * 6 + [8])
        self.assertEqual(result["status"], "deviation_signal")
        self.assertEqual(result["latest_signal"]["observed_occupancy"], 8)
        self.assertIn("median 2.00", result["latest_signal"]["evidence"])
        self.assertIn("not evidence of an emergency", result["interpretation"])

    def test_noisy_baseline_and_configured_minimum_suppress_small_change(self):
        noisy = detect_occupancy_deviations([1, 2, 1, 2, 1, 2, 3.5])
        configured = detect_occupancy_deviations([2] * 6 + [8], minimum_increase=10)
        self.assertEqual(noisy["status"], "no_deviation_signal")
        self.assertEqual(configured["status"], "no_deviation_signal")


if __name__ == "__main__":
    unittest.main()
