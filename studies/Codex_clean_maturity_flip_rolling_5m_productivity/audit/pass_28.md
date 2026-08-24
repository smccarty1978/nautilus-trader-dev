<!-- AUDIT_SUMMARY_V2_START -->
{"verdict":"BLOCKED","audit_type":"causal","auditor":"codex-lookahead-canonical-provider-pass28","critical":3,"warning":2,"note":1,"study":"Codex_clean_maturity_flip_rolling_5m_productivity","audited_execution_composite_sha256":"cda6a8e680f742815ddb8a0be4a0c83c927366841a524b5685f9019e5fab5b32"}
<!-- AUDIT_SUMMARY_V2_END -->

# Look-Ahead & Timestamp Audit — Pass 28

**Date:** 2026-08-23T03:21:04.7670559Z
**Scope:** Diff-first component review of the ten staged generic provider modules, parameterization changes in `features/trackers/ohlcv_delta.py` and `features/trackers/price_levels.py`, the V2 temporal validator/resolver in `features/registry.py`, and `scripts/run_full_legacy_feature_parity.py`.
**Scope hash:** Working-tree component hash `4d00ecba6b4a2a16c94aeea4fdbadeab12ba59bea4cb0be5afb61f2e5c39c4b3` (14 files, sorted path plus SHA-256).
**Lint:** Focused `causal_lint.py`: 14/14 files, 0 critical / 0 warning. Focused pytest: 19 passed.
**Verdict:** BLOCKED

## Summary
- Critical: 3
- Warning: 2
- Note: 1

## Prior findings adjudicated

| # | Prior finding | Status | Evidence |
|---|---|---|---|
| Pass 27 B9/B10 | Instance schemas admit temporal combinations the providers do not implement. | NOT FIXED | `validate_feature_instance` still checks only top-level `bar_state` and `timeframe`; nested source/reference states and timeframes pass through, and `derive_instance_input_requirements` falls back to the fixed legacy stream (`features/registry.py:844-895,916-928`). |

## Critical findings

### [A1/B2] `features/trackers/generic_ohlcv_delta.py:26-35` — the completed-bar API requires an open-stamp-named clock that the tracker treats as availability time
**Failure path:** `update_completed_bar(**bar)` forwards to `OHLCVDeltaTracker.update(ts_event=...)`; `accumulate_regime` also exposes `ts_event`. The tracker uses this field as the observation close clock for cutoffs and elapsed calculations (`features/trackers/ohlcv_delta.py:103-134,207-244,328-392`). Passing a normal NT bar's open-stamped `ts_event` therefore marks the bar/window one interval early and shifts regime-window membership; only deliberately passing `bar.ts_init` under the misleading `ts_event` name is causal.
**Smallest fix:** Make the generic boundary accept `ts_avail`/`close_ts`, reject ambiguous `ts_event`, and pass that close timestamp to the legacy tracker explicitly.

### [B9/G2] `features/trackers/generic_arrival.py:16-29,90-122` — second-valued windows count observations and silently bridge missing seconds
**Failure path:** Arrival state stores no timestamps. After five ordinary observations followed by a gap, `velocity(window=5)` compares the latest value with the fifth prior observation and divides by five even if those observations span 20 seconds; relative-volume and correlation windows behave the same. `GenericMedianCenterProvider.slope` similarly interprets `sample_seconds` as an observation count (`features/trackers/generic_median_center.py:37-47`). Native 1s gaps therefore change the effective horizon and the feature number while the instance still claims a seconds duration.
**Smallest fix:** Store/require close timestamps and either enforce the exact cadence or select and validate observations by elapsed-time boundaries, returning the declared unavailable/null state for incomplete windows.

### [B9] `features/trackers/generic_arrival.py:17-35,91-111` — query domains can exceed retained state and return valid-looking neutral values forever
**Failure path:** A provider constructed with `max_window_seconds=5` accepts `velocity(window=7)` and returns `0.0` indefinitely because the deque can never hold eight samples; volume queries whose aggregation plus baseline exceeds capacity similarly return `1.0`. `GenericMedianCenterProvider(retained_seconds=20)` accepts a 30-second query and computes from the retained tail as though it covered the requested window (`features/trackers/generic_median_center.py:20-47`). These are wrong valid-looking numbers, not declared unavailability.
**Smallest fix:** Bind supported query domains at construction/resolution and fail closed when any requested window/sample/baseline exceeds retained causal history.

## Warnings

### Continuing [B9/B10] — unsupported compound temporal instances remain accepted
`source_bar_state="forming"`, `reference_bar_state="forming"`, and unsupported source/reference timeframes validate, yet resolve to the completed `1s+1m+5m` legacy provider; rolling cadence is likewise unconstrained (`features/registry.py:844-895,916-928`). Current legacy aliases remain completed 1m/5m and are not numerically changed.

### [B2] `features/trackers/generic_price_levels.py:25-38` — `observation_ts` does not bound provider state
After feeding completed minutes through T+2, requesting a snapshot for T returns rolling/session levels from the later state because `PriceLevelTracker.calculate` reads all current deques and uses `observation_ts` only for elapsed fields (`features/trackers/price_levels.py:110-180,190-233`). The live event loop currently snapshots immediately, but this causal-order invariant is not enforced by the staged generic API.

## Notes
- The available `CLEAR` preflight and declared composite `cda6a8e...` predate these staged/untracked providers. This component report does not authenticate or clear that working-tree surface; PREPARE/FREEZE/preflight must be rerun after remediation.

## Referred to contract-checker
- Assess whether the parity artifact proves availability/reset coverage and manifest closure; the causal audit does not gate deliverable completeness or test-evidence sufficiency.

## Clean checks
- A2-A5, B1, B3-B7, C1-C3, F1-F4, G1, G3-G4, H1-H4 clean or non-applicable on the changed component surface.
- Completed-only restrictions in the structural and rolling adapters, exact trailing boundaries in rolling productivity, named-zone session conversion, price-level rolling gap invalidation, and OHLCV/price-level custom-window construction were otherwise clean.
