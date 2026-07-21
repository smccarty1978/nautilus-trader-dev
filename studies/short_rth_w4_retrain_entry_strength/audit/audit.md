# Look-Ahead & Timestamp Audit — short_rth_w4_retrain_entry_strength

**Date:** 2026-07-18
**Scope:**
- `studies/short_rth_w4_retrain_entry_strength/phase0_prepare_data.py`
- `studies/short_rth_w4_retrain_entry_strength/train_and_evaluate.py`
- `studies/short_rth_w4_retrain_entry_strength/layer2_policy.py`
- `studies/short_rth_w4_retrain_entry_strength/layer3_overlay.py`
- `studies/short_rth_w4_retrain_entry_strength/select_and_attribute.py`
- Direct imports inspected for correctness-of-use only (not re-audited): `studies/short_rth_entry_surface_backfill/label_full_surface.py`, `studies/regime_sequence_chop_context/train_weakness_model.py` + `build_regime_sequence.py` (feature name resolution), `studies/CODEX_5_X_weakness_atlas_repair/CODEX_5_X_train_repaired_w4.py` (direction convention), `studies/fable5_short_rth_threshold_ladder/run_ladder.py` (control reconciliation).
- SPEC reviewed: `studies/short_rth_w4_retrain_entry_strength/SPEC.md`
- Existing run outputs cross-checked: `results/phase0_manifest.json`, `results/manifest.json`, `results/economic_results.csv`

**Auditor:** lookahead-auditor v1
**Scope hash (5 audited files, sha256 of concatenated bytes basis):** phase0_prepare_data.py (244 lines) + train_and_evaluate.py (297 lines) + layer2_policy.py (139 lines) + layer3_overlay.py (88 lines) + select_and_attribute.py (187 lines) — 955 lines total, each read in full.

## Summary

- Critical: 0
- Warning: 3
- Note: 5

**Overall status: PASS.** No look-ahead bias, train/serve skew, or 2026-into-selection leakage was found across the five audited files. All seven items in the user's specific checklist passed. The findings below are methodology-robustness and reporting-clarity issues, not causality defects, and do not invalidate the already-produced `SHORT_RTH_BASELINE_STILL_BEST` decision in `results/manifest.json`.

## Critical findings

None.

## Warnings

### [W1] `select_and_attribute.py:111-139` — `apply_gate()` only automates 3 of the SPEC's ~6 selection-gate criteria

SPEC.md's "Selection gate" section requires checking, in addition to $/trade and 2026-positivity: PF and/or DD improvement, "pre-alignment stop reduction is not offset by removing too many opposing-flip winners," "monthly shape is not obviously worse," and "the result is not driven by one month." `attribution()` (lines 54-108) computes the underlying numbers (`opposing_flip_winners_removed_count`, `net_pnl_lost_from_removed_opposing_flip_winners`, `monthly_pnl_full`/`monthly_pnl_selected`, `monthly_concentration_selected_top1_share`), but `apply_gate()` never reads them — the automated `decision` string is derived solely from `dev_improves` (per-trade OR PF vs Baseline A) and `test_positive`/`test_not_materially_worse` (2026 per-trade vs 50% of Baseline A 2026 per-trade). In the current run this is harmless because `dev_improves` was already `False` (gbt/0.35 per-trade $4.75 vs baseline $23.64), so the run correctly terminated at `SHORT_RTH_BASELINE_STILL_BEST` before the missing checks would have mattered. But on a future rerun (different data, different band grid, etc.) the code could emit `SHORT_RTH_RETRAIN_PROMISING` even if the selected model clips too many opposing-flip winners or its edge is concentrated in one month, since those checks are not gated in code — only visible if a human reads `failure_attribution` in the manifest afterward.

**Recommended fix (do not apply):** fold an opposing-flip-winner-clip threshold and a monthly-concentration/robustness check into `apply_gate()` so `SHORT_RTH_RETRAIN_CLIPS_WINNERS` can actually be emitted programmatically, and require monthly-driven-by-one-month explicitly logged as a caveat in the decision struct.

### [W2] `select_and_attribute.py:40-51` — `select_best()` has no minimum-trade-count guard

`select_best()` ranks all (model, band) combinations on 2025 by `per_trade` (desc), tie-break `profit_factor` (desc), with the only filter being `trades > 0`. There is no floor on sample size. In the current run this is immaterial — the smallest 2025 Layer-2 band still has 702-1,255 trades — but the selection mechanism itself is not protected against picking a high-variance, low-n combo in any future rerun with a wider band grid, a smaller population, or a per-model/per-year split. Given this is exactly the class of overfitting the study exists to prevent (see `SHORT_RTH_RETRAIN_OVERFITS_2025` outcome label), the selector should not be exposed to unbounded small-n noise even in principle.

### [W3] `select_and_attribute.py:40-51` / `train_and_evaluate.py:250-256` — `w4_comparator` is not excluded from the "best model" candidate pool

SPEC.md explicitly documents Model family C ("current pooled W4 score/rank") as "a non-retrained comparator (never trained on 2021-2024)" and lists it under "Model families" alongside the two trainable families only for baseline continuity — not as a promotion candidate. `select_best()` reads `economic_results.csv` without excluding `model == "w4_comparator"`, so if the frozen W4 comparator happened to produce the best 2025 per-trade number, `manifest.json`'s `selected_model` would read `"w4_comparator"` and a `SHORT_RTH_RETRAIN_PROMISING` decision would misleadingly imply a *retrained* model succeeded, when in fact the incumbent frozen scorer (repackaged onto this study's broader candidate population) won. Did not occur in this run (`gbt` won), so this is a latent reporting-ambiguity risk rather than an active defect.

## Notes

### [N1] SPEC.md:191-193 text is stale relative to the implemented cutoff methodology

SPEC.md's retention-band paragraph says cutoffs should be "computed within the split being reported (train-only percentiles for train, frozen dev cutoffs applied unchanged to 2026)" — i.e., it implies train should get its own train-derived percentiles. The actual implementation (`train_and_evaluate.py:237-244`) computes cutoffs *only* from `dev_df` (2025) and applies those same frozen numbers to train, 2025, and 2026 alike (train usage explicitly diagnostic-only per code comments and per the task description supplied for this audit). This is not a leakage issue — if anything it is more conservative than SPEC's literal text — but SPEC.md should be updated so future readers aren't confused about which cutoffs train diagnostics actually use.

### [N2] `select_and_attribute.py:22-27` vs `:112-119` — hardcoded baseline literals duplicate `BASELINE_A`

`apply_gate()` hardcodes `1.129` for the PF-improvement check on line 116 instead of referencing `BASELINE_A["combined"]["profit_factor"]`, which is already defined at the top of the file. Not a causality bug, but a drift risk: if `BASELINE_A` is ever revised (e.g., a corrected baseline recomputation), the gate's literal `1.129` would silently go stale unless someone remembers to edit both places.

### [N3] Layer 2's candidate universe is materially larger than Baseline A's, even after retention filtering

At 100% retention, the Layer-2 one-entry-per-regime population is 1,678 trades (2025) vs. Baseline A's 650 — a byproduct of the SPEC's explicit design choice that "the frozen W4 score is not used to define 2021-2024 [or 2025/2026] candidates" (SPEC.md:107-110). Even the tightest band (20%) still retains 702-1,255 trades, 1.1x-1.9x Baseline A's count. This is called out in the SPEC itself and is not a bug, but because the entire selection gate hinges on comparing this population's $/trade and PF against Baseline A's, the final report should state prominently that Layer 2 vs. Baseline A is a different-opportunity-set comparison, not a strict apples-to-apples re-scoring of the same 650/222 trades (that comparison is what Layer 3 is for).

### [N4] 2025/2026 Policy A labels are computed independently per calendar year

`phase0_prepare_data.py:99-121` builds `canonical_regime_timeline` and simulates Policy A exits using only that single year's `RAW_1S[year]` bar array, per year, in a loop. Any regime/confirmation-window that would span a Dec 31 -> Jan 1 boundary is implicitly bounded within the single year's array. This mirrors the already-audited treatment used for 2021-2024 in `short_rth_entry_surface_backfill` (not a new defect introduced by this study), but is worth re-confirming was actually checked there, since it now silently propagates into two more years' labels.

### [N5] No per-feature NaN-rate artifact, despite being a SPEC-required "data check"

SPEC.md's "Required outputs" section lists "missing feature columns, NaN rate" as a data check. The actual Phase 0 script only asserts whole-row join completeness (`fully_missing_features`, `join_rate_any_feature_present` — both check "is *every* one of the 149 columns NaN for this row," not per-column rates). No per-column NaN-rate CSV/report was found in `results/`. Because `HistGradientBoostingClassifier` handles NaN natively and `SimpleImputer(strategy="median")` for logistic regression is fit strictly on train (see Clean Checks, Item 3), this is a documentation-completeness gap rather than a leakage risk, but it means a silently-high per-column NaN rate in a specific feature (e.g. an early-K sequence feature with `seq_Kr_available=False` for short regimes) would not currently surface in any artifact.

## User checklist — item-by-item findings

1. **2026 used to choose model family/band/features/hyperparameters?** No. Verified by full read + targeted grep of all five files: cutoffs, `select_best()`, feature list, and hyperparameters (`C=1.0`, `max_depth=3`, `learning_rate=0.05`, `max_iter=200`) are all fixed/predeclared or derived from train (2021-2024)/dev (2025) only. `test_df`/`test_X`/`test_y`/2026 economics are referenced only for post-hoc reporting (AUC, calibration deciles, `test_row` in `select_and_attribute.py`), always computed *after* the frozen selection.

2. **Retention cutoffs frozen on 2025 only?** Yes. `train_and_evaluate.py:238-244` computes `cutoffs[model_name][band] = np.quantile(dev_df[score_col].dropna(), 1-band)` — `dev_df` is exclusively the 2025 parquet. These are persisted to `retention_cutoffs.json` and applied unchanged to train (diagnostic-only) and 2026 in `layer2_policy.py:94-113`. 2026's own score distribution is never read when computing cutoffs.

3. **Imputer/scaler train-only for logreg? Same for GBT?** Yes for both. `fit_logistic()` (`train_and_evaluate.py:68-75`) calls `.fit_transform` only on `train_X`; `score_logistic()` (`:78-81`) calls `.transform` only (no `.fit`) on dev_X/test_X. `fit_gbt()` (`:84-88`) fits `HistGradientBoostingClassifier` on `train_X`/`train_y` only; dev/test scores come from `predict_proba` with no re-fit.

4. **`select_best()` uses only 2025 economics?** Yes. `select_and_attribute.py:44` filters `econ.split == "2025"` before any ranking; `dev_row`/`test_row` are pulled separately in `main()` (lines 150-155) with `test_row` (2026) computed strictly after `best` is already fixed, and never fed back into `select_best()` or `apply_gate()`'s `dev_improves` check.

5. **`build_schedule()` causal (no look-ahead to "best" checkpoint)?** Yes. `layer2_policy.py:39-43` sorts by `(regime_start_ns, observation_time)` ascending, then takes the first row per regime whose own score already clears the frozen cutoff (`groupby(...).first()` on a pre-filtered, time-sorted frame). This always resolves to the temporally-first eligible checkpoint — it never compares candidate checkpoints against each other's future-realized outcome to pick a "best" one.

6. **W4 comparator never mixed into 2021-2024 training rows?** Confirmed. `train_and_evaluate.py:159-176` loads W4 scores only from the 2025/2026 `CODEX_5_X_repaired_w4_scores_*.parquet` files and merges them only onto `dev_df`/`test_df`; `train_df` (2021-2024) never has a `w4_score` column. `direction == 1` filtering correctly selects the prevailing-bullish (short-fade) rows per the atlas's documented `{-1, +1}` domain (`CODEX_5_X_train_repaired_w4.py:55-56, 105-106`), consistent with this being a short-only study.

7. **Label leakage in the 149 features?** None found. `FEATURE_COLS = CENTER_FEATS + SEQUENCE_FEATS` (imported from `train_weakness_model.py`) contains no `net_pnl`, `exit_reason`, or current-trade MFE/MAE fields. Two feature names contain "mfe" (`seq_Kr_mean_retracement_mfe`, `seq_Kr_asym_mfe`); tracing their definition in `build_regime_sequence.py:5-27` shows they are computed exclusively from `df_regimes` rows with `end_time <= checkpoint_ts` (i.e., MFE of **prior, already-completed** regimes), which is causal by construction, not an outcome of the row's own hypothetical trade.

## Clean checks

- A2/F3 — 1-second bars loaded via `RAW_1S[year]` with no `ts_init_delta` shift applied, consistent with the project convention that 1s bars need no adjustment.
- B1/B4/B5/B7 — no `rolling(center=True)`, no `.shift(-N)` in the feature path, no `.ffill()`/`.bfill()` in these five files; logistic-regression standardization is fit train-only (see Item 3 above).
- C3 — split is a fixed temporal partition (2021-2024 train / 2025 dev / 2026 test); no `cross_val_score` or random splitter used anywhere.
- D2/D3/D4 — one fitted model object per family is reused (not re-fit) to score all three splits; feature ordering (`FEATURE_COLS`) is a single shared list imported identically in `phase0_prepare_data.py` and `train_and_evaluate.py`.
- Phase 0 gate — re-ran/inspected `results/phase0_manifest.json`: `decision: PHASE0_PASS`, 100% join rate for all of 2021-2026, 0 label errors, combined 2021-2024 row count 813,972 matches SPEC's stated figure exactly.
- H1-H4 (bracket-sim price resolution) — out of scope for re-derivation per task instructions; the five audited files import `label_full_surface.label_row`/`add_derived_targets`/`data_quality_checks` **unmodified** (verified: single canonical copy of `label_full_surface.py` exists under `short_rth_entry_surface_backfill/`, no shadow/forked copy found via filesystem search), so no new H-class risk is introduced by this study — contingent on that upstream module's own prior audit remaining valid.
- Sign-error self-fix — confirmed present and consistent: `select_and_attribute.py:85-89` (`net_pnl_saved_from_avoided_stops`) and the analogous `net_pnl_saved_from_removed_losers` (line 96) both correctly negate a negative-PnL subset sum to report a positive "saved" quantity; `net_pnl_lost_from_removed_winners` (line 91) correctly reports the positive foregone-gain sum unnegated.
- Internal consistency spot-check — `economic_results.csv` shows identical economics (1,678 trades, net -$10,613) across `logreg`/`gbt`/`w4_comparator` at `retention_band == 1.0` for split `2025`, as expected since 100% retention performs no score-based filtering regardless of model — confirms the three scoring pipelines share the same underlying candidate population and Layer-2 mechanics.

---

*Audit complete. Findings reflect read-only static analysis of the five named files plus the direct imports needed to resolve feature/label provenance. Dynamic bugs and the correctness of the upstream `label_full_surface.py` Policy A simulator itself are out of scope per task instructions (already audited in `short_rth_entry_surface_backfill`).*
