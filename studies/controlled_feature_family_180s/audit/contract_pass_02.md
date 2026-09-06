# CONTRACT AUDIT — pass 02 — `controlled_feature_family_180s`

- auditor: `contract-checker:009_contract_audit_d40607ee`
- audited execution composite: `14b13abb23e53f3d415ecd1a54726baa03381e5772ef5c85fe1c7bc65c51ce2d`
- plan `b845b9c35d75` · spec `bcc1f0fcd49f` · source commit `ca988236` · packet_version 2

## 1. Prior findings (pass 01, `contract-checker:003_contract_audit_179cb047` @ `da3d3ab4ee9b`)

| # | Adjudication | Evidence |
|---|---|---|
| NOTE 1 — year-role table omits TRAIN 2024 | **NOT FIXED** | `packet.year_role_table` and `model.validation.year_role_table` still carry 5 rows (2025 dev_oos + 4 prohibited) at composite `14b13abb23e5`; no `{"year": 2024, "role": "train"}` row. Carried as NOTE 1 below. |
| NOTE 2 — no predeclared metric / multiplicity | **PARTIALLY ADDRESSED** | Integrity half is now executable: `analysis.gate.arm_delta_integrity` is declared (`compiled_plan.json:11-18,49-62`) and implemented fail-closed (`research/analysis/diagnostic_ops.py:742-926`, raises `ANALYSIS_ARM_DELTA_INTEGRITY_FAILED` at :925). Metric half unchanged: `primary_metric` still null (`compiled_plan.json:2196`), `terminal_decisions: {}` (`research_decision.yaml:6`). Carried as NOTE 2. |
| NOTE 3 — `dev_oos` is one window doing two jobs | **NOT FIXED, AND ITS STATED BASIS IS INCORRECT** | Pass 01 justified the single window by "`assert_oos_open` freezes TRAIN first". On this study's compiled path that call is never reached — see WARNING 1. Escalated, not double-counted. |
| NOTE 4 — inert `GAP` precedence + TRAIN-only population parity | **NOT FIXED** | `outcome.semantics.resolution_precedence` still lists `GAP` with `max_gap_ns: null` on a `flip` kernel; `analysis.source` still `"train"` (`compiled_plan.json:19`), so `population_parity_vs_parent` compares only 2024 against the parent reference. Carried as NOTE 3. |

## 2. Findings this pass

### WARNING 1 — the declared analysis is TRAIN-sourced, so no arm is ever scored on the declared 2025 window

`compiled_plan.json:19` sets `analysis.source: "train"`. In `research_workflow/lifecycle_v2.py:1205-1211`, a plan that declares `analysis:` is analysed by that pipeline and **returns at :1211**, before `assert_oos_open` (:1212-1213) and before the entire OOS scoring block (:1214-1257: freeze-canonical binding, `authenticate_model`, `oos_metrics`). With `source == "train"` the frame is the 2024 TRAIN partition (:1154-1156).

Concrete failure path: run the lifecycle to completion. The `oos` stage writes `_work/controller/partitions/oos/2025/{candidates,observations}.parquet`; **no stage reads them**. `artifacts/experiment_analysis_v2.json` is written with `authority: "plan.analysis.source=train"` and contains no `oos_metrics`, no `frozen_models_oos`, and no model authentication against `train_experiment_freeze.json`. Both declared gates (`population_parity_vs_parent`, `arm_delta_integrity`) then vouch for TRAIN only: `arm_delta_integrity_gate` rebuilds its population from `models_doc["tuning_years"]` = `[2024]` (`diagnostic_ops.py:818,830-832` mirroring `lifecycle_v2.py:791,907`). The three pairwise deltas B/C/D vs A would be read off 2024 walk-forward fold metrics while `research_decision.yaml:3` asks for "stable **forward** classification information" and the chronology declares 2025 as the only non-TRAIN window — in-sample family screening presented as forward evidence.

Not adjudicated in the decision contract: `research_decision.yaml` (lines 1-16) nowhere states that 2025 is collected-but-unopened in this pass.

Smallest remediation — either one, not both:
1. Declare in `research_decision.yaml` that this pass is a TRAIN-only controlled screen and 2025 stays unopened, so the analysis worker cannot report a forward claim; or
2. after `freeze`, set `analysis.source: "oos"` so the same two gates and the OOS scoring path run on 2025 (`lifecycle_v2.py:1148-1153`).

### NOTE 4 (new) — machine-local absolute path lands in a declared artifact

`diagnostic_ops.py:920` writes `"models_manifest": str(manifest_path)` — an absolute, operator-specific path — into the payload persisted as `artifacts/arm_delta_integrity.json` (`lifecycle_v2.py:1178-1188`). The context that supplies it is correctly excluded from plan identity (`lifecycle_v2.py:1164-1171`), but the artifact is not byte-reproducible across machines. Remediation: record the path relative to `study_dir`.

### Carried notes

- **NOTE 1** — emit `{"year": 2024, "role": "train"}` in the year-role table; the fact is declared in `chronology.train` and `experiment_authorization.json`, so nothing is ambiguous, but the artifact whose purpose is to make year double-use visible is still incomplete.
- **NOTE 2** — the analysis worker must name the comparison metric and state all three deltas, not only the largest.
- **NOTE 3** — inert `GAP` precedence rule; TRAIN-only population parity (2025 has no external reference).

## 3. Requirement table

| Requirement | Verdict | Evidence | Remediation |
|---|---|---|---|
| Deliverables for every stage that ran exist | PASS | brief §1 table: 6/6 present, non-zero bytes. V2 study — `packet.deliverables_by_stage` is the contract; no `config/deliverables_contract.json` expected | — |
| Audited composite is current | PASS | R9_closure_current=pass; controller `execution_composite == current == 14b13abb23e5` | — |
| Preflight ran every required check | PASS | 8/8 PASSED, `leaked_outcome_columns=[]` @ `14b13abb23e5` | — |
| Readiness passed | PASS | R1/R3/R5/R8/R9/R10 pass | — |
| Causal and contract identities distinct | PASS | `lookahead-auditor:008_causal_audit_6dd5120e` vs this auditor | — |
| Seal binds report bytes to audited composite | PENDING BY DESIGN | `packet.identity.seal` still binds `da3d3ab4ee9b` and `contract-checker:003`; the `seal` stage follows `contract_audit` | re-seal must bind this report at `14b13abb23e5` |
| TRAIN/OOS/prohibited disjoint; authorization current | PASS | train `[2024]` · dev/oos `[2025]` · prohibited `[2021,2022,2023,2026]`; `authorized_dates` `2024-03-01` inside TRAIN | — |
| C4 — walk-forward does not refit on the test window | PASS | 9 folds, fit 3 months → validate the next month, disjoint (`packet.model.validation.month_folds`); fold thresholds are quantiles of the **fit** window's scores applied unchanged to validation (`lifecycle_v2.py:878-882`); final fit confined to tuning years `[2024]` (:907) | — |
| C4 — promotion gate implements every frozen check | PASS | `analysis.gate.arm_delta_integrity` runs as an ordinary pipeline step and raises, aborting `analyze` before any artifact is written (`diagnostic_ops.py:924-926`); it refuses a population it cannot reproduce (:843-852) | — |
| C4 — the gate covers the reported deliverable | **WARNING 1** | gate scope = TRAIN fitted population only | see WARNING 1 |
| D1 / D3 — offline-vs-live feature parity, ONNX export | NOT APPLICABLE | no live strategy and no export in this study (`model.family: model.lightgbm`, `mode: train`) | — |
| D2 — cascade trained on post-filter distribution | NOT APPLICABLE | no filter cascade; four independent arms on one collected population | — |
| D4 — deterministic ordering / encoding / imputation | PASS | `ordered_inputs=arm_cols` and `feature_contract_sha256` over the ordered list (`lifecycle_v2.py:914-915`); `score()` re-verifies canonical bytes before predicting; R5_binding_proof=pass; params `deterministic:true, n_jobs:1, random_state:42` | — |
| Frozen feature sets carry no forward-outcome columns | PASS | `assert_causal_feature_surface(arm_cols)` (`lifecycle_v2.py:862`); preflight `leaked_outcome_columns=[]` | — |
| E1 / E2 — bar subscriptions and `BarType` match the data | PASS | streams `nq_1s` / `nq_1m` bound to `NQ_1S_V2_GLOBEX` digest `9e7aecb7a291`; session reference digest `e577a36165ab` over 6 tables | — |
| E3 / E4 — fill model, next-bar entry | NOT APPLICABLE | collection + classification study; no simulated venue and no order submission | — |
| E5 — indicator warmup respected | PASS | `chronology.warmup`: 5 days before partition with `candidate_emission: false` and `target_generation: false` | — |
| Every declared primitive maps to one runtime implementation | PASS | `packet.binding_proof`: 38/38 `bound: true`; 35 declared feature columns all covered | — |
| Model-arm delta integrity declared | PASS | populated / variance / distinct fit identity / distinct predictions all enforced per arm per cell (`diagnostic_ops.py:883-911`), thresholds recorded in the payload | — |
| No study Python (tier 2) | PASS | `packet.study_python.python_files: []` | — |
| Partition reconciliation, TRAIN-freeze-before-OOS, outcome manifest self-description | NOT APPLICABLE (pre-execution) | collection/fit/freeze/oos have not run at this composite | re-check at the post-execution audit |

## Referred to lookahead-auditor

None. Causality was cleared at this composite (`audit/status.json`, verdict CLEAR, critical 0 / warning 0 / note 4).

## Blocking verdict

**BLOCKED** on WARNING 1. Every mechanical control this study declares is present, current and — for the newly merged `analysis.gate.arm_delta_integrity` — genuinely executable and fail-closed, which closes the "declared gate wired to nothing" risk the prior pass could not test. What is not settled is scope: with `analysis.source: "train"` the analyze stage returns before `assert_oos_open` and before all OOS scoring, so the 2025 window the chronology declares is collected and then read by no stage, and both integrity gates vouch only for 2024. Pass 01 explicitly assumed the opposite. Because the decision contract asks for *forward* information and does not adjudicate a TRAIN-only pass, this must be resolved by a one-line disclosure in `research_decision.yaml` or by moving the analysis to `source: "oos"` after the freeze — not by a redesign. The other four findings are non-blocking hygiene and disclosure.

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "BLOCKED", "audit_type": "contract", "study": "controlled_feature_family_180s", "auditor": "contract-checker:009_contract_audit_d40607ee", "audited_execution_composite_sha256": "14b13abb23e53f3d415ecd1a54726baa03381e5772ef5c85fe1c7bc65c51ce2d", "critical": 0, "warning": 1, "note": 4}
<!-- AUDIT_SUMMARY_V2_END -->
