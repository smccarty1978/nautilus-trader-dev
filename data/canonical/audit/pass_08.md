<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "causal", "auditor": "Codex reviewer /root/dense_causal_audit", "critical": 0, "warning": 0, "note": 0, "study": "NQ_dense_1s_2016_2026", "audited_execution_composite_sha256": "8234eb620c18f24875d903def642b9aeff75f7f06fa7a2daffb6b4d3b34fa13c"}
<!-- AUDIT_SUMMARY_V2_END -->

# Look-Ahead & Timestamp Audit — Pass 08

**Date:** 2026-08-20T16:04:11.1047732Z
**Scope:** Frozen surface in `data/canonical/audit/audit_packet.json`: `expected_windows` endpoint change in `scripts/build_dense_1s.py`, corresponding calendar test update in `scripts/tests/test_build_dense_1s.py`, and broadened endpoint convention in `data/canonical/config/deliverables_contract.json`. Other production paths are unchanged from pass 07.
**Scope hash:** execution composite `8234eb620c18f24875d903def642b9aeff75f7f06fa7a2daffb6b4d3b34fa13c`; all three frozen file hashes rechecked unchanged.
**Lint:** 0 critical / 0 warning; utility preflight `CLEAR`, compile check passed, focused pytest 20 passed (`data/canonical/audit/preflight.json`).
**Verdict:** CLEAR

## Summary
- Critical: 0
- Warning: 0
- Note: 0

## Prior findings adjudicated
| # | Prior finding | Status | Evidence |
|---|---|---|---|
| Pass 07 | No findings (CLEAR, 0 critical / 0 warning / 0 note) | N/A | No finding requires remediation. Closure exceptions, causal carry, coverage, chronology, and publication logic are unchanged; only declared market-close endpoint membership changed. |

## Critical findings
None.

## Warnings
None.

## Notes
None.

## Referred to contract-checker
- `scripts/build_dense_1s.py:611` manifest wording still names 16:00:00/pre-regime 15:15:00 only and omits the newly frozen early-close endpoint convention.

## Clean checks
- **Exact declared-close inclusion:** every timezone-aware calendar `market_close` remains represented internally as a half-open window end plus exactly one second (`scripts/build_dense_1s.py:107-142`). This includes one row at normal and holiday/special close timestamps; the next second is outside the window, so no closure interval is densified.
- **Native precedence:** the raw Thanksgiving close timestamp that previously remained before the next expected window is now consumed by its own session window. `NativeStream` copies it once, `densify_window` marks it `is_fill=false`, and native parity remains blocking. No future reopen value participates.
- **Missing endpoint causality:** if a declared close boundary lacks a native row, it is an expected second and receives only the last prior canonical close. The unchanged source-index accumulation cannot select a later native row.
- **Calendar/exception interaction:** a native row at a declared early close is now inside the ordinary calendar window, so `add_native_exception_windows` does not add a duplicate singleton. Closure-interior exception rules remain unchanged and sorted.
- **YTD/session safety:** `cap_exclusive = last_native_ns + 1s` clips the extended endpoint when the available source ends earlier (`scripts/build_dense_1s.py:119,137-138`). The Thanksgiving test now asserts both the last pre-close second and exact early-close boundary (`scripts/tests/test_build_dense_1s.py:101-107`); named-zone DST and historical 15:15 rules are unchanged.
- **Checklist disposition:** A1/A3/A4, B1-B10, C1-C3, F1/F2, G3/G4, and H1-H4 are not exercised by this isolated raw-data utility. A2/A5, F3/F4, and G1/G2 were verified clean for declared-close endpoint expansion.
