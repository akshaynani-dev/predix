"""Measure visible-person occupancy estimation error against labeled tracks."""

import argparse
import json
import math
from pathlib import Path
from typing import Any


def _load(path: Path, *, ground_truth: bool) -> dict[int, int]:
    frames: dict[int, int] = {}
    with path.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            try:
                row = json.loads(line)
                frame = int(row["frame_number"])
                if frame < 1 or frame in frames:
                    raise ValueError
                if ground_truth:
                    people = [d for d in row["detections"] if d["class"] == "person"]
                    ids = [str(d["track_id"]) for d in people]
                    if any(not value or value == "None" for value in ids):
                        raise ValueError
                    frames[frame] = len(set(ids))
                else:
                    occupancy = row["occupancy"]
                    if occupancy.get("data_kind") not in {
                        "estimated_visible_people", "estimated_active_person_tracks",
                    }:
                        raise ValueError
                    count = int(occupancy["count"])
                    if count < 0:
                        raise ValueError
                    frames[frame] = count
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError(f"Invalid {'ground-truth' if ground_truth else 'prediction'} record at line {line_number}.") from exc
    return frames


def evaluate_occupancy(ground_truth_path: Path, predictions_path: Path) -> dict[str, Any]:
    """Return MAE, RMSE, signed bias and non-zero-only MAPE for aligned frames."""
    truth = _load(ground_truth_path, ground_truth=True)
    predictions = _load(predictions_path, ground_truth=False)
    if set(truth) != set(predictions):
        raise ValueError("Ground-truth and prediction files must contain the same evaluated frame numbers.")
    if not truth:
        return {"metric": "visible_person_occupancy_estimation", "status": "insufficient_data", "frames": 0}
    errors = [predictions[frame] - actual for frame, actual in truth.items()]
    absolute = [abs(error) for error in errors]
    nonzero_percentage_errors = [
        abs(predictions[frame] - actual) / actual
        for frame, actual in truth.items() if actual > 0
    ]
    return {
        "metric": "visible_person_occupancy_estimation",
        "status": "available",
        "frames": len(truth),
        "mae_people": round(sum(absolute) / len(absolute), 4),
        "rmse_people": round(math.sqrt(sum(error * error for error in errors) / len(errors)), 4),
        "bias_people": round(sum(errors) / len(errors), 4),
        "mape_percent_nonzero_ground_truth": round(100 * sum(nonzero_percentage_errors) / len(nonzero_percentage_errors), 4) if nonzero_percentage_errors else None,
        "mape_excluded_zero_ground_truth_frames": len(truth) - len(nonzero_percentage_errors),
        "ground_truth_basis": "distinct labeled person track IDs per frame",
        "limitations": "Metrics measure visible-person estimation on labeled frames, not unique people across a clip. Ground-truth identity consistency and representative occlusion/camera conditions are required.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate PREDIX visible-person estimates against labeled track IDs.")
    parser.add_argument("ground_truth", type=Path)
    parser.add_argument("predictions", type=Path)
    args = parser.parse_args()
    print(json.dumps(evaluate_occupancy(args.ground_truth, args.predictions), indent=2))
