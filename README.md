# PREDIX — Predictive Intelligence Platform

PREDIX analyzes uploaded and browser-camera video with local YOLO detection, temporary anonymous tracking, polygon-zone occupancy estimates, and evidence-linked analytics. Forecasts are withheld when a complete observation history cannot support chronological evaluation. Detector confidence is not system accuracy, and an occupancy estimate is not a unique-person count.

## Current capabilities

- MP4, WebM, and MOV upload with streamed size enforcement, video decoding checks, and server-extracted metadata.
- Asynchronous YOLO inference, progress reporting, annotated playback, and paginated frame-level detections.
- User-started browser-camera, allowlisted RTSP, and browser-native HTTPS HLS analysis over bounded WebSocket frame streams, sharing the same detector runtime as uploaded video.
- Event grouping, temporal summaries, configurable polygon zones, active anonymous person-track estimates, observed zone entries/exits and between-zone transitions, occupancy trends, and operator-configured capacity statuses. Live counts separate raw detections, observed tracks, and tracks carried through a configurable missed-sample limit.
- Uploaded-video detector-activity deviation against a trailing median/scaled-MAD baseline. It requires consecutive buckets, breaks on missing data, and describes detector output volume only; it is not occupancy or an incident signal.
- Per-zone 1/5/10-minute occupancy forecasts compared against persistence using chronological rolling-origin evaluation; unsupported horizons return insufficient data.
- Live zone forecasts use completed 15-second occupancy buckets and the same rolling-origin evaluator; the 1-minute horizon needs six continuous minutes, while 5- and 10-minute horizons need 30 and 60 minutes.
- Robust occupancy-deviation signals and a limited early-warning cue that requires both configured capacity and deviation evidence. It recommends human verification and does not produce a risk score or incident determination.
- Per-zone operator-review guidance from configured capacity and occupancy-deviation rules. It can recommend human review but does not prescribe staffing or allocate security resources; the rule has not been validated against labeled incidents.
- Live occupancy-signal alerts group current configured capacity/deviation signals by zone, expose evidence, and avoid duplicate entries per zone. Their severity mirrors operator-configured occupancy thresholds; they are not security or incident alerts.
- SQLite persistence for uploaded sessions, live-session aggregate summaries, events, aggregates, indexed uploaded/live occupancy observations, evaluated live forecasts, and deduplicated occupancy-signal alert episodes with evidence and active/resolved/session-ended state. Schema version 6 preserves existing history; session deletion removes associated stored records.
- Historical recurring-observation analysis and a legacy next-session activity-rate advisory, with evidence and insufficient-data responses.
- Responsive React interface with upload/analysis, zone drawing, analytics, and historical comparisons.

PREDIX detects general object categories. Uploaded and live analysis use short-lived anonymous box association; IDs are not identities, and occupancy can miss or double-count people. Movement is measured in image pixels, not calibrated physical direction. Live zone occupancy is available after the operator draws a polygon; live zone settings and track membership remain in memory, while aggregate session summaries are retained in SQLite until deleted. A live occupancy early-warning cue appears only when an operator-configured capacity status and a trailing occupancy deviation co-occur; the rule is not validated against labeled anomaly events. Per-zone review guidance uses those same operator-configured rules and recommends human review only; it is not validated as an incident predictor and does not prescribe staffing or allocate security resources. Suspicious-object detection, security alerts, and incident-risk classification remain unavailable because no validated model, dataset, or operational policy is configured. The general detector does not trigger security alerts. PREDIX does not perform facial recognition or identity matching. Live mode supports browser cameras, allowlisted RTSP input, and HTTPS HLS in browsers with native HLS playback and CORS-enabled frame sampling. HLS playlists load directly in the operator's browser; no backend HLS gateway fetches playlist-referenced resources. Sampled frames use the same detector engine as uploaded video.

## Technology stack

| Layer | Technology |
| --- | --- |
| Frontend | React, Vite, Tailwind CSS, Lucide icons |
| API | FastAPI, Pydantic settings, Uvicorn |
| Vision | Ultralytics YOLO, PyTorch, OpenCV |
| Persistence | SQLite behind a repository interface |
| Tests | Python `unittest`, FastAPI `TestClient`, frontend build and Oxlint |

## Project structure

```text
PREDIX/
├── backend/app/       # API, CV, analytics, prediction, events, database, configuration
├── backend/tests/     # backend unit and API integration tests
├── frontend/src/      # React application and analysis/dashboard components
├── docs/              # architecture, API, development, testing, model, privacy
├── README.md
└── .gitignore
```

## Requirements

- Python 3.11 (the pinned backend dependencies are in `backend/requirements.txt`).
- Node.js and npm.
- OpenCV-compatible video files. Apple Silicon MPS is selected automatically when available; CPU is the fallback. CUDA can be selected explicitly on a compatible host.
- The configured Ultralytics model weights. `yolo11n.pt` is downloaded by Ultralytics on first use if it is not already available.

## Run locally

From the repository root:

```sh
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

In another terminal:

```sh
cd frontend
npm install
cp .env.example .env
npm run dev
```

Open the Vite URL printed by npm (normally `http://localhost:5173`). The frontend API base is configurable with `VITE_API_URL`; its default is `http://localhost:8000`.

## Configuration

Backend settings are read from `backend/.env` or the process environment. Copy `backend/.env.example` and adjust as needed:

| Setting | Purpose |
| --- | --- |
| `ALLOWED_ORIGINS` | Comma-separated browser origins allowed by CORS. |
| `MAX_UPLOAD_SIZE_BYTES` | Maximum streamed upload size. |
| `UPLOAD_DIR_NAME`, `DATABASE_PATH` | Source-video storage and SQLite database paths (relative paths resolve from `backend/`). |
| `MODEL_NAME`, `DEFAULT_CONF_THRESHOLD`, `DEFAULT_IMAGE_SIZE`, `FRAME_STRIDE`, `TRACK_IOU_THRESHOLD`, `TRACK_MAX_MISSED_FRAMES`, `DEVICE` | Detector and anonymous tracker configuration. IoU threshold must be greater than 0 and at most 1; missed-frame retention is 0–10. Tracking updates run on every inferred frame; uploaded-video cadence follows `FRAME_STRIDE`, while live cadence follows the frontend interval setting. `DEVICE` is `auto`, `cpu`, `mps`, or `cuda`. |
| `LIVE_MAX_FRAME_BYTES`, `LIVE_MAX_FRAME_WIDTH`, `LIVE_MAX_FRAME_HEIGHT`, `LIVE_MIN_FRAME_INTERVAL_MS` | Bound frame size, resolution, and WebSocket inference cadence for browser-camera input. |
| `VITE_LIVE_FRAME_WIDTH`, `VITE_LIVE_FRAME_HEIGHT`, `VITE_LIVE_FRAME_INTERVAL_MS` | Frontend live capture target dimensions (clamped to 320–1280 by 240–720 px) and minimum frame interval (clamped to 250–10000 ms). Coordinate dimensions with backend `LIVE_MAX_FRAME_WIDTH` and `LIVE_MAX_FRAME_HEIGHT`; defaults are 640×720 px and 500 ms. Frames are scaled to fit both dimension limits while preserving aspect ratio. |

Do not commit `.env`, uploaded videos, generated outputs, databases, or model weights. The repository `.gitignore` excludes these paths and file types.

## Processing and data

1. Upload is written under a UUID-prefixed server filename. Filename, extension, MIME type, streamed size, and video decoding are checked.
2. Analysis runs in a background worker, one video at a time per process. It writes sampled detections, deterministic events, an annotated video, and aggregate summaries.
3. Completed results are committed to SQLite. Frame detections and anonymous track observations remain in JSONL; events, aggregates, and track-aware zone occupancy buckets are queryable through the repository.
4. Zone occupancy forecasts require complete track-aware samples and at least three training plus three chronological validation windows for each horizon. A trailing mean is used only if its MAE improves on the persistence baseline. Error ranges use rolling-origin MAE and are not calibrated probabilities.
5. Zone deviation signals compare against the preceding six occupancy buckets using a configurable median/scaled-MAD threshold. The early-warning cue requires both a configured HIGH/CRITICAL capacity status and an occupancy deviation. This cue is unvalidated against incident outcomes and only recommends human verification.
6. The older activity-rate forecast remains available for compatibility and predicts object instances per sampled frame; it is not the primary crowd forecast.

Video and derived information remain on the configured host until the session is deleted. `DELETE /api/video/{video_id}` deletes the source video, generated outputs, zone config, and related SQLite records. Live sampled frames and temporary track state are memory-only; aggregate live-session summaries remain in SQLite until deleted with `DELETE /api/live/sessions/{session_id}`. Back up or delete the SQLite database separately when managing the host. The application does not include user authentication or role-based access; keep it on a trusted network or put it behind an authenticated gateway before multi-user or public deployment. CORS is not an access-control substitute.

## API overview

Interactive OpenAPI documentation is available at `/docs` while the backend is running.

| Method | Route | Description |
| --- | --- | --- |
| `GET` | `/api/health` | Service health. |
| `GET` | `/api/capabilities` | Configured intelligence capabilities and evidence limits. |
| `GET` | `/api/live/status` | Current browser-camera session metrics. |
| `GET` | `/api/live/sessions` | List persisted aggregate live-session summaries. |
| `GET`, `DELETE` | `/api/live/sessions/{session_id}` | Read or delete one aggregate live-session record. |
| `GET` | `/api/live/sessions/{session_id}/zones/{zone_id}/occupancy` | Read stored aggregate occupancy buckets and available evaluated forecasts for one live zone. |
| `GET` | `/api/live/sessions/{session_id}/alerts` | Read persisted occupancy-signal alert episodes and their active, resolved, or session-ended status. |
| `GET` | `/api/live/alerts` | Read the current grouped occupancy-signal snapshot (not security or incident alerts). |
| `WebSocket` | `/api/live/ws` | Receive sampled JPEG frames or configured RTSP frame requests and return detections/latency metrics. |
| `POST` | `/api/video/upload` | Upload a video as multipart field `file`. |
| `DELETE` | `/api/video/{video_id}` | Delete the session and its persisted artifacts. |
| `GET`, `PUT` | `/api/video/{video_id}/zones` | Read or configure normalized polygon zones before analysis. |
| `POST` | `/api/video/{video_id}/analyze` | Start asynchronous analysis. |
| `GET` | `/api/video/{video_id}/analysis/status` | Read job progress and state. |
| `GET` | `/api/video/{video_id}/analysis/result` | Read completed summary. |
| `GET` | `/api/video/{video_id}/analysis/detections` | Page frame-level detections. |
| `GET` | `/api/video/{video_id}/analysis/events` | Page generated events. |
| `GET` | `/api/video/{video_id}/analysis/temporal` | Query temporal summaries and detector-activity deviation. |
| `GET` | `/api/video/{video_id}/analysis/spatial` | Query zone summaries. |
| `GET` | `/api/video/{video_id}/analysis/zones/{zone_id}/forecast` | Evaluated 1/5/10-minute visible-person occupancy forecasts. |
| `GET` | `/api/video/{video_id}/annotated` | Stream annotated MP4 output. |
| `GET` | `/api/history/sessions` and `/api/history/sessions/{video_id}` | List and inspect stored sessions. |
| `GET` | `/api/history/sessions/{video_id}/events`, `/activity`, `/zones`, `/occupancy/{zone_id}` | Query stored events and aggregates; activity endpoints accept video-time ranges. |
| `GET` | `/api/history/patterns` | Identify supported recurring observations. |
| `GET` | `/api/history/predictions/activity-rate` | Evaluated next-session estimate when history qualifies. |
| `GET` | `/api/history/decision-support` | Evidence-linked advisory recommendation when warranted. |

## Validation

Backend unit and API integration tests:

```sh
cd backend
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m pip check
.venv/bin/python -m compileall -q app tests
```

Frontend production build and lint:

```sh
cd frontend
npm run build
npm run lint
```

## Architecture

```text
React/Vite
  └─ FastAPI API
      ├─ Upload and metadata validation
      ├─ Background video detector (OpenCV + Ultralytics)
      ├─ Detection JSONL → events → temporal and zone analytics
      └─ SQLite session/history repository
             └─ patterns → evaluated forecast → advisory decision support
```

Uploaded video, browser-camera frames, browser-native HLS playback, and allowlisted RTSP frames use the same detector and per-frame tracking boundary. The browser camera acquires permission only after an explicit start action and sends one sampled frame at a time to the backend WebSocket. The Live Camera view accepts an RTSP URL whose host is allowlisted by the backend; RTSP frames are sampled over that socket, and the source is released on stop or disconnect. Native HLS is played by the operator's browser and requires HTTPS, browser support, and CORS permission for frame sampling; no backend HLS gateway is implemented. Authentication and deployment-grade multi-worker job coordination are not implemented. See [backend/requirements.txt](backend/requirements.txt) for pinned Python dependencies.
