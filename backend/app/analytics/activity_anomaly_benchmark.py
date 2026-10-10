"""Evaluate detector-activity deviation signals against labeled session buckets."""

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

from app.analytics.anomalies import detect_activity_deviations


def _read_labeled_buckets(path: Path, bucket_seconds: int) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen: set[tuple[str, int]] = set()
    try:
        source = path.open(encoding="utf-8")
    except OSError as exc:
        raise ValueError("Could not open the labeled activity data file.") from exc

    try:
        with source:
            for line_number, line in enumerate(source, start=1):
                try:
                    row = json.loads(line)
                    session_id = row["session_id"]
                    bucket_start = row["bucket_start_seconds"]
                    value = row["detector_instances_per_frame"]
                    label = row["anomaly"]
                    if (
                        not isinstance(session_id, str) or not session_id.strip()
                        or isinstance(bucket_start, bool) or not isinstance(bucket_start, (int, float))
                        or not math.isfinite(bucket_start) or bucket_start < 0
                        or bucket_start % bucket_seconds != 0
                        or isinstance(value, bool) or not isinstance(value, (int, float))
                        or not math.isfinite(value) or value < 0
                        or type(label) is not bool
                    ):
                        raise ValueError
                    bucket_start = int(bucket_start)
                    identity = (session_id, bucket_start)
                    if identity in seen:
                        raise ValueError
                    seen.add(identity)
                    groups[session_id].append({
                        "bucket_start_seconds": bucket_start,
                        "observed_frames": 1,
                        "average_instances_per_observed_frame": float(value),
                        "anomaly": label,
                    })
                except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                    raise ValueError(f"Invalid labeled activity record at line {line_number}.") from exc
    except OSError as exc:
        raise ValueError("Could not read the labeled activity data file.") from exc

    for session_id, rows in groups.items():
        rows.sort(key=lambda row: row["bucket_start_seconds"])
        times = [row["bucket_start_seconds"] for row in rows]
        if any(later - earlier != bucket_seconds for earlier, later in zip(times, times[1:])):
            raise ValueError(f"Labeled buckets for session {session_id!r} must be continuous.")
    return groups


def evaluate_activity_anomalies(
    labels_path: Path,
    *,
    bucket_seconds: int = 15,
    baseline_buckets: int = 6,
    mad_multiplier: float = 3.0,
    minimum_increase: float = 1.0,
) -> dict[str, Any]:
    """Report bucket classification metrics using only earlier session buckets."""
    if bucket_seconds < 1 or baseline_buckets < 2:
        raise ValueError("bucket_seconds must be positive and baseline_buckets must be at least two.")
    if not math.isfinite(mad_multiplier) or mad_multiplier <= 0:
        raise ValueError("mad_multiplier must be finite and positive.")
    if not math.isfinite(minimum_increase) or minimum_increase < 0:
        raise ValueError("minimum_increase must be finite and non-negative.")

    groups = _read_labeled_buckets(labels_path, bucket_seconds)
    true_positive = false_positive = true_negative = false_negative = 0
    evaluated = excluded_warmup = 0

    for rows in groups.values():
        history: list[dict[str, Any]] = []
        for row in rows:
            history.append(row)
            if len(history) <= baseline_buckets:
                excluded_warmup += 1
                continue
            signal = detect_activity_deviations(
                history,
                bucket_seconds=bucket_seconds,
                baseline_buckets=baseline_buckets,
                mad_multiplier=mad_multiplier,
                minimum_increase=minimum_increase,
            )
            latest = signal.get("latest_signal")
            predicted = bool(
                latest and latest["bucket_start_seconds"] == row["bucket_start_seconds"]
            )
            actual = row["anomaly"]
            evaluated += 1
            if predicted and actual:
                true_positive += 1
            elif predicted:
                false_positive += 1
            elif actual:
                false_negative += 1
            else:
                true_negative += 1

    if not evaluated:
        return {
            "metric": "detector_activity_deviation_evaluation",
            "status": "insufficient_data",
            "groups": len(groups),
            "evaluated_buckets": 0,
            "excluded_warmup_buckets": excluded_warmup,
            "required_history_buckets_per_group": baseline_buckets + 1,
        }

    predicted_positive = true_positive + false_positive
    actual_positive = true_positive + false_negative
    actual_negative = true_negative + false_positive
    precision = true_positive / predicted_positive if predicted_positive else None
    recall = true_positive / actual_positive if actual_positive else None
    f1_denominator = 2 * true_positive + false_positive + false_negative
    f1 = 2 * true_positive / f1_denominator if f1_denominator else None
    specificity = true_negative / actual_negative if actual_negative else None
    return {
        "metric": "detector_activity_deviation_evaluation",
        "status": "available",
        "groups": len(groups),
        "evaluated_buckets": evaluated,
        "excluded_warmup_buckets": excluded_warmup,
        "bucket_seconds": bucket_seconds,
        "baseline_buckets": baseline_buckets,
        "mad_multiplier": mad_multiplier,
        "minimum_increase": minimum_increase,
        "confusion_matrix": {
            "true_positive": true_positive,
            "false_positive": false_positive,
            "true_negative": true_negative,
            "false_negative": false_negative,
        },
        "precision": round(precision, 4) if precision is not None else None,
        "recall": round(recall, 4) if recall is not None else None,
        "f1": round(f1, 4) if f1 is not None else None,
        "specificity": round(specificity, 4) if specificity is not None else None,
        "limitations": "Labels define detector-activity deviations, not incidents or occupancy. Predictions at each bucket use only earlier session observations. Results measure agreement with the supplied labels and do not establish incident-risk performance or guaranteed future behavior.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate detector-activity deviation against labeled session buckets.")
    parser.add_argument("labels", type=Path, help="JSONL with session_id, bucket_start_seconds, detector_instances_per_frame, and boolean anomaly.")
    parser.add_argument("--bucket-seconds", type=int, default=15)
    parser.add_argument("--baseline-buckets", type=int, default=6)
    parser.add_argument("--mad-multiplier", type=float, default=3.0)
    parser.add_argument("--minimum-increase", type=float, default=1.0)
    args = parser.parse_args()
    try:
        result = evaluate_activity_anomalies(
            args.labels,
            bucket_seconds=args.bucket_seconds,
            baseline_buckets=args.baseline_buckets,
            mad_multiplier=args.mad_multiplier,
            minimum_increase=args.minimum_increase,
        )
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
