# Contract & Governance Audit — pass 14 (framework-reconciliation re-audit)

Study: `clean_maturity_flip_model_180s_horizon`
Declared audited execution composite: `bd2e9cf145a7408cff84613fec65149a94c296eeafad6194b42d427df4203e0e`
Lifecycle position: post-SEAL, pre-AUTHORIZE / pre-TRAIN-collection. Deterministic
framework reconciliation (stages 1–6) only. No TRAIN/OOS artifacts exist yet — their
absence is expected and is not scored as a defect.

## Prior-pass adjudication

- **contract_pass_12** (agent, composite `85efdcc4…`) — stale composite; every substantive
  finding (model-family resolution, `config/baseline.json` consistency, `random_state`
  hygiene, TRAIN/OOS chronology, threshold/decile provenance delegation, rename-collision
  guard, terminal-label reachability, deliverables) was `PASS`/resolved at the time. All
  superseded by the reseal; no open blocking item carried forward.
- **contract_pass_13** (library `research_workflow.contract_audit`, composite `bd2e9cf1…`,
  current) — `CLEAR`, 0/0/0. 12 deterministic checks passed including
  `declared_surface_matches_authorized` (13==13), `deliverables_contract`,
  `generic_collector_binding`, `population_target_contracts`, `phase0_manifest`,
  `legacy_aliases_excluded`. No open item.

No prior blocking finding remains unresolved.

## Requirement rows

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| Audited execution composite is current | PASS | `audit/frozen_execution_manifest.json` `frozen_execution_composite_sha256` = `bd2e9cf1…`; `audit/readiness.json` R8 `IDENTITY_STABLE` resolved 144 files twice to `bd2e9cf1…`; `audit/preflight.json` (post-seal re-run `20260829T061652Z`) `EXECUTION_MANIFEST` PASSED with `execution_composite_sha256 = bd2e9cf1…` | preflight `EXECUTION_MANIFEST` check re-derives the composite | — |
| Resolver run independently by this auditor | NOT VERIFIED | did not execute `scripts/resolve_execution_manifest.py` in this pass (turn budget). Mitigated by preflight's own re-derivation above and by `run_preexec_audits.py` re-deriving on ingest | — | on ingest, confirm tooling re-derives `bd2e9cf1…` |
| SPEC.md / study.yaml hash namespace consistency | NOT VERIFIED | `frozen_execution_manifest` records `study:SPEC.md = f839f75b…`, `study:study.yaml = 7a49b6b5…`; `artifacts/phase0_source_manifest.json` records `spec_md_sha256 = f5d37442…`, `study_yaml_sha256 = f924191c…`; post-seal `preflight.json` `spec_hash = f5d37442…`. Both study text files differ in the same direction between the two records — consistent with a resolver newline/normalization convention rather than post-seal drift, but not proven. Preflight `EXECUTION_MANIFEST` PASSED, which is the authoritative re-derivation | preflight EXECUTION_MANIFEST PASSED | run `resolve_execution_manifest.py` and confirm the composite is unchanged; document the resolver's file-hash convention vs raw SHA-256 |
| Preflight ran every required check and passed | PASS | `audit/preflight.json` `status: CLEAR`, `required_checks_missing: []`, `checks_complete: true`, all 8 of EXECUTION_MANIFEST / CAUSAL_LINT / ARTIFACT_SCHEMA / FEATURE_PROMOTION / RESEARCH_DECISION_FIDELITY / REQUIRED_GATES / RUNTIME_CONTRACT_BINDING / CAUSAL_INVARIANTS = PASSED | 14 targeted tests (per reconciliation writeup) | — |
| Readiness passed (R1–R10) | PASS | `audit/readiness.json` `overall_status: PASS`; r1–r10 each `passed: true` incl. r2_derived_5m (`CompletedMinuteFiveMinuteAggregator`, no external 5m stream), r4 (213,431 callbacks, no inversion), r9 (0 alternate catalog openers), r10 (emitted 13 features ⊆ resolved universe 13) | — | — |
| Causal & contract reviews have distinct declared identities | PASS | `audit/status.json` auditor `research_workflow.causal_audit`; `audit/contract_status.json` auditor `research_workflow.contract_audit`; seal `reviewer_provenance.causal` vs `.contract` distinct. Provenance strength `DECLARED_IDENTITY_ONLY` (structural — no session-evidence contract exists) | — | — |
| Seal binds report bytes to the audited composite | PASS | `artifacts/preexec_audit_seal.json` `seal_status: LOCKED`, `composite_seal_hash = bd2e9cf1…`; embeds `causal_audit_verdict.audit_report_sha256 = 112ee1e…` (`audit/pass_13.md`) and `contract_audit_verdict.audit_report_sha256 = 3c8d62f…` (`audit/contract_pass_13.md`) plus full `file_hashes` map | — | — |
| `research_decision.yaml` baseline adherence (parent canonical A/B/C, horizon-only change) | PASS | `research_decision.yaml` `baseline` = "parent's exact canonical feature instances (A/B/C), target horizon shortened only"; `variable_being_tested: [flip_target_horizon_seconds]`; `study.yaml` `features.instances` (13) = parent repaired `feature_sets` union by canonical name + parameters; `target.horizon_seconds: 180` is the only semantic delta | preflight `RESEARCH_DECISION_FIDELITY` PASSED | — |
| `baseline_feature_selection.mode: none` honored | PASS | `research_decision.yaml` `baseline_feature_selection.mode: none`; `study.yaml` `features.selection.mode: none`, `feature_count: 13`; `phase0_source_manifest.json` `selection_contract.mode: none` | — | — |
| `model_arms` A/B/C definitions honored | PASS | `research_decision.yaml` A=arrival trio, B=A+1m/5m structural, C=B+rolling 300s; `study.yaml` `model.arms` = [BASELINE, BASELINE_PLUS_STRUCTURAL, BASELINE_PLUS_STRUCTURAL_PLUS_ROLLING_5M]; parent `train_experiment_freeze_repaired.json` `feature_sets` A=3/B=9/C=13 identical by name | — | — |
| Chronology (train 2021–23 / dev 2024 / prohibited 2025–26) | PASS | `research_decision.yaml` `chronology`, `study.yaml` `chronology`, `phase0_source_manifest.json` `chronology` all agree | preflight `RESEARCH_DECISION_FIDELITY` PASSED | — |
| `prohibited_changes` / `additional_protocol_notes` (incl. 2023 single-use) | PASS | `research_decision.yaml` 10 `prohibited_changes` tokens + 2023-reject-only note; `implementation/two_phase_selection.py` `FINAL_VALIDATION_YEARS=(2023,)`, phase-1 call passes `final_train_validation_years=None` and asserts 2023 rows absent (l.105–108, 254–257) | preflight `RESEARCH_DECISION_FIDELITY` + `RUNTIME_CONTRACT_BINDING` PASSED; 27 study-local tests reported passing (not re-run here) | — |
| A/B/C surface reconciliation vs parent **repaired** freeze | PASS | Child `config/feature_contract.json` `feature_list` (13) = parent `train_experiment_freeze_repaired.json` `feature_sets.C` by name + parameters; child `compiled_study.json` `feature_list_sha256 = 38c0201f…` (disambiguated `prior_1m_*`/`prior_5m_*`); child ordering is structural-first vs parent arrival-first — arm slicing is by column name so composition (A=3/B=9/C=13) is unaffected | R10 emitted-feature parity | at TRAIN-freeze (stage 13) slice arms in `research_decision.yaml` arrival-first order for arm-comparable `feature_order_hashes` (already flagged in reconciliation §3) |
| Frozen feature sets contain no forward-outcome columns | PASS | `config/feature_contract.json` 13 features all regime-geometry / rolling-productivity / arrival / ema; `derived_causal_inputs: []`; `contains_provisional_features: []`; forward outcomes declared post-hoc descriptive only (`research_decision.yaml` `forward_outcomes_post_hoc`) | preflight `CAUSAL_INVARIANTS` + causal pass_13 `composite_target_label_only` PASSED | — |
| `config/model_selection.json` matches `study.yaml` | PASS | `config/model_selection.json`: `fixed_hyperparameters {verbosity: -1}` only (no `random_state`), `secondary_metrics: [brier]` only, `search_method: random`, `max_trials: 24`, `random_seed: 42`, `tuning_years: [2021,2022]`, `final_train_validation_years: [2023]`, `final_validation_policy: gated`, `max_degradation_vs_inner_validation: 0.15`, `calibration_max_brier: 0.3` — all equal `study.yaml model.selection`. Pre-existing drift (stale `random_state: 42`, invalid `brier_score`/`precision_at_p*`/`resolved_count`) corrected per reconciliation §2d | — | — |
| Two-phase protocol expressible under current `ModelSpec.selection` / `research_workflow/model_selection.py` | PASS | `implementation/two_phase_selection.py` composes `research_workflow.model_selection.run_model_selection`: Phase 1 own `phase1_family_spec()` (all 5 non-seed parent HPs fixed) + `search_method='none'` + `final_train_validation_years=None`; Phase 2 full `study.yaml` spec + `[2023]` gate, single winning arm passed so `_evaluate_final_validation` cannot re-enter candidate loop; `_walk_forward_folds([2021,2022])` → one fold fit=2021/val=2022 | preflight `RUNTIME_CONTRACT_BINDING` PASSED; contract_pass_13 verified `freeze_train_artifacts` `ModelSelectionBindingMismatch`/`FinalValidationFailed` guards | — |
| `terminal_decision_classes: [A,B,C,D,MIXED]` reachable | PASS | `two_phase_selection.py` returns per-direction `{dir}_PASS` (winning arm A/B/C accepted at 2023 gate) or `{dir}_FAIL` (→ D for that direction, STOP); divergent directions → MIXED; 2024 OOS primary comparison then assigns terminal class. Consistent with pass_12/13 reachability findings | — | — |
| Deliverables contract — `collect` mode artifacts producible | PASS | `config/deliverables_contract.json` `authorized_modes: [collect]`; 5 deliverables (`candidates.parquet`, `observations.parquet` [carries labels — present], `collection_manifest.json`, `run_manifest.json`, `status.json`) all produced by `backtests/nt_runtime/output_manager.py::persist_collection` / `OutputManager`; `SPEC.md` §4 rendered from the contract, not hand-listed | contract_pass_13 `deliverables_contract` check PASSED | — |
| Domain & completeness contract (SPEC §7 partition grid / boundary / zero-row / global validation) | NOT VERIFIED | canonical Study-Factory `SPEC.md` (58 lines) has no §7; domain is carried by `config/population_contract.json` (`causal_checkpoint`: 5s grid origin `regime_start_ns`, triggering `completed_1s_bar`, `observation_timing: interval_close`) and `compiled_study.json`. Not independently reconciled against a partition grid this pass; prior passes treated it as satisfied | — | at collection-merge (stage 11) confirm partition reconciliation to zero duplicate ids / no overlapping intervals |
| Lifecycle artifacts that must not yet exist | NOT APPLICABLE | `experiment_authorization.json`, `train_experiment_freeze_*`, `forward_outcome_manifest.json`, partition provenance — all correctly absent (stale copies quarantined under `_stale_pre_reconcile_20260829/`); pre-AUTHORIZE stage | — | — |
| Study-local `two_phase_selection.py` / `final_train_freeze.py` (27 tests) | NOT VERIFIED (non-blocking per task) | modules present in `frozen_execution_manifest` closure; grep confirms structure; task states test-suite pass is "not blocking at this stage" | 27 tests reported passing in reconciliation writeup — not re-executed here | run `pytest studies/clean_maturity_flip_model_180s_horizon/tests/` before Phase-1 dispatch; assess BLUEPRINT novelty-ladder retirement vs generic `model_selection` at that point |
| C4 walk-forward / selection-seal discipline | PASS (design) | single causal fold fit=2021/val=2022; 2023 reject-only, touched once, no path back to candidate loop; no test-window refit | preflight `CAUSAL_INVARIANTS` PASSED | re-audit on the real Phase-1/2 manifests at stage 12 |
| D train/serve skew, encoding/ordering determinism, artifact hash binding | NOT APPLICABLE (no serve/fit yet) | no ONNX, no live strategy, no fitted model this stage; feature ordering divergence vs parent noted above is name-keyed and benign | — | verify at TRAIN freeze |
| E backtest configuration / fill model / warmup | NOT APPLICABLE | `collect` mode only; no order simulation | — | — |

## Referred to lookahead-auditor

None — no look-ahead outside the SPEC observed in the contract surface.

## Blocking verdict

**CLEAR**

Against the audited composite `bd2e9cf1…` the reconciled pre-execution state is legitimate:
readiness PASS (R1–R10), preflight CLEAR (8/8 required checks, re-run post-seal and
re-deriving the same composite), seal LOCKED with distinct declared auditor identities and
report-byte + composite binding, and `research_decision.yaml` / `study.yaml` /
`config/model_selection.json` / `config/target_contract.json` / `config/feature_contract.json`
mutually consistent and faithful to the parent's repaired baseline with the horizon change
(300→180) as the sole semantic delta. The parameterized-feature identity repair
(`feature_list_sha256 4e46c0b3→38c0201f`, `prior_1m_*` now distinct from `prior_5m_*`) is a
deterministic framework reconciliation that preserves canonical semantic identity; the
recompiled 13-feature C set matches the parent by name and parameters. All
contract_pass_12 items are resolved or superseded and contract_pass_13 (current composite)
was CLEAR. No new blocking finding.

Non-blocking residuals the researcher should be aware of before re-collection: (1) I did not
personally run `scripts/resolve_execution_manifest.py` — the `run_preexec_audits.py` ingest
re-derives it, and preflight already re-derived `bd2e9cf1…` post-seal; (2) a SHA-256 namespace
difference between `frozen_execution_manifest.json` and `phase0_source_manifest.json`/
`preflight.json` for `SPEC.md` and `study.yaml` looks like a resolver normalization
convention but was not proven not-drift; (3) SPEC §7 domain/completeness grid is not present
in the canonical template and was not reconciled against a partition grid this pass;
(4) the 27 study-local tests were not re-executed. None of these block re-collection; items
(2)–(4) should be closed at the collection-merge / Phase-1 checkpoints.

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "contract", "auditor": "contract-checker", "critical": 0, "warning": 0, "note": 0, "not_verified": 4, "blocking": 0, "study": "clean_maturity_flip_model_180s_horizon", "audited_execution_composite_sha256": "bd2e9cf145a7408cff84613fec65149a94c296eeafad6194b42d427df4203e0e"}
<!-- AUDIT_SUMMARY_V2_END -->
