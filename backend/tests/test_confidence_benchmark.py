"""Tests for offline, label-based detector threshold comparison."""

import json
import tempfile
import unittest
from pathlib import Path

from app.cv.confidence_benchmark import evaluate_confidence_thresholds


class ConfidenceBenchmarkTests(unittest.TestCase):
    def test_compares_candidates_on_same_labels_without_automatic_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / "scene.mp4"
            video.write_bytes(b"fixture")
            truth = root / "labels.jsonl"
            truth.write_text(json.dumps({
                "frame_number": 1,
                "detections": [{"class": "person", "bbox": {"x1": 0, "y1": 0, "x2": 10, "y2": 10}}],
            }) + "\n", encoding="utf-8")

            def predict(_video, output, *, confidence_threshold, **configuration):
                detections = []
                if confidence_threshold < 0.5:
                    detections.append({
                        "class": "person",
                        "confidence": 0.6,
                        "bbox": {"x1": 0, "y1": 0, "x2": 10, "y2": 10},
                    })
                output.write_text(json.dumps({"frame_number": 1, "detections": detections}) + "\n", encoding="utf-8")
                return {"model": "fixture-model", "device": "cpu", "video_frames_read": 1, "inference_frames": 1}

            result = evaluate_confidence_thresholds(
                video,
                truth,
                [0.5, 0.25],
                model_name="fixture-model",
                prediction_runner=predict,
            )

        self.assertFalse(result["automatic_threshold_selection"])
        self.assertEqual([item["confidence_threshold"] for item in result["candidates"]], [0.25, 0.5])
        self.assertEqual(result["candidates"][0]["evaluation"]["classes"]["person"]["recall"], 1.0)
        self.assertEqual(result["candidates"][1]["evaluation"]["classes"]["person"]["false_negatives"], 1)

    def test_rejects_empty_invalid_and_duplicate_candidates(self):
        with self.assertRaisesRegex(ValueError, "at least one"):
            evaluate_confidence_thresholds(Path("video"), Path("labels"), [])
        with self.assertRaisesRegex(ValueError, "finite values"):
            evaluate_confidence_thresholds(Path("video"), Path("labels"), [float("nan")])
        with self.assertRaisesRegex(ValueError, "duplicates"):
            evaluate_confidence_thresholds(Path("video"), Path("labels"), [0.25, 0.25])


if __name__ == "__main__":
    unittest.main()
