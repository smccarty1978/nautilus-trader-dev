# Look-Ahead & Timestamp Audit — Pass 02 (delta)

**Study** `nq_fair_pricing_reversion`
**Scope** `features/trackers/host_bindings.py` (`FeatureHostBinding.epoch_value`: `rth_open_elapsed_seconds`, `rth_recovery_direction`), `studies/nq_fair_pricing_reversion/study.yaml` (`population.qualify`, `population.direction`)
**Audited composite** `a61ce09e86d58d242fdf4c9c00cdf9de849870dc020f5a450c6c90d6d6fc4e37` (plan `85e78bc5d6b47528e1aeec4fd4a12558a1442d5310e69a54c5b4f32336c1e385`)
**Lint** preflight CLEAR; readiness PASS; tests 159 passed / 0 failed

## Prior findings adjudicated
| # | Finding | Status | Evidence |
|---|---|---|---|
| 1 | pass_01 reported no findings and "F1-F4 clean" | NOT FIXED (process gap, see Notes) | pass_01 did not verify that candidate emission was bounded to the declared 09:31-11:00 ET window; the persisted smoke emitted 405 candidates 09:31-16:15 ET. |

## Checks performed
- **Anchor availability (A1/B1).** `rth_open` / `_rth_open_ts` are written only in `update_1m`, fed a COMPLETED 1m bar stamped with its close (`ts_avail`). The anchor is first non-None at the 09:31 epoch; before that both new fields fail closed (`elapsed` returns None, so `<= 5400` is False; direction returns 0).
- **`rth_open_elapsed_seconds`.** Pure function of `epoch.T` and the anchor timestamp: `(T - rth_open_ts)/1e9 + 60`. Uses nothing after T. T=09:31 -> 60s, T=11:00 -> 5400s, T=11:01 -> 5460s (excluded). Boundary values are asserted in `test_rth_open_eligibility_fields.py`.
- **`rth_recovery_direction`.** `-sign(epoch.price - anchor)` where `epoch.price` is the completed 1m bar close at T and the anchor is frozen for the session. No regime/EMA input. Zero displacement -> 0 -> excluded by `!= 0`.
- **Evaluation point.** `qualify` runs in `HostCore` before `_emit_candidate`, i.e. a compiled predicate on epoch-time state, not a post-collection filter. `direction` is resolved at emission and frozen into the pending outcome at T.
- **Outcome kernel unchanged.** Recovery targets still derive from `decision_price`/`reference_price` frozen at open; entry reference is `next_bar_open` strictly after T.

## Notes
- NOTE: pass_01 did not trace the population gate. Corrected here by direct reading of the compiled `population.qualify` AST.
- NOTE: the `+ 60.0` open-instant offset assumes the 1m cadence declared in this plan; it is not derived from the stream's bar duration.

## Referred to contract-checker
- Declared-identity provenance only: both pass files for this study were authored in one agent session (see contract pass 02).

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "causal", "auditor": "lookahead-auditor", "critical": 0, "warning": 0, "note": 2, "study": "nq_fair_pricing_reversion", "audited_execution_composite_sha256": "a61ce09e86d58d242fdf4c9c00cdf9de849870dc020f5a450c6c90d6d6fc4e37"}
<!-- AUDIT_SUMMARY_V2_END -->
