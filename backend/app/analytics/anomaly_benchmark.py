"""Evaluate occupancy-deviation signals against explicitly labeled buckets."""

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

from app.analytics.anomalies import detect_occupancy_deviations


def _read_labeled_buckets(path: Path, bucket_seconds: int) -> dict[tuple[str, str], list[dict[str, Any]]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    seen: set[tuple[str, str, int]] = set()
    try:
        source = path.open(encoding="utf-8")
    except OSError as exc:
        raise ValueError("Could not open the labeled anomaly data file.") from exc

    try:
        with source:
            for line_number, line in enumerate(source, start=1):
                try:
                    row = json.loads(line)
                    session_id = row["session_id"]
                    zone_id = row["zone_id"]
                    bucket_start = row["bucket_start_seconds"]
                    occupancy = row["estimated_occupancy"]
                    label = row["anomaly"]
                    if (
                        not isinstance(session_id, str) or not session_id.strip()
                        or not isinstance(zone_id, str) or not zone_id.strip()
                        or isinstance(bucket_start, bool) or not isinstance(bucket_start, (int, float))
                        or not math.isfinite(bucket_start) or bucket_start < 0
                        or bucket_start % bucket_seconds != 0
                        or isinstance(occupancy, bool) or not isinstance(occupancy, (int, float))
                        or not math.isfinite(occupancy) or occupancy < 0
                        or type(label) is not bool
                    ):
                        raise ValueError
                    bucket_start = int(bucket_start)
                    identity = (session_id, zone_id, bucket_start)
                    if identity in seen:
                        raise ValueError
                    seen.add(identity)
                    groups[(session_id, zone_id)].append({
                        "bucket_start_seconds": bucket_start,
                        "estimated_occupancy": float(occupancy),
                        "anomaly": label,
                    })
                except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                    raise ValueError(f"Invalid labeled anomaly record at line {line_number}.") from exc
    except OSError as exc:
        raise ValueError("Could not read the labeled anomaly data file.") from exc

    for key, rows in groups.items():
        rows.sort(key=lambda row: row["bucket_start_seconds"])
        times = [row["bucket_start_seconds"] for row in rows]
        if any(later - earlier != bucket_seconds for earlier, later in zip(times, times[1:])):
            raise ValueError(f"Labeled buckets for session {key[0]!r}, zone {key[1]!r} must be continuous.")
    return groups


def evaluate_occupancy_anomalies(
    labels_path: Path,
    *,
    bucket_seconds: int = 15,
    baseline_buckets: int = 6,
    mad_multiplier: float = 3.0,
    minimum_increase: float = 1.0,
) -> dict[str, Any]:
    """Compute binary classification metrics using only each bucket's past data."""
    if bucket_seconds < 1:
        raise ValueError("bucket_seconds must be at least one.")
    if baseline_buckets < 2:
        raise ValueError("baseline_buckets must be at least two.")
    if not math.isfinite(mad_multiplier) or mad_multiplier <= 0:
        raise ValueError("mad_multiplier must be finite and positive.")
    if not math.isfinite(minimum_increase) or minimum_increase < 0:
        raise ValueError("minimum_increase must be finite and non-negative.")

    groups = _read_labeled_buckets(labels_path, bucket_seconds)
    true_positive = false_positive = true_negative = false_negative = 0
    evaluated = excluded_warmup = 0

    for rows in groups.values():
        history: list[float] = []
        for row in rows:
            history.append(row["estimated_occupancy"])
            if len(history) <= baseline_buckets:
                excluded_warmup += 1
                continue
            anomaly = detect_occupancy_deviations(
                history,
                baseline_buckets=baseline_buckets,
                mad_multiplier=mad_multiplier,
                minimum_increase=minimum_increase,
            )
            predicted = bool(
                anomaly.get("signals")
                and anomaly["signals"][-1]["bucket_index"] == len(history) - 1
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
            "metric": "occupancy_deviation_anomaly_evaluation",
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
        "metric": "occupancy_deviation_anomaly_evaluation",
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
        "limitations": "Labels must identify occupancy-deviation buckets using a predeclared definition. Predictions at each bucket use only the preceding occupancy observations. Excluded warmup buckets have no full baseline. Results measure this configured rule on the supplied labels; they are not incident-risk accuracy or a guarantee of future performance.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate occupancy-deviation signals against labeled zone buckets.")
    parser.add_argument("labels", type=Path, help="JSONL with session_id, zone_id, bucket_start_seconds, estimated_occupancy, and boolean anomaly.")
    parser.add_argument("--bucket-seconds", type=int, default=15)
    parser.add_argument("--baseline-buckets", type=int, default=6)
    parser.add_argument("--mad-multiplier", type=float, default=3.0)
    parser.add_argument("--minimum-increase", type=float, default=1.0)
    args = parser.parse_args()
    try:
        result = evaluate_occupancy_anomalies(
            args.labels,
            bucket_seconds=args.bucket_seconds,
            baseline_buckets=args.baseline_buckets,
            mad_multiplier=args.mad_multiplier,
            minimum_increase=args.minimum_increase,
        )
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2))
