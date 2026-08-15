# Look-Ahead & Timestamp Audit — Pass 13

**Date:** 2026-08-15T01:22:28-05:00  
**Scope:** New completed-1m-to-5m aggregator, changed collector routing/reset paths, structural tracker/5m registry-engine state flow, and the model runner's structural coverage gate  
**Scope hash:** `1c7432238645b46b8968befb3f66dc2774ed2882e541e2d679988539312f7f51`  
**Lint:** 0 critical / 0 warning  
**Verdict:** BLOCKED

## Summary

- Critical: 1
- Warning: 1
- Note: 0

The new aggregator promotes no forming 5m bar and correctly ignores 1s-only defects when the completed 1m parent is valid. The 1m discontinuity reset does not reset all recursive 5m state.

## Prior findings adjudicated

| # | Prior finding | Status | Evidence |
|---|---|---|---|
| C-01 | C3 2024 opened before direction-specific freeze | FIXED | The model-runner order remains train load, train coverage, train-only freeze/fit, then the first OOS load (`run_exploratory_models.py:178-227`). The new coverage checks do not send OOS information backward. |
| C-02 | G2/C3 partial or duplicated annual partitions accepted | FIXED | Exact annual bounds, required-year identity, row-year equality, lineage, and duplicate checkpoint checks remain unchanged in `_load_partitions` (`run_exploratory_models.py:125-175`). |

## Critical findings

### [G2/B9] `implementation/collector.py:244-268,293-306` — a missing or rejected 1m parent leaves recursive 5m regime state alive

**Failure path:** A completed 5m state exists, then a 1m parent is missing or has volume <= 1. `_reset_after_1m_discontinuity` replaces the 1m engines, geometry tracker, and 5m bucket builder, but it does not replace `_registry` or `_engine_5m`. When the first complete post-gap 5m bucket is later promoted, `RegimeStateEngine` computes its EMA, ATR, sticky regime, and previous-close true range from pre-gap 5m state. Geometry then consumes those bridged values and can emit structurally available post-gap features with the wrong 5m regime/ATR.

**Smallest fix:** In the shared 1m-discontinuity reset, also create a fresh 5m `CompletedBarRegistry` and `RegimeStateEngine` before accepting any post-gap parent.

## Warnings

### [A2/B9] `implementation/collector.py:244-263`; `collectors/collector_v2/aggregator.py:259-286` — completed-parent availability relation is assumed, not enforced

The new aggregator buckets on 1m `ts_event`, while the callback is ordered by `ts_init`. It checks minute alignment but never verifies `ts_event + 60s == ts_init`. The configured catalog is expected to satisfy that convention, but a shifted parent stream could be grouped into the wrong 5m window without an immediate fail-closed error.

**Smallest fix:** Before any 1m state update, require `int(bar.ts_event) + 60 * NS == int(bar.ts_init)` and raise on violation.

## Notes

- None.

## Referred to contract-checker

- None newly referred this pass.

## Clean checks

- A1, B2, G2/G4: each 5m callback occurs only after five exact, aligned, quality-approved completed 1m parents; the current/forming bucket is never exposed.
- B2/C1-C2/G2: 1s gaps and rejected seconds still stop 1s feature advancement, invalidate overlapping label horizons on availability timestamps, and suppress rows through causal recovery; they do not erase an independently valid completed 5m parent history.
- C3: train structural coverage is checked before train-only selection/fitting; OOS coverage is checked only after the first authenticated 2024 load and does not alter fitted models.
- A3-A5, B1, B3-B7, B10, F1-F4, G1, G3 remain clean. H1-H4 are not applicable.
