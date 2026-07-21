# Fifth Pre-Execution Lookahead and Causality Audit

**Status:** **PASS**

**Findings:** **0 CRITICAL, 0 WARNING**

## Scope

Read-only fifth pre-execution audit of the current `run_study.py`, `config.json`, frozen repaired W4 score/trade artifacts, raw 1-second inputs, repaired upstream contracts, and audited confirmation-clock outcome artifacts. The study itself was not executed and no result artifacts were written.

## Full-chain verification

The complete computation chain was exercised read-only through report construction:

- 4,383 unique frozen trades loaded: 3,246 from 2025 and 1,137 from 2026.
- 214,767 score-grid rows constructed: exactly 49 trigger-relative checkpoints for every trade.
- 4,383 morphology-feature rows and 4,383 price-feature rows reconciled one-to-one.
- 12 group summary rows, 132 group-path rows, 105 gate rows, and 120 compact comparison rows constructed without runtime errors.
- Every overall gate's retained + removed + unevaluable counts reconciled to 4,383.
- Report construction and decision-label generation completed.

## Causality and timestamp findings

- Score offset zero exactly equals the stored causal decision timestamp and frozen entry W4 score.
- Every score observation lies on the exact five-second trigger-relative grid.
- Frozen score availability exactly equals the union of the two declared censoring contracts for every grid cell:
  - flip censor begins at `checkpoint_ts >= confirm_flip_ns`;
  - administrative censor begins at `checkpoint_ts > regime_start_ns + 1,800 seconds`, preserving the atlas checkpoint at exactly 1,800 seconds.
- Counts reconcile to 23,657 flip-censored cells, 3,048 administratively censored cells, with 1,131 overlapping both causes. No score exists in a censored cell and no at-risk cell lacks a score.
- Successor-regime scores are never substituted for the entry-regime score. At-risk path summaries publish score-at-risk, flip-censor, and administrative-censor counts at every reported offset.
- Raw price checkpoints use only completed one-second bars with timestamps strictly before each boundary. Directional PnL uses the completed bar close; MFE/MAE use only the same bounded high/low slice and the frozen entry-fill open.
- Retrospective baseline and Policy A outcome memberships are used only as analysis labels and are not represented as causal entry features or executable policy results.

## Feature and gate verification

- The full uniform five-second path supports the declared pre-60/pre-120 dwell, extrema, crossing, persistence, and collapse calculations.
- First-60-second exposure uses the twelve left-edge intervals in `[0, 60)`, so at-risk and above-threshold durations are correctly bounded at 60 seconds.
- Collapse is nullable when censoring prevents a resolved conclusion. Group summaries publish observable and unresolved denominators plus both censor-cause counts; the report prints the observable denominators for the primary comparison.
- `trade_direction` is derived only after validating frozen `entry_direction` is exactly ±1. Every +1 maps to `long_fade`, every -1 maps to `short_fade`, matching the upstream confirmation-clock convention.
- Score gates are tri-state: at-risk observations evaluate retained/removed, a regime ending by the checkpoint is removed, and active-regime administrative unavailability is unevaluable. The three statuses are mutually exclusive and exhaustive.
- Price gates use completed-bar checkpoint marks. Gate tables are explicitly descriptive original-entry/original-PnL selection diagnostics and do not claim delayed-entry performance.
- Persistence and collapse do not drive the final decision label. The only possible nomination is the fixed descriptive price-response condition, and the report requires a separate causal delayed-entry replay before any policy claim.

## Reproducibility and authorization

The runner fails closed unless this exact clean audit and its bound authorization match the current runner/config/audit hashes. Frozen upstream inputs and generated outputs are hash-inventoried by the run manifest. The current scope is authorized for its first execution.
