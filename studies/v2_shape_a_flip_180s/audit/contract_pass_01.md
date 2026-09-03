---
audit_type: "contract"
study: v2_shape_a_flip_180s
auditor: contract-checker
---

# Contract & Governance Audit — v2_shape_a_flip_180s — pass 01

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| Plan bound to spec (`plan_sha256`/`spec_sha256` consistent) | PASS | `compiled_plan.json:835` plan_sha256=`1571ff25c6dcba84db4db5f895c038d47ba9be43aa1dfe39f93a42d4e44f2744`, `:948` spec_sha256=`c2b5daad43ac19fd23d453306398772febc26753fbf6fd41c2b67ae245c07856`; identical values in `audit_packet_contract.json` (`plan_sha256`, `spec_sha256`) and `audit/frozen_execution_manifest.json` (both fields) | `readiness.json` check `PLAN_BOUND_TO_SPEC` = PASSED | none |
| TRAIN/OOS/prohibited chronology disjoint, no double use | PASS | `study.yaml:58-62` train=[2021], dev=[2022], prohibited=[2023-2026]; packet `chronology.authorized_dates`=["2021-01-05"]; `experiment_authorization.json` train_years=[2021], oos_years=[2022], prohibited_years=[2023-2026] — all three sources agree, sets disjoint | `readiness.json` check `CHRONOLOGY_ROLE_TABLE` = PASSED | none |
| Model validation year-role table: tuning only 2021, no final-validation year | PASS | packet `model.validation.tuning_years=[2021]`, `final_train_validation_years=[]`; `year_role_table`: 2021=tuning, 2022=dev_oos, 2023-2026=prohibited. `study.yaml:66` mirrors `final_train_validation_years: []`. No year appears twice with a different role. | none required (declarative) | none |
| Experiment authorization present and bound to composite | PASS | `artifacts/experiment_authorization.json` present, `authorization_sha256` recorded, years match chronology above | — | none |
| Readiness PASS bound to audited composite | PASS | `audit/readiness.json`: `overall_status: PASS`, `execution_composite_sha256: b7792ad8515f...` matches `frozen_execution_manifest.json` | R1/R3/R5/R8/R9 all `passed: true`; R9 explicitly reconciles `current=b7792ad8515f frozen=b7792ad8515f` | none |
| Preflight CLEAR bound to same composite | PASS | `audit/preflight.json`: `audit_ready: true`, `status: CLEAR`, `execution_composite_sha256` matches manifest; all 7 required checks (`PLAN_BOUND_TO_SPEC`, `EXECUTION_MANIFEST`, `ENTRY_REFERENCE_EXECUTABLE`, `FORWARD_OUTCOME_GUARD`, `CHRONOLOGY_ROLE_TABLE`, `PREDICATES_COMPILE`, `CAUSAL_INVARIANTS`) show `PASSED` — none missing | — | none |
| Tests PASS bound to same composite | PASS | `_work/controller/test_summary.json`: 33 passed / 0 failed, `execution_composite_sha256` matches manifest | test files listed: `test_golden_fixture.py`, `test_grammar_v2.py`, `test_host_core.py` | none |
| Causal status CLEAR, distinct auditor identity, bound to same composite | PASS | `audit/status.json`: `verdict: CLEAR`, `auditor: lookahead-auditor` (distinct from `contract-checker`), `audited_execution_composite_sha256` matches manifest; `critical: 0` | — | none |
| Deliverables reachable: label column exists, entry reference executable | PASS | `compiled_plan.json:400,821` list `target_flip_within_horizon` in observation columns; `:803` `entry_reference: "next_bar_open"`; `:812` `label_column: "target_flip_within_horizon"` — consistent with packet `outcome.label_column` | `readiness.json` check `ENTRY_REFERENCE_EXECUTABLE` = PASSED | none |
| Dataset provenance: NQ_1S_V2 digest matches | PASS | `research/datasets/NQ_1S_V2.yaml:8` `logical_digest: 9e7aecb7a2910b4402a6cb4f34cc2f6deb5df19d0e889b2c696cf4f844292c64` equals `compiled_plan.json` stream digest and packet `instruments.NQ.dataset_digest` | `readiness.json` `R1_NQ`: "digest 9e7aecb7a291 bytes verified" | none |
| No study Python under study directory (tier-2, zero-code requirement) | PASS | `Glob **/*.py` under `studies/v2_shape_a_flip_180s` returned no files | `readiness.json` invariant list / packet `invariants` includes "no study Python for a tier-2 study" | none |
| Model integrity: lightgbm train mode, explicit params + random_state | PASS | `study.yaml:64-66` and packet `model.params`: `family: lightgbm`, `max_depth:3, num_leaves:7, learning_rate:0.03, min_data_in_leaf:100, n_estimators:200, n_jobs:1, deterministic:true, random_state:42`. No model arms declared (`model.arms: []`), so the arm-delta integrity checks (identical fit/prediction identity, feature variance) in the packet's model-integrity guidance are NOT APPLICABLE — this is a single-arm study. | — | none |
| Deliverables-by-stage reachability (packet's own list) | PASS | Spot-checked artifacts referenced above (`compiled_plan.json`, `audit/frozen_execution_manifest.json`, `artifacts/experiment_authorization.json`, `audit/readiness.json`, `audit/preflight.json`, `audit/status.json`, `_work/controller/test_summary.json`) all exist at declared paths and are non-empty. Downstream stage artifacts (`fit`, `analyze`, `close`, `smoke`, partitions, merged data) were not independently re-derived here since this pass audits governance/lifecycle state, not the study's data outputs — no re-run trigger observed. | — | none |

## Referred to lookahead-auditor
None — no undeclared look-ahead observed; causality is already CLEAR under a distinct auditor identity (`lookahead-auditor`, `audit/status.json`).

## Blocking verdict
CLEAR

Every lifecycle artifact examined (frozen execution manifest, readiness, preflight, causal status, test summary, experiment authorization) declares and reconciles to the same execution composite `b7792ad8515f0dd6f1f74a7546db9a9c86fba2ae90345cf27498600ac384b443`, `plan_sha256` and `spec_sha256` are identical across the compiled plan, the audit packet, and the frozen manifest, chronology and the model's tuning-only year-role table are disjoint with no double use, the declared label column and entry reference are present and executable in the compiled plan, the NQ_1S_V2 dataset digest matches its source definition, no study Python exists, and lightgbm model params including `random_state` are explicit. No governance violation was found.

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "contract", "study": "v2_shape_a_flip_180s", "auditor": "contract-checker", "audited_execution_composite_sha256": "b7792ad8515f0dd6f1f74a7546db9a9c86fba2ae90345cf27498600ac384b443", "critical": 0, "warning": 0, "note": 1}
<!-- AUDIT_SUMMARY_V2_END -->
