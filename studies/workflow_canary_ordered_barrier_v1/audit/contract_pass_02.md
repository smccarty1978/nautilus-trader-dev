# Contract Audit — Pass 02 (bounded re-audit)

**Study:** `workflow_canary_ordered_barrier_v1` (disposable Tier-1 workflow canary)
**Audited execution composite:** `b24fc7a7989a043e843dc41e4c8530935ac56d6ac00678749809885c720e5316`
**Prior pass:** `contract_pass_01.md` — CLEAR, 2 non-blocking WARNINGs.
**Mode:** PRE-EXECUTION / PRE-SEAL. No collect run, no seal, no authorization, no TRAIN
freeze exists.
**Delta reviewed this pass:** one follow-up change to
`research_workflow/generic_collector.py` (`_evaluate_checkpoint` now derives
`target_frozen_atr = float(self.regime_engine.atr or 0.0)` at T and writes it into all
three checkpoint `cand_record` builders) + new test `test_5c_...` in
`research_workflow/tests/test_ordered_barrier_entry_reference.py`; removal of
`CANARY_BLOCKER.md`; parity driver moved to `_work/`. All pass-01 findings not touched by
this delta are carried by reference, not re-derived (bounded re-audit protocol).

## Composite / lifecycle freshness

- `audit/frozen_execution_manifest.json` `frozen_execution_composite_sha256` =
  `b24fc7a7…5316` = audited composite = `audit/readiness.json`
  `prepared_execution_identity` = `audit/preflight.json` `execution_composite_sha256`.
  PREPARE re-run after the change (`generated_at_utc` 21:05:10). **PASS.**
- `compiled_study_sha256` = `d5b0d9dc…5134` — **unchanged** from pass 01. `study.yaml`,
  `SPEC.md`, `compiled_study.json`, `config/*` untouched. No spec-hash restamp.
- No seal / `experiment_authorization.json` / `train_experiment_freeze.json` /
  `audit/status.json` exists. Nothing to be staled by the edit. **PASS.**
- preflight `status: CLEAR`, all 8 required checks run and `PASSED`,
  `required_checks_missing: []`, `checks_complete: true`. readiness `overall_status:
  PASS` (R1–R10). **PASS.**

## Prior findings adjudicated

| # | Pass-01 finding | Status | Evidence |
|---|---|---|---|
| WARNING 1 | Compiled `target.condition_logic: "AND"` over `flip_within_60s` (`kind: flip`) + `ordered_barrier_canary`, but `research/engines/target_engine.py:116-118` sets `primitive: "ordered_barrier"` from mere presence of `conditions` and `resolve_target_runtime` dispatches solely to `OrderedBarrierTargetRuntime`; the `flip` condition is never conjoined, so the emitted label reflects only the barrier race. | **CARRIED as NOTE** (per coordinator) | Out of scope for the entry-reference / ATR-freeze fix. Confirmed still present: compiler and runtime unchanged this pass. Recorded below as a known framework limitation (also affects `clean_tradable_reversal`); to be carried into the canary report as a follow-up. Not re-raised as a blocker or warning. |
| WARNING 2 | `CANARY_BLOCKER.md` stale — described a `BLOCKED` R10 state and an old composite that this delta had already fixed. | **FIXED** | File removed — `Glob studies/workflow_canary_ordered_barrier_v1/*.md` now returns only `SPEC.md`. |

## New-delta verification

| Requirement | Verdict | Evidence |
|---|---|---|
| `target_frozen_atr` derivation faithful to the compiled contract (`atr_source: latest_causally_completed_1m_wilder_atr_14_available_at_T`, `atr_frozen_at: decision_ts`) | PASS | `generic_collector.py:1244` `target_atr_t = float(self.regime_engine.atr or 0.0)` — single derivation at the top of `_evaluate_checkpoint`, used in all three `cand_record` dicts (`:1433`, `:1536`, `:1643`). This is the **same** source the episode path already uses (`_build_episode_candidate_row:1120,1161-1162` — `atr_t` / `target_frozen_atr` both `float(self.regime_engine.atr or 0.0)`), so the ordered-barrier half-width is now frozen at T identically across population paths. It is distinct from `cand_record["atr"]` (= `regime_frozen_atr`, frozen at regime **start**), which the prior checkpoint path fed to the barrier — the change moves the checkpoint path from a regime-start ATR to a decision-ts ATR, **increasing** contract faithfulness. `_frozen_target_atr_at_T` key precedence `("target_frozen_atr", "atr_t", "atr")` (`:698`) makes `target_frozen_atr` win; `_track_pending:651` consumes it; non-positive still fails closed (`:700-705`). |
| No change to the persisted candidate / observation surface | PASS | `target_frozen_atr` is not in `study.yaml` `metadata_columns` (`observation_ts`, `regime_start_ns`, `checkpoint_index`) nor in the 5 feature aliases; it is consumed only by `_track_pending` (which builds its own narrow dict) and `OutputManager.persist_collection` rejects undeclared columns. readiness R10 for this composite: `emitted_feature_count: 5` (same 5 features), `metadata_count: 4`, `unexpected_columns: []`, `candidate_rows_observed: 1`, `passed: true` — byte-identical surface to pass 01. |
| No change to freeze / seal state | PASS | see "Composite / lifecycle freshness". Only `research_workflow/generic_collector.py` (already inside the execution closure) and a test file changed; composite re-derived and re-frozen; no downstream sealed artifact exists. |
| Test coverage genuine | PASS | `test_5c_target_atr_is_the_T_frozen_value_not_the_feature_normalization_atr` sets `atr=99.0` (feature-norm) and `target_frozen_atr=10.0` on a checkpoint candidate, asserts `pending_candidates[0]["atr"] == 10.0` and a touch at `0.25*10` resolves `LABELED_POSITIVE` (would miss a `0.25*99` barrier). Directly exercises the precedence the fix relies on. |
| Terminal-label reachability / deliverables contract / research-decision fidelity | PASS (unchanged) | `config/deliverables_contract.json` unchanged (`authorized_modes: ["collect"]`, 5 deliverables); `terminal_decisions` WORKFLOW_CANARY_PASS/FAIL both reachable; `artifacts/research_decision_fidelity_report.json` `status: PASSED`, `findings: []`; preflight `RESEARCH_DECISION_FIDELITY: PASSED`. |

## C4 / D / E

- **C4**: NOT APPLICABLE — single fixed arm, no model selection.
- **D**: NOT APPLICABLE — no model trained or served.
- **E**: PASS — disposition/censoring reconciliation and the independent replay oracle
  (`target_replay_oracle.replay`, `validate_target_parity` gating `censoring_mismatches ==
  0`) are unchanged by this delta and were verified in pass 01. The oracle derives its
  ATR from `candidate["atr"]`, which `_track_pending` now populates from the same
  T-frozen value on both paths — parity semantics preserved.

## NOTE (carried, per coordinator): composite `condition_logic: "AND"` not conjoined

`study.yaml` / `compiled_study.json` declare `target.type: composite`,
`condition_logic: "AND"` over a `flip` condition and an `ordered_barrier` condition. The
compiler sets `primitive: "ordered_barrier"` whenever any `conditions` exist
(`research/engines/target_engine.py:116-118`) and the collector dispatches to a single
`TargetRuntime`; nothing conjoins the `flip_within_60s` condition, so the emitted
`target_flip_within_horizon` / `disposition` reflect only the ordered-barrier race. For
this canary this is immaterial (acceptance C1/C2 concern only the ordered-barrier binding;
every emitted label is a valid ordered-barrier label and every declared terminal label is
reachable). It is a genuine declaration-vs-implementation gap for any real `composite` +
`flip` study — it also affects `clean_tradable_reversal`. Recommended follow-up:
`_compile_target_contract` should reject a `condition_logic` it cannot execute, or stamp
`condition_logic_effective` into the contract. Recorded as a framework limitation, not a
blocker or warning against this study.

## Referred to lookahead-auditor

- Whether `self.regime_engine.atr` at T is strictly the *latest causally completed* 1m
  Wilder ATR(14) (no partial-bar contribution) is a causal-timing judgement. The episode
  path already relied on this value and `CAUSAL_LINT` / `CAUSAL_INVARIANTS` passed in
  preflight against composite `b24fc7a7…`; this delta only extends the same source to the
  checkpoint path.

## Blocking verdict

<!-- AUDIT_SUMMARY_V2_START -->
{
  "verdict": "CLEAR",
  "audit_type": "contract",
  "study": "workflow_canary_ordered_barrier_v1",
  "auditor": "contract-checker",
  "audited_execution_composite_sha256": "b24fc7a7989a043e843dc41e4c8530935ac56d6ac00678749809885c720e5316",
  "blocking": 0,
  "critical": 0,
  "warning": 0,
  "not_verified": 0
}
<!-- AUDIT_SUMMARY_V2_END -->

**CLEAR.** The follow-up change is faithful to the compiled target contract: the
checkpoint population path now freezes the ordered-barrier ATR from the latest completed
1m ATR available at the decision timestamp (`self.regime_engine.atr`), identical to the
episode path and consistent with `atr_frozen_at: decision_ts` — a strict improvement over
the prior regime-start ATR. `target_frozen_atr` is not persisted (readiness R10 shows a
byte-identical 5-feature / 4-metadata surface with `unexpected_columns: []`), the compiled
study hash is unchanged, and no seal / authorization / freeze artifact exists to be
staled. Pass-01 WARNING 2 (`CANARY_BLOCKER.md`) is fixed by removal. Pass-01 WARNING 1
(unimplemented composite `AND` logic) stands as a documented framework limitation carried
forward as a NOTE / follow-up per the coordinator, out of scope for this fix and
non-blocking for this disposable canary. No new contract or governance defect.
