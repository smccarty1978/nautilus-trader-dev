# Look-Ahead & Timestamp Audit — Pass 05

**Date:** 2026-08-14T07:49:01.8591757-05:00  
**Scope:** 24 files: `collectors/collector_v2/aggregator.py`; the structural registry/tracker; study `SPEC.md`, config, and lint result; `run_study.py`; 11 implementation files covering collection, shared paths, fitting/evaluation, validation/finalization, and promotion flow; and 6 study tests. Unchanged inherited Walk-A engines remain clean from pass 04 and were not reopened.  
**Scope hash:** `ec8512110818db1d2195a2d614c51f1d4cbc8a6c96d0dd0014189475f3c8ebbc`  
**Lint:** 0 critical / 0 warning from `causal_lint.py`  
**Verdict:** PASS

## Summary

- Critical: 0
- Warning: 0
- Note: 0
- Targeted tests: 11 passed in 1.54s.

## Prior findings adjudicated

| # | Prior finding | Status | Evidence |
|---|---|---|---|
| 1 | [A1/A5] Equal-time 5m snapshots omitted the bucket that just completed | FIXED | `implementation/collector.py:61-73` consumes the eligible completed 1s bar, calls `finalize_through(ts_init)`, and snapshots afterward; `collectors/collector_v2/aggregator.py:117-135` publishes only an existing bucket with `close_ts <= available_ns`. |
| 2 | [A1] 1s extrema were stamped with bar-open time | FIXED | `implementation/collector.py:53-62` distinguishes `ts_event` from `ts_init` and sends `ts_init` to `StructuralRegimeGeometryTracker.on_1s`; open time remains only the aggregation bucket key. |
| 3 | [G4] Volume-one bars fed structural extrema and completed-5m indicators | FIXED | `implementation/collector.py:55-63` gates tracker, aggregator, and eligible-close state on `volume > 1`. |
| 4 | [B9] Registry metadata omitted the load-bearing 1m-flip update | FIXED | `features/registry.py:594-616` declares `source_timeframe='1s+1m+5m'` and the completed-1s/completed-5m/then-1m-flip update anchor. |
| 5 | [G4] An excluded volume-one checkpoint still supplied the snapshot price | FIXED | `implementation/collector.py:63-73` retains only the last eligible close and passes it to `snapshot`; `tests/test_single_tick_exclusion.py:34-46` verifies an excluded differing close cannot enter the snapshot. |
| 6 | [G2] Corrected collection output default was disconnected from downstream consumers | FIXED | `implementation/paths.py:4-8` defines the sole corrected root; the producer (`implementation/run_collection_grid.py:10-13`), fitter (`run_study.py:15,40`), validator (`implementation/validate.py:10-14`), and finalizer (`implementation/finalize_artifacts.py:11-16`) all import it. Direct runtime equality checks passed. |

## Critical findings

None.

## Warnings

None.

## Notes

None.

## Referred to contract-checker

None newly referred; earlier contract referrals are not re-raised.

## Clean checks

- A1-A5; B1-B7, B9-B10; C1-C3; F1-F4; G1-G4; H1-H4 verified clean on the changed surface or preserved as unchanged-clean from pass 04.
- Collection, fitting, validation, and finalization now share the corrected collection root without a stale-root fallback.
- `run_study.py:39-59,95-117,120-129` keeps future regime-end data confined to labels/evaluation, preserves the temporal 2021-2023/2024 split, derives thresholds and deciles only from TRAIN scores, and computes OOS crossings from causal scores.

