# Look-Ahead & Timestamp Audit — Pass 17

**Date** 2026-08-31 ·
**Scope** Red-Team Remediation Pass 1 execution-semantics changes on this study's closure:
`research/schemas/study_spec.py` (`PopulationQualificationSpec`, `TargetSpec.session_end_censoring`,
`ExecutionSpec.modeling_driver_relpaths`, `compute_sha256`); `research/engines/target_engine.py`
(`resolve_session_end_censoring`, `compile_target_contract`); `research/engines/population_engine.py`
(`compile_population_contract`); `backtests/nt_runtime/modes/collect.py` (`build_collector_config_kwargs`
qualification + `session_end_censoring` + `derived_inputs` binding); `research_workflow/generic_collector.py`
(`__init__` derived-scorer block, new `_apply_derived_scores`, `_append_candidate`, episode row builder);
`research_workflow/target_runtime.py` (`assert_target_semantic_field_coverage`, RT-05 field sets,
`FlipTargetRuntime.parity_row`, `validate_target_parity` bare-flip branch);
`research_workflow/target_replay_oracle.py` (`_replay_flip_condition`, `replay_expression`);
`research_workflow/{experiment,modeling,modeling_drivers,runtime_bindings}.py`; off-path diff
(`derived_inputs.py`, `external_model_scoring.py`, `model_artifacts.py`, `analysis.py`,
`oos_analysis_lineage.py`, `workflow_engine.py`); study `study.yaml` + `compiled_study.json` +
`config/target_contract.json` and `config/population_contract.json` mirror refresh. ·
**Scope hash (frozen execution composite)** `09b5c66db8ec72bbf05f539c6a877dc8c9198774f4c4b7117fdea72fd618f48a` ·
**Lint** 0 critical / 0 warning (`audit/preflight.json` CAUSAL_LINT PASSED, run `20260831T153641Z`) ·
**Verdict** `CLEAR`

## Summary
Critical: 0 · Warning: 0 · Note: 2

## Composite freshness
Declared composite `09b5c66d…18f48a` is byte-identical across
`audit/frozen_execution_manifest.json` (`frozen_execution_composite_sha256`),
`audit/preflight.json` (`execution_composite_sha256`, `status: CLEAR`, `audit_ready: true`,
all 8 gates PASSED incl. `EXECUTION_MANIFEST` re-derivation, `CAUSAL_LINT` 0/0,
`RUNTIME_CONTRACT_BINDING` PASS; preflight run `20260831T153641Z`, generated 15:36:41Z), and
`audit/readiness.json` (`prepared_execution_identity` and `r8_double_identity.composite_sha256`
`09b5c66d…`, `overall_status: PASS`, R1–R10 PASS incl. R2 `TIMESTAMP_CONTRACT_OK` and R4
`CALLBACK_ORDER_OK`; re-emitted at this composite, generated 15:34:48Z). The three inputs
now carry one identity; the pass_15/pass_16 note about a lagging `readiness.json` identity is
**RESOLVED**.
The composite moved from earlier-pass `486d1b56…` → `e9709310…` → `09b5c66d…` solely because
two generated mirrors were deterministically re-dumped from the compiler output:
`config/target_contract.json` (adds the top-level `session_end_censoring: true` verified in
Analysis §2) and `config/population_contract.json` (RT-06 typed-field key ORDER only, content
byte-identical). Both are non-authoritative human/tooling mirrors that no live runtime path
reads (the collector binds `study_data.contracts[...]` from `compiled_study.json`); all
`config/*.json` mirrors are now byte-consistent with the compiler output. `Bash` unavailable
this session; verification is by reading the three files.

## Prior findings adjudicated
| # | Finding | Status | Evidence |
|---|---|---|---|
| pass_14 NOTE "Live flip path and dormant `FlipTargetRuntime` disagree on the T boundary" | CARRIED / narrowed | Legacy inline path still the only runtime for this study (see Analysis). RT-07 now gives `validate_target_parity` a genuinely independent bare-flip oracle (`target_replay_oracle._replay_flip_condition`, via `replay_expression`) where pass_14 had none. The convention it enforces — lower bound `T < ts`, upper bound `ts <= T+180s`, `SESSION_END` when `end > session_close_ts` — matches the live inline path on every reachable candidate. The only divergent class (a confirmation landing at exactly T) is unreachable: 5s candidate cadence + 1s-before-1m dispatch. Improvement, not a defect. |
| pass_14 NOTE "Shorter horizon reduces session-end censoring" | CARRIED | Unaffected by Pass 1; horizon still 180 via `spec.target.horizon_seconds` → `cfg.horizon_seconds`. Re-stated below. |
| pass_15/16 NOTE "`readiness.json` identity lags the current composite" | RESOLVED | `readiness.json` re-emitted at `09b5c66d…`; R1–R10 PASS; all three audit inputs now one identity. |
| pass_14 "Referred to contract-checker" (parameterized-feature identity repair; parent SPEC.md drift; `model_family` joblib claim; dormant `model.params` `random_state`; optional `pre_fit` gate; stale downstream TRAIN artifacts) | RE-REFERRED | Not adjudicated here — see `## Referred to contract-checker`. |

## Analysis — does RT Pass 1 introduce look-ahead on this study's live path?

**1. Target primitive unchanged; new runtime machinery still dormant.**
`contracts.target_contract.primitive == "flip_within_horizon"`; `conditions: null`,
`required_forward_outcomes: null` (`compiled_study.json:377,43,45`). `_track_pending`
(`generic_collector.py:709,726`) falls through the `composite` and `ordered_barrier` guards
to the **unchanged legacy inline `pending` dict** (`gc:761-769`), which still gates
`session_close_ts` on `self.cfg.session_end_censoring`. `FlipTargetRuntime.open_pending` /
`_terminal_pending` / `ingest_bar` / `parity_row` are never invoked at collection time.
The generic_collector diff touches only `__init__` (derived scorers), the new
`_apply_derived_scores`, `_append_candidate`'s keep-set, and `_build_episode_candidate_row`
(~gc:1341); `_emit_observation`, `_on_regime_flip`, `_sweep_elapsed_horizons` and the
legacy `_track_pending` branch are byte-identical to pass_14. Only
`runtime.from_disposition()` remains on the live path, unchanged (pass_14 field-by-field).

**2. `session_end_censoring` resolves to `true`, from the contract's own policy.**
`resolve_session_end_censoring` (`target_engine.py:114-119`): `TargetSpec.session_end_censoring`
is `None` (absent from `compiled_study.json` spec.target — `exclude_if` drops it),
`required_forward_outcomes` is `None`, so it returns the historical default `True`.
`compile_target_contract` writes both `target_contract.session_end_censoring: true` (new
top-level) and `censoring_policy.session_end_censoring: true` (`compiled_study.json:386,388`);
the generated mirror `config/target_contract.json` was refreshed to match.
`build_collector_config_kwargs` (`collect.py:329-337` new form): `"session_end_censoring" in _tc`
is true → `cfg_kwargs["session_end_censoring"] = bool(_tc["session_end_censoring"]) = True`.
Identical to the pre-merge hard-coded value; the fallback (`censoring_policy`) is not reached
and is the same `true` anyway. No hard-coded default in the resolved path.

**3. Typed `PopulationQualificationSpec` is behaviour-neutral here.**
Compiled `spec.population.qualification` carries the same six keys with the same values
(`established:true, age_gate_seconds:120, cadence_seconds:5, running_mfe_atr_gte:1.0,
new_progress_windows_gte:2, retained_mfe_ratio_gte:0.5`, `compiled_study.json:25-32`); only
JSON key order changed. `compute_sha256` (`study_spec.py:993,1002`) dumps with
`sort_keys=True`, so order is hash-neutral; `spec_sha256` moved (`e363badf…`→`f31494da…`)
solely because `modeling_driver_relpaths` is now a set, non-empty field. All six keys are
declared Group-A/`extra="forbid"` fields; `validate_mutually_exclusive_population_tests`
passes (no identity-allowlist path). `collect.py:266-272` collapses the typed object via
`model_dump(exclude_none=True)` back to the historical dict before the unchanged
`.get(key, default)` wiring — same keys, same values into the established-filter runtime.
`population_engine.compile_population_contract` does the same at compile time; the refreshed
`config/population_contract.json` mirror is a key-order-only re-dump, content byte-identical.

**4. `_apply_derived_scores` / derived-input machinery is a no-op.**
`spec.features.derived_inputs: null` (`compiled_study.json:175`);
`features.derived_causal_inputs: []` (`:922`). `collect.py:334-343` only sets
`cfg_kwargs["derived_inputs"]` when `_runtime_di` is non-empty → not set. In
`generic_collector.__init__`, `di_list` is empty → `self._derived_scorers == []`.
`_apply_derived_scores` (`gc:539`) returns immediately; `_append_candidate` (`gc:571-573`)
adds no score name to the keep-set. The persisted candidate surface is exactly the 13
declared aliases + canonical keys + metadata — confirmed by readiness R10
(`emitted_features` = the 13, `unexpected_columns: []`). The design of the scorer path
(scores only from `record`-resident values snapped ≤T, `availability_ts` = candidate T,
null-out on any missing input) is causally sound but not exercised here.

**5. RT-05 `assert_target_semantic_field_coverage` is a fail-closed pre-seal gate.**
Added to `runtime_bindings.verify_runtime_contract` (`runtime_bindings.py:165-169`) as an
additional assertion after the existing dispatch check — it does not replace or loosen any
check. For this contract: `confirmation {mode: completed_1m_bar, confirmation_bars: 1}` is
non-inert but `confirmation` ∈ `FlipTargetRuntime.CONSUMED_SEMANTIC_FIELDS`, and both
sub-values are in `SUPPORTED_SEMANTIC_VALUES` (`mode` ∈ {bar_close, completed_1m_bar};
`confirmation_bars` ∈ {None, 1}). No `atr_source` / `atr_frozen_at` / `bar_inclusion` /
exotic `entry_reference` present. Gate passes; `RUNTIME_CONTRACT_BINDING` PASSED in preflight.

**6. Modeling-driver declaration touches only the TRAIN identity.**
`execution.modeling_driver_relpaths = [implementation/final_train_freeze.py,
implementation/two_phase_selection.py]` (`study.yaml`, `compiled_study.json:333-338`).
`modeling_closure.resolve_modeling_closure` folds these bytes into
`MODELING_EXECUTION_CLOSURE` only; they are absent from
`frozen_execution_manifest.json:resolved_execution_file_list`'s runtime portion except as
`study:` inputs already hashed. `assert_declared_modeling_drivers`
(`modeling_drivers.py`) is a static AST scan of `implementation/*.py` for governed-module
imports, invoked only inside `fit_models` / `freeze_train_artifacts` — no runtime data
path, no bar access, no forward window. `experiment.assert_oos_open` (RT-01) only hardened
its existing `modeling_driver_relpaths` read with `or []` guards; still raises
`TrainFreezeRequired` and fails closed. No OOS/2024-2026 path became reachable.

**7. Off-path modules confirmed off-path.**
`research_workflow/analysis.py`, `oos_analysis_lineage.py`, `workflow_engine.py`,
`derived_inputs.py` are absent from the frozen execution file list — not in the collection
producer closure. `external_model_scoring.py` and `model_artifacts.py` are in the list
(bytes hashed) but are reachable only through the empty derived-scorer path (collection) or
TRAIN-stage `persist_models` — neither runs for this study at collection.
`workflow_engine.classify_oos_analysis` is wrapped in a non-blocking `try/except` and only
reads existing artifacts.

**8. Repeat-offender checks.** No cross-event elapsed time added. No new `_T_*` collector
field on the persisted surface. No running/eventual extremum column. No grouping variable.
No forward-outcome column (`mfe_*`, `post_confirmation_*`) — readiness R10 emitted-feature
list is the 13 declared. `bar_state: completed` on all 1m/5m structural instances;
`confirmation.mode: completed_1m_bar` (no forming bar). Session handling: emission RTH,
`session_close_ns(T, "RTH")` is a pure function of T; the ETH regime state the engine sees
is unchanged. 1s-before-1m dispatch unchanged (readiness R4: no callback inversion).

## Critical findings
None.

## Warnings
None.

## Notes
### [NOTE] Bare-flip parity gate now has an independent oracle (pass_14 NOTE, narrowed)
RT-07 routes `validate_target_parity`'s `flip_within_horizon` branch to
`replay_expression → _replay_flip_condition` (`target_replay_oracle.py:198-259`,
`target_runtime.py:697-703`) instead of `FlipTargetRuntime.terminal()` (runtime as its own
oracle). This is a strengthening. The oracle enforces `T < ts <= T+180s` and
`SESSION_END` when `end > session_close_ts`, matching the live inline path for every
candidate the 5s cadence can produce. The pre-TRAIN target-replay parity gate should still
record this convention explicitly when it runs (stage 11b), and confirm the
`_replay_flip_condition` GAP rule (tape-interruption → `CENSORED/GAP`) does not diverge
from the legacy path's `on_stop` `DATA_END` censoring on real RTH data.

### [NOTE] Shorter horizon reduces session-end censoring (carried, unaffected by Pass 1)
`horizon_end_ts > session_close_ts` is true less often at 180s than 300s, so more
near-close candidates receive a real label rather than `SESSION_END`. Expected; the
researcher should anticipate a modest population shift near RTH close versus the 300s
parent when comparing base rates.

## Referred to contract-checker
- Parameterized-feature identity repair, parent SPEC.md drift, `model_family` joblib claim, dormant `model.params` `random_state`, optional `pre_fit` gate, stale downstream TRAIN artifacts (carried pass_14) — re-referred, not adjudicated.
- RT-09 `model_artifacts.py` `library_versions` / `runtime_identity_sha256` on persisted registry records, and RT-13 OOS-analysis lineage identity — model-integrity / provenance scope.
- `modeling_driver_relpaths` → `MODELING_EXECUTION_CLOSURE` resolution correctness and seal freshness — closure/seal scope.

## Clean checks
A1–A5, B1–B7/B9/B10, C1–C3, F1–F4, G1–G4 clean. H not exercised (flip target, no bracket
sim on this path).

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "causal", "auditor": "lookahead-auditor", "critical": 0, "warning": 0, "note": 2, "study": "clean_maturity_flip_model_180s_horizon", "audited_execution_composite_sha256": "09b5c66db8ec72bbf05f539c6a877dc8c9198774f4c4b7117fdea72fd618f48a"}
<!-- AUDIT_SUMMARY_V2_END -->
