---
audit_type: "contract"
study: v2_shape_b_deep_pullback_5s
auditor: contract-checker
---

# Contract & Governance Audit — v2_shape_b_deep_pullback_5s — pass 01

Composite audited: `0db52eeff6bbe048a4bf6adb8652df4aa94b14915e1f311a851a2b5ebd7fcca0`
(`audit/frozen_execution_manifest.json`, generated `2026-09-02T19:19:27Z`).

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| Plan bound to spec | PASS | `compiled_plan.json:1709` plan_sha256=`e4d66bedf80ebc239e377dd41994e7ab83c4d8bfd670d7056c3e3ae34595300d`, `:1746` spec_sha256=`fc71ef2bd9248bb938203cf7eca7c7a315517dd68f03c634c5fb49bec25912da`; identical in packet and `frozen_execution_manifest.json` | `readiness.json` `PLAN_BOUND_TO_SPEC`=PASSED | none |
| TRAIN/OOS/prohibited chronology disjoint | PASS | `study.yaml:131-135`, `experiment_authorization.json` train=[2021], oos=[2022], prohibited=[2023-2026] | `readiness.json` `CHRONOLOGY_ROLE_TABLE`=PASSED | none |
| Model declaration | NOT APPLICABLE | `study.yaml:136` `model: none`; packet `"model": null`; no `fit`/`model` deliverable claimed beyond the packet's own `fit` stage (`artifacts/experiment_models.json`) — this study produces no trained model, only consumes a frozen external score. The "explicit params + random_state" hard-gate check does not apply here. | — | none |
| Readiness PASS bound to composite | PASS | `audit/readiness.json`: `overall_status: PASS`, composite matches manifest; R9 `current=0db52eeff6bb frozen=0db52eeff6bb`; R5 "39 primitives bound; unbound=[]" | R1/R3/R5/R8/R9 all `passed: true` | none |
| Preflight CLEAR bound to composite | PASS | `audit/preflight.json`: `status: CLEAR`, composite matches; all 7 required checks PASSED | — | none |
| Tests PASS bound to composite | PASS | `_work/controller/test_summary.json`: 34 passed / 0 failed, composite matches | 3 test files | none |
| Causal status CLEAR, distinct auditor, bound to composite | PASS | `audit/status.json`: `verdict: CLEAR`, `auditor: lookahead-auditor`, composite matches, `critical: 0` | — | none |
| Label column and entry reference executable | PASS | `compiled_plan.json:1677` `entry_reference: "next_bar_open"`; `:1686` `label_column: "target_flip_within_horizon"`; observation columns include `target_flip_within_horizon` | `readiness.json` `ENTRY_REFERENCE_EXECUTABLE`=PASSED | none |
| Population session ALL with outcome-level RTH censoring declared | PASS | `study.yaml:18` `population.session: ALL`; `study.yaml:130` `outcome.session: RTH` — two distinct, correctly-scoped fields (candidate population is not session-restricted; outcome resolution/censoring is RTH-bounded) | `readiness.json` `R3_session_table` detail: `{"censor_session": "RTH", ..., "session": "ALL"}` — confirms the split is compiled and reconciled, not just prose | none |
| Frozen external model score (`model_c_score_at_candidate`) — parent freeze/model hashes recorded | PASS | `study.yaml:99-116` and `compiled_plan.json:2886-2893` declare `parent_train_freeze_artifact_sha256=c5bd68ca503a...`, `model_artifact_sha256=03f602c5b389...`, `preprocessing_artifact_sha256=d74dd6931cfb...`, `retrain_prohibited: true`. Verified against the live parent artifacts: `studies/clean_maturity_flip_model_rolling_productivity/artifacts/train_experiment_freeze_repaired.json` and `.../preprocessing_manifest.json` (the latter's embedded `preprocessing_hash: 0833da444eaa...` matches the declared value exactly) — both exist read-only in the main repo, outside this worktree | — | none |
| Study never writes into the parent | PASS | `frozen_execution_manifest.json:worktree_dirty_paths` (this study's dirty-path list, distinct from the packet shown) lists only paths under `studies/v2_shape_b_deep_pullback_5s/`; no path under `studies/clean_maturity_flip_model_rolling_productivity/` appears. `derived_inputs` in `study.yaml` only reads named artifact paths — no write API is invoked by the binding (`FrozenExternalScoreBinding`, `kind: derived_input`) | — | none |
| No study Python | PASS | `Glob **/*.py` under `studies/v2_shape_b_deep_pullback_5s` returns none | — | none |

## Referred to lookahead-auditor
None — the outcome-comment in `study.yaml:118-124` documents a known historical parity caveat (memory: `forward_outcome_target_not_wired_into_collector`) that this study explicitly reproduces for parity rather than introducing; causal review is CLEAR on this composite under distinct identity `lookahead-auditor`.

## Blocking verdict
CLEAR

All lifecycle artifacts (readiness, preflight, causal status, tests, authorization) reconcile to the single audited composite `0db52eeff6bb...`. Plan/spec binding holds. Chronology is disjoint with no model-selection year table needed (no model trained by this study). The population-session-ALL / outcome-session-RTH split is compiled and reconciled by R3, not merely declared in prose. The frozen external score input's parent freeze artifact, model artifact, and preprocessing hashes are all independently verified against the live read-only parent study directory, `retrain_prohibited: true` is recorded, and no write path touches the parent. No study Python exists. No governance violation found.

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "contract", "study": "v2_shape_b_deep_pullback_5s", "auditor": "contract-checker", "audited_execution_composite_sha256": "0db52eeff6bbe048a4bf6adb8652df4aa94b14915e1f311a851a2b5ebd7fcca0", "critical": 0, "warning": 0, "note": 1}
<!-- AUDIT_SUMMARY_V2_END -->
