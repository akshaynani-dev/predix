"""Runtime and resource benchmarking tests, separate from quality evaluation."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from app.cv.performance_benchmark import benchmark_video


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


class PerformanceBenchmarkTests(unittest.TestCase):
    def test_reports_timing_and_process_memory_separately_from_quality(self):
        detector = SimpleNamespace(
            model_name="candidate.pt", device="mps", device_name="Apple MPS",
            load_model=lambda: object(), detect_frame=lambda _frame: ([], None),
        )
        capture = FakeCapture("unused")
        with tempfile.NamedTemporaryFile() as video, patch(
            "app.cv.performance_benchmark._peak_rss_megabytes", return_value=321.5
        ):
            result = benchmark_video(
                Path(video.name), model_name="candidate.pt", frame_stride=2,
                warmup_frames=1,
                detector_factory=lambda **_kwargs: detector,
                capture_factory=lambda _path: capture,
            )

        self.assertEqual(result["model"], "candidate.pt")
        self.assertEqual(result["device"], "mps")
        self.assertEqual(result["video_frames_read"], 5)
        self.assertEqual(result["inference_frames_including_warmup"], 3)
        self.assertEqual(result["warmup_inference_frames_excluded"], 1)
        self.assertEqual(result["measured_inference_frames"], 2)
        self.assertIsNotNone(result["p50_inference_latency_ms"])
        self.assertIsNotNone(result["p95_inference_latency_ms"])
        self.assertEqual(result["process_peak_rss_mb"], 321.5)
        self.assertIn("not_measured", result["quality_metrics"])
        self.assertTrue(capture.released)

    def test_rejects_video_without_frames_after_warmup_and_releases_capture(self):
        detector = SimpleNamespace(
            model_name="candidate.pt", device="cpu", device_name="CPU",
            load_model=lambda: object(), detect_frame=lambda _frame: ([], None),
        )
        capture = FakeCapture("unused")
        capture.frames = [np.zeros((8, 8, 3), dtype=np.uint8)]
        with tempfile.NamedTemporaryFile() as video:
            with self.assertRaisesRegex(ValueError, "no measured inference frames"):
                benchmark_video(
                    Path(video.name), warmup_frames=1,
                    detector_factory=lambda **_kwargs: detector,
                    capture_factory=lambda _path: capture,
                )
        self.assertTrue(capture.released)


if __name__ == "__main__":
    unittest.main()
