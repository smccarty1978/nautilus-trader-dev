# Reproduce — Established-Regime Age Gate Study (120s vs 240s)

Final decision: `AGE_GATE_INCONCLUSIVE`. All commands below assume
`cd studies/short_rth_established_age_gate_flip_quality`.

## 0. Prerequisites

- `studies/ohlcv_volume_delta_price_level_features/_work/full_{2021..2026}.parquet`
  (feature-foundation study, `ACCEPT_FEATURE_FOUNDATION`).
- `studies/short_rth_entry_surface_backfill/_work/surface_{2021..2024}.parquet`
  and `.../results/reconciliation_2025_2026_surface.parquet` (gate-input
  columns: `regime_age_s`, `running_mfe_atr`, `retained_mfe_ratio`,
  `confirm_flip_ns`, etc.).
- `studies/short_rth_enriched_volume_level_retrain/_work/feature_sets.json`
  and its `train_and_evaluate.py` (`fit_logistic`/`fit_gbt`/`find_position_cols`/
  `one_hot_position_cols`, all imported not reimplemented).
- Raw 1s bars: `data/raw/NQ_v0_1s_{year}.parquet` (for the post-flip MFE scan).

## 1. Phase 0 — join gate columns, derive labels, build gate surfaces

```bash
python phase0_prepare_data.py
```

Joins `regime_age_s`/`running_mfe_atr`/`retained_mfe_ratio`/`confirm_flip_ns`
onto each year's `full_{year}.parquet` (100% key match required); derives
`bearish_flip_within_{300,600}s`, `time_to_bearish_flip_s`,
`adverse_move_1p25A_before_bearish_flip`, `no_flip_before_timeout` from
existing columns (`aligned`, `hit_pre_alignment_stop`); computes
`post_flip_mfe_atr_{300,600}s` via a raw-1s-bar scan done once per distinct
regime (not per row); builds the follow-through labels; one-hot encodes the
29 `*_position` categorical columns; builds Gate A (120s) / Bridge (180s) /
Gate B (240s) full-checkpoint and first-eligible-per-regime surfaces as pure
row-filters on `regime_age_s`.

Writes: `_work/prepared_{2021..2026}.parquet`, `_work/full_{gate}_{year}.parquet`,
`_work/first_eligible_{gate}_{year}.parquet` (18 files each), `_work/feature_sets.json`,
`results/phase0_manifest.json`.

Expected: 100% gate-column join rate, 0 unavailable post-flip windows, all 6
years. Runtime ~9 minutes (raw-bar loading + regime-level MFE scan
dominates).

## 2. Population + label-quality diagnostics

```bash
python population_label_diagnostics.py
```

Writes: `results/gate_population_summary.csv`,
`results/gate_label_quality_by_year.csv`,
`results/full_checkpoint_surface_summary.csv`,
`results/first_eligible_surface_summary.csv`.

## 3. Feature separation diagnostics

```bash
python feature_separation_diagnostics.py
```

Per gate x label x feature: oriented AUC (year-pooled and per-year),
Cohen's d, decile-monotonicity Spearman rho, on the first-eligible surface.
No thresholds selected.

Writes: `_work/feature_separation_per_feature.csv`,
`results/gate_feature_separation.csv`.

Expected: mean pooled AUC per family in the 0.506-0.519 range across all
three gates and three labels — differences between gates are in the 3rd-4th
decimal (not meaningful).

## 4. Optional diagnostic model

```bash
python optional_diagnostic_model.py
```

Regularized logistic regression + shallow GBT (`F3` combined features),
train 2021-2024 / inspect 2025 / sealed 2026, per gate, for
`bearish_flip_within_300s_and_followthrough_1A` and
`adverse_move_1p25A_before_bearish_flip`. Not a production candidate.

Writes: `results/optional_model_diagnostics.csv`.

## 5. Manifest

```bash
python build_manifest.py
```

Assembles `results/manifest.json` from all prior CSVs.

## 6. Audit

Run the `lookahead-auditor` agent against this study directory.

Result: `audit/audit.md`, PASS, 0 CRITICAL. 1 WARNING (raw-data-gap could
inflate `post_flip_mfe_atr_*` at a window boundary) + 2 NOTEs, all three
fixed post-audit (see audit.md's "Post-audit fixes applied" section) —
`phase0_prepare_data.py`'s window slice changed from inclusive to exclusive
of the boundary bar, a runtime assertion was added for `confirm_flip_ns`
regime-constancy, and follow-through labels became NaN-propagating instead
of plain booleans. Full pipeline re-run after the fix; `results/*.csv`
reflect the fixed code.

## Full pipeline (in order)

```bash
python phase0_prepare_data.py
python population_label_diagnostics.py
python feature_separation_diagnostics.py
python optional_diagnostic_model.py
python build_manifest.py
```
