"""Conservative recurring-pattern summaries from stored sessions."""

import math
from collections import defaultdict
from typing import Any

MINIMUM_SESSIONS = 3
MINIMUM_CLASS_SESSION_SHARE = 0.6
MINIMUM_ZONE_TOP_SHARE = 2 / 3


def discover_patterns(sessions: list[dict[str, Any]]) -> dict[str, Any]:
    """Report only repeated observations with explicit supporting sessions."""
    completed = [
        session for session in sessions
        if session.get("summary") is not None and session.get("spatial_summary") is not None
    ]
    if len(completed) < MINIMUM_SESSIONS:
        return {
            "data_kind": "historical_pattern_analysis",
            "observation_source": "completed_sessions",
            "session_count": len(completed),
            "minimum_sessions": MINIMUM_SESSIONS,
            "patterns": [],
            "message": "Insufficient historical data for reliable pattern analysis.",
        }

    patterns: list[dict[str, Any]] = []
    session_count = len(completed)

    class_sessions: dict[str, list[str]] = defaultdict(list)
    for session in completed:
        for object_class, count in (session["summary"].get("detection_instances_by_class") or {}).items():
            if count > 0:
                class_sessions[object_class].append(session["video_id"])

    minimum_class_sessions = math.ceil(MINIMUM_CLASS_SESSION_SHARE * session_count)
    for object_class, supporting_sessions in sorted(
        class_sessions.items(), key=lambda item: (-len(item[1]), item[0])
    ):
        if len(supporting_sessions) >= minimum_class_sessions:
            patterns.append({
                "pattern_type": "recurring_object_class",
                "description": (
                    f"{object_class} appeared in detections in {len(supporting_sessions)} "
                    f"of {session_count} completed sessions."
                ),
                "supporting_sessions": len(supporting_sessions),
                "session_count": session_count,
                "supporting_video_ids": supporting_sessions,
            })

    top_zone_sessions: dict[str, list[dict[str, Any]]] = defaultdict(list)
    zone_definitions: dict[str, str] = {}
    zone_names: dict[str, set[str]] = defaultdict(set)
    sessions_with_zone_observations = 0
    for session in completed:
        zones = session["spatial_summary"].get("zones") or []
        zone_counts = []
        for zone in zones:
            zone_id = zone.get("zone_id")
            zone_name = zone.get("name")
            if not zone_id or not zone_name:
                continue
            zone_definitions[zone_id] = zone_name
            zone_names[zone_id].add(zone_name)
            count = int(zone.get("detection_instances", 0))
            zone_counts.append((zone_id, zone_name, count))
        total = sum(item[2] for item in zone_counts)
        if total <= 0:
            continue
        sessions_with_zone_observations += 1
        top_zone_id, top_zone_name, top_count = sorted(
            zone_counts, key=lambda item: (-item[2], item[1].casefold(), item[0])
        )[0]
        top_zone_sessions[top_zone_id].append({
            "video_id": session["video_id"],
            "zone_name": top_zone_name,
            "detection_instances": top_count,
            "share_percent": round(top_count * 100 / total, 2),
        })

    for zone_id, evidence in sorted(
        top_zone_sessions.items(), key=lambda item: (-len(item[1]), zone_definitions[item[0]].casefold())
    ):
        required = math.ceil(MINIMUM_ZONE_TOP_SHARE * sessions_with_zone_observations)
        if (
            sessions_with_zone_observations >= MINIMUM_SESSIONS
            and len(zone_names[zone_id]) == 1
            and len(evidence) >= required
        ):
            zone_name = zone_definitions[zone_id]
            patterns.append({
                "pattern_type": "recurrent_zone_activity",
                "description": (
                    f"{zone_name} had the highest observed zone activity in {len(evidence)} "
                    f"of {sessions_with_zone_observations} sessions with zone detections."
                ),
                "zone_id": zone_id,
                "supporting_sessions": len(evidence),
                "session_count": sessions_with_zone_observations,
                "evidence": evidence,
            })

    return {
        "data_kind": "historical_pattern_analysis",
        "observation_source": "completed_sessions",
        "session_count": session_count,
        "minimum_sessions": MINIMUM_SESSIONS,
        "patterns": patterns,
        "message": None if patterns else "No recurring patterns met the evidence threshold.",
    }
