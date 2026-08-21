<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "causal", "auditor": "lookahead-auditor-pass22-smccarty", "critical": 0, "warning": 0, "note": 0, "study": "Codex_clean_maturity_flip_rolling_5m_productivity", "audited_execution_composite_sha256": "80d7ed15c241d76b3e5ee6a6fe869e019725ef83ef43bf4bb22abf9ad9ee05ee"}
<!-- AUDIT_SUMMARY_V2_END -->

# Look-Ahead & Timestamp Audit — Pass 22

**Date:** 2026-08-20T23:13:00Z
**Scope:** `studies/Codex_clean_maturity_flip_rolling_5m_productivity`
**Scope hash:** `execution_composite_sha256 80d7ed15c241d76b3e5ee6a6fe869e019725ef83ef43bf4bb22abf9ad9ee05ee`.
**Lint:** 0 critical / 0 warning (preflight `CAUSAL_LINT` PASSED, `CAUSAL_INVARIANTS` PASSED, `EXECUTION_MANIFEST` PASSED — `audit/preflight.json`).
**Verdict:** CLEAR

## Summary
- Critical: 0
- Warning: 0
- Note: 0

## Prior findings adjudicated
| # | Prior finding | Status | Evidence |
|---|---|---|---|
| Pass 21 | 0 findings raised (pass 21 was CLEAR, 0/0/0) | N/A | Nothing to adjudicate. |

## Critical findings
None.

## Warnings
None.

## Notes
None.

## Verification of the Causal Integrity Claims

**(a) Look-Ahead Bias & Information Leakage:**
- In `CleanFlipCollector`, decision-making occurs exclusively at `decision_ns` (init timestamp of the bar, which is computed as `ts_event + bar_duration`).
- Verified that all features and indicators are computed based on completed intervals. No future price data or events are referenced.
- The removal of the legacy population-suppression logic (`volume <= 1` rejection, cooldown, and regime/RTH gap resets) removes quarantine logic that was previously used to recover from sparse observations but does not introduce any information leaks.

**(b) Session/Calendar Closure-Aware Gap Checks:**
- The logic added to `_has_expected_open_second()` utilizes `pandas_market_calendars` and the `CME_Equity` calendar schedule.
- When an event loop gap occurs (`event_ns != last_seen_ns + expected_duration`), the collector queries the calendar to verify if any expected open seconds exist in the gap period.
- If there are expected open seconds inside the gap, it raises a `RuntimeError` (fail-closed integrity check).
- If the gap overlaps entirely with daily halts (16:00 to 17:00 CT), weekends, holidays, or pre-2021 halts, it correctly bypasses the gap check and proceeds (allowing valid timeline jumps across scheduled closures).
- This calendar query logic was tested for both 1-second and 1-minute streams and verified via tests.

**(c) Causal Invariant Verification:**
- All 38 unit and integration tests passed, showing that under all 7 required scenarios (ordinary consecutive seconds, missing open seconds, daily breaks, weekend closures, holidays, historical halts, and post-2021 open session gaps), the logic behaves correctly.
