"""SQLite implementation for persisted sessions, events, and aggregates."""

import json
import math
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from app.spatial.config import classify_capacity


class SessionNotFoundError(LookupError):
    """Raised when a result is saved for a missing uploaded session."""


class SQLiteRepository:
    """Small repository boundary that keeps SQL out of API and CV services."""

    SCHEMA_VERSION = 6

    def __init__(self, database_path: Path):
        self.database_path = Path(database_path)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def health_check(self) -> bool:
        """Confirm SQLite accepts a lightweight read query."""
        with self._connection() as connection:
            return connection.execute("SELECT 1").fetchone()[0] == 1

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version > self.SCHEMA_VERSION:
                raise RuntimeError(
                    f"Database schema version {version} is newer than supported version {self.SCHEMA_VERSION}."
                )
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    video_id TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    stored_filename TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    metadata_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    completed_at TEXT,
                    model TEXT,
                    device TEXT,
                    confidence_threshold REAL,
                    frames_processed INTEGER,
                    total_frames INTEGER,
                    total_detection_instances INTEGER,
                    total_events INTEGER,
                    processing_time_seconds REAL,
                    processing_fps REAL,
                    zones_configured INTEGER NOT NULL DEFAULT 0,
                    summary_json TEXT,
                    temporal_summary_json TEXT,
                    spatial_summary_json TEXT
                );
                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY,
                    video_id TEXT NOT NULL REFERENCES sessions(video_id) ON DELETE CASCADE,
                    timestamp_seconds REAL NOT NULL,
                    event_type TEXT NOT NULL,
                    object_class TEXT NOT NULL,
                    count INTEGER NOT NULL,
                    confidence REAL NOT NULL,
                    zone_id TEXT,
                    zone_name TEXT,
                    metadata_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_events_session_time
                    ON events(video_id, timestamp_seconds);
                CREATE INDEX IF NOT EXISTS idx_events_session_zone_time
                    ON events(video_id, zone_id, timestamp_seconds);
                CREATE TABLE IF NOT EXISTS measurements (
                    video_id TEXT NOT NULL REFERENCES sessions(video_id) ON DELETE CASCADE,
                    bucket_start_seconds REAL NOT NULL,
                    bucket_end_seconds REAL NOT NULL,
                    bucket_seconds INTEGER NOT NULL,
                    observed_frames INTEGER NOT NULL,
                    detection_instances INTEGER NOT NULL,
                    average_instances_per_observed_frame REAL NOT NULL,
                    counts_by_class_json TEXT NOT NULL,
                    PRIMARY KEY(video_id, bucket_start_seconds)
                );
                CREATE TABLE IF NOT EXISTS zone_measurements (
                    video_id TEXT NOT NULL REFERENCES sessions(video_id) ON DELETE CASCADE,
                    zone_id TEXT NOT NULL,
                    zone_name TEXT NOT NULL,
                    bucket_start_seconds REAL NOT NULL,
                    bucket_end_seconds REAL NOT NULL,
                    observed_frames INTEGER NOT NULL,
                    event_count INTEGER NOT NULL,
                    detection_instances INTEGER NOT NULL,
                    counts_by_class_json TEXT NOT NULL,
                    PRIMARY KEY(video_id, zone_id, bucket_start_seconds)
                );
                CREATE INDEX IF NOT EXISTS idx_zone_measurements_session_time
                    ON zone_measurements(video_id, bucket_start_seconds);
                CREATE TABLE IF NOT EXISTS occupancy_observations (
                    video_id TEXT NOT NULL REFERENCES sessions(video_id) ON DELETE CASCADE,
                    zone_id TEXT NOT NULL,
                    bucket_start_seconds REAL NOT NULL,
                    bucket_end_seconds REAL NOT NULL,
                    estimated_mean_visible_people REAL NOT NULL,
                    configured_capacity INTEGER,
                    capacity_ratio REAL,
                    capacity_status TEXT NOT NULL,
                    PRIMARY KEY(video_id, zone_id, bucket_start_seconds)
                );
                CREATE INDEX IF NOT EXISTS idx_occupancy_session_zone_time
                    ON occupancy_observations(video_id, zone_id, bucket_start_seconds);
                CREATE TABLE IF NOT EXISTS live_sessions (
                    session_id TEXT PRIMARY KEY,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    status TEXT NOT NULL,
                    summary_json TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_live_sessions_started_at
                    ON live_sessions(started_at DESC);
                CREATE TABLE IF NOT EXISTS live_occupancy_observations (
                    session_id TEXT NOT NULL REFERENCES live_sessions(session_id) ON DELETE CASCADE,
                    zone_id TEXT NOT NULL,
                    bucket_start_seconds REAL NOT NULL,
                    bucket_end_seconds REAL NOT NULL,
                    observation_count INTEGER NOT NULL,
                    estimated_mean_visible_people REAL NOT NULL,
                    configured_capacity INTEGER,
                    capacity_ratio REAL,
                    capacity_status TEXT NOT NULL,
                    PRIMARY KEY(session_id, zone_id, bucket_start_seconds)
                );
                CREATE INDEX IF NOT EXISTS idx_live_occupancy_session_zone_time
                    ON live_occupancy_observations(session_id, zone_id, bucket_start_seconds);
                CREATE TABLE IF NOT EXISTS live_crowd_predictions (
                    session_id TEXT NOT NULL REFERENCES live_sessions(session_id) ON DELETE CASCADE,
                    zone_id TEXT NOT NULL,
                    as_of_session_seconds REAL NOT NULL,
                    horizon_seconds INTEGER NOT NULL,
                    forecast REAL NOT NULL,
                    uncertainty_mae REAL,
                    model TEXT NOT NULL,
                    evaluation_json TEXT NOT NULL,
                    PRIMARY KEY(session_id, zone_id, as_of_session_seconds, horizon_seconds)
                );
                CREATE INDEX IF NOT EXISTS idx_live_predictions_session_zone_time
                    ON live_crowd_predictions(session_id, zone_id, as_of_session_seconds);
                CREATE TABLE IF NOT EXISTS live_occupancy_alert_episodes (
                    episode_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES live_sessions(session_id) ON DELETE CASCADE,
                    alert_id TEXT NOT NULL,
                    zone_id TEXT NOT NULL,
                    zone TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    ended_at TEXT,
                    severity TEXT NOT NULL CHECK (severity IN ('WATCH', 'WARNING', 'CRITICAL')),
                    signal TEXT NOT NULL,
                    supporting_evidence_json TEXT NOT NULL,
                    recommendation TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('active', 'resolved', 'session_ended'))
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_live_alert_active_deduplication
                    ON live_occupancy_alert_episodes(session_id, alert_id) WHERE status = 'active';
                CREATE INDEX IF NOT EXISTS idx_live_alert_session_status_time
                    ON live_occupancy_alert_episodes(session_id, status, last_seen_at DESC);
                """
            )
            alert_columns = {
                row["name"] for row in connection.execute(
                    "PRAGMA table_info(live_occupancy_alert_episodes)"
                ).fetchall()
            }
            if "zone" not in alert_columns:
                connection.execute(
                    "ALTER TABLE live_occupancy_alert_episodes ADD COLUMN zone TEXT NOT NULL DEFAULT ''"
                )
                connection.execute(
                    "UPDATE live_occupancy_alert_episodes SET zone = zone_id WHERE zone = ''"
                )
            # Version 2 adds uploaded-zone occupancy. Version 3 adds aggregate
            # live-session history. Version 4 adds indexed live occupancy buckets
            # and validated crowd-prediction snapshots. Version 5 adds occupancy
            # alert episodes; version 6 adds/backfills their display zone label.
            # No frames or track IDs are stored.
            # Active rows from a previous process are explicitly marked interrupted.
            interrupted_at = datetime.now(timezone.utc).isoformat()
            connection.execute(
                """UPDATE live_sessions SET status = 'interrupted', ended_at = ?
                   WHERE ended_at IS NULL""",
                (interrupted_at,),
            )
            connection.execute(
                """UPDATE live_occupancy_alert_episodes
                   SET status = 'session_ended', ended_at = ?
                   WHERE status = 'active' AND session_id IN (
                       SELECT session_id FROM live_sessions WHERE ended_at = ?
                   )""",
                (interrupted_at, interrupted_at),
            )
            connection.execute(f"PRAGMA user_version = {self.SCHEMA_VERSION}")

    def save_live_occupancy_bucket(
        self,
        session_id: str,
        zone_id: str,
        *,
        bucket_start_seconds: float,
        bucket_end_seconds: float,
        observation_count: int,
        estimated_mean_visible_people: float,
        configured_capacity: int | None,
        capacity_ratio: float | None,
        capacity_status: str,
    ) -> None:
        """Persist one completed, aggregate-only live occupancy bucket."""
        numeric_values = (bucket_start_seconds, bucket_end_seconds, estimated_mean_visible_people)
        if (
            not session_id or not zone_id
            or any(not math.isfinite(value) for value in numeric_values)
            or bucket_start_seconds < 0 or bucket_end_seconds <= bucket_start_seconds
            or observation_count < 1 or estimated_mean_visible_people < 0
            or (configured_capacity is not None and configured_capacity < 1)
            or (capacity_ratio is not None and (not math.isfinite(capacity_ratio) or capacity_ratio < 0))
            or capacity_status not in {"NORMAL", "LOW", "MODERATE", "HIGH", "CRITICAL", "UNCONFIGURED", "UNAVAILABLE"}
        ):
            raise ValueError("Invalid live occupancy bucket.")
        with self._connection() as connection:
            connection.execute(
                """INSERT INTO live_occupancy_observations
                   (session_id, zone_id, bucket_start_seconds, bucket_end_seconds,
                    observation_count, estimated_mean_visible_people, configured_capacity,
                    capacity_ratio, capacity_status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(session_id, zone_id, bucket_start_seconds) DO UPDATE SET
                    bucket_end_seconds = excluded.bucket_end_seconds,
                    observation_count = excluded.observation_count,
                    estimated_mean_visible_people = excluded.estimated_mean_visible_people,
                    configured_capacity = excluded.configured_capacity,
                    capacity_ratio = excluded.capacity_ratio,
                    capacity_status = excluded.capacity_status""",
                (
                    session_id, zone_id, bucket_start_seconds, bucket_end_seconds,
                    observation_count, estimated_mean_visible_people, configured_capacity,
                    capacity_ratio, capacity_status,
                ),
            )

    def save_live_crowd_predictions(
        self,
        session_id: str,
        zone_id: str,
        forecast: dict[str, Any],
    ) -> None:
        """Persist only available, chronologically evaluated live forecasts."""
        as_of = forecast.get("as_of_session_seconds")
        if not session_id or not zone_id or not isinstance(as_of, (int, float)) or not math.isfinite(as_of) or as_of < 0:
            raise ValueError("Invalid live crowd prediction time.")
        rows = []
        for item in forecast.get("forecasts", []):
            if item.get("status") != "available":
                continue
            horizon = item.get("horizon_seconds")
            estimate = item.get("forecast")
            uncertainty = (item.get("uncertainty") or {}).get("mae")
            model = item.get("model")
            evaluation = item.get("evaluation")
            if (
                isinstance(horizon, bool) or not isinstance(horizon, int) or horizon < 1
                or isinstance(estimate, bool) or not isinstance(estimate, (int, float))
                or not math.isfinite(estimate) or estimate < 0
                or not isinstance(model, str) or not model
                or not isinstance(evaluation, dict)
                or (uncertainty is not None and (not isinstance(uncertainty, (int, float)) or not math.isfinite(uncertainty) or uncertainty < 0))
            ):
                raise ValueError("Invalid evaluated live crowd prediction.")
            rows.append((
                session_id, zone_id, float(as_of), horizon, float(estimate),
                float(uncertainty) if uncertainty is not None else None,
                model, json.dumps(evaluation, separators=(",", ":")),
            ))
        if not rows:
            return
        with self._connection() as connection:
            connection.executemany(
                """INSERT INTO live_crowd_predictions
                   (session_id, zone_id, as_of_session_seconds, horizon_seconds, forecast,
                    uncertainty_mae, model, evaluation_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(session_id, zone_id, as_of_session_seconds, horizon_seconds) DO UPDATE SET
                    forecast = excluded.forecast,
                    uncertainty_mae = excluded.uncertainty_mae,
                    model = excluded.model,
                    evaluation_json = excluded.evaluation_json""",
                rows,
            )

    def get_live_zone_observations(self, session_id: str, zone_id: str) -> dict[str, list[dict[str, Any]]]:
        """Read durable occupancy buckets and evaluated predictions for a live zone."""
        with self._connection() as connection:
            observations = connection.execute(
                """SELECT * FROM live_occupancy_observations
                   WHERE session_id = ? AND zone_id = ? ORDER BY bucket_start_seconds""",
                (session_id, zone_id),
            ).fetchall()
            predictions = connection.execute(
                """SELECT * FROM live_crowd_predictions
                   WHERE session_id = ? AND zone_id = ?
                   ORDER BY as_of_session_seconds, horizon_seconds""",
                (session_id, zone_id),
            ).fetchall()
        decoded_predictions = []
        for row in predictions:
            item = dict(row)
            item["evaluation"] = json.loads(item.pop("evaluation_json"))
            decoded_predictions.append(item)
        return {
            "observations": [dict(row) for row in observations],
            "predictions": decoded_predictions,
        }

    def update_live_occupancy_alerts(
        self,
        session_id: str,
        alerts: list[dict[str, Any]],
        *,
        observed_at: str | None = None,
    ) -> None:
        """Update deduplicated occupancy-alert episodes from one live observation.

        Repeated frames update the same active episode. Last-seen evidence is
        refreshed at most every five seconds unless severity or signal changes,
        limiting SQLite writes during high-FPS streams.
        """
        from datetime import datetime, timezone

        timestamp = observed_at or datetime.now(timezone.utc).isoformat()
        try:
            observed_time = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except (AttributeError, ValueError) as exc:
            raise ValueError("Invalid live occupancy-alert timestamp.") from exc
        if observed_time.tzinfo is None:
            raise ValueError("Live occupancy-alert timestamps must include a timezone.")
        timestamp = observed_time.astimezone(timezone.utc).isoformat()

        clean_alerts: dict[str, tuple[Any, ...]] = {}
        for alert in alerts:
            alert_id = alert.get("alert_id")
            zone_id = alert.get("zone_id")
            zone = alert.get("zone", zone_id)
            severity = alert.get("severity")
            signal = alert.get("signal")
            evidence = alert.get("supporting_evidence")
            recommendation = alert.get("recommendation")
            if (
                not isinstance(alert_id, str) or not alert_id
                or not isinstance(zone_id, str) or not zone_id
                or not isinstance(zone, str) or not zone
                or severity not in {"WATCH", "WARNING", "CRITICAL"}
                or not isinstance(signal, str) or not signal
                or not isinstance(evidence, list)
                or not isinstance(recommendation, str) or not recommendation
                or alert_id in clean_alerts
            ):
                raise ValueError("Invalid live occupancy alert.")
            try:
                evidence_json = json.dumps(evidence, separators=(",", ":"), allow_nan=False)
            except (TypeError, ValueError) as exc:
                raise ValueError("Invalid live occupancy alert evidence.") from exc
            clean_alerts[alert_id] = (zone_id, zone, severity, signal, evidence_json, recommendation)

        with self._connection() as connection:
            active_rows = connection.execute(
                """SELECT episode_id, alert_id FROM live_occupancy_alert_episodes
                   WHERE session_id = ? AND status = 'active'""",
                (session_id,),
            ).fetchall()
            for row in active_rows:
                if row["alert_id"] not in clean_alerts:
                    connection.execute(
                        """UPDATE live_occupancy_alert_episodes
                           SET status = 'resolved', ended_at = ?
                           WHERE episode_id = ? AND status = 'active'""",
                        (timestamp, row["episode_id"]),
                    )

            for alert_id, (zone_id, zone, severity, signal, evidence_json, recommendation) in clean_alerts.items():
                existing = connection.execute(
                    """SELECT episode_id, last_seen_at, severity, signal
                       FROM live_occupancy_alert_episodes
                       WHERE session_id = ? AND alert_id = ? AND status = 'active'""",
                    (session_id, alert_id),
                ).fetchone()
                if existing is None:
                    connection.execute(
                        """INSERT INTO live_occupancy_alert_episodes
                           (episode_id, session_id, alert_id, zone_id, zone, first_seen_at,
                            last_seen_at, severity, signal, supporting_evidence_json,
                            recommendation, status)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')""",
                        (
                            str(uuid.uuid4()), session_id, alert_id, zone_id, zone, timestamp,
                            timestamp, severity, signal, evidence_json, recommendation,
                        ),
                    )
                    continue

                try:
                    last_seen = datetime.fromisoformat(existing["last_seen_at"])
                    refresh_evidence = (observed_time - last_seen).total_seconds() >= 5
                except ValueError:
                    refresh_evidence = True
                changed = existing["severity"] != severity or existing["signal"] != signal
                if refresh_evidence or changed:
                    connection.execute(
                        """UPDATE live_occupancy_alert_episodes
                           SET last_seen_at = ?, zone = ?, severity = ?, signal = ?,
                               supporting_evidence_json = ?, recommendation = ?
                           WHERE episode_id = ? AND status = 'active'""",
                        (timestamp, zone, severity, signal, evidence_json, recommendation, existing["episode_id"]),
                    )

    def get_live_occupancy_alerts(self, session_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        """Read recent alert episodes without retaining frames or track IDs."""
        if not 1 <= limit <= 500:
            raise ValueError("Live occupancy-alert limit must be between 1 and 500.")
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT * FROM live_occupancy_alert_episodes
                   WHERE session_id = ? ORDER BY first_seen_at DESC LIMIT ?""",
                (session_id, limit),
            ).fetchall()
        result = []
        for row in rows:
            alert = dict(row)
            alert["supporting_evidence"] = json.loads(alert.pop("supporting_evidence_json"))
            result.append(alert)
        return result

    def create_live_session(self, session_id: str) -> None:
        """Persist the start of a live stream without recording image data."""
        started_at = datetime.now(timezone.utc).isoformat()
        with self._connection() as connection:
            connection.execute(
                """INSERT INTO live_sessions (session_id, started_at, status)
                   VALUES (?, ?, 'connecting')""",
                (session_id, started_at),
            )

    def finish_live_session(
        self,
        session_id: str,
        *,
        status: str,
        summary: dict[str, Any],
    ) -> None:
        """Store aggregate session metrics and end status, never track IDs."""
        if status not in {"disconnected", "failed"}:
            raise ValueError("Unsupported live-session final status.")
        ended_at = datetime.now(timezone.utc).isoformat()
        with self._connection() as connection:
            cursor = connection.execute(
                """UPDATE live_sessions SET ended_at = ?, status = ?, summary_json = ?
                   WHERE session_id = ? AND ended_at IS NULL""",
                (ended_at, status, json.dumps(summary, separators=(",", ":")), session_id),
            )
            if cursor.rowcount != 1:
                raise SessionNotFoundError(session_id)
            connection.execute(
                """UPDATE live_occupancy_alert_episodes
                   SET status = 'session_ended', ended_at = ?
                   WHERE session_id = ? AND status = 'active'""",
                (ended_at, session_id),
            )

    def get_live_session(self, session_id: str) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM live_sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        summary_json = result.pop("summary_json")
        result["summary"] = json.loads(summary_json) if summary_json else None
        return result

    def list_live_sessions(self, *, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT * FROM live_sessions ORDER BY started_at DESC LIMIT ? OFFSET ?""",
                (limit, offset),
            ).fetchall()
        result = []
        for row in rows:
            session = dict(row)
            summary_json = session.pop("summary_json")
            session["summary"] = json.loads(summary_json) if summary_json else None
            result.append(session)
        return result

    def delete_live_session(self, session_id: str) -> bool:
        with self._connection() as connection:
            cursor = connection.execute(
                "DELETE FROM live_sessions WHERE session_id = ?", (session_id,)
            )
        return cursor.rowcount == 1

    def create_session(
        self,
        *,
        video_id: str,
        filename: str,
        stored_filename: str,
        content_type: str,
        size_bytes: int,
        metadata: dict[str, Any],
    ) -> None:
        created_at = datetime.now(timezone.utc).isoformat()
        with self._connection() as connection:
            connection.execute(
                """INSERT INTO sessions
                   (video_id, filename, stored_filename, content_type, size_bytes,
                    metadata_json, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'uploaded', ?)""",
                (
                    video_id, filename, stored_filename, content_type, size_bytes,
                    json.dumps(metadata, separators=(",", ":")), created_at,
                ),
            )

    def set_status(self, video_id: str, status: str) -> None:
        if status not in {"uploaded", "analyzing", "error"}:
            raise ValueError("Unsupported session status transition.")
        with self._connection() as connection:
            cursor = connection.execute(
                "UPDATE sessions SET status = ? WHERE video_id = ?",
                (status, video_id),
            )
            if cursor.rowcount != 1:
                raise SessionNotFoundError(video_id)

    def save_completed(
        self,
        video_id: str,
        summary: dict[str, Any],
        temporal: dict[str, Any],
        spatial: dict[str, Any],
        events_path: Path,
    ) -> None:
        completed_at = datetime.now(timezone.utc).isoformat()
        with self._connection() as connection:
            cursor = connection.execute(
                """UPDATE sessions SET
                    status = 'completed', completed_at = ?, model = ?, device = ?,
                    confidence_threshold = ?, frames_processed = ?, total_frames = ?,
                    total_detection_instances = ?, total_events = ?,
                    processing_time_seconds = ?, processing_fps = ?, zones_configured = ?,
                    summary_json = ?, temporal_summary_json = ?, spatial_summary_json = ?
                   WHERE video_id = ?""",
                (
                    completed_at,
                    summary["model"],
                    summary["device"],
                    summary["confidence_threshold"],
                    summary["frames_processed"],
                    summary["total_frames"],
                    summary["total_detection_instances"],
                    summary["total_events"],
                    summary["processing_time_seconds"],
                    summary["processing_fps"],
                    summary["zones_configured"],
                    json.dumps(summary, separators=(",", ":")),
                    json.dumps(temporal, separators=(",", ":")),
                    json.dumps(spatial, separators=(",", ":")),
                    video_id,
                ),
            )
            if cursor.rowcount != 1:
                raise SessionNotFoundError(video_id)

            connection.execute("DELETE FROM events WHERE video_id = ?", (video_id,))
            connection.execute("DELETE FROM measurements WHERE video_id = ?", (video_id,))
            connection.execute("DELETE FROM zone_measurements WHERE video_id = ?", (video_id,))
            connection.execute("DELETE FROM occupancy_observations WHERE video_id = ?", (video_id,))

            batch: list[tuple[Any, ...]] = []
            with events_path.open("r", encoding="utf-8") as records:
                for line in records:
                    event = json.loads(line)
                    batch.append((
                        event["event_id"], video_id, event["timestamp_seconds"],
                        event["event_type"], event["object_class"], event["count"],
                        event["confidence"], event.get("zone_id"), event.get("zone_name"),
                        json.dumps(event.get("metadata", {}), separators=(",", ":")),
                    ))
                    if len(batch) >= 500:
                        self._insert_events(connection, batch)
                        batch.clear()
            if batch:
                self._insert_events(connection, batch)

            bucket_seconds = temporal["aggregation"]["bucket_seconds"]
            for bucket in temporal["aggregation"]["timeline"]:
                connection.execute(
                    """INSERT INTO measurements
                       (video_id, bucket_start_seconds, bucket_end_seconds, bucket_seconds,
                        observed_frames, detection_instances, average_instances_per_observed_frame,
                        counts_by_class_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        video_id, bucket["bucket_start_seconds"], bucket["bucket_end_seconds"],
                        bucket_seconds, bucket["observed_frames"], bucket["detection_instances"],
                        bucket["average_instances_per_observed_frame"],
                        json.dumps(bucket["counts_by_class"], separators=(",", ":")),
                    ),
                )

            for zone in spatial["zones"]:
                for bucket in zone["timeline"]:
                    connection.execute(
                        """INSERT INTO zone_measurements
                           (video_id, zone_id, zone_name, bucket_start_seconds, bucket_end_seconds,
                            observed_frames, event_count, detection_instances, counts_by_class_json)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            video_id, zone["zone_id"], zone["name"],
                            bucket["bucket_start_seconds"], bucket["bucket_end_seconds"],
                            bucket["observed_frames"], bucket["event_count"],
                            bucket["detection_instances"],
                            json.dumps(bucket["counts_by_class"], separators=(",", ":")),
                        ),
                    )

            for zone in spatial["zones"]:
                occupancy = zone.get("occupancy") or {}
                capacity = occupancy.get("configured_capacity")
                for bucket in occupancy.get("timeline", []):
                    estimate = bucket.get("estimated_mean_visible_people")
                    if estimate is None:
                        continue
                    thresholds = occupancy.get("status_thresholds")
                    capacity_status, ratio = classify_capacity(estimate, capacity, thresholds)
                    connection.execute(
                        """INSERT INTO occupancy_observations
                           (video_id, zone_id, bucket_start_seconds, bucket_end_seconds,
                            estimated_mean_visible_people, configured_capacity, capacity_ratio, capacity_status)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            video_id, zone["zone_id"], bucket["bucket_start_seconds"], bucket["bucket_end_seconds"],
                            estimate, capacity, ratio, capacity_status,
                        ),
                    )

    @staticmethod
    def _insert_events(connection: sqlite3.Connection, batch: list[tuple[Any, ...]]) -> None:
        connection.executemany(
            """INSERT INTO events
               (event_id, video_id, timestamp_seconds, event_type, object_class, count,
                confidence, zone_id, zone_name, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            batch,
        )

    def delete_session(self, video_id: str) -> None:
        with self._connection() as connection:
            connection.execute("DELETE FROM sessions WHERE video_id = ?", (video_id,))

    @staticmethod
    def _decode_session(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        session = dict(row)
        for field in ("metadata_json", "summary_json", "temporal_summary_json", "spatial_summary_json"):
            value = session.pop(field)
            key = field.removesuffix("_json")
            session[key] = json.loads(value) if value else None
        return session

    def get_session(self, video_id: str) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM sessions WHERE video_id = ?", (video_id,)
            ).fetchone()
        return self._decode_session(row)

    def list_completed_summaries(self, limit: int = 100) -> list[dict[str, Any]]:
        """Load a bounded set of completed sessions for pattern analysis."""
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT video_id, filename, created_at, summary_json,
                          spatial_summary_json
                   FROM sessions WHERE status = 'completed'
                   ORDER BY created_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [
            {
                "video_id": row["video_id"],
                "filename": row["filename"],
                "created_at": row["created_at"],
                "summary": json.loads(row["summary_json"]) if row["summary_json"] else None,
                "spatial_summary": json.loads(row["spatial_summary_json"])
                if row["spatial_summary_json"] else None,
            }
            for row in rows
        ]

    def list_sessions(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        start_at: str | None = None,
        end_at: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses = []
        parameters: list[Any] = []
        if start_at:
            clauses.append("created_at >= ?")
            parameters.append(start_at)
        if end_at:
            clauses.append("created_at <= ?")
            parameters.append(end_at)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        parameters.extend((limit, offset))
        with self._connection() as connection:
            rows = connection.execute(
                f"""SELECT video_id, filename, stored_filename, content_type, size_bytes,
                          metadata_json, status, created_at, completed_at, model, device,
                          frames_processed, total_frames, total_detection_instances,
                          total_events, processing_time_seconds, processing_fps, zones_configured
                   FROM sessions {where} ORDER BY created_at DESC LIMIT ? OFFSET ?""",
                parameters,
            ).fetchall()
        sessions = []
        for row in rows:
            session = dict(row)
            session["metadata"] = json.loads(session.pop("metadata_json"))
            sessions.append(session)
        return sessions

    def get_events(self, video_id: str, *, limit: int, offset: int) -> tuple[list[dict[str, Any]], bool]:
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT * FROM events WHERE video_id = ?
                   ORDER BY timestamp_seconds, event_id LIMIT ? OFFSET ?""",
                (video_id, limit + 1, offset),
            ).fetchall()
        page = [dict(row) for row in rows[:limit]]
        for event in page:
            event["metadata"] = json.loads(event.pop("metadata_json"))
            event.pop("video_id")
        return page, len(rows) > limit

    def get_activity(
        self, video_id: str, *, start_seconds: float | None, end_seconds: float | None
    ) -> list[dict[str, Any]]:
        clauses = ["video_id = ?"]
        parameters: list[Any] = [video_id]
        if start_seconds is not None:
            clauses.append("bucket_end_seconds > ?")
            parameters.append(start_seconds)
        if end_seconds is not None:
            clauses.append("bucket_start_seconds < ?")
            parameters.append(end_seconds)
        with self._connection() as connection:
            rows = connection.execute(
                f"SELECT * FROM measurements WHERE {' AND '.join(clauses)} ORDER BY bucket_start_seconds",
                parameters,
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["counts_by_class"] = json.loads(item.pop("counts_by_class_json"))
            result.append(item)
        return result

    def get_zone_activity(
        self, video_id: str, *, start_seconds: float | None, end_seconds: float | None
    ) -> list[dict[str, Any]]:
        clauses = ["video_id = ?"]
        parameters: list[Any] = [video_id]
        if start_seconds is not None:
            clauses.append("bucket_end_seconds > ?")
            parameters.append(start_seconds)
        if end_seconds is not None:
            clauses.append("bucket_start_seconds < ?")
            parameters.append(end_seconds)
        with self._connection() as connection:
            rows = connection.execute(
                f"""SELECT * FROM zone_measurements WHERE {' AND '.join(clauses)}
                    ORDER BY zone_name, bucket_start_seconds""",
                parameters,
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["counts_by_class"] = json.loads(item.pop("counts_by_class_json"))
            result.append(item)
        return result

    def get_zone_occupancy(
        self,
        video_id: str,
        zone_id: str,
        *,
        start_seconds: float | None,
        end_seconds: float | None,
    ) -> list[dict[str, Any]]:
        clauses = ["video_id = ?", "zone_id = ?"]
        parameters: list[Any] = [video_id, zone_id]
        if start_seconds is not None:
            clauses.append("bucket_end_seconds > ?")
            parameters.append(start_seconds)
        if end_seconds is not None:
            clauses.append("bucket_start_seconds < ?")
            parameters.append(end_seconds)
        with self._connection() as connection:
            rows = connection.execute(
                f"""SELECT * FROM occupancy_observations WHERE {' AND '.join(clauses)}
                    ORDER BY bucket_start_seconds""",
                parameters,
            ).fetchall()
        return [dict(row) for row in rows]
