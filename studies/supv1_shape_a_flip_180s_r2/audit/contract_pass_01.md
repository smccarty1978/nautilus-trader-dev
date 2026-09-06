# CONTRACT AUDIT pass 01 — study `supv1_shape_a_flip_180s_r2`

- auditor: `contract-checker:003_contract_audit_0180bf4a`
- audited execution composite: `ee051527aa24c26591c0ef9f22316e4d2015ce6d752cdd8d8b66ea3356997984`
- plan `19a4543583eb` · spec `6afe992b2bcf` · audit packet `e8b8c4c4e67a` (packet_version 2)
- surface: pre-execution (compile → prepare → readiness → preflight → tests have run; collection, fit, freeze, oos, analyze have not)
- deliverables contract consumed: `packet.deliverables_by_stage` (V2; per-study `config/deliverables_contract.json` is the V1 artifact and its absence is not a finding, per brief §1)

## Requirements

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| Audited execution composite is current | PASS | controller card: `execution_composite` = `current` = `ee051527aa24`; readiness `R9_closure_current=pass` (brief §1) | tests PASS 110/0 at the same composite | — |
| Preflight ran every required check and passed | PASS | `audit/preflight.json` 8/8 required PASSED, `leaked_outcome_columns=[]` | — | — |
| Readiness passed (R1/R3/R5/R8/R9/R10) | PASS | `audit/readiness.json` all pass | — | — |
| Causal and contract reviews have distinct identities | PASS | `audit/status.json` auditor `lookahead-auditor:002_causal_audit_c3be3994` (CLEAR) vs this report's `contract-checker:003_contract_audit_0180bf4a` | — | — |
| TRAIN/OOS/prohibited disjoint, authorization fresh | PASS | `artifacts/experiment_authorization.json:5-16` train [2021], oos [2022], prohibited [2023-2026]; `year_role_table` assigns exactly one role per year | — | — |
| Deliverables declared for every stage that ran exist | PASS | brief §1 existence table: 6/6 present, non-zero bytes | — | — |
| No study Python for a tier-2 study | PASS | `packet.study_python.python_files = []`; readiness `R10_zero_study_python=pass` | — | — |
| Every declared primitive maps to exactly one runtime implementation | PASS | `packet.binding_proof`: 3 trackers + 13 features, all `bound: true`, one implementation each; readiness `R5_binding_proof=pass` | — | — |
| Identity columns declared on every row | PASS | `packet.columns.identity` = observation_ts / regime_start_ns / checkpoint_index; `study.yaml:16,25` cadence `index_column` + `anchor_identity` | — | — |
| Outcome columns are labels, never features | PASS | `packet.columns.features` (13) and `packet.columns.observation` are disjoint; `target_flip_within_horizon` appears only as `outcome.label_column`; preflight `leaked_outcome_columns=[]`; guard is a hard gate at fit/freeze (§6.2) | — | — |
| Outcome semantics match the declaration | PASS | `study.yaml:52-57` (event `regime_1m.flipped`, horizon 180s, session_end censor) vs `packet.outcome`: kernel flip, `session_end_censoring: true`, `horizon_end_rule: strict`, `same_bar_rule: ambiguous_censor`, `max_gap_ns: null` (inert on a flip kernel) | — | — |
| Terminal label reachable | PASS | `packet.columns.observation` carries `disposition`, `censored`, `censor_reason`, `resolved_at_ts`, `horizon_end_ts`, `session_close_ts`; both label states plus the censor state are producible by the declared precedence `SESSION_END > GAP > BARRIER_TOUCH > HORIZON_EXPIRY` | — | — |
| **C4** walk-forward does not refit over the test window; selection authenticates its own result | PASS (with NOTE 1) | No selection executes: `study.yaml:63-66` declares no `search_space`, and `research_workflow/tuning.py:tune` has no production caller. 2022 is never fit on | — | — |
| **D1** offline features == live features | PASS | Single production path: the declared providers in `packet.binding_proof` produce TRAIN and OOS identically; readiness `R8_host_boundary_lint=pass`. No live strategy in scope | — | — |
| **D2** filter cascade trained on the post-filter distribution | PASS | One compiled `qualify` predicate (`study.yaml:17-23`) defines the population for TRAIN and OOS alike; no separate pre-filter model exists to skew the distribution | — | — |
| **D3** ONNX export from the validated model object | NOT APPLICABLE | No export declared | — | — |
| **D4** deterministic, identical encodings / imputation / feature order | PASS | `model.params`: `deterministic: true`, `n_jobs: 1`, `random_state: 42`; feature order is the frozen ordered `packet.columns.features` list under `plan_sha256 19a4543583eb`; no categorical encoder declared (13 continuous features); model/feature-order binding is a hard gate (`scripts/check_model_binding.py`, §6.2) | — | — |
| **E1/E2** bar subscriptions match the data client | PASS | `study.yaml:8-13`: streams `NQ_1S_V2 [1s, 1m]`; `regime_1m` 1m, `excursion` 1s, `regime_bar_5m` buckets 1m bars to 5m — no unsubscribed bar type; dataset digest `9e7aecb7` and `R1_NQ=pass` | — | — |
| **E3** fill model / LIMIT auto-fill | NOT APPLICABLE | Label-collection study; no orders, no simulated venue | — | — |
| **E4** entry at the next bar's open | NOT APPLICABLE | No order submission. Observation-time causality is `lookahead-auditor` scope (CLEAR at this composite) | — | — |
| **E5** indicator warmup respected | PASS | `packet.chronology.warmup`: `days_before_partition: 5`, `candidate_emission: false`, `target_generation: false`; `study.yaml:19` additionally requires `regime_1m.age_s >= 120s` and `features.structural_snapshot_ready` | — | — |
| Model-arm delta integrity declarations | NOT APPLICABLE | `packet.model.arms = []`, `packet.outcome.arms = []` — single model, no delta claimed | — | — |
| Seal binds report bytes to the audited composite | NOT APPLICABLE (pass 01) | `packet.identity.seal = {}`; the seal stage runs after this audit | — | — |
| TRAIN freeze before any OOS artifact; thresholds `derivation_population: "train"`; partitions reconcile; outcome manifest self-describing | NOT APPLICABLE (pre-execution) | freeze/collection/oos stages have not run; each is an enforced gate at its stage (§6.2) | — | — |

## Year-role call table (every governed call that will touch a year)

| Stage / call | Years touched | Role |
|---|---|---|
| collection (train partition) | 2021 + 5 warmup days before | TRAIN |
| fit (`artifacts/experiment_models.json`) | 2021 | TRAIN |
| freeze (thresholds, deciles) | 2021 | TRAIN only |
| oos collection + scoring, analyze | 2022 | dev_oos, read-once |
| — | 2023, 2024, 2025, 2026 | prohibited, never touched |

No year carries two roles. `tuning_years: [2021]` is inside TRAIN by platform design (`research_workflow/tuning.py:3-5`), so it is not a second role for 2021.

## Findings

**NOTE 1 — a declared validation protocol that nothing executes.** `study.yaml:66` declares `validation: {protocol: model_selection.random, tuning_years: [2021], final_train_validation_years: []}`, and `packet.model.validation` carries it forward. No model selection can occur: no `search_space` is declared (the compiler only requires the protocol in the reverse direction — `research_workflow/grammar/compiler.py:1146` — never the converse), and `research_workflow/tuning.py:tune` has no production caller (only tests and `artifacts/platform_v2/redteam/...`). The fit will therefore use `model.params` verbatim; nothing is tuned, and no `artifacts/tuning_trials.json` will exist. This changes no result, but no downstream artifact or report may describe these hyperparameters as tuned or validated. Latent trap if it is ever wired: `walk_forward_folds([2021])` returns `[]` (`research_workflow/tuning.py:79`, `if i > 0`), so a single tuning year yields zero folds and `tune` would raise `TUNING_NO_COMPLETE_TRIAL`. Smallest remediation: drop the `validation:` block, or add a `search_space` **and** a second tuning year.

**NOTE 2 — the dev year and the OOS year are the same year, with no reserved final validation.** `study.yaml:60` `dev: [2022]` compiles to `oos_years: [2022]` and the single role `dev_oos`; `final_train_validation_years: []`. With one model and no selection this is a single, legitimate read of 2022 — but the study has no spare out-of-sample year. Any re-fit, threshold change or feature change informed by a 2022 result consumes the only OOS year. Smallest remediation: treat 2022 as read-once and require a fresh authorization for any post-OOS iteration.

**NOTE 3 — warmup reaches into days with no declared role.** `days_before_partition: 5` pulls late-2020 bars before TRAIN 2021 and late-2021 bars before OOS 2022. Both are safe: `candidate_emission: false` and `target_generation: false` mean warmup days emit no candidates and no labels, so no undeclared-role row enters a fit. Recorded as a disclosure, not a defect.

## Referred to lookahead-auditor

Nothing new. Observation-time and label causality were cleared at this composite (`audit/status.json`, critical 0 / warning 0 / note 3).

## Blocking verdict

**CLEAR.** Every requirement applicable to the stages that have run is `PASS` or `NOT APPLICABLE`; no `FAIL` and no `NOT VERIFIED` blocking requirement. Declarations and runtime bindings agree (13 features, 3 trackers, one implementation each), the chronology assigns exactly one role per year with TRAIN/OOS/prohibited disjoint, the outcome is declared as a label and is absent from the feature surface, and the deliverables declared for compile/prepare/readiness/preflight/tests all exist at the audited composite. The three findings are disclosures: an inert validation-protocol declaration, a single dual-purpose dev/OOS year, and role-free warmup days that emit nothing. Freeze/OOS/threshold and partition-reconciliation requirements are unverifiable at this phase and must be re-audited after execution.

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "contract", "study": "supv1_shape_a_flip_180s_r2", "auditor": "contract-checker:003_contract_audit_0180bf4a", "audited_execution_composite_sha256": "ee051527aa24c26591c0ef9f22316e4d2015ce6d752cdd8d8b66ea3356997984", "critical": 0, "warning": 0, "note": 3}
<!-- AUDIT_SUMMARY_V2_END -->
