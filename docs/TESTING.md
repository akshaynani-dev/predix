# Testing

## Automated coverage

Backend tests use `unittest` and FastAPI `TestClient`. They cover upload validation and cleanup, API health/history, SQLite round trips and cascade deletion, detector sampling/serialization, event generation, temporal and spatial calculations, pattern evidence, forecast evaluation, and decision-support thresholds.

Run the complete checks:

```sh
cd backend
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m pip check
.venv/bin/python -m compileall -q app tests
cd ../frontend
npm run build
npm run lint
```

Fixture-based detector tests patch inference results; they validate record handling, not model accuracy. Upload tests create a tiny synthetic video, and corrupt/empty/oversized cases verify rejection and cleanup.

## End-to-end smoke checklist

1. Start FastAPI and Vite; confirm `/api/health` and frontend connectivity.
2. Upload a valid video and check server-reported metadata.
3. Configure zones, start analysis, and poll until completed.
4. Inspect detections, events, temporal/spatial summaries, and annotated playback.
5. Confirm the completed session and aggregates are queryable from history.
6. Confirm pattern/forecast/decision-support responses state insufficient data when the history threshold is not met.
7. Delete the session and confirm related records/artifacts are removed.

Actual inference smoke tests depend on local model weights and the host's OpenCV/device support. Record device, model, frame count, elapsed time, and measured throughput when reporting such a run. Do not treat an empty-scene smoke video as a model-accuracy evaluation.

## Local smoke measurement (2026-10-07)

On the development Mac, a 5-frame, 64×48 synthetic blank MP4 completed end to end with `yolo11n.pt` on Apple MPS. The latest run reported 1.60 s processing time (3.12 sampled frames/s), 4.54 ms upload handling for this tiny local file, and 1.25 ms `/api/health` latency through in-process TestClient. Peak Python-process RSS was 561.2 MiB, including Python, OpenCV, PyTorch, and the loaded detector; cumulative process CPU time was 1.97 s. A separate frontend browser health request completed in 19 ms.

These are smoke measurements, not representative capacity benchmarks: the clip is tiny and blank, the API latency excludes a real network hop, and no CPU/GPU utilization percentage or frontend cold-load time was collected. MPS was selected for inference. Measure representative footage and device utilization before tuning or making deployment capacity claims.
