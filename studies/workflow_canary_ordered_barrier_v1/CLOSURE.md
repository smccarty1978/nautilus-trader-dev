# CLOSURE — workflow_canary_ordered_barrier_v1

**Status:** CLOSED · **Outcome:** WORKFLOW_CANARY_PASS · **Terminal decision:** CANARY_COMPLETE
**Closed:** 2026-08-28 · disposable / test-only · scientific_status: VALID_DIAGNOSTIC (canary mechanics only — never a research or production model)

## Purpose

30-minute canary proving the repaired research workflow executes the real normal path
end-to-end on a tiny TRAIN-only fixture, and that a compiled `ordered_barrier` target
primitive resolves to `OrderedBarrierTargetRuntime` with the collected target outputs
coming from that runtime — **population-agnostically** (checkpoint-grid, not just
episode-lifecycle) and **faithfully to the compiled `TargetContract`**
(`entry_reference: next_bar_open`, barrier ATR frozen at the decision timestamp T,
barrier horizon = the forward outcome's declared 60s).

## The framework fix this canary drove

`research_workflow/target_runtime.py`, `research_workflow/target_replay_oracle.py`,
`research_workflow/generic_collector.py` (+ `research_workflow/tests/test_ordered_barrier_entry_reference.py`).

`OrderedBarrierTargetRuntime` was only reachable from the `episode_lifecycle` population
path, because `generic_collector._track_pending` required the population candidate builder
to pre-populate a target-specific `entry_price`; the checkpoint-grid path raised
`TARGET_RUNTIME_REFERENCE_MISSING`. Now:

- **`OrderedBarrierTargetRuntime.open_pending(candidate)`** builds a runtime-owned pending
  observation from candidate-time state only (identity, T, frozen candidate-time ATR,
  barrier ATR distances, barrier horizon, session close, max gap). No `entry_price`.
- **`OrderedBarrierTargetRuntime.ingest_bar(pending, bar)`** streams the causal 1s
  execution tape and resolves `entry_reference: next_bar_open` on the first bar strictly
  after T (that bar's OPEN); `entry_ts = ts_close − 1s`; horizon deadline measured from
  `entry_ts`, not from T. The tape retains `open` so an independent replay can re-derive
  the entry.
- **`generic_collector`** routes BOTH population paths through `open_pending`; the episode
  path's `entry_price = price_at_T` line was removed. `_frozen_target_atr_at_T` normalizes
  `target_frozen_atr` / `atr_t` / `atr` so both paths freeze the barrier ATR at the same
  latest-completed-1m Wilder ATR available at T. The barrier horizon comes from the
  compiled `ordered_barriers[].horizon_seconds` (60), not `cfg.horizon_seconds` (which
  defaults to 300 when the target has no top-level horizon).
- **`target_replay_oracle.replay`** is an independent re-implementation: it derives the
  entry reference and barrier race from the compiled contract and the tape, never from a
  pre-populated field. `validate_target_parity` now also gates on `censoring_mismatches`.

Causal audit (lookahead-auditor) and contract audit (contract-checker): **CLEAR** across
passes 01–04. Two carried non-blocking notes (`max_gap_seconds=1` study-power; legacy
oracle fixture branch) and one carried framework limitation
(composite `condition_logic: "AND"` with a `flip` condition is compiled to
`primitive: ordered_barrier` but the `flip` condition is never conjoined by the collector —
also affects `clean_tradable_reversal`; immaterial here, every emitted label is a valid
ordered-barrier label).

## What ran (sealed composite `f79ecff8a466e6ae3fce130f42d3f9ab355915ea032ec8b1a5adc57eece05408`)

| Stage | Result |
|---|---|
| create → compile → fidelity → PREPARE → READINESS R1–R10 → PREFLIGHT | PASS / CLEAR |
| causal review · contract review (distinct reviewers, passes 01–04) | CLEAR / CLEAR |
| SEAL · NT SMOKE (2023-03-03) · validate_smoke · reconcile | sealed · ACCEPTED |
| AUTHORIZE (`ef937ba4…`) | train [2023], oos [2024] |
| bounded authorized TRAIN collect — 2023-03-03 RTH | 1984 candidates · 822 SUCCESS / 841 FAILURE-or-TIMEOUT / 321 CENSORED |
| target replay parity (independent oracle vs runtime, 9700 rows) | 0 disposition · 0 binary-label · 0 censoring mismatches |
| MERGE (1 partition) | 1663 resolved · dataset identity `2870c137…` |
| FIT — one fixed LightGBM, deterministic seed 42, no tuning | model_id `88fbba9568763c4122f6a8b98f096222cb8b656b9238525b4542f90ae3d2a2ce` |
| model artifact + golden fixture + `validate_golden_predictions` | `66ef5ed7…` · `8d9f1d59…` · PASS |
| TRAIN FREEZE | `7dae3f3d…` |
| study closure → `WorkflowEngine.advance()` | `terminal_state = STUDY_CLOSED`, `next_deterministic_action = null` |
| model resolvable / loadable / golden-parity AFTER closure | PASS |
| Study B (`workflow_canary_model_reuse_v1`) reuse by immutable model_id | scores reproduced, source study not reopened, no runtime code change |

OOS (2024/2025/2026) never accessed. No existing scientific study modified.

## Disposable artifacts

`studies/workflow_canary_ordered_barrier_v1/` and `studies/workflow_canary_model_reuse_v1/`
plus `studies/model_registry/88fbba95….json` and the model artifact under this study's
`artifacts/models/`. Safe to delete once the framework fix is committed — nothing
scientific depends on them. Do not delete before the registry/closure verification is no
longer needed as evidence.
