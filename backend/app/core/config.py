"""PREDIX application settings loaded from environment variables."""

from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    SERVICE_NAME: str = "PREDIX"
    SERVICE_VERSION: str = "0.3.0"
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    ALLOWED_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"

    # ── Video upload ─────────────────────────────────────────────────────────
    # 1 GB default — raise via env var for larger demos
    MAX_UPLOAD_SIZE_BYTES: int = Field(default=1_073_741_824, gt=0)
    LIVE_MAX_FRAME_BYTES: int = Field(default=1_500_000, gt=0)
    LIVE_MAX_FRAME_WIDTH: int = Field(default=1280, gt=0)
    LIVE_MAX_FRAME_HEIGHT: int = Field(default=720, gt=0)
    LIVE_MIN_FRAME_INTERVAL_MS: int = Field(default=250, ge=0)
    RTSP_ALLOWED_HOSTS: str = ""
    RTSP_OPEN_TIMEOUT_MS: int = Field(default=5000, ge=100, le=60000)
    RTSP_READ_TIMEOUT_MS: int = Field(default=2000, ge=100, le=60000)
    # Folder name only; absolute path is computed below (independent of CWD)
    UPLOAD_DIR_NAME: str = "uploads"
    ANALYSIS_DIR_NAME: str = "analysis_outputs"
    DATABASE_PATH: str = "data/predix.sqlite3"
    ALLOWED_VIDEO_EXTENSIONS: str = ".mp4,.webm,.mov"
    ALLOWED_VIDEO_MIME_TYPES: str = "video/mp4,video/webm,video/quicktime"

    # ── Computed helpers ─────────────────────────────────────────────────────

    @property
    def cors_origins(self) -> List[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",")]

    @property
    def allowed_extensions(self) -> List[str]:
        return [e.strip().lower() for e in self.ALLOWED_VIDEO_EXTENSIONS.split(",")]

    @property
    def allowed_mime_types(self) -> List[str]:
        return [m.strip().lower() for m in self.ALLOWED_VIDEO_MIME_TYPES.split(",")]

    @property
    def rtsp_allowed_hosts(self) -> List[str]:
        return [host.strip().lower().rstrip(".") for host in self.RTSP_ALLOWED_HOSTS.split(",") if host.strip()]

    @property
    def upload_dir(self) -> Path:
        """
        Absolute path to the uploads directory.
        Always resolves to  <repo>/backend/uploads/  regardless of the
        working directory from which Uvicorn is launched.
        """
        backend_root = Path(__file__).resolve().parent.parent.parent
        return backend_root / self.UPLOAD_DIR_NAME

    @property
    def analysis_dir(self) -> Path:
        """
        Absolute path to the analysis outputs directory.
        Always resolves to  <repo>/backend/analysis_outputs/  regardless of the
        working directory from which Uvicorn is launched.
        """
        backend_root = Path(__file__).resolve().parent.parent.parent
        return backend_root / self.ANALYSIS_DIR_NAME

    @property
    def database_path(self) -> Path:
        """Resolve a configurable SQLite path relative to the backend root."""
        path = Path(self.DATABASE_PATH).expanduser()
        if path.is_absolute():
            return path
        backend_root = Path(__file__).resolve().parent.parent.parent
        return backend_root / path

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
