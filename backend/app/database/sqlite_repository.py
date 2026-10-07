"""SQLite implementation for persisted sessions, events, and aggregates."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


class SessionNotFoundError(LookupError):
    """Raised when a result is saved for a missing uploaded session."""


class SQLiteRepository:
    """Small repository boundary that keeps SQL out of API and CV services."""

    def __init__(self, database_path: Path):
        self.database_path = Path(database_path)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

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
                """
            )

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
