"""Reusable ObjectDetector abstraction for PREDIX Phase 3.

Decoupled from FastAPI, web endpoints, and external queues.
Performs frame-by-frame pretrained YOLO object detection and writes anonymous
short-lived track observations during uploaded-video processing. No density
model or risk scoring is performed.
"""

import logging
import json
import math
import os
import time
import gc
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import cv2
import numpy as np

from app.cv.config import cv_settings
from app.cv.frame_processing import process_frame
from app.video_processing.sources import UploadedVideoSource
from app.cv.tracker_factory import create_anonymous_tracker

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
    occupancy_peak_estimate: int
    occupancy_mean_estimate: float


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
        self._model_load_error: str | None = None
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
            try:
                from ultralytics import YOLO
                self._model = YOLO(self.model_name)
                self._model_load_error = None
            except Exception as exc:
                self._model_load_error = type(exc).__name__
                logger.exception("Could not load configured YOLO model '%s'.", self.model_name)
                raise
        return self._model

    def unload_model(self) -> bool:
        """Release cached model references and clear the selected accelerator cache."""
        if self._model is None:
            return False
        self._model = None
        gc.collect()
        try:
            import torch

            if self._device == "mps" and hasattr(torch, "mps"):
                torch.mps.empty_cache()
            elif self._device == "cuda" and torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            logger.debug("Could not clear the %s accelerator cache after model unload.", self._device, exc_info=True)
        return True

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

        source = UploadedVideoSource(input_path)
        try:
            source.open()
        except Exception:
            staged_video.unlink(missing_ok=True)
            staged_detections.unlink(missing_ok=True)
            raise

        writer = None
        try:
            total_frames = int(source.get(cv2.CAP_PROP_FRAME_COUNT))
            fps = source.get(cv2.CAP_PROP_FPS)
            if not math.isfinite(fps) or fps <= 0:
                fps = 30.0
            width = int(source.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(source.get(cv2.CAP_PROP_FRAME_HEIGHT))

            if total_frames <= 0:
                total_frames = 1  # Guard against division by zero
            if width <= 0 or height <= 0:
                raise RuntimeError("The video has invalid frame dimensions.")

            # Initialize web-compatible video writer (try avc1, fallback to mp4v)
            fourcc = cv2.VideoWriter_fourcc(*"avc1")
            writer = cv2.VideoWriter(str(staged_video), fourcc, fps, (width, height))
            if not writer.isOpened():
                writer.release()
                fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                writer = cv2.VideoWriter(str(staged_video), fourcc, fps, (width, height))

            if not writer.isOpened():
                raise RuntimeError("Could not initialize the annotated video writer.")
        except Exception:
            source.release()
            if writer is not None:
                writer.release()
            staged_video.unlink(missing_ok=True)
            staged_detections.unlink(missing_ok=True)
            raise

        frames_processed = 0
        total_detection_instances = 0
        detection_instances_by_class: Dict[str, int] = {}
        inference_frames = 0
        tracker = create_anonymous_tracker()
        occupancy_total = 0
        occupancy_peak = 0
        start_time = time.perf_counter()

        try:
            with staged_detections.open("w", encoding="utf-8") as detections_file:
                while True:
                    ret, frame = source.read()
                    if not ret:
                        break

                    frames_processed += 1
                    frame_number = frames_processed

                    if (frame_number - 1) % self.frame_stride == 0:
                        detections, tracked_detections, annotated_frame = process_frame(
                            self,
                            tracker,
                            frame,
                            timestamp_seconds=(frame_number - 1) / fps,
                        )
                        inference_frames += 1
                        active_tracks = tracker.active_tracks
                        visible_people = sum(track["class"] == "person" for track in active_tracks.values())
                        observed_people = sum(item["class"] == "person" for item in tracked_detections)
                        carried_people = max(0, visible_people - observed_people)
                        occupancy_total += visible_people
                        occupancy_peak = max(occupancy_peak, visible_people)
                        detections_file.write(json.dumps({
                            "timestamp_seconds": round((frame_number - 1) / fps, 3),
                            "frame_number": frame_number,
                            "frame_width": width,
                            "frame_height": height,
                            "tracking_available": True,
                            "detections": [
                                {
                                    "class": det.class_name,
                                    "confidence": det.confidence,
                                    "track_id": tracked_detections[index]["track_id"],
                                    "direction": tracked_detections[index]["direction"],
                                    "dwell_seconds": tracked_detections[index]["dwell_seconds"],
                                    "bbox": {
                                        "x1": det.bbox[0], "y1": det.bbox[1],
                                        "x2": det.bbox[2], "y2": det.bbox[3],
                                    },
                                }
                                for index, det in enumerate(detections)
                            ],
                            "occupancy": {
                                "data_kind": "estimated_active_person_tracks",
                                "count": visible_people,
                                "raw_person_detection_instances": sum(
                                    detection.class_name == "person" for detection in detections
                                ),
                                "observed_track_count": observed_people,
                                "temporally_carried_track_count": carried_people,
                                "retention_limit_missed_frames": tracker.max_missed_frames,
                            },
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
            source.release()
            writer.release()
            os.replace(staged_video, output_path)
            os.replace(staged_detections, detection_output_path)
        except Exception:
            source.release()
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
            occupancy_peak_estimate=occupancy_peak,
            occupancy_mean_estimate=round(occupancy_total / max(inference_frames, 1), 2),
        )
