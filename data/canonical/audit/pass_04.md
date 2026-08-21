<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "causal", "auditor": "Codex reviewer /root/dense_causal_audit", "critical": 0, "warning": 0, "note": 0, "study": "NQ_dense_1s_2016_2026", "audited_execution_composite_sha256": "299c03a546a8ac6a21270b6bc0f730def2634f83de0e3aa24dbd0b0ca1f8ea07"}
<!-- AUDIT_SUMMARY_V2_END -->

# Look-Ahead & Timestamp Audit — Pass 04

**Date:** 2026-08-20T15:49:48.6551178Z
**Scope:** Frozen surface in `data/canonical/audit/audit_packet.json`: changed `scripts/build_dense_1s.py`, changed `scripts/tests/test_build_dense_1s.py`, and endpoint/boundary-report update in `data/canonical/config/deliverables_contract.json`. Review concentrated on exact session-close and pre-regime 15:15:00 CT endpoint inclusion, full-source boundary scanning, and the added 2021 smoke date.
**Scope hash:** execution composite `299c03a546a8ac6a21270b6bc0f730def2634f83de0e3aa24dbd0b0ca1f8ea07`; all three frozen file hashes rechecked unchanged.
**Lint:** 0 critical / 0 warning; utility preflight `CLEAR`, compile check passed, focused pytest 19 passed (`data/canonical/audit/preflight.json`).
**Verdict:** CLEAR

## Summary
- Critical: 0
- Warning: 0
- Note: 0

## Prior findings adjudicated
| # | Prior finding | Status | Evidence |
|---|---|---|---|
| Pass 03 | No findings (CLEAR, 0 critical / 0 warning / 0 note) | N/A | No finding requires remediation. Coverage merge, fill state, fallback restart, publication validation, and UTC/YTD logic remain clean; only the explicitly approved endpoint convention and its evidence path changed. |

## Critical findings
None.

## Warnings
None.

## Notes
None.

## Referred to contract-checker
None.

## Clean checks
- **Inclusive endpoint construction:** `expected_windows` retains half-open internal representation but adds exactly one second to each calendar `market_close`, and to the old-regime `break_start` end only (`scripts/build_dense_1s.py:106-140`). Thus 16:00:00 CT/session-close and old-regime 15:15:00 CT occur once; 16:00:01–16:59:59 and 15:15:01–15:29:59 remain outside all windows. The named-zone calendar still supplies DST, holiday, and special-session boundaries.
- **No future-price path:** `NativeStream.read_window` uses the exclusive adjusted end when slicing native rows (`scripts/build_dense_1s.py:222-242`), and `densify_window` still derives a missing endpoint only from the maximum matched native position at or before that second (`scripts/build_dense_1s.py:250-299`). A later reopen/native price is never used for the endpoint or for a missing reopen second.
- **Boundary scan:** `validate_native_boundaries` converts UTC nanoseconds explicitly and uses `America/Chicago` before classifying exact endpoints versus closure interiors (`scripts/build_dense_1s.py:143-179`). It can only block publication; its counts never enter OHLC, timestamps, calendar windows, or carry state. Exact 16:00:00/17:00:00 handling and interior rejection are covered at `scripts/tests/test_build_dense_1s.py:127-133`.
- **Regime/YTD consistency:** old-regime 15:15:00 inclusion and post-regime continuous trading are asserted at `scripts/tests/test_build_dense_1s.py:72-81`; calendar early-close and DST cases remain covered at `scripts/tests/test_build_dense_1s.py:101-107`. `cap_exclusive = last_native_ns + 1s` still prevents endpoint expansion past the final 2026/YTD native timestamp (`scripts/build_dense_1s.py:118,135-136`).
- **Raw precedence and integrity:** the boundary precheck rejects any native timestamp inside declared closure interiors before candidate construction (`scripts/build_dense_1s.py:519-531`); candidate coverage, native parity, fill-price validity, order, and overrun checks remain blocking before publication.
- **Checklist disposition:** A1/A3/A4, B1-B10, C1-C3, F1/F2, G3/G4, and H1-H4 are not exercised by this isolated raw-data utility. A2/A5, F3/F4, and G1/G2 were verified clean for the endpoint override.
