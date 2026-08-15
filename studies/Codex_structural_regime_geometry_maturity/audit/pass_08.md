# Look-Ahead & Timestamp Audit — Pass 08

**Date:** 2026-08-14T09:01:51.8549450-05:00  
**Scope:** 17 files: the changed RTH snapshot gate and DST boundary test; connected collector, monthly warmup/retention, shared-lineage, validator, completed-5m registry/aggregator/tracker paths; SPEC; registry metadata; and targeted causal tests. Unchanged fitting, label, and inherited Walk-A surfaces remain clean from pass 07 and were not reopened.  
**Scope hash:** `ddff238b3f7f48dd1df7c08c6ca556a4012b63b2fd5bbe1f6f2ec725b3deb189`  
**Lint:** 0 critical / 0 warning from `causal_lint.py`  
**Verdict:** PASS

## Summary

- Critical: 0
- Warning: 0
- Note: 0
- Study tests: 20 passed in 1.73s.

## Prior findings adjudicated

| # | Prior finding | Status | Evidence |
|---|---|---|---|
| 1 | [A1/A5] Equal-time 5m snapshots omitted the bucket that just completed | FIXED | `implementation/collector.py:65-86` consumes the eligible completed 1s bar and calls `finalize_through(ts_init)` before snapshot; `collectors/collector_v2/aggregator.py:117-135` publishes only existing buckets with `close_ts <= available_ns`. |
| 2 | [A1] 1s extrema were stamped with bar-open time | FIXED | `implementation/collector.py:65-75` confines `ts_event` to the explicit aggregation bucket key and passes completed-bar `ts_init` to the structural tracker. |
| 3 | [G4] Volume-one bars fed structural extrema and completed-5m indicators | FIXED | `implementation/collector.py:68-76` gates tracker, aggregator, and eligible-close updates on `volume > 1`. |
| 4 | [B9] Registry metadata omitted the load-bearing 1m-flip update | FIXED | `features/registry.py:594-618` declares `1s+1m+5m`, the completed-1s/completed-5m/then-1m-flip anchor, event window, and event-start reset. |
| 5 | [G4] An excluded volume-one checkpoint supplied the snapshot price | FIXED | `implementation/collector.py:81-86` requires and snapshots only `_last_close`, which is updated solely by eligible bars. |
| 6 | [G2] Corrected collection output was disconnected from downstream consumers | FIXED | `implementation/paths.py:4-8` remains the sole collection root used by `implementation/run_collection_grid.py:10-13,36-53`, `implementation/validate.py:10-15`, and the unchanged fitting/finalization consumers verified in pass 07. |

## Critical findings

None.

## Warnings

None.

## Notes

None.

## Referred to contract-checker

None.

## Clean checks

- A1-A5; B1-B7, B9-B10; C1-C3; F1-F4; G1-G4; H1-H4 verified clean on the changed surface or preserved as unchanged-clean from pass 07.
- `implementation/collector.py:22-26,65-91` classifies the completed 1s availability/decision timestamp `ts_init`, updates 1s/5m state before the session gate, and appends only when Chicago local time is in `[08:30,15:00)`. Thus ETH causally warms state but cannot produce a row.
- `features/trackers/structural_regime_geometry.py:99-145` confirms the pre-gate snapshot is read-only; no ETH snapshot call mutates feature state.
- `tests/test_rth_snapshot_gate.py:10-14` covers the winter open, summer/DST open, pre-open exclusion, and exact 15:00 close exclusion using UTC inputs; the implementation uses `ZoneInfo("America/Chicago")`, not a fixed offset.
- `implementation/run_collect.py:67-83` loads only backward warmup and retains `[start,end)` rows, while `implementation/validate.py:75-96` maps the emitted population against RTH canonical score keys and preserves completed-5m provenance at or before decision time.
