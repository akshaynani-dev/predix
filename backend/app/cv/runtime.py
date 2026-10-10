"""Shared detector and single-pipeline reservation for resource-safe inference."""

import threading

from app.cv.detector import ObjectDetector

_detector: ObjectDetector | None = None
_detector_lock = threading.Lock()
_pipeline_lock = threading.Lock()
_active_pipeline: str | None = None


def get_detector() -> ObjectDetector:
    """Load one detector lazily for uploaded and live frame sources."""
    global _detector
    if _detector is None:
        with _detector_lock:
            if _detector is None:
                _detector = ObjectDetector()
    return _detector


def loaded_model_class_names() -> list[str] | None:
    """Return the actual class vocabulary only after the configured model is loaded."""
    with _detector_lock:
        if _detector is None or _detector._model is None:
            return None
        names = getattr(_detector._model, "names", None)
        if isinstance(names, dict):
            return [str(names[key]) for key in sorted(names)]
        if isinstance(names, (list, tuple)):
            return [str(name) for name in names]
        return None


def reserve_pipeline(owner: str) -> bool:
    """Allow only one inference source to use the local model at a time."""
    global _active_pipeline
    with _pipeline_lock:
        if _active_pipeline is not None:
            return False
        _active_pipeline = owner
        return True


def release_pipeline(owner: str) -> None:
    """Unload inference resources and release only the matching source reservation."""
    global _active_pipeline
    with _pipeline_lock:
        if _active_pipeline == owner:
            if _detector is not None:
                with _detector_lock:
                    _detector.unload_model()
            _active_pipeline = None


def active_pipeline() -> str | None:
    with _pipeline_lock:
        return _active_pipeline
