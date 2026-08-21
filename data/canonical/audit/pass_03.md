<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "causal", "auditor": "Codex reviewer /root/dense_causal_audit", "critical": 0, "warning": 0, "note": 0, "study": "NQ_dense_1s_2016_2026", "audited_execution_composite_sha256": "47621eed1183c6394d02ad30e7f2c04e5a8561fafdcc8c1880ea30b47c39c9c8"}
<!-- AUDIT_SUMMARY_V2_END -->

# Look-Ahead & Timestamp Audit — Pass 03

**Date:** 2026-08-20T11:46:25.0625859Z
**Scope:** Frozen surface in `data/canonical/audit/audit_packet.json`: changed `scripts/build_dense_1s.py`, changed `scripts/tests/test_build_dense_1s.py`, and unchanged causal/timestamp/calendar clauses in `data/canonical/config/deliverables_contract.json`. Review concentrated on coverage merge counting, partition hashing/reason metadata, and manifest-before-output publication.
**Scope hash:** execution composite `47621eed1183c6394d02ad30e7f2c04e5a8561fafdcc8c1880ea30b47c39c9c8`; all three frozen file hashes rechecked unchanged.
**Lint:** 0 critical / 0 warning; utility preflight `CLEAR`, compile check passed, focused pytest 18 passed (`data/canonical/audit/preflight.json`).
**Verdict:** CLEAR

## Summary
- Critical: 0
- Warning: 0
- Note: 0

## Prior findings adjudicated
| # | Prior finding | Status | Evidence |
|---|---|---|---|
| Pass 02 | No findings (CLEAR, 0 critical / 0 warning / 0 note) | N/A | No finding requires remediation. The prior-clean fill state, fallback restart, UTC timestamp, and historical calendar paths remain semantically unchanged. |

## Critical findings
None.

## Warnings
None.

## Notes
None.

## Referred to contract-checker
- `scripts/build_dense_1s.py:550-554` writes the success manifest before `os.replace`; the completion review should adjudicate the crash state in which manifest publication succeeds but final output publication fails.

## Clean checks
- **Coverage merge:** `_validate_expected_coverage` compares the current expected and actual UTC seconds and advances only the smaller timestamp on a defect (`scripts/build_dense_1s.py:292-338`). An absent expected second increments only `missing_expected_open_seconds`; an extra actual second increments only `rows_during_scheduled_closures`. Exact matches advance both. No future value is used to synthesize, classify, or repair a past row, and any nonzero count blocks publication (`scripts/build_dense_1s.py:508-518`).
- **Chronology/YTD:** native parity, fill-price causality, duplicate/order checks, exact calendar coverage, and the inclusive final-native boundary are still evaluated on the unpublished candidate (`scripts/build_dense_1s.py:348-389,503-518`). The added independent missing/extra tests exercise both merge directions (`scripts/tests/test_build_dense_1s.py:138-148`).
- **Partition metadata:** `_parquet_details` hashes sorted partition path/hash pairs (`scripts/build_dense_1s.py:453-467`). This observes already-written candidate bytes and never feeds the fill state, calendar windows, timestamps, prices, or validation ordering. `fallback_reason` is likewise descriptive only (`scripts/build_dense_1s.py:490-502,520-526`).
- **Publication boundary:** the candidate is fully materialized and validated before either the manifest or final output is published (`scripts/build_dense_1s.py:503-554`). Reordering these two final artifact operations does not change any canonical row or permit an invalid candidate to occupy the final data path.
- **Historical sessions/timestamps:** UTC open-stamped `ts_event`, named-zone calendar construction, pre/post-2021 halt regimes, schedule-defined maintenance gap, and causal reopen behavior are unchanged from passes 01-02.
- **Checklist disposition:** A1/A3/A4, B1-B10, C1-C3, F1/F2, G3/G4, and H1-H4 are not exercised by this isolated raw-data utility. A2/A5, F3/F4, and G1/G2 were verified clean for the changed surface.
