# Reproduce — Short-RTH Pure Regime-Flip Prediction

Final decision: `PURE_FLIP_SIGNAL_INCONCLUSIVE`. All commands below assume
`cd studies/short_rth_pure_flip_prediction_enriched`.

## 0. Prerequisites

- `studies/ohlcv_volume_delta_price_level_features/_work/full_{2021..2026}.parquet`
- `studies/short_rth_entry_surface_backfill/_work/surface_{2021..2024}.parquet`
  and `.../results/reconciliation_2025_2026_surface.parquet`
- `studies/short_rth_established_age_gate_flip_quality/phase0_prepare_data.py`
  (reused: `load_gate_columns`, `post_flip_mfe_by_regime`, `followthrough_flag`)
- `studies/short_rth_enriched_volume_level_retrain/phase0_prepare_data.py`
  (reused: `find_position_cols`, `one_hot_position_cols`) and
  `.../train_and_evaluate.py` (reused: `fit_logistic`, `fit_gbt`) and
  `.../_work/feature_sets.json`
- `data/raw/NQ_v0_1s_{year}.parquet`

## 1. Pre-execution tests (run BEFORE Phase 0, per project standing rule)

```bash
python -m pytest tests/test_build_labels.py -v
```

7 hand-computed tests, including the core regression case (a row stopped
out by Policy A's pre-alignment stop, but whose regime still flips within
300s — must be labeled positive, unlike the prior study's buggy
`aligned`-based reuse). Expected: 7 passed.

## 2. Phase 0 — join gate columns, corrected primary label, full surface

```bash
python phase0_prepare_data.py
```

Builds `bearish_regime_flip_within_300s` from pure `confirm_flip_ns`/
`observation_time` arithmetic (SPEC.md finding 1) — never via Policy A's
`aligned`. Reuses `post_flip_mfe_by_regime`/`followthrough_flag` from the
age-gate study and `find_position_cols`/`one_hot_position_cols` from the
enriched retrain study via a same-name-collision-safe `importlib` loader
(see the file's own header comment — both upstream scripts happen to share
the literal filename `phase0_prepare_data.py`).

Writes: `_work/prepared_{2021..2026}.parquet`,
`_work/train_2021_2024_prepared.parquet`, `_work/feature_sets.json`,
`results/phase0_manifest.json`.

Expected: 100% gate-column join rate, 0 primary-label censored rows, all 6
years. Runtime ~3 minutes.

## 3. Data readiness + label quality

```bash
python build_readiness_and_label_quality.py
```

Writes: `results/data_readiness.csv`, `results/label_quality_by_year.csv`.

## 4. Pre-execution audit (of step 2's label logic, before step 5's expensive run)

Run the `lookahead-auditor` agent against `phase0_prepare_data.py` +
`tests/test_build_labels.py` specifically. Result:
`audit/audit.md` (first section), 0 CRITICAL.

## 5. Train + calibrate

```bash
python train_and_evaluate.py
```

8 (feature_set × model) combos, binary target
`bearish_regime_flip_within_300s`, train 2021-2024, calibrate (isotonic +
sigmoid) on 2025 only via `CalibratedClassifierCV(FrozenEstimator(...))`,
evaluate raw and calibrated on 2026.

Writes: `results/model_metrics.csv`, `results/calibration_deciles.csv`,
`results/feature_importance.csv`, `_work/scored_{train,dev_2025,test_2026}.parquet`.

Expected: best combo F3/gbt, 2025 AUC raw ≈0.671, 2026 AUC raw ≈0.670.
Runtime ~22 minutes.

## 6. Regime-level + feature-family diagnostics

```bash
python regime_and_family_diagnostics.py
```

Writes: `results/regime_level_diagnostics.csv`,
`results/feature_family_contribution.csv`.

Expected: regime-level AUC ≈0.47-0.53 across all 8 combos, both years —
this is the key number that overturns the row-level headline (see step 7).

## 7. Selection + signal viability gate

```bash
python select_and_gate.py
```

Selects best (feature_set, model) by 2025 raw AUC, applies the SPEC's
signal-viability gate — **requires both row-level AND regime-level checks
to pass** (post-audit fix; the first version of this gate ignored the
regime-level diagnostics entirely, see `audit/audit.md`'s "Post-audit fix
applied" section).

Writes: `results/manifest.json`,
`results/selected_model_predictions_2025.parquet`,
`results/selected_model_predictions_2026.parquet`.

Expected: `DECISION: PURE_FLIP_SIGNAL_INCONCLUSIVE`.

## 8. Completion-gate audit

Run the `lookahead-auditor` agent against the full pipeline. Result:
`audit/audit.md` (second, appended section), 1 CRITICAL found and fixed
(see step 7), re-verified clean after the fix.

## Full pipeline (in order)

```bash
python -m pytest tests/test_build_labels.py -v
python phase0_prepare_data.py
python build_readiness_and_label_quality.py
python train_and_evaluate.py
python regime_and_family_diagnostics.py
python select_and_gate.py
```
