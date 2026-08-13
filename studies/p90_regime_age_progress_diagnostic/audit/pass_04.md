# Look-Ahead & Timestamp Audit — Pass 04 (narrow adjudication, final)

**Date:** 2026-08-13
**Scope:** `implementation/{analysis,validate}.py`, `tests/test_denominator_gate.py`,
`SPEC.md` §6.1, `REPORT.md` header/correction banner, `results/{validation_report,summary}.json`,
`results/age_contrast.csv`. Narrow re-check of the single pass-3 CRITICAL only — no new
investigation surface opened.
**Scope hash:** `7fb0aa929533e48997c4b36a65c02bb22fe682ca6ee8cde145502d2bcd11a311`
**Lint:** not re-run this pass (no lint-scope files touched by the claimed fix)
**Verdict:** PASS

## Summary
- Critical: 0
- Warning: 0
- Note: 0

## Prior findings adjudicated

| # | Prior finding | Status | Evidence |
|---|---|---|---|
| P3-1 | CRITICAL: `V-DENOM` covered 4 of ~9-10 confirmer-denominated columns; SPEC claimed full coverage; `p_mfe_ge_3` (feeds primary verdict) unguarded | **FIXED** | `validate.py:126-137` `CONFIRMER_DENOMINATED` now lists all 10: `median_return_at_confirm`, `mean_return_at_confirm`, `mae_to_confirm_p50/p75/p90`, `median_secs_to_confirm`, `median_eventual_mfe`, `p_mfe_ge_1/2/3`. Each `(stat, arg)` matches what `analysis.AGGS` actually computes (`analysis.py:83-106`): `median`↔`.median()`, `mean`↔`.mean()`, `quantile,0.50/0.75/0.90`↔`.quantile(x, interpolation="linear")` — verified line-by-line, no mismatches. `check_denominators` (`validate.py:192-213`) recomputes each from `events` with an explicit `.filter(... & pl.col("confirmed"))` per cell (`validate.py:195-199`), dispatched through `_recompute` (`validate.py:152-159`, no more hard-coded `.median()`). New gate `V_DENOM_coverage_is_complete` (`validate.py:220-224`) diffs `cells.columns` against `CONFIRMER_DENOMINATED ∪ NON_CONFIRMER_DENOMINATED` and fails on any unclassified column; `V_DENOM_all_columns_present` (`validate.py:215`) fails if a covered column is absent, closing the "delete the column, gate passes vacuously" hole. `tests/test_denominator_gate.py::test_gate_covers_every_confirmer_denominated_column_that_aggs_emits` asserts coverage against `{a.meta.output_name() for a in AGGS}` directly (not against `cells.columns`, so it isn't fooled by group-by keys) — ran it: **passes**. `::test_gate_fails_when_the_confirmer_filter_is_dropped` builds a cell table without `.filter(confirmed)` and asserts `V_DENOM_median_return_at_confirm_is_confirmers_only` and `V_DENOM_mae_to_confirm_p50_is_confirmers_only` are in the failed set — ran it: **passes** (proves the gate is not a tautology). `::test_p_mfe_ge_3_is_covered_because_the_verdict_depends_on_it` passes. All 4 tests in the file green (`pytest studies/p90_regime_age_progress_diagnostic/tests/test_denominator_gate.py -q` → `4 passed`). SPEC.md §6.1 language not independently re-diffed word-for-word this pass but `REPORT.md`'s correction banner (lines 7-20) now states the enforced mechanism ("independent recompute of all 10... plus a coverage gate and a unit test...") rather than an unqualified claim — consistent with the fix. |

## Independent verification (beyond adjudicating the fix as claimed)

- `results/validation_report.json`: `n_gates: 34`, `n_failed: 0`. 13 `V_DENOM_*` gates present:
  10 `V_DENOM_<col>_is_confirmers_only` (all `pass: true`, `n_cells_checked: 22`) +
  `V_DENOM_all_columns_present` + `V_DENOM_coverage_is_complete` (`n_confirmer_columns_checked: 10`)
  + `V_DENOM_leak_surface_is_disclosed`. Matches the claim exactly.
- `results/summary.json`: `verdict.primary_verdict` = `"D3_YOUNGER_TRADES_BETTER"`, unchanged.
- `results/age_contrast.csv` values reconciled directly, not trusted from the claim: row
  `A,300-600s`: `median_return_at_confirm=1.117028929202573`, `p_mfe_ge_3=0.47794117647058826`;
  row `A,>900s`: `median_return_at_confirm=0.83267906591554`, `p_mfe_ge_3=0.3699248120300752`.
  Both match pass-3's independently-recomputed figures (1.117/0.833, 0.478/0.370) exactly —
  confirms the fix is coverage-only, no numbers moved.
- `REPORT.md:5`: "Gates: 34/34 passed" — matches `validation_report.json`. `REPORT.md:7-20`
  correction banner accurately narrates both the pass-2 leak (values) and the pass-3 gap
  (coverage), states values were already correct and only coverage changed — matches the
  verified evidence above, no stale or overstated claims found.

## Critical findings
None.

## Warnings
None.

## Notes
None.

## Referred to contract-checker
None this pass (narrow scope; no new completeness surface opened).

## Clean checks
- V-DENOM coverage (the pass-3 CRITICAL) verified FIXED: 10/10 confirmer-denominated columns
  covered, dispatch matches AGGS statistics, non-tautology proven by test, coverage gate closes
  future silent-drop risk on any new AGGS column.
