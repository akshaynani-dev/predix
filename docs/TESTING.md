# Testing

## Automated coverage

Backend tests use `unittest` and FastAPI `TestClient`. Integration-test lifespans use a temporary SQLite database so test fixtures cannot contaminate the developer database or change its schema/history. Tests cover upload validation and cleanup, component health/capability responses, process CPU/RSS/MPS metric labeling, API history, SQLite forward migrations through version 6, occupancy persistence/deletion and live-session summary and per-zone history persistence/interruption/deletion, occupancy-alert episode migration/deduplication/resolution/session-end handling and history API behavior, detector sampling and tracking serialization including capture/staged-file cleanup when metadata or video-writer setup fails, shared frame-processing behavior, shared upload/live tracker configuration and pipeline-owner-safe model unloading, short-lived active-track occupancy smoothing and raw-detection separation, allowlisted RTSP URL validation and timeout parameterization, RTSP WebSocket frame inference/stop cleanup and sanitized allowlist rejection, browser-camera WebSocket frame handling/disconnect cleanup, bounded live occupancy bucket aggregation and rolling-validated prediction (including missing-window behavior and completed-bucket reporting), live early-warning insufficient-history and combined-signal behavior, grouped occupancy alert severity/evidence/deduplication and current-vs-persisted endpoint behavior, event generation, temporal and spatial calculations including observed track-based zone transitions, capacity thresholds, runtime benchmark sampling and metric labeling, detector evaluation including prediction-only false positives and confusion-matrix handling, occupancy forecasts against a persistence baseline, anomaly signals, early-warning combinations, pattern evidence, and existing activity-rate decision-support behavior.

Frontend tests cover bounded live reconnect backoff, health-state mapping from real API responses, and bounded analysis-status retry backoff. Run them with `cd frontend && npm test`; also run `npm run lint` and `npm run build`.

Run the complete checks:

```sh
cd backend
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m pip check
.venv/bin/python -m compileall -q app tests
cd ../frontend
npm run build
npm run lint
npm test
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
8. Start a configured live source, confirm observations include detections, occupancy, and stream metrics, then stop it and confirm the stream is offline.
9. After successful upload analysis or a stopped live session, confirm `/api/health` reports the detection model as `NOT_LOADED`; the next inference session should load the model lazily again. Delete the live-session record after checking its summary.

Actual inference smoke tests depend on local model weights and the host's OpenCV/device support. Record device, model, frame count, elapsed time, and measured throughput when reporting such a run. Do not treat an empty-scene smoke video as a model-accuracy evaluation.

For labeled evaluation, provide frame-aligned ground-truth JSONL with `frame_number` and `detections` entries containing `class` and pixel `bbox` (`x1`, `y1`, `x2`, `y2`). Generate candidate predictions from a local checkpoint with `cd backend && ./.venv/bin/python -m app.cv.predict_benchmark path/to/video.mp4 path/to/predictions.jsonl --model /path/to/local-model.pt`, then run `cd backend && ./.venv/bin/python -m app.cv.benchmark path/to/labels.jsonl path/to/predictions.jsonl --iou 0.5`. The evaluator reports per-class precision, recall, false positives/negatives, interpolated AP at the selected IoU, AP for each IoU from 0.50 through 0.95, mAP@[.50:.95], and a confusion matrix with background misses/false alarms. Compare confidence thresholds with `cd backend && ./.venv/bin/python -m app.cv.confidence_benchmark path/to/video.mp4 path/to/labels.jsonl --thresholds 0.15 0.25 0.4 0.5`; all thresholds use the same clip/labels/stride and no candidate is selected automatically. Compare candidates on the same labeled frames and stride; any labeled frame skipped by inference counts as a miss. Ground truth must cover representative scenes; current repository data has no labeled benchmark set, so no accuracy score is claimed.

Tracking and occupancy are evaluated separately. Labeled tracking records must include persistent anonymous `track_id` values; run `cd backend && ./.venv/bin/python -m app.cv.tracking_benchmark path/to/tracks.jsonl path/to/predictions.jsonl --iou 0.5` for MOTA, ID switches, and fragmentation using frame-local greedy IoU matching. Occupancy labels use distinct person track IDs per frame; run `cd backend && ./.venv/bin/python -m app.cv.occupancy_benchmark path/to/tracks.jsonl path/to/predictions.jsonl` for MAE, RMSE, bias, and MAPE only on nonzero ground-truth frames. Keep frame IDs aligned; frames without predictions are treated as misses by detection metrics. These evaluators are workflows only; there is no labeled project set, so no tracking or occupancy quality score is currently claimed.

Occupancy-deviation rules can be evaluated separately from object detection: create JSONL records with `session_id`, `zone_id`, `bucket_start_seconds`, `estimated_occupancy`, and a manually assigned boolean `anomaly` label, with continuous buckets per session/zone. Run `cd backend && ./.venv/bin/python -m app.analytics.anomaly_benchmark path/to/labeled-zone-buckets.jsonl --bucket-seconds 15 --baseline-buckets 6 --mad-multiplier 3 --minimum-increase 1`. The evaluator uses only preceding observations for each prediction and reports the confusion matrix, precision, recall, F1, specificity, and excluded warmup buckets. Define labels before running and evaluate on held-out sessions; repeated buckets, missing intervals, non-finite values, and non-boolean labels are rejected. The repository has no labeled anomaly set, so this command currently supports evaluation workflows, not an anomaly-performance claim.

Native HLS integration tests cover HTTPS playlist URL validation, the browser-source WebSocket handshake, `source_kind` persistence, and rejection of playlist URLs at the backend. A real playback smoke test requires a reachable HTTPS `.m3u8` source with anonymous CORS headers on its playlists and media resources, and a browser whose video element reports native HLS support. Confirm sampled detections, `source_kind: hls` in live history, visible CORS/playback errors, bounded retries, and release on stop. No representative HLS fixture or source URL is included in the repository, so automated tests do not claim end-to-end camera playback.

## Local smoke measurement (2026-10-07)

On the development Mac, a 5-frame, 64×48 synthetic blank MP4 completed end to end with `yolo11n.pt` on Apple MPS. The latest run reported 1.60 s processing time (3.12 sampled frames/s), 4.54 ms upload handling for this tiny local file, and 1.25 ms `/api/health` latency through in-process TestClient. Peak Python-process RSS was 561.2 MiB, including Python, OpenCV, PyTorch, and the loaded detector; cumulative process CPU time was 1.97 s. A separate frontend browser health request completed in 19 ms.

These are smoke measurements, not representative capacity benchmarks: the clip is tiny and blank, the API latency excludes a real network hop, and no CPU/GPU utilization percentage or frontend cold-load time was collected. MPS was selected for inference. Measure representative footage and device utilization before tuning or making deployment capacity claims.

## Live inference smoke check (2026-10-10)

A generated 320×240 JPEG was sent through the live WebSocket using the local `yolo11n.pt` model on Apple MPS. PREDIX returned an `observation` for frame 1; after the stop message it acknowledged `session_stopped`, reported live status `offline`, and health returned the detector to `NOT_LOADED`. The session summary was persisted as `disconnected` and deleted with HTTP 200. This verifies the live inference and cleanup path only; a single synthetic frame is not a detection-quality or camera-source validation.

## Existing project clip runtime benchmark (2026-10-10)

The existing 2320×1080, 30 fps upload was benchmarked with `cd backend && ./.venv/bin/python -m app.cv.performance_benchmark uploads/907fabcd-13ad-41b1-97f6-981807e902a0_12269404_2320_1080_30fps.mp4` using `yolo11n.pt`, Apple MPS, image size 640, frame stride 1, and confidence threshold 0.25. OpenCV decoded 331 frames; after two warmup frames, the 329 measured frames had 24.396 ms mean latency, 24.522 ms P50, 29.303 ms P95, and 40.990 measured inference FPS. Model load took 1.176 s and whole-process peak RSS was 636.69 MiB. Two same-named project uploads were SHA-256 identical, so this represents one unique clip. The result measures runtime only: there is no frame-aligned ground truth, and it does not establish precision, recall, tracking quality, occupancy error, or suitability for other scenes. RSS includes the Python/OpenCV/PyTorch process, and throughput depends on host load, thermals, video decode, and software versions.

On four evenly spaced frames from this dense scene, `yolo11n.pt` at confidence 0.25 produced mean person-detection counts of 8.00, 14.25, and 25.75 at image sizes 640, 960, and 1280. After two warmup inferences per size, mean inference latency was 18.80 ms, 25.82 ms, and 48.45 ms respectively on MPS. This is a small unlabelled resolution comparison: higher counts do not prove higher recall or better accuracy, and the four-frame timings are not capacity benchmarks. The production default remains unchanged until frame-aligned labels establish whether the additional detections are correct and representative of other scenes.

The same clip completed through the HTTP upload, zone configuration, asynchronous analysis, result retrieval, and delete path using temporary upload/output folders and a temporary SQLite database. Upload returned 200; analysis completed 331 of the metadata-reported 336 frames in 14.53 s with `yolo11n.pt` on MPS. A whole-frame test polygon yielded 2,711 person detection instances and a track-aware mean/peak estimate of 8.19/12 for the short clip. Delete returned 200, removed the source and analysis artifacts, and health reported the model `NOT_LOADED`. The sampled frames visibly contain a dense crowd, so these estimates should not be interpreted as a ground-truth headcount or reliable capacity measurement. This is a qualitative warning about this one scene, not a quantified error rate; representative frame-level person/track labels are required to validate or recalibrate the estimator.
