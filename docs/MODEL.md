# Model and Predictive Intelligence

## Object detection

PREDIX uses the configurable Ultralytics detector from `backend/app/cv/`. Defaults use `yolo11n.pt`, confidence `0.25`, image size `640`, frame stride `1`, and device `auto`. Automatic device selection prefers Apple MPS when available and falls back to CPU. `MODEL_NAME`, `DEFAULT_CONF_THRESHOLD`, `DEFAULT_IMAGE_SIZE`, `FRAME_STRIDE`, and `DEVICE` can be set in `backend/.env`. Weights are downloaded/loaded locally by Ultralytics; they are not stored in Git.

This is pretrained general object detection. PREDIX does not fine-tune on campus data and does not provide a project-specific accuracy claim. Detection instances across frames are not unique-object counts. The model's confidence is detector output, not the probability that an operational event will occur.

## Pattern discovery

Pattern rules operate on completed sessions and include supporting evidence. Current rules require repeated class presence or a recurring, consistently named configured zone. Fewer than three completed sessions produces the explicit insufficient-history result. The rules describe observations; they do not extrapolate future events.

## Forecast and evaluation

The current forecast target is `object_instances_per_sampled_frame` for the next compatible uploaded session. The model is a trailing mean over the previous three sessions. Sessions are grouped by model, confidence threshold, frame stride, and image size. At least six compatible sessions are required, yielding at least three rolling-origin test windows. The frontend/API exposes MAE, MSE, RMSE, and R² when defined. The displayed estimated range is forecast ± rolling-origin MAE, not a calibrated probability interval.

This baseline is intentionally simple and interpretable. It is not validated for different sites, camera setups, time schedules, or deployment populations. Re-evaluate with representative data before operational use; no forecast should be treated as certainty.

## Decision support

When the forecast is available and exceeds the compatible historical activity-rate 75th percentile, the API suggests considering a resource-plan review and returns the forecast value, comparison threshold, and supporting session IDs. Otherwise, it returns no recommendation. It makes no incident, identity, risk, or guaranteed-outcome claim.
