# Architecture

## Runtime components

- **React/Vite frontend** owns upload, progress polling, zone editing, playback, and presentation of API-derived results.
- **FastAPI** validates requests, coordinates background inference, exposes analysis/history routes, and sanitizes client-facing errors.
- **Video processing** validates decoded metadata with OpenCV and iterates frames without loading the full video into memory.
- **Detector** wraps configurable Ultralytics inference and writes newline-delimited structured detection records plus an annotated MP4.
- **Event engine** groups detections from the same sampled frame and class into reproducible `object_detected` events. It assigns a zone using the bounding-box centroid when a configured normalized polygon contains it.
- **Analytics** derives time buckets and zone summaries from stored detection/event records.
- **SQLite repository** owns session, event, and aggregate persistence behind a repository boundary.
- **Prediction services** analyze only compatible completed sessions and return explicit insufficient-data responses when validation cannot be performed.

## Data path

```text
Upload → metadata validation → session row → background detector
  → detection JSONL → events JSONL → temporal and spatial summaries
  → atomic SQLite completion transaction → API → dashboard
                                         └→ patterns → evaluated forecast → advisory support
```

The frame record is the lowest-level stored observation. Events group same-frame class observations; temporal and spatial aggregates summarize those observations. Forecasts are distinct from observations and expose their target, supporting sessions, model configuration, and rolling-origin evaluation.

## Persistence and lifecycle

The default database is `backend/data/predix.sqlite3`. Source videos live in `backend/uploads/`; annotated videos and intermediate JSONL artifacts live in `backend/analysis_outputs/`. These paths are ignored by Git. Deleting a session removes its files and cascades through SQLite records. Zone configuration is stored per video before analysis starts.

Job state is held in memory and one analysis job is allowed at a time per process. SQLite history survives process restart, but active jobs do not. Multi-worker job coordination is not implemented.

## Streaming extension point

The current supported source is an uploaded video. The detector processes frames incrementally and the event/analytics services consume structured records, so a future camera source can feed the same frame inference and downstream services. No camera capture, WebRTC, RTSP, or live stream API is implemented. Keep the upload route and its lifecycle as the stable source implementation when adding another source.

## Trust boundaries and limitations

Uploads are untrusted input: extension, MIME, size, and actual decodability are checked; server paths are generated from UUIDs. CORS uses configured origins. The application has no user authentication or authorization and should remain on a trusted host/network or behind an authenticated gateway. SQLite is appropriate for local academic use; concurrent distributed deployment needs a different job coordinator and database deployment plan.
