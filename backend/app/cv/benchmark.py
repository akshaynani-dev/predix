"""Ground-truth evaluation for detector JSONL outputs.

Each JSONL line represents one frame and contains ``frame_number`` and a
``detections`` array. Ground truth omits confidence; predictions include it.
"""

import json
import argparse
import math
from pathlib import Path
from typing import Any


def _load_records(path: Path, *, ground_truth: bool) -> dict[int, list[dict[str, Any]]]:
    frames: dict[int, list[dict[str, Any]]] = {}
    with path.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            try:
                record = json.loads(line)
                frame = int(record["frame_number"])
                detections = record["detections"]
                if frame < 1 or not isinstance(detections, list):
                    raise ValueError
                if frame in frames:
                    raise ValueError
                clean = []
                for detection in detections:
                    box = detection["bbox"]
                    xyxy = [float(box[key]) for key in ("x1", "y1", "x2", "y2")]
                    class_name = str(detection["class"]).strip()
                    confidence = 1.0 if ground_truth else float(detection["confidence"])
                    if (
                        not class_name
                        or not all(math.isfinite(value) for value in xyxy)
                        or xyxy[2] <= xyxy[0]
                        or xyxy[3] <= xyxy[1]
                        or not math.isfinite(confidence)
                        or not 0 <= confidence <= 1
                    ):
                        raise ValueError
                    clean.append({
                        "class": class_name,
                        "bbox": xyxy,
                        "confidence": confidence,
                    })
                frames[frame] = clean
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError(f"Invalid {'ground-truth' if ground_truth else 'prediction'} record at line {line_number}.") from exc
    return frames


def _iou(left: list[float], right: list[float]) -> float:
    x1, y1 = max(left[0], right[0]), max(left[1], right[1])
    x2, y2 = min(left[2], right[2]), min(left[3], right[3])
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    area_left = (left[2] - left[0]) * (left[3] - left[1])
    area_right = (right[2] - right[0]) * (right[3] - right[1])
    return intersection / max(area_left + area_right - intersection, 1e-12)


def _evaluate_loaded(
    truth: dict[int, list[dict[str, Any]]],
    predictions: dict[int, list[dict[str, Any]]],
    iou_threshold: float,
) -> dict[str, Any]:
    """Calculate metrics from already validated frame-aligned records."""
    if not 0 < iou_threshold <= 1:
        raise ValueError("IoU threshold must be in (0, 1].")
    truth_classes = {d["class"] for rows in truth.values() for d in rows}
    prediction_classes = {d["class"] for rows in predictions.values() for d in rows}
    if not truth_classes:
        raise ValueError("Ground truth contains no labeled objects; metrics are undefined.")
    classes = sorted(truth_classes | prediction_classes)

    by_class: dict[str, dict[str, Any]] = {}
    for class_name in classes:
        gt_by_frame = {frame: [d for d in rows if d["class"] == class_name] for frame, rows in truth.items()}
        gt_total = sum(map(len, gt_by_frame.values()))
        matched = {frame: set() for frame in gt_by_frame}
        candidates = sorted(
            ((d["confidence"], frame, d) for frame, rows in predictions.items() for d in rows if d["class"] == class_name),
            key=lambda item: item[0], reverse=True,
        )
        tp, fp = [], []
        for _, frame, prediction in candidates:
            targets = gt_by_frame.get(frame, [])
            options = [(idx, _iou(prediction["bbox"], target["bbox"])) for idx, target in enumerate(targets) if idx not in matched.get(frame, set())]
            best_idx, best_iou = max(options, key=lambda pair: pair[1], default=(-1, 0.0))
            is_match = best_idx >= 0 and best_iou >= iou_threshold
            tp.append(1 if is_match else 0)
            fp.append(0 if is_match else 1)
            if is_match:
                matched.setdefault(frame, set()).add(best_idx)
        cum_tp, cum_fp, recalls, precisions = 0, 0, [], []
        for t, f in zip(tp, fp):
            cum_tp += t
            cum_fp += f
            recalls.append(cum_tp / gt_total if gt_total else 0.0)
            precisions.append(cum_tp / max(cum_tp + cum_fp, 1))
        ap = (
            sum(max((p for r, p in zip(recalls, precisions) if r >= level), default=0.0) for level in [i / 100 for i in range(101)]) / 101
            if gt_total else None
        )
        by_class[class_name] = {
            "ground_truth_count": gt_total,
            "prediction_count": len(candidates),
            "true_positives": cum_tp,
            "false_positives": cum_fp,
            "false_negatives": gt_total - cum_tp,
            "precision": cum_tp / max(cum_tp + cum_fp, 1),
            "recall": cum_tp / gt_total if gt_total else None,
            "average_precision": ap,
        }
    labels = sorted(truth_classes | prediction_classes) + ["background"]
    confusion = {actual: {predicted: 0 for predicted in labels} for actual in labels}
    for frame in sorted(set(truth) | set(predictions)):
        actual_items = truth.get(frame, [])
        predicted_items = predictions.get(frame, [])
        pairs = sorted(
            (
                (_iou(actual["bbox"], predicted["bbox"]), actual_index, predicted_index)
                for actual_index, actual in enumerate(actual_items)
                for predicted_index, predicted in enumerate(predicted_items)
                if _iou(actual["bbox"], predicted["bbox"]) >= iou_threshold
            ),
            reverse=True,
        )
        matched_actual: set[int] = set()
        matched_predicted: set[int] = set()
        for _, actual_index, predicted_index in pairs:
            if actual_index in matched_actual or predicted_index in matched_predicted:
                continue
            matched_actual.add(actual_index)
            matched_predicted.add(predicted_index)
            confusion[actual_items[actual_index]["class"]][predicted_items[predicted_index]["class"]] += 1
        for actual_index, actual in enumerate(actual_items):
            if actual_index not in matched_actual:
                confusion[actual["class"]]["background"] += 1
        for predicted_index, predicted in enumerate(predicted_items):
            if predicted_index not in matched_predicted:
                confusion["background"][predicted["class"]] += 1
    labeled_aps = [by_class[class_name]["average_precision"] for class_name in sorted(truth_classes)]
    mean_ap = sum(labeled_aps) / len(labeled_aps)
    return {
        "metric": "object_detection_evaluation",
        "iou_threshold": iou_threshold,
        "average_precision_mean": mean_ap,
        "mean_average_precision_at_iou": mean_ap,
        "classes": by_class,
        "confusion_matrix": {"labels": labels, "actual_rows_predicted_columns": confusion},
        "ground_truth_frames": len(truth),
        "prediction_frames": len(predictions),
    }


def evaluate_detections(ground_truth_path: Path, predictions_path: Path, iou_threshold: float = 0.5) -> dict[str, Any]:
    """Return selected-IoU metrics and mAP across IoU 0.50:0.95."""
    if not 0 < iou_threshold <= 1:
        raise ValueError("IoU threshold must be in (0, 1].")
    truth = _load_records(ground_truth_path, ground_truth=True)
    predictions = _load_records(predictions_path, ground_truth=False)
    if not any(detection for rows in truth.values() for detection in rows):
        raise ValueError("Ground truth contains no labeled objects; metrics are undefined.")

    result = _evaluate_loaded(truth, predictions, iou_threshold)
    thresholds = [round(value / 100, 2) for value in range(50, 100, 5)]
    threshold_results = {
        f"{threshold:.2f}": _evaluate_loaded(truth, predictions, threshold)
        for threshold in thresholds
    }
    result["average_precision_by_iou"] = {
        threshold: metrics["average_precision_mean"]
        for threshold, metrics in threshold_results.items()
    }
    result["mean_average_precision_50_95"] = round(
        sum(result["average_precision_by_iou"].values()) / len(thresholds), 6
    )
    for class_name, metrics in result["classes"].items():
        class_aps = [
            threshold_results[threshold]["classes"][class_name]["average_precision"]
            for threshold in threshold_results
            if threshold_results[threshold]["classes"][class_name]["average_precision"] is not None
        ]
        metrics["average_precision_50_95"] = round(sum(class_aps) / len(class_aps), 6) if class_aps else None
    result["map_definition"] = "Mean AP over IoU thresholds 0.50 to 0.95 inclusive in 0.05 increments; only classes with labeled ground-truth objects are averaged."
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate PREDIX detection JSONL against frame-level labels.")
    parser.add_argument("ground_truth", type=Path, help="Frame JSONL with class and bbox for each labeled object")
    parser.add_argument("predictions", type=Path, help="PREDIX detection JSONL output")
    parser.add_argument("--iou", type=float, default=0.5, help="IoU match threshold (default: 0.5)")
    args = parser.parse_args()
    print(json.dumps(evaluate_detections(args.ground_truth, args.predictions, args.iou), indent=2))
