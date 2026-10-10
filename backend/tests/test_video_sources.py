"""Tests for the shared uploaded/live frame-source boundary."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import cv2
import numpy as np

from app.video_processing.sources import RTSPVideoSource, UploadedVideoSource, VideoSourceError


class VideoSourceTests(unittest.TestCase):
    def test_uploaded_source_exposes_frames_and_releases_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.mp4"
            writer = cv2.VideoWriter(
                str(path), cv2.VideoWriter_fourcc(*"mp4v"), 5.0, (64, 48)
            )
            if not writer.isOpened():
                self.skipTest("OpenCV MP4 writer is unavailable")
            writer.write(np.zeros((48, 64, 3), dtype=np.uint8))
            writer.release()

            source = UploadedVideoSource(path)
            source.open()
            self.assertTrue(source.is_opened())
            self.assertEqual(int(source.get(cv2.CAP_PROP_FRAME_WIDTH)), 64)
            ok, frame = source.read()
            self.assertTrue(ok)
            self.assertEqual(frame.shape[:2], (48, 64))
            source.release()
            self.assertFalse(source.is_opened())

    def test_unreadable_source_fails_with_safe_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "not-a-video.mp4"
            path.write_bytes(b"not a video")
            source = UploadedVideoSource(path)
            with self.assertRaisesRegex(VideoSourceError, "configured video source"):
                source.open()
            self.assertFalse(source.is_opened())

    def test_rtsp_source_requires_an_allowlisted_host(self):
        for url in (
            "http://camera.example/live",
            "rtsp://other.example/live",
            "rtsp://camera.example",
        ):
            with self.subTest(url=url):
                with self.assertRaisesRegex(VideoSourceError, "invalid or its host is not allowlisted"):
                    RTSPVideoSource(url, allowed_hosts=["camera.example"])

    def test_rtsp_source_uses_ffmpeg_and_bounded_open_read_timeouts(self):
        capture = Mock()
        capture.isOpened.return_value = True
        source = RTSPVideoSource(
            "rtsps://user:password@camera.example/live",
            allowed_hosts=["CAMERA.EXAMPLE."],
            open_timeout_ms=4000,
            read_timeout_ms=1500,
        )

        with patch("app.video_processing.sources.cv2.VideoCapture", return_value=capture) as open_capture:
            source.open()
            args = open_capture.call_args.args
            self.assertEqual(args[0], "rtsps://user:password@camera.example/live")
            self.assertEqual(args[1], cv2.CAP_FFMPEG)
            self.assertEqual(args[2], [
                cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 4000,
                cv2.CAP_PROP_READ_TIMEOUT_MSEC, 1500,
            ])
            source.release()

        capture.release.assert_called_once()


if __name__ == "__main__":
    unittest.main()
