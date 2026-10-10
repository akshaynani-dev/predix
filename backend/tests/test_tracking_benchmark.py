import json
import tempfile
import unittest
from pathlib import Path

from app.cv.tracking_benchmark import evaluate_tracking


class TrackingBenchmarkTests(unittest.TestCase):
    def test_consistent_tracks_have_no_switch_or_fragmentation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gt, pred = root / "gt.jsonl", root / "pred.jsonl"
            box = {"x1": 0, "y1": 0, "x2": 10, "y2": 10}
            gt.write_text("".join(json.dumps({"frame_number": i, "detections": [{"class": "person", "track_id": "person-1", "bbox": box}]}) + "\n" for i in (1, 2, 3)))
            pred.write_text("".join(json.dumps({"frame_number": i, "detections": [{"class": "person", "track_id": "pred-1", "bbox": box}]}) + "\n" for i in (1, 2, 3)))
            result = evaluate_tracking(gt, pred)
        self.assertEqual(result["mota"], 1.0)
        self.assertEqual(result["id_switches"], 0)
        self.assertEqual(result["fragmentations"], 0)

    def test_id_switch_and_gap_are_counted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gt, pred = root / "gt.jsonl", root / "pred.jsonl"
            box = {"x1": 0, "y1": 0, "x2": 10, "y2": 10}
            gt.write_text("".join(json.dumps({"frame_number": i, "detections": [{"class": "person", "track_id": "person-1", "bbox": box}]}) + "\n" for i in (1, 2, 3)))
            pred.write_text("".join(json.dumps({"frame_number": i, "detections": detections}) + "\n" for i, detections in [
                (1, [{"class": "person", "track_id": "pred-1", "bbox": box}]),
                (2, []),
                (3, [{"class": "person", "track_id": "pred-2", "bbox": box}]),
            ]))
            result = evaluate_tracking(gt, pred)
        self.assertEqual(result["id_switches"], 1)
        self.assertEqual(result["fragmentations"], 1)
        self.assertAlmostEqual(result["mota"], 1 / 3, places=3)


if __name__ == "__main__":
    unittest.main()
