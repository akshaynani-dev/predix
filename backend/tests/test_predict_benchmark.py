"""Tests for candidate-model predictions used by labeled detector evaluation."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from app.cv.benchmark import evaluate_detections
from app.cv.detector import Detection
from app.cv.predict_benchmark import predict_video


class FakeCapture:
    def __init__(self, _path):
        self.frames = [np.zeros((8, 8, 3), dtype=np.uint8) for _ in range(5)]
        self.released = False

    def isOpened(self):
        return True

    def read(self):
        if self.frames:
            return True, self.frames.pop(0)
        return False, None

    def release(self):
        self.released = True


class PredictBenchmarkTests(unittest.TestCase):
    def test_prediction_jsonl_round_trips_through_labeled_evaluator(self):
        detector = SimpleNamespace(
            model_name="candidate.pt", device="cpu", device_name="CPU",
            load_model=lambda: object(),
            detect_frame=lambda _frame: ([Detection("person", 0.9, [1, 2, 6, 7])], None),
        )
        capture = FakeCapture("unused")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / "evaluation.mp4"
            video.write_bytes(b"test")
            output = root / "candidate.jsonl"
            result = predict_video(
                video, output, frame_stride=2,
                detector_factory=lambda **_kwargs: detector,
                capture_factory=lambda _path: capture,
            )
            records = [json.loads(line) for line in output.read_text().splitlines()]
            truth = root / "labels.jsonl"
            truth.write_text("".join(json.dumps({
                "frame_number": frame_number,
                "detections": [{"class": "person", "bbox": records[0]["detections"][0]["bbox"]}],
            }) + "\n" for frame_number in range(1, 6)))
            quality = evaluate_detections(truth, output)

        self.assertEqual([record["frame_number"] for record in records], [1, 3, 5])
        self.assertEqual(result["inference_frames"], 3)
        self.assertEqual(quality["classes"]["person"]["true_positives"], 3)
        self.assertEqual(quality["classes"]["person"]["false_negatives"], 2)
        self.assertTrue(capture.released)

    def test_failure_does_not_replace_existing_output_and_releases_capture(self):
        detector = SimpleNamespace(
            model_name="candidate.pt", device="cpu", device_name="CPU",
            load_model=lambda: object(), detect_frame=lambda _frame: (_ for _ in ()).throw(RuntimeError("inference failed")),
        )
        capture = FakeCapture("unused")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / "evaluation.mp4"
            video.write_bytes(b"test")
            output = root / "candidate.jsonl"
            output.write_text("previous complete output\n")
            with self.assertRaisesRegex(RuntimeError, "inference failed"):
                predict_video(
                    video, output, overwrite=True,
                    detector_factory=lambda **_kwargs: detector,
                    capture_factory=lambda _path: capture,
                )
            self.assertEqual(output.read_text(), "previous complete output\n")
            self.assertEqual(list(root.glob("*.partial")), [])
        self.assertTrue(capture.released)

    def test_existing_output_requires_explicit_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / "evaluation.mp4"
            output = root / "candidate.jsonl"
            video.write_bytes(b"test")
            output.write_text("keep\n")
            with self.assertRaisesRegex(FileExistsError, "overwrite=True"):
                predict_video(video, output)

    def test_missing_candidate_checkpoint_does_not_attempt_remote_download(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / "evaluation.mp4"
            video.write_bytes(b"test")
            with self.assertRaisesRegex(FileNotFoundError, "present locally"):
                predict_video(video, root / "candidate.jsonl", model_name="missing-candidate.pt")


if __name__ == "__main__":
    unittest.main()
