# Reproduce — Short-RTH W4 Retrain Entry Strength

Final decision: `SHORT_RTH_BASELINE_STILL_BEST`. All commands below assume
`cd studies/short_rth_w4_retrain_entry_strength`.

## 0. Prerequisite

`studies/short_rth_entry_surface_backfill/` must already have produced
`results/full_surface_labels_{2021,2022,2023,2024}.parquet`,
`_work/atlas_5s_backfill_{2021,2022,2023,2024}.parquet`, and
`results/reconciliation_2025_2026_surface.parquet` (all already delivered by
that study).

## 1. Phase 0 — data readiness

```bash
python phase0_prepare_data.py
```

Joins the 149 causal features onto the 2021-2024 labeled surface, builds
full-surface Policy A labels for 2025/2026 (reusing `label_full_surface.label_row`
verbatim from the backfill study), joins features for those two years, and
re-verifies the known 650/222 candidate controls on the feature-joined
output. Writes only into this study's own `_work/`/`results/` — the backfill
study's directories are read-only input.

Writes: `_work/labeled_featured_{2021..2026}.parquet`,
`_work/train_2021_2024_featured.parquet`, `results/phase0_summary.md`,
`results/phase0_manifest.json`.

Expected: `DECISION: PHASE0_PASS`. Runtime ~1-2 minutes.

## 2. Train and score models

```bash
python train_and_evaluate.py
```

Trains logistic regression (train-only median-impute + standardize) and
`HistGradientBoostingClassifier(max_depth=3)` on 2021-2024 to predict
`hit_pre_alignment_stop`. Scores train/2025/2026. Joins the frozen W4 score
for 2025/2026 as a third (non-retrained) comparator. Computes retention-band
cutoffs (100/85/70/50/35/20%) on the 2025 score distribution and freezes
them.

Writes: `results/model_diagnostics.csv`, `results/calibration_deciles.csv`,
`results/feature_importance.csv`, `results/retention_band_results.csv`,
`_work/scored_{train,dev_2025,test_2026}.parquet`,
`_work/retention_cutoffs.json`.

Expected AUCs: logreg train/2025/2026 ≈ 0.562/0.529/0.518; GBT ≈
0.658/0.526/0.518; W4 comparator ≈ n/a/0.500/0.493. Runtime ~1 minute.

## 3. Layer 2 — one-entry-per-regime policy

```bash
python layer2_policy.py
```

For each (model, band, split): groups by `regime_start_ns`, takes the first
eligible RTH checkpoint (by `observation_time`) whose score clears that
model's frozen cutoff, and computes full trade economics.

Writes: `results/economic_results.csv`, `results/monthly_results.csv`,
`results/exit_reason_attribution.csv`, `_work/schedule_{model}_{split}_{band}.parquet`
(54 schedule files: 3 models × ~3-2 splits × 6 bands).

## 4. Layer 3 — fixed-807 overlay

```bash
python layer3_overlay.py
```

Applies every (model, band, split∈{2025,2026}) Layer-2 schedule to the
known fixed-807 regime set (`fable5_nt_short_rth_policy_a/_work/short_rth_schedule_{year}.parquet`)
and reports keep/drop/moved-entry counts plus kept-subset economics.

Writes: `results/layer3_fixed807_overlay.csv`.

## 5. Selection, sealed evaluation, attribution

```bash
python select_and_attribute.py
```

Selects the (model, band) with the highest 2025 Layer-2 per-trade PnL (ties
by PF) — **2026 is never read during selection**. Evaluates the frozen
selection on 2026. Runs the SPEC's selection gate. Computes failure
attribution (stops avoided vs winners removed, by month) against that same
model's own 100%-retention schedule.

Writes: `results/manifest.json` (top-level decision + full gate/attribution
detail), `results/best_model_trade_schedule.parquet` (2025),
`results/best_model_oos_2026_trades.parquet` (2026).

Expected: selects GBT @ 35% retention; `DECISION: SHORT_RTH_BASELINE_STILL_BEST`.

## Lookahead audit

`audit/audit.md` — PASS, 0 CRITICAL, 3 WARNING, 5 NOTE, covering all 5
scripts above. Re-run the audit if any of these scripts are modified before
trusting a rerun's output; the 3 warnings (incomplete gate automation, no
minimum-trade-count floor on selection, frozen W4 comparator not excluded
from the "best" candidate pool) did not affect this run but are unguarded
paths for a future one.

## Order dependency

Step 1 has no dependency beyond the prerequisite. Steps 2-5 must run in
order (each reads the previous step's `_work/`/`results/` output). Total
runtime for the full sequence: ~5-10 minutes.

## Not done

No feature selection beyond the fixed 149-column set. No threshold
optimization beyond the 6 fixed retention bands. No hyperparameter search
(model configs are fixed, not tuned). No NT-native validation — this
remains a 1-second-OHLC research simulation throughout. No promotion to NT
schedule-driven validation (the decision explicitly does not warrant it).
