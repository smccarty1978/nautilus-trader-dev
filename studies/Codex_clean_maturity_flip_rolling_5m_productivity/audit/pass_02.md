# Look-Ahead & Timestamp Audit — Pass 02

**Date:** 2026-08-14T15:47:23-05:00  
**Scope:** Study SPEC/config/implementation/tests plus the directly used feature engine, rolling/structural/velocity/volume/pullback trackers, collector-v2 aggregator/regime engine/registry, and imported reference `RegimeEngine`  
**Scope hash:** `bd8ad9f5ee5a894f6c29885482484ae9992ebe4d15004afc0c88c55e3df8f5f3`  
**Lint:** 0 critical / 0 warning  
**Verdict:** BLOCKED

## Summary

- Critical: 3
- Warning: 0
- Note: 2

## Prior findings adjudicated

| # | Prior finding | Status | Evidence |
|---|---|---|---|
| 1 | G2/B9 rolling interior coverage | FIXED | `rolling_5m_productivity.py:85-90` requires all 301 exact one-second close timestamps and returns `INCOMPLETE_1S_WINDOW` on any gap. |
| 2 | G2 partial 5m completion | NOT FIXED | `aggregator.py:145-152,193-204` now discards the partial bucket, but `collector.py:155-157` invalidates only geometry. The persistent `RegimeStateEngine` and registry are not reset, so the next accepted 5m bar resumes ATR/EMA/regime from before the missing bucket. |
| 3 | G4 shared quality gate | FIXED | `collector.py:145-153` applies `volume > 1` before any feature, geometry, or aggregation update. |
| 4 | F2 RTH boundary flag | FIXED | `collector.py:186-190` emits the rolling-window crossing flag and the completed-5m regime's causal start/session provenance; conversion uses `America/Chicago`. |

## Critical findings

### [G2] Prior #2 NOT FIXED — discarded 5m buckets still leave recursive state bridged across the gap

**Failure path:** After an incomplete 5m bucket is reported, `on_5m_gap` clears only `StructuralRegimeGeometryTracker` state (`structural_regime_geometry.py:85-89`). `self._engine_5m` and its `CompletedBarRegistry` remain live. The next full 5m bucket therefore computes true range, ATR, EMA, and regime against the pre-gap close/state (`regime_engine.py:88-102`), and that bridged state is later admitted to structural geometry. Model B/C values can consequently depend on an unobserved interval.

**Smallest fix:** Invalidate/reset the 5m regime engine and registry on every discarded bucket, and do not describe the gap close timestamp as a completed 5m close.

### [G2, B9] `collector.py:149` — rejected seconds are silently compressed in count-based baseline windows

**Failure path:** The shared quality gate skips a rejected second, but the next valid second continues the same `FeatureEngine`. Trackers such as `ArrivalVelocityTracker` store prices without timestamps (`features/trackers/velocity.py:8-16`), so a nominal five-observation/“5s” calculation after one rejected second spans six wall-clock seconds. Pullback, arrival-volume, and other count-window candidates have the same failure path, changing the train-only Top-25 ranking while the row carries no baseline-gap unavailability state.

**Smallest fix:** Make the engine gap-aware and suppress/reset every count-based 1s feature until its declared wall-clock window is consecutively complete; do not merely omit the rejected observation.

### [B2, B9] `features/engine.py:125` — the flip minute's buffered 1s bars are assigned to the new regime before its start

**Failure path:** The collector defines a new regime as starting at the 1m close `T` (`collector.py:201-211`). At that callback, `FeatureEngine.update_1m` sees the new `regime_id`, resets regime aggregates at `T`, then replays the whole buffered minute's 1s bars into that new state (`features/engine.py:125-170`). Those bars occurred in `[T-60s,T]`, before the declared new-regime start, so the next checkpoint's regime-volume/range/delta baseline features include prior-regime observations.

**Smallest fix:** On a flip, attribute the buffered minute to the ending regime before resetting new-regime state at `T`; only 1s bars with availability after `T` may accumulate into the new regime.

## Warnings

- None.

## Notes

- Exact T-300 anchor semantics and completed-through-T rolling availability remain causal after the coverage fix.
- The normal full-coverage 5m path still finalizes at `close_ts <= decision_ns`, audits provenance, and excludes the forming bucket.

## Referred to contract-checker

- None newly referred this pass.

## Clean checks

- A1, A3-A5, B1, B3-B7, B10, C1, F1-F4 verified clean on the implemented path.
- C2-C3 are not yet exercised; H1-H4 are not applicable.
