"""Run one detector configuration on local video and write evaluation JSONL."""

import argparse
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

import cv2

from app.cv.detector import ObjectDetector
from app.cv.config import cv_settings


def predict_video(
    video_path: Path,
    output_path: Path,
    *,
    model_name: str | None = None,
    confidence_threshold: float = 0.25,
    image_size: int = 640,
    frame_stride: int = 1,
    overwrite: bool = False,
    detector_factory: Callable[..., Any] = ObjectDetector,
    capture_factory: Callable[..., Any] = cv2.VideoCapture,
) -> dict[str, Any]:
    """Stream a local video through one detector and atomically save predictions.

    The output schema is accepted by ``app.cv.benchmark``. This command does
    not calculate accuracy; ground-truth labels are required for that step.
    """
    if not 0 <= confidence_threshold <= 1:
        raise ValueError("Confidence threshold must be between 0 and 1.")
    if image_size < 1 or frame_stride < 1:
        raise ValueError("Image size and frame stride must be positive.")
    if not video_path.is_file():
        raise FileNotFoundError("Prediction video was not found.")
    if video_path.resolve() == output_path.resolve():
        raise ValueError("Prediction output must not overwrite the source video.")
    if output_path.exists() and not overwrite:
        raise FileExistsError("Prediction output already exists; pass overwrite=True to replace it.")
    selected_model = model_name or cv_settings.MODEL_NAME
    if not Path(selected_model).is_file():
        raise FileNotFoundError("Candidate model checkpoint must be present locally; automatic model downloads are not used by this tool.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    capture = capture_factory(str(video_path))
    if not capture.isOpened():
        capture.release()
        raise ValueError("Could not open the prediction video.")

    temporary_path: Path | None = None
    frame_number = 0
    inference_frames = 0
    start_time = time.perf_counter()
    try:
        detector = detector_factory(
            model_name=selected_model,
            conf_threshold=confidence_threshold,
            image_size=image_size,
            frame_stride=frame_stride,
        )
        detector.load_model()
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            suffix=".partial",
            delete=False,
        ) as output:
            temporary_path = Path(output.name)
            while True:
                success, frame = capture.read()
                if not success:
                    break
                frame_number += 1
                if (frame_number - 1) % frame_stride:
                    continue
                detections, _ = detector.detect_frame(frame)
                inference_frames += 1
                record = {
                    "frame_number": frame_number,
                    "detections": [{
                        "class": detection.class_name,
                        "confidence": detection.confidence,
                        "bbox": {
                            "x1": detection.bbox[0],
                            "y1": detection.bbox[1],
                            "x2": detection.bbox[2],
                            "y2": detection.bbox[3],
                        },
                    } for detection in detections],
                }
                output.write(json.dumps(record, separators=(",", ":"), allow_nan=False) + "\n")
            output.flush()
            os.fsync(output.fileno())

        if inference_frames == 0:
            raise ValueError("The prediction video contained no readable frames.")
        os.replace(temporary_path, output_path)
        temporary_path = None
        return {
            "metric": "detector_predictions_generated",
            "model": detector.model_name,
            "device": detector.device,
            "device_name": detector.device_name,
            "confidence_threshold": confidence_threshold,
            "image_size": image_size,
            "frame_stride": frame_stride,
            "video_frames_read": frame_number,
            "inference_frames": inference_frames,
            "output_path": str(output_path),
            "elapsed_seconds": round(time.perf_counter() - start_time, 3),
            "quality_metrics": "not_measured; run app.cv.benchmark with representative frame-aligned labels",
        }
    except Exception:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise
    finally:
        capture.release()


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate PREDIX detector predictions for labeled evaluation.")
    parser.add_argument("video", type=Path, help="Local MP4, WebM, or MOV evaluation video")
    parser.add_argument("output", type=Path, help="Output prediction JSONL path")
    parser.add_argument("--model", default=None, help="Ultralytics model path/name; defaults to backend configuration")
    parser.add_argument("--confidence", type=float, default=0.25)
    parser.add_argument("--image-size", type=int, default=640)
    parser.add_argument("--frame-stride", type=int, default=1)
    parser.add_argument("--overwrite", action="store_true", help="Replace an existing output file after successful processing")
    args = parser.parse_args()
    print(json.dumps(predict_video(
        args.video,
        args.output,
        model_name=args.model,
        confidence_threshold=args.confidence,
        image_size=args.image_size,
        frame_stride=args.frame_stride,
        overwrite=args.overwrite,
    ), indent=2))


if __name__ == "__main__":
    main()
