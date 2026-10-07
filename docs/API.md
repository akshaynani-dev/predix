# API Reference

The live OpenAPI schema at `/openapi.json` and interactive `/docs` are the source of truth for request and response models. API base is `http://localhost:8000/api` in local development. IDs are UUID4 values returned by upload.

## Upload and lifecycle

### `POST /video/upload`

Multipart form field `file`. Accepts configured `.mp4`, `.webm`, or `.mov` extensions and corresponding video MIME types. The response contains `video_id`, server `stored_filename`, byte size, content type, and decoded duration/resolution/FPS/frame count. Errors include 400 for invalid or unsupported video, 413 for over-limit uploads, and 500 for storage/database failures.

### `DELETE /video/{video_id}`

Deletes the uploaded file, analysis artifacts, zone configuration, and SQLite session/history. Returns 404 when no source file exists and 400 for invalid IDs.

## Zones and analysis

- `GET /video/{video_id}/zones` returns the session's normalized polygon configuration.
- `PUT /video/{video_id}/zones` accepts a JSON `zones` array; each zone has a unique `zone_id`, `name`, and polygon points normalized to the video dimensions in `[0,1]`. Zones lock once analysis starts.
- `POST /video/{video_id}/analyze` starts background analysis and returns a job ID and detector configuration.
- `GET /video/{video_id}/analysis/status` returns progress/state; `GET /analysis/result` returns a completed summary.
- `GET /analysis/detections?limit=100&offset=0` pages sampled frame detections.
- `GET /analysis/events?limit=100&offset=0` pages derived events.
- `GET /analysis/temporal?bucket_seconds=15` returns time-bucket aggregates and derived summary statistics.
- `GET /analysis/spatial?bucket_seconds=15` returns configured-zone and unassigned activity.
- `GET /video/{video_id}/annotated` streams the generated MP4.

## History and intelligence

- `GET /history/sessions?limit=50&offset=0&start_at=...&end_at=...` lists sessions; timestamp filters require timezone offsets.
- `GET /history/sessions/{video_id}` returns stored session details.
- `GET /history/sessions/{video_id}/events?limit=100&offset=0` pages persisted events.
- `GET /history/sessions/{video_id}/activity?start_seconds=...&end_seconds=...` queries video-relative aggregate buckets and statistics.
- `GET /history/sessions/{video_id}/zones?start_seconds=...&end_seconds=...` queries stored zone aggregates.
- `GET /history/patterns` discovers recurring class/zone observations only when evidence thresholds are met.
- `GET /history/predictions/activity-rate` evaluates a trailing-mean next-session estimate when enough compatible history exists.
- `GET /history/decision-support` returns a cautious advisory only when the forecast qualifies.

All query limits and ranges are validated. Historical event/aggregate routes require a completed session. Prediction values are rates of detected instances per sampled frame, not counts of unique entities.
