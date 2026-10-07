"""Metadata extraction for uploaded video files."""

from pathlib import Path
import math
from typing import TypedDict

import cv2


class VideoMetadata(TypedDict):
    duration_seconds: float
    width: int
    height: int
    fps: float
    frame_count: int


class VideoMetadataError(ValueError):
    """Raised when a file cannot be decoded as a usable video."""


def extract_video_metadata(path: Path) -> VideoMetadata:
    """Read container metadata and decode one frame to reject invalid files."""
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        capture.release()
        raise VideoMetadataError("The uploaded file is not a readable video.")

    try:
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        has_frame, _ = capture.read()

        if (
            not has_frame
            or width <= 0
            or height <= 0
            or not math.isfinite(fps)
            or fps <= 0
            or frame_count <= 0
        ):
            raise VideoMetadataError("The uploaded file is not a readable video.")

        return {
            "duration_seconds": round(frame_count / fps, 3),
            "width": width,
            "height": height,
            "fps": round(fps, 3),
            "frame_count": frame_count,
        }
    except cv2.error as exc:
        raise VideoMetadataError("The uploaded file is not a readable video.") from exc
    finally:
        capture.release()
