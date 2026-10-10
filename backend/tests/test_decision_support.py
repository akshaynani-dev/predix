"""Tests for conservative evidence-linked decision support."""

import unittest

from app.prediction.decision_support import build_decision_support


def sessions_with_rates(rates):
    return [
        {
            "video_id": f"session-{index}",
            "created_at": f"2026-01-{index + 1:02d}T00:00:00+00:00",
            "summary": {
                "model": "yolo11n.pt",
                "confidence_threshold": 0.25,
                "frame_stride": 30,
                "image_size": 640,
                "inference_frames": 1,
                "total_detection_instances": rate,
            },
        }
        for index, rate in enumerate(rates)
    ]


class DecisionSupportTests(unittest.TestCase):
    def test_insufficient_data_never_recommends(self):
        result = build_decision_support(sessions_with_rates([2, 3, 4]))
        self.assertEqual(result["status"], "insufficient_data")
        self.assertEqual(result["recommendations"], [])

    def test_above_historical_threshold_links_evidence(self):
        result = build_decision_support(sessions_with_rates([1, 1, 1, 1, 1, 10]))
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["recommendations"][0]["type"], "review_resource_plan")
        self.assertEqual(result["recommendations"][0]["basis"]["supporting_video_ids"], [
            f"session-{index}" for index in range(6)
        ])

    def test_typical_prediction_does_not_recommend(self):
        result = build_decision_support(sessions_with_rates([2, 2, 2, 2, 2, 2]))
        self.assertEqual(result["recommendations"], [])
        self.assertIn("does not indicate", result["message"])


if __name__ == "__main__":
    unittest.main()
