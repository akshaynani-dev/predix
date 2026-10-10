"""Construct upload and live trackers from the shared CV configuration."""

from app.cv.config import cv_settings
from app.cv.tracking import AnonymousIoUTracker


def create_anonymous_tracker() -> AnonymousIoUTracker:
    """Return the common short-lived tracker used by every video source."""
    return AnonymousIoUTracker(
        iou_threshold=cv_settings.TRACK_IOU_THRESHOLD,
        max_missed_frames=cv_settings.TRACK_MAX_MISSED_FRAMES,
    )
