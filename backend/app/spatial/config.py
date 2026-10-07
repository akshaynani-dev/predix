"""Per-video normalized polygon zone configuration."""

import json
import os
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.config import settings

_ZONE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class ZoneDefinition(BaseModel):
    zone_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=100)
    polygon: list[tuple[float, float]] = Field(min_length=3, max_length=100)

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
