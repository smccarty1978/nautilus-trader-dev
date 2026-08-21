<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "BLOCKED", "audit_type": "causal", "auditor": "Codex reviewer /root/dense_causal_audit", "critical": 1, "warning": 0, "note": 0, "study": "NQ_dense_1s_2016_2026", "audited_execution_composite_sha256": "fdf1ceca11d110d287ffc4c18600d1f5a7f99a394c2c6a619dfd4278c2e770be"}
<!-- AUDIT_SUMMARY_V2_END -->

# Look-Ahead & Timestamp Audit — Pass 11

**Date:** 2026-08-20T16:14:27.4195735Z
**Scope:** Frozen surface in `data/canonical/audit/audit_packet.json`: changed native-boundary/calendar validation in `scripts/build_dense_1s.py` and corresponding change in `scripts/tests/test_build_dense_1s.py`; `data/canonical/config/deliverables_contract.json` unchanged. Full changed functions were inspected because the untracked-file packet contains no contextual diff.
**Scope hash:** execution composite `fdf1ceca11d110d287ffc4c18600d1f5a7f99a394c2c6a619dfd4278c2e770be`; all three frozen file hashes rechecked unchanged.
**Lint:** 0 critical / 0 warning; utility preflight `CLEAR`, compile check passed, focused pytest 21 passed (`data/canonical/audit/preflight.json`).
**Verdict:** BLOCKED

## Summary
- Critical: 1
- Warning: 0
- Note: 0

## Prior findings adjudicated
| # | Prior finding | Status | Evidence |
|---|---|---|---|
| Pass 10 | No findings (CLEAR, 0 critical / 0 warning / 0 note) | N/A | No prior finding requires remediation. The new generic-calendar classification changed an area not present in pass 10. |

## Critical findings

### [F3/G2] `scripts/build_dense_1s.py:188-202` — clock-time masks whitelist weekend/holiday closure rows as approved maintenance/halt exceptions

**Failure path:** Give the validator one isolated raw row at Saturday 2023-06-17 16:15:01 CT (`2023-06-17T21:15:01Z`). There are no base calendar windows, but `interior_mask` is true solely because the clock hour is 16. The code records `outside_base_calendar_rows=1` and one `interior_timestamp`, then subtracts the latter from the former: `generic_closure_rows=0`. With one non-contiguous row under the 100-row limit, `boundary_validation` becomes `PASS`. `add_native_exception_windows` then adds `[t,t+1s)`, the candidate preserves the weekend native row, and coverage treats it as expected rather than reporting a closure row. Minimal diagnostic execution confirmed exactly: `PASS`, one exception, zero generic rows, empty base windows, and one augmented singleton. The same path applies to isolated 16:xx rows after a holiday early close and pre-2021 15:15-interior rows on non-session days.

**Smallest fix:** derive the maintenance/halt exception mask from explicit schedule intervals for the corresponding valid session day (or an exact frozen allowlist of the six approved timestamps), and subtract only timestamps proven to be inside an authorized exception interval; all other outside-base timestamps must remain generic blocking rows.

## Warnings
None.

## Notes
None.

## Referred to contract-checker
None.

## Clean checks
- Base-window membership uses ordered starts with half-open end comparison correctly (`scripts/build_dense_1s.py:150-152,191-194`); the defect is the unconditional clock-time subtraction afterward.
- Calendar close endpoints, old-regime endpoint inclusion, causal prior-close selection, native parity, chronology, YTD clipping, and publication validation remain unchanged from pass 10.
- A1/A3/A4, B1-B10, C1-C3, F1/F2, G3/G4, and H1-H4 remain non-applicable. A2/A5 and F4 remain clean; F3/G2 are blocked by the finding above.
