# Study Report — Mirrored Long-Side Top-100 Pure-Flip Model Training

## Decision

**`LONG_TOP100_STUDY_REMEDIATION_REQUIRED`**

The study halted at the data-availability gate, before any feature matrix,
label vector, or model was constructed. The frozen top-100 feature list was
resolved cleanly; the blocker is that the **long-side data/label surface the
study requires does not exist**, and building it is out of the declared
"lightweight offline model-training" scope.

This is not a modeling failure (no model was fit) and not a feature-resolution
failure (the list resolved). It is a missing-prerequisite finding: the
`REMEDIATION_REQUIRED` label is the honest fit because the required data and
label infrastructure is absent.

## What was verified this session (live repo state, not assumed)

| Claim | Evidence |
|---|---|
| Short-side surface target is `bearish_regime_flip_within_300s` | schema of `short_rth_pure_flip_prediction_enriched/_work/prepared_2025.parquet` |
| Short-side population is prevailing-**long** (`direction == 1`) | `short_rth_entry_surface_backfill/entry_surface.py:70-71` (`if direction != 1: continue`) |
| No `bullish_regime_flip_within_300s` anywhere | grep across repo; not present in any `_work/*.parquet` |
| No `direction == -1` checkpoint population anywhere | funnel drops it for all 6 years; confirmed by prior repo-wide search in `nt_pure_flip_trigger_poc_and_mirrored_long_model` |
| Mirror = full pipeline rebuild, already deferred | `nt_pure_flip_trigger_poc_and_mirrored_long_model/STUDY_REPORT.md` Phase 3 `descoped_scope_gap_deferred`, user decision 2026-07-20 |

## Answers to the brief's ten required questions

1. **What exact top-100 feature list was used?** The ranked raw list in
   `results/top100_feature_list.csv` (100 features), sourced from
   `runtime_constrained_f3_feature_reduction/results/top_100_raw_feature_columns.csv`.
   Families: 44 `regime_median_center_slope_alignment`, 29 `ohlcv_est_delta`,
   27 `price_level_context`. `ordered_feature_list_sha256 =
   f2a6db0b6453433ccc1970255808c940133d1530ff4aa907339966c8c4f37992`.
2. **Was the list resolved cleanly from short-side artifacts?** Yes — from the
   feature-reduction study's ranked output. One recorded ambiguity: the trained
   `F3_top100_gbt_v1` expands to 103 columns via one-hot completion; the raw
   ranked top-100 is the unambiguous per-brief list. Note that the short-side
   reduction study's own selection gate returned
   `NO_REDUCED_MODEL_PRESERVES_POPULATION` — i.e. no reduced model was promoted;
   the top-100 is a feature *ranking* artifact, which is all this brief needs.
3. **Was the bullish-flip target mirrored correctly?** Cannot be answered — the
   target column does not exist and was never constructed. No mirrored labeling
   was performed.
4. **2025 / 2026 AUCs?** N/A — no model trained.
5. **2025 / 2026 top-decile flip rates?** N/A — no model trained.
6. **2025 / 2026 top-decile lifts?** N/A — no model trained.
7. **2026 monthly AUC stability?** N/A — 2026 was never opened.
8. **Closeness to the short-side bearish-flip model?** Not comparable — no
   long-side model exists to compare.
9. **Which feature families mattered most?** N/A for the long side. (On the
   short side the top ranks are dominated by center/slope/alignment and
   price-level context.)
10. **Is the long-side signal strong enough to justify long-entry /
    short-exit-warning / reversal studies?** Undetermined by this study. The
    prerequisite is building the mirrored long-side surface first.

## Required artifacts — status

Produced (legitimate):
- `results/top100_feature_list.csv`
- `results/top100_feature_manifest.json`
- `SPEC.md`, `STUDY_REPORT.md`, `REPRODUCE.md`, `audit/audit.md`

Intentionally **absent** (would require the non-existent long-side surface;
fabricating them would be dishonest): `data_readiness.csv`,
`label_quality_by_year.csv`, `model_metrics.csv`, `calibration_deciles.csv`,
`regime_level_diagnostics.csv`, `feature_importance.csv`,
`feature_family_contribution.csv`, `selected_model_predictions_2025.parquet`,
`selected_model_predictions_2026.parquet`, `model_manifest.json`.

## Audit gate

The mandatory `lookahead-auditor` pass was **not reached**: execution halted at
the data-availability gate before any causal/feature-engineering/model logic was
written, so there is nothing to audit. The audit gate applies before finalizing
a strategy or feature engineering; neither was produced. See `audit/audit.md`.

## Recommended remediation (a separate, properly-scoped study)

To actually run this study, first build the mirrored long-side surface:
1. New inverted `entry_surface`-style funnel keeping `direction == -1`, with the
   `favorable` excursion sign convention inverted (bearish-regime favorable =
   down).
2. Full re-attachment of the F3 feature surface across 2021–2026 for that
   population, using the direction-aware trackers (`price_levels.py` already
   accepts `direction=+1`; confirm long-side sign semantics per the brief's
   mirroring-audit checklist).
3. Fresh pure-arithmetic `bullish_regime_flip_within_300s` labeling with 300 s
   forward-horizon censoring.
4. Only then apply the frozen top-100 (already resolved and hashed here) and
   train logreg + GBT under the standard split discipline.

That is the multi-phase rebuild the user deferred on 2026-07-20 and should be
briefed as its own study, not folded into a "lightweight" job.
