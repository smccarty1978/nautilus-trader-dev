# Reproduce — Short-RTH Enriched Volume/Level Retrain

Final decision: `ENRICHED_RETRAIN_OVERFITS_2025`. All commands below assume
`cd studies/short_rth_enriched_volume_level_retrain`.

Note: on Windows, `train_and_evaluate.py`'s GBT permutation-importance step
runs single-threaded (`n_jobs=1`) — a joblib multiprocessing IPC ceiling
(`WinError 1450`) was hit at `n_jobs=-1` on the largest (695-feature) combo.
Each `(feature_set, model)` combo is checkpointed to
`_work/checkpoints/{key}.pkl` immediately after fitting, so a crash on one
combo does not lose already-completed ones; delete the checkpoint directory
before re-running on changed upstream data (see audit finding D4).

## 0. Prerequisite

`studies/ohlcv_volume_delta_price_level_features/_work/full_{2021..2026}.parquet`
must already exist (delivered by that study,
`ACCEPT_FEATURE_FOUNDATION`). `studies/short_rth_w4_retrain_entry_strength/results/phase0_manifest.json`
must exist (its `PHASE0_PASS` control reconciliation is reused here by
construction, not recomputed — see SPEC.md "Scout-pass findings").
`studies/fable5_nt_short_rth_policy_a/_work/short_rth_schedule_{2025,2026}.parquet`
must exist for the Layer 3 fixed-807 overlay.

## 1. Phase 0 — data readiness

```bash
python phase0_prepare_data.py
```

Loads `full_{year}.parquet` for 2021-2026, filters to `label_available`,
builds the 5-class `outcome_class` target from existing `exit_reason`/
`net_pnl` columns, one-hot encodes the 29 bounded `*_position` categorical
columns (fixed category list), builds the F0/F1/F2/F3 feature-column lists,
concatenates 2021-2024 into the training frame, and re-verifies row/label
identity against the prior retrain study's `labeled_featured_{year}.parquet`
(reusing its already-passed 650/222 control reconciliation).

Writes: `_work/prepared_{2021..2026}.parquet`,
`_work/train_2021_2024_prepared.parquet`, `_work/feature_sets.json`,
`results/data_readiness.csv`, `results/phase0_manifest.json`.

Expected: `DECISION: PHASE0_PASS`. Runtime ~3 minutes.

## 2. Train and score models

```bash
python train_and_evaluate.py
```

Trains regularized multinomial logistic regression (train-only median-impute
+ standardize) and `HistGradientBoostingClassifier(max_depth=3)` on
2021-2024 for each of the four feature sets (F0/F1/F2/F3), predicting the
5-class `outcome_class`. Computes `entry_quality_score` from `predict_proba`.
Computes retention-band cutoffs (100/85/70/50/35/20%) on the 2025 score
distribution per (feature_set, model) combo and freezes them.

Writes: `results/model_diagnostics.csv`, `results/calibration_deciles.csv`,
`results/feature_importance.csv`, `_work/scored_{train,dev_2025,test_2026}.parquet`,
`_work/retention_cutoffs.json`, `results/train_and_evaluate_manifest.json`,
`_work/checkpoints/{feature_set}__{model}.pkl` (one per combo).

Expected 2025 AUC (opposing_flip_winner / pre_alignment_stop), best combo
F3-gbt: 0.5816 / 0.5797 (2026: 0.5827 / 0.5690 — the most AUC-stable combo
in the grid). Runtime ~82 minutes total across all 8 combos (F0: ~95s/278s,
F1: ~493s/502s, F2: ~448s/745s, F3: ~1127s/1138s for logreg/gbt
respectively).

## 3. Layer 1 — row-level diagnostics

```bash
python layer1_diagnostics.py
```

For each (feature_set, model, band, split): retention rate and per-class
outcome-class rates among retained rows vs. all rows. Descriptive only —
rows overlap heavily within a regime by construction, not deployable PnL
(see Layer 2 for that).

Writes: `results/retention_band_results.csv`.

## 4. Layer 2 — one-entry-per-regime policy

```bash
python layer2_policy.py
```

For each (feature_set, model, band, split): groups by `regime_start_ns`,
takes the first RTH checkpoint whose `entry_quality_score` clears that
split's frozen cutoff. Writes per-combo trade schedules and aggregate
economics.

Writes: `results/economic_results.csv`, `results/monthly_results.csv`,
`results/exit_reason_attribution.csv`,
`_work/schedule_{feature_set}__{model}_{split}_{band}.parquet`.

## 5. Layer 3 — fixed-807 overlay

```bash
python layer3_overlay.py
```

Applies each Layer 2 schedule to the known fixed-807 regime set (2025/2026
only), reporting keep/drop/added/moved counts and kept-subset economics.

Writes: `results/layer3_fixed807_overlay.csv`.

## 6. Selection gate + attribution + feature-family contribution

```bash
python select_and_attribute.py
```

Selects the best (feature_set, model, retention band) using 2025 Layer-2
economics only, evaluates on sealed 2026, applies the selection gate,
computes stop-savings-vs-winner-clipping attribution, and aggregates
feature-importance by family (existing / volume-delta / price-level) for
every non-F0 (feature_set, model) combo.

Writes: `results/manifest.json`, `results/feature_family_contribution.csv`,
`results/feature_set_comparison.csv`,
`results/selected_model_trade_schedule.parquet`,
`results/selected_model_oos_2026_trades.parquet`.

Expected: selected combo F3_volume_delta_plus_price_levels / logreg / 20%
retention. 2025: 1,243 trades, +$45,110 net (+$36.29/tr, PF 1.241). 2026:
378 trades, −$1,177 net (−$3.11/tr, PF 0.983). `DECISION:
ENRICHED_RETRAIN_OVERFITS_2025`.

## 7. Audit

Run the `lookahead-auditor` agent against this study directory (Phase 0
through selection scripts). Required: 0 CRITICAL before accepting results.

Result: `audit/audit.md`, PASS, 0 CRITICAL (1 non-blocking WARNING, 3 NOTEs
— documentation drift only, corrected in `SPEC.md`).

## Full pipeline (in order)

```bash
python phase0_prepare_data.py
python train_and_evaluate.py
python layer1_diagnostics.py
python layer2_policy.py
python layer3_overlay.py
python select_and_attribute.py
```
