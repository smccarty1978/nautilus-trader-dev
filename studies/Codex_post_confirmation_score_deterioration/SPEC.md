# Post-Confirmation Score Deterioration / Runner Protection — Frozen Specification

**Study:** `Codex_post_confirmation_score_deterioration`  
**Frozen:** 2026-08-10, before execution  
**Substrate:** `data/canonical/regime_complete_v1/` (accepted NT-produced canonical store)  
**Predecessor:** `studies/armed_fade_score_path_progression/`

## Decision

Determine whether the score of the *newly confirmed regime* is available soon
enough to supply causal post-confirmation trade-management information. This is
a feasibility-first diagnostic, not an entry-selection or exit-policy
optimization.

## Frozen population and semantics

The population is every valid Top-10 armed regime from the predecessor's
`armed_regime_score_paths.parquet` that reached a canonical full continuation
terminal. The canonical terminal labels are preserved unchanged:

- `CONFIRMED_THEN_STOPPED`
- `FINAL_FLIP_EXIT_LOSER`
- `FINAL_FLIP_EXIT_WINNER`
- `SESSION_EXIT`

`STOPPED_BEFORE_CONFIRM` remains in the denominator reconciliation but is not a
post-confirmation trade.

For a confirmed fade trade, the score stream is the non-null **in-domain score
of the newly confirmed regime**, at its actual dispatch timestamp. It is the
opposing-model warning score: a *rising* score predicts a flip against the open
trade. It is not a supporting-continuation score, and a falling score must not
be called deterioration for this position. An out-of-domain score is excluded;
substituting it would change the frozen model-domain contract.

The path begins no earlier than `walk_a_confirm_ns` and ends no later than the
predecessor's canonical `full_exit_ns`, both inclusively. No observation is
synthesized at a missing dispatch. Features would require at least three actual
observations; that threshold is a minimal path-definition requirement, not a
tuned signal.

## Gate 1 — observability

Before building deterioration, retreat/recovery, divergence, runner-touch, or
policy diagnostics, reconcile the population and measure valid score-stream
coverage overall, by terminal label, direction, and arm-entry year.

Gate 1 passes only if the failure population has enough valid post-confirmation
coverage for a representative causal path analysis: at least 50% of failed
trades must have three true in-domain observations before terminal exit. This
is a feasibility floor, not an efficacy threshold. If Gate 1 fails, no event is
constructed from target labels, no score fallback is introduced, and no policy
simulation is allowed. Required later artifacts record `NOT_EVALUABLE` with
the blocking coverage evidence.

## Invariants

1. Population labels are read only after the path/coverage window is fixed and
   are targets, never predictors.
2. Every score timestamp is within the inclusive confirmation-to-terminal
   interval; paths are strictly monotonic and duplicate regime/timestamp pairs
   are forbidden.
3. The new regime is joined only when its canonical start timestamp and
   direction equal the confirmation timestamp and trade direction.
4. Session is RTH; 2026 is excluded. 2025 overlaps threshold calibration and
   is explicitly not threshold-OOS.
5. No costs, fill assumptions, ATR definitions, confirmation rules, or terminal
   labels are redefined here. No policy is simulated when Gate 1 fails.

## Deliverables manifest

`README.md`, `REPORT.md`, `config/run.yaml`, and these machine-readable results
are required: `population_reconciliation.json`,
`post_confirmation_score_path_summary.json`, `deterioration_event_table.json`,
`retreat_recovery_analysis.json`, `price_score_divergence.json`,
`runner_touch_analysis.json`, `year_direction_stability.json`, and
`validation_report.json`. `audit/status.json` and
`audit/contract_status.json` are required before a result is called clean.

## Terminal labels

Exactly one of the handoff labels must be emitted. This frozen contract assigns
**A — POST-CONFIRMATION SCORE HAS NO USEFUL MANAGEMENT INFORMATION** if Gate 1
fails because valid-score coverage does not represent the failure population.
It assigns no other label unless Gate 1 passes and the specified subsequent
analysis is run.
