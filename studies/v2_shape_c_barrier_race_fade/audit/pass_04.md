# Look-Ahead & Timestamp Audit — Pass 04 (delta)

**Date** 2026-09-02 · **Scope** `research_workflow/host/outcomes.py` (`first_bar_at_or_after` branch, hash changed),
`research_workflow/target_replay_oracle.py` (mirrored fix, hash changed)
**Scope hash (audited composite)** `51bc1054629d2a65b8e00489778bf7143cc00af1c6348f4ccb3e6399230420ce`
**Lint** preflight CLEAR; readiness overall PASS · **Verdict** CLEAR

## Summary
Critical: 0 · Warning: 0 · Note: 1

## Prior findings adjudicated
| # | Finding | Status | Evidence |
|---|---|---|---|
| 1 | [pass_03 Note] `first_bar_at_or_after` bypasses `SESSION_END`/`GAP` precedence for the one extra evaluated bar | **PARTIALLY FIXED — session-close sub-case closed, gap sub-case still open** | `outcomes.py:326-331`: the `past_end` branch now checks `if p.session_close is not None and ts > p.session_close: self._expire_arm(p, i); continue` **before** evaluating `hi/lo` for a touch — a bar closing after the arm's session close now expires (TIMEOUT/per-expiry-policy) rather than being scored as a fill. This directly closes the early-close/overnight-reopen failure mode described (4 arms previously resolving ~18,000s later on a 17:00 CT reopen bar). Traced `target_replay_oracle.py:120` (`if end_rule != "first_bar_at_or_after" or (session_close_ts is not None and ts > session_close_ts): ...`) — the independent oracle mirrors the same session-close guard. The `gap` check (`self.c.max_gap_ns`) is still not consulted inside this branch — unchanged from pass_03, so a genuine tape gap spanning into the one extra evaluated bar would still be scored as a touch/expiry rather than `GAP`. Narrower now (session-close case closed), still a disclosure-only NOTE, not blocking. |

No CRITICAL or WARNING findings existed in pass_03 to adjudicate.

## Checks performed (delta-scoped)
- **Causality unaffected.** The fix only changes which *disposition* is assigned to the extra bar already being evaluated (TIMEOUT/expire vs. a scored touch) — it reads no new data, nothing earlier than what `on_bar` already receives in causal order, and touches no candidate/feature column. Consistent with pass_03's conclusion that this whole mechanism is label-window construction only (C1).
- `p.session_close` used for the new guard is the same value computed once at `open()` from `session_table.session_close(T)` (`outcomes.py:236`) — unchanged, already-audited causal input; no new dependency introduced.
- `_expire_arm` resolves at `p.arm_end[i]` (the horizon-end timestamp fixed at entry), not at the disqualified bar's `ts` — consistent with existing `TIMEOUT`/expiry-policy semantics elsewhere in the kernel.
- Test `research_workflow/tests/test_host_core.py::test_first_bar_at_or_after_never_crosses_the_session_close` (referenced by the coordinator) exercises exactly this boundary; not independently re-run here, taken as declared per the shared audit protocol's trust of the study's own bounded-fixture test suite.

## Notes
- (narrowed, carried forward) `first_bar_at_or_after` still does not check `max_gap_ns` for the one extra evaluated bar — a tape gap crossing that bar would be scored as a touch/expiry rather than `GAP`. Disclosure only; smallest fix would mirror the session-close guard's placement for the gap check.

## Referred to contract-checker
- (carried forward, unaffected) Frozen-model reuse governance / target-authority `21d598a8...` provenance.

## Clean checks
A1-A5, B1-B7, B9, B10, C1-C3, F1, F3-F4, G1, G3-G4, H1-H4 clean. F2 (session boundary precedence) now clean for the session-close case; gap-check note above is the only residual.

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "causal", "study": "v2_shape_c_barrier_race_fade", "auditor": "lookahead-auditor", "audited_execution_composite_sha256": "51bc1054629d2a65b8e00489778bf7143cc00af1c6348f4ccb3e6399230420ce", "critical": 0, "warning": 0, "note": 1}
<!-- AUDIT_SUMMARY_V2_END -->
