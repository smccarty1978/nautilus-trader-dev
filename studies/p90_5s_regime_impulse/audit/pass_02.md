# Look-Ahead & Timestamp Audit — Pass 02

**Date:** 2026-08-12
**Scope:** `SPEC.md` (§2.1, §3, §4.3-4.4, §8), `implementation/regime_5s.py`,
`implementation/policy.py`, `implementation/lineage.py`, `implementation/analysis.py`,
`implementation/validate.py`, `run_study.py`, `tests/test_regime_5s_parity.py`;
read-only reference to shared `studies/model_driven_entry_exit_discovery/implementation/engine.py`
(unchanged, not re-litigated).
**Scope hash:** `c6faf020a87fcf7be32f262ac9baf03ad7c85f18fa6a7a032a9cee74c4a1e704`
(sha256 over ordered filenames + contents of the 8 files above; changes from
pass 1's `df23824655645abe54fcbe21e70369a424c05906053b1b18e1596500de0a3bc4`
because `regime_5s.py` and `SPEC.md` were edited)
**Lint:** 0 critical / 0 warning (`causal_lint.py`, 10 files scanned)
**Verdict:** PASS

## Summary
- Critical: 0
- Warning: 0
- Note: 0

## Prior findings adjudicated

| # | Prior finding | Status | Evidence |
|---|---|---|---|
| 1 | [G] `regime_5s.py::main()` did not discard the final partial 5s bucket despite claiming to | **FIXED** | `regime_5s.py:205-206` now computes `final_bucket_n_1s` and sets `buckets = all_buckets.head(n_slots - 1)` *before* `apply_regime`/`flip_timeline` run — the same truncation the parity test applies (`test_regime_5s_parity.py:81`). `main()` truncates before applying the EMA/sticky recursion rather than after; since the recursion at index `i` depends only on rows `<= i`, this is equivalent to the test's apply-then-truncate order for every retained row. Metadata is now computed, not hardcoded: `final_partial_bucket_discarded": bool(n_buckets == n_slots - 1)` (`regime_5s.py:249`). Rebuilt artifact confirms: `buckets_built=18,774,838`, `buckets_expected_closed=18,774,838` (`=expected_slots-1`), `final_partial_bucket_1s_rows=1`, `rows_reconcile=true`, `regime_changes=2,054,398` (unchanged from pass 1, as expected — see below). Independently re-verified the discarded bucket is still inert: last surviving flip's `close_ts` = `2025-12-30 23:59:50` UTC (≈17:59:50 CT), ~3 hours past the 15:00 CT RTH session close every arm's exit is capped at (`policy.py:117-121,138`), so no arm/entry/exit can reach the dropped slot. Also confirmed against `collectors/collector_v2/aggregator.py`'s own docstring ("does NOT close the final partial bucket... discarded for safety") that the fix's rationale is the real aggregator's documented behavior, not an assumption about row counts. Full parity suite re-run: 7/7 passing. |
| 2 | Referred to contract-checker — SPEC §2.1 named a non-existent `arming.py` loader | **WITHDRAWN (confirmed closed, contract-checker's finding not mine)** | `SPEC.md:64-68` now correctly attributes this study's loader as `implementation/lineage.py::load_arms` (verified present at `lineage.py:55`) and clarifies `arming.py::arm_population` belongs to the upstream `armed_fade_score_path_progression` study, not this one. Text now accurately describes the code. This was contract-checker's item; noting resolution for completeness, not re-adjudicating on causal grounds. |

## Re-verification of the seven load-bearing claims (current tree)

All seven claims from pass 1 were re-checked against the current tree, since
`regime_5s.py` — the module `Regime5s` is built from — changed:

1. **5s bucket = `(C-5s, C]`.** Unchanged bucketing logic (`regime_5s.py:61-75`); `test_bucket_contains_only_past_bars` re-run, passes. **Holds.**
2. **Entry strictly after arm.** `policy.py:113` unchanged (mtime predates this pass's edit). **Holds.**
3. **5s exit strictly after flip bucket close.** `policy.py:128-138` unchanged. The truncation fix removes one *ineligible* trailing bucket from the searchable timeline; it cannot advance any `first_non_aligned_after` result earlier, only (harmlessly, per point 1 above) shrink the searchable tail by one row that no query ever reached. **Holds.**
4. **Stop trigger/fill separation, no trigger-price credit.** `policy.py:150-173` unchanged. **Holds.**
5. **1m confirmation excluded from `OUTCOMES`.** `policy.py:35-40,189-198` unchanged. **Holds.**
6. **MFE/MAE indexed at trigger, not fill.** `policy.py:174,181,187,205-206` unchanged. **Holds.**
7. **Vectorised ≡ replay parity.** Re-run: `pytest studies/p90_5s_regime_impulse/tests/test_regime_5s_parity.py -q` → **7 passed**. The test's own truncation (`.head(buckets.height - 1)`) and `main()`'s truncation are now the same operation for the same reason, closing the gap pass 1 flagged. **Holds, and the underlying discrepancy pass 1 noted is gone.**

## Critical findings
None.

## Warnings
None.

## Notes
None. (Pass 1's single NOTE is resolved per adjudication table above, not restated.)

## Referred to contract-checker
None new this pass.

## Clean checks
A1-A5, B1-B7/B9/B10, C1-C3, F1-F4, G1-G4, H1-H4 verified clean on the current
tree. `regime_5s.py`'s build-metadata reconciliation (`buckets_reconcile`,
`rows_reconcile`) is now a real invariant computed from the truncated build,
not an assertion — re-verified true against the current parquet.
