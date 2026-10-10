"""Short-lived anonymous IoU association for frame-level detections.

IDs are random per stream, expire after missed frames, and are not identities.
"""

from dataclasses import dataclass
import uuid


@dataclass
class _Track:
    track_id: str
    class_name: str
    bbox: list[int]
    first_seen_seconds: float
    missed: int = 0


class AnonymousIoUTracker:
    def __init__(self, iou_threshold: float = 0.3, max_missed_frames: int = 2):
        if not 0 < iou_threshold <= 1 or max_missed_frames < 0:
            raise ValueError("Invalid tracker configuration.")
        self.iou_threshold = iou_threshold
        self.max_missed_frames = max_missed_frames
        self._tracks: dict[str, _Track] = {}

    @property
    def active_track_ids(self) -> set[str]:
        """Return the IDs still retained inside this tracker's missed-frame limit."""
        return set(self._tracks)

    @property
    def active_tracks(self) -> dict[str, dict]:
        """Expose anonymous track state for estimates without exposing identities."""
        return {
            track_id: {
                "class": track.class_name,
                "bbox": list(track.bbox),
                "missed_frames": track.missed,
            }
            for track_id, track in self._tracks.items()
        }

    @staticmethod
    def _iou(a: list[int], b: list[int]) -> float:
        x1, y1 = max(a[0], b[0]), max(a[1], b[1])
        x2, y2 = min(a[2], b[2]), min(a[3], b[3])
        intersection = max(0, x2 - x1) * max(0, y2 - y1)
        area_a = max(0, a[2] - a[0]) * max(0, a[3] - a[1])
        area_b = max(0, b[2] - b[0]) * max(0, b[3] - b[1])
        return intersection / max(area_a + area_b - intersection, 1e-12)

    def update(self, detections: list, timestamp_seconds: float = 0.0) -> list[dict]:
        candidates = []
        for track_id, track in self._tracks.items():
            for index, detection in enumerate(detections):
                if track.class_name == detection.class_name:
                    overlap = self._iou(track.bbox, detection.bbox)
                    if overlap >= self.iou_threshold:
                        candidates.append((overlap, track_id, index))
        candidates.sort(reverse=True)
        assigned_tracks: set[str] = set()
        assigned_detections: set[int] = set()
        matches: dict[int, str] = {}
        for _, track_id, index in candidates:
            if track_id not in assigned_tracks and index not in assigned_detections:
                assigned_tracks.add(track_id)
                assigned_detections.add(index)
                matches[index] = track_id

        for track_id, track in list(self._tracks.items()):
            if track_id not in assigned_tracks:
                track.missed += 1
                if track.missed > self.max_missed_frames:
                    del self._tracks[track_id]

        output = []
        for index, detection in enumerate(detections):
            track_id = matches.get(index)
            if track_id is None:
                track_id = uuid.uuid4().hex[:12]
                previous_center = None
                first_seen = timestamp_seconds
            else:
                previous = self._tracks[track_id]
                previous_center = (
                    (previous.bbox[0] + previous.bbox[2]) / 2,
                    (previous.bbox[1] + previous.bbox[3]) / 2,
                )
                first_seen = previous.first_seen_seconds
            current_bbox = list(detection.bbox)
            center = ((current_bbox[0] + current_bbox[2]) / 2, (current_bbox[1] + current_bbox[3]) / 2)
            direction = None if previous_center is None else {
                "dx_pixels": round(center[0] - previous_center[0], 2),
                "dy_pixels": round(center[1] - previous_center[1], 2),
                "basis": "image coordinates; positive y points down",
            }
            self._tracks[track_id] = _Track(
                track_id, detection.class_name, current_bbox,
                first_seen_seconds=first_seen,
            )
            output.append({
                "track_id": track_id,
                "class": detection.class_name,
                "bbox": current_bbox,
                "direction": direction,
                "dwell_seconds": round(max(0.0, timestamp_seconds - first_seen), 3),
            })
        return output


def estimate_tracked_zone_occupancy(
    active_tracks: dict[str, dict],
    observed_memberships: dict[str, set[str]],
    previous_memberships: dict[str, set[str]],
) -> dict[str, dict[str, int]]:
    """Count observed and briefly carried person tracks by their last known zone."""
    result: dict[str, dict[str, int]] = {}
    for track_id, track in active_tracks.items():
        if track.get("class") != "person":
            continue
        observed = track_id in observed_memberships
        memberships = observed_memberships.get(track_id, previous_memberships.get(track_id, set()))
        for zone_id in memberships:
            counts = result.setdefault(zone_id, {"count": 0, "observed_count": 0, "carried_count": 0})
            counts["count"] += 1
            counts["observed_count" if observed else "carried_count"] += 1
    return result
