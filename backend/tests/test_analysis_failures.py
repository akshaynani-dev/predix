"""Failure handling for background analysis and persisted job state."""

import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, PropertyMock, patch

from app.api import analysis
from app.core.config import Settings
from app.database.sqlite_repository import SQLiteRepository


class AnalysisFailureTests(unittest.TestCase):
    def test_model_loading_failure_sets_sanitized_error_and_cleans_artifacts(self):
        video_id = str(uuid.uuid4())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = SQLiteRepository(root / "history.sqlite3")
            repository.initialize()
            repository.create_session(
                video_id=video_id,
                filename="sample.mp4",
                stored_filename=f"{video_id}_sample.mp4",
                content_type="video/mp4",
                size_bytes=123,
                metadata={"duration_seconds": 1, "width": 64, "height": 48, "fps": 5, "frame_count": 5},
            )
            repository.set_status(video_id, "analyzing")
            (root / f"{video_id}_annotated.mp4").write_bytes(b"partial")
            (root / f"{video_id}_detections.jsonl").write_text("partial")
            (root / f"{video_id}_events.jsonl").write_text("partial")
            analysis._analysis_jobs[video_id] = {"status": "analyzing"}
            self.addCleanup(analysis._analysis_jobs.pop, video_id, None)
            detector = SimpleNamespace(
                process_video=Mock(side_effect=FileNotFoundError("private weights path"))
            )

            with (
                patch("app.api.analysis.repository", repository),
                patch.object(Settings, "analysis_dir", new_callable=PropertyMock, return_value=root),
                patch.object(analysis, "_get_detector", return_value=detector),
            ):
                analysis._run_analysis_worker(
                    "job-id", video_id, root / "source.mp4", root / f"{video_id}_annotated.mp4", []
                )

            self.assertEqual(repository.get_session(video_id)["status"], "error")
            self.assertEqual(
                analysis._analysis_jobs[video_id]["error"],
                "Video analysis failed. Check backend logs and retry.",
            )
            self.assertFalse((root / f"{video_id}_annotated.mp4").exists())
            self.assertFalse((root / f"{video_id}_detections.jsonl").exists())
            self.assertFalse((root / f"{video_id}_events.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
