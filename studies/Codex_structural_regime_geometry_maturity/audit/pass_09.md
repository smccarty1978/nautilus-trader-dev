# Look-Ahead & Timestamp Audit — Pass 09

**Date:** 2026-08-14T11:13:34.2147587-05:00  
**Scope:** 66 files: 18 connected causal/source and compact aggregate-evidence files covering collector RTH/DST emission, equal-time event ordering, structural tracker, 5m aggregator/engine/registry, monthly collection and shared lineage, causal validation, train/OOS fitting, catalog identifiers, SPEC, lint, and aggregate manifests; plus the 48 monthly collection `manifest.json` files. Generated parquet/CSV tables, reports, seals, promotion, contracts, and test-quality surfaces were not inspected.  
**Scope hash:** `a56e7820487525d8da7562869b6f125446bad9755be63eb77af57025e12d037d`  
**Lint:** 0 critical / 0 warning from `causal_lint.py`  
**Verdict:** PASS

## Summary

- Critical: 0
- Warning: 0
- Note: 0

## Prior findings adjudicated

| # | Prior finding | Status | Evidence |
|---|---|---|---|
| 1 | [A1/A5] Equal-time 5m snapshots omitted the bucket that just completed | FIXED | `implementation/collector.py:72-86` consumes the eligible completed 1s bar, calls `finalize_through(ts_init)`, and snapshots afterward; `collectors/collector_v2/aggregator.py:117-135` publishes only an existing bucket with `close_ts <= available_ns`. |
| 2 | [A1] 1s extrema were stamped with bar-open time | FIXED | `implementation/collector.py:65-75` confines `ts_event` to the explicit aggregation bucket key and passes completed-bar `ts_init` to the structural tracker. |
| 3 | [G4] Volume-one bars fed structural extrema and completed-5m indicators | FIXED | `implementation/collector.py:68-76` gates tracker, aggregator, and eligible-close state on `volume > 1`. |
| 4 | [B9] Registry metadata omitted the load-bearing 1m-flip update | FIXED | `features/registry.py:594-618` declares `1s+1m+5m`, the completed-1s/completed-5m/then-1m-flip anchor, event window, and event-start reset. |
| 5 | [G4] An excluded volume-one checkpoint supplied the snapshot price | FIXED | `implementation/collector.py:80-86` requires and snapshots only `_last_close`, which is updated solely by eligible bars. |
| 6 | [G2] Corrected collection output was disconnected from downstream consumers | FIXED | `implementation/paths.py:4-8` remains the sole corrected root; collection, fitting, and validation import it (`implementation/run_collection_grid.py:10-13`, `run_study.py:15,39-40`, `implementation/validate.py:10-15`), and 48 manifests are present under that root. |

## Critical findings

None.

## Warnings

None.

## Notes

None.

## Referred to contract-checker

- `results/validation_report.json:2,495` records a top-level FAIL from extra snapshots without canonical-regime keys; population/deliverable completeness is contract-checker scope and does not contradict the clean causal subchecks.

## Clean checks

- A1-A5; B1-B7, B9-B10; C1-C3; F1-F4; G1-G4; H1-H4 verified clean on the current connected surface or preserved unchanged-clean through pass 08.
- `SPEC.md:49-54` freezes the equal-time sequence as completed 1s, completed 5m, snapshot, then equal-time 1m update; `implementation/collector.py:72-99` implements that order and stamps frozen flips with `bar.ts_init`.
- `implementation/collector.py:22-26,77-91` uses `America/Chicago`, updates causal ETH state before the session gate, emits only `[08:30,15:00)`, and snapshots only completed eligible 1s/5m state.
- `features/trackers/structural_regime_geometry.py:59-83,99-145` mutates state only on completed input callbacks and keeps `snapshot` read-only; `collectors/collector_v2/registry.py:116-127` rejects any completed state after the decision timestamp.
- `implementation/run_collect.py:57-92` restricts collection to 2021-2024, loads only backward warmup, retains `[start,end)`, and records per-partition hashes and readiness. All 48 compact manifests report exact bounds, matching hashes, valid membership, warmup readiness, and the 2025 seal boundary; `results/validation_report.json:54,499-502` confirms completed-5m provenance, registry provenance, sealed years, and unique available geometry.
- `run_study.py:39-64,100-121` keeps future regime ends confined to labels/evaluation, assigns training only through 2023 and OOS only to 2024, and derives thresholds/deciles solely from TRAIN scores. `results/phase0_contract.json:4-17` records the same materialized year split.
