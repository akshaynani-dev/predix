"""Tests for the shared frame-level inference and tracking boundary."""

import unittest

from app.cv.frame_processing import process_frame


class FrameProcessingTests(unittest.TestCase):
    def test_runs_detection_then_tracking_and_returns_annotation(self):
        frame = object()
        annotated = object()
        detections = [object()]
        tracked = [{"track_id": "temporary"}]
        calls = []

        class Detector:
            def detect_frame(self, received_frame):
                calls.append(("detect", received_frame))
                return detections, annotated

        class Tracker:
            def update(self, received_detections, timestamp_seconds):
                calls.append(("track", received_detections, timestamp_seconds))
                return tracked

        result = process_frame(Detector(), Tracker(), frame, 12.5)

        self.assertEqual(result, (detections, tracked, annotated))
        self.assertEqual(calls, [("detect", frame), ("track", detections, 12.5)])


if __name__ == "__main__":
    unittest.main()
