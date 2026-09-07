# CONTRACT AUDIT pass 01 — `es_180s_model_c_portability`

- auditor: `contract-checker:003_contract_audit_c32ade61`
- audited execution composite: `da3d3ab4ee9bcd7e8c5987763e603ce89d8fb984252ebca9f3fccb6876325540`
- phase B, pre-execution (compile / prepare / readiness / preflight / tests have run; collection, fit, freeze, oos, seal have not)
- surface: `audit_packet_contract.json` (sha256 `0f99a9b5…`, packet_version 2) + brief gate facts; two targeted reads outside the packet, cited below

## Requirements

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| Deliverables declared for every stage that ran exist | PASS | brief §1 table: 6/6 present, non-zero bytes; `packet.deliverables_by_stage` is the V2 contract (no V1 `config/deliverables_contract.json` expected) | tests PASS 116/0 @ composite | — |
| Audited composite is current | PASS | controller fingerprints `execution_composite=current=da3d3ab4ee9b`; R9_closure_current=pass | readiness PASS | — |
| Preflight ran every required check and passed | PASS | 8/8 required PASSED; `leaked_outcome_columns=[]` | — | — |
| Readiness passed | PASS | overall PASS; R1_ES, R3_session_table, R5_binding_proof, R8_host_boundary_lint, R9, R10 pass | — | — |
| Causal and contract identities distinct | PASS | causal `lookahead-auditor:002_causal_audit_857890b1` vs. this report's auditor id | — | — |
| TRAIN/OOS/prohibited years disjoint; authorization not stale | PASS | `packet.chronology` train [2020-2023] / dev [2024] / prohibited [2025, 2026] == `experiment_authorization.json` train_years/oos_years/prohibited_years; no third role declared | — | — |
| No study Python for a tier-2 study | PASS | `packet.study_python.python_files=[]`, `exception=null`; R10 pass | — | — |
| Every declared primitive maps to exactly one runtime implementation | PASS | `packet.binding_proof`: 16/16 `bound:true`; the two `feature.regime_efficiency` entries are timeframe aliases of one provider (`generic_structural_geometry`), which is the canonical identity, not a duplicate provider | R5_binding_proof=pass | — |
| Declared feature surface == the study's stated 13-feature surface | PASS | `packet.columns.features` = 13 entries | — | — |
| Cell subset column is produced by the collection | PASS | cells subset on `regime_direction`, declared in `packet.columns.metadata` (`ref regime_1m.dir`) and in `columns.observation` | — | — |
| Outcome columns are labels, never features | PASS | `target_flip_within_horizon`, `disposition`, `censored`, `flip_ts`, `resolved_at_ts` appear only under `columns.observation`; `features` carries none of them. `rolling_300s_giveback_atr` is a causal input, correctly not rejected | preflight `leaked_outcome_columns=[]` | — |
| **C4** no refit on data overlapping the test window; selection seals authenticate their own result | PASS | fit is TRAIN 2020–2023 only; 2024 (`dev`) is consumed by the `oos` stage alone. `model.validation` is null (`compiled_plan.json:997`) → no early-stopping/validation split, `search_space` empty → no tuning, `arms: []` → no arm selection. Nothing selects on 2024, so the two-role split cannot double-use it | — | — |
| **C4** promotion gates implement every frozen check | NOT APPLICABLE | no promotion/selection seal declared; `packet.identity.seal` is `{}` — the seal stage runs after both audits | — | — |
| **D1** offline features match live `on_bar` | NOT APPLICABLE | observational collection study; no live strategy is deployed. Features are produced once, inside the NT host, by the bound providers above | R8 host_boundary_lint=pass | — |
| **D2** filter cascade trained on post-filter distribution | NOT APPLICABLE | no filter cascade / prefilter declared | — | — |
| **D3** ONNX export from the validated model object | NOT APPLICABLE | `family: model.lightgbm`, `mode: train`; no export declared | — | — |
| **D4** deterministic encodings, imputation, feature ordering | PASS | all 13 features are numeric (no categorical encoding); feature order fixed by `columns.features`; `random_state: 42`, `n_estimators` fixed per cell, no `search_space` → fit is reproducible. Model/feature-order binding is a hard gate (`scripts/check_model_binding.py`) that runs at fit, not yet | — | re-check at fit stage |
| **E1** bar subscriptions match the data client's bar type | PASS | one declared instrument (`ES`, venue `XCME`, `ES_1S_V2_GLOBEX`, digest `9f38a41e…`); all trackers bound against that host | R1_ES=pass, R5=pass | — |
| **E2** `BarAggregation`/`PriceType` match the data loaded | PASS (gate-derived) | the packet does not carry the `BarType` strings; the verdict rests on R1_ES, the deterministic data-readiness gate over the declared subscriptions, plus the single-dataset declaration | R1_ES=pass | — |
| **E3** fill model; `LIMIT` does not auto-fill at signal price | NOT APPLICABLE | no orders, no venue fill simulation — the study emits observations and labels, no trades | — | — |
| **E4** entry is not assumed on the just-closed bar | PASS | `outcome.entry_reference: "next_bar_open"` (`compiled_plan.json:1008`); `flip.inclusive_start: true` with `horizon_ns: 180000000000` (180 s) measured from that reference | — | — |
| **E5** indicator warmup respected | PASS | `chronology.warmup`: `days_before_partition: 5`, `candidate_emission: false`, `target_generation: false` — warmup days load state but emit neither candidates nor targets | — | — |
| Model-integrity: reported arm delta declares its verification | NOT APPLICABLE | `arms: []`; the study reports no arm delta. Direction cells are a population split, not an added feature block | — | — |
| Freeze-before-OOS, `derivation_population: "train"`, partition reconciliation, `forward_outcome_manifest.json` self-description | NOT APPLICABLE (this pass) | the freeze, oos, reconcile and collection stages have not run; these are re-audited at the post-execution composite | — | — |

## Findings

**NOTE-1 — the audit packet's `model` block omits `cells`, hiding the per-direction fit plan from a packet-bounded auditor.**
`_model_summary` projects only `mode`/`family`/`params`/`arms`/`validation` (plus `models` in score mode and `search_space` when present) — `research_workflow/audit_packets_v2.py:88-89`. This study fits **two** direction cells with distinct hyperparameters (`compiled_plan.json:964-985`: `LONG` `learning_rate 0.0394 / n_estimators 100`, `SHORT` `learning_rate 0.0289 / n_estimators 200`, over shared `max_depth 5 / num_leaves 4`). From the packet alone the study looks like a single union-surface model with one param set, which is exactly the shape the platform now refuses. Graded NOTE, not WARNING: the omission is an inherited limitation of main's packet builder (unchanged by this study branch), and the hidden content was recovered in this pass from the authoritative `compiled_plan.json` and found well-formed and consistent with the declared description ("fixed direction-specific hyperparameters carried over from the NQ parent"). No unverified invariant remains for this study. Smallest remediation (platform, not this study): carry `cells` in `_model_summary`.

**NOTE-2 — `GAP` is an inert element of the declared `resolution_precedence`.**
`outcome.semantics.resolution_precedence` is `[SESSION_END, GAP, BARRIER_TOUCH, HORIZON_EXPIRY]` with `max_gap_ns: null` on a `flip` kernel. Gap resolution is barrier-only, so the reachable terminals are `SESSION_END` (with `session_end_censoring: true`), the flip itself, and `HORIZON_EXPIRY`; `censored`/`censor_reason` carry the disposition. Disclosure only — no declared terminal label is unreachable in a way the study's conclusion depends on.

**NOTE-3 — `year_role_table` is null.**
It is read from `model.validation` (`audit_packets_v2.py:152`), which this plan sets to null, so the null is structural rather than an omission by the study. With exactly two year roles and no tuning or selection call touching 2024, the `chronology` block is itself unambiguous and a call-by-call table adds nothing here. Worth restoring the moment any tuning or final-validation role is added.

## Referred to lookahead-auditor

None. Causality (A, B, C1–C3, F, G, H) — including the 1m/5m derivation from the 1 s dataset — was cleared at this same composite by `lookahead-auditor:002_causal_audit_857890b1` (critical 0 / warning 0 / note 5).

## Blocking verdict

**CLEAR.** Every deliverable declared for a stage that has run exists; the audited composite is current and matches the controller, preflight, readiness and test fingerprints; the chronology is disjoint and matches the authorization, with nothing in the compiled plan able to select on 2024; the feature surface is 13 declared, numeric, forward-outcome-free columns bound one-to-one to runtime implementations; and E4/E5 are satisfied by `next_bar_open` and a non-emitting 5-day warmup. Three NOTEs are disclosure-only. Requirements that depend on stages not yet run — freeze-before-OOS, threshold `derivation_population`, partition reconciliation, outcome-manifest self-description, and the `check_model_binding.py` gate — are recorded NOT APPLICABLE for this pass and must be re-audited at the post-execution composite; this verdict does not vouch for them.

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "contract", "study": "es_180s_model_c_portability", "auditor": "contract-checker:003_contract_audit_c32ade61", "audited_execution_composite_sha256": "da3d3ab4ee9bcd7e8c5987763e603ce89d8fb984252ebca9f3fccb6876325540", "critical": 0, "warning": 0, "note": 3}
<!-- AUDIT_SUMMARY_V2_END -->
