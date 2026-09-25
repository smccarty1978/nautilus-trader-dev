# CONTRACT AUDIT — pass 03 — `controlled_feature_family_180s`

- auditor: `contract-checker:012_contract_audit_23f8b436`
- audited execution composite: `14b13abb23e53f3d415ecd1a54726baa03381e5772ef5c85fe1c7bc65c51ce2d`
- plan `b845b9c35d75` · spec `bcc1f0fcd49f` · source commit `823cd0cf` · packet_version 2
- executable surface vs. pass 02: **0 changed / 0 added / 0 removed** closure files (90 files, same composite). The delta `ca988236..823cd0cf` is study-side only: `research_decision.yaml`, regenerated `compile_card.json` / `experiment_authorization.json` / `frozen_execution_manifest.json` (composite + timestamps), and audit records.

## 1. Adjudication of pass 02 findings (`contract-checker:009_contract_audit_d40607ee`)

| # | Adjudication | Evidence |
|---|---|---|
| **WARNING 1** — TRAIN-sourced analysis, so no arm is scored on the declared 2025 window | **FIXED** | Pass 02's remediation option 1 was taken verbatim, and exceeded: `research_decision.yaml:17-67` (commit `99f06ed2`) declares `pass_scope.id: TRAIN_ONLY_CONTROLLED_SCREEN`, `opens_dev_oos: false`, a call-by-call `year_roles` table (2024 train / 2025 dev_oos **unopened** / four prohibited), `forward_evidence_available` limited to the nine 2024 walk-forward month folds, three explicit `prohibited_claims`, and an `admissible_conclusion_scope` that makes a positive arm delta a candidate rather than a confirmation. |
| — mechanism claim in that disclosure | **VERIFIED INDEPENDENTLY** | `research_workflow/lifecycle_v2.py:1205-1211`: a plan declaring `analysis:` is analysed by that pipeline and **returns at :1211**, before `assert_oos_open` (:1212-1213) and before the OOS scoring block (:1214+). With `source != "oos"` the frame is the TRAIN partition (:1154-1156). The disclosure's rejection of `source: "oos"` as the alternative is also correct on the code: that branch calls `assert_oos_open` (:1148-1150) but still returns at :1211, so it restores neither freeze-canonical binding nor `authenticate_model` nor `oos_metrics`. |
| NOTE 1 — year-role table omits TRAIN 2024 | **NOT FIXED (still NOTE)** | `packet.year_role_table` and `packet.model.validation.year_role_table` still carry the same 5 rows (2025 `dev_oos` + 4 `prohibited`); no `{"year": 2024, "role": "train"}`. Now partially compensated outside the packet by `research_decision.yaml:44-50`. Carried below. |
| NOTE 2 — no predeclared comparison metric / multiplicity | **NOT FIXED (still NOTE)** | `packet.model.validation.primary_metric: null`; `research_decision.yaml:6` `terminal_decisions: {}` (unchanged by the pass-scope commit, which only appended). Carried. |
| NOTE 3 — inert `GAP` precedence + TRAIN-only population parity | **PARTIALLY FIXED (still NOTE)** | Parity half is now *declared*, not fixed: the TRAIN-only reference frame is disclosed at `research_decision.yaml:38-43` and is intended. `GAP` half unchanged: `packet.outcome.semantics.resolution_precedence` still lists `GAP` with `max_gap_ns: null` on a `flip` kernel — inert by construction, not a defect. Carried. |
| NOTE 4 — machine-local absolute path in `artifacts/arm_delta_integrity.json` | **NOT FIXED (still NOTE)** | `research/analysis/diagnostic_ops.py` is unchanged at this composite (0 closure files changed), so `"models_manifest": str(manifest_path)` still lands in the persisted payload. The supplying context is correctly excluded from plan identity (`lifecycle_v2.py:1164-1171`), so this is reproducibility hygiene only. Carried. |

Pass 02's blocking status was retired study-side (`audit/contract_status_pass_02_retired.json`) on the stated ground that a study-contract disclosure cannot change the execution composite, so the derived `AUDIT_BLOCKER` could never clear itself. That reasoning is sound and the pass-02 report was kept unchanged as the record; this pass adjudicates the remediation independently, on the artifacts, not on the retirement note.

## 2. New findings this pass

**None blocking.** No new CRITICAL and no new WARNING. The executable surface did not move, and the single study-side change is the disclosure this pass was convened to adjudicate.

### Carried notes (non-blocking)

- **NOTE 1** — emit `{"year": 2024, "role": "train"}` in `model.validation.year_role_table`. This matters slightly more now: the packet is what a downstream worker reads, and the pass-scope declaration that bounds the conclusion lives only in `research_decision.yaml`. The year-role table is the natural place for it to surface.
- **NOTE 2** — the analysis worker must name the comparison metric and state all three pairwise deltas (B, C, D vs `A_BASELINE_13`), not only the largest, and must honour `pass_scope.prohibited_claims`. Those claims are a declaration, not a mechanical gate; nothing in the pipeline refuses a forward-framed conclusion.
- **NOTE 3** — inert `GAP` precedence rule; population parity is TRAIN-only by design (2025 has no external reference in this pass).
- **NOTE 4** — record `models_manifest` relative to `study_dir` so `arm_delta_integrity.json` is byte-reproducible across machines.

## 3. Requirement table

| Requirement | Verdict | Evidence | Remediation |
|---|---|---|---|
| Deliverables for every stage that ran exist | PASS | brief §1: 6/6 present, non-zero bytes. V2 study — `packet.deliverables_by_stage` is the contract; no `config/deliverables_contract.json` expected | — |
| Audited composite is current | PASS | R9_closure_current=pass; controller `execution_composite == current == 14b13abb23e5`; `worktree_dirty_paths: []` | — |
| Preflight ran every required check | PASS | 8/8 PASSED, `leaked_outcome_columns=[]` @ `14b13abb23e5` | — |
| Readiness passed | PASS | R1/R3/R5/R8/R9/R10 pass | — |
| Causal and contract identities distinct | PASS | `lookahead-auditor:008_causal_audit_6dd5120e` vs. this auditor; three distinct contract identities across passes 01–03 | — |
| Seal binds report bytes to the audited composite | PENDING BY DESIGN | `packet.identity.seal` still binds `da3d3ab4ee9b` / `contract-checker:003`; `seal` follows `contract_audit` | re-seal must bind this report at `14b13abb23e5` |
| TRAIN/OOS/prohibited disjoint; authorization current | PASS | train `[2024]` · dev/oos `[2025]` · prohibited `[2021,2022,2023,2026]`; regenerated at the current composite; `authorized_dates` `2024-03-01` inside TRAIN | — |
| Declared pass scope matches the executable path | PASS | `research_decision.yaml:17-67` vs. `lifecycle_v2.py:1148-1156,1205-1213`; the declared TRAIN-only screen is exactly what the code performs | — |
| C4 — walk-forward does not refit on the test window | PASS | 9 folds, fit 3 months → validate the next, disjoint (`packet.model.validation.month_folds`); final fit confined to `[2024]` | — |
| C4 — promotion gate implements every frozen check | PASS | `analysis.gate.arm_delta_integrity` runs as a pipeline step and raises `ANALYSIS_ARM_DELTA_INTEGRITY_FAILED`, aborting `analyze` before artifacts are written (`diagnostic_ops.py:924-926`) | — |
| C4 — the gate covers the reported deliverable | PASS (was WARNING 1) | gate scope is the 2024 TRAIN population, and the deliverable is now declared to be a 2024-only screen — scope and vouching now coincide | — |
| D1 / D3 — offline-vs-live parity, ONNX export | NOT APPLICABLE | no live strategy, no export (`model.family: model.lightgbm`, `mode: train`) | — |
| D2 — cascade trained on post-filter distribution | NOT APPLICABLE | no filter cascade; four independent arms on one collected population | — |
| D4 — deterministic ordering / encoding / imputation | PASS | ordered inputs + `feature_contract_sha256`; R5_binding_proof=pass; `deterministic:true, n_jobs:1, random_state:42` | — |
| Frozen feature sets carry no forward-outcome columns | PASS | preflight `leaked_outcome_columns=[]`; `assert_causal_feature_surface` on arm columns | — |
| E1 / E2 — bar subscriptions and `BarType` match the data | PASS | streams `nq_1s` / `nq_1m` on `NQ_1S_V2_GLOBEX` digest `9e7aecb7a291`; session digest `e577a36165ab` over 6 tables | — |
| E3 / E4 — fill model, next-bar entry | NOT APPLICABLE | collection + classification study; no simulated venue, no order submission | — |
| E5 — indicator warmup respected | PASS | `chronology.warmup`: 5 days, `candidate_emission: false`, `target_generation: false` | — |
| Every declared primitive maps to one runtime implementation | PASS | `packet.binding_proof`: 38/38 `bound: true`; all 35 declared feature columns covered | — |
| Model-arm delta integrity declared | PASS | populated / variance / distinct fit identity / distinct predictions enforced per arm per cell | — |
| No study Python (tier 2) | PASS | `packet.study_python.python_files: []` | — |
| Partition reconciliation, TRAIN-freeze-before-OOS, outcome manifest self-description | NOT APPLICABLE (pre-execution) | collection/fit/freeze/oos have not run at this composite | re-check at the post-execution audit |

## Referred to lookahead-auditor

None. Causality was cleared at this composite (`audit/status.json`, CLEAR, critical 0 / warning 0 / note 4) and the executable surface has not moved since.

## Blocking verdict

**CLEAR.** The one blocking finding of pass 02 was a scope defect, not a mechanism defect, and it has been remediated in the place pass 02 named: `research_decision.yaml` now declares this pass a TRAIN-only controlled screen, states call-by-call which year each role touches, bounds the admissible conclusion to 2024, and forbids by name the three forward claims the compiled path cannot support. I verified the disclosure's mechanism claim against `lifecycle_v2.py:1148-1156,1205-1213` rather than accepting it — it is accurate, including its reason for rejecting `analysis.source: "oos"` as a one-line fix. Everything else this study declares is present, current and consistent at composite `14b13abb23e5`: 38/38 bindings bound, 8/8 preflight checks passed, readiness R1–R10 pass, 132/132 tests, no study Python, disjoint year roles. Four non-blocking notes remain, all carried unchanged; the closest to substantive is that `pass_scope`'s prohibited claims are a declaration honoured by the analysis worker, not a gate — the seal and the post-execution audit are where that has to be re-checked against the written conclusion.

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "contract", "study": "controlled_feature_family_180s", "auditor": "contract-checker:012_contract_audit_23f8b436", "audited_execution_composite_sha256": "14b13abb23e53f3d415ecd1a54726baa03381e5772ef5c85fe1c7bc65c51ce2d", "critical": 0, "warning": 0, "note": 4}
<!-- AUDIT_SUMMARY_V2_END -->
