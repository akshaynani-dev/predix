# Development Guide

## Environment

Use Python 3.11 in `backend/.venv` and Node/npm in `frontend/`. Follow the repository-root startup commands in [README.md](../README.md). Copy the `.env.example` files before changing local settings. Never put secrets or personal paths in tracked files.

## Change workflow

1. Inspect the relevant API, service, UI, and tests before editing.
2. Keep dependencies pinned and make the smallest change that fits the existing boundaries.
3. Put business logic in its service/module, not in a route or large UI component.
4. Preserve the raw observation → event → aggregate → pattern → forecast lineage.
5. Add/update tests for behavior and error paths.
6. Run backend tests, `pip check`, `compileall`, frontend build, and lint before handoff.
7. For a CV change, verify a real decoded video through the configured local model where practical; clearly distinguish fixture tests from real inference.

## Useful commands

```sh
cd backend
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m pip check
.venv/bin/python -m compileall -q app tests
```

```sh
cd frontend
npm run build
npm run lint
```

## Configuration notes

Backend settings are loaded from `backend/.env` or environment variables. Relative upload/database paths are resolved from `backend/`. Detector settings use the same backend env file. Browser-camera frame size, dimensions, and inference cadence are bounded by the `LIVE_MAX_FRAME_*` and `LIVE_MIN_FRAME_INTERVAL_MS` settings. Frontend live capture dimensions and minimum frame interval can be set with `VITE_LIVE_FRAME_WIDTH`, `VITE_LIVE_FRAME_HEIGHT`, and `VITE_LIVE_FRAME_INTERVAL_MS`; defaults are 640×720 px and 500 ms. Frames are scaled to fit both target dimensions while preserving aspect ratio. Coordinate these values with backend `LIVE_MAX_FRAME_WIDTH` and `LIVE_MAX_FRAME_HEIGHT`. The frontend reads Vite settings at build/dev startup. CORS origins are configured with `ALLOWED_ORIGINS`.

## Data and cleanup

Local uploads, outputs, SQLite data, virtual environments, node_modules, and model weights are excluded from version control. Delete a demo session through `DELETE /api/video/{video_id}` to clean its source, analysis outputs, zone file, and historical rows. Do not delete user media for development unless the owner requested it.
