import unittest
from types import SimpleNamespace
from unittest.mock import patch
from pydantic import ValidationError

from app.cv.tracking import AnonymousIoUTracker, estimate_tracked_zone_occupancy
from app.cv.tracker_factory import create_anonymous_tracker
from app.cv.config import CVSettings, cv_settings


def detection(box, class_name="person"):
    return SimpleNamespace(class_name=class_name, bbox=box)


class AnonymousTrackerTests(unittest.TestCase):
    def test_tracker_settings_reject_invalid_thresholds_and_retention(self):
        for settings in (
            {"TRACK_IOU_THRESHOLD": 0},
            {"TRACK_IOU_THRESHOLD": 1.1},
            {"TRACK_MAX_MISSED_FRAMES": -1},
            {"TRACK_MAX_MISSED_FRAMES": 11},
        ):
            with self.subTest(settings=settings), self.assertRaises(ValidationError):
                CVSettings(**settings)

    def test_shared_tracker_factory_uses_configured_association_and_retention(self):
        with patch.object(cv_settings, "TRACK_IOU_THRESHOLD", 0.6), patch.object(
            cv_settings, "TRACK_MAX_MISSED_FRAMES", 4,
        ):
            tracker = create_anonymous_tracker()
        self.assertEqual(tracker.iou_threshold, 0.6)
        self.assertEqual(tracker.max_missed_frames, 4)

    def test_associates_overlapping_same_class_boxes(self):
        tracker = AnonymousIoUTracker(iou_threshold=0.2)
        first = tracker.update([detection([0, 0, 20, 20])], timestamp_seconds=0)
        next_frame = tracker.update([detection([2, 0, 22, 20])], timestamp_seconds=1)
        self.assertEqual(first[0]["track_id"], next_frame[0]["track_id"])
        self.assertEqual(next_frame[0]["direction"]["dx_pixels"], 2.0)
        self.assertEqual(next_frame[0]["dwell_seconds"], 1.0)

    def test_expires_gaps_and_does_not_cross_match_classes(self):
        tracker = AnonymousIoUTracker(iou_threshold=0.2, max_missed_frames=1)
        first = tracker.update([detection([0, 0, 20, 20])])[0]["track_id"]
        other = tracker.update([detection([0, 0, 20, 20], "car")])[0]["track_id"]
        self.assertNotEqual(first, other)
        tracker.update([])
        after_expiry = tracker.update([detection([0, 0, 20, 20])])[0]["track_id"]
        self.assertNotEqual(first, after_expiry)

    def test_invalid_configuration_is_rejected(self):
        with self.assertRaises(ValueError):
            AnonymousIoUTracker(iou_threshold=0)

    def test_active_track_metadata_reports_missed_frames(self):
        tracker = AnonymousIoUTracker(max_missed_frames=1)
        track_id = tracker.update([detection([0, 0, 20, 20])])[0]["track_id"]
        tracker.update([])
        self.assertEqual(tracker.active_tracks[track_id]["class"], "person")
        self.assertEqual(tracker.active_tracks[track_id]["missed_frames"], 1)
        tracker.update([])
        self.assertNotIn(track_id, tracker.active_tracks)

    def test_zone_estimate_carries_only_active_person_tracks_at_last_known_zone(self):
        active = {
            "observed": {"class": "person", "missed_frames": 0},
            "missed": {"class": "person", "missed_frames": 1},
            "vehicle": {"class": "car", "missed_frames": 1},
        }
        result = estimate_tracked_zone_occupancy(
            active,
            {"observed": {"entry"}},
            {"missed": {"entry"}, "vehicle": {"entry"}},
        )
        self.assertEqual(result["entry"], {"count": 2, "observed_count": 1, "carried_count": 1})
