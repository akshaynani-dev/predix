"""Per-video normalized polygon zone configuration."""

import json
import os
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.config import settings

_ZONE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class OccupancyStatusThresholds(BaseModel):
    low: float = Field(default=0.5, gt=0, le=1)
    moderate: float = Field(default=0.75, gt=0, le=1)
    high: float = Field(default=0.9, gt=0, le=1)
    critical: float = Field(default=1.0, gt=0, le=1)

    @model_validator(mode="after")
    def validate_order(self) -> "OccupancyStatusThresholds":
        if not self.low <= self.moderate <= self.high <= self.critical:
            raise ValueError("Occupancy status thresholds must be ordered low to critical.")
        return self


class ZoneDefinition(BaseModel):
    zone_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=100)
    polygon: list[tuple[float, float]] = Field(min_length=3, max_length=100)
    occupancy_capacity: int | None = Field(default=None, gt=0, le=100000)
    status_thresholds: OccupancyStatusThresholds = Field(default_factory=OccupancyStatusThresholds)
    anomaly_mad_multiplier: float = Field(default=3.0, gt=0, le=10)
    anomaly_minimum_increase: float = Field(default=1.0, ge=0, le=100000)

    @field_validator("zone_id")
    @classmethod
    def validate_zone_id(cls, value: str) -> str:
        if not _ZONE_ID_PATTERN.fullmatch(value):
            raise ValueError("Zone IDs may contain only letters, numbers, underscores, and hyphens.")
        return value

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Zone name cannot be empty.")
        return value

    @field_validator("polygon")
    @classmethod
    def validate_normalized_points(
        cls, value: list[tuple[float, float]]
    ) -> list[tuple[float, float]]:
        if any(not 0 <= x <= 1 or not 0 <= y <= 1 for x, y in value):
            raise ValueError("Zone points must use normalized coordinates between 0 and 1.")
        if len(set(value)) < 3:
            raise ValueError("A zone polygon must contain at least three distinct points.")
        return value


class ZoneConfiguration(BaseModel):
    zones: list[ZoneDefinition] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_unique_ids(self) -> "ZoneConfiguration":
        ids = [zone.zone_id for zone in self.zones]
        if len(ids) != len(set(ids)):
            raise ValueError("Zone IDs must be unique within a video.")
        return self


def classify_capacity(estimate: float | None, capacity: int | None, thresholds: dict[str, float] | None) -> tuple[str, float | None]:
    """Classify an estimate only against an operator-configured capacity."""
    if estimate is None:
        return "UNAVAILABLE", None
    if capacity is None or capacity <= 0:
        return "UNCONFIGURED", None
    limits = thresholds or {"low": 0.5, "moderate": 0.75, "high": 0.9, "critical": 1.0}
    ratio = estimate / capacity
    if ratio >= limits["critical"]:
        return "CRITICAL", ratio
    if ratio >= limits["high"]:
        return "HIGH", ratio
    if ratio >= limits["moderate"]:
        return "MODERATE", ratio
    if ratio >= limits["low"]:
        return "LOW", ratio
    return "NORMAL", ratio


def zone_config_path(video_id: str) -> Path:
    return settings.analysis_dir / f"{video_id}_zones.json"


def load_zones(video_id: str) -> list[dict[str, Any]]:
    path = zone_config_path(video_id)
    if not path.is_file():
        return []
    config = ZoneConfiguration.model_validate_json(path.read_text(encoding="utf-8"))
    return [zone.model_dump(mode="json") for zone in config.zones]


def save_zones(video_id: str, configuration: ZoneConfiguration) -> None:
    path = zone_config_path(video_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.partial")
    try:
        temporary.write_text(configuration.model_dump_json(), encoding="utf-8")
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
