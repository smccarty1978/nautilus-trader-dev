# Contract Audit — Pass 01

**Study:** `workflow_canary_ordered_barrier_v1` (disposable Tier-1 workflow canary)
**Audited execution composite:** `fd7472b6ee9026840b5a9b2cdb383719b25801b95e6f1b8e7388ca2a3400c6ca`
**Mode:** PRE-EXECUTION / PRE-SEAL. No collect run, no seal, no authorization, no TRAIN
freeze exists yet. Findings judge contract consistency and reachability in the frozen
study assets and the reviewed code delta, not produced artifacts.
**Delta reviewed:** `research_workflow/target_runtime.py`,
`research_workflow/target_replay_oracle.py`, `research_workflow/generic_collector.py`
(+ `research_workflow/tests/test_ordered_barrier_entry_reference.py`) vs `c4ae619`.
Causality (A, B, C1–C3, F, G, H) is out of scope — see `## Referred to lookahead-auditor`.

## Composite / lifecycle freshness

- `audit/frozen_execution_manifest.json` `frozen_execution_composite_sha256` =
  `fd7472b6…c6ca` = audited composite = `audit/readiness.json`
  `prepared_execution_identity` = `audit/preflight.json` `execution_composite_sha256` =
  R8 `composite_sha256`. PREPARE was re-run after the code change. **PASS.**
- `target_runtime.py` / `target_replay_oracle.py` / `generic_collector.py` all appear in
  `resolved_execution_file_list` with hashes matching the frozen map — the delta is
  inside the closure and is captured by the freeze. **PASS.**
- No `preexec_audit_seal.json`, `experiment_authorization.json`,
  `train_experiment_freeze.json`, `audit/status.json`, `audit/contract_status.json`
  present. Nothing stale exists to invalidate. **PASS (nothing to bind yet).**

## Requirement table

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| 1. Runtime faithful to compiled `TargetContract` (primitive, `entry_reference`, barrier ATR, `session_end_censoring`, `max_gap_seconds` — not hard-coded) | PASS | `compiled_study.json` `contracts.target_contract.primitive == "ordered_barrier"`, `required_forward_outcomes[0].entry_reference == "next_bar_open"`, `ordered_barriers[0]` fav/adv 0.25 / horizon 60. `generic_collector.py:417-433` reads primitive via `resolve_target_runtime(_tc)`, barrier off `required_forward_outcomes[*].ordered_barriers`, `_ordered_barrier_entry_reference` / `_ordered_barrier_max_gap_seconds` off the compiled FO spec; `_track_pending` (645-670) forwards them + `session_close_ts` gated on `cfg.session_end_censoring`. Oracle `_contract_barrier` (`target_replay_oracle.py:18-31`) re-reads all four from the contract. `open_pending` raises `TARGET_ENTRY_REFERENCE_UNSUPPORTED` for anything but `next_bar_open`. No literals. | `test_ordered_barrier_entry_reference.py` tests 3,4,5,9,10; `test_11*` runtime-vs-oracle | none |
| 2. Population-type independence (checkpoint-grid vs episode-lifecycle reach `open_pending` with the same target-time state contract) | PASS | No `study_id` / population-type branch anywhere in `target_runtime.py` or `target_replay_oracle.py` (read in full). `generic_collector._track_pending` branches only on `_benchmark_mode` (ablation env var) and `_target_primitive`. Both compact checkpoint path (`:1522-1540`, supplies `atr`) and episode path (`_build_episode_candidate_row:1144-1165`, supplies `atr_t`/`target_frozen_atr`, `entry_price` line removed) route through `_track_pending` → `open_pending`. `_frozen_target_atr_at_T` (`:690-705`) normalizes `target_frozen_atr`/`atr_t`/`atr`, fails closed if none positive. | `test_2_and_12_population_type_does_not_change_target_semantics` drives `_checkpoint_cand` and `_episode_cand` (no `entry_price`, different ATR key names) through the same `_track_pending`/`_run` and asserts identical disposition, label, and `resolved_at_ts` — genuine, not a tautology | none |
| 3. Disposition / label / censoring reconciliation (E) — every candidate reaches exactly one terminal disposition; censored rows carry `label=None`+`censor_reason`; unobserved entry-reference → DATA_END censor, not dropped | PASS | `_resolve_ordered_barriers:760-798`: unresolved entry + `final` → `_emit_observation(CENSORED, None, censor_reason=CENSOR_DATA_END)`; `final and now_ts < horizon_end_ts` → DATA_END; else terminal POSITIVE/NEGATIVE/CENSORED via runtime, one `_emit_observation` per candidate, remainder retained. `_emit_observation:707-749` sets `target_flip_within_horizon=None`, `censored=1`, `censor_reason` for non-POSITIVE/NEGATIVE. `OrderedBarrierTargetRuntime.terminal` covers SESSION_END, GAP, AMBIGUOUS_SAME_BAR_TOUCH, TIMEOUT→NEGATIVE. | tests 8, 9, 9b, 10, 10b; DATA_END path exercised via `_run(..., final=True)` | none |
| 4. Independent replay oracle (E / model-integrity) — separate, contract+tape derived, `validate_target_parity` requires `censoring_mismatches == 0` | PASS | `target_replay_oracle.replay` is a standalone module function, not a `TargetRuntime` subclass, shares no helper with `terminal`; derives entry from first taped bar with `ts > T` (`:61-66`), never reads a pre-populated `entry_price` when tape has `open`. `validate_target_parity` (`target_runtime.py:231-266`) computes `cm` and `passed = dm==0 and lm==0 and cm==0`; returns `censoring_mismatches`. | `test_11_*` (6 param combos) assert `censoring_mismatches == 0` and `passed`; `test_11b_oracle_is_independent_of_pre_populated_entry_price` feeds `entry_price=999999.0` and still gets the tape-derived answer | none |
| 5. Freeze/seal freshness (pre-seal) | PASS | see "Composite / lifecycle freshness" above | preflight `checks_complete: true`, `required_checks_missing: []`, all 8 `check_outcomes` PASSED | none |
| 6. `research_decision` → SPEC → `study.yaml` fidelity | PASS | `artifacts/research_decision_fidelity_report.json` `status: PASSED`, `findings: []`; preflight `RESEARCH_DECISION_FIDELITY: PASSED`. chronology `train=[2023] dev=[2024] prohibited=[2025,2026]` identical across all three files; `baseline_feature_selection.mode: none` ↔ `study.yaml baseline {}` + single fixed LightGBM arm `CANARY_SINGLE`, `model_selection.json` search none; prohibited-change list carried verbatim into the report. `compiled_study.json spec_sha256` == `SPEC.md` declared source hash. | preflight | none |
| 7. Terminal-label reachability | PASS | `terminal_decisions: WORKFLOW_CANARY_PASS → CANARY_COMPLETE`, `WORKFLOW_CANARY_FAIL → CANARY_BLOCKER_REPORTED`. PASS reached via the full closure path to `STUDY_CLOSED` (acceptance C4); FAIL via a filed blocker report — the mechanism has already been exercised once (`CANARY_BLOCKER.md`). Observation labels `LABELED_POSITIVE`/`LABELED_NEGATIVE`/`CENSORED` all reachable through `_emit_observation`. | tests 1,2,7,8,9 cover all three observation dispositions | none |
| Deliverables contract (`config/deliverables_contract.json`) | PASS (consumed, not reconstructed) | Present; `authorized_modes: ["collect"]`; 5 deliverables (`candidates.parquet`, `observations.parquet`, `collection_manifest.json`, `run_manifest.json`, `status.json`). SPEC §4 renders from it. collect has not run, so output existence is not yet assertable — R7/R10 validated the schema path through the real `OutputManager`. | readiness R7, R10 (`candidate_rows_observed: 1`, `passed: true`) | none |
| Model-integrity declarations (§6.2) | NOT APPLICABLE | Single fixed arm, no selection, no arm-delta claim, no recommended-check claims in SPEC; no model trained yet | — | — |
| Composite target `condition_logic: "AND"` honoured | **WARNING** | `study.yaml`/`compiled_study.json` declare `target.type: composite`, `condition_logic: "AND"` over `flip_within_60s` (`kind: flip`) **and** `ordered_barrier_canary`. The compiler (`research/engines/target_engine.py:116-118`) sets `primitive: "ordered_barrier"` whenever any `conditions` exist; `resolve_target_runtime` then dispatches solely to `OrderedBarrierTargetRuntime`. No code conjoins the `flip` condition — the emitted `target_flip_within_horizon` / `disposition` (and the repurposed `flip_ts`/`time_to_flip_seconds`) reflect **only** the barrier race. The declared "POSITIVE iff opposite flip within 60s AND favorable barrier first" reduces silently to "favorable barrier first". Harmless for this canary (acceptance C1/C2 test only the ordered-barrier binding; every emitted label is a legitimate ordered-barrier label) but a real `composite`+`flip` study copying this shape would get a mislabeled target. | `test_11*` only compare against the ordered-barrier oracle; no test asserts the flip conjunction | Compiler should reject (or explicitly document as reduced) a `condition_logic` it does not implement — e.g. `target_engine._compile_target_contract` raises `COMPOSITE_LOGIC_UNIMPLEMENTED` unless every non-barrier condition is representable, or emits `condition_logic_effective: "ordered_barrier_only"` into the contract. |
| `CANARY_BLOCKER.md` currency | **WARNING** | The file states "BLOCKED at READINESS R10 … Not sealed, not run" and cites an old composite `05577de9…`. Current `audit/readiness.json` is `overall_status: PASS` with R10 `passed: true` at composite `fd7472b6…`; the blocker it documents (checkpoint path requiring a synthesized `entry_price`) is exactly what this delta fixes. The doc now contradicts the live lifecycle state. | n/a | Delete or replace `CANARY_BLOCKER.md` (disposable-study narrative doc, not a governed artifact — non-blocking). |

## C4 / D / E summary

- **C4** (walk-forward, selection seals): NOT APPLICABLE — single fixed arm, no model
  selection, no test-set split beyond the declared TRAIN-only canary scope.
- **D** (train/serve skew, encoding/imputation determinism, artifact hash binding):
  NOT APPLICABLE — no model trained or served yet. `model.params` pin
  `random_state: 42`, `deterministic: true`, `n_jobs: 1`.
- **E** (disposition/censoring reconciliation, independent replay, warmup/backtest
  config): PASS — see rows 3, 4. Warmup declared `pre_train_only`, `candidate_emission:
  false`, `target_generation: false`; readiness R1 shows `warmup_start 2023-02-26`,
  `run_end 2023-03-03` — inside TRAIN year, no prohibited-year contact.

## Referred to lookahead-auditor

- `entry_reference: next_bar_open` resolution in `OrderedBarrierTargetRuntime.ingest_bar`
  (`entry_ts = ts - NS`, `bar_inclusion: fully_forward` making the entry bar itself
  barrier-eligible) and the `_track_pending` deferred-entry rewrite are causal-convention
  choices on the hot collector path. Timestamp legality is the lookahead-auditor's call;
  `CANARY_BLOCKER.md` §"Smallest proposed fix" already flags this for a ruling.

## Blocking verdict

<!-- AUDIT_SUMMARY_V2_START -->
{
  "verdict": "CLEAR",
  "audit_type": "contract",
  "study": "workflow_canary_ordered_barrier_v1",
  "auditor": "contract-checker",
  "audited_execution_composite_sha256": "fd7472b6ee9026840b5a9b2cdb383719b25801b95e6f1b8e7388ca2a3400c6ca",
  "blocking": 0,
  "critical": 0,
  "warning": 2,
  "not_verified": 0
}
<!-- AUDIT_SUMMARY_V2_END -->

**CLEAR.** All seven verification points pass: the compiled `ordered_barrier` contract is
read (not hard-coded) by both the collector and an independently-implemented replay
oracle; the target runtime is population-type agnostic and both candidate paths reach
`open_pending` with the same candidate-time state (T + frozen ATR, no synthesized
`entry_price`); every candidate reaches exactly one terminal disposition with unobserved
entries censored `DATA_END` rather than dropped; `validate_target_parity` now gates on
`censoring_mismatches == 0`; the frozen composite matches the audited composite with no
seal/authorization/freeze artifact yet to be staled; research-decision→SPEC→study.yaml
fidelity passes; and both terminal canary labels are reachable. Two non-blocking WARNINGs:
(1) the declared `condition_logic: "AND"` composite silently reduces to the ordered-barrier
primitive — the `flip_within_60s` condition has no effect on the label, which would
mislead a future composite study though it is immaterial to this canary's stated scope;
(2) `CANARY_BLOCKER.md` is stale and now contradicts the passing readiness state. Neither
blocks execution of this disposable canary.
