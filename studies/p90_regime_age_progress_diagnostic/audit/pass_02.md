# Look-Ahead & Timestamp Audit — Pass 02

**Date:** 2026-08-13
**Scope:** `implementation/{analysis,contract,outcomes,population,validate}.py`, `run_study.py`,
`REPORT.md`, `SPEC.md` (deliverable/denominator sections only), `tests/test_diagnostic_contracts.py`,
`results/*.json`, `results/*.csv`, `results/p90_events.parquet`.
**Scope hash:** `178cfb863cb26d105b670957e2a5bf4300d81ab0eb08a02d9b2b95d785efbfc1`
**Lint:** not re-run this pass (no lint-scope files changed since pass 01's 0/0); results/ is generated data, out of lint scope.
**Verdict:** BLOCKED

## Summary
- Critical: 1
- Warning: 0
- Note: 1

## Prior findings adjudicated

| # | Prior finding | Status | Evidence |
|---|---|---|---|
| 1 | CRITICAL: `validate.py` `classify()` aliased empty `fired` to `D5_NOTHING_CHANGES` | **RESOLVED** | `validate.py:213-216` now returns `"D0_UNCLASSIFIED"` with an explanatory comment citing pass 1; `unclassified` flag added. `summary.json`'s actual run fired `[D3, D4, D5]` (not empty), so D0 wasn't exercised this run, but the code path is correct and distinct from D5. SPEC 6.2 unchanged in scope, not re-checked (contract-checker territory). |
| 2 | WARNING: `population.py:48-78` `arm_population` reimplemented the accepted filter and dropped the full-population guard | **RESOLVED** | `population.py:82-84` now imports and calls `_assert_arming_population_is_complete` from the accepted `arming.py` module (not reimplemented). `tests/test_diagnostic_contracts.py:88-128` (`test_matches_accepted_arm_rule_at_600s`) directly diffs this module's output against `arming.ACC.arm_population` on a 4-regime synthetic frame covering crossing/no-predecessor/below-gate/late-predecessor branches and asserts row-for-row equality — verified present and correctly scoped. |
| 3 | NOTE: `contract.py` age-column name divergence (`regime_age_seconds` vs `seconds_from_regime_start`) | **RESOLVED** | `contract.py:74-80,124` adds `age_column_identity` row; `phase0_contract.json` row 16 reports `"0 disagreements"`, `match: true` on the real store. |
| 4 | NOTE: `analysis.py` docstring denominator imprecision | **RESOLVED for the case raised** | `analysis.py:7-19` now documents three denominators explicitly with `n_flip_censored` disclosure. **However, this pass found the docstring's *third* denominator claim ("over CONFIRMERS only ... `return_at_confirm_*`") is not actually enforced in code — see new CRITICAL below.** This is a materially different, newly-discovered defect in the same area, not a re-raise of the resolved NOTE. |

## Critical findings

### [analysis.py:68-74, outcomes.py:144-146] `return_at_confirm_atr`/`mae_to_confirm_atr` are pooled over STOPPED trades, not confirmers-only, contradicting SPEC §6.1 and the study's own headline table
`outcomes.py:144-146` copies `mae_to_confirm_atr`/`return_at_confirm_atr`/`seconds_to_confirm` from the walk engine's return dict **unconditionally**, regardless of `confirmed` (line 142-143). The walk engine populates these fields for `STOPPED_BEFORE_CONFIRM` trades too (measured at the stop, not a confirmation). `analysis.py:68-74` aggregates them with bare `.median()`/`.quantile()`/`.mean()`, which only null-skips — it does **not** filter on `confirmed`. This directly contradicts `analysis.py:15-19`'s own docstring and `SPEC.md:371-372` ("median_return_at_confirm ... are over **confirmers only** and carry `n_confirmed` alongside").

**Failure path (measured on the real output, population A, `>900s` bucket):**
- Non-confirmed rows with a non-null `return_at_confirm_atr`: **2,950** (all `STOPPED_BEFORE_CONFIRM`), vs `n_confirmed`=3,325.
- True confirmers-only median return: **0.8327**; true confirmers-only mean: **0.8946**.
- What is actually emitted as `median_return_at_confirm` in `age_contrast.csv`/`primary_matrix.csv`/`outcome2_confirmation.csv`/`velocity_table.csv`/`population_comparison.csv`/`year_side_stability.csv`: **0.5579** median, **0.0508** mean — computed over the pooled 6,408-row `>900s` population (stops included), not the 3,325 confirmers `n_confirmed` sits next to.
- Same pattern in `300-600s`: confirmers-only median **1.1170** vs the emitted (pooled) **0.7770** — a ~44% overstatement error in the *other* direction relative to the true confirmers-only figure.

This is not hypothetical: **REPORT.md §4's own table is internally self-contradictory as a direct result.** Its Young/Old columns (0.777 / 0.558) are copied from the leaky pooled `age_contrast.csv`, but its Δ (**+0.2843**) matches *only* the true confirmers-only difference (1.1170 − 0.8327 = 0.2843) — i.e. 0.777 − 0.558 = 0.219 ≠ the printed 0.2843. The bootstrap script (correctly) filtered to confirmers; the point-estimate columns pasted next to it did not. `median_return_at_confirm` is listed as **THE MAIN DELIVERABLE**'s 4th data column (SPEC.md:347, `primary_matrix.csv`), so this is a wrong number in the headline artifact, not an ancillary one.

**Smallest fix:** in `outcomes.py`, null `mae_to_confirm_atr`/`return_at_confirm_atr`/`seconds_to_confirm` when `not confirmed` (mirroring the existing `eventual_max_mfe_atr` gating at line 149-161), or add an explicit `.filter(pl.col("confirmed"))` before the three aggregations at `analysis.py:69-74`. Then re-run and re-verify `median_return_at_confirm` against `n_confirmed` in every downstream CSV and REPORT.md §2-§7.

## Warnings
None new this pass.

## Notes
- `analysis.py:64-65`'s `p_stopped`/`p_session_unresolved` correctly use `terminal_label ==` string comparisons over all arms (unaffected by the above — those are genuinely all-arms metrics per SPEC and match their documented denominator).

## Referred to contract-checker
- None new this pass (the D1-D5 exhaustiveness question from pass 1 remains referred and is not re-raised).

## Clean checks
- 21/21 `validation_report.json` gates verified to test what their names claim: `V_PARITY_population_b_8950` reproduces the accepted 8,950-arm population exactly; A/B reconciliation `8,596 (same-ts) + 354 (diff-ts) + 239 (only-A) = 9,189 = n_a`, and `8,596 + 354 = 8,950 = n_b`, `n_only_b = 0` — all coherent and matching `population_lineage.json`.
- `results/*` and `p90_events.parquet` contain no `entry_year == 2026` (`p90_events.parquet['entry_year'].unique()` = `[2021..2025]`); the only string occurrences of "2026" are disclosure labels (`"2026 SEALED"`, gate name `V_SEALED_no_2026`).
- Retrospective columns (`seconds_to_prevailing_flip`, `eventual_max_mfe_atr`, `flip_le_*`, `mfe_ge_*`) confirmed absent from every `group_by`/`filter` call in `analysis.py`, `outcomes.py`, `population.py`, `validate.py` — appear only as emitted outcome columns.
- 40-cell grid confirmed complete with empty cells retained (`primary_matrix.csv`/`outcome1_target.csv`/`outcome3_opportunity.csv` all show `120-240s`/`240-300s` × every mfe_bucket rows for population B as `n=0, thin_cell=true`, not dropped).
- Every REPORT.md-quoted number outside §4 (Phase 0 contract table, §2 eligibility/qualify-rate table, §3 primary matrix, §5 year/side table, §6 velocity table, §7 A/B table, the 12.3%/19.5% extrapolation figures, the −0.079 session-remaining correlation) reconciled exactly to `phase0_contract.json`, `p90_eligibility_base_rates.csv`, `first_eligible_age_by_regime.csv`, `primary_matrix.csv`, `year_side_stability.csv`, `velocity_table.csv`, `population_comparison.csv`, and direct recomputation from `p90_events.parquet` (session-remaining medians 8752.5/9932.5/11652.5s, corr −0.0794).
- REPORT.md §4's bootstrap CI table is correctly labelled "Bootstrap 2,000 draws, seed 20260813... *Supplementary robustness check, not a SPEC deliverable*" and is not listed in SPEC.md's Deliverables Manifest — labelling verified correct (its Young/Old *values*, not its supplementary status, are the defect above).
- A1-A5, B1-B10, C1(new observations), C3, F1-F4, G1-G4, H1-H4: no new violations in the results-generation surface; entry price/ATR/session logic unchanged from pass 1's clean findings.
