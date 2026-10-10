"""Frame-aligned tracking evaluation using labeled temporary object IDs."""

import json
import argparse
from pathlib import Path
from typing import Any

from app.cv.benchmark import _iou


def _records(path: Path, *, require_ids: bool) -> dict[int, list[dict[str, Any]]]:
    frames: dict[int, list[dict[str, Any]]] = {}
    with path.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            try:
                record = json.loads(line)
                frame = int(record["frame_number"])
                if frame < 1 or frame in frames or not isinstance(record["detections"], list):
                    raise ValueError
                detections = []
                for detection in record["detections"]:
                    box = detection["bbox"]
                    bbox = [float(box[key]) for key in ("x1", "y1", "x2", "y2")]
                    track_id = detection.get("track_id")
                    if bbox[2] <= bbox[0] or bbox[3] <= bbox[1] or not detection.get("class"):
                        raise ValueError
                    if require_ids and (track_id is None or str(track_id) == ""):
                        raise ValueError
                    detections.append({"class": str(detection["class"]), "bbox": bbox, "track_id": str(track_id) if track_id is not None else None})
                frames[frame] = detections
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError(f"Invalid tracking record at line {line_number}.") from exc
    return frames


def evaluate_tracking(ground_truth_path: Path, predictions_path: Path, iou_threshold: float = 0.5) -> dict[str, Any]:
    """Report detection matches, ID switches, fragmentation, and MOTA.

    Labels must include persistent anonymous object IDs. Matching is greedy
    by descending IoU within each frame and class; users should treat this
    evaluator's stated association method as part of the metric definition.
    """
    if not 0 < iou_threshold <= 1:
        raise ValueError("IoU threshold must be in (0, 1].")
    truth = _records(ground_truth_path, require_ids=True)
    predictions = _records(predictions_path, require_ids=True)
    if set(truth) != set(predictions):
        raise ValueError("Ground-truth and prediction files must contain the same evaluated frame numbers.")

    total_gt = sum(len(items) for items in truth.values())
    total_predictions = sum(len(items) for items in predictions.values())
    matches_total = false_positives = false_negatives = id_switches = fragmentations = 0
    prior_prediction: dict[str, str] = {}
    last_matched_frame: dict[str, int] = {}
    last_visible_frame: dict[str, int] = {}

    for frame in sorted(truth):
        gt_items = truth[frame]
        pred_items = predictions[frame]
        candidates = []
        for gt_index, gt in enumerate(gt_items):
            for pred_index, prediction in enumerate(pred_items):
                if gt["class"] == prediction["class"]:
                    overlap = _iou(gt["bbox"], prediction["bbox"])
                    if overlap >= iou_threshold:
                        candidates.append((overlap, gt_index, pred_index))
        candidates.sort(reverse=True)
        used_gt: set[int] = set()
        used_pred: set[int] = set()
        for _, gt_index, pred_index in candidates:
            if gt_index in used_gt or pred_index in used_pred:
                continue
            used_gt.add(gt_index)
            used_pred.add(pred_index)
            matches_total += 1
            gt_id = gt_items[gt_index]["track_id"]
            pred_id = pred_items[pred_index]["track_id"]
            if gt_id in prior_prediction and prior_prediction[gt_id] != pred_id:
                id_switches += 1
            if last_visible_frame.get(gt_id) == frame - 1 and last_matched_frame.get(gt_id, frame) < frame - 1:
                fragmentations += 1
            prior_prediction[gt_id] = pred_id
            last_matched_frame[gt_id] = frame
        false_negatives += len(gt_items) - len(used_gt)
        false_positives += len(pred_items) - len(used_pred)
        for gt in gt_items:
            last_visible_frame[gt["track_id"]] = frame

    mota = 1 - (false_negatives + false_positives + id_switches) / total_gt if total_gt else None
    return {
        "metric": "anonymous_tracking_evaluation",
        "status": "available" if total_gt else "insufficient_data",
        "iou_threshold": iou_threshold,
        "frames": len(truth),
        "ground_truth_detections": total_gt,
        "predicted_detections": total_predictions,
        "matches": matches_total,
        "false_positives": false_positives,
        "false_negatives": false_negatives,
        "id_switches": id_switches,
        "fragmentations": fragmentations,
        "mota": round(mota, 4) if mota is not None else None,
        "limitations": "Frame-aligned labels with consistent anonymous IDs are required. Greedy IoU association is used for frame matching; this does not evaluate identity recognition or real-world trajectories.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate anonymous PREDIX tracks against frame-aligned labeled IDs.")
    parser.add_argument("ground_truth", type=Path)
    parser.add_argument("predictions", type=Path)
    parser.add_argument("--iou", type=float, default=0.5)
    args = parser.parse_args()
    print(json.dumps(evaluate_tracking(args.ground_truth, args.predictions, args.iou), indent=2))
