# Model card — `short_bearish_flip_top25_current_reference`

**Status: PROVISIONAL** · provenance `COPIED_EXISTING_FITTED_ARTIFACT` · source of truth **joblib**

## Purpose

The reduced 25-feature short-side model currently bound by the NT parity smoke. Frozen as the *current reference* so the smoke's inputs cannot drift.

## Target

`bearish_regime_flip_within_300s` — 1 if the current bullish
RTH regime flips bearish within **300 s** of `observation_time`.

- `current_regime_direction` = 1
- `predicted_flip_direction` = bearish
- `entry_interpretation` = short counter-regime entry timing
- `exit_warning_interpretation` = long exit warning

## Population

NQ, RTH only, established regimes, 5 s checkpoint cadence.
Train 813,972 rows (2021-2024) · dev 198,255 (2025) ·
sealed test 63,021 (2026).

## Feature set

`TOP25` — 25 raw features,
25 model columns.
Order is **significant** and frozen in `feature_order.csv`
(`feature_order_sha256 = acce720cce3322d6…`).

## Training split

Train 2021-2024 · select 2025 · sealed test 2026.
Selected on 2025 by: 2025 AUC (upstream reduction study).

## Selected model

`HistGradientBoostingClassifier`
Hyperparameters: `{"max_depth": 3, "learning_rate": 0.05, "max_iter": 200, "random_state": 42}`
Calibration: none (raw `predict_proba`)
Scoring: `predict_proba(X[feature_order])[:, 1]`

## Validation metrics

| | 2025 (dev) | 2026 (sealed) |
|---|---:|---:|
| AUC | 0.67099 | 0.67247 |
| Top-decile flip rate | 0.5059 | 0.50095 |

Recomputed from this artifact's own `score_reference_*.parquet`.

## Reproducibility / parity

| check | split | rows | max_abs_diff | tol | status |
|---|---|---:|---:|---:|---|
| `auc_vs_published` | train | 813,972 | 0.000e+00 | 1e-09 | **PASS** |
| `auc_vs_published` | 2025 | 198,255 | 0.000e+00 | 1e-09 | **PASS** |
| `score_column_sha256_vs_frozen_thresholds` | 2025 | 198,255 | 0.000e+00 | 0e+00 | **PASS** |
| `threshold_recompute_q0.95` | 2025 | 198,255 | 0.000e+00 | 1e-15 | **PASS** |
| `threshold_recompute_q0.975` | 2025 | 198,255 | 0.000e+00 | 1e-15 | **PASS** |

ONNX: `model.onnx` present, parity PASS (max_abs_diff 2.781e-07 vs joblib).

## Thresholds

`threshold_status = PARTIAL_FROM_SOURCE`.
Copied verbatim from `studies/nt_reduced_f3_top25_population_parity_smoke/config/frozen_thresholds.json`; top-5% = 0.4962425079016764, top-2.5% = 0.5606134281146. top20/top15/top10 were NEVER selected upstream. Left null - not invented, not recomputed.

Thresholds are frozen **separately** from the model and were never recomputed here.

## Known limitations

- **Predicts regime-flip probability, not trade PnL.** No economics, stop, target,
  slippage, or fill model has ever validated this model.
- **Regime-level AUC is ~0.50 (chance).** It does not tell you *which* regimes flip - it
  prices *when*, inside a regime, a flip is imminent (~35-45 s median lead). Any gate must
  read the row-level score, not a regime-aggregated one.
- **No thresholds are implied by the model.** See `threshold_manifest.json`.
- **RTH only, NQ only.** Never evaluated on ETH or another instrument.
- **Carries a known 1-second look-ahead** (see Causal convention). Its published metrics are
  therefore mildly optimistic. This was NOT fixed upstream; the long-side models were.
- **Status is PROVISIONAL** where marked: the source manifest says `status: "candidate"` and
  the NT parity smoke consuming it has not published a STUDY_REPORT. Do not treat its
  numbers as final.

## Causal convention

INHERITED 1s LOOK-AHEAD (disclosed, NOT fixed): the upstream attach_features.py bar-snap uses searchsorted(..., side='right')-1, which includes a bar at ts_event == observation_time - a still-forming open-labelled bar. Affects the ohlcv+price features. The long side fixed this; this short artifact does not. Its metrics are therefore ~1s optimistic. See long_rth_mirrored_surface_top100_training/audit/audit.md.

## How to load

```python
import joblib, pandas as pd
model = joblib.load("artifacts/short_bearish_flip_top25_current_reference/model.joblib")
order = pd.read_csv("artifacts/short_bearish_flip_top25_current_reference/feature_order.csv")["feature_name"].tolist()
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
