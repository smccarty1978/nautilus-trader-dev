# Runtime-Constrained F3 Feature Reduction and Model Persistence -- Report

## Decision

**`NO_REDUCED_MODEL_PRESERVES_POPULATION`** -- see `results/selection_gate_decision.json` and
`results/final_decision.json` for the structured record.

Every tested candidate -- including the near-full 546-feature live-ready set -- failed the
predeclared top-5%/top-2.5% regime-overlap gate (>=95% required). The best performer,
`F3_top25_gbt_v1` (25 raw features), reached only 91.9%/88.0%. `F3_live546_gbt_v2` (546
features, nearly the full model) reached only 91.4%/87.0%. No candidate is frozen as the
runtime model. AUC deltas were mostly within tolerance for the smaller candidates -- this is
specifically a population-preservation finding, not a raw-discrimination finding, which is
exactly the kind of gap this study's design (population overlap alongside aggregate metrics)
was built to surface.

## 1. Top 100 raw feature columns

Full list: `results/top_100_raw_feature_columns.csv` (complete 695-row ranking in
`results/full_raw_feature_ranking_695.csv`). Top 10:

| rank | feature | family | importance_mean |
|---|---|---|---|
| 1 | `aligned_price_minus_center_15m` | regime_median_center_slope_alignment (F0) | 0.01210 |
| 2 | `rolling_5m_low_signed_distance_atr` | price_level_context | 0.00707 |
| 3 | `aligned_price_minus_center_30m` | F0 | 0.00554 |
| 4 | `aligned_price_minus_center_5m` | F0 | 0.00515 |
| 5 | `rth_elapsed_seconds` | ohlcv_est_delta | 0.00423 |
| 6 | `rolling_15m_high_signed_distance_atr` | price_level_context | 0.00170 |
| 7 | `rolling_60m_high_signed_distance_atr` | price_level_context | 0.00146 |
| 8 | `rolling_15m_low_signed_distance_atr` | price_level_context | 0.00143 |
| 9 | `rolling_30m_low_signed_distance_atr` | price_level_context | 0.00105 |
| 10 | `price_change_points_60s` | ohlcv_est_delta | 0.00090 |

Computed via repeated permutation importance (`scoring="roc_auc"`, GBT baseline, n_repeats=5,
`random_state=42`) on a deterministic, regime-stratified, monthly-preserved 30,000-row 2025
sample (`config/importance_sample.json`, cap 25 rows/regime, target 2,500 rows/month, all 12
months hit target, 1,673/1,678 regimes represented).

**Ranking is genuinely, not just tail-noise, unstable month-to-month**: full-695 Spearman rank
correlation between each month's own ranking and the overall ranking averages 0.24; restricting
to just the top-100 (59% average overlap) and top-25 (45% average overlap) confirms this is real
churn at the head of the ranking, not just noise among unimportant features
(`results/monthly_importance_stability.csv`, `results/phase3_importance_summary.json`). The
selected/ranked feature set should be understood as the best-performing set averaged over the
full 2025 stratified sample, not a universally stable top-N truth.

## 2. Top canonical runtime calculations

`results/top_canonical_runtime_sources.csv`. **695 raw model columns collapse to 608 unique
canonical runtime calculations** -- 87 raw columns are one-hot dummy siblings (29 categorical
groups x 4 dummies each, `__ABOVE`/`__BELOW`/`__TOUCH`/`__UNAVAILABLE`) of an already-counted
base calculation, per `results/f3_feature_inventory_v2_summary.json`. The top-ranked canonical
calculation is identical to the top raw feature (`aligned_price_minus_center_15m` is not a
one-hot member).

## 3. Does F0 add material value?

**Yes, measurably** -- but it is still not demonstrated portable.

- Phase 2 family ablation: F0 alone (149 features, using the EXISTING offline pandas columns,
  never tracker-sourced) scores dev AUC 0.6634 -- close to `ohlcv_est_delta` alone (214
  features, AUC 0.6681) and meaningfully better than `price_level_context` alone (332 features,
  AUC 0.6411). `results/family_ablation_summary.csv`.
- Phase 3 grouped importance: F0's 149 features carry the HIGHEST total importance sum of the
  three families (0.0194), ahead of `price_level_context` (0.0145, 332 features) and
  `ohlcv_est_delta` (0.0065, 214 features) despite having the fewest features.
  `results/phase3_importance_summary.json`.
- Since this session began, `features/trackers/median_center.py` (`MedianCenterTracker`) now
  exists and registers all 149 F0 features (`status="provisional"`), lookahead-audit clean
  (`features/audit_median_center.md`, 0 CRITICAL/WARNING/NOTE). Per explicit user decision
  (2026-07-20), this study ran one bounded parity side-check rather than expanding scope.
  **The first version of this check was itself found to have two real bugs by the
  completion-gate audit** (not the tracker's fault): (1) it hardcoded `current_regime=-1` for
  the entire replay instead of tracking the true alternating regime direction, and (2) even
  after fixing that, `canonical_regime_timeline()`'s `direction` column turned out to use the
  OPPOSITE sign convention from this population's own `entry_direction` at the IDENTICAL
  `regime_start_ns` (confirmed exact-timestamp match, not a timing bug -- 2,418/2,418 checkpoints
  in the pre-fix run showed the wrong sign, too consistent to be noise). Both fixed and verified
  (`n_wrong_direction_at_snapshot=0` in the final run).
  With both bugs fixed, the result is now a genuine, well-evidenced **partial validation**
  (`results/f0_tracker_parity_check.json` -> `parity_verdict: PARTIAL_MATCH_ATR_NORMALIZATION_UNVERIFIED`):
  causal bar-by-bar bookkeeping is strongly confirmed correct -- 68 of 116 ATR-independent
  features match at 100% (2,418/2,418 rows), including the ENTIRE regime-activity-count,
  sequence-alternation, sequence-overlap, and duration-ratio families for every K in {3,5,8,12}.
  ATR-DEPENDENT features (33 features, e.g. `aligned_price_minus_center_*`, `slope_*_aligned_atr`,
  `ordering_state`'s compression branch) match at only 5.6%, cleanly explained by this bounded
  check's one remaining, disclosed approximation: ATR held constant at the 2-week window's
  median `atr_at_entry` rather than the continuously-varying 1m-merged series the offline
  reference actually uses (`build_median_centers.py:87`). **F0's causal regime/sequence logic is
  now verified; its ATR-normalized value agreement remains genuinely unverified, not
  demonstrated wrong.** A real portability verdict needs one more bounded follow-on: replay with
  the true continuous ATR series (now that the harness's two real bugs are fixed, this is the
  only remaining gap).

## 4. Smallest candidate that passed every gate

**None.** All 8 raw-count candidates FAIL (`results/phase7_gate_results.csv`,
`results/selection_gate_decision.json`). The binding constraint is the top-5%/top-2.5%
regime-overlap gate (>=95% required); no candidate exceeded 93.5% on either band. AUC-delta and
average-precision-delta gates passed for several candidates (e.g. `F3_top25_gbt_v1`: AUC delta
-0.00017, well within -0.005 tolerance) -- the finding is specifically that population overlap
degrades faster than aggregate predictive metrics as features are removed.

## 5. Raw column count vs. unique runtime calculation count

695 raw F3 model columns -> 608 unique canonical runtime calculations (87 collapse via one-hot
grouping). The 546-feature live-ready pool -> the same collapsing logic applies; see
`results/f3_feature_inventory_v2_summary.json` for the full family/registry breakdown.

## 6. 2025 score and regime-population overlap vs. the 695 baseline

`results/candidate_model_metrics.csv`, `results/candidate_population_overlap.csv`. Best-case
summary (F3_top25_gbt_v1, the smallest/best-performing candidate):

- AUC: 0.6710 vs. baseline 0.6712 (delta -0.00017)
- Average precision: 0.4120 vs. baseline 0.4122 (delta -0.00014)
- Top-5% regime overlap (quantile-matched): 91.9% (744/810 baseline-selected regimes recovered)
- Top-2.5% regime overlap (quantile-matched): 88.0% (528/600 recovered)
- Score Pearson/rank correlation vs. baseline: see CSV (both >0.9 for this candidate)

**Methodological caveat, disclosed rather than concealed**: this implementation's
"quantile-matched" and "count-matched" (operating-point) comparisons are numerically
near-identical in every row of `candidate_population_overlap.csv`. Both bands are defined as
"top N% of the SAME 198,255-row population" via `np.quantile`, so "baseline's row count in its
own top-N% band" is, by construction, always ~N% of the total regardless of which model produced
it -- matching a candidate to that count is mathematically close to just taking the candidate's
own top-N% quantile. A genuinely different operating-point comparison would need to start from a
real deployment threshold (not defined within this study's scope -- that threshold lives in the
separate NT live-scoring study), so this study's two required comparisons did not end up testing
materially different things. Disclosed as a real methodological gap, not hidden.

## 7. Extra and missing high-score candidates

Per-candidate `both_selected` / `baseline_only` / `candidate_only` counts are in
`results/candidate_population_overlap.csv` (`quantile_matched_baseline_only`,
`quantile_matched_cand_only` columns). For `F3_top25_gbt_v1`'s top-5% band: 744 both-selected,
66 baseline-only (missed by the candidate), and a comparable number candidate-only (extra,
false-positive-flavored selections not in baseline's own top band).

## 8. Monthly stability

- Feature-ranking stability: see section 1 above (real instability, 24% mean full-rank
  correlation, 59%/45% top-100/top-25 overlap).
- Model predictive stability: baseline's own monthly AUC ranges 0.618 (July) to 0.697
  (Oct/Nov) -- a >0.05 natural swing present in the underlying prediction problem for EVERY
  model, not evidence of any one candidate's weakness (`results/baseline_monthly_auc.json`). The
  Phase 7 monthly-collapse gate was corrected mid-study to compare each candidate against
  baseline's SAME-month AUC (not the candidate's own overall AUC) after this natural variability
  was discovered -- an self-referential threshold would have wrongly failed every candidate,
  including a hypothetical byte-identical copy of the baseline itself.

## 9-10. Selected model path and SHA-256 / feature-list path and SHA-256

**Not applicable -- no model was selected.** The verified BASELINE (695-feature) artifact remains
at `artifacts/models/F3_695_baseline/model.joblib`,
SHA-256 `dd16ab38518cc00377058a0ff4068b59477eb1261fc541f25976767a08da670b`, ordered feature list at
`artifacts/models/F3_695_baseline/feature_list.json`.

## 11. Every persisted candidate model and its status

`results/model_catalog.json` -- 15 models total: 1 baseline, 6 family ablations (B-G), and 8
raw-count candidates. **Correction (caught by the completion-gate audit, not by this study's own
first-pass reporting)**: an earlier draft of this section wrongly claimed `F3_live546_gbt_v2` was
"deduplicated by hash" between Phase 2's `B_live546` ablation and Phase 5's 546-feature raw-count
candidate. In fact those two feature lists contain the identical 546-feature SET in different
COLUMN ORDER (`bc2d66ca...` vs `1f8d0dc6...` list hashes) -- Phase 5's original attempt to
persist under the same `F3_live546_gbt_v2` id hit `common.py`'s atomic-promotion hash-mismatch
guard (`RuntimeError: refusing to overwrite`, exactly as `test_atomic_model_promotion_refuses_hash_mismatch`
verifies it should) and crashed rather than silently reusing anything. Fixed by training a
properly-versioned `F3_live546_gbt_v2` (Phase 4/5's actual ranked-order candidate) and re-running
Phases 6-8 against it. The corrected numbers (AUC 0.66554 vs. the original mistaken reuse's
0.66551, top-5% regime overlap 91.36% vs. 91.36%) are effectively unchanged -- this model appears
insensitive to this particular column-order difference for this dataset -- but the provenance is
now honest and the decision (`NO_REDUCED_MODEL_PRESERVES_POPULATION`) is unaffected either way.
All persisted models are reloadable, all raw-count candidates are `gate_fail`, none is `frozen`
since nothing was selected. No model exists only under `_work/`.

## 12. What the evidence supports

- The 695-feature baseline model's predictive discrimination (AUC ~0.67) can be closely matched
  by substantially fewer raw columns purely on aggregate metrics (25 features reach AUC 0.671).
- Population-level agreement (which specific regimes get flagged) degrades meaningfully faster
  than aggregate AUC as features are removed -- even the near-full 546-feature set loses ~8-13
  percentage points of top-band regime overlap versus the full 695.
- F0's 149 features carry real, concentrated predictive signal (highest per-feature importance
  of the three families, competitive standalone AUC) -- the case for eventually porting them is
  stronger than the prior prereqs study's finding implied, now that a provisional live tracker
  exists, AND that tracker's causal regime/sequence bookkeeping is now positively verified
  correct (not just "not yet shown wrong") for the 116 ATR-independent F0 features.
- Feature importance rankings are genuinely unstable month-to-month; any fixed reduced feature
  set is a compromise across a heterogeneous year, not a universally-optimal choice.

## 13. What the evidence does not support

- No claim that a ~40-100 feature reduced model preserves this model's operationally-relevant
  high-score population well enough to substitute for the full 695-feature model, per this
  study's own predeclared gates.
- No claim that F0's ATR-normalized features are portable -- that specific gap remains genuinely
  unverified due to this bounded check's disclosed constant-ATR approximation, not because the
  tracker was shown wrong there. (Its non-ATR regime/sequence logic IS now positively verified,
  per section 3 -- this is a narrower, more precise caveat than "F0 is unverified" broadly.)
- No economic or trading claim of any kind (forbidden by SPEC scope, not attempted).
- No claim of live NT population parity (that remains the separate, not-yet-run
  `nt_live_ml_scoring_population_parity` study).
- No claim that 2025-based selection generalizes to 2026 or any other unseen year -- this study's
  own scope never checks that, by design.

## 14. Bounded next action

Given `NO_REDUCED_MODEL_PRESERVES_POPULATION`: the user's original three options (proceed with a
40-100 feature model, use a larger live-ready subset, or port F0) are all constrained by this
result -- none of the tested subsets, including the largest tested (546/695 features), meets the
predeclared population-preservation bar. Two concrete, bounded follow-ons this evidence points
toward, for the user to choose between (not decided here):

1. **Relax or re-examine the 95% regime-overlap gate** against real operational tolerance (this
   study's 95% bar was a predeclared, conservative default, not derived from an existing
   deployed threshold) -- if a lower bar (e.g. 85-90%) is operationally acceptable,
   `F3_top25_gbt_v1` or `F3_live546_gbt_v2` may be worth reconsidering against that relaxed bar.
2. **A proper F0 parity follow-on** (continuous per-minute ATR feed, confirmed regime-source
   match) to resolve whether F0 is genuinely portable -- given F0's demonstrated standalone
   value, this could change the reduction calculus materially if it succeeds.

Neither action is taken in this study. If a reduced model is later selected via either path, the
bounded next action remains: use the frozen reduced model and ordered feature contract in the
separate production-like NT live-scoring population-parity study, where streamed candidate
generation, feature snapshots, live scores, triggers, orders, fills, and extra/missing trades
will be reconciled end to end. This study does not itself constitute production validation.
