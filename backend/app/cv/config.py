"""Computer Vision module configuration for PREDIX Phase 3."""

from pathlib import Path
from typing import List, Literal
from pydantic import Field
from pydantic_settings import BaseSettings


class CVSettings(BaseSettings):
    """
    Configuration for Phase 3 Computer Vision engine.
    Uses the official Ultralytics nano detection checkpoint.
    """
    # Single lightweight, currently supported Ultralytics nano detection checkpoint
    MODEL_NAME: str = "yolo11n.pt"

    # Conservative inference settings to reduce Apple M2 compute load
    DEFAULT_CONF_THRESHOLD: float = Field(default=0.25, ge=0, le=1)
    DEFAULT_IMAGE_SIZE: int = Field(default=640, gt=0)
    BATCH_SIZE: int = 1
    FRAME_STRIDE: int = Field(default=1, ge=1)
    TRACK_IOU_THRESHOLD: float = Field(default=0.3, gt=0, le=1)
    TRACK_MAX_MISSED_FRAMES: int = Field(default=2, ge=0, le=10)
    DEVICE: Literal["auto", "cpu", "mps", "cuda"] = "auto"

    # Key COCO classes prioritized for PREDIX campus/urban observation
    TARGET_CLASSES: List[str] = [
        "person",
        "car",
        "bus",
        "truck",
        "motorcycle",
        "bicycle",
    ]

    model_config = {
        "env_file": str(Path(__file__).resolve().parents[2] / ".env"),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


cv_settings = CVSettings()
