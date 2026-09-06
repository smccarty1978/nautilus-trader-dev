# CONTRACT AUDIT pass 01 — `controlled_feature_family_180s`

Auditor `contract-checker:003_contract_audit_179cb047` · composite `da3d3ab4ee9bcd7e8c5987763e603ce89d8fb984252ebca9f3fccb6876325540` · packet `audit_packet_contract.json` (v2) · brief 003.

Gate facts cited, not re-derived: preflight CLEAR 8/8 (`leaked_outcome_columns=[]`), readiness PASS (R1/R3/R5/R8/R9/R10), tests PASS 116/0, controller `NEEDS_CONTRACT_AUDIT` with `execution_composite == current == plan/spec` fingerprints, causal audit CLEAR under a distinct identity (`lookahead-auditor:001_causal_audit_2e1d03e5`). Deliverables for every stage that has run exist (brief §1 table). A V2 study has no `config/deliverables_contract.json`; `packet.deliverables_by_stage` is the contract and was consumed as given.

## Checklist subset (C4, D, E)

| Requirement | Verdict | Evidence | Remediation |
|---|---|---|---|
| **C4** walk-forward does not refit on data overlapping the test window | PASS | `packet.model.validation.month_folds`: 9 folds, each `fit_months` = the 3 calendar months strictly preceding its single `validation_months` entry; all inside 2024. `tuning_years: []`, `final_train_validation_years: []`, `max_trials: null` → no tuning surface. | — |
| **C4** selection seals authenticate their own selected result | PASS (with NOTE 2) | No selection exists to seal: `research_decision.yaml:3` predeclares four fixed arms compared pairwise against the declared control, "No combined arm. No tuning. No feature selection." `primary_metric: null` is consumed only by the tuning objective (`research_workflow/tuning.py:155`) and the `validation.model_selection.*` winner rule (`research_workflow/model_selection.py:406`), neither of which this protocol (`validation.walk_forward_months`, `max_trials: null`) invokes. | — |
| **C4** promotion gates implement every frozen check | PASS | 2025 (`dev`/`oos`) cannot be collected at all until a TRAIN freeze exists and is bound to the current authorization: `research_workflow/experiment.py:254-257` requires `assert_oos_open` plus `train_freeze_sha256 == freeze.freeze_sha256`; `experiment.py:284-294` fails closed on a missing or unbound freeze. Freeze payload must carry `feature_sets, preprocessing_hash, model_hashes, thresholds, deciles` (`experiment.py:267-270`). | — |
| **D1** offline features match live `on_bar` | PASS | No second implementation exists to skew. All 35 declared features resolve to one runtime provider each via the generic adapters (`packet.binding_proof`, all `bound: true`; R5_binding_proof pass), and `packet.columns.derived` is empty — no post-hoc pandas-side recomputation. Study declares zero study Python (`packet.study_python`, R10 pass). | — |
| **D2** filter cascades trained on the post-filter distribution | NOT APPLICABLE | No cascade: one collected population, four arms fit on the same rows; `outcome.arms: []`, `primary_arm: null`. | — |
| **D3** ONNX exported from the validated model object | NOT APPLICABLE | No export, no serve leg; `model.mode: "train"`, deliverables end at `artifacts/experiment_models.json` / `experiment_analysis_v2.json`. | — |
| **D4** deterministic encodings, imputation, feature ordering | PASS | `model.params`: `deterministic: true`, `n_jobs: 1`, `random_state: 42`. Each arm declares an explicit ordered feature list; model/feature-order binding is a hard gate (`scripts/check_model_binding.py`, §6.2). No categorical columns declared — all 35 features are continuous tracker outputs. | — |
| **E1/E2** bar subscriptions and `BarType` match the loaded data | PASS | Streams `nq_1m` / `nq_1s` only (`compiled_plan.availability.rows`), instrument `NQ` / dataset `NQ_1S_V2_GLOBEX` digest `9e7aecb7…`; R1_NQ and R3_session_table pass. `regime_bar_5m` is a calendar bucket over `nq_1m`, not a separate 5m subscription. | — |
| **E3** fill model / no `LIMIT` auto-fill | NOT APPLICABLE | Classification study: no orders, no venue, no PnL. Label is `target_flip_within_horizon`; `outcome.contract: "label"`. | — |
| **E4** entry at the next bar's open | NOT APPLICABLE | Same reason; no entry is simulated. Checkpoint visibility is causal-auditor scope and was CLEARed there. | — |
| **E5** indicator warmup respected | PASS | `chronology.warmup`: `days_before_partition: 5` with `candidate_emission: false` and `target_generation: false` — warmup bars prime trackers but emit no candidates and no labels. | — |

## Lifecycle state

Composite current (`compiled_plan.json:768-769` closure `da3d3ab4ee9b`, 90 files; R9 pass; controller fingerprints agree) · preflight ran all 8 required checks · readiness R1–R10 pass · causal and contract identities distinct · authorization disjoint (`train {2024}` / `oos {2025}` / `prohibited {2021,2022,2023,2026}`) and consistent with `chronology.train/dev/prohibited` · outcome columns are labels only (`target_flip_within_horizon`, `disposition`, `censored`, `censor_reason`, `resolved_at_ts`, … appear in `columns.observation` and in **no** arm feature list; preflight `leaked_outcome_columns=[]`). Seal, TRAIN freeze, reconcile and `forward_outcome_manifest.json` rows are NOT APPLICABLE at this stage — those artifacts belong to stages that have not run; each is fail-closed downstream.

`chronology.authorized_dates: ["2024-03-01"]` alongside `train: [2024]` is not a scope contradiction: the spec-level date list bounds smoke/unauthorized runs (`scripts/validate_smoke.py:138-145`, `backtests/nt_runtime/data_plan.py:91-118`), while a governed partition run overrides it with the signed authorization's own date list (`backtests/nt_runtime/modes/collect.py:86-94`, `data_plan.py:105`). Full-year 2024 collection is therefore reachable.

## Findings

- **NOTE 1 — the year-role table omits the TRAIN year.** `packet.year_role_table` and `model.validation.year_role_table` list only `2025: dev_oos` and the four prohibited years; 2024 has no row. The fact is declared twice elsewhere (`chronology.train`, `experiment_authorization.json`), so nothing is ambiguous in practice, but the artifact whose purpose is to make year double-use visible is incomplete. Remediation: emit a `{"year": 2024, "role": "train"}` row.
- **NOTE 2 — no predeclared comparison metric or multiplicity handling.** Three pairwise deltas (B, C, D vs A) will be read off one held-out window; `primary_metric` is null (mechanically correct here) and `terminal_decisions` is empty by design (`research_decision.yaml:6,10-12`). The reported metric and the direction of the conclusion are therefore chosen after the artifacts exist. Remediation: the analysis worker must name the metric and state all three deltas, not only the largest.
- **NOTE 3 — `dev_oos` is one window doing two jobs.** 2025-01-01→2025-03-31 is the only non-TRAIN window and is labelled both `dev` (chronology) and `oos` (authorization). Legitimate as a single-use confirmation because model fitting is confined to 2024 folds and `assert_oos_open` freezes TRAIN first; it would stop being legitimate if any arm were re-fit or re-thresholded after 2025 is opened.
- **NOTE 4 — declared-but-inert resolution rule, and TRAIN-only population parity.** `outcome.semantics.resolution_precedence` lists `GAP` while `max_gap_ns` is null on a `flip` kernel, so that rule cannot fire. Separately, `analysis.gate.population_parity` (`compiled_plan.json:14-42`, expected_total 450973, one predeclared 2024-12-31 exclusion) has `source: "train"` — the 2025 population has no external reference and is unverified against any parent authority.

## Referred to lookahead-auditor

None. No look-ahead surface outside C4/D/E was reached.

## Blocking verdict

**CLEAR.** Every C4, D and E rule is PASS or NOT APPLICABLE with cited evidence; no CRITICAL and no WARNING. The four findings are disclosures: an incomplete year-role table, an unstated comparison metric, a single window serving as both dev and OOS, and one inert outcome rule plus a parity gate that covers TRAIN only. None blocks; NOTE 2 and NOTE 3 are the conditions the analyze stage must honour for the arm deltas to be reportable as results rather than hypotheses.

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "contract", "study": "controlled_feature_family_180s", "auditor": "contract-checker:003_contract_audit_179cb047", "audited_execution_composite_sha256": "da3d3ab4ee9bcd7e8c5987763e603ce89d8fb984252ebca9f3fccb6876325540", "critical": 0, "warning": 0, "note": 4}
<!-- AUDIT_SUMMARY_V2_END -->
