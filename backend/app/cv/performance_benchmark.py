"""Measure inference speed and process memory on a supplied video.

This benchmark measures runtime only. It does not evaluate detection quality;
use ``app.cv.benchmark`` with labeled data for precision, recall, and AP.
"""

import argparse
import json
import math
import resource
import sys
import time
from pathlib import Path
from typing import Any, Callable

import cv2

from app.cv.detector import ObjectDetector


def _peak_rss_megabytes() -> float:
    """Return process maximum resident set size in MiB (OS units differ)."""
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    divisor = 1024 * 1024 if sys.platform == "darwin" else 1024
    return round(value / divisor, 2)


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(0, math.ceil(percentile * len(ordered)) - 1)
    return round(ordered[rank], 3)


def benchmark_video(
    video_path: Path,
    *,
    model_name: str | None = None,
    image_size: int = 640,
    frame_stride: int = 1,
    confidence_threshold: float = 0.25,
    warmup_frames: int = 2,
    detector_factory: Callable[..., Any] = ObjectDetector,
    capture_factory: Callable[..., Any] = cv2.VideoCapture,
) -> dict[str, Any]:
    """Benchmark one detector configuration on the supplied video stream."""
    if frame_stride < 1 or image_size < 1 or warmup_frames < 0:
        raise ValueError("Frame stride and image size must be positive; warmup frames cannot be negative.")
    if not 0 <= confidence_threshold <= 1:
        raise ValueError("Confidence threshold must be between 0 and 1.")
    if not video_path.is_file():
        raise FileNotFoundError("Benchmark video was not found.")

    detector = detector_factory(
        model_name=model_name,
        conf_threshold=confidence_threshold,
        image_size=image_size,
        frame_stride=frame_stride,
    )
    load_started = time.perf_counter()
    detector.load_model()
    model_load_seconds = time.perf_counter() - load_started

    capture = capture_factory(str(video_path))
    if not capture.isOpened():
        capture.release()
        raise ValueError("Could not open the benchmark video.")

    timings_ms: list[float] = []
    frame_number = 0
    inference_frame_count = 0
    warmup_inference_count = 0
    run_started = time.perf_counter()
    cpu_started = time.process_time()
    try:
        while True:
            success, frame = capture.read()
            if not success:
                break
            frame_number += 1
            if (frame_number - 1) % frame_stride:
                continue
            inference_frame_count += 1
            if warmup_inference_count < warmup_frames:
                detector.detect_frame(frame)
                warmup_inference_count += 1
                continue
            inference_started = time.perf_counter()
            detector.detect_frame(frame)
            timings_ms.append((time.perf_counter() - inference_started) * 1000)
    finally:
        capture.release()

    elapsed_seconds = time.perf_counter() - run_started
    cpu_seconds = time.process_time() - cpu_started
    if not timings_ms:
        raise ValueError("The video contained no measured inference frames after warmup and frame sampling.")

    measured_seconds = sum(timings_ms) / 1000
    return {
        "metric": "inference_performance_benchmark",
        "model": detector.model_name,
        "device": detector.device,
        "device_name": detector.device_name,
        "image_size": image_size,
        "frame_stride": frame_stride,
        "confidence_threshold": confidence_threshold,
        "video_frames_read": frame_number,
        "inference_frames_including_warmup": inference_frame_count,
        "warmup_inference_frames_excluded": warmup_inference_count,
        "measured_inference_frames": len(timings_ms),
        "model_load_seconds": round(model_load_seconds, 3),
        "mean_inference_latency_ms": round(sum(timings_ms) / len(timings_ms), 3),
        "p50_inference_latency_ms": _percentile(timings_ms, 0.5),
        "p95_inference_latency_ms": _percentile(timings_ms, 0.95),
        "measured_inference_fps": round(len(timings_ms) / measured_seconds, 3) if measured_seconds else None,
        "run_wall_seconds": round(elapsed_seconds, 3),
        "run_cpu_seconds": round(cpu_seconds, 3),
        "process_peak_rss_mb": _peak_rss_megabytes(),
        "quality_metrics": "not_measured; requires frame-aligned labeled ground truth",
        "limitations": "Peak RSS is for the whole benchmark process, not model-only memory. Results depend on video, device state, thermal state, codec, and software versions.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure PREDIX detector inference speed and process memory on a video.")
    parser.add_argument("video", type=Path, help="Local MP4, WebM, or MOV evaluation video")
    parser.add_argument("--model", default=None, help="Ultralytics model path/name; defaults to backend configuration")
    parser.add_argument("--image-size", type=int, default=640)
    parser.add_argument("--frame-stride", type=int, default=1)
    parser.add_argument("--confidence", type=float, default=0.25)
    parser.add_argument("--warmup-frames", type=int, default=2)
    args = parser.parse_args()
    print(json.dumps(benchmark_video(
        args.video,
        model_name=args.model,
        image_size=args.image_size,
        frame_stride=args.frame_stride,
        confidence_threshold=args.confidence,
        warmup_frames=args.warmup_frames,
    ), indent=2))


if __name__ == "__main__":
    main()
