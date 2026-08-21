# Look-Ahead & Timestamp Audit — Pass 01

**Date:** 2026-08-14T15:37:25-05:00  
**Scope:** `SPEC.md`, `config/study.yaml`, `implementation/{collector,contracts,phase0}.py`, `features/engine.py`, rolling and structural trackers, collector-v2 aggregator/regime engine/registry, and the imported reference `RegimeEngine`  
**Scope hash:** `8b0be8aab555e489b2e39a8a38b64a3fcd8a0841d6cee952077c25d51b559bbe`  
**Lint:** 0 critical / 0 warning  
**Verdict:** BLOCKED

## Summary

- Critical: 3
- Warning: 1
- Note: 2

## Prior findings adjudicated

N/A — first audit pass.

## Critical findings

### [G2, B9] `features/trackers/rolling_5m_productivity.py:80` — interior gaps are accepted as a complete 300-second window

**Failure path:** If bars at exactly `T-300` and `T` exist but any interior second is missing, lines 80-84 accept the window because only its endpoints are checked. The tracker then computes extrema, progress, and speed over fewer than 301 declared boundary states and marks the result available, changing Model C inputs while concealing the missing data.

**Smallest fix:** Require the exact expected one-second timestamp grid (or an equivalent consecutive-cadence/count invariant) before emitting available rolling features; otherwise return an explicit gap reason.

### [G2] `collectors/collector_v2/aggregator.py:137` — partial 5m buckets are promoted as fully completed bars

**Failure path:** `_on_1s_for_tf` tracks only bucket identity, not constituent coverage. After one or more missing/filtered seconds, either a later-bucket arrival (lines 160-177) or `finalize_through` (lines 127-135) publishes the partial OHLCV bucket with its nominal 5m `close_ts`. `RegimeStateEngine` then updates ATR/EMA/regime from that partial bar, and the collector exposes it as `current_5m_completed_close_ts`, changing completed-5m geometry.

**Smallest fix:** Track expected constituent timestamps/coverage per bucket and refuse or explicitly mark incomplete 5m buckets; never write them to `CompletedBarRegistry` as completed state.

### [G4] `studies/Codex_clean_maturity_flip_rolling_5m_productivity/implementation/collector.py:142` — zero/single-tick bars enter baseline and rolling features

**Failure path:** Every 1s bar is sent to `FeatureEngine.update_1s` before the `volume > 1.0` gate at lines 143-145. `features/engine.py:94-117` advances velocity, volume, OHLCV-delta, median-center, pullback buffers, and the new rolling tracker. Thus a volume-zero or single-tick bar can alter clean-baseline selection and Model C while the same bar is excluded from structural/5m state.

**Smallest fix:** Apply one shared bar-quality decision before any feature tracker advances, and combine it with explicit missing-window/bucket handling so rejected bars make affected windows unavailable rather than silently shortening them.

## Warnings

### [F2] `studies/Codex_clean_maturity_flip_rolling_5m_productivity/implementation/collector.py:137` — session-crossing state is neither reset nor flagged

The rolling tracker and 5m structural state advance on all subscribed bars, while RTH is checked only when rows are emitted at lines 156-157. An eligible checkpoint during the first five minutes of RTH therefore incorporates ETH state, and a 5m regime may span the session boundary, without a boundary flag. Define continuous-session semantics explicitly and emit a boundary flag, or reset the affected trackers at the named `America/Chicago` RTH boundary.

## Notes

- The ordinary complete-cadence path uses `bar.ts_init` as the 1s availability boundary, requires `ts_event < ts_init`, finalizes the 5m bucket through the decision time, and checks registry provenance before snapshotting. No forming 5m bucket is read.
- The structural tracker keeps current-active and immediately prior completed 5m regimes separate; the frozen current-distance fields read only the active regime's completed-bar running high/low.

## Referred to contract-checker

- Eligibility filtering plus downstream label construction, temporal Top-25 selection, and result artifacts are not present in this pre-execution code surface and require contract-gate coverage before any corresponding execution.

## Clean checks

- A1, A3-A5, B1-B7, B10, C1, F1, F3-F4 verified clean on the implemented path.
- C2-C3 are not yet exercised; H1-H4 are not applicable because this collector does not simulate fills or brackets.
