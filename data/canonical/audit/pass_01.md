<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "causal", "auditor": "Codex reviewer /root/dense_causal_audit", "critical": 0, "warning": 0, "note": 0, "study": "NQ_dense_1s_2016_2026", "audited_execution_composite_sha256": "23e6bed15694b680a6d3a80a193a5af1f1f9e755a201546c19a1ab4560f3627d"}
<!-- AUDIT_SUMMARY_V2_END -->

# Look-Ahead & Timestamp Audit — Pass 01

**Date:** 2026-08-20T11:33:04.7530585Z
**Scope:** Frozen surface in `data/canonical/audit/audit_packet.json`: `scripts/build_dense_1s.py`, `scripts/tests/test_build_dense_1s.py`, and causal/timestamp/calendar clauses in `data/canonical/config/deliverables_contract.json`. Minimum external context: installed `pandas_market_calendars==5.4.0` schedule rows at the 2021 regime boundary; immutable raw source schema/range metadata and targeted raw rows at the old halt, new regime, and maintenance closure.
**Scope hash:** execution composite `23e6bed15694b680a6d3a80a193a5af1f1f9e755a201546c19a1ab4560f3627d` (`audit_packet.json`; all three file hashes rechecked unchanged).
**Lint:** 0 critical / 0 warning; utility preflight `CLEAR` with compile check passed and focused pytest 9 passed (`data/canonical/audit/preflight.json`).
**Verdict:** CLEAR

## Summary
- Critical: 0
- Warning: 0
- Note: 0

## Critical findings
None.

## Warnings
None.

## Notes
None.

## Referred to contract-checker
None.

## Clean checks
- **Causal carry-forward:** `scripts/build_dense_1s.py:232-255` selects only the last matched native row at or before each expected second. Missing seconds never read the next native value; the cross-window state is the last prior native row. The reopen test at `scripts/tests/test_build_dense_1s.py:61` proves the first missing post-closure second uses the pre-closure close rather than the next native price.
- **Timestamp contract:** `scripts/build_dense_1s.py:101-102,216-249` requires and preserves UTC `timestamp[ns]` open-stamped `ts_event`; it introduces no `ts_init`. This is a raw canonical file, not an NT catalog. Any later NT catalog ingestion remains responsible for close-time dispatch semantics.
- **Calendar/session ordering:** `scripts/build_dense_1s.py:106-137` consumes timezone-aware `CME_Equity` schedule opens/closes, clips the final half-open window to `last_ns + 1s`, applies the 15:15–15:30 CT break only through session date 2021-06-25, and leaves the schedule-defined 16:00–17:00 CT maintenance gap empty. Installed schedule inspection confirmed UTC shifts across DST and the break columns on both sides of the regime boundary; targeted raw inspection found 0 old-break rows, native post-change rows, and 0 maintenance rows.
- **Input ordering and schedule exclusion:** `scripts/build_dense_1s.py:157-199` fails closed on duplicate/out-of-order timestamps and on any native row encountered during a scheduled closure or outside all expected windows.
- **Checklist disposition:** A1/A3/A4, B1-B10, C1-C3, F1/F2, G3/G4, and H1-H4 are not exercised by this isolated raw-data utility. A2/A5, F3/F4, and G1/G2 were verified clean for the scoped contract.
