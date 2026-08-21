# Look-Ahead & Timestamp Audit — Pass 01

**Date:** 2026-08-14T05:26:54.4543422-05:00  
**Scope:** 38 files: the changed registry/tracker; all study source, config, test, result-manifest, and run-status files relevant to collection and decile evaluation; inherited aggregator/registry/regime and Walk-A path engines; one generated 2024-01 structural partition and its raw NQ.v.0 1s source for deterministic evidence.  
**Scope hash:** `9b7e03b7838694579c6f3d3a6debc7400878609870c4db2f95697443fb93daf7`  
**Lint:** 0 critical / 0 warning from `causal_lint.py`  
**Verdict:** BLOCKED

## Summary

- Critical: 3
- Warning: 1
- Note: 0

## Critical findings

### [A1/A5] `implementation/collector.py:53-60` — equal-time 5m snapshots omit the bucket that just completed

**Failure path:** For a 1s bar covering `[T-1s,T]`, the collector passes `ts_event=T-1s` to `TimeframeAggregator` and snapshots at `ts_init=T`. The aggregator closes a bucket only when a bar whose `ts_event` is in the next bucket arrives (`collectors/collector_v2/aggregator.py:121-157`), so the 5m bucket ending at `T` is published at `T+1s`, after the checkpoint at `T`. The generated 2024-01 partition confirms the wrong state: 3,482 ordinary 5m-boundary checkpoints have `checkpoint_decision_ns - current_5m_completed_close_ts = 300s`, rather than using the bar whose `close_ts == T` as required by `SPEC.md:49-58`. Every 5m-boundary row therefore has stale range, displacement, ATR/regime, and distance features; those rows enter fitting and OOS AUC/decile results.

**Smallest fix:** Publish the bucket ending at `T` after consuming its final completed 1s bar and before the `T` snapshot, while preserving forming-bucket exclusion; then recollect and reevaluate.

### [A1] `implementation/collector.py:53-56` — 1s extrema are stamped with bar-open time

**Failure path:** `_geometry.on_1s(te, ...)` stores `bar.ts_event` in `_Regime.high_ns/low_ns` (`features/trackers/structural_regime_geometry.py:31-35`), and a later flip freezes that timestamp as `structural_origin_ns` (`structural_regime_geometry.py:63-70`). For every extreme formed by a 1s bar with `ts_event=t` and `ts_init=t+1s`, the origin is recorded one second early. `structural_expansion_atr_per_min` then divides by `(T-origin_ns)` (`structural_regime_geometry.py:121-129`), producing a systematically understated speed that enters both train and OOS models.

**Smallest fix:** Timestamp completed-1s extrema with `bar.ts_init`, retain `ts_event` only where an open-time bucket identifier is explicitly required, and rerun dependent artifacts.

### [G4] `implementation/collector.py:55-56` — single-tick bars feed structural and 5m indicators

**Failure path:** There is no volume/single-tick guard before the bar updates the current-regime extrema and the 5m `EMA3/EMA9`/ATR state (`collectors/collector_v2/regime_engine.py:67-109`). The NQ.v.0 source contains such inputs: on 2024-01-02, 9,162 of 48,207 1s bars had volume 1 and zero range. A single print at a new price therefore changes a structural high/low and expansion, and can change the aggregated 5m regime/ATR, contrary to G4; the resulting features affect fitted scores and the reported conclusion.

**Smallest fix:** Enforce and document the G4 eligibility policy before both tracker and aggregator updates, then recollect and reevaluate.

## Warnings

### [B9] `features/registry.py:611-617` — registry metadata omits the load-bearing 1m-flip update

All registered structural fields declare `source_timeframe='1s'` and `update_anchor='completed_1s_and_completed_5m'`, but current/prior 1m state and frozen origins require `on_1m_flip` (`collector.py:64-70`). The present collector calls it explicitly, so this does not itself change this run, but a registry-driven consumer cannot reproduce the feature cadence from the declared metadata.

## Notes

None.

## Referred to contract-checker

- Deliverable coverage between the registry/SPEC structural family and the fitted feature list requires contract adjudication.
- The exhaustive decile evaluation timed out and was replaced by a sampled economic diagnostic; manifest/report compliance requires contract adjudication.

## Clean checks

- A2-A4; B1-B7 and B10; C1-C3; F1-F4; G1-G3; H1-H4 verified clean or not applicable on the inspected causal paths.
- Labels remain isolated from feature fitting; model fitting, score thresholds, and decile edges use 2021-2023 only, with 2024 held OOS.
- Walk-A stop detection uses 1s high/low and next-bar-open fills with adverse same-bar resolution; no trigger-price fill was found.
