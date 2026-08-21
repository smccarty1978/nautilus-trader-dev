# Look-Ahead & Timestamp Audit — Pass 06

**Date:** 2026-08-14T19:32:58-05:00  
**Scope:** Material label/gate changes in `implementation/collector.py` and `implementation/run_collect.py`; frozen SPEC/config; directly used feature-engine, rolling/structural tracker, 5m aggregation/state/registry, and reference 1m regime paths  
**Scope hash:** `d734ee2ababec62a7714bae35edf0e2be3cc06ffe18e19ea1c15115c5f41b387`  
**Lint:** 0 critical / 0 warning  
**Verdict:** BLOCKED

## Summary

- Critical: 2
- Warning: 0
- Note: 1

The feature snapshot is frozen at T and the target is added later inside the NT event loop. The resolver's strict wait past `T+300s` correctly accommodates 1s-before-1m dispatch: a flip at T is excluded and a flip at exactly `T+300s` is observed before resolution. Target observability is not yet fail-closed at two data-quality boundaries.

## Prior findings adjudicated

| # | Prior finding | Status | Evidence |
|---|---|---|---|
| 1 | G2/B9 missing-second feature-state suppression and causal reset | FIXED | The unchanged feature-state path still marks both cumulative reset flags and applies the 1800s recovery gate (`collector.py:168-174,213-216`); the new pending-label path does not undo that feature suppression. |
| 2 | F1/B9 valid RTH accumulation before the first regime | FIXED | The unchanged engine path still transitions RTH before buffered attribution and accumulates valid RTH minutes independently of regime initialization (`features/engine.py:126-147`). |

## Critical findings

### [G4/C2] `implementation/collector.py:179-180,307-312` — the first rejected 1s bar after T does not invalidate `(T,T+300s]`

**Failure path:** A row is queued at checkpoint decision time T. The next 1s bar has `ts_event == T`, `ts_init == T+1s`, and volume <= 1, so it is the first completed second inside the target window. The rejection calls `_invalidate_pending_horizons(T, T)`, but the overlap test requires `checkpoint < gap_end_ns`; for this row that is `T < T`, false. The row remains observable and contributes a label/count despite a frozen low-quality target second.

**Smallest fix:** Represent the rejected bar as its completed interval (for example event interval `[event_ns,event_ns+1s)`) and use one consistent half-open overlap test against target `(T,T+300s]`, including boundary fixtures for the first and last target seconds.

### [G2/C2] `implementation/run_collect.py:46-47`; `implementation/collector.py:251-273,314-328` — missing 1m target bars can be emitted as negative labels

**Failure path:** The runner loads independent 1s and 1m catalog streams. If all 1s bars are present but a 1m bar in `(T,T+300s]` is absent, `_on_1m` never observes the possible regime transition. No 1m continuity/readiness state marks the pending horizon invalid. At the first 1s callback after the endpoint, `_resolve_pending_labels` sees no recorded flip and emits `flip_within_300s = 0`, turning an unavailable target into a false negative.

**Smallest fix:** Track completed 1m continuity/quality in event time and refuse or censor a pending label unless every required parent-minute close through its endpoint was observed before resolution; invalidate overlapping pending horizons on a detected bad/missing 1m bar.

## Warnings

- None.

## Notes

- `collector.py:314-328` resolves only after the full endpoint and mutates only the captured row's label; `flip_within_300s` is not in any feature registry block or established-regime eligibility input.

## Referred to contract-checker

- None newly referred this pass.

## Clean checks

- A1-A5, B1-B7, B9-B10, C1, C3, F1-F4, G1, G3 verified clean on the changed collection path.
- H1-H4 are not applicable: this study creates no orders or fills.
