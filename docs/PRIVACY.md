# Privacy and Security Notes

## Data processed

PREDIX processes video supplied by the operator, decoded frames, general object detections, temporary anonymous box-track IDs, event records, zone configuration, and aggregate session measurements. Source media and derived records are stored locally on the configured host. Uploaded-video track IDs and derived movement/dwell observations are stored in the session's detection JSONL until session deletion. For live mode, browser permission is requested only after an explicit start action; sampled frames and in-memory track state are not persisted by the live service. Aggregate live-session metrics (frame/detection counts, peak active-track estimate, final FPS/latency, and zone totals) are stored in SQLite until deleted with `DELETE /api/live/sessions/{session_id}`. A process restart marks any unfinished live-session row as interrupted. Track IDs are random within a session and are not identities; pixel direction is image-space movement, not a calibrated physical direction; occupancy is a potentially inaccurate active-track estimate, not unique-person counting. A track may remain counted in its last zone for the configured missed-sample limit (`TRACK_MAX_MISSED_FRAMES`, default two). Stopping or leaving the live view closes the socket, clears live tracking state, and stops camera tracks. The application does not perform facial recognition, identity inference, or personal profiling.

## Retention and deletion

Uploaded videos and derived records remain until the operator deletes the session. `DELETE /api/video/{video_id}` removes the source video, annotated output, intermediate JSONL, zone configuration, and associated SQLite rows. Live aggregate history remains until deleted through `DELETE /api/live/sessions/{session_id}`. The application has no automatic expiration policy or multi-user retention controls. Database backups must be managed and deleted separately by the host operator.

## Security controls

- Upload file extension and MIME allowlists, streamed byte limit, decoded-video validation, UUID-generated storage names, and cleanup on failed uploads.
- API path/query/body validation and bounded pagination/range inputs.
- Client errors avoid internal exception details and filesystem locations; diagnostic exceptions are sent to server logs.
- CORS origins are configurable and methods/headers are restricted to the application's browser API needs.
- Environment files, local databases, uploads, outputs, and model weights are excluded from Git.

## Deployment boundary

The application does not implement login, authentication, or per-user authorization. Do not expose it to the public internet or an untrusted shared network without an authenticated gateway, transport encryption, and an access-control/retention plan. CORS is a browser policy, not authentication. Logs should be access-controlled because exceptions can contain local operational details. Review applicable organizational policies before processing real campus video.
