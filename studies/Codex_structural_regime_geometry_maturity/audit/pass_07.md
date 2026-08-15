# Look-Ahead & Timestamp Audit — Pass 07

**Date:** 2026-08-14T08:05:01.6665875-05:00  
**Scope:** 21 files: the changed all-score snapshot validator and phase-0/lint terminal-abort integration; connected collection, shared-lineage, fitting, selection, evaluation, finalization, and promotion paths; the structural tracker/aggregator/registry fixes needed to adjudicate prior findings; SPEC, lint, and 7 study tests. Unchanged inherited Walk-A engines remain clean from pass 04 and were not reopened.  
**Scope hash:** `ed2bfcbf724bc49e027fcab48622230d09d79cbbff8b6597622f003916dd32e3`  
**Lint:** 0 critical / 0 warning from `causal_lint.py`  
**Verdict:** PASS

## Summary

- Critical: 0
- Warning: 0
- Note: 0
- Study tests: 19 passed in 1.74s.

## Prior findings adjudicated

| # | Prior finding | Status | Evidence |
|---|---|---|---|
| 1 | [A1/A5] Equal-time 5m snapshots omitted the bucket that just completed | FIXED | `implementation/collector.py:59-73` consumes the eligible completed 1s bar and calls `finalize_through(ts_init)` before snapshot; `collectors/collector_v2/aggregator.py:117-135` publishes only existing buckets with `close_ts <= available_ns`. |
| 2 | [A1] 1s extrema were stamped with bar-open time | FIXED | `implementation/collector.py:53-62` confines `ts_event` to aggregation and passes `ts_init` to the structural tracker. |
| 3 | [G4] Volume-one bars fed structural extrema and completed-5m indicators | FIXED | `implementation/collector.py:55-63` gates tracker, aggregator, and eligible-close state on `volume > 1`. |
| 4 | [B9] Registry metadata omitted the load-bearing 1m-flip update | FIXED | `features/registry.py:594-618` declares `1s+1m+5m`, the completed-1s/completed-5m/then-1m-flip anchor, regime-event windows, and event-start reset. |
| 5 | [G4] An excluded volume-one checkpoint supplied the snapshot price | FIXED | `implementation/collector.py:63-73` retains and snapshots only the last eligible close. |
| 6 | [G2] Corrected collection output was disconnected from downstream consumers | FIXED | `implementation/paths.py:4-8` remains the single root imported by `implementation/run_collection_grid.py:10-13`, `run_study.py:15,39-40`, `implementation/validate.py:10-15`, and `implementation/finalize_artifacts.py:11-16`. |

## Critical findings

None.

## Warnings

None.

## Notes

None.

## Referred to contract-checker

- `implementation/validate.py:75-94` maps every collected snapshot against RTH-only score keys and requires zero unmapped snapshots, while `implementation/collector.py:67-75` emits checkpoints without an RTH snapshot gate; adjudicate the extra ETH-row behavior under SPEC §7 completeness.

## Clean checks

- A1-A5; B1-B7, B9-B10; C1-C3; F1-F4; G1-G4; H1-H4 verified clean on the changed surface or preserved as unchanged-clean from pass 06.
- `implementation/validate.py:75-96` validates all RTH decision/regime score keys without filtering on structural availability; its completed-5m provenance checks remain at or before decision time.
- `run_study.py:39-64` maps independent snapshots to the canonical decision/regime key before labels are attached; future regime ends remain confined to label/evaluation columns.
- `run_study.py:100-138` preserves the temporal 2021-2023/2024 split and derives thresholds/deciles from TRAIN scores only; OOS first crossings use causal scores in decision-time order.
- `implementation/finalize_artifacts.py:57-74` adds only gate-state abort inputs and materializes checkpoint rows from decision-time score/snapshot state; it does not introduce future-label data into features or selection.
