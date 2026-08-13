# Phase B Implementation Third Audit

**Date:** 2026-07-24  
**Scope:** Phase B adapter, strategy, collector, global label finalizer, runtime parity validator, contract tests, frozen packet/config, and relevant final-spec clauses  
**Scope hash:** `d12296bdf8b02a53e7184b67575bbb904df4b8e9b80ff371a7d3217792223c1e`  
**Auditor:** lookahead-auditor v1  
**Verdict:** **PASS — safe to run the March parity/benchmark**

## Summary

- Critical: 0
- Warning: 0
- Note: 0

## Critical findings

None.

## Warnings

None.

## Clean checks

### Runtime parity

- Duplicate Phase B checkpoint keys fail immediately.
- Every expected Bullish and in-session Bearish reference key must exist.
- Null masks are compared before complete-row scoring filters.
- Ordered vectors, feature-vector hashes, probabilities, and raw scores must all agree.
- Both models must have nonempty parity populations.
- All percentile, decile, and Top-N fields must remain null.
- Expected and matched key counts plus mismatch diagnostics are persisted.

### Global label finalization

- Finalization requires exactly 60 monthly partitions covering 2021–2025.
- Every partition must be explicitly provisional before finalization.
- UTC intervals are derived from exact Central-time calendar months.
- Score, flip, and missing-dispatch hashes are validated before the global join.
- Flip facts are deduplicated by timestamp and direction.
- Finalized manifests record the global flip-ledger and finalizer-code hashes.
- Monthly manifests become `complete` only after the global rewrite.

### Timestamp and causal state

- A real BacktestEngine test verifies coincident 1-second callbacks precede 1-minute callbacks.
- The runner structurally uses the tested finer-stream-first order.
- Decisions use exact callbacks with completed `ts_event<T` sources.
- Equal-time minute updates occur after scoring at `T`.
- Bullish and Bearish adapters remain separate.
- Emission is independent of future flips, labels, model domain, and later regime completion.
- Missing dispatches are diagnosed and never synthesized.

### Provenance and schema

- Bearish model, ordered features, mapping, engine, trackers, and RegimeEngine are hash-bound.
- Monthly manifests record collector code, dependencies, models, mapping, config, and catalog.
- Per-model schema, availability reasons, vector hashes, and null rank fields are separate.
- Same-time flips are excluded; +300/+600 endpoints are inclusive.
- Horizon-specific and conservative shared censoring are correct.

## Compliance matrix

| Rules | Status |
|---|---|
| A1–A5 | PASS |
| B1–B7 | PASS/N/A |
| C1–C3 | PASS |
| C4 | N/A |
| D1 | PASS |
| D2 | N/A |
| D3–D4 | PASS |
| E1–E2 | PASS |
| E3–E5 | N/A |
| F1–F4 | PASS |
| G1–G3 | PASS |
| G4 | N/A |
| H1–H4 | N/A |

---

*Read-only pre-execution audit. This verdict authorizes the bounded March parity/benchmark only; full-build acceptance still requires the specified runtime results and completion audit.*
