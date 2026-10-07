# PREDIX — Predictive Intelligence Platform

PREDIX analyzes uploaded video with local YOLO object detection, turns frame observations into events and time/zone summaries, and stores completed sessions for transparent historical analysis. Forecasts and recommendations are withheld when the history is too small or incompatible. Detection counts are frame-level instances; they are not unique people or object tracks.

## Current capabilities

- MP4, WebM, and MOV upload with streamed size enforcement, video decoding checks, and server-extracted metadata.
- Asynchronous YOLO inference, progress reporting, annotated playback, and paginated frame-level detections.
- Event grouping, temporal activity summaries, configurable normalized polygon zones, and zone activity views.
- SQLite persistence for sessions, events, and aggregate measurements. Deleting a session removes its stored history and files.
- Historical recurring-observation analysis; a next-session activity-rate estimate with rolling-origin evaluation; and evidence-linked advisory decision support.
- Responsive React interface with upload/analysis, zone drawing, analytics, and historical comparisons.

PREDIX detects general object categories. It does not perform facial recognition, identity matching, object tracking, unique-person counting, risk scoring, or live camera ingestion. The current pipeline is uploaded-video based; the detector, event engine, and source processing boundary are intended extension points for a future live source.

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
| `MODEL_NAME`, `DEFAULT_CONF_THRESHOLD`, `DEFAULT_IMAGE_SIZE`, `FRAME_STRIDE`, `DEVICE` | Detector model and inference configuration. `DEVICE` is `auto`, `cpu`, `mps`, or `cuda`. |

Do not commit `.env`, uploaded videos, generated outputs, databases, or model weights. The repository `.gitignore` excludes these paths and file types.

## Processing and data

1. Upload is written under a UUID-prefixed server filename. Filename, extension, MIME type, streamed size, and video decoding are checked.
2. Analysis runs in a background worker, one video at a time per process. It writes sampled detections, deterministic events, an annotated video, and aggregate summaries.
3. Completed results are committed to SQLite. Frame detections remain in JSONL output files; events and aggregates are queryable from SQLite.
4. Historical patterns need at least three completed sessions. Activity forecasts need at least six sessions with the same model, confidence, stride, and image size, allowing at least three rolling-origin test windows. Estimates are normalized to object instances per sampled frame and are not calibrated probabilities.
5. Decision support only suggests reviewing resource plans when the forecast is above the compatible history's 75th percentile. It is advisory and exposes the comparison evidence.

Video and derived information remain on the configured host until the session is deleted. `DELETE /api/video/{video_id}` deletes the source video, generated outputs, zone config, and related SQLite records. Back up or delete the SQLite database separately when managing the host. The application does not include user authentication or role-based access; keep it on a trusted network or put it behind an authenticated gateway before multi-user or public deployment. CORS is not an access-control substitute.

## API overview

Interactive OpenAPI documentation is available at `/docs` while the backend is running.

| Method | Route | Description |
| --- | --- | --- |
| `GET` | `/api/health` | Service health. |
| `POST` | `/api/video/upload` | Upload a video as multipart field `file`. |
| `DELETE` | `/api/video/{video_id}` | Delete the session and its persisted artifacts. |
| `GET`, `PUT` | `/api/video/{video_id}/zones` | Read or configure normalized polygon zones before analysis. |
| `POST` | `/api/video/{video_id}/analyze` | Start asynchronous analysis. |
| `GET` | `/api/video/{video_id}/analysis/status` | Read job progress and state. |
| `GET` | `/api/video/{video_id}/analysis/result` | Read completed summary. |
| `GET` | `/api/video/{video_id}/analysis/detections` | Page frame-level detections. |
| `GET` | `/api/video/{video_id}/analysis/events` | Page generated events. |
| `GET` | `/api/video/{video_id}/analysis/temporal` | Query temporal summaries. |
| `GET` | `/api/video/{video_id}/analysis/spatial` | Query zone summaries. |
| `GET` | `/api/video/{video_id}/annotated` | Stream annotated MP4 output. |
| `GET` | `/api/history/sessions` and `/api/history/sessions/{video_id}` | List and inspect stored sessions. |
| `GET` | `/api/history/sessions/{video_id}/events`, `/activity`, `/zones` | Query stored events and aggregates; activity endpoints accept video-time ranges. |
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

The uploaded-video path is the implemented source. Live capture, authentication, tracking, unique identity counts, and deployment-grade multi-worker job coordination are not implemented. See [backend/requirements.txt](backend/requirements.txt) for pinned Python dependencies.
