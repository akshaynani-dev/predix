"""Tests for labeled occupancy-anomaly evaluation metrics."""

import json
import tempfile
import unittest
from pathlib import Path

from app.analytics.anomaly_benchmark import evaluate_occupancy_anomalies


class OccupancyAnomalyBenchmarkTests(unittest.TestCase):
    def write_rows(self, rows):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "labels.jsonl"
        path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        return path

    def test_reports_false_positives_false_negatives_and_classification_metrics(self):
        occupancies = [0, 0, 5, 0, 0, 3, 0]
        labels = [False, False, False, False, False, True, True]
        rows = [{
            "session_id": "s1",
            "zone_id": "entry",
            "bucket_start_seconds": index * 15,
            "estimated_occupancy": occupancy,
            "anomaly": label,
        } for index, (occupancy, label) in enumerate(zip(occupancies, labels))]
        result = evaluate_occupancy_anomalies(
            self.write_rows(rows), baseline_buckets=2, mad_multiplier=1, minimum_increase=2
        )
        self.assertEqual(result["confusion_matrix"], {
            "true_positive": 1,
            "false_positive": 1,
            "true_negative": 2,
            "false_negative": 1,
        })
        self.assertEqual(result["precision"], 0.5)
        self.assertEqual(result["recall"], 0.5)
        self.assertEqual(result["f1"], 0.5)
        self.assertEqual(result["excluded_warmup_buckets"], 2)

    def test_insufficient_history_returns_no_accuracy_metrics(self):
        rows = [{
            "session_id": "s1", "zone_id": "entry", "bucket_start_seconds": 0,
            "estimated_occupancy": 0, "anomaly": False,
        }]
        result = evaluate_occupancy_anomalies(self.write_rows(rows), baseline_buckets=2)
        self.assertEqual(result["status"], "insufficient_data")
        self.assertNotIn("precision", result)
        self.assertEqual(result["excluded_warmup_buckets"], 1)

    def test_groups_have_isolated_baselines(self):
        rows = []
        for index in range(3):
            rows.append({
                "session_id": "s1", "zone_id": "entry", "bucket_start_seconds": index * 15,
                "estimated_occupancy": [0, 0, 5][index], "anomaly": index == 2,
            })
            rows.append({
                "session_id": "s2", "zone_id": "entry", "bucket_start_seconds": index * 15,
                "estimated_occupancy": 0, "anomaly": False,
            })
        result = evaluate_occupancy_anomalies(
            self.write_rows(rows), baseline_buckets=2, mad_multiplier=1, minimum_increase=2
        )
        self.assertEqual(result["groups"], 2)
        self.assertEqual(result["evaluated_buckets"], 2)
        self.assertEqual(result["confusion_matrix"]["true_positive"], 1)
        self.assertEqual(result["confusion_matrix"]["true_negative"], 1)

    def test_rejects_gaps_duplicate_buckets_and_non_boolean_labels(self):
        base = {
            "session_id": "s1", "zone_id": "entry", "bucket_start_seconds": 0,
            "estimated_occupancy": 0, "anomaly": False,
        }
        variants = [
            [base, {**base, "bucket_start_seconds": 30}],
            [base, base],
            [{**base, "anomaly": 0}],
        ]
        for rows in variants:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                evaluate_occupancy_anomalies(self.write_rows(rows), bucket_seconds=15)


if __name__ == "__main__":
    unittest.main()
