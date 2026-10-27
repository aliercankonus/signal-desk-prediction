# 07 — Model Comparison

## Initial candidates

| Model | Role |
| --- | --- |
| No-change / midpoint | Reference |
| Simple momentum | Reference |
| Logistic regression | Direction probability |
| Micro-Price | Short-term price reference |
| Small CatBoost | Nonlinear candidate; train outside the VPS |

## Rules

- Use the same data period, feature snapshots and cost assumptions.
- An uncalibrated score is not a probability.
- One-minute and five-minute targets are separate.
- Event-level Micro-Price output is not directly a 1/5-minute success rate.
- An ensemble is not the default.
- Select models on validation; run the final test once.
- Reject negative strategies/models when appropriate; do not rescue them by tuning on the same final test.

## Data split

The proposed research window is 60 days. The 100 GB profile may not support full
raw replay. Feature/label datasets may be retained longer, but fill/replay claims
require supporting raw detail.

## Required manifest

`model_manifest.schema.json` is mandatory:

- Model ID/version.
- Training/validation/final windows.
- Feature version.
- Label definition.
- Calibration method.
- Cost assumptions.
- Metrics: accuracy, Brier, log-loss, calibration bins, net expectancy, coverage, max drawdown, trade count.
- Artifact hash.
