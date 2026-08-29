# CLOSURE — workflow_canary_ordered_barrier_v1

**Status:** CLOSED · **Outcome:** WORKFLOW_CANARY_PASS · **Terminal decision:** CANARY_COMPLETE
**Closed:** 2026-08-29 · disposable / test-only · scientific_status: VALID_DIAGNOSTIC (canary mechanics only — never a research or production model)

## Purpose

Bounded workflow canary proving the repaired research workflow executes the real normal
path end-to-end on a tiny TRAIN-only fixture, and that a **composite** `target_contract`
(`condition_logic: AND` over a `flip` condition and an `ordered_barrier` condition) is
executed as the **full compiled Boolean expression** — every child conjoined per
`condition_logic`, monotone `worst_status` censoring, **no Boolean short-circuit** — with
the collected target outputs coming from that runtime, and an independent replay oracle
agreeing row-for-row.

## The framework fix this canary drove

`research_workflow/target_expression.py` *(new)*, `research_workflow/target_runtime.py`,
`research_workflow/target_replay_oracle.py`, `research_workflow/generic_collector.py`,
`research_workflow/runtime_bindings.py`, `research/engines/target_engine.py`,
`backtests/nt_runtime/modes/collect.py` (+ tests
`research_workflow/tests/test_composite_target_expression.py`,
`test_single_primitive_ordered_barrier_regression.py`).

Before this fix, a `composite` target compiled to `primitive: "ordered_barrier"` and the
collector emitted **only** the ordered-barrier race — the `flip_within_60s` child was
silently dropped, and the replay oracle shared the omission so parity falsely passed
(`artifacts/target_replay_parity.json`, now marked **HISTORICAL_FALSE_PASS /
NON_AUTHORITATIVE_FOR_COMPOSITE_TARGET_PARITY**, preserved verbatim as forensic evidence).

Now:

- `compile_target_contract` compiles a target with ≥ 2 conditions to `primitive:
  "composite"` and embeds an explicit `target_expression` tree plus
  `censoring_composition: "monotone_worst_status"`.
- `research_workflow/target_expression.py::compile_target_expression` builds the executable
  `And` / `Or` tree over per-condition `PrimitiveTarget` leaves (`flip` →
  `flip_within_horizon`, `ordered_barrier` → `ordered_barrier`; `excursion` / `return`
  represented for provenance but fail closed at `resolve_target_runtime`).
- `CompositeTargetRuntime` owns one child `TargetRuntime` per condition, streams **both**
  the causal 1s execution tape (to ordered-barrier children) and the prevailing-regime
  flips (to flip children), and composes their terminal results. Composition is monotone
  `worst_status` (anchored to `research_workflow.forward_outcomes.contracts.worst_status`):
  a composite is RESOLVED only when every child is resolved; any CENSORED / AMBIGUOUS /
  unresolved child → composite CENSORED with the worst child censor reason. `AND(False,
  CENSORED) → NEGATIVE` and `OR(True, CENSORED) → POSITIVE` are **not** allowed.
- `generic_collector._resolve_composite` is the collector dispatch; it also accumulates raw
  causal inputs per emitted observation and runs the independent oracle
  (`get_composite_target_parity()`), which collect mode writes to
  `composite_target_replay_parity.json` and **fails the run** on any mismatch.
- `target_replay_oracle.replay_expression` is a deliberately separate second implementation:
  it re-parses `conditions` / `condition_logic` off the contract itself (never imports
  `compile_target_expression`), carries its own censor-severity table, and re-implements the
  monotone composition (`_compose_monotone`).
- Preflight `RUNTIME_CONTRACT_BINDING` re-derives the expression from the contract and
  refuses on drift (`TARGET_EXPRESSION_DRIFT` / `COMPOSITE_RUNTIME_EXPRESSION_MISMATCH`).

Causal review (lookahead-auditor) and contract review (contract-checker): **CLEAR** at the
final composite `93b33fadc8d21d186e93995e28f761f1bc3bc9641a10eb99c6d9715675d1fa69`
(passes 01–09; earlier passes are the iterative-fix history, retained by the durable
`audit_lineage/` anchor).

## Authoring mechanism

The authored `study_spec` is embedded in `research_decision.yaml` so
`scripts/run_research_workflow.py --advance` drives compile → prepare/freeze → readiness →
preflight → causal/contract → seal → smoke deterministically. This is the **generic**
documented compiler path (`research_workflow/study_spec_compiler.py` line 172:
`request.get("study_spec") or request.get("study_yaml")`), exercised by
`research_workflow/tests/test_workflow_engine.py` — not a canary special case.

## What ran (sealed composite `93b33fadc8d21d186e93995e28f761f1bc3bc9641a10eb99c6d9715675d1fa69`)

| Stage | Result |
|---|---|
| compile (`primitive: composite`, `target_expression` embedded) → PREPARE → READINESS R1–R10 → PREFLIGHT | PASS / CLEAR |
| causal review · contract review (distinct reviewers, passes 01–09) | CLEAR / CLEAR |
| SEAL · NT SMOKE (2023-03-03) · validate_smoke · reconcile | sealed · ACCEPTED |
| **composite target replay parity** (smoke, independent `replay_expression` oracle) | **9700 rows · 0 disposition · 0 binary-label · 0 censoring mismatches** — `artifacts/composite_target_replay_parity.json` |
| AUTHORIZE (`ef937ba4…`) | train [2023], oos [2024] |
| bounded authorized TRAIN collect — **2023-03-03 RTH only** (governed `run_collect_mode(stage="day", date_range=("2023-03-03","2023-03-03"), experiment_authorization=runtime_authorization(study,"train"))`; NOT a full-year run) | 1984 candidates · 1225 NEGATIVE / 10 POSITIVE / 749 CENSORED |
| MERGE (1 partition) | 1235 resolved (10 positive / 1225 negative) · dataset identity `09d382f1…` |
| FIT — one fixed LightGBM, deterministic seed 42, no tuning | model_id `be1bda56e1e60cd578bb064be209560c76955b6127bed6d0e3eff6e6554e4818` |
| model artifact + golden fixture + `validate_golden_predictions` | `503e873d…` · `e391c473…` · PASS |
| TRAIN FREEZE | `b63bf524e6b2c9419136fd6d11856de9dd1166fe4a15d09927998199ce70e6a7` |
| study closure → `WorkflowEngine.advance()` | `terminal_state = STUDY_CLOSED`, `next_deterministic_action = null` |
| model resolvable / loadable / golden-parity AFTER closure | PASS |
| Study B (`workflow_canary_model_reuse_v1`) reuse by immutable model_id | scores reproduced (≤ 1e-12), source study not reopened, no runtime code change → STUDY_CLOSED |

Full-year TRAIN: **not run.** OOS (2024/2025/2026): **never accessed.** No existing
scientific study modified.

## Old canary evidence

`artifacts/target_replay_parity.json` — **HISTORICAL_FALSE_PASS**,
**NON_AUTHORITATIVE_FOR_COMPOSITE_TARGET_PARITY**. Preserved verbatim (original data under
`original_artifact`). The authoritative composite parity is
`artifacts/composite_target_replay_parity.json` (and the per-run copy under `runs/`).

The pre-fix model `88fbba9568763c4122f6a8b98f096222cb8b656b9238525b4542f90ae3d2a2ce`
(barrier-only label) is superseded; the authoritative canary model is
`be1bda56e1e60cd578bb064be209560c76955b6127bed6d0e3eff6e6554e4818` (composite label,
`primitive: composite`, full `target_expression`, monotone `worst_status`, corrected
runtime + corrected independent replay).

## Disposable artifacts

`studies/workflow_canary_ordered_barrier_v1/` and `studies/workflow_canary_model_reuse_v1/`
plus `studies/model_registry/be1bda56….json` and the model artifact under this study's
`artifacts/models/`. Safe to delete once the framework fix is committed — nothing
scientific depends on them.
