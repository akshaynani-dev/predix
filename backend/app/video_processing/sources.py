"""Video frame-source boundary shared by uploaded and future live sources."""

from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

import cv2


class VideoSourceError(RuntimeError):
    """Raised when a configured video source cannot be opened or read."""


class VideoSource(Protocol):
    """Minimal frame-source contract consumed by the detector pipeline."""

    source_kind: str

    def open(self) -> None: ...
    def is_opened(self) -> bool: ...
    def read(self) -> tuple[bool, Any]: ...
    def get(self, property_id: int) -> float: ...
    def release(self) -> None: ...


class OpenCVVideoSource:
    """OpenCV-backed frame source for a file path, camera index, or stream URI."""

    def __init__(
        self,
        source: str | Path | int,
        *,
        source_kind: str,
        backend: int | None = None,
        open_timeout_ms: int | None = None,
        read_timeout_ms: int | None = None,
    ):
        self.source = source
        self.source_kind = source_kind
        self.backend = backend
        self.open_timeout_ms = open_timeout_ms
        self.read_timeout_ms = read_timeout_ms
        self._capture: cv2.VideoCapture | None = None

    def open(self) -> None:
        if self._capture is not None and self._capture.isOpened():
            return
        capture_source = str(self.source) if isinstance(self.source, Path) else self.source
        if self.backend is not None:
            params = []
            if self.open_timeout_ms is not None:
                params.extend([cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, self.open_timeout_ms])
            if self.read_timeout_ms is not None:
                params.extend([cv2.CAP_PROP_READ_TIMEOUT_MSEC, self.read_timeout_ms])
            self._capture = cv2.VideoCapture(capture_source, self.backend, params)
        else:
            self._capture = cv2.VideoCapture(capture_source)
        if not self._capture.isOpened():
            self._capture.release()
            self._capture = None
            raise VideoSourceError("Could not open the configured video source.")

    def is_opened(self) -> bool:
        return self._capture is not None and self._capture.isOpened()

    def read(self) -> tuple[bool, Any]:
        if not self.is_opened():
            return False, None
        return self._capture.read()

    def get(self, property_id: int) -> float:
        if not self.is_opened():
            return 0.0
        return float(self._capture.get(property_id))

    def release(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None


class UploadedVideoSource(OpenCVVideoSource):
    """The stable uploaded-video source used by the existing API workflow."""

    def __init__(self, path: str | Path):
        super().__init__(path, source_kind="upload")


class LiveOpenCVSource(OpenCVVideoSource):
    """OpenCV camera/stream source for the live pipeline extension."""

    def __init__(self, source: str | int):
        super().__init__(source, source_kind="live")


class RTSPVideoSource(OpenCVVideoSource):
    """Allowlisted RTSP camera source with bounded FFmpeg connection timeouts."""

    def __init__(
        self,
        url: str,
        *,
        allowed_hosts: list[str],
        open_timeout_ms: int = 5000,
        read_timeout_ms: int = 2000,
    ):
        parsed = urlsplit(url)
        hostname = (parsed.hostname or "").encode("idna").decode("ascii").lower().rstrip(".")
        allowed = {host.encode("idna").decode("ascii").lower().rstrip(".") for host in allowed_hosts}
        try:
            port = parsed.port
        except ValueError as exc:
            raise VideoSourceError("The configured RTSP source is invalid.") from exc
        if (
            parsed.scheme.lower() not in {"rtsp", "rtsps"}
            or not hostname
            or hostname not in allowed
            or parsed.path == ""
            or parsed.fragment
            or (port is not None and not 1 <= port <= 65535)
            or open_timeout_ms <= 0
            or read_timeout_ms <= 0
        ):
            raise VideoSourceError("The configured RTSP source is invalid or its host is not allowlisted.")
        super().__init__(
            url,
            source_kind="rtsp",
            backend=cv2.CAP_FFMPEG,
            open_timeout_ms=open_timeout_ms,
            read_timeout_ms=read_timeout_ms,
        )
