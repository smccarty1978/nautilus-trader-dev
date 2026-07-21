# Model card — `short_bearish_flip_top100_ref`

**Status: FINAL** · provenance `COPIED_EXISTING_FITTED_ARTIFACT` · source of truth **joblib**

## Purpose

Lineage anchor for the short-side reduction: the 100-raw-feature model the 25-feature model was reduced from. Kept so the reduction can be re-derived.

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

`TOP100` — 100 raw features,
103 model columns.
Order is **significant** and frozen in `feature_order.csv`
(`feature_order_sha256 = 7475821527374064…`).

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
| AUC | 0.66411 | 0.66879 |
| Top-decile flip rate | 0.49793 | 0.49032 |

Recomputed from this artifact's own `score_reference_*.parquet`.

## Reproducibility / parity

| check | split | rows | max_abs_diff | tol | status |
|---|---|---:|---:|---:|---|
| `auc_vs_published` | train | 813,972 | 0.000e+00 | 1e-09 | **PASS** |
| `auc_vs_published` | 2025 | 198,255 | 0.000e+00 | 1e-09 | **PASS** |

ONNX: **No usable ONNX export** — conversion parity FAIL; the file was deleted rather than shipped. Use joblib.

## Thresholds

`threshold_status = NOT_SELECTED`.
No thresholds have been selected for this model. 

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
model = joblib.load("artifacts/short_bearish_flip_top100_ref/model.joblib")
order = pd.read_csv("artifacts/short_bearish_flip_top100_ref/feature_order.csv")["feature_name"].tolist()
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
