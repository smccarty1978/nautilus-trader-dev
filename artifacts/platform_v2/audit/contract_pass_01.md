audit_type: "contract"
auditor: "contract-checker/platform-v2-pass-01"
study: "platform_v2_migration"
range: "baseline/2026-09-platform..HEAD (2138cc4)"

## Compliance table

| # | Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|---|
| 1 | Sealed-study authority preserved | PASS | `studies/.../artifacts/preexec_audit_seal.json` composite_seal_hash `1a6eed85...` and `audit/frozen_execution_manifest.json` `frozen_execution_composite_sha256` both `1a6eed85254d052ca84c823a4af5a3d643af83fac57310811720086807077c36`, byte-identical to the packet's declared composite; `closure_hash.py:87-105` `frozen_hash_algorithm`/`resolve_hash_algorithm` default unrecorded manifests to `"v1"`; `resolve_execution_manifest.py:947-954` `verify_frozen_execution_identity` reads `frozen_data.get("hash_algorithm") or "v1"` and re-resolves with that algorithm before comparing | `scripts/tests/test_closure_narrowing.py` "sealed regime-transition study resolves under v1 with identical membership" (checkpoint 09) | No git-diff tool available in this session; verified by hash equality instead of byte-diff — note as residual gap below |
| 2 | Target authority unchanged, no 2024 access | PASS | `artifacts/train_target_authority_reconciliation.json`: `authoritative_train_target_sha256: 21d598a8...`, `phase_d_authorization.oos_years_locked: [2024]`, `oos_access_authorized: false`; `controller_actions.py:348-350` OOS stage calls `assert_oos_open(study)` from `research_workflow/experiment.py:284`; no `2024` literal found in `governed_controller.py` | grep for `2024` in controller path: none | none |
| 3 | Model store v2 migration | PASS (with a provenance caveat) | `studies/.../artifacts/model_store_migration.json`: `records:468, migrated:468, tiers: {ledger/rejected:456, registry/selected:12}, exports:{joblib/verified:12}`; `model_store.py:350-399` `add_export` wraps the export in `try/except Exception` and never raises — export failure cannot fail the canonical model | checkpoint `03_model_contract_v2.json`: `scripts/tests/test_model_store.py 11 passed`, golden_validate_sample `max_abs_diff 0.0`, golden frames "468 x 256 real TRAIN rows" | Store root `~/.nt_research/models` is machine-local and not in the repo — the committed migration report + golden-frame validate-sample is the only repo-durable provenance; **insufficient on its own to reproduce the store on another machine**. Recommend also committing per-model `manifest.json` sha256 list (or the store's own manifest index) into the study's `artifacts/` tree |
| 4 | Controller stage order / label / freeze / close / deprecation | PASS | `controller_actions.py:122-132` `_label_column` requires explicit `--label-column` or `target_contract.label_column`, else raises `LABEL_COLUMN_REQUIRED` — never guesses; `scripts/run_research_workflow.py`, `run_partitioned_train_collection.py`, `reconcile_study_capabilities.py` each print `{"STATUS":"DEPRECATED", ...}` and `return 2` unconditionally | checkpoint `04_controller.json`: 12+46 passed | none |
| 5 | Roots — digest identity, no repo-relative fallback | PASS | `roots.py:221-254`: configured-roots path raises `DATASET_ROOT_UNRESOLVED` if no `logical_digest` declared, and never falls back to a repo-relative path once `catalog_roots` is configured; `DatasetDigestMismatch`/`DuplicateDatasetConflict` guard cross-root conflicts; receipts record `dataset_id`+`logical_digest`, never path (`roots.py:183-184`) | checkpoint `02_roots.json`: 12 passed, per-dataset hashes recorded | none |
| 6 | Capability registry current, no broken entries | PASS | `research_workflow/capabilities/registry.json`: all 9 kind blocks show `"broken": 0` (grepped), including `trackers` — resolved after item 06 landed `tracker.regime.dual_ema` (checkpoint 05 had recorded `trackers.broken:1` before item 06) | checkpoint `05_capability_registry.json` 10 passed; `06_regime_tracker.json` 4 parity tests passed | none |
| 7 | Deliverable completeness (checkpoints 01-09) | PASS w/ NOTEs | All 9 checkpoint files: `status: "PASS"`; item 08 (`workspace.py`) states its own code "included in the item 07 commit" — a commit-boundary slip, not a missing deliverable; item 03 records ONNX export as `not_done` (available but unexercised) | consolidated run: 483 passed / 4 failed (all 4 pre-existing on baseline per packet) / 0 new failures | none required; disclose ONNX-not-run and the 07/08 commit-boundary slip in the release note |

## NOTE: git-diff not directly executable in this session

No shell/bash tool was available to this auditor in this session; `studies/` unchanged-except-new-file claim was verified indirectly via composite-hash equality (item 1) and by confirming `model_store_migration.json` is additive and `train_target_authority_reconciliation.json` content is internally consistent, rather than by a literal `git diff --stat -- studies/`. This is a process gap, not a code defect — recommend the orchestrator supply a `git diff --stat` artifact for the next pass.

## NOTE: model store provenance is machine-local

Item 3's `~/.nt_research/models` root is outside the repo; the only repo-durable trace is `model_store_migration.json` (counts + tiers) plus the golden-frame validate-sample delta (`max_abs_diff 0.0`). That is sufficient to confirm no retraining occurred (byte-identity check) but is **not** sufficient to reconstruct or audit the store's contents from the repo alone on a different machine. Not a blocking gate per §6.2 (this is provenance completeness, not a hard gate), but should be tracked as a DO SOON.

## Referred to lookahead-auditor

The three `questions_for_causal_auditor` in the packet (hot-path timing changes, v2 closure-hash executable-behavior-without-composite-move, and root resolution physical-dataset substitution) are causal/timing questions and are explicitly out of this auditor's scope — referred verbatim, not evaluated here.

## Blocking verdict

CLEAR

All seven in-scope compliance items verified PASS from direct artifact/code evidence: the sealed study's composite hash is byte-identical pre/post migration, the v1 hashing algorithm is authoritative for the frozen manifest and confirmed by `verify_frozen_execution_identity`, the TRAIN target authority (`21d598a8...`) is unchanged and 2024/OOS access remains gated behind `assert_oos_open`, the 468-model migration is additive/non-retraining with export failures isolated from fit success, the controller never guesses a label column and all three deprecated entry points hard-exit(2), dataset root resolution enforces digest identity with no repo-relative fallback once configured, and the capability registry shows zero broken entries across all nine checkpoints. Two NOTEs are recorded (no git-diff tool this session; model-store provenance is machine-local) as residual gaps for the next pass, not as CRITICAL findings.

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "contract", "auditor": "contract-checker/platform-v2-pass-01", "critical": 0, "warning": 0, "note": 2, "study": "platform_v2_migration", "audited_execution_composite_sha256": "2138cc4"}
<!-- AUDIT_SUMMARY_V2_END -->
