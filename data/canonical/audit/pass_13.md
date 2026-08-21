<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "BLOCKED", "audit_type": "causal", "auditor": "Codex reviewer /root/dense_causal_audit", "critical": 1, "warning": 0, "note": 0, "study": "NQ_dense_1s_2016_2026", "audited_execution_composite_sha256": "f3ea7799ca403e220809c2724162a44b0a5c58cc4e9c3fe2feaf103904a73d75"}
<!-- AUDIT_SUMMARY_V2_END -->

# Look-Ahead & Timestamp Audit — Pass 13

**Date:** 2026-08-20T16:19:20.1394959Z
**Scope:** Frozen surface in `data/canonical/audit/audit_packet.json`: unchanged causal implementation/tests in `scripts/build_dense_1s.py` and `scripts/tests/test_build_dense_1s.py`, plus the refrozen exception policy in `data/canonical/config/deliverables_contract.json`.
**Scope hash:** execution composite `f3ea7799ca403e220809c2724162a44b0a5c58cc4e9c3fe2feaf103904a73d75`; all three frozen file hashes rechecked by deterministic preflight.
**Lint:** 0 critical / 0 warning; utility preflight `CLEAR`, compile check passed, focused pytest 23 passed (`data/canonical/audit/preflight.json`).
**Verdict:** BLOCKED

## Summary
- Critical: 1
- Warning: 0
- Note: 0

## Prior findings adjudicated
| # | Prior finding | Status | Evidence |
|---|---|---|---|
| Pass 11 [F3/G2], retained in pass 12 | Clock-time masks whitelist weekend/holiday closure rows as approved maintenance/halt exceptions. | **NOT FIXED** | Builder and tests are byte-identical to pass 12. The refrozen policy now explicitly says weekend/full-holiday rows are never whitelisted (`data/canonical/config/deliverables_contract.json:21`), but `interior_mask` still classifies any 16:xx CT timestamp without a valid session-day check (`scripts/build_dense_1s.py:193-208`) and removes it before the early-close-date filter (`scripts/build_dense_1s.py:223-239`). The exact Saturday `2023-06-17T21:15:01Z` and Christmas `2023-12-25T22:15:01Z` diagnostics therefore still return `boundary_validation=PASS`. |

## Critical findings

No new critical finding. Pass 11 [F3/G2] remains active and blocking. The smallest fix remains to qualify every 15:15–15:30 and 16:00–17:00 exception against a valid scheduled session/day before adding its singleton window; weekend/full-holiday timestamps must remain blocking regardless of local clock time.

## Warnings
None.

## Notes
None.

## Referred to contract-checker
None.

## Clean checks
- The refrozen distinction between declared maintenance/halt exceptions, early-close tails, and weekend/full-holiday closures is causally unambiguous; the implementation does not yet enforce the weekend/full-holiday exclusion for the clock-time path.
- Calendar close endpoints, old-regime endpoint inclusion, causal prior-close selection, native parity, chronology, YTD clipping, and publication validation are unchanged from pass 12.
- A1/A3/A4, B1-B10, C1-C3, F1/F2, G3/G4, and H1-H4 remain non-applicable. A2/A5 and F4 remain clean; F3/G2 remain blocked.
