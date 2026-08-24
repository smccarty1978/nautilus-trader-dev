<!-- AUDIT_SUMMARY_V2_START -->
{"verdict":"BLOCKED","audit_type":"causal","auditor":"codex-lookahead-cleanflip-pass30","critical":2,"warning":0,"note":0,"study":"Codex_clean_maturity_flip_rolling_5m_productivity","audited_execution_composite_sha256":"ee064017c7f275aae5b470115982a440eb2dca608165e854dacb66f4e6623fc7"}
<!-- AUDIT_SUMMARY_V2_END -->

# Look-Ahead & Timestamp Audit — Pass 30

**Date:** 2026-08-24T03:08:37Z
**Scope:** Diff-first causal review of the frozen canonical-only integration: active feature resolution, FeatureEngine provider binding, CleanFlip collector timestamp/label flow, and active authority instance metadata. The unchanged label, regime, rolling-productivity, and completed 1m→5m state paths were checked against the prior clean reviews only where needed to resolve the new canonical state flow.
**Scope hash:** `ee064017c7f275aae5b470115982a440eb2dca608165e854dacb66f4e6623fc7` (equal in `audit/frozen_execution_manifest.json` and `audit/preflight.json`).
**Lint:** `audit/lint.json`: 84/84 files, 100% coverage, 0 critical / 0 warning. Preflight: CLEAR, 493 passed / 2 deselected.
**Verdict:** BLOCKED

## Summary
- Critical: 2
- Warning: 0
- Note: 0

## Prior findings adjudicated

| # | Prior finding | Status | Evidence |
|---|---|---|---|
| Pass 29 note | Governed preflight predates the staged component. | FIXED | Current freeze and preflight both bind composite `ee064017...`; preflight is `CLEAR` and postdates the canonical-only integration. |

## Critical findings

### [B9/B10] `features/engine.py:294-309` — parameterized definitions are executed without a FeatureInstance and collapse to an arbitrary compatibility value

**Failure path:** The compiled study declares `instances: null` and `feature_list: null` (`compiled_study.json:65-66`) while requesting the entire canonical-definition universe. `resolve_feature_request()` accepts a bare canonical name and returns empty parameters plus the canonical name as its sole physical alias (`features/registry.py:1226-1286`). FeatureEngine then searches `provider_compatibility_keys()` and takes the first historical key present (`features/engine.py:294-309`). This is not parameter-neutral: `arrival_velocity` covers 5/10/20/30-observation lookbacks, `regime_efficiency` covers completed prior 1m and 5m streams, and `vol_sum` covers regime-reset and multiple rolling-window values. The current sorted fallback selects `arrival_vel_10s`, `prior_1m_regime_efficiency`, and `regime_vol_sum`, respectively, without those parameters being declared. Consequently the emitted canonical column can contain a different lookback, input stream, reset policy, value, and availability than another legitimate instance of the same definition. R10's set-containment check cannot detect this because all are renamed to the same allowed canonical column.

**Smallest fix:** Require explicit, validated FeatureInstances for every parameterized definition used by the study and bind each resolved instance directly to the provider output for those parameters; remove first-compatible-key selection as an execution rule.

### [B2/B9] `features/registry.py:1226-1309` — active resolver bypasses the existing temporal/domain validator

**Failure path:** The active-bundle branch copies supplied parameters directly (`resolved_parameters = supplied`) and derives streams without calling `validate_feature_instance()` or an equivalent bundle validator. A request for `regime_efficiency(timeframe=1m, context=prior, bar_state=forming)` therefore resolves successfully and advertises `forming_1m`, although `GenericStructuralGeometryProvider` only accepts completed 1m regime transitions and completed 5m regime bars (`features/trackers/generic_structural_geometry.py:19-34`). Likewise an arbitrary rolling cadence such as `rolling_retention_ratio(window=60s, update_every=5m)` resolves despite the provider's completed-1s update contract. This lets a study compile an unsupported temporal mode rather than failing closed, so the declared availability can diverge from the actual completed-bar state used at runtime.

**Smallest fix:** Validate active-authority parameters, required fields, supported combinations, bar states, cadence, and provider domains before deriving input requirements; reject unsupported forming/cadence requests.

## Warnings

None.

## Notes

None.

## Referred to contract-checker
- Verify that the frozen execution closure authenticates the dynamically loaded `features/authority/*` bundle and `features/trackers/generic_*.py` provider modules; they are not listed in the current frozen manifest.

## Clean checks
- A1-A5: CleanFlip continues to order and index 1s/1m/derived-5m state by completed `ts_init`; 1m requires `ts_event + 60s == ts_init`.
- B1, B3-B7: no centered/negative-lag/backfill/future-normalization path was introduced by the canonical integration.
- C1-C3: label horizon remains strictly `(T, T+300s]`, resolves only after the full horizon, and stays separate from feature snapshots.
- F1-F4: decision/session checks use close-time timestamps and `America/Chicago`; rolling boundary checks are backward-looking.
- G1-G4: catalog/data-quality and completed-bar gap guards are unchanged on the reviewed execution path.
- H1-H4: not applicable; this collector has no offline bracket simulator.
