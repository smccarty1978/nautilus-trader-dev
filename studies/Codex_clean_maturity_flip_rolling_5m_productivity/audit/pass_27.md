<!-- AUDIT_SUMMARY_V2_START -->
{"verdict":"BLOCKED","audit_type":"causal","auditor":"codex-lookahead-fsv2-pass27","critical":0,"warning":1,"note":0,"study":"Codex_clean_maturity_flip_rolling_5m_productivity","audited_execution_composite_sha256":"cda6a8e680f742815ddb8a0be4a0c83c927366841a524b5685f9019e5fab5b32"}
<!-- AUDIT_SUMMARY_V2_END -->

# Look-Ahead & Timestamp Audit — Pass 27

**Date:** 2026-08-22T15:30:00Z
**Scope:** Contextual diff from pass 26 through frozen Feature System V2 composite `cda6a8e...`; causal review of `features/registry.py`, `features/calendar_aggregation.py`, the unchanged structural/rolling providers, `features/engine.py`, the CleanFlip collector/phase0 integration, and relevant V2/legacy parity tests. `backtests/nt_runtime/readiness.py` and OutputManager were inspected only to resolve R10/runtime state flow. No `audit_packet.json` exists for this study, so `git diff -U20` plus the frozen manifest was the primary surface.
**Scope hash:** `cda6a8e680f742815ddb8a0be4a0c83c927366841a524b5685f9019e5fab5b32`; independently re-resolved with 90/90 identical canonical hashes, no added/removed/modified closure entries.
**Lint:** `audit/lint.json`: 82/82 files, 100% coverage, 0 critical, 0 warning. `audit/preflight.json`: CLEAR, run `20260822T152209Z_443aeb660c91`, all six mandatory checks passed.
**Verdict:** BLOCKED

## Summary
- Critical: 0
- Warning: 1
- Note: 0

## Prior findings adjudicated

| # | Prior finding | Status | Evidence |
|---|---|---|---|
| Pass 26 note | WITHDRAWN as historical-only | The pass-26 composite delta attribution was informational and applied to `3be6c871...`. This pass independently resolved and reviewed the new V2 composite `cda6a8e...`; no prior causal warning or critical remained to adjudicate. |

## Critical findings

None.

## Warnings

### [B9/B10] `features/registry.py:740-764, 835-906` — verified instance schemas admit temporal combinations the providers do not implement

**Failure path:** `move_outside_completed_range` declares `source_bar_state` and `reference_bar_state`, but `validate_feature_instance` validates neither value. An instance requesting `source_bar_state="forming"` and `reference_bar_state="forming"` resolves as VERIFIED; `derive_instance_input_requirements` then falls through to a completed-stream requirement, while `StructuralRegimeGeometryTracker` only consumes completed 1m/5m state (`structural_regime_geometry.py:73-89,119-150`). A forming 5m high can differ from the last completed 5m high, so the resolved feature value can be temporally different from the requested instance. Similarly, arbitrary completed timeframes such as 3m resolve to the same provider even though its state is concretely 1m/5m. Rolling definitions accept arbitrary `update_every`, while the provider integration is fixed to completed 1s updates. The current CleanFlip aliases are unaffected because every migrated structural alias explicitly requests completed 1m/5m and every rolling alias requests `window=300s, update_every=1s`; this is therefore a real non-headline temporal-contract defect, not a current-result critical.

**Smallest fix:** Fail closed on unsupported parameter domains/states: constrain the structural definitions to the provider's proven completed 1m/5m combinations, validate source/reference bar states explicitly, and constrain rolling cadence to the wired completed-1s cadence until other combinations have actual provider/runtime support and causal evidence.

## Notes

None.

## Referred to contract-checker
- Verify that promotion evidence and the frozen/sealed closure bind `feature_definition_promotions.json` and prove the declared parameter domains, rather than authenticating only the unchanged historical tracker files and legacy instances.

## Clean checks
- A1-A5: unchanged NT timestamp path; R2/R4 readiness evidence confirms 1s/1m close availability and callback order.
- B1-B8: no future shift, centered window, backfill, future join, or full-sample normalization added.
- B9/B10: current completed 1m/5m structural aliases and trailing 300s rolling aliases are clean; broader accepted domains blocked above.
- C1-C3: label construction/splits unchanged from pass 26.
- F1-F4, G1-G4: unchanged and clean for the current execution path.
- H1-H4: N/A; no offline bracket simulation in this collector.
