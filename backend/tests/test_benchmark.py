import json
import tempfile
import unittest
from pathlib import Path

from app.cv.benchmark import evaluate_detections


class DetectionBenchmarkTests(unittest.TestCase):
    def test_metrics_match_by_frame_class_and_iou(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            truth = root / "truth.jsonl"
            predictions = root / "predictions.jsonl"
            box = {"x1": 0, "y1": 0, "x2": 10, "y2": 10}
            truth.write_text(json.dumps({"frame_number": 1, "detections": [{"class": "person", "bbox": box}]}) + "\n")
            predictions.write_text(json.dumps({"frame_number": 1, "detections": [{"class": "person", "bbox": box, "confidence": 0.9}, {"class": "person", "bbox": {"x1": 20, "y1": 20, "x2": 30, "y2": 30}, "confidence": 0.8}]}) + "\n")
            result = evaluate_detections(truth, predictions)
            self.assertEqual(result["classes"]["person"]["true_positives"], 1)
            self.assertEqual(result["classes"]["person"]["false_positives"], 1)
            self.assertEqual(result["classes"]["person"]["false_negatives"], 0)
            self.assertEqual(result["classes"]["person"]["recall"], 1.0)

    def test_empty_ground_truth_refuses_to_claim_metrics(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "truth.jsonl").write_text('{"frame_number": 1, "detections": []}\n')
            (root / "predictions.jsonl").write_text('{"frame_number": 1, "detections": []}\n')
            with self.assertRaisesRegex(ValueError, "no labeled objects"):
                evaluate_detections(root / "truth.jsonl", root / "predictions.jsonl")

    def test_predictions_for_unlabeled_classes_are_false_positives_and_confusions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            truth = root / "truth.jsonl"
            predictions = root / "predictions.jsonl"
            box = {"x1": 0, "y1": 0, "x2": 10, "y2": 10}
            truth.write_text(json.dumps({
                "frame_number": 1,
                "detections": [{"class": "person", "bbox": box}],
            }) + "\n")
            predictions.write_text("".join(json.dumps(record) + "\n" for record in [
                {"frame_number": 1, "detections": [{"class": "knife", "bbox": box, "confidence": 0.8}]},
                {"frame_number": 2, "detections": [{"class": "knife", "bbox": box, "confidence": 0.7}]},
            ]))

            result = evaluate_detections(truth, predictions)

        knife = result["classes"]["knife"]
        self.assertEqual(knife["ground_truth_count"], 0)
        self.assertEqual(knife["false_positives"], 2)
        self.assertIsNone(knife["recall"])
        self.assertIsNone(knife["average_precision"])
        matrix = result["confusion_matrix"]["actual_rows_predicted_columns"]
        self.assertEqual(matrix["person"]["knife"], 1)
        self.assertEqual(matrix["background"]["knife"], 1)
        self.assertEqual(matrix["person"]["background"], 0)
        self.assertEqual(result["average_precision_mean"], 0.0)

    def test_duplicate_frame_records_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            box = {"x1": 0, "y1": 0, "x2": 10, "y2": 10}
            records = {"frame_number": 1, "detections": [{"class": "person", "bbox": box}]}
            truth = root / "truth.jsonl"
            predictions = root / "predictions.jsonl"
            truth.write_text(json.dumps(records) + "\n")
            prediction_record = {
                **records,
                "detections": [{"class": "person", "bbox": box, "confidence": 0.9}],
            }
            predictions.write_text(json.dumps(prediction_record) + "\n" + json.dumps(prediction_record) + "\n")
            with self.assertRaisesRegex(ValueError, "Invalid prediction record"):
                evaluate_detections(truth, predictions)

    def test_unmatched_ground_truth_is_a_false_negative(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            box = {"x1": 0, "y1": 0, "x2": 10, "y2": 10}
            truth = root / "truth.jsonl"
            predictions = root / "predictions.jsonl"
            truth.write_text(json.dumps({
                "frame_number": 1,
                "detections": [{"class": "person", "bbox": box}],
            }) + "\n")
            predictions.write_text('{"frame_number": 1, "detections": []}\n')

            result = evaluate_detections(truth, predictions)

        self.assertEqual(result["classes"]["person"]["false_negatives"], 1)
        self.assertEqual(result["classes"]["person"]["recall"], 0.0)
        matrix = result["confusion_matrix"]["actual_rows_predicted_columns"]
        self.assertEqual(matrix["person"]["background"], 1)

    def test_reports_selected_iou_and_mean_ap_across_iou_thresholds(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            truth = root / "truth.jsonl"
            predictions = root / "predictions.jsonl"
            truth.write_text(json.dumps({
                "frame_number": 1,
                "detections": [{"class": "person", "bbox": {"x1": 0, "y1": 0, "x2": 9, "y2": 10}}],
            }) + "\n")
            predictions.write_text(json.dumps({
                "frame_number": 1,
                "detections": [{"class": "person", "bbox": {"x1": 0, "y1": 0, "x2": 7, "y2": 10}, "confidence": 0.9}],
            }) + "\n")

            result = evaluate_detections(truth, predictions)

        self.assertEqual(result["average_precision_by_iou"]["0.50"], 1.0)
        self.assertEqual(result["average_precision_by_iou"]["0.75"], 1.0)
        self.assertEqual(result["average_precision_by_iou"]["0.80"], 0.0)
        self.assertEqual(result["mean_average_precision_50_95"], 0.6)
        self.assertEqual(result["classes"]["person"]["average_precision_50_95"], 0.6)
