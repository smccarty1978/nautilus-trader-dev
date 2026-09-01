<!-- AUDIT_SUMMARY_V2_START -->
{"verdict":"CLEAR","audit_type":"contract","auditor":"contract-checker","critical":0,"warning":0,"not_verified":0,"note":4,"study":"regime_transition_target_before_stop_v1","audited_execution_composite_sha256":"4f45256b975f8f3b4ef310f941a00a0efbe16e4c62e5b193e769c8fa4a0b3ea9"}
<!-- AUDIT_SUMMARY_V2_END -->

# Contract Audit — Pass 08 (SEAL authorization only; NOT fitting)

Adjudicates the Phase D modeling-composition repair after the second remediation round.
Ledger note: the last recorded contract entry in `audit/pass_ledger.json` is pass 06
(`8065d438…`); this report is filed as pass 08 per the task packet and audits composite
`4f45256b975f8f3b4ef310f941a00a0efbe16e4c62e5b193e769c8fa4a0b3ea9`. The orchestrator issues
the authenticated status.

## Prior-finding adjudication

### Pass 06 (composite `8065d438`, BLOCKED, 3 CRITICAL) — all RESOLVED

1. **Target authority not enforced at the executable boundary** — RESOLVED.
   `implementation/phase_d_modeling.py:101-112` `_assert_target_authority` runs at
   `run_phase_d` line 269, *before* `out.mkdir` (278), config expansion, closure resolution
   and any `fit_temporal_fold` call. It requires the canonical path
   `_work/train_merged_collection/phase_c2_reconciled_targets.parquet`, recomputes its byte
   SHA and compares to `AUTHORITATIVE_TARGET_SHA256 = 21d598a8…`, and requires both that
   byte SHA and `AUTHORITATIVE_TARGET_LOGICAL_SHA256 = 552690f0…` to appear in
   `artifacts/train_target_authority_reconciliation.json`. Caller `--targets` is refused
   unless it resolves to that same path (`:270-271 PHASE_D_ARBITRARY_TARGET_PATH_PROHIBITED`).
   Tests: `tests/test_phase_d_modeling_driver.py::test_contract_pass06_wrong_target_hash_fails_closed_before_output`
   (asserts `not out.exists()`), `::test_phase_d_rejects_arbitrary_or_missing_authority`.

2. **Governed fit-time hard gates bypassed** — RESOLVED. The driver now imports only
   `from research_workflow.modeling import fit_temporal_fold` (`:24`); `_fit_one` (`:244-249`)
   routes every cell/fold through it. No `research.analysis.modeling.fit_model` import on the
   fit path (`research/analysis/modeling` is used only for `SplitPolicy` / `write_model_manifest`).
   `research_workflow/modeling.py:159 def fit_temporal_fold`. Tests
   `::test_contract_pass06_fit_path_routes_only_through_governed_primitive` (asserts the negative
   imports) and `::test_section9_A_H_I_J_K_full_run` (asserts `_assert_study_open` and
   `assert_gates_satisfied` were invoked).

3. **Incomplete Phase D executable / output contract; missing per-fold log loss** — RESOLVED.
   `config/deliverables_contract.json` now authorizes mode `modeling` with
   `phase_d_modeling_report.json` + `phase_d_model_artifacts.json`, each `mode: "modeling"`;
   the driver writes exactly those two files (`:347-350`). `SPEC.md:44,54-57` renders the same
   `modeling` mode and deliverables; `SPEC.md:15` custom scope lists `phase_d_modeling.py`.
   Per-fold `log_loss` is emitted in both `attempts[].fold_metrics` (`:304`) and
   `validation[fold]` (`:332`). Test `::test_contract_pass06_report_schema_and_per_fold_log_loss`
   checks the report schema keys, `log_loss.metric == "log_loss"` for attempts and validation,
   and deliverables-contract agreement.

### Pass 07 (composite `6adc4485`, BLOCKED, 2 items) — both RESOLVED

1. **R9 ALTERNATE_CATALOG_OPENER_VIOLATION in `implementation/canary_diagnostics.py` +
   `gap_diagnostic.py`** — RESOLVED. Both files are absent from the worktree (direct `Read`
   returns "file does not exist"; a repo-wide `Grep` for `ParquetDataCatalog(` /
   `data/catalog` / `NQ_v0_2020_2026` under `studies/regime_transition_target_before_stop_v1/**`
   returns zero hits inside `implementation/` — only dataset-identity strings in contracts and
   manifests). They are excluded from the frozen closure:
   `audit/frozen_execution_manifest.json` `resolved_execution_file_list` contains only
   `study:implementation/phase_d_modeling.py` and
   `study:implementation/target_before_stop_diagnostics.py`. `audit/readiness.json` R9
   `NO_ALTERNATE_CATALOG_OPENERS` = pass, `overall_status` PASS.

2. **"Phase D.0 target-authority reconciliation artifacts do not exist"** — CONFIRMED SCOPING
   ERROR in pass 07. In this worktree both artifacts are present and internally consistent:
   `artifacts/train_target_authority_reconciliation.json` (status PASS, byte `21d598a8…`,
   target-only logical `552690f0…`, 1,387,411 rows, all mismatch counts 0, C.3 accounting
   `matches_declared_counts: true`, oracle 639/639, `oos_2024_accessed:false`,
   `phase_d_authorization.authorized: true`) and `artifacts/phase_d0_authority_closed.json`
   (`CLOSED_PASS`, `modeling_started:false`). The withdrawn `785d95ee…` hash is preserved only
   as `superseded_reported_hash / UNSUPPORTED`. `experiment_authorization.json` now records a
   repo-relative `study_path` ("studies/regime_transition_target_before_stop_v1"), new
   `authorization_sha256 4611455d…`, TRAIN [2021,2022,2023] / OOS [2024] / prohibited
   [2025,2026] — internally disjoint and matching `study.yaml`, `research_decision.yaml`
   (`chronology` and `phase_d_modeling_protocol`), and the driver constants
   (`phase_d_modeling.py:29-30`).

### Passes 01–05 — CLEAR, nothing to re-adjudicate.

## Compliance

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| `deliverables_contract.json` present, literal, consumed (not reconstructed) | PASS | `config/deliverables_contract.json` authorizes `collect`, `modeling`; modeling → `phase_d_modeling_report.json`, `phase_d_model_artifacts.json`; driver writes exactly those (`phase_d_modeling.py:347-350`). | `test_phase_d_modeling_driver.py::test_contract_pass06_report_schema_and_per_fold_log_loss` asserts contract/engine/SPEC agreement. | — |
| SPEC ↔ study.yaml ↔ research_decision.yaml adherence (baseline, feature-selection mode, arms, chronology, prohibited changes) | PASS | `research_decision.yaml:12-15` train/dev/prohibited; `:22` baseline feature-selection `mode: none`; `:24-33` prohibited 2024/25/26 use; `:38-49` 6 cells + folds + selection. `study.yaml:11,142-167,196-197,219-221` mirror. | `test_section9_D_E/F/G` fix folds and TRAIN-only years. | — |
| 6 modeling cells (LONG/SHORT × SL0_5/SL1_0/SL1_5), expanding folds, candidate_grid, selection_priority | PASS | `study.yaml:144-167` 6 arms, `validation_folds` [2021]→2022 / [2021,2022]→2023, 36-config `candidate_grid`, `selection_priority`; driver `phase_d_modeling.py:34-47,317` mirrors (3·3·2·2=36; sort by `-min_roc_auc,-mean_roc_auc,-mean_pr_auc,std,idx`). | `test_section9_A_H_I_J_K_full_run` (6 cells, 12 distinct SELECTED arms), `test_section9_D_E_temporal_folds_accepted`. | — |
| `execution.modeling_driver_relpaths` + `bespoke.custom_scope` include `implementation/phase_d_modeling.py`; implementation/ holds only the two declared files | PASS | `study.yaml:196-197,219-221`; frozen manifest lists only the two `study:implementation/*.py`; `canary_diagnostics.py`/`gap_diagnostic.py` absent. | driver `run_phase_d:263-265` calls `assert_declared_modeling_drivers` and refuses if `phase_d_modeling.py` not declared. | — |
| Terminal decision labels reachable (POSITIVE / NEGATIVE_SL binary; censor dispositions excluded) | PASS | `phase_d_modeling.py:156-166` binary set = {POSITIVE, NEGATIVE, NEGATIVE_SL}; TIMEOUT/SESSION_END/GAP/AMBIGUOUS/DATA_END excluded; C.3 accounting in reconciliation shows non-zero POS and NEG_SL for all 3 arms. | `test_section9_A_H_I_J_K_full_run` H-branch: TIMEOUT never enters the binary label set, no NaN labels. | — |
| Target artifact self-describing / authenticated before any estimator (C4, D) | PASS | `_assert_target_authority` at `run_phase_d:269` precedes output dir + fit; byte + logical SHA + reconciliation-record cross-check. | `test_contract_pass06_wrong_target_hash_fails_closed_before_output` (`not out.exists()`). | — |
| Fit path routes only through `research_workflow.modeling.fit_temporal_fold`; governed open/partition/outcome/pre_fit gates invoked (C4) | PASS | `phase_d_modeling.py:24,244-249`; no `fit_model` import; `research_workflow/modeling.py:159`. | `test_contract_pass06_fit_path_routes_only_through_governed_primitive`; `test_section9_A…` asserts `_assert_study_open` + `assert_gates_satisfied` invoked. Full body of `fit_temporal_fold` inferred from pass-06 cross-reference + test coverage. | — |
| Per-fold metrics include `log_loss` alongside ROC AUC / PR AUC / Brier; report schema test present | PASS | `phase_d_modeling.py:62-65,303-304,331-333`. | `test_contract_pass06_report_schema_and_per_fold_log_loss`. | — |
| Section-9 acceptance tests A–K present (synthetic/contract) | PASS | `tests/test_phase_d_modeling_driver.py:142-292` `test_section9_A_H_I_J_K_full_run`, `_B_`, `_C_`, `_D_E_`, `_F_`, `_G_`, plus pass-06 closure tests. | Present (not executed per scope). | — |
| TRAIN/OOS/prohibited disjoint; authorization not stale; repo-relative study_path | PASS | `experiment_authorization.json` (2021-23 / 2024 / 2025-26; `study_path` repo-relative; `authorization_sha256 4611455d…`, generated 2026-09-01T21:00Z, same cycle as composite). | driver `run_phase_d:266-268` `PHASE_D_CHRONOLOGY_CONTRACT_MISMATCH`; `load_phase_c_inputs:140-143` `PHASE_D_NONTRAIN_YEAR_READ`. `test_section9_G_oos_year_cannot_enter_train_protocol`. | — |
| TRAIN artifacts not frozen before OOS; 2024 unaccessed; no TRAIN freeze / OOS opening claimed | PASS | No `train_experiment_freeze.json`, no `artifacts/phase_d/`, no modeling run dirs (all `runs/*` are collect `_day`/`_full`). `phase_d0_authority_closed.json` `constraints_held`: `oos_2024_accessed:false`, `modeling_started:false`. | `test_phase_d_rejects_oos_input_before_fit`. | — |
| Frozen feature sets carry no forward-outcome columns; exactly 13 ordered features | PASS | `phase_d_modeling.py:127-132` requires 13 unique columns from `config/feature_contract.json`; features joined from observations only, targets kept as separate label columns. `audit/preflight.json` CAUSAL_LINT / CAUSAL_INVARIANTS PASSED. | `test_section9_A…` H/I branches. | — |
| Partitions reconcile (no dup ids, no overlapping intervals, one authority hash) | PASS | `train_target_authority_reconciliation.json` `exact_current_cross_check`: `row_order_mismatches:0`, identity mismatches 0; single authority `21d598a8…` bound by freeze card, resume manifest, C.3, D.0. | driver `load_phase_c_inputs:123-126` row-count + identity-order equality; `_assert_group_integrity` regime-group disjointness. | — |
| Frozen execution composite current | PASS | `audit/frozen_execution_manifest.json` self-declares `4f45256b…` (generated 2026-09-01T21:03Z); `audit/preflight.json` EXECUTION_MANIFEST = PASSED on the same composite (run 21:05Z, 8/8 checks, none missing). | Independent re-run of `scripts/resolve_execution_manifest.py` not possible in this audit environment (no shell); relied on the preflight harness re-resolution + self-consistent manifest. | — |
| Preflight ran every required check and passed | PASS | `audit/preflight.json`: 8 required checks, `required_checks_missing: []`, `checks_complete: true`, all `PASSED`, `status: CLEAR`. | — | — |
| Readiness passed (R1–R10) | PASS | `audit/readiness.json` `overall_status: PASS`; R1 DATASET_IDENTITY_OK, R5 REAL_COLLECTOR_INSTANTIATED, R8 IDENTITY_STABLE, R9 NO_ALTERNATE_CATALOG_OPENERS. | — | — |
| Causal and contract reviews have distinct declared identities | PASS | `audit/pass_ledger.json`: causal `Lookahead Auditor (Claude 3.7 Sonnet)`, contract `Codex-PhaseD-Contract-20260901` / this pass `contract-checker`; `audit/status.json` ≠ `audit/contract_status.json`. | — | — |
| Seal binds report bytes to the audited composite | NOT APPLICABLE (pre-seal) | `artifacts/preexec_audit_seal.json` binds an obsolete composite; task and pass-06 both note the orchestrator re-seals after both current audits are CLEAR. | — | Orchestrator re-runs `scripts/preexec_audit_seal.py`. |
| `research_workflow/modeling.py` reachability in the modeling closure (pass-07 WARNING) | PASS | `research_workflow/modeling_closure.py:30-39` seeds `research_workflow/modeling.py` (+ `model_selection`, `partitioning`, `experiment`, `gates`, `research/analysis/modeling.py`) and AST-closes; `phase_d_modeling.py:282` calls `resolve_modeling_closure(study, driver_relpaths=declared)` and threads `closures=closure` into `persist_models` (`:306-309,338-341`). The collection composite `4f45256b` legitimately excludes it (fit code does not run in the collector); the TRAIN freeze binds both composites. | — | — |
| Backtest / fill model / warmup (E) | NOT APPLICABLE | Phase D is TRAIN modeling only; `research_decision.yaml:38-49` authorizes no backtest or entry rule. | — | — |
| Train/serve skew, encoding/imputation/ordering determinism (D4) | PASS | `phase_d_modeling.py:246-249` seed 42, `deterministic: True`, `n_jobs: 1`, identity preprocessing (`preprocessing_identity={"kind":"identity"}`); frozen ordered feature contract; `_year`/`_direction` deterministic maps. | `test_phase_d_...::test_phase_d_synthetic_is_train_only_...` asserts identical `selected` across two runs. | — |

## Notes (non-blocking)

1. `artifacts/preexec_audit_seal.json` binds an obsolete composite — expected pre-seal; the
   orchestrator re-seals once both current audits are CLEAR.
2. The recorded causal lineage stops at pass 05 / composite `4dcdc030`. The Phase D driver's
   temporal-fold construction and year-filter guards (`phase_d_modeling.py:36-47,68-74,140-145,169-174`)
   post-date that pass. See `## Referred to lookahead-auditor`.
3. `candidates_path` / `observations_path` are supplied by the caller and are not SHA-bound to
   a preserved Phase C authority (only the target is). Defence in depth: exact row-count +
   identity-order equality against the authenticated target (`:123-126`) and the TRAIN-year
   guard (`:140-143`). A future hardening could pin their SHAs in the reconciliation record.
4. Independent re-execution of `scripts/resolve_execution_manifest.py` and recomputation of
   `authorization_sha256` were not possible in this audit environment (no shell); the
   preflight `EXECUTION_MANIFEST` check performs that re-resolution and passed.

## Referred to lookahead-auditor

The Phase D modeling driver (`implementation/phase_d_modeling.py`) — expanding-window temporal
folds, `regime_start_ns` group-disjointness, `observation_ts`→year OOS guard, first-fire
threshold derived from validation scores only — is newer than the last causal pass (05); a
concurrent causal pass should cover it.

## Blocking verdict

**CLEAR.** All three pass-06 CRITICALs are remediated at the executable boundary with matching
negative tests; both pass-07 blockers are resolved (the diagnostics scripts are gone and out of
the closure, R9 passes; the Phase D.0 authority artifacts exist, are internally consistent, and
bind the single target hash `21d598a8…`). The frozen composite `4f45256b…` is current per the
preflight re-resolution, readiness is PASS across R1–R10, chronology is disjoint and consistent
across SPEC / study.yaml / research_decision.yaml / authorization / driver, 2024 is unaccessed,
and no TRAIN freeze or OOS opening is claimed. Nothing blocks SEAL. The seal itself and the
concurrent causal re-audit remain the orchestrator's to complete.
