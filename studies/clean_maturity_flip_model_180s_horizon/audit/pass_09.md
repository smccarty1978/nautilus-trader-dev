# Look-Ahead & Timestamp Audit — Pass 09

**Date** 2026-08-27 · **Scope** Concurrent commit `cc23a48` (`research/schemas/study_spec.py`, `research/engines/{population,target}_engine.py`, `research_workflow/execution_plan.py`, `research_workflow/gates.py`, `research_workflow/forward_outcomes/{__init__,analysis,contracts,guard,tracker}.py`, `research_workflow/modeling.py` — new file) traced against our study's actual compiled contracts and runtime closure; `scripts/check_artifact_schema.py`'s `scan_artifacts()` fix; `audit/{preflight,readiness,lint,schema_check,frozen_execution_manifest}.json` · **Scope hash (frozen execution composite)** `6f3fa8bd613fb45810956684abf6c6ea75498fc18ff0c83e77580e581055eeb6` · **Lint** 0 critical / 0 warning (`audit/lint.json`, 100/100 files, 100% coverage) · **Verdict** `CLEAR`

## Summary
Critical: 0 · Warning: 0 · Note: 1

## Prior findings adjudicated
| # | Finding | Status | Evidence |
|---|---|---|---|
| 1 | pass 07/08 referrals (parent SPEC.md drift, `model_family_resolution` joblib claim, `model.params` random_state landmine) | WITHDRAWN (not re-raised; untouched by `cc23a48`; still open on contract-checker's side) | unchanged this pass |

## (1) Composite freshness
`6f3fa8bd613fb45810956684abf6c6ea75498fc18ff0c83e77580e581055eeb6` matches exactly across `audit/frozen_execution_manifest.json`, `audit/preflight.json` (`status: CLEAR`), and `audit/readiness.json` (`prepared_execution_identity`, `overall_status: PASS`). `audit/lint.json` still 100/100 files (Codex's changes modified *existing* tracked `repo:` files' content — moving the composite — rather than adding new files to our closure; the one genuinely new file, `research_workflow/modeling.py`, is confirmed absent from our resolved list, see §3).

## (2) Verified the "contracts unchanged" claim myself — did not take it on trust
Read `compiled_study.json`'s `population_contract` (lines 353-375), `target_contract` (376-390), `execution_contract.chronology` (922-936), and `timestamp_contract` (938-991) directly and compared field-by-field against the exact values I recorded in pass 08: `session="RTH"`, `qualification.age_gate_seconds=120` (+ the other 4 qualification fields), `causal_checkpoint` block, `horizon_seconds=180`, `confirmation={completed_1m_bar, 1}`, `decision_reference="decision_ts"`, `chronology.train=[2021,2022,2023]`/`dev=[2024]`/`prohibited=[2025,2026]`, and the full `timestamp_contract` (including the empirically-measured deltas). All byte-identical. `feature_contract.feature_list_sha256` still `4e46c0b3...df33`. `compiled_study.json`'s new top-level `spec_sha256` (`f17e54590d...`) legitimately differs from earlier passes — but that hash covers the *whole* spec including `lineage`/`model.selection`/`baseline`, which changed across passes 2-8 for reasons already adjudicated; it is not evidence of a causal-contract change from *this* commit.

## (3) Traced why Codex's changes cannot silently add causal surface (not just observed that they didn't)
- **`episode_lifecycle`** (new `PopulationSpec` field, `study_spec.py:118-120`): `population_engine.py:49-50` only writes it into the contract `if pop_spec.episode_lifecycle is not None`. Our study's `PopulationSpec` never sets it — confirmed absent from `population_contract` — so this is a no-op for us, not merely "currently unused."
- **Composite-target fields** (`conditions`/`condition_logic`/`required_forward_outcomes` on `TargetSpec`): `target_engine.py:100` (`if target_spec.conditions:`) skips the entire composite-target compilation block when `conditions` is unset. `TargetSpec.validate_composite_target` (`study_spec.py:280-307`) does `conditions = self.conditions or []`, so with zero conditions declared, none of its validators (condition_logic requirement, duplicate-id check, forward-outcome cross-reference) can fire. Our study declares no `conditions` (confirmed `null` in both the raw spec and absent from the compiled contract) — this is provably inert for us, not just presently empty.
- **New `pre_fit` gate stage** (`gates.py:19` `_STAGE_ORDER`, and the `pre_fit`-specific `dataset_identity_sha256` binding check at lines 101-118): `assert_gates_satisfied` only iterates `spec.required_gates or []` (line 89) — our study declares `required_gates: []` (confirmed both in `spec.required_gates=null` and compiled `contracts.required_gates=[]`), so the loop body — including the new pre_fit-specific check — never executes regardless of which stages now exist. `gates.py` is genuinely wired into `phase0.py`/`preflight.py`/`prepare.py`/`readiness.py`/`seal.py` (confirmed by grep — these already call `assert_gates_satisfied`), so this isn't merely untested code; it is exercised, and provably a no-op for a study with zero declared gates.
- **`research_workflow/execution_plan.py`** (a genuine *runtime*-closure file, unlike the four above): this one governs actual NT collection callback wiring, so I checked it more carefully. The new `required_regime_state_timeframes: Tuple[str, ...] = ()` field is appended to `CompiledExecutionPlan` with a default and threaded through `for_collector(..., required_regime_state_timeframes=())` as a keyword-only parameter with the same default. The only caller of `for_collector` is `research_workflow/generic_collector.py` — **not** touched by this commit — so whatever value it already passes is unchanged; the new parameter takes its default for every existing caller, ours included. Combined with `compact`/`aliases` logic being byte-for-byte the same code path our study already exercised, this is backward-compatible by construction, not merely by observation.
- **`research_workflow/modeling.py`** (genuinely new file): confirmed via repo-wide grep it is imported only by test files (`test_study_spec_extensions.py`, `test_analysis_reproducibility.py`, etc.) — none of our study's actual execution seeds (`backtests/run_nt_study.py`, `collect.py`, the strategy class, `compile_study.py`, the preflight/readiness/seal scripts) import it. Consistent with its absence from our `resolved_execution_file_list` (grepped, zero matches) — this is the expected state for FIT-stage code before FIT has happened, not a repeat of the pass-07 gap (that gap was a study-owned file missing a *should-be-tracked* location; this is shared repo code not yet reachable from any of our seeds, which is a different and currently correct situation).
- **`forward_outcomes/tracker.py`** (already in our closure pre-`cc23a48`, content changed): confirmed via grep that `generic_collector.py` — our actual collection strategy — contains zero references to `forward_outcomes`/`tracker`/`ForwardOutcomeTracker`. It is reached in our closure via the contract-authority graph, not the runtime-collection graph, so its content change cannot have affected the 1,387,411 rows already collected.

**Conclusion for (3):** none of Codex's changes impose a new requirement on `study.yaml`, and none can silently alter our study's causal contract or its already-collected TRAIN rows — every new capability is either provably gated off by a field our study leaves unset/empty, or lives in code our collection run never touches.

## (4) `check_artifact_schema.py` fix — correct, and does not mask a real issue
Read the current `scan_artifacts()` (line 205): `if name in {"status.json", "contract_status.json"} and json_file.parent == root / "audit":` — scoped to files whose parent directory is exactly `<root>/audit`. This mirrors the pre-existing `candidate_authority` branch two lines above it (same `json_file.parent == root / "audit"` pattern), so it is a proven scoping idiom being reapplied, not a novel one. Our real audit status file lives at `studies/<id>/audit/status.json` (parent exactly `audit/`), so it is still validated; a collection run's `runs/<run_id>/status.json` (parent `runs/<run_id>`, a different schema entirely — NT run-outcome fields, not `verdict`/`critical`/`warning`) is now correctly excluded. I checked for an over-broad exclusion risk (a legitimate audit status file living one level deeper, e.g. `audit/subdir/status.json`) — no such file exists in this study's `audit/` layout, so nothing that should be checked is skipped. `audit/schema_check.json` confirms `status_json: 2, seal_manifests: 1, critical: 0, warning: 0, clean: true` for this run.

## (5) Target/population/feature/chronology re-confirmed unchanged
Covered directly in §2; restated for completeness: `horizon_seconds=180`, `session="RTH"`, all 13 canonical `FeatureInstance`s (`feature_list_sha256=4e46c0b3...df33`), and `chronology` all byte-identical to every prior pass.

## Critical findings
None.

## Warnings
None.

## Notes
### [NOTE] TRAIN collection's runtime closure was not touched by `cc23a48` — the already-collected 1,387,411 rows remain consistent with everything verified in passes 1-8
Codex's changed files (`study_spec.py`, `population_engine.py`, `target_engine.py`, `execution_plan.py`, `gates.py`, `forward_outcomes/*`, `modeling.py`) are contract-authority, governance, or future-FIT-stage code. None of `research_workflow/generic_collector.py`, `features/trackers/*.py`, or `backtests/nt_runtime/*.py` (the actual NT collection execution path) appear in the list of changed files, and I independently confirmed (§3) that the one runtime-closure file that did change (`execution_plan.py`) only added a backward-compatible, default-valued field never populated by our (unchanged) caller. This is not itself a lifecycle/completeness question (out of my scope) — it is the causal basis for why I can say the collected data's population/target/feature timing is still the same recipe I've verified across 8 passes.

## Referred to contract-checker
- (carried forward, unresolved) `discovered_parent_spec_md_drift`, `model_family_resolution` joblib-claim verification, `model.params` dormant `random_state` landmine.
- (new, informational) Whether this study should adopt the new `pre_fit` gate stage now that TRAIN collection has produced real data — a research-protocol/completeness decision, not a causal requirement (confirmed in §3 that not adopting it introduces no causal gap).

## Clean checks
A1–A5, B1–B7/B9/B10, C1–C3, F1–F4, G1–G4, H1–H4 clean — re-verified against the concurrent commit, not merely re-asserted.

<!-- AUDIT_SUMMARY_V2_START -->
{"audit_type": "causal", "auditor": "lookahead-auditor", "study": "clean_maturity_flip_model_180s_horizon", "verdict": "CLEAR", "critical": 0, "warning": 0, "note": 1, "audited_execution_composite_sha256": "6f3fa8bd613fb45810956684abf6c6ea75498fc18ff0c83e77580e581055eeb6"}
<!-- AUDIT_SUMMARY_V2_END -->
