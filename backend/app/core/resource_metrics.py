"""Best-effort process resource telemetry using local runtime measurements."""

import threading
import time
import sys
from typing import Any

try:
    import resource
except ImportError:  # pragma: no cover - resource is unavailable on Windows
    resource = None

_sample_lock = threading.Lock()
_previous_sample: tuple[float, float] | None = None


def process_resource_metrics(*, device: str | None = None, torch_module: Any = None) -> dict:
    """Return measured process CPU/RSS and optional PyTorch MPS allocation.

    CPU percent is a delta between health calls and is normalized to one CPU
    core, so it can exceed 100% for a multithreaded process. RSS is the process
    high-water mark since start, not its current resident size.
    """
    global _previous_sample

    now = time.monotonic()
    cpu_seconds = None
    peak_rss_mb = None
    if resource is not None:
        try:
            usage = resource.getrusage(resource.RUSAGE_SELF)
            cpu_seconds = float(usage.ru_utime + usage.ru_stime)
            raw_rss = float(usage.ru_maxrss)
            # macOS reports bytes; Linux and the common BSD variants report KiB.
            peak_rss_mb = raw_rss / (1024 * 1024 if sys.platform == "darwin" else 1024)
        except (OSError, ValueError, AttributeError):
            pass

    cpu_percent = None
    if cpu_seconds is not None:
        with _sample_lock:
            previous = _previous_sample
            _previous_sample = (now, cpu_seconds)
        if previous is not None:
            elapsed = now - previous[0]
            if elapsed > 0:
                cpu_percent = round(max(0.0, cpu_seconds - previous[1]) / elapsed * 100, 1)

    mps_allocated_mb = None
    if device == "mps" and torch_module is not None:
        mps = getattr(torch_module, "mps", None)
        current_allocated = getattr(mps, "current_allocated_memory", None)
        if callable(current_allocated):
            try:
                mps_allocated_mb = round(float(current_allocated()) / (1024 * 1024), 1)
            except (RuntimeError, OSError, TypeError, ValueError):
                pass

    return {
        "status": "available" if cpu_seconds is not None or peak_rss_mb is not None or mps_allocated_mb is not None else "unavailable",
        "process_cpu_percent_of_one_core": cpu_percent,
        "process_cpu_seconds_since_start": round(cpu_seconds, 2) if cpu_seconds is not None else None,
        "process_peak_rss_mb_since_start": round(peak_rss_mb, 1) if peak_rss_mb is not None else None,
        "mps_allocated_mb": mps_allocated_mb,
        "measurement_notes": {
            "cpu_percent": "Measured between health requests; null on the first sample; may exceed 100% for multithreaded CPU work.",
            "resident_memory": "Peak resident memory since process start, not current memory.",
            "mps_memory": "PyTorch MPS allocated tensor memory only; not total device memory or utilization.",
        },
    }
