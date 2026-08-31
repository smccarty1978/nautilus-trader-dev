# Contract & Governance Audit — pass 16 (Red-Team Remediation Pass 1 re-audit)

Study: `clean_maturity_flip_model_180s_horizon`
Audited execution composite: `09b5c66db8ec72bbf05f539c6a877dc8c9198774f4c4b7117fdea72fd618f48a`
Lifecycle position: post framework merge (RT-01..RT-13) + `execution.modeling_driver_relpaths`
declaration + deterministic `config/*.json` mirror refresh, re-PREPARE'd and re-READINESS'd and
re-audited (causal pass_17 CLEAR). A full TRAIN+OOS cycle (commits `5d7372e..641d4a8`) was run
against the prior seal `bd2e9cf1`; those artifacts now exist and their stage-scoped lineage is
stale — this is the expected trigger for re-SEAL + deterministic lineage re-freeze, not a defect.

## Prior-pass adjudication (contract_pass_14; contract_pass_15 superseded at e9709310)

- Resolver run independently by this auditor — **STILL OPEN** (no Bash this session); mitigated by
  preflight `EXECUTION_MANIFEST` re-derivation and `run_preexec_audits.py` re-derivation on ingest.
- SPEC.md / study.yaml hash-namespace consistency — **SUPERSEDED**: `study.yaml` hash moved
  `7a49b6b5…`→`464ed34a…` (modeling_driver_relpaths), `frozen_execution_manifest.json` /
  `phase0_source_manifest.json` re-generated at `09b5c66d…`, preflight `EXECUTION_MANIFEST` PASSED.
- SPEC §7 domain / partition grid — **STILL OPEN** (carried; canonical template has no §7; domain
  carried by `population_contract` 5s grid / `regime_start_ns` origin / `interval_close`).
- 27 study-local tests — **FIXED**: re-run this session, PASS (per task).
- Referred-out: parameterized-feature identity repair — **RESOLVED** (`feature_list_sha256
  38c0201f…` is consistent SPEC → `feature_contract.json` → `train_experiment_freeze.json`
  `feature_sets` with `prior_1m_*` distinct from `prior_5m_*`). Parent SPEC.md drift — **NOT THIS
  STUDY'S** (parent history, flagged, lineage binds on composite). `model.params random_state` —
  **RESOLVED** (`model_selection.json`: `random_seed: 42`, `fixed_hyperparameters {verbosity:-1}`
  only, no `random_state`). `model_family` joblib claim / optional `pre_fit` gate — **NOT
  APPLICABLE** / re-stamped at deterministic re-freeze. Stale downstream TRAIN artifacts —
  **EXPECTED** (row: stale stage-scoped lineage).
- `config/population_contract.json` mirror key-order (contract_pass_15 WARNING) — **RESOLVED**:
  re-dumped from `compiled_study.json[contracts][population_contract]`, hash `f68c39e6…`→`5ac7180e…`,
  content byte-identical (RT-06 key-order only). All `config/*.json` mirrors now byte-consistent
  with the compiler output (zero drift).

## Requirement rows

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| Audited composite is current across the 3 inputs | PASS | `frozen_execution_manifest.json` `frozen_execution_composite_sha256 = 09b5c66d…`; `preflight.json` `execution_composite_sha256 = 09b5c66d…`, `status: CLEAR`, `audit_ready: true`, 8/8 checks PASSED (run `20260831T153641Z`); `readiness.json` `prepared_execution_identity = 09b5c66d…`, `overall_status: PASS`, R1–R10, generated 15:34:48Z (re-emitted at current composite) | preflight `EXECUTION_MANIFEST` re-derivation | — |
| Distinct auditor identities | PASS | this report `contract-checker`; `audit/status.json` + `audit/pass_17.md` `lookahead-auditor` (CLEAR at `09b5c66d…`); both `DECLARED_IDENTITY_ONLY` | — | — |
| `spec_sha256` `e363badf…`→`f31494da…` for exactly one reason | PASS (not independently recomputed) | diff: only `execution.modeling_driver_relpaths` added to spec; `qualification` key-order shift is hash-neutral (`compute_sha256` `sort_keys=True`); `session_end_censoring` appears only under `contracts.*`, not `spec.target` (`exclude_if` drops `None`). `compiled_study.json` (`e3843c7d…`) and `spec_hash` (`f5d37442…`) unchanged from the e9709310 pass | `tests/test_study_contracts.py` (committed, re-run PASS); preflight `EXECUTION_MANIFEST` + `RESEARCH_DECISION_FIDELITY` PASSED | on ingest confirm tooling re-derives `f31494da…` |
| `modeling_driver_relpaths` faithful | PASS | only two `implementation/*.py`: `two_phase_selection.py:39 from research_workflow.model_selection import run_model_selection`; `final_train_freeze.py:29 from research_workflow.modeling import fit_models, freeze_train_artifacts` — both governed; both declared; `modeling_drivers.find_participating_modeling_modules` would return exactly this set. Bytes bound in `frozen_execution_manifest` `file_sha256_map` (`d6e3070f…` / `e9f872fb…`). Lineage-only: no population/feature/target/chronology/model-family/threshold/split/direction/order/horizon change | causal pass_17; preflight `RUNTIME_CONTRACT_BINDING` PASSED | — |
| Generated-mirror `config/target_contract.json` refreshed, not hand-authored | PASS | byte-identical (key order + values) to `compiled_study.json.contracts.target_contract` (lines 376–391): `session_end_censoring: true` top-level + `censoring_policy.session_end_censoring: true`. Authoritative value from `target_engine.resolve_session_end_censoring`: no authored `TargetSpec.session_end_censoring`, no `required_forward_outcomes` → historical default `True` | causal pass_16/17; preflight `RUNTIME_CONTRACT_BINDING` (RT-05 `assert_target_semantic_field_coverage`) PASSED | — |
| No OTHER `config/*.json` mirror drifted | PASS | all mirrors byte-consistent with the compiler output: `population_contract.json` re-dumped (`5ac7180e…`, RT-06 key-order only, content identical); `feature_contract.json` (`3607b3dd…`), `model_selection.json` (`86241ac5…`), `target_contract.json` (`ba93cfeb…`) all in sync with `compiled_study.json.contracts` | preflight `RESEARCH_DECISION_FIDELITY` PASSED | — |
| target_contract semantics unchanged | PASS | `primitive: flip_within_horizon`, `horizon_seconds: 180`, `confirmation {completed_1m_bar, 1}`, `censoring_policy.session_end_censoring: true`, `direction: both` — all unchanged; `feature_contract.derived_causal_inputs: []` | — | — |
| Chronology TRAIN 2021-23 / dev 2024 / prohibited 2025-26 | PASS | `experiment_authorization.json` `train_years [2021,2022,2023]`, `oos_years [2024]`, `prohibited_years [2025,2026]`; `compiled_study.json` `execution_contract.chronology` agrees; `research_decision.yaml` (`c24e456e…`, unchanged) | preflight `RESEARCH_DECISION_FIDELITY` PASSED | — |
| No forward-outcome columns in feature surface | PASS | `feature_contract.json` 13 regime-geometry/rolling-productivity/arrival/ema features; `derived_causal_inputs: []`; `contains_provisional_features: []`; readiness R10 `emitted_features` = the 13, `unexpected_columns: []`; `train_experiment_freeze.json` `feature_sets.{LONG,SHORT}_C` = same 13 | causal pass_17; preflight `CAUSAL_INVARIANTS` PASSED | — |
| TRAIN/OOS/prohibited disjoint; authorization not stale in binding | PASS | `experiment_authorization.json` `authorization_sha256 19534de9…` == `train_experiment_freeze.json.authorization_sha256` == `oos_collection_manifest.json.authorization_sha256`; `oos_unlock.json` `OOS_UNLOCKED`, `oos_year 2024`, `oos_leaks_count 0`, `pristine_oos_proven true` | — | — |
| TRAIN artifacts frozen before OOS produced; thresholds/deciles `derivation_population: train` | PASS | `train_experiment_freeze.json` `generated_at 2026-08-31T03:09:02Z`; `oos_unlock.json` `authorized_at 03:18:28Z` (after); `oos_collection_manifest.json` binds `train_freeze_sha256 b2f80255…`. All thresholds `derivation_population: "train"`, deciles `derivation: "TRAIN_ONLY"` | — | — |
| Stage-scoped lineage + seal freshness | PASS (expected-stale, non-blocking) | `train_experiment_freeze.json` `stage_scoped_lineage`: `COLLECTION_PRODUCER_CLOSURE bd2e9cf1…` (prior composite) / `TARGET_RUNTIME_CLOSURE 54dc9897…` / `MODELING_EXECUTION_CLOSURE 7541e123…` — all stale vs current tree; `preexec_audit_seal.json` still `LOCKED` at `bd2e9cf1…` (pass 14). `authorization_sha256`/`freeze_sha256` UNCHANGED and still bound by `oos_collection_manifest.json`. Collection behaviour parity preserved (readiness R1–R10 PASS incl. R10; causal pass_16/17 CLEAR — legacy inline flip path byte-identical, `session_end_censoring` resolves to same `true`) | readiness R1–R10; causal pass_16 §1,§2 | re-SEAL at `09b5c66d…`, then deterministic lineage TRAIN re-freeze + OOS reconciliation (NO recollection, NO retrain); reconcile existing TRAIN/OOS `candidate_sha256`/`observation_sha256` and re-bind OOS analysis (RT-13 identity) to the refreshed freeze |
| Deliverables contract (`authorized_modes: [collect]`) producible | PASS | `deliverables_contract.json` 5 deliverables (`candidates.parquet`, `observations.parquet` [labels], `collection_manifest.json`, `run_manifest.json`, `status.json`) all via `output_manager.py::persist_collection`/`OutputManager`; `oos_collection_manifest.json` shows 450,973 candidate+observation rows, both hashed; SPEC.md rendered from contract | — | — |
| Terminal decision labels reachable | PASS | `two_phase_selection.py` per-direction `{dir}_PASS`/`{dir}_FAIL` at 2023 reject-only gate → A/B/C or D, divergent → MIXED, 2024 OOS assigns terminal class; consistent with pass_12/13/14 | 27 study-local tests PASS this session | — |
| Off-path modules genuinely off-path | PASS | `analysis.py`, `oos_analysis_lineage.py`, `workflow_engine.py`, `derived_inputs.py` absent from `frozen_execution_manifest` `resolved_execution_file_list`. `external_model_scoring.py`/`model_artifacts.py` hashed but reachable only via empty derived-scorer path (`derived_causal_inputs: []`) or TRAIN `persist_models`. Frozen models `139fb532…`/`4d62250a…` carry `scientific_status: UNASSESSED` / `reuse_status: PERMITTED` — RT-09 permits (blocks only explicitly-invalid); not consumed as a derived input here | causal pass_16 §4,§7 | — |
| C4 walk-forward / selection seal discipline | PASS (design) | single causal fold fit=2021/val=2022; 2023 reject-only, one touch, no path back to candidate loop; `model_selection.json` `tuning_years [2021,2022]`, `final_train_validation_years [2023]`, `final_validation_policy: gated` | preflight `CAUSAL_INVARIANTS` PASSED; re-audit on real Phase-1/2 manifests at re-freeze | — |
| D train/serve skew / determinism / artifact hash binding | PASS | `train_experiment_freeze.json` binds `model_hashes`, `preprocessing_hash 96ebac89…`, per-model `artifact_sha256` + `golden_fixture_sha256` + `native_booster_sha256`; `aggregate_of` records `no_refit`/`no_retune`/`model_bytes_reused_verbatim`. No ONNX, no live serve path | — | verify golden reproduction at deterministic re-freeze |
| E backtest configuration / fill / warmup | NOT APPLICABLE | `collect` mode only; no order simulation on this path | — | — |

## Referred to lookahead-auditor

None — no look-ahead outside the SPEC observed in the contract surface. Causal pass_17 (CLEAR,
same composite `09b5c66d…`) already covers the RT Pass 1 execution-semantics surface.

## Blocking verdict

**CLEAR**

Against composite `09b5c66d…` the pre-execution state is legitimate. The three lifecycle inputs
(frozen manifest, preflight, readiness) agree on the composite; preflight is CLEAR with 8/8
required checks; readiness R1–R10 PASS and was re-emitted at the current composite; the causal
gate (pass_17) is CLEAR under a distinct declared identity. The only spec change is the additive,
hash-relevant `execution.modeling_driver_relpaths` declaration, which is faithful (both — and
only — study-local modeling drivers declared) and lineage-only. The `config/*.json` mirrors are
now all byte-consistent with the compiler output (the pass_15 `population_contract.json`
key-order drift is resolved by a deterministic re-dump; content was always byte-identical). Target
primitive, horizon (180), confirmation, censoring, chronology, feature surface and deliverables
are all unchanged and internally consistent. The stale stage-scoped lineage in
`train_experiment_freeze.json` and the stale `preexec_audit_seal.json` are the expected
consequence of the framework merge and are the reason the re-SEAL + deterministic lineage TRAIN
re-freeze + OOS reconciliation steps exist; they are not blocking. Non-blocking residuals:
(1) `spec_sha256 f31494da…` not independently recomputed here (mitigated by committed test +
ingest re-derivation); (2) the deterministic re-freeze must reconcile the existing TRAIN/OOS
parquet content hashes and re-bind the OOS analysis lineage (RT-13) — behaviour-equivalence is
the load-bearing assumption, attested by causal pass_16/17, not by re-execution; (3) SPEC §7
domain/partition grid still not reconciled against a partition grid; (4) resolver not run
independently this session.

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "contract", "auditor": "contract-checker", "critical": 0, "warning": 0, "note": 4, "study": "clean_maturity_flip_model_180s_horizon", "audited_execution_composite_sha256": "09b5c66db8ec72bbf05f539c6a877dc8c9198774f4c4b7117fdea72fd618f48a"}
<!-- AUDIT_SUMMARY_V2_END -->
