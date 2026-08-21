<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "causal", "auditor": "Codex reviewer /root/dense_causal_audit", "critical": 0, "warning": 0, "note": 0, "study": "NQ_dense_1s_2016_2026", "audited_execution_composite_sha256": "eab5e388ae688eff8aa1875b916254056017109a68c83d9881cbec806bd0a888"}
<!-- AUDIT_SUMMARY_V2_END -->

# Look-Ahead & Timestamp Audit — Pass 06

**Date:** 2026-08-20T15:58:12.3848990Z
**Scope:** Frozen surface in `data/canonical/audit/audit_packet.json`: changed `scripts/build_dense_1s.py`, changed `scripts/tests/test_build_dense_1s.py`, and closure-native exception policy in `data/canonical/config/deliverables_contract.json`. Review concentrated on the materiality guard, singleton exception-window construction, chronological consumption, carry state, and closure coverage.
**Scope hash:** execution composite `eab5e388ae688eff8aa1875b916254056017109a68c83d9881cbec806bd0a888`; all three frozen file hashes rechecked unchanged.
**Lint:** 0 critical / 0 warning; utility preflight `CLEAR`, compile check passed, focused pytest 19 passed (`data/canonical/audit/preflight.json`).
**Verdict:** CLEAR

## Summary
- Critical: 0
- Warning: 0
- Note: 0

## Prior findings adjudicated
| # | Prior finding | Status | Evidence |
|---|---|---|---|
| Pass 05 | No findings (CLEAR, 0 critical / 0 warning / 0 note) | N/A | No finding requires remediation. Normal-close/early-close selection, old-regime endpoint handling, causal fill, UTC/YTD, coverage, and publication paths remain clean; only isolated native closure handling changed. |

## Critical findings
None.

## Warnings
None.

## Notes
None.

## Referred to contract-checker
- Focused tests exercise isolated-versus-contiguous materiality but do not directly execute `add_native_exception_windows` through candidate construction; test sufficiency belongs to completion review.

## Clean checks
- **Exception discovery/materiality:** `validate_native_boundaries` classifies timestamps only after explicit UTC-to-`America/Chicago` conversion, collects only maintenance-interior and old-regime halt-interior native timestamps, sorts them, and blocks any contiguous one-second run or more than 100 rows (`scripts/build_dense_1s.py:146-191`). Exact approved 16:00:00 and 15:15:00 boundary seconds remain outside the exception list.
- **Singleton-only insertion:** `add_native_exception_windows` adds `[t,t+1s)` only when `t` is outside every normal calendar window, then sorts all windows (`scripts/build_dense_1s.py:194-200`). Because the guard rejects adjacent exception timestamps, singleton windows cannot combine into a filled closure span or overlap one another.
- **Native, not synthetic:** each singleton is derived from an observed raw `ts_event`; `NativeStream.read_window` consumes that exact row, and `densify_window` sees its only expected second as matched. It is therefore copied with `is_fill=false`; no closure second before or after it is synthesized. Duplicate/out-of-order raw timestamps remain independently fail-closed.
- **Carry-state causality:** processing order is chronological. After an exception, later fill state may use that already-observed native close, but never a later exception or reopen price. If no exception occurs, reopen behavior remains the last prior canonical close. This preserves causal availability even across the nominal closure.
- **Coverage/integrity:** the same augmented window list drives construction and exact coverage validation (`scripts/build_dense_1s.py:547-575`), so the approved singleton is expected exactly once while every other closure interior second remains forbidden. Native parity, fill validity, chronology, YTD overrun, and source hashes still block publication.
- **Checklist disposition:** A1/A3/A4, B1-B10, C1-C3, F1/F2, G3/G4, and H1-H4 are not exercised by this isolated raw-data utility. A2/A5, F3/F4, and G1/G2 were verified clean for closure-native exceptions.
