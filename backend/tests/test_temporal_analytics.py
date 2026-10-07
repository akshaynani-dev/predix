"""Unit tests for temporal aggregates over stored frame observations."""

import json
import tempfile
import unittest
from pathlib import Path

from app.analytics.temporal import AnalyticsDataError, build_temporal_analytics


class TemporalAnalyticsTests(unittest.TestCase):
    def test_buckets_preserve_observations_and_derived_statistics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "detections.jsonl"
            records = [
                {
                    "timestamp_seconds": 0.2,
                    "frame_number": 1,
                    "detections": [
                        {"class": "person", "confidence": 0.9},
                        {"class": "person", "confidence": 0.8},
                    ],
                },
                {"timestamp_seconds": 1.5, "frame_number": 2, "detections": []},
                {"timestamp_seconds": 5.1, "frame_number": 3, "detections": [{"class": "car", "confidence": 0.4}]},
            ]
            path.write_text("".join(json.dumps(record) + "\n" for record in records))

            result = build_temporal_analytics(path, bucket_seconds=5)

        self.assertEqual(result["observation_source"], "stored_frame_detections")
        self.assertEqual(result["time_basis"], "video_seconds")
        self.assertEqual(result["sampled_frames"], 3)
        self.assertEqual(result["total_detection_instances"], 3)
        self.assertEqual(result["counts_by_class"], {"car": 1, "person": 2})
        self.assertEqual(result["confidence_distribution"][1]["count"], 1)
        self.assertEqual(result["confidence_distribution"][3]["count"], 2)
        timeline = result["aggregation"]["timeline"]
        self.assertEqual(len(timeline), 2)
        self.assertEqual(timeline[0]["observed_frames"], 2)
        self.assertEqual(timeline[0]["detection_instances"], 2)
        self.assertEqual(timeline[0]["counts_by_class"], {"person": 2})
        self.assertEqual(timeline[1]["counts_by_class"], {"car": 1})
        self.assertEqual(
            result["aggregation"]["statistics"]["mean_instances_per_observed_frame"],
            1.0,
        )

    def test_empty_observations_report_no_statistics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "detections.jsonl"
            path.write_text("")

            result = build_temporal_analytics(path, bucket_seconds=15)

        self.assertEqual(result["sampled_frames"], 0)
        self.assertEqual(result["aggregation"]["timeline"], [])
        self.assertIsNone(result["aggregation"]["statistics"]["peak_period"])

    def test_malformed_record_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "detections.jsonl"
            path.write_text("not json\n")

            with self.assertRaises(AnalyticsDataError):
                build_temporal_analytics(path, bucket_seconds=15)

    def test_excessive_timeline_requires_a_larger_bucket(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "detections.jsonl"
            path.write_text(json.dumps({
                "timestamp_seconds": 10_000,
                "frame_number": 1,
                "detections": [],
            }) + "\n")

            with self.assertRaises(AnalyticsDataError):
                build_temporal_analytics(path, bucket_seconds=1)


if __name__ == "__main__":
    unittest.main()
