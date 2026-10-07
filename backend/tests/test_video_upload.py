"""Integration tests for validated, metadata-bearing video uploads."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app


class VideoUploadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def upload(self, filename: str, content: bytes, content_type: str = "video/mp4"):
        return self.client.post(
            "/api/video/upload",
            files={"file": (filename, content, content_type)},
        )

    def make_video(self, path: Path) -> None:
        writer = cv2.VideoWriter(
            str(path), cv2.VideoWriter_fourcc(*"mp4v"), 5.0, (64, 48)
        )
        if not writer.isOpened():
            self.skipTest("OpenCV MP4 writer is unavailable in this environment")
        for _ in range(5):
            writer.write(np.zeros((48, 64, 3), dtype=np.uint8))
        writer.release()

    def test_valid_video_returns_extracted_metadata_and_can_be_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.mp4"
            self.make_video(path)
            response = self.upload("sample.mp4", path.read_bytes())

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["metadata"]["width"], 64)
        self.assertEqual(payload["metadata"]["height"], 48)
        self.assertEqual(payload["metadata"]["frame_count"], 5)
        self.assertEqual(payload["metadata"]["fps"], 5.0)
        self.assertEqual(payload["metadata"]["duration_seconds"], 1.0)
        deleted = self.client.delete(f"/api/video/{payload['video_id']}")
        self.assertEqual(deleted.status_code, 200, deleted.text)

    def test_empty_upload_is_rejected(self) -> None:
        response = self.upload("empty.mp4", b"")

        self.assertEqual(response.status_code, 400)
        self.assertIn("empty", response.json()["detail"].lower())

    def test_corrupt_video_is_rejected_without_storing_it(self) -> None:
        before = {path.name for path in settings.upload_dir.iterdir() if path.is_file()}
        response = self.upload("corrupt.mp4", b"not a video")
        after = {path.name for path in settings.upload_dir.iterdir() if path.is_file()}

        self.assertEqual(response.status_code, 400)
        self.assertEqual(after, before)

    def test_unsupported_extension_and_mime_are_rejected(self) -> None:
        extension_response = self.upload("notes.txt", b"x", "video/mp4")
        mime_response = self.upload("clip.mp4", b"x", "application/octet-stream")

        self.assertEqual(extension_response.status_code, 400)
        self.assertEqual(mime_response.status_code, 400)

    def test_size_limit_is_enforced_before_video_decode(self) -> None:
        with patch.object(settings, "MAX_UPLOAD_SIZE_BYTES", 4):
            response = self.upload("large.mp4", b"12345")

        self.assertEqual(response.status_code, 413)


if __name__ == "__main__":
    unittest.main()
