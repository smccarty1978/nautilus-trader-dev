<!-- AUDIT_SUMMARY_V2_START -->
{"verdict":"BLOCKED","audit_type":"causal","auditor":"codex-lookahead-cleanflip-pass32","critical":0,"warning":1,"note":0,"study":"Codex_clean_maturity_flip_rolling_5m_productivity","audited_execution_composite_sha256":"5b45381851765e4deda7d82f85b2d535a99e88411a0eb7d2dd59595c099a39ef"}
<!-- AUDIT_SUMMARY_V2_END -->

# Look-Ahead & Timestamp Audit — Pass 32

**Date:** 2026-08-24T04:05:09Z
**Scope:** Diff-first re-audit of the explicit 532-instance migration: `compiled_study.json`, `features/registry.py`, `features/engine.py`, `features/trackers/ohlcv_delta.py`, and the CleanFlip collector. Unchanged label, timestamp, session, and target paths were checked only for continuity with prior clean findings.
**Scope hash:** `5b45381851765e4deda7d82f85b2d535a99e88411a0eb7d2dd59595c099a39ef` (equal in the current freeze and CLEAR preflight).
**Lint:** `audit/lint.json`: 93/93 files, 100% coverage, 0 critical / 0 warning. Preflight is CLEAR.
**Verdict:** BLOCKED

## Summary
- Critical: 0
- Warning: 1
- Note: 0

## Prior findings adjudicated

| # | Prior finding | Status | Evidence |
|---|---|---|---|
| Pass 31 B9/B10 | Parameterized definitions had no executable FeatureInstance binding. | **FIXED** | The compiled contract now declares 532 instances with 532 unique explicit physical aliases and no alias/mapping mismatches. The collector consumes the resolved alias list (`implementation/collector.py:189-204`), and `FeatureEngine.snapshot()` resolves each exact requested alias before reading that exact provider field (`features/engine.py:307-315`). The former first-key compatibility selection is absent; the remaining one-key fallback is deterministic and cannot select among parameter instances. |

## Critical findings

None.

## Warnings

### [B9] `compiled_study.json:1117-1122` — trailing OHLCV windows are declared as calendar timeframes

**Failure path:** `vol_sum_120s` is declared as `context=rolling, timeframe=120s`, and `est_delta_sum_300s` is likewise declared with `timeframe=300s` (`compiled_study.json:1337-1342`). Requirement derivation interprets every `timeframe` literally as a completed calendar-bar stream (`features/registry.py:1343-1349`), producing `completed_120s` and `completed_300s`. The bound OHLCV implementation instead consumes completed 1s bars and applies a trailing cutoff `obs_ts - W * NS` (`features/trackers/ohlcv_delta.py:57,211-212`). Thus the authenticated FeatureInstance/input contract describes completed calendar bars while runtime values retain trailing-window semantics. The current collector still receives completed 1s bars, so this does not change the historical CleanFlip numbers, but the causal/input contract is false and would misroute a consumer that obeys the derived requirements.

**Smallest fix:** Encode these rolling instances with `window=<duration>` (and the supported update cadence), keep completed 1s as the provider input, and regenerate the study contract so requirement derivation reports the actual trailing-window semantics. Do not alter provider calculations or historical aliases.

## Notes

None.

## Referred to contract-checker

- Confirm that OutputManager and the collector require the same complete 532-alias instance surface rather than treating definition-universe containment as completeness.

## Clean checks
- All 532 compiled instances have explicit aliases; all parameter-bearing instances preserve their declared parameters through `resolve_feature_request`; the four empty-parameter instances have empty schemas. There are 532 unique aliases and zero mapping mismatches.
- No instance requests `bar_state=forming`; completed regime instances and rolling-productivity `window=300s, update_every=1s` resolve causally.
- No arbitrary multi-alias compatibility fallback remains in the execution path.
- A1-A5, B1-B7, C1-C3, F1-F4, and G1-G4 remain clean on unchanged runtime paths.
- H1-H4 are not applicable; this collector has no offline bracket-price simulator.
