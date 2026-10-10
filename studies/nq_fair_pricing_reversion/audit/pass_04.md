# Look-Ahead & Timestamp Audit — Pass 04 (delta)

**Study** `nq_fair_pricing_reversion`
**Scope** `research_workflow/grammar/compiler.py` (`unit: recovery` in `barrier.arms`), `research_workflow/host/outcomes.py` (per-arm dispatch for mixed recovery, point, reference barrier arms with conditional ATR requirement), `studies/nq_fair_pricing_reversion/study.yaml`
**Audited composite** `dad232b5150ed7b50e230579cc7068e4ff11ff1166ddffde975b1a1a2860595e` (plan `9b9b80c640aff865546e9000a8bbed5d5b0ffc4050aece8606f9dec8a442c5cb`)
**Lint** preflight CLEAR; readiness PASS; tests 159 passed / 0 failed

## Prior findings adjudicated
| # | Finding | Status | Evidence |
|---|---|---|---|
| 1 | Pass 03 verified candidate emission window (09:31-11:00 ET), entry cutoff (11:00 ET), session cutoff (11:30 ET), and tracker causality | FIXED | Preserved byte-identically; multi-unit bracket additions run strictly under the same causal constraints |

## Checks performed
- **Mixed-Arm Outcome Dispatch (Checklist A1, B1, C1).** In `research_workflow/host/outcomes.py`, `LabelOutcomeKernel.on_bar()` dispatches each barrier arm individually according to its declared unit:
  - `unit: recovery` evaluates milestone fractions of decision displacement (`abs(p_decision - p_ref)`) without inspection of future bars or adverse stops.
  - `unit: points` evaluates fixed point distances from executable `next_bar_open` fill price.
  - `unit: reference` evaluates anchor target `p_ref` and adverse stop points from executable fill price.
  - Same-bar collisions and gap censoring rules apply uniformly across all arms.
- **ATR Independence (Checklist C1).** `has_atr_arm` is derived dynamically across declared arms; when all arms use `recovery`, `points`, or `reference`, no ATR is required at decision time $T$, preventing false halts while maintaining strict causal typing.
- **Entry & Session Cutoffs (Checklist A1, C2).** `entry_cutoff` strictly rejects fills post 11:00:00 ET (`ENTRY_PAST_CUTOFF`); `session_cutoff` bounds all 6 arms to 11:30:00 ET, expiring untouched arms via `TIMEOUT`.
- **Zero Lookahead in Reference/Recovery Targets (Checklist A1).** Reference price $rth\_open$ and decision price $epoch.price$ are sampled strictly at decision epoch $T$ from completed bars.

## Notes
- NOTE: All 6 arms (`m25`, `m50`, `m75`, `m100`, `tp38_sl25`, `anchor_sl25`) resolve concurrently on causal completed-bar stream.
- NOTE: Primary arm is declared as `tp38_sl25` for legacy single-label column alignment.

## Referred to contract-checker
- Governance verification of 6-arm barrier declaration in `study.yaml` against `research_decision.yaml`.

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "causal", "auditor": "lookahead-auditor", "critical": 0, "warning": 0, "note": 2, "study": "nq_fair_pricing_reversion", "audited_execution_composite_sha256": "dad232b5150ed7b50e230579cc7068e4ff11ff1166ddffde975b1a1a2860595e"}
<!-- AUDIT_SUMMARY_V2_END -->
