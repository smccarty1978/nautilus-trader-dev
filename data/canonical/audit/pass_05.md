<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "causal", "auditor": "Codex reviewer /root/dense_causal_audit", "critical": 0, "warning": 0, "note": 0, "study": "NQ_dense_1s_2016_2026", "audited_execution_composite_sha256": "52e7179b890012f47d368cb9cbcedf59d4308b8e85d5a49fb26d5faa438ee46c"}
<!-- AUDIT_SUMMARY_V2_END -->

# Look-Ahead & Timestamp Audit — Pass 05

**Date:** 2026-08-20T15:52:07.8787779Z
**Scope:** Frozen surface in `data/canonical/audit/audit_packet.json`: changed `scripts/build_dense_1s.py`, changed `scripts/tests/test_build_dense_1s.py`, and unchanged endpoint convention in `data/canonical/config/deliverables_contract.json`. Review concentrated on limiting the terminal-second override to normal 16:00 CT closes and explicit old-regime 15:15:00/15:15:01 handling.
**Scope hash:** execution composite `52e7179b890012f47d368cb9cbcedf59d4308b8e85d5a49fb26d5faa438ee46c`; all three frozen file hashes rechecked unchanged.
**Lint:** 0 critical / 0 warning; utility preflight `CLEAR`, compile check passed, focused pytest 19 passed (`data/canonical/audit/preflight.json`).
**Verdict:** CLEAR

## Summary
- Critical: 0
- Warning: 0
- Note: 0

## Prior findings adjudicated
| # | Prior finding | Status | Evidence |
|---|---|---|---|
| Pass 04 | No findings (CLEAR, 0 critical / 0 warning / 0 note) | N/A | No finding requires remediation. The causal fill, native-boundary scan, coverage, publication, and YTD paths remain unchanged; only the calendar-close endpoint predicate and focused tests changed. |

## Critical findings
None.

## Warnings
None.

## Notes
None.

## Referred to contract-checker
None.

## Clean checks
- **Normal-close predicate:** `market_close` is converted from the calendar's timezone-aware timestamp to `America/Chicago`; only a 16:00 CT close receives the exact one-second extension (`scripts/build_dense_1s.py:121-127`). The predicate therefore follows DST through the named zone and does not rely on a fixed UTC offset.
- **Early closes:** holiday/special closes that are not 16:00 CT retain the library's half-open endpoint (`scripts/build_dense_1s.py:123-127`). The Thanksgiving case confirms the early-close boundary is not extended (`scripts/tests/test_build_dense_1s.py:101-107`). This removes the pass-04 broadened endpoint without changing any prior-close state or native value.
- **Old-regime halt:** the first interval still ends at `break_start + 1s`, so exact 15:15:00 CT is represented once and 15:15:01–15:29:59 remain outside all expected windows (`scripts/build_dense_1s.py:128-142`). The boundary scan accepts exact 15:15:00 and rejects 15:15:01 (`scripts/tests/test_build_dense_1s.py:127-138`).
- **No future-price path:** adjusted window endpoints only determine membership. `NativeStream.read_window` and `densify_window` remain unchanged: a missing accepted endpoint is synthesized from the last matched canonical close at or before that timestamp, never from the next reopen/native price.
- **Coverage/YTD:** the final-source cap remains `last_native_ns + 1s`, so neither the normal-close override nor a later calendar session can extend beyond 2026/YTD. Exact coverage, native parity, fill-price validity, chronology, and closure-interior counts still block publication.
- **Checklist disposition:** A1/A3/A4, B1-B10, C1-C3, F1/F2, G3/G4, and H1-H4 are not exercised by this isolated raw-data utility. A2/A5, F3/F4, and G1/G2 were verified clean for the tightened endpoint rule.
