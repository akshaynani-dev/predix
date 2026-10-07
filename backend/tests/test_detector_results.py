"""Tests for structured frame-level detector output and sampling."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from app.cv.detector import Detection, ObjectDetector
from app.cv.config import CVSettings


class DetectorResultTests(unittest.TestCase):
    def make_video(self, path: Path, frame_count: int = 5) -> None:
        writer = cv2.VideoWriter(
            str(path), cv2.VideoWriter_fourcc(*"mp4v"), 5.0, (64, 48)
        )
        if not writer.isOpened():
            self.skipTest("OpenCV MP4 writer is unavailable in this environment")
        for _ in range(frame_count):
            writer.write(np.zeros((48, 64, 3), dtype=np.uint8))
        writer.release()

    def run_detector(self, frame_stride: int) -> tuple[object, list[dict], Path]:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        source = root / "source.mp4"
        output = root / "annotated.mp4"
        detection_output = root / "detections.jsonl"
        self.make_video(source)

        detector = ObjectDetector(frame_stride=frame_stride)
        fixture_detection = Detection("person", 0.91, [1, 2, 30, 40])
        with patch.object(
            detector,
            "detect_frame",
            side_effect=lambda frame: ([fixture_detection], frame.copy()),
        ):
            result = detector.process_video(
                "test-video",
                source,
                output,
                detection_output,
            )

        records = [json.loads(line) for line in detection_output.read_text().splitlines()]
        self.assertTrue(output.is_file())
        return result, records, detection_output

    def test_detection_records_have_public_schema_and_counts(self) -> None:
        result, records, _ = self.run_detector(frame_stride=1)

        self.assertEqual(len(records), 5)
        self.assertEqual(records[0]["frame_number"], 1)
        self.assertEqual(records[0]["timestamp_seconds"], 0.0)
        self.assertEqual(records[0]["detections"][0]["class"], "person")
        self.assertEqual(records[0]["detections"][0]["confidence"], 0.91)
        self.assertEqual(
            records[0]["detections"][0]["bbox"],
            {"x1": 1, "y1": 2, "x2": 30, "y2": 40},
        )
        self.assertEqual(result.total_detection_instances, 5)
        self.assertEqual(result.inference_frames, 5)

    def test_frame_stride_samples_deterministically(self) -> None:
        result, records, _ = self.run_detector(frame_stride=2)

        self.assertEqual([record["frame_number"] for record in records], [1, 3, 5])
        self.assertEqual(result.frames_processed, 5)
        self.assertEqual(result.inference_frames, 3)

    def test_nonpositive_frame_stride_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ObjectDetector(frame_stride=0)

    def test_missing_model_weights_surface_as_a_processing_error(self) -> None:
        detector = ObjectDetector()
        with patch("ultralytics.YOLO", side_effect=FileNotFoundError("weights missing")):
            with self.assertRaisesRegex(FileNotFoundError, "weights missing"):
                detector.load_model()

    def test_invalid_device_configuration_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            CVSettings(DEVICE="remote")


if __name__ == "__main__":
    unittest.main()
