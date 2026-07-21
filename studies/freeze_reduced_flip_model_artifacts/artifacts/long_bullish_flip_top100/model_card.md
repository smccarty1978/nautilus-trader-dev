# Model card — `long_bullish_flip_top100`

**Status: FINAL** · provenance `RECONSTRUCTED_NO_FITTED_ARTIFACT_EXISTED` · source of truth **joblib**

## Purpose

Long-side reference model (LONG_SURFACE_TOP100_SIGNAL_STRONG_PARITY) that the reduced sets were measured against.

## Target

`bullish_regime_flip_within_300s` — 1 if the current bearish
RTH regime flips bullish within **300 s** of `observation_time`.

- `current_regime_direction` = -1
- `predicted_flip_direction` = bullish
- `entry_interpretation` = long counter-regime entry timing
- `exit_warning_interpretation` = short exit warning

## Population

NQ, RTH only, established regimes, 5 s checkpoint cadence.
Train 682,952 rows (2021-2024) · dev 163,397 (2025) ·
sealed test 52,488 (2026).

## Feature set

`TOP100` — 100 raw features,
100 model columns.
Order is **significant** and frozen in `feature_order.csv`
(`feature_order_sha256 = f2a6db0b6453433c…`).

## Training split

Train 2021-2024 · select 2025 · sealed test 2026.
Selected on 2025 by: 2025 AUC (tie-break 2025 AP); 2026 never used for selection.

## Selected model

`HistGradientBoostingClassifier`
Hyperparameters: `{"max_depth": 3, "learning_rate": 0.05, "max_iter": 200, "random_state": 42}`
Calibration: none (raw `predict_proba`)
Scoring: `predict_proba(X[feature_order])[:, 1]`

## Validation metrics

| | 2025 (dev) | 2026 (sealed) |
|---|---:|---:|
| AUC | 0.66816 | 0.6512 |
| Top-decile flip rate | 0.51138 | 0.53648 |

Recomputed from this artifact's own `score_reference_*.parquet`.

## Reproducibility / parity

| check | split | rows | max_abs_diff | tol | status |
|---|---|---:|---:|---:|---|
| `joblib_reload_vs_source` | 2025 | 163,397 | 0.000e+00 | 1e-09 | **PASS** |
| `joblib_reload_vs_source` | 2026 | 52,488 | 0.000e+00 | 1e-09 | **PASS** |
| `auc_vs_published` | 2025 | 163,397 | 0.000e+00 | 1e-09 | **PASS** |
| `auc_vs_published` | 2026 | 52,488 | 0.000e+00 | 1e-09 | **PASS** |

ONNX: **No usable ONNX export** — conversion parity FAIL; the file was deleted rather than shipped. Use joblib.

## Thresholds

`threshold_status = NOT_SELECTED`.
No thresholds have been selected for this model. No long-side trigger study has run. Thresholds must be chosen on 2025 (or new data) by a future study - never 2026.

Thresholds are frozen **separately** from the model and were never recomputed here.

## Known limitations

- **Predicts regime-flip probability, not trade PnL.** No economics, stop, target,
  slippage, or fill model has ever validated this model.
- **Regime-level AUC is ~0.50 (chance).** It does not tell you *which* regimes flip - it
  prices *when*, inside a regime, a flip is imminent (~35-45 s median lead). Any gate must
  read the row-level score, not a regime-aggregated one.
- **No thresholds are implied by the model.** See `threshold_manifest.json`.
- **RTH only, NQ only.** Never evaluated on ETH or another instrument.
- **Reconstructed, not originally persisted.** No fitted object existed; this artifact is a
  refit that reproduces the source study's stored predictions bit-identically. It is
  equivalent, not the literal original object (none was ever saved).
- 2021-2024 train / 2025 select / 2026 sealed. 2026 was never used to fit, select,
  tune, threshold, or calibrate.

## Causal convention

Strict: latest_source_ts_used < observation_time. Raw 1s bars are open-labelled ([t, t+1s)), so the last COMPLETED bar at observation_time has ts_event strictly before it. Corrected in long_rth_mirrored_surface_top100_training after a CRITICAL audit finding.

## How to load

```python
import joblib, pandas as pd
model = joblib.load("artifacts/long_bullish_flip_top100/model.joblib")
order = pd.read_csv("artifacts/long_bullish_flip_top100/feature_order.csv")["feature_name"].tolist()
```

> **Trusted-local only.** `joblib`/`pickle` executes code on load. Load this file only from
> this repository, never from an untrusted source.

## How to score

```python
scores = model.predict_proba(df[order])[:, 1]   # positive_class_index = 1
```

Columns **must** be passed in `feature_order.csv` order. Verify against
`score_reference_2025.parquet` before trusting a new integration.

## What not to use it for

- Do **not** use it to decide *whether* to trade a regime — regime-level AUC is chance.
- Do **not** read the probability as an expected-PnL or edge estimate.
- Do **not** apply thresholds from another model; they are model-specific.
- Do **not** use ONNX output as the source of truth — joblib is authoritative.
- Do **not** use it outside NQ RTH.

**This model predicts regime flip probability, not trade PnL.**
