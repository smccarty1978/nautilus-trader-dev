# Phase D/E Completion Look-Ahead & Causal Audit

**Date:** 2026-07-25  
**Scope:** Final Phase D code and monthly artifacts, supervisor, Phase E validation and finalization, canonical outputs, build report and normative inventory annex, accepted Phase B/C inputs, and final specification §§12–19  
**Auditor:** lookahead-auditor v1  
**Scope hash:** `4dd25815fa9913f0e95ae9b1699c9a1416a916593fcda1444f50600235e4fa4b`

## Summary

- Critical: 0
- Warning: 0
- Note: 0
- Verdict: **PASS — the full-trade-path builder satisfies final acceptance**

## Findings

None.

## Acceptance evidence

### Final population

- Phase D source partitions: `60`
- Selected trades: `5,836`
- One-second path rows: `6,589,582`
- Completed fallback paths: `5,617`
- Right-censored paths: `219`
- Canonical population partitions: `120`
- Canonical path partitions: `5,307`
- Ambiguous same-bar rows: `9,841`

All monthly manifests are complete and share one Phase D identity and one accepted flip-ledger identity.

### Validation-to-finalization binding

The prior provenance blocker is resolved:

- The validator requires a complete 60-month global source manifest and exactly 60 monthly source partitions.
- Every monthly manifest must be complete and share the global Phase D and flip-ledger identities.
- Every source path and summary parquet is verified against its monthly manifest.
- The validation report records the source global-manifest hash and exactly 60 deterministic bindings containing each monthly manifest, path, and summary hash.
- All 60 bindings identify unique partitions.
- The finalizer requires the validation result to pass and rehashes the source global manifest, every monthly manifest, every path parquet, and every summary parquet.
- Canonical writes occur only after exact ledger equality.
- Validation SHA-256: `29138eb91eedbcb0fad2328b51bc0316c7d7a9016bab8c0c5c2ac15be79ba903`
- Source global-manifest SHA-256: `aff47e957c7beb9c1336bcda4e87429dc010fbeb942573eb987675c6b53783e9`

The canonical validation hash exactly matches the current validation-report bytes.

### Every-trade summary/path parity

- Trades checked: `5,836`
- Summary/path failures: `0`
- Path row-count, first/final timestamps, MFE/MAE values and timestamps, and completed fallback-return mark parity passed.
- Censored paths remained excluded from completed fallback economics.

### Direct raw-catalog parity

- Deterministic samples: `360`
- Monthly partitions represented: `60`
- Raw OHLC mismatches: `0`
- Samples cover endpoints, both directions, confirmation and fallback boundaries, and overlapping paths where available.

### Causal and timestamp semantics

- Phase C selection remains independent of future endpoints.
- Fallback is the first accepted opposite-direction flip strictly after confirmation.
- Endpoint information becomes operative only when replay reaches its timestamp.
- Paths start with the first completed bar whose open time is at or after the decision.
- The fallback boundary bar is included; the first subsequent bar is excluded and stored separately.
- Regime state for a row ending at `T` uses flips strictly before `T`.
- Five-second scores available at `T` attach to the row ending at `T`.
- Carried scores retain source timestamp, age, and carry status.
- MFE and MAE use one-second high/low with correct direction-normalized signs.
- Same-bar entry revisit plus new favorable extreme is explicitly ambiguous.
- No catalog access or path crosses the sealed boundary.

### Input and runtime provenance

- Phase B flip artifacts are monthly hash-verified and globally ledger-bound.
- Phase B carried-score artifacts are hash-verified during production and resume.
- Phase C selections must be complete, hash-valid, and carry the accepted historical identity.
- Bullish and Bearish warning thresholds are exactly bound to frozen sources.
- Waiver authorization and inclusive `>=` membership are enforced.
- Runner, strategy, core, task packet, configuration, waiver, threshold sources, and accepted upstream evidence are identity-bound.
- The memory-isolated supervisor aggregates exactly 60 complete common-identity manifests.

### Report completeness

`BUILD_REPORT.md` and `results/build_report_inventory.json` satisfy specification §18:

- Exact model and adapter hashes, model IDs, causal status, cadence, and thresholds are reported.
- The annex contains 60 monthly score/session/regime breakdowns.
- Availability and domain/exploratory counts are reported by regime.
- Selection, completion, censoring, overlap, and concurrency counts are reported.
- The annex contains all `5,307` canonical path partition row, size, and hash records.
- Every-trade and raw-bar validation, ambiguity, baseline economics, warning coverage, lead times, and frozen false-warning results are reported.
- No threshold optimization was performed.
- The 2025 threshold-reference overlap disclosure remains explicit.

## Specification §19 acceptance

| Criterion | Status |
|---|---|
| Causally corrected and refrozen Bullish model | PASS |
| Exact model-specific adapter parity | PASS |
| Runtime probability parity at five-second cadence | PASS |
| Frozen threshold manifests | PASS |
| NT-native global score collection | PASS |
| Exact first in-domain Top-2.5% selection | PASS |
| Frozen timestamp and descriptive-price conventions | PASS |
| Fallback mark for every completed trade | PASS |
| Decision-through-fallback MFE/MAE | PASS |
| Every-trade summary/path parity | PASS |
| Monthly deterministic raw-bar parity | PASS |
| Explicit censoring and economics exclusion | PASS |
| Both-model score visibility | PASS |
| Explicit exploratory out-of-domain state | PASS |
| Monthly partitioning, hashing, and resume behavior | PASS |
| Direct baseline MFE-capture computation | PASS |
| Opposite-model studies possible without path rebuild | PASS |

## Compliance matrix

| Rule | Status |
|---|---|
| A1–A5 | PASS |
| B1–B7 | PASS/N/A |
| C1–C4 | PASS/N/A |
| D1–D4 | PASS |
| E1–E5 | PASS/N/A |
| F1–F4 | PASS |
| G1–G4 | PASS/N/A |
| H1–H4 | N/A |
| Specification §§12–17 | PASS |
| Specification §18 | PASS |
| Specification §19 | PASS |

---

*Read-only completion audit complete. The full-trade-path builder meets the mandatory zero-critical/zero-warning acceptance gate.*
