# Look-Ahead & Timestamp Audit — Pass 06

**Date:** 2026-08-14T07:59:49.0104282-05:00  
**Scope:** 24 files: the tracked aggregator/registry diff; structural tracker; study SPEC/config/lint; collector, warmup runner, grid runner, shared paths, composite-key fitting/validation, finalization/promotion paths; and 9 study test files. Unchanged inherited Walk-A engines remain clean from pass 04 and were not reopened.  
**Scope hash:** `a01b606ed31b9b4672a58d3716218c33816d25daf615507e2cdcea19fffcfd1f`  
**Lint:** 0 critical / 0 warning from `causal_lint.py`  
**Verdict:** PASS

## Summary

- Critical: 0
- Warning: 0
- Note: 0
- Study tests: 18 passed in 1.66s.

## Prior findings adjudicated

| # | Prior finding | Status | Evidence |
|---|---|---|---|
| 1 | [A1/A5] Equal-time 5m snapshots omitted the bucket that just completed | FIXED | `implementation/collector.py:59-73` consumes the eligible completed 1s bar, calls `finalize_through(ts_init)`, and snapshots afterward; `collectors/collector_v2/aggregator.py:117-135` publishes only existing buckets with `close_ts <= available_ns`. |
| 2 | [A1] 1s extrema were stamped with bar-open time | FIXED | `implementation/collector.py:53-62` keeps `ts_event` as the aggregation bucket key and sends `ts_init` to the structural tracker. |
| 3 | [G4] Volume-one bars fed structural extrema and completed-5m indicators | FIXED | `implementation/collector.py:55-63` gates tracker, aggregator, and eligible-close updates on `volume > 1`. |
| 4 | [B9] Registry metadata omitted the load-bearing 1m-flip update | FIXED | `features/registry.py:612-618` declares `1s+1m+5m`, the completed-1s/completed-5m/then-1m-flip anchor, regime-event window units, and event-start reset. |
| 5 | [G4] An excluded volume-one checkpoint supplied the snapshot price | FIXED | `implementation/collector.py:63-73` retains only the last eligible close and passes that value to `snapshot`. |
| 6 | [G2] Corrected collection output was disconnected from downstream consumers | FIXED | `implementation/paths.py:4-8` defines the sole corrected root; the grid producer (`implementation/run_collection_grid.py:10-13,36-53`), fitter (`run_study.py:15,39-40`), validator (`implementation/validate.py:10-15`), and finalizer (`implementation/finalize_artifacts.py:11-16`) all import it. |

## Critical findings

None.

## Warnings

None.

## Notes

None.

## Referred to contract-checker

- Adjudicate the validator's all-snapshot versus accepted-RTH-base denominator under the SPEC's domain/completeness contract.

## Clean checks

- A1-A5; B1-B7, B9-B10; C1-C3; F1-F4; G1-G4; H1-H4 verified clean on the changed surface or preserved as unchanged-clean from pass 05.
- `implementation/run_collect.py:35-54,67-90` loads only backward warmup, retains only `[start,end)`, and requires completed tracker state at the first retained snapshot; no warmup row enters fitting.
- `run_study.py:39-64` maps independent snapshots to the canonical timestamp once, then uses the exact decision/regime composite for fitting and labeling; future regime ends remain label-only.
- `run_study.py:100-121,125-134` preserves the temporal 2021-2023/2024 split and derives thresholds/deciles from TRAIN scores only; OOS crossing selection uses causal scores in decision-time order.
