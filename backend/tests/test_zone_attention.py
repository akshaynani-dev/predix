import unittest

from app.prediction.zone_attention import recommend_zone_attention


class ZoneAttentionTests(unittest.TestCase):
    def setUp(self):
        self.occupancy = {
            "estimation_status": "estimated",
            "status": "HIGH",
            "current_estimate": 18,
            "configured_capacity": 20,
            "capacity_ratio": 0.9,
        }
        self.anomaly = {
            "status": "deviation_signal",
            "latest_signal": {
                "evidence": "Observed estimate exceeded the configured trailing baseline.",
                "increase_over_baseline": 8,
            },
        }

    def test_combined_capacity_and_deviation_recommend_human_review(self):
        result = recommend_zone_attention(self.occupancy, self.anomaly)
        self.assertEqual(result["status"], "priority_review")
        self.assertEqual(len(result["signals"]), 2)
        self.assertIn("human", result["recommendation"].lower())
        self.assertIn("not been validated", result["validation_status"])
        self.assertNotIn("risk_score", result)

    def test_capacity_only_recommends_review_against_configured_limit(self):
        result = recommend_zone_attention(self.occupancy, {"status": "no_deviation_signal"})
        self.assertEqual(result["status"], "capacity_review")
        self.assertEqual(len(result["signals"]), 1)

    def test_deviation_only_recommends_review_of_observed_change(self):
        occupancy = {**self.occupancy, "status": "MODERATE"}
        result = recommend_zone_attention(occupancy, self.anomaly)
        self.assertEqual(result["status"], "occupancy_change_review")

    def test_no_trigger_is_not_presented_as_assurance_of_safety(self):
        occupancy = {**self.occupancy, "status": "NORMAL"}
        result = recommend_zone_attention(occupancy, {"status": "no_deviation_signal"})
        self.assertEqual(result["status"], "no_configured_trigger")
        self.assertIn("does not mean the zone is safe", result["recommendation"])

    def test_missing_tracking_or_capacity_withholds_recommendation(self):
        for occupancy in (
            {"estimation_status": "unavailable", "status": "UNAVAILABLE"},
            {**self.occupancy, "status": "UNCONFIGURED", "configured_capacity": None},
        ):
            with self.subTest(occupancy=occupancy):
                result = recommend_zone_attention(occupancy, self.anomaly)
                self.assertEqual(result["status"], "unavailable")
                self.assertIsNone(result["recommendation"])

    def test_insufficient_anomaly_history_does_not_look_like_no_trigger(self):
        occupancy = {**self.occupancy, "status": "NORMAL"}
        result = recommend_zone_attention(occupancy, {"status": "insufficient_data"})
        self.assertEqual(result["status"], "insufficient_data")
        self.assertIsNone(result["recommendation"])
        self.assertIn("does not mean the zone is safe", result["limitation"])


if __name__ == "__main__":
    unittest.main()
