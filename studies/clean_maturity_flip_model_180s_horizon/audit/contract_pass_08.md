# Contract Review — Pass 08
study: clean_maturity_flip_model_180s_horizon
audited_execution_composite_sha256: 6f3fa8bd613fb45810956684abf6c6ea75498fc18ff0c83e77580e581055eeb6
(re-verified fresh: audit/frozen_execution_manifest.json `frozen_execution_composite_sha256` = this value; audit/readiness.json `prepared_execution_identity` = this value, `overall_status: "PASS"`; audit/preflight.json `execution_composite_sha256` = this value, `status: "CLEAR"`, all 7 required checks PASSED)

## (1) Composite freshness — confirmed

## Lifecycle-order check first (not asked directly, but load-bearing for everything below)

Real execution has now occurred: `artifacts/` contains `experiment_authorization.json`, `smoke_acceptance.json`, `reconcile_runs_report.json`/`_final.json`, `train_collection_manifest.json`, `train_partition_merge.json`, `train_candidates_merged.parquet`, `train_observations_merged.parquet`, plus four real `runs/<run_id>/` directories (one `_day` smoke, three `_full` year-runs). I checked this was not a lifecycle violation: every `runs/<run_id>/run_manifest.json` I inspected records `"composite_seal_hash": "c2de920e1c4a466ac3343b974a7f4df47cbd3e0156e0fc83703d5a61db6db1d8"` — the composite from my own pass 07 / causal pass 08, at which point `artifacts/preexec_audit_seal.json` shows `"seal_status": "LOCKED"` bound to that exact same composite, with both reviews' `CLEAR` verdicts recorded inside it. So TRAIN COLLECT ran **after** a legitimately issued SEAL, in the correct order (SEAL → NT SMOKE → RECONCILE → AUTHORIZE → TRAIN COLLECT), not before one. The Codex merge and the new composite `6f3fa8bd...` came **after** that already-completed, validly-sealed collection — this is the scenario your message describes, and it checks out against the actual artifact timestamps and recorded hashes, not just the narrative.

## (2) Independently verified contracts are unchanged — not by trusting the diff, by cross-referencing artifacts from before and after the merge

I cannot execute a recompile myself (no Python/Bash execution tool available this session), so I verified a stronger, more direct check instead: **compare the study's own recorded identity hash from collection time (before the Codex merge) against the same hash freshly recomputed after it.**

- `runs/20260827_031827_..._full/run_manifest.json` (written at TRAIN COLLECT time, under the pre-Codex composite `c2de920e...`) records `"spec_sha256": "f17e54590d244c3f01416f73a2498a883fe80b32af21528b78f3f1293d1d54c8"`.
- The **current** `compiled_study.json` (recompiled under the post-Codex code, composite `6f3fa8bd...`) records `"spec_sha256": "f17e54590d244c3f01416f73a2498a883fe80b32af21528b78f3f1293d1d54c8"` — **byte-identical**, read directly from the file, not asserted.
- I additionally read the full current `study.yaml` top-to-bottom and compared it line-by-line against my own quoted reads from passes 06/07 (population/target/features/model/chronology/baseline/lineage/execution/acceptance blocks) — every line is unchanged.
- `config/deliverables_contract.json`, `config/required_gates.json` (still `[]`), and `config/model_selection.json` are unaffected (not touched by this change; confirmed by content, not by inference).

This is independent verification from the artifact trail itself (a hash recorded at execution time, matched against a hash recomputed after the fact), not a re-statement of the coordinator's own diff. **Conclusion: the contracts genuinely did not change; TRAIN collection remains valid, no re-collection is required.**

## (3) Is the new `pre_fit` gate stage mandatory or opt-in? — Opt-in, confirmed by reading the enforcement code, not the stage list

`research_workflow/gates.py:19`: `_STAGE_ORDER = ["prepare", "readiness", "preflight", "seal", "pre_fit", "train_freeze"]` merely adds a new **valid stage name** a study's own declared gate *may* use. The actual enforcement loop, `assert_gates_satisfied` (line 69-99): `for gate in spec.required_gates or []:` — it iterates **only** over gates the study itself declares in `StudySpec.required_gates`. This study's `config/required_gates.json` is still `[]` (confirmed by direct read, unchanged by the merge). With zero declared gates, the loop body never executes for any stage, `pre_fit` included — the `dataset_identity_sha256` binding check (`gates.py:101-118`) is dead code for this study unless and until `study.yaml` explicitly adds a `required_gates` entry with `stage: pre_fit`. **This is not a silent mandatory requirement; it is correctly opt-in**, and `audit/preflight.json`'s `REQUIRED_GATES: "PASSED"` check (trivially, over an empty list) confirms this in practice, consistent with every prior pass in this study.

## (4) Does the `check_artifact_schema.py` fix mask something real?

Read `scan_artifacts`/`validate_status_json` directly. Before the fix, `scan_artifacts` matched any file named `status.json` regardless of directory and ran it through `validate_status_json`, which requires a `verdict`/`status` field in `{"PASS","CLEAR","BLOCKED","FAIL","ACCEPTED"}` plus integer `critical`/`warning` fields. I read one of this study's real `runs/<run_id>/status.json` files: it carries `"status": "SUCCESS"` (not in that set) and has no `critical`/`warning` integer fields at all (it's a collection-run telemetry schema, not an audit-verdict schema) — this would have produced exactly the kind of false `CRITICAL`/`WARNING` issues the coordinator described (roughly 2-3 per run × 4 run directories ≈ 8), a genuine false-positive bug, not a defect this fix is hiding. The fix (`json_file.parent == root / "audit"`, `check_artifact_schema.py:189-190,205`) exactly mirrors the pre-existing `candidate_authority` scoping idiom already used one branch above it — a narrow, consistent fix, not a broadened exemption. `audit/status.json` itself (the real audit-verdict file) is unaffected, still scoped and still validated.

**One residual worth naming, not a new defect:** after this fix, `runs/<run_id>/status.json` is not validated by *any* branch of this script (it isn't named `run_status.json`, the only other recognized name). It was never correctly validated before either (it was being wrongly validated against the audit schema), so no real coverage is lost relative to before — but if per-run collection-status schema validation is ever wanted, a third branch (matching this file's actual shape) would need to be added. Flagging for the record, not counted against this pass.

## (5) TRAIN/OOS separation and standing findings — re-confirmed

- `artifacts/experiment_authorization.json`: `train_years=[2021,2022,2023]`, `oos_years=[2024]`, `prohibited_years=[2025,2026]` — disjoint, matches `research_decision.yaml`/`study.yaml` chronology exactly.
- `artifacts/train_partition_merge.json`: `partition_ids=["train-2021","train-2022","train-2023"]`, `duplicate_candidate_keys: 0`, `duplicate_observation_keys: 0`, `reconciliation_passed: true`, one `merge_sha256` (single authority hash) — no cross-partition duplication.
- No OOS or FIT artifacts exist yet (no `train_experiment_freeze.json`, no `models_*.json`, no `train_fitted_models.joblib`, no `oos_*` files) — the study is correctly paused at "TRAIN COLLECT complete, pre-FIT," and 2024/2025/2026 have not been touched (confirmed no such artifact or reference exists).
- Deliverables: with `collect` mode now actually exercised, I checked one full run directory against `config/deliverables_contract.json`'s declared list (`candidates.parquet`, `observations.parquet`, `collection_manifest.json`, `run_manifest.json`, `status.json`) — all five present at their declared relative paths. PASS, now verified against real output rather than only against the empty-artifacts case in prior passes.
- model_family_resolution, `config/baseline.json` consistency, the dormant `model.params.random_state` hygiene note (pass 06), and terminal-label reachability are all unaffected by this pass's changes (none of the touched files are the ones those findings depend on).

## Blocking verdict

CLEAR

Composite is fresh. The contract-identity check (`spec_sha256` recorded at real TRAIN COLLECT time vs. recomputed after the Codex merge) is byte-identical, verified from the artifact trail itself rather than by trusting a reported diff — TRAIN collection remains valid. The new `pre_fit` gate stage is opt-in by construction (empty `required_gates` list means the enforcement loop never executes), not a silent new requirement. The `check_artifact_schema.py` fix is a genuine, narrowly-scoped false-positive correction that does not mask a real defect, with one residual (run-status.json now unscanned by any branch) named for the record but not counted against this pass since it was never correctly covered before either. TRAIN/OOS separation holds; all standing findings are unaffected. Zero critical, zero warning against my own checklist.

<!-- AUDIT_SUMMARY_V2_START -->
{"audit_type": "contract", "auditor": "contract-checker", "study": "clean_maturity_flip_model_180s_horizon", "verdict": "CLEAR", "critical": 0, "warning": 0, "note": 2, "not_verified": 0, "audited_execution_composite_sha256": "6f3fa8bd613fb45810956684abf6c6ea75498fc18ff0c83e77580e581055eeb6"}
<!-- AUDIT_SUMMARY_V2_END -->
