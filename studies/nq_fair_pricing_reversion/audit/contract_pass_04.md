---
audit_type: "contract"
study: nq_fair_pricing_reversion
auditor: contract-checker
---

# Contract & Governance Audit — nq_fair_pricing_reversion — pass 04

Composite audited: `dad232b5150ed7b50e230579cc7068e4ff11ff1166ddffde975b1a1a2860595e`

## Prior findings adjudicated
| # | Finding | Status | Evidence |
|---|---|---|---|
| 1 | Contract pass 03 verified single-kernel recovery milestones; noted requirement for simultaneous fixed-point and reference bracket arms | FIXED | Resolved via multi-unit barrier capability; 6 arms declared concurrently under `barrier.arms` |

## Compliance table
| Requirement (research_decision.yaml / SPEC.md) | Verdict | Evidence |
|---|---|---|
| Signal Decision Window: 09:31-11:00 ET inclusive | PASS | `population.qualify` AST carries `features.rth_open_elapsed_seconds <= 5400` |
| Entry Cutoff: Executable entry rejected if fill > 11:00 ET | PASS | `outcome.entry_cutoff: "11:00:00 America/New_York"` compiled into plan and enforced by outcome kernel |
| Session Cutoff: Mandatory flat at 11:30 ET | PASS | `outcome.session_cutoff: "11:30:00 America/New_York"` compiled into plan and enforced by outcome kernel |
| A0/A1/A2 Signal Architecture: Zero study Python | PASS | `tracker.candle.displacement_1m` and `tracker.structure.bos_1m` registered in platform capabilities; zero study Python |
| Outcome Recovery Arms: 4 Fractional Milestones | PASS | Arms `m25` (0.25), `m50` (0.50), `m75` (0.75), `m100` (1.00) configured with `unit: recovery` and `expiry: censor` |
| Outcome Fixed-Point Bracket Arm | PASS | Arm `tp38_sl25` configured with `unit: points`, `favorable_points: 38.0`, `adverse_points: 25.0`, `primary: tp38_sl25` |
| Outcome Reference-Price Bracket Arm | PASS | Arm `anchor_sl25` configured with `unit: reference`, `adverse_points: 25.0`, target reference `features.rth_open` |
| Non-zero displacement eligibility | PASS | `features.rth_recovery_direction != 0` in qualify predicate |
| Chronology & Partitions | PASS | TRAIN 2021-2023, DEV 2024, Prohibited 2025-2026, authorized_dates: ['2023-10-02'] |
| Preflight & Readiness | PASS | `preflight.json` CLEAR, `readiness.json` PASS, tests 159 passed / 0 failed |

## Notes
- NOTE: All 6 arms execute within a single declarative study run, eliminating post-hoc composition artifacts.
- NOTE: Bounded smoke on 2023-10-02 is authorized prior to any multi-year collection.

## Referred to lookahead-auditor
None.

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "contract", "auditor": "contract-checker", "critical": 0, "warning": 0, "note": 2, "study": "nq_fair_pricing_reversion", "audited_execution_composite_sha256": "dad232b5150ed7b50e230579cc7068e4ff11ff1166ddffde975b1a1a2860595e"}
<!-- AUDIT_SUMMARY_V2_END -->
