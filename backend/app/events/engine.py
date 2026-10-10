"""Convert frame-level detections into explainable object activity events."""

import json
import os
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any


class EventDataError(ValueError):
    """Raised when a detection record cannot be transformed safely."""


def _zone_for_detection(
    bbox: dict[str, int], frame_width: int, frame_height: int, zones: list[dict[str, Any]]
) -> tuple[str | None, str | None]:
    center_x = (bbox["x1"] + bbox["x2"]) / (2 * frame_width)
    center_y = (bbox["y1"] + bbox["y2"]) / (2 * frame_height)
    for zone in zones:
        polygon = zone["polygon"]
        inside = False
        previous = len(polygon) - 1
        for current, (x_current, y_current) in enumerate(polygon):
            x_previous, y_previous = polygon[previous]
            crosses = (y_current > center_y) != (y_previous > center_y)
            if crosses and center_x < (
                (x_previous - x_current) * (center_y - y_current)
                / (y_previous - y_current) + x_current
            ):
                inside = not inside
            previous = current
        if inside:
            return zone["zone_id"], zone["name"]
    return None, None


def generate_events(
    detections_path: Path,
    events_path: Path,
    video_id: str,
    zones: list[dict[str, Any]] | None = None,
) -> int:
    """Group detected instances by frame and class, writing JSONL events."""
    if not detections_path.is_file():
        raise FileNotFoundError("Frame-level detection results were not found.")

    events_path.parent.mkdir(parents=True, exist_ok=True)
    staged_path = events_path.with_name(f".{events_path.name}.partial")
    event_count = 0
    try:
        with detections_path.open("r", encoding="utf-8") as source, staged_path.open(
            "w", encoding="utf-8"
        ) as destination:
            for line_number, line in enumerate(source, start=1):
                try:
                    frame = json.loads(line)
                    frame_number = int(frame["frame_number"])
                    timestamp = float(frame["timestamp_seconds"])
                    detections = frame["detections"]
                except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                    raise EventDataError(
                        f"Invalid detection record at line {line_number}."
                    ) from exc

                grouped: dict[tuple[str, str | None, str | None], list[dict[str, Any]]] = defaultdict(list)
                for detection in detections:
                    try:
                        object_class = str(detection["class"])
                        confidence = float(detection["confidence"])
                        bbox = detection["bbox"]
                        if not object_class or not 0 <= confidence <= 1:
                            raise ValueError
                        if not all(key in bbox for key in ("x1", "y1", "x2", "y2")):
                            raise ValueError
                    except (KeyError, TypeError, ValueError) as exc:
                        raise EventDataError(
                            f"Invalid detection in frame {frame_number}."
                        ) from exc
                    zone_id = zone_name = None
                    if zones:
                        frame_width = int(frame["frame_width"])
                        frame_height = int(frame["frame_height"])
                        if frame_width <= 0 or frame_height <= 0:
                            raise EventDataError(
                                f"Invalid frame dimensions at frame {frame_number}."
                            )
                        zone_id, zone_name = _zone_for_detection(
                            bbox, frame_width, frame_height, zones
                        )
                    grouped[(object_class, zone_id, zone_name)].append({
                        "confidence": confidence,
                        "bbox": {key: int(bbox[key]) for key in ("x1", "y1", "x2", "y2")},
                    })

                for (object_class, zone_id, zone_name), instances in grouped.items():
                    event_id = str(uuid.uuid5(
                        uuid.NAMESPACE_URL,
                        f"predix:{video_id}:{frame_number}:{object_class}:{zone_id}",
                    ))
                    event = {
                        "event_id": event_id,
                        "timestamp_seconds": timestamp,
                        "event_type": "object_detected",
                        "object_class": object_class,
                        "count": len(instances),
                        "zone_id": zone_id,
                        "zone_name": zone_name,
                        "confidence": round(
                            sum(item["confidence"] for item in instances) / len(instances), 4
                        ),
                        "source_video_id": video_id,
                        "metadata": {
                            "frame_number": frame_number,
                            "detections": [
                                {"confidence": item["confidence"], "bbox": item["bbox"]}
                                for item in instances
                            ],
                        },
                    }
                    destination.write(json.dumps(event, separators=(",", ":")) + "\n")
                    event_count += 1

        os.replace(staged_path, events_path)
        return event_count
    except Exception:
        staged_path.unlink(missing_ok=True)
        raise
