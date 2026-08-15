# Look-Ahead & Timestamp Audit — Pass 07

**Date:** 2026-08-14T19:36:08-05:00  
**Scope:** Pass-06 remediation in `implementation/collector.py`; unchanged `implementation/run_collect.py`; frozen SPEC/config and directly used feature-engine, rolling/structural, 5m state, and reference 1m regime paths as needed for state-flow resolution  
**Scope hash:** `473c2e4a5b4b7b57c9413dd3d1c7157278606bc429054a1bd35650a7618afcab`  
**Lint:** 0 critical / 0 warning  
**Verdict:** BLOCKED

## Summary

- Critical: 2
- Warning: 0
- Note: 1

No new findings were opened. Both Pass-06 findings remain blocking because the remediations fail at the opposite endpoint or detection-order boundary.

## Prior findings adjudicated

| # | Prior finding | Status | Evidence |
|---|---|---|---|
| C-01 | G4/C2 rejected 1s target-boundary invalidation | NOT FIXED | Changing the overlap predicate to inclusive at both ends fixes the first bar inside the target, but `collector.py:326-331` now also treats a bar whose `ts_event == T+300s` as overlapping. That bar closes at `T+301s` and is outside `(T,T+300s]`. |
| C-02 | G2/C2 missing 1m target bar can become a negative | NOT FIXED | `collector.py:254-270` detects a gap only when the next 1m callback arrives. `collector.py:333-347` can resolve on the first 1s callback after the endpoint, before that next parent callback exposes a missing final 1m bar. |

## Critical findings

### [G4/C2] `implementation/collector.py:180-181,326-331` — C-01 uses an inclusive upper overlap edge outside the target horizon

**Failure path:** A row at T has a completely observable target through `T+300s`. The next 1s bar has `ts_event == T+300s`, `ts_init == T+301s`, so it is outside the target. If that bar is rejected, `_invalidate_pending_horizons(T+300s,T+300s)` passes because the row endpoint equals `gap_start_ns`. The resolver is skipped on the rejected bar; a later valid callback drops the now-unobservable row. Sample membership therefore depends on data strictly after the frozen target horizon.

**Smallest fix:** Express both target and unavailable bars as consistent half-open event intervals: target event stamps `[T,T+300s)` and a rejected 1s bar `[event,event+1s)`, then invalidate only on a nonempty intersection.

### [G2/C2] `implementation/collector.py:254-270,333-347` — C-02 still resolves before absence of the last required 1m close is knowable

**Failure path:** Let the last required parent close at or immediately before `T+300s` be missing. At the 1s callback exactly at the endpoint, resolution waits as intended. At `T+301s`, no later 1m callback has arrived, so `_last_seen_1m_init_ns` still looks contiguous up to the preceding minute and the row is emitted as `flip_within_300s = 0`. The next 1m callback detects the gap up to 59 seconds later, but the row is no longer pending and cannot be invalidated.

**Smallest fix:** Before resolution, require 1m readiness through the latest parent close belonging to the horizon, or defer resolution until the next parent callback proves continuity through that close; only then emit the label.

## Warnings

- None.

## Notes

- Once a 1m gap is observed, the new reset path is fail-closed for subsequent feature rows until post-gap state is causally re-established (`collector.py:256-293`).

## Referred to contract-checker

- None newly referred this pass.

## Clean checks

- No changed area previously marked clean produced a new finding.
- A1-A5, B1-B7, B9-B10, C1, C3, F1-F4, G1, G3 remain clean; H1-H4 are not applicable.
