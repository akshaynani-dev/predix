"""Reusable ObjectDetector abstraction for PREDIX Phase 3.

Decoupled from FastAPI, web endpoints, and external queues.
Performs frame-by-frame pretrained YOLO object detection.
No tracking, density, or risk scoring is performed.
"""

import logging
import json
import math
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import cv2
import numpy as np

from app.cv.config import cv_settings

logger = logging.getLogger(__name__)


@dataclass
class Detection:
    """Represents an individual detected object bounding box in a single frame."""
    class_name: str
    confidence: float
    bbox: List[int]  # [x1, y1, x2, y2] in integer pixel coordinates


@dataclass
class AnalysisResult:
    """Overall aggregated detection result for a processed video."""
    video_id: str
    model: str
    device: str
    device_name: str
    confidence_threshold: float
    frames_processed: int
    total_frames: int
    total_detection_instances: int
    average_instances_per_frame: float
    detection_instances_by_class: Dict[str, int]
    processing_time_seconds: float
    processing_fps: float
    output_filename: str
    detection_results_filename: str
    inference_frames: int
    frame_stride: int
    image_size: int


class ObjectDetector:
    """
    Object detection engine using official Ultralytics YOLO models.
    Operates on single frames or streams video files frame-by-frame.
    """

    def __init__(
        self,
        model_name: Optional[str] = None,
        conf_threshold: Optional[float] = None,
        image_size: Optional[int] = None,
        frame_stride: Optional[int] = None,
    ):
        # Configuration-driven: explicit None check preserves 0.0
        self.model_name = model_name if model_name is not None else cv_settings.MODEL_NAME
        self.conf_threshold = conf_threshold if conf_threshold is not None else cv_settings.DEFAULT_CONF_THRESHOLD
        self.image_size = image_size if image_size is not None else cv_settings.DEFAULT_IMAGE_SIZE
        self.frame_stride = frame_stride if frame_stride is not None else cv_settings.FRAME_STRIDE
        if self.frame_stride < 1:
            raise ValueError("Frame stride must be at least 1.")

        self._model = None
        self._device, self._device_name = self._detect_device()

    @property
    def device(self) -> str:
        return self._device

    @property
    def device_name(self) -> str:
        return self._device_name

    def _detect_device(self) -> Tuple[str, str]:
        """
        Detect Apple Silicon MPS acceleration or fallback to CPU.
        Returns a tuple of (device_identifier, human_readable_device_name).
        """
        requested = cv_settings.DEVICE
        try:
            import torch

            if requested == "cpu":
                return "cpu", "CPU"
            if requested == "mps":
                if not torch.backends.mps.is_available() or not torch.backends.mps.is_built():
                    raise RuntimeError("MPS was requested but is not available.")
                logger.info("Apple Silicon MPS acceleration is available and selected.")
                return "mps", "Apple MPS"
            if requested == "cuda":
                if not torch.cuda.is_available():
                    raise RuntimeError("CUDA was requested but is not available.")
                return "cuda", "CUDA"
            if requested == "auto" and torch.backends.mps.is_available() and torch.backends.mps.is_built():
                logger.info("Apple Silicon MPS acceleration is available and selected.")
                return "mps", "Apple MPS"
        except RuntimeError:
            raise
        except Exception as exc:
            logger.warning("Could not initialize MPS device detection: %s", exc)

        logger.info("Using CPU for inference.")
        return "cpu", "CPU"

    def load_model(self) -> Any:
        """
        Lazily load the YOLO model onto the detected hardware device.
        Cached on self._model.
        """
        if self._model is None:
            logger.info("Loading YOLO model '%s' onto device '%s'...", self.model_name, self._device)
            from ultralytics import YOLO
            self._model = YOLO(self.model_name)
        return self._model

    def detect_frame(self, frame: np.ndarray) -> Tuple[List[Detection], np.ndarray]:
        """
        Run inference on a single BGR image/frame.
        Returns (list of Detection objects, annotated BGR frame).
        """
        model = self.load_model()
        # Conservative single-frame prediction: batch=1, no tracking
        results = model.predict(
            source=frame,
            device=self._device,
            conf=self.conf_threshold,
            imgsz=self.image_size,
            verbose=False,
        )

        detections: List[Detection] = []
        result = results[0]

        if result.boxes is not None and len(result.boxes) > 0:
            for box in result.boxes:
                cls_id = int(box.cls[0].item())
                class_name = result.names.get(cls_id, str(cls_id))
                confidence = round(float(box.conf[0].item()), 4)
                xyxy = [int(v) for v in box.xyxy[0].tolist()]
                detections.append(Detection(
                    class_name=class_name,
                    confidence=confidence,
                    bbox=xyxy,
                ))

        annotated_frame = result.plot()
        return detections, annotated_frame

    def process_video(
        self,
        video_id: str,
        input_path: Path,
        output_path: Path,
        detection_output_path: Path,
        progress_callback: Optional[Callable[[int, int, int, float], None]] = None,
    ) -> AnalysisResult:
        """
        Stream frames incrementally from input_path, perform object detection,
        write annotated frames to output_path, and compute frame-level statistics.

        Never loads the full video into RAM.
        """
        if not input_path.exists():
            raise FileNotFoundError(f"Source video not found: {input_path}")

        # Stage both outputs so interrupted/failed jobs never leave partial results.
        output_path.parent.mkdir(parents=True, exist_ok=True)
        detection_output_path.parent.mkdir(parents=True, exist_ok=True)
        staged_video = output_path.with_name(f".{output_path.stem}.partial{output_path.suffix}")
        staged_detections = detection_output_path.with_name(
            f".{detection_output_path.stem}.partial{detection_output_path.suffix}"
        )

        cap = cv2.VideoCapture(str(input_path))
        if not cap.isOpened():
            cap.release()
            raise RuntimeError(f"Could not open video file: {input_path}")

        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        if not math.isfinite(fps) or fps <= 0:
            fps = 30.0
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        if total_frames <= 0:
            total_frames = 1  # Guard against division by zero
        if width <= 0 or height <= 0:
            cap.release()
            raise RuntimeError("The video has invalid frame dimensions.")

        # Initialize web-compatible video writer (try avc1, fallback to mp4v)
        fourcc = cv2.VideoWriter_fourcc(*"avc1")
        writer = cv2.VideoWriter(str(staged_video), fourcc, fps, (width, height))
        if not writer.isOpened():
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            writer = cv2.VideoWriter(str(staged_video), fourcc, fps, (width, height))

        if not writer.isOpened():
            cap.release()
            staged_video.unlink(missing_ok=True)
            raise RuntimeError("Could not initialize the annotated video writer.")

        frames_processed = 0
        total_detection_instances = 0
        detection_instances_by_class: Dict[str, int] = {}
        inference_frames = 0
        start_time = time.perf_counter()

        try:
            with staged_detections.open("w", encoding="utf-8") as detections_file:
                while True:
                    ret, frame = cap.read()
                    if not ret:
                        break

                    frames_processed += 1
                    frame_number = frames_processed

                    if (frame_number - 1) % self.frame_stride == 0:
                        detections, annotated_frame = self.detect_frame(frame)
                        inference_frames += 1
                        detections_file.write(json.dumps({
                            "timestamp_seconds": round((frame_number - 1) / fps, 3),
                            "frame_number": frame_number,
                            "frame_width": width,
                            "frame_height": height,
                            "detections": [
                                {
                                    "class": det.class_name,
                                    "confidence": det.confidence,
                                    "bbox": {
                                        "x1": det.bbox[0], "y1": det.bbox[1],
                                        "x2": det.bbox[2], "y2": det.bbox[3],
                                    },
                                }
                                for det in detections
                            ],
                        }, separators=(",", ":")) + "\n")

                        total_detection_instances += len(detections)
                        for det in detections:
                            cname = det.class_name
                            detection_instances_by_class[cname] = (
                                detection_instances_by_class.get(cname, 0) + 1
                            )
                    else:
                        annotated_frame = frame

                    writer.write(annotated_frame)
                    if progress_callback:
                        elapsed = time.perf_counter() - start_time
                        progress_callback(
                            frames_processed, total_frames, total_detection_instances, elapsed
                        )

            if frames_processed == 0:
                raise RuntimeError("The video contains no readable frames.")
            cap.release()
            writer.release()
            os.replace(staged_video, output_path)
            os.replace(staged_detections, detection_output_path)
        except Exception:
            cap.release()
            writer.release()
            staged_video.unlink(missing_ok=True)
            staged_detections.unlink(missing_ok=True)
            output_path.unlink(missing_ok=True)
            detection_output_path.unlink(missing_ok=True)
            raise

        total_elapsed = round(time.perf_counter() - start_time, 2)
        processing_fps = round(frames_processed / max(total_elapsed, 0.001), 2)
        avg_per_frame = round(total_detection_instances / max(frames_processed, 1), 2)

        return AnalysisResult(
            video_id=video_id,
            model=self.model_name,
            device=self._device,
            device_name=self._device_name,
            confidence_threshold=self.conf_threshold,
            frames_processed=frames_processed,
            total_frames=total_frames,
            total_detection_instances=total_detection_instances,
            average_instances_per_frame=avg_per_frame,
            detection_instances_by_class=detection_instances_by_class,
            processing_time_seconds=total_elapsed,
            processing_fps=processing_fps,
            output_filename=output_path.name,
            detection_results_filename=detection_output_path.name,
            inference_frames=inference_frames,
            frame_stride=self.frame_stride,
            image_size=self.image_size,
        )
