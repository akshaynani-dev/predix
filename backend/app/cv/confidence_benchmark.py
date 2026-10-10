"""Compare detector confidence thresholds against the same labeled video frames."""

import argparse
import json
import math
import tempfile
from pathlib import Path
from typing import Any, Callable

from app.cv.benchmark import evaluate_detections
from app.cv.config import cv_settings
from app.cv.predict_benchmark import predict_video


def evaluate_confidence_thresholds(
    video_path: Path,
    ground_truth_path: Path,
    thresholds: list[float],
    *,
    model_name: str | None = None,
    image_size: int = 640,
    frame_stride: int = 1,
    iou_threshold: float = 0.5,
    prediction_runner: Callable[..., dict[str, Any]] = predict_video,
    evaluator: Callable[..., dict[str, Any]] = evaluate_detections,
) -> dict[str, Any]:
    """Run independent threshold predictions and report every candidate's metrics.

    No threshold is selected automatically. Candidate comparisons require the
    same local video, ground-truth frames, model, image size, and sampling stride.
    """
    if not thresholds:
        raise ValueError("Provide at least one confidence threshold.")
    candidates = [float(value) for value in thresholds]
    if any(not math.isfinite(value) or not 0 <= value <= 1 for value in candidates):
        raise ValueError("Confidence thresholds must be finite values in [0, 1].")
    if len(set(candidates)) != len(candidates):
        raise ValueError("Confidence thresholds must not contain duplicates.")
    if image_size < 1 or frame_stride < 1:
        raise ValueError("Image size and frame stride must be positive.")
    if not 0 < iou_threshold <= 1:
        raise ValueError("IoU threshold must be in (0, 1].")

    selected_model = model_name or cv_settings.MODEL_NAME
    results = []
    with tempfile.TemporaryDirectory(prefix="predix-confidence-eval-") as temporary_directory:
        temporary_path = Path(temporary_directory)
        for threshold in sorted(candidates):
            prediction_path = temporary_path / f"threshold-{threshold:.6f}.jsonl"
            run = prediction_runner(
                video_path,
                prediction_path,
                model_name=selected_model,
                confidence_threshold=threshold,
                image_size=image_size,
                frame_stride=frame_stride,
            )
            metrics = evaluator(ground_truth_path, prediction_path, iou_threshold)
            results.append({
                "confidence_threshold": threshold,
                "prediction_run": {
                    "model": run.get("model", selected_model),
                    "device": run.get("device"),
                    "video_frames_read": run.get("video_frames_read"),
                    "inference_frames": run.get("inference_frames"),
                    "elapsed_seconds": run.get("elapsed_seconds"),
                },
                "evaluation": metrics,
            })

    return {
        "metric": "confidence_threshold_comparison",
        "video": str(video_path),
        "ground_truth": str(ground_truth_path),
        "model": selected_model,
        "image_size": image_size,
        "frame_stride": frame_stride,
        "iou_threshold": iou_threshold,
        "automatic_threshold_selection": False,
        "candidates": results,
        "interpretation": "Compare precision, recall, false positives, false negatives, and mAP against the chosen operating requirements. These labeled-scene results do not establish general accuracy or guarantee detection outcomes.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare explicit detector confidence thresholds against frame-aligned labels."
    )
    parser.add_argument("video", type=Path, help="Local evaluation video")
    parser.add_argument("ground_truth", type=Path, help="Frame-aligned ground-truth JSONL")
    parser.add_argument("--thresholds", type=float, nargs="+", required=True, help="Candidate thresholds in [0, 1]; no automatic selection")
    parser.add_argument("--model", default=None, help="Local Ultralytics checkpoint; defaults to backend configuration")
    parser.add_argument("--image-size", type=int, default=640)
    parser.add_argument("--frame-stride", type=int, default=1)
    parser.add_argument("--iou", type=float, default=0.5)
    args = parser.parse_args()
    result = evaluate_confidence_thresholds(
        args.video,
        args.ground_truth,
        args.thresholds,
        model_name=args.model,
        image_size=args.image_size,
        frame_stride=args.frame_stride,
        iou_threshold=args.iou,
    )
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
