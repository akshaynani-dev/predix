"""Tests for evidence-limited historical pattern discovery."""

import unittest

from app.analytics.patterns import discover_patterns


def make_session(video_id: str, counts: dict[str, int], zones: list[dict]) -> dict:
    return {
        "video_id": video_id,
        "summary": {"detection_instances_by_class": counts},
        "spatial_summary": {"zones": zones},
    }


class PatternDiscoveryTests(unittest.TestCase):
    def test_insufficient_history_is_explicit(self) -> None:
        result = discover_patterns([make_session("one", {"person": 2}, [])])

        self.assertEqual(result["patterns"], [])
        self.assertEqual(
            result["message"],
            "Insufficient historical data for reliable pattern analysis.",
        )

    def test_recurring_class_and_zone_pattern_include_evidence(self) -> None:
        sessions = [
            make_session(video_id, {"person": 2}, [
                {"zone_id": "entry", "name": "Entry", "detection_instances": 4},
                {"zone_id": "hall", "name": "Hall", "detection_instances": 1},
            ])
            for video_id in ("a", "b", "c")
        ]

        result = discover_patterns(sessions)

        self.assertEqual(result["session_count"], 3)
        self.assertEqual(len(result["patterns"]), 2)
        class_pattern = next(p for p in result["patterns"] if p["pattern_type"] == "recurring_object_class")
        zone_pattern = next(p for p in result["patterns"] if p["pattern_type"] == "recurrent_zone_activity")
        self.assertEqual(class_pattern["supporting_sessions"], 3)
        self.assertEqual(class_pattern["supporting_video_ids"], ["a", "b", "c"])
        self.assertEqual(zone_pattern["zone_id"], "entry")
        self.assertEqual(zone_pattern["supporting_sessions"], 3)

    def test_inconsistent_zone_names_do_not_create_zone_pattern(self) -> None:
        sessions = [
            make_session("a", {}, [{"zone_id": "shared", "name": "Entrance", "detection_instances": 5}]),
            make_session("b", {}, [{"zone_id": "shared", "name": "Parking", "detection_instances": 4}]),
            make_session("c", {}, [{"zone_id": "shared", "name": "Corridor", "detection_instances": 3}]),
        ]

        result = discover_patterns(sessions)

        self.assertEqual(result["patterns"], [])
        self.assertEqual(result["message"], "No recurring patterns met the evidence threshold.")


if __name__ == "__main__":
    unittest.main()
