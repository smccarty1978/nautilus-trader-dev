<!-- AUDIT_SUMMARY_V2_START -->
{"verdict":"BLOCKED","audit_type":"causal","auditor":"codex-lookahead-cleanflip-pass31","critical":1,"warning":0,"note":0,"study":"Codex_clean_maturity_flip_rolling_5m_productivity","audited_execution_composite_sha256":"df1c7a75ca963214f8aa178f9832c5497afd9023f0b657718fd62b05c400604d"}
<!-- AUDIT_SUMMARY_V2_END -->

# Look-Ahead & Timestamp Audit — Pass 31

**Date:** 2026-08-24T03:30:23Z
**Scope:** Diff-first re-audit of the pass-30 remediation. Comparing pass 30's authenticated file map with the current freeze identifies exactly three changed closure entries: `features/registry.py`, `features/engine.py`, and the regenerated phase-zero manifest. Only the first two contain causal behavior.
**Scope hash:** `df1c7a75ca963214f8aa178f9832c5497afd9023f0b657718fd62b05c400604d` (equal in current freeze and CLEAR preflight).
**Lint:** `audit/lint.json`: 84/84 files, 100% coverage, 0 critical / 0 warning. Preflight required gates all PASSED.
**Verdict:** BLOCKED

## Summary
- Critical: 1
- Warning: 0
- Note: 0

## Prior findings adjudicated

| # | Prior finding | Status | Evidence |
|---|---|---|---|
| Pass 30 B9/B10 | Parameterized definitions execute without FeatureInstances and collapse to an arbitrary compatibility value. | **NOT FIXED** | First-key selection was removed, but the study still declares `feature_list: null` and `instances: null` (`compiled_study.json:65-66`). The replacement calls `canonicalize_provider_columns(raw_features)` as though it returned canonical values (`features/engine.py:301-328`), while that helper returns an old-name → canonical-name rename map. Multi-instance definitions therefore resolve to no value instead of a declared instance. |
| Pass 30 B2/B9 | Active resolver bypasses temporal/domain validation. | **FIXED** | Parameter-bearing active requests now call `validate_feature_instance()` before requirement derivation (`features/registry.py:1279-1297`). Direct checks confirm unsupported `regime_efficiency(..., bar_state=forming)` and `rolling_retention_ratio(..., update_every=5m)` fail closed. Definitions outside the pre-existing in-module V2 set also fail closed rather than accepting unsupported parameters. |

## Critical findings

### [B9/B10] `features/engine.py:301-328` — parameterized canonical definitions still have no executable FeatureInstance binding

**Failure path:** CleanFlip still requests a definition universe with no FeatureInstances (`compiled_study.json:65-66`). The new code removes first-compatible-key selection, but `canonicalize_provider_columns()` returns a rename dictionary such as `{"arrival_vel_5s": "arrival_velocity", "arrival_vel_10s": "arrival_velocity"}` (`features/registry.py:1387-1392`); it does not transform provider values into `{"arrival_velocity": value}`. Consequently `canonical_raw_features.get("arrival_velocity")` is absent. Because `arrival_velocity` has four compatibility keys, the one-key fallback is intentionally skipped and the emitted canonical value becomes `None`. The same occurs for multi-instance definitions such as `regime_efficiency` and `vol_sum`. This removes the arbitrary value but still does not execute a declared lookback/timeframe/context; valid historical calculations become unavailable while R10 continues to pass on column-name containment alone. The study's feature values and null/availability behavior are therefore changed.

**Smallest fix:** Make executable study requests explicit validated FeatureInstances and bind each instance directly to its generic provider output. A definition-universe request may authenticate definitions, but must not be treated as an executable parameter choice. Do not collapse multiple parameter instances into one unparameterized column.

## Warnings

None.

## Notes

None.

## Referred to contract-checker

None. The pass-30 manifest-coverage referral is not re-raised here.

## Clean checks
- A1-A5, C1-C3, F1-F4, G1-G4 remain clean on the unchanged collector/label/data path.
- B1, B3-B7 remain clean; the two changed code files introduce no future-indexed transform.
- B2/B9 temporal validation remediation is fail-closed for unsupported forming state and cadence.
- H1-H4 remain non-applicable; no offline bracket simulator exists in this collector.
