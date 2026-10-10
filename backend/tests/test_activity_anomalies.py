import unittest

from app.analytics.anomalies import detect_activity_deviations


def buckets(values, *, gap_after=None, bucket_seconds=15):
    result = []
    index = 0
    for position, value in enumerate(values):
        if gap_after is not None and position >= gap_after:
            index += 1
        result.append({
            "bucket_start_seconds": index * bucket_seconds,
            "observed_frames": 10,
            "average_instances_per_observed_frame": value,
        })
        index += 1
    return result


class ActivityDeviationTests(unittest.TestCase):
    def detect(self, values, **kwargs):
        return detect_activity_deviations(
            buckets(values), bucket_seconds=15, baseline_buckets=3, **kwargs
        )

    def test_increase_is_compared_to_preceding_buckets_and_explained(self):
        result = self.detect([1, 1, 1, 5])

        self.assertEqual(result["status"], "deviation_signal")
        self.assertEqual(result["metric"], "average_instances_per_observed_frame")
        self.assertEqual(result["latest_signal"]["bucket_start_seconds"], 45)
        self.assertEqual(result["latest_signal"]["baseline_median_instances_per_frame"], 1)
        self.assertIn("preceding 3-bucket median", result["latest_signal"]["evidence"])
        self.assertIn("not evaluated", result["validation_status"])

    def test_stable_activity_does_not_signal(self):
        result = self.detect([2, 2, 2, 2, 2])

        self.assertEqual(result["status"], "no_deviation_signal")
        self.assertEqual(result["signals"], [])
        self.assertEqual(result["evaluated_windows"], 2)

    def test_increase_below_configured_minimum_does_not_signal(self):
        result = self.detect([1, 1, 1, 1.5], minimum_increase=1)

        self.assertEqual(result["status"], "no_deviation_signal")

    def test_missing_buckets_break_the_baseline_and_are_not_imputed(self):
        timeline = buckets([1, 1, 1, 5], gap_after=2)
        result = detect_activity_deviations(timeline, bucket_seconds=15, baseline_buckets=3)

        self.assertEqual(result["status"], "insufficient_data")
        self.assertEqual(result["signals"], [])
        self.assertEqual(result["required_consecutive_buckets"], 4)

    def test_short_history_is_insufficient(self):
        result = self.detect([0, 2, 1])

        self.assertEqual(result["status"], "insufficient_data")
        self.assertIsNone(result["latest_signal"])

    def test_invalid_rule_configuration_is_rejected(self):
        with self.assertRaises(ValueError):
            detect_activity_deviations([], bucket_seconds=15, mad_multiplier=float("nan"))


if __name__ == "__main__":
    unittest.main()
