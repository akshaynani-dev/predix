import unittest
from unittest.mock import Mock, patch

from app.cv.runtime import release_pipeline


class PipelineRuntimeTests(unittest.TestCase):
    def test_releasing_matching_pipeline_unloads_cached_detector(self):
        detector = Mock()
        with patch("app.cv.runtime._detector", detector), patch(
            "app.cv.runtime._active_pipeline", "live:session-1",
        ):
            release_pipeline("live:session-1")
        detector.unload_model.assert_called_once_with()

    def test_wrong_owner_cannot_unload_detector(self):
        detector = Mock()
        with patch("app.cv.runtime._detector", detector), patch(
            "app.cv.runtime._active_pipeline", "upload:session-1",
        ):
            release_pipeline("live:session-2")
        detector.unload_model.assert_not_called()

    def test_release_without_cached_detector_is_safe(self):
        with patch("app.cv.runtime._detector", None), patch(
            "app.cv.runtime._active_pipeline", "live:session-3",
        ):
            release_pipeline("live:session-3")


if __name__ == "__main__":
    unittest.main()
