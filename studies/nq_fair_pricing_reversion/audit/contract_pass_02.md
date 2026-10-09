---
audit_type: "contract"
study: nq_fair_pricing_reversion
auditor: contract-checker
---

# Contract & Governance Audit — nq_fair_pricing_reversion — pass 02

Composite audited: `a61ce09e86d58d242fdf4c9c00cdf9de849870dc020f5a450c6c90d6d6fc4e37`

## Prior findings adjudicated
| # | Finding | Status | Evidence |
|---|---|---|---|
| 1 | contract pass_01 CLEAR while executed population violated `research_decision.yaml` (candidates 09:31-16:15 ET; direction from `regime_1m.dir`) | NOT FIXED in pass_01, FIXED in this composite | `study.yaml` now declares `qualify` + `direction: features.rth_recovery_direction`; compiled plan carries both |

## Compliance table
| Requirement (research_decision.yaml) | Verdict | Evidence |
|---|---|---|
| Window 09:31-11:00 ET inclusive, no emission after 11:00 | PASS (declared + compiled) | compiled `population.qualify` AST: `features.rth_open_elapsed_seconds <= 5400`; runtime proof is the repeated smoke |
| Zero displacement ineligible | PASS (declared + compiled) | `features.rth_recovery_direction != 0` in the compiled AST |
| Recovery direction = -sign(close_T - anchor_T); regime is context only | PASS | `population.direction = features.rth_recovery_direction`; `regime_1m.dir` no longer referenced as direction |
| Forward tracking continues past 11:00 to RTH close / horizon | PASS | `outcome.horizon: 5400s` per arm, `session_end: truncate`, consistent with `forward_observation_end` |
| Milestones independent, SESSION_END never a failure | PASS | arms m25/m50/m75/m100, `expiry: censor` |
| Preflight / readiness / tests bound to composite | PASS | preflight CLEAR, readiness PASS, 159 passed |
| Chronology | PASS | train 2021-2023, dev 2024, prohibited 2025-2026, authorized_dates 2023-10-02 |
| Zero study Python | PASS | `ZERO_STUDY_PYTHON` PASSED |

## Notes
- NOTE: reporting strata (20/40/60/80 points; 1.0/1.5/2.0 ATR) are descriptive and are not gates here. The points distance is in `distance_to_level`; no ATR-normalised column is emitted yet.
- NOTE: independence limitation. Causal pass 02 and this report were authored by the same agent session under declared role names; provenance is `DECLARED_IDENTITY_ONLY`, not session-bound. A genuinely independent re-review is recommended before any multi-year collection.

## Referred to lookahead-auditor
None.

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "contract", "auditor": "contract-checker", "critical": 0, "warning": 0, "note": 2, "study": "nq_fair_pricing_reversion", "audited_execution_composite_sha256": "a61ce09e86d58d242fdf4c9c00cdf9de849870dc020f5a450c6c90d6d6fc4e37"}
<!-- AUDIT_SUMMARY_V2_END -->
