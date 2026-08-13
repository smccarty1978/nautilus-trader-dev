# Phase B Final-Boundary Correction Audit

**Date:** 2026-07-24  
**Scope:** December interval changes in `run_phase_b_months.py`, `finalize_phase_b_labels.py`, collector seal behavior, task packet, and unchanged Phase B config  
**Scope hash:** `3f6158cfd2a2dcf408942db189c3d1899c4de6ddaaf94e3e49a628bf6ff5dce5`  
**Auditor:** lookahead-auditor v1  
**Verdict:** **PASS — December collection and global finalization authorized**

## Summary

- Critical: 0
- Warning: 0
- Note: 0

## Critical findings

None.

## Warnings

None.

## Clean checks

### December interval

- The runner special-cases only `(2025, 12)` and sets its exclusive end directly to `SEALED_BOUNDARY`.
- All other months retain exact America/Chicago calendar boundaries converted to UTC.
- December begins at `2025-12-01 00:00 America/Chicago` and ends at `2026-01-01T00:00:00Z`.
- The resulting partition is intentionally a partial CT-calendar month, matching the revised frozen contract.
- All December RTH observations remain before the seal; only post-seal evening data is excluded.

### No 2026 access

- The monthly collector rejects `end > SEALED_BOUNDARY`.
- December now passes with `end == SEALED_BOUNDARY`.
- Forward label loading remains `min(end+601s, SEALED_BOUNDARY)`.
- The NT engine run end is the same sealed timestamp.
- Labels are joined only from flip facts observed no later than the seal.

### Label and censor semantics

- Global label observability ends exactly at `SEALED_BOUNDARY`.
- Same-time flips remain excluded.
- The 300- and 600-second censor flags continue to use horizon-specific observability.
- The shared censor flag remains the conservative 600-second flag.
- No label affects checkpoint emission, features, model scores, domains, or ranks.

### Resume and provenance

- Runner and finalizer require the corrected December end.
- A stale December manifest using the former CT-midnight end fails validation.
- Existing completed partitions retain valid config and runtime provenance.
- All partitions still require four-day warmup, current config hash, identical runtime identity, and valid artifact hashes.

### Finalization safety

- The finalizer still requires exactly 60 provisional partitions.
- It validates every interval before reading the global flip ledger.
- December cannot be accepted with a post-seal end.
- Global finalization occurs only after corrected December completes.
- Final manifests retain the flip-ledger, finalizer-code, and sealed observation-end hashes.

## Compliance matrix

| Rule | Status |
|---|---|
| A1–A5 | PASS |
| B1–B7 | PASS |
| C1–C3 | PASS |
| D1–D4 | PASS/N/A |
| E1–E2 | PASS |
| F1–F4 | PASS |
| G1–G4 | PASS |
| H1–H4 | N/A |

*Read-only targeted audit. The corrected December run and subsequent single global finalizer may proceed.*
