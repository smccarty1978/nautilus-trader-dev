# Look-Ahead & Timestamp Audit — Pass 03

**Date:** 2026-08-14T15:59:55-05:00  
**Scope:** Study SPEC/config/implementation/tests plus directly used feature-engine/tracker and collector-v2 state paths  
**Scope hash:** `2b56a283346ab081be1fb684c69f0f438a56d6ad67c8606dca2db1b7174628bc`  
**Lint:** 0 critical / 0 warning  
**Verdict:** BLOCKED

## Summary

- Critical: 3
- Warning: 0
- Note: 2

## Prior findings adjudicated

| # | Prior finding | Status | Evidence |
|---|---|---|---|
| 1 | G2 recursive 5m state bridges discarded bucket | FIXED | `collector.py:160-164,171-175` recreates both `CompletedBarRegistry` and `RegimeStateEngine` before invalidating geometry. No recursive 5m state survives the gap. |
| 2 | G2/B9 rejected seconds compress baseline windows | FIXED | `collector.py:157-188` records the rejected close boundary and suppresses every feature row through the frozen 1800-second maximum count window. |
| 3 | B2/B9 real-flip minute assigned to new regime | FIXED | `features/engine.py:125-149` flushes the buffered minute into the active prior regime before resetting on a real `regime_id` change. |

## Critical findings

### [G2, B9] `collector.py:146` — a truly missing 1s bar bypasses baseline-gap suppression

**Failure path:** The suppression clock is set only when an actual callback has `volume <= 1` (lines 157-158). If a catalog second is absent entirely, there is no callback to update `_last_rejected_feature_ns`; the next valid callback advances the count-only `FeatureEngine`, and feature rows continue to emit. For example, `ArrivalVelocityTracker` then labels five observations spanning six wall-clock seconds as `arrival_vel_5s`. The 5m/rolling paths eventually detect their own coverage gap, but baseline candidate windows remain silently compressed and can change the train-only Top-25.

**Smallest fix:** Track the last accepted 1s event/close timestamp and treat every non-1s advance as a feature gap, applying the same 1800-second row suppression (and explicit downstream invalidation) as a rejected bar.

### [B2, B9] `features/engine.py:151` — first-ever regime receives a minute that predates its declared start

**Failure path:** When there was no active regime, a newly initialized regime resets at the completed 1m close `T` (lines 135-147), then lines 151-154 accumulate all buffered bars from `[T-60s,T]` into it. The collector records that regime as starting at `T` (`collector.py:222-232`). Consequently, the first regime's volume/range/delta sums contain pre-start observations; at `T+5s`, `regime_elapsed_seconds` is about 5 while the sums can already contain a full minute.

**Smallest fix:** Discard the pre-start buffered minute when the first regime is initialized; only bars whose availability timestamp is after the recorded start may enter its cumulative state.

### [F1, F2] `features/engine.py:131` — buffered-minute flush occurs before the close-time RTH transition

**Failure path:** `accumulate_regime_rth` updates both regime and RTH accumulators according to the current `_rth_active` flag. The new flush at lines 131-134 runs before `_is_rth(bar.ts_init)` changes that flag at lines 173-178. At the repository-defined 08:30 close boundary, the minute is accumulated while RTH is still inactive and is then omitted from every later RTH cumulative feature that day; the inverse occurs at the 15:00 boundary. This violates the frozen close-time session convention and can alter baseline selection.

**Smallest fix:** Separate regime and RTH attribution ordering: flush the minute to the prior regime while classifying its RTH accumulation from the current completed 1m close boundary.

## Warnings

- None.

## Notes

- Rolling T-300 coverage, exact anchor choice, and completed-through-T semantics remain clean.
- Completed 5m state is now fail-closed across observed incomplete buckets and still excludes forming buckets.

## Referred to contract-checker

- None newly referred this pass.

## Clean checks

- A1, A3-A5, B1, B3-B7, B10, C1, F3-F4, G4 verified clean on the implemented path.
- C2-C3 are not yet exercised; H1-H4 are not applicable.
