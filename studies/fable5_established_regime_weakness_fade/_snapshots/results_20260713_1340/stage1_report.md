# Established Regime Weakness Fade — Stage 1

## Decision

`ESTABLISHED_REGIME_FILTER_FOUND`

Stage 2 is authorized by the predeclared gate.

## Key cohort contrast

| split_value   | cohort_label       |   count |   pct_population |   median_duration_s |   median_final_flip_pnl_atr |   median_peak_mfe_atr |   median_new_progress_windows |   median_retained_m60 |   median_giveback_atr |   median_w4_m60 |   median_w4_m30 |   median_w4_flip |
|:--------------|:-------------------|--------:|-----------------:|--------------------:|----------------------------:|----------------------:|------------------------------:|----------------------:|----------------------:|----------------:|----------------:|-----------------:|
| train         | all                |  110499 |            1.000 |             540.000 |                      -0.382 |                 1.291 |                         1.000 |                 0.130 |                 1.931 |           0.354 |           0.434 |            0.593 |
| train         | mfe>=1 & flip<0.5  |   28814 |            0.261 |             660.000 |                      -0.589 |                 1.692 |                         2.000 |                 0.174 |                 2.417 |           0.359 |           0.433 |            0.607 |
| train         | mfe>=1 & flip>=0.5 |   37112 |            0.336 |             900.000 |                       1.634 |                 3.045 |                         2.000 |                 0.645 |                 1.545 |           0.351 |           0.428 |            0.585 |
| train         | mfe<1              |   44573 |            0.403 |             360.000 |                      -1.372 |                 0.443 |                         1.000 |                -1.533 |                 1.777 |           0.354 |           0.440 |            0.592 |
| validation    | all                |   27165 |            1.000 |             600.000 |                      -0.355 |                 1.302 |                         1.000 |                 0.132 |                 1.916 |           0.414 |           0.561 |            0.700 |
| validation    | mfe>=1 & flip<0.5  |    7274 |            0.268 |             660.000 |                      -0.574 |                 1.678 |                         2.000 |                 0.188 |                 2.408 |           0.396 |           0.565 |            0.688 |
| validation    | mfe>=1 & flip>=0.5 |    9109 |            0.335 |             900.000 |                       1.636 |                 2.989 |                         2.000 |                 0.650 |                 1.471 |           0.412 |           0.558 |            0.705 |
| validation    | mfe<1              |   10782 |            0.397 |             360.000 |                      -1.373 |                 0.450 |                         1.000 |                -1.625 |                 1.777 |           0.426 |           0.561 |            0.706 |

## Gate — 2021–2024 discovery

```json
{
  "period": "train",
  "winner_count": 37112,
  "failed_runner_count": 28814,
  "duration_ratio": 1.3636363636363635,
  "peak_mfe_ratio": 1.7996602451429349,
  "progress_windows_delta": 0.0,
  "retained_m60_delta": 0.47124824684431976,
  "winner_w4_rise_m60_to_flip": 0.1702420505012079,
  "winner_w4_rise_paired_n": 30001,
  "winner_w4_rise_paired_fraction": 0.8083908169864195,
  "winner_peak_to_flip_s": 202.0,
  "winner_giveback_atr": 1.5449526345742661,
  "structural_conditions": {
    "duration": true,
    "peak_mfe": true,
    "progress_windows": false,
    "retention_m60": true
  },
  "structural_pass_count": 3,
  "sample_pass": true,
  "weakness_window_pass": true,
  "pass": true
}
```

## Gate — 2025 sanity check

```json
{
  "period": "validation",
  "winner_count": 9109,
  "failed_runner_count": 7274,
  "duration_ratio": 1.3636363636363635,
  "peak_mfe_ratio": 1.7813460378473154,
  "progress_windows_delta": 0.0,
  "retained_m60_delta": 0.462101025103384,
  "winner_w4_rise_m60_to_flip": 0.23373586534030916,
  "winner_w4_rise_paired_n": 7320,
  "winner_w4_rise_paired_fraction": 0.8036008343396641,
  "winner_peak_to_flip_s": 181.0,
  "winner_giveback_atr": 1.4714922339856304,
  "structural_conditions": {
    "duration": true,
    "peak_mfe": true,
    "progress_windows": false,
    "retention_m60": true
  },
  "structural_pass_count": 3,
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
