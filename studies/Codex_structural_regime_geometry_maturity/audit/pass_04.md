# Look-Ahead & Timestamp Audit — Pass 04

**Date:** 2026-08-14T07:38:18.189856-05:00  
**Scope:** 23 files: the unchanged collector/aggregator/tracker causal surface; the post-pass-03 run, selection, validation, evaluation, reporting, and promotion changes; their study tests; and the inherited Walk-A outcome/market engines needed to resolve label and timestamp flow.  
**Scope hash:** `04b7d273d28f08009c63f61fa1a98dd0df83655572bf1ec9c58727cef6846272`  
**Lint:** 0 critical / 0 warning from `causal_lint.py`  
**Verdict:** BLOCKED

## Summary

- Critical: 0
- Warning: 1
- Note: 0

## Prior findings adjudicated

| # | Prior finding | Status | Evidence |
|---|---|---|---|
| 1 | [A1/A5] Equal-time 5m snapshots omitted the bucket that just completed | FIXED | `implementation/collector.py:59-73` still consumes the eligible completed 1s bar, calls `finalize_through(ts_init)`, and then snapshots; `collectors/collector_v2/aggregator.py:117-135` publishes only buckets with `close_ts <= available_ns`. |
| 2 | [A1] 1s extrema were stamped with bar-open time | FIXED | `implementation/collector.py:59-63` still passes `bar.ts_init` to the geometry tracker; `ts_event` remains only the explicit aggregation bucket key. |
| 3 | [G4] Excluded volume-one bars fed structural/current-price features | FIXED | `implementation/collector.py:56-73` still gates tracker, aggregator, and `_last_close` updates on eligibility and snapshots with the last eligible close; `tests/test_single_tick_exclusion.py:34-46` verifies the excluded price cannot enter the snapshot. |
| 4 | [B9] Registry metadata omitted the load-bearing 1m-flip update | FIXED | `features/registry.py:615-618` still declares `1s+1m+5m` ownership and the completed-1s/completed-5m/then-1m-flip update anchor. |

## Critical findings

None.

## Warnings

### [G2] `implementation/run_collection_grid.py:12,28` — corrected collection output is disconnected from the downstream input root by default

The grid runner defaults to `_work/collection`, but fitting (`run_study.py:38`), validation (`implementation/validate.py:13`), and finalization (`implementation/finalize_artifacts.py:15`) exclusively read `_work/collection_audit_fix_v2`. That latter directory does not currently exist. A normal invocation without `--output-root` therefore cannot feed the audited corrected rows to analysis; if a stale `collection_audit_fix_v2` later exists, downstream code can silently analyze it while the corrected run is written elsewhere. This is an unenforced data-lineage invariant on which every fitted and OOS number depends.

**Smallest fix:** Make one collection-root constant/config drive collection, fitting, validation, and finalization (or change the grid default to the exact downstream root) before the 48-month run.

## Notes

None.

## Referred to contract-checker

- Re-audit the remediated deliverables and promotion surface; the currently materialized `audit/contract_status.json` still records the prior BLOCKED verdict.

## Clean checks

- A1-A5; B1-B7, B9-B10; C1-C3; F1-F4; G1, G3-G4; H1-H4 verified clean on the changed surface or preserved as unchanged-clean from pass 03.
- `run_study.py:45-57,93-115` keeps future regime-end values in labels, uses a temporal 2021-2023/2024 split, and derives thresholds/deciles only from TRAIN predictions.
- `implementation/sealed_outcomes.py:14-30` restricts path and regime inputs to 2021-2024 and censors ends at the 2025 boundary; inherited Walk-A remains 1s high/low with accepted causal ordering.
- Targeted study tests: 8 passed in 0.72s.
