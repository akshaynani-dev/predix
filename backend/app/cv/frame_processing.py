"""Shared per-frame detection and anonymous tracking pipeline."""

from typing import Any


def process_frame(
    detector: Any,
    tracker: Any,
    frame: Any,
    timestamp_seconds: float,
) -> tuple[list[Any], list[dict], Any]:
    """Run inference and temporal association for one frame from any source.

    Uploaded video and live camera ingestion both use this boundary so detector
    and tracker behavior stays consistent across input sources.
    """
    detections, annotated_frame = detector.detect_frame(frame)
    tracked_detections = tracker.update(
        detections,
        timestamp_seconds=timestamp_seconds,
    )
    return detections, tracked_detections, annotated_frame
