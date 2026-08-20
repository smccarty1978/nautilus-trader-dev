<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "causal", "auditor": "Codex reviewer /root/dense_causal_audit", "critical": 0, "warning": 0, "note": 0, "study": "NQ_dense_1s_2016_2026", "audited_execution_composite_sha256": "f367df219d206e38c60a1879457c13391838936ffcf6822cdcc957dbb43ed8ad"}
<!-- AUDIT_SUMMARY_V2_END -->

# Look-Ahead & Timestamp Audit — Pass 02

**Date:** 2026-08-20T11:41:47.4751671Z
**Scope:** Frozen surface in `data/canonical/audit/audit_packet.json`: changed `scripts/build_dense_1s.py`, changed `scripts/tests/test_build_dense_1s.py`, and unchanged causal/timestamp/calendar clauses in `data/canonical/config/deliverables_contract.json`. Full changed files were used because the untracked-file packet contains hashes but no contextual diff.
**Scope hash:** execution composite `f367df219d206e38c60a1879457c13391838936ffcf6822cdcc957dbb43ed8ad`; all three frozen file hashes rechecked unchanged.
**Lint:** 0 critical / 0 warning; utility preflight `CLEAR`, compile check passed, focused pytest 14 passed (`data/canonical/audit/preflight.json`).
**Verdict:** CLEAR

## Summary
- Critical: 0
- Warning: 0
- Note: 0

## Prior findings adjudicated
| # | Prior finding | Status | Evidence |
|---|---|---|---|
| Pass 01 | No findings (CLEAR, 0 critical / 0 warning / 0 note) | N/A | No finding requires remediation. The previously clean `expected_windows`, `NativeStream`, and `densify_window` causal paths remain semantically unchanged; the new composite changes publication, fallback, and validation evidence around them. |

## Critical findings
None.

## Warnings
None.

## Notes
None.

## Referred to contract-checker
- `data/canonical/audit/audit_packet.json` freezes the pass-02 surface hashes but omits the required contextual diff; full changed files were reviewed because they remain untracked.

## Clean checks
- **Retry causality:** `_write_candidate` creates a new `NativeStream` and empty prior-close state on every call (`scripts/build_dense_1s.py:416-422`). If the single-file attempt raises a writer/filesystem error, the partitioned fallback restarts from the first immutable native row (`scripts/build_dense_1s.py:485-494`); no partially advanced state or future value is reused.
- **Publication ordering:** native parity, fill-price validity, calendar coverage, chronology, and YTD limit are computed on the unpublished candidate (`scripts/build_dense_1s.py:495-510`). Publication occurs only after all are clean (`scripts/build_dense_1s.py:538-543`), so the fallback/publication changes do not alter causal row construction.
- **YTD/calendar evidence:** coverage compares the candidate positionally to every half-open expected schedule window and makes both missing and non-calendar substitutions blocking (`scripts/build_dense_1s.py:292-341`). `ytd_overrun_rows` counts timestamps strictly later than the last native open timestamp (`scripts/build_dense_1s.py:347-388`), consistent with the inclusive final native second.
- **Historical sessions/timestamps:** new deterministic cases cover weekend closure, Sunday reopen, Christmas/New Year closure, Thanksgiving early close, and DST reopen (`scripts/tests/test_build_dense_1s.py:100-108`). UTC open-stamped `ts_event`, the pre/post-2021 break regime, the schedule-defined maintenance gap, and causal reopen fill behavior remain unchanged from pass 01.
- **Checklist disposition:** A1/A3/A4, B1-B10, C1-C3, F1/F2, G3/G4, and H1-H4 are not exercised by this isolated raw-data utility. A2/A5, F3/F4, and G1/G2 were verified clean for the changed surface.
