# Mirrored Long-Side Top-100 Pure-Flip Model Training

## Status

**BLOCKED at the data-availability gate — halted before any model matrix was
constructed.** Decision: `LONG_TOP100_STUDY_REMEDIATION_REQUIRED`. See
`STUDY_REPORT.md` for the full finding.

The frozen top-100 feature list was resolved cleanly (see
`results/top100_feature_manifest.json`). The study cannot proceed because **no
long-side (prevailing-bearish, `direction == -1`) checkpoint population or
`bullish_regime_flip_within_300s` label exists anywhere in the repository.**
Building it is a multi-study pipeline rebuild that was explicitly descoped by
the user on 2026-07-20, not the "lightweight offline model-training job" this
brief assumes.

## Intended design (not executed)

- **Decision question:** Given a qualified bearish RTH regime, can the reduced
  top-100 feature set predict a bullish regime flip within the next 300 s?
- **Population:** NQ, RTH only, `direction == -1` (prevailing-bearish) regime
  checkpoints — the mirror of the short-side `direction == 1` population.
- **Target:** `bullish_regime_flip_within_300s`, a pure market-state transition
  label independent of stop/PnL/timeout/entry/exit.
- **Features:** frozen `TOP100_short_reduced_features` (resolved below).
- **Split:** train 2021–2024, dev/select 2025, sealed test 2026. No 2026 in any
  fitting or selection decision.
- **Models:** regularized logistic regression + `HistGradientBoostingClassifier(
  max_depth=3, learning_rate=0.05, max_iter=200, random_state=42)`.

## Frozen feature list (resolved — this part succeeded)

- `feature_source_file`:
  `studies/runtime_constrained_f3_feature_reduction/results/top_100_raw_feature_columns.csv`
- `feature_source_sha256`:
  `6c6ceba7d3520e91b0feaed00cd6ab320230e8404e840894190b1cc7e70bc619`
- `ordered_feature_list_sha256`:
  `f2a6db0b6453433ccc1970255808c940133d1530ff4aa907339966c8c4f37992`
- `n_features`: 100
- `feature_family_counts`: `regime_median_center_slope_alignment` 44,
  `ohlcv_est_delta` 29, `price_level_context` 27
- Timing: 97 `verified`, 3 `TIMING_UNVERIFIED`
  (`regime_first_half_vol`, `regime_abs_delta_per_atr_moved`,
  `regime_price_change_atr`).
- All 100 are registry-bound with live trackers on the **short-side** surface.

**Ambiguity recorded, not silently resolved:** the short-side *trained* model
`F3_top100_gbt_v1` expands to **103** columns via one-hot group completion. The
frozen top-100 here is the ranked **raw** feature list (exactly 100), which is
the unambiguous per-brief interpretation. This is a secondary note; it is not
the blocker.

## Why the study is blocked (verified against live repo state this session)

1. `studies/short_rth_pure_flip_prediction_enriched/_work/prepared_2025.parquet`
   carries the target `bearish_regime_flip_within_300s` and an
   `entry_direction`; its population is prevailing-**long** regimes.
2. `studies/short_rth_entry_surface_backfill/entry_surface.py:70-71` does
   `if direction != 1: continue` — it drops every non-long regime at the first
   funnel stage, for all six years. The long-side (`direction == -1`) population
   is therefore never materialized.
3. No `bullish_regime_flip_within_300s` column exists in any
   `studies/**/_work/*.parquet`.
4. The prior study
   `studies/nt_pure_flip_trigger_poc_and_mirrored_long_model` reached exactly
   this conclusion (Phase 3 `descoped_scope_gap_deferred`, 2026-07-20): the
   mirror requires a new inverted `entry_surface` funnel, a full 695-feature
   re-attachment run across 2021–2026, fresh `bullish_regime_flip_within_300s`
   labeling, and a fresh retrain — "the equivalent of three prior full studies'
   pipelines mirrored."

## Stop conditions triggered (from the brief)

- "any feature is unavailable in the long-side prepared surface" — **all 100**
  are unavailable because the surface does not exist.
- "a required feature is absent from the long-side surface."
- "the run requires implementing new features" (population + label + feature
  re-attachment).
- The core premise "lightweight offline mirrored-model training job" is false.

Per the brief, the correct action is to **stop and report instead of
improvising**. Substituting the short-side surface (wrong population *and* wrong
target) is explicitly not allowed and would be scientifically invalid.
