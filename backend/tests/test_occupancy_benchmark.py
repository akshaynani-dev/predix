import json
import tempfile
import unittest
from pathlib import Path

from app.cv.occupancy_benchmark import evaluate_occupancy


class OccupancyBenchmarkTests(unittest.TestCase):
    def test_reports_count_error_and_excludes_zero_frames_from_mape(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gt, pred = root / "gt.jsonl", root / "pred.jsonl"
            gt.write_text("".join(json.dumps({"frame_number": i, "detections": labels}) + "\n" for i, labels in [
                (1, [{"class": "person", "track_id": "a"}, {"class": "person", "track_id": "b"}]),
                (2, []),
            ]))
            pred.write_text("".join(json.dumps({"frame_number": i, "occupancy": {"data_kind": "estimated_visible_people", "count": count}}) + "\n" for i, count in [(1, 3), (2, 1)]))
            result = evaluate_occupancy(gt, pred)
        self.assertEqual(result["mae_people"], 1.0)
        self.assertEqual(result["rmse_people"], 1.0)
        self.assertEqual(result["bias_people"], 1.0)
        self.assertEqual(result["mape_percent_nonzero_ground_truth"], 50.0)
        self.assertEqual(result["mape_excluded_zero_ground_truth_frames"], 1)

    def test_no_person_frames_have_undefined_mape(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "gt.jsonl").write_text('{"frame_number": 1, "detections": []}\n')
            (root / "pred.jsonl").write_text('{"frame_number": 1, "occupancy": {"data_kind": "estimated_visible_people", "count": 0}}\n')
            result = evaluate_occupancy(root / "gt.jsonl", root / "pred.jsonl")
        self.assertIsNone(result["mape_percent_nonzero_ground_truth"])

    def test_accepts_temporally_stabilized_active_track_estimates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "gt.jsonl").write_text('{"frame_number": 1, "detections": []}\n')
            (root / "pred.jsonl").write_text(
                '{"frame_number": 1, "occupancy": {"data_kind": "estimated_active_person_tracks", "count": 0}}\n'
            )
            result = evaluate_occupancy(root / "gt.jsonl", root / "pred.jsonl")
        self.assertEqual(result["status"], "available")


if __name__ == "__main__":
    unittest.main()
