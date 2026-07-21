# Established Regime Weakness Fade — Stage 1

## Decision

`ESTABLISHED_REGIME_FILTER_FOUND`

Stage 2 is authorized by the predeclared gate.

## Key cohort contrast

| split_value   | cohort_label       |   count |   pct_population |   median_duration_s |   median_final_flip_pnl_atr |   median_peak_mfe_atr |   median_new_progress_windows |   median_retained_m60 |   median_giveback_atr |   median_w4_m60 |   median_w4_m30 |   median_w4_flip |
|:--------------|:-------------------|--------:|-----------------:|--------------------:|----------------------------:|----------------------:|------------------------------:|----------------------:|----------------------:|----------------:|----------------:|-----------------:|
| train         | all                |  110499 |            1.000 |             540.000 |                      -0.796 |                 1.379 |                         1.000 |                 0.193 |                 2.145 |           0.354 |           0.434 |            0.593 |
| train         | mfe>=1 & flip<0.5  |   36583 |            0.331 |             600.000 |                      -0.569 |                 1.754 |                         2.000 |                 0.222 |                 2.420 |           0.353 |           0.428 |            0.603 |
| train         | mfe>=1 & flip>=0.5 |   28789 |            0.261 |            1380.000 |                       2.128 |                 4.744 |                         3.000 |                 0.679 |                 2.409 |           0.333 |           0.395 |            0.538 |
| train         | mfe<1              |   45127 |            0.408 |             300.000 |                      -1.443 |                 0.382 |                         1.000 |                -1.200 |                 1.833 |           0.363 |           0.451 |            0.605 |
| validation    | all                |   27165 |            1.000 |             600.000 |                      -0.765 |                 1.396 |                         1.000 |                 0.217 |                 2.136 |           0.414 |           0.561 |            0.700 |
| validation    | mfe>=1 & flip<0.5  |    9156 |            0.337 |             600.000 |                      -0.551 |                 1.737 |                         2.000 |                 0.242 |                 2.404 |           0.393 |           0.557 |            0.686 |
| validation    | mfe>=1 & flip>=0.5 |    7147 |            0.263 |            1380.000 |                       2.119 |                 4.713 |                         3.000 |                 0.691 |                 2.416 |           0.355 |           0.495 |            0.625 |
| validation    | mfe<1              |   10862 |            0.400 |             300.000 |                      -1.447 |                 0.391 |                         1.000 |                -1.200 |                 1.841 |           0.448 |           0.581 |            0.729 |

## Gate — 2021–2024 discovery

```json
{
  "period": "train",
  "winner_count": 28789,
  "failed_runner_count": 36583,
  "duration_ratio": 2.3,
  "peak_mfe_ratio": 2.704269864421758,
  "progress_windows_delta": 1.0,
  "retained_m60_delta": 0.45667686034658517,
  "winner_w4_rise_m60_to_flip": 0.13280380402602654,
  "winner_w4_rise_paired_n": 20551,
  "winner_w4_rise_paired_fraction": 0.7138490395637223,
  "winner_peak_to_flip_s": 347.0,
  "winner_giveback_atr": 2.40885739704602,
  "structural_conditions": {
    "duration": true,
    "peak_mfe": true,
    "progress_windows": true,
    "retention_m60": true
  },
  "structural_pass_count": 4,
  "sample_pass": true,
  "weakness_window_pass": true,
  "pass": true
}
```

## Gate — 2025 sanity check

```json
{
  "period": "validation",
  "winner_count": 7147,
  "failed_runner_count": 9156,
  "duration_ratio": 2.3,
  "peak_mfe_ratio": 2.7126021864314644,
  "progress_windows_delta": 1.0,
  "retained_m60_delta": 0.44906222809448604,
  "winner_w4_rise_m60_to_flip": 0.20088705213641367,
  "winner_w4_rise_paired_n": 5042,
  "winner_w4_rise_paired_fraction": 0.7054708269203862,
  "winner_peak_to_flip_s": 316.0,
  "winner_giveback_atr": 2.416413423384879,
  "structural_conditions": {
    "duration": true,
    "peak_mfe": true,
    "progress_windows": true,
    "retention_m60": true
  },
  "structural_pass_count": 4,
  "sample_pass": true,
  "weakness_window_pass": true,
  "pass": true
}
```

## Interpretation limits

- Cohorts use final flip PnL and peak MFE only as retrospective descriptive labels; they are not live filters.
- W4 values are attached from the last checkpoint whose availability time is at or before each target (observation T plus one second).
- W4 was fit on 2021–2024, so discovery-period W4 contrasts are in-sample. The 2025 gate is the out-of-sample sanity check.
- W4 coverage ends at regime age 1,800 seconds. A score is considered "at" a target only when its availability is within one native checkpoint interval (30 seconds in 2021–2024; 5 seconds in 2025), so stale capped scores are reported unavailable.
- No 2026 row is scored, characterized, or summarized in Stage 1. The untouched test remains sealed unless Stage 2 is fully specified and frozen.
