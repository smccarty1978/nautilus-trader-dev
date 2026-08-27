# Look-Ahead & Timestamp Audit — Pass 11

**Date** 2026-08-27 · **Scope** `implementation/two_phase_selection.py` (`_run_model_selection_to_named_manifest`, `run_phase1_architecture_selection`'s new `direction` parameter and per-call rename), new regression test `test_phase1_manifests_do_not_clobber_across_directions_or_metrics` (`tests/test_two_phase_selection.py`), `audit/{preflight,readiness,lint,frozen_execution_manifest}.json` · **Scope hash (frozen execution composite)** `72d474e824e4ddd3b42b221a3465b8de305f02118cf0bfb5cd49bc44f40006bf` · **Lint** 0 critical / 0 warning (`audit/lint.json`, 100/100 files, 100% coverage) · **Verdict** `CLEAR`

## Summary
Critical: 0 · Warning: 0 · Note: 0

This is a contract-checker-originated finding (artifact clobbering / reproducibility, not look-ahead), but since it touches the same orchestration module I've verified since pass 07 for chronological-isolation guarantees, I traced it in full rather than rubber-stamping it — a silent overwrite of Phase-1's own evidence would have undermined my ability to verify those guarantees held for a *specific* direction/metric run.

## Prior findings adjudicated
| # | Finding | Status | Evidence |
|---|---|---|---|
| 1 | pass 10 referrals (parent SPEC.md drift, `model_family_resolution` joblib claim, `model.params` random_state landmine, optional `pre_fit` gate adoption) | WITHDRAWN (not re-raised; untouched this pass) | unchanged |

## (1) Composite freshness
`72d474e824e4ddd3b42b221a3465b8de305f02118cf0bfb5cd49bc44f40006bf` matches exactly across `audit/frozen_execution_manifest.json`, `audit/preflight.json` (`status: CLEAR`), and `audit/readiness.json` (`prepared_execution_identity`, `overall_status: PASS`). `audit/lint.json` unchanged at 100/100 files (existing tracked file's content changed, no new file added).

## (2) Traced the fix — genuinely produces 4 distinct artifacts, no clobbering
- **Root cause, confirmed by reading `research_workflow/model_selection.py::run_model_selection`** (unchanged since pass 05): it always writes to the hardcoded `artifacts/model_selection_manifest.json`. Before this fix, `run_phase1_architecture_selection`'s two calls (pr_auc, then brier) both hit that path with no rename in between — and since Phase 1 runs once per direction (LONG, then SHORT) against the *same* study directory, all four calls raced for the same file; only the last (SHORT/brier) survived on disk.
- **The fix**: `run_phase1_architecture_selection` now accepts `direction` (threaded through from `run_direction_two_phase_selection`'s existing `direction` argument, line 317-320) and routes both of its calls through the new `_run_model_selection_to_named_manifest` helper (lines 127-144), which calls `run_model_selection` then immediately does `default_path.replace(out_path)` to `model_selection_manifest_phase1_{direction.lower()}_{prauc,brier}.json` — this is the identical rename-immediately-after-call pattern already used (and verified in pass 07/08) for Phase 2/3's own manifest.
- **No race is possible**: `pr_auc_manifest = _run_model_selection_to_named_manifest(...)` (line 169) completes its own governed call *and* its own rename before `brier_manifest = _run_model_selection_to_named_manifest(...)` (line 174) begins — ordinary sequential Python statement execution, not concurrency. Likewise, `run_study_two_phase_selection`'s two `run_direction_two_phase_selection` calls (LONG then SHORT) are sequential dict-literal evaluations (verified in pass 07) — so the full call order is LONG-prauc-call+rename → LONG-brier-call+rename → LONG's Phase2/3 → SHORT-prauc-call+rename → SHORT-brier-call+rename → SHORT's Phase2/3. At every point where the shared default path is written, the *previous* writer has already moved it out of the way. Four distinct file names (`..._long_prauc.json`, `..._long_brier.json`, `..._short_prauc.json`, `..._short_brier.json`) can never collide with each other by construction (direction and metric are both baked into the filename).
- **The new test proves this against real execution, not just inspection**: `test_phase1_manifests_do_not_clobber_across_directions_or_metrics` (`tests/test_two_phase_selection.py:176-198`) calls `run_phase1_architecture_selection` twice — once per direction — into the **same** temp directory (reproducing the actual multi-direction-same-study-dir scenario the bug occurred in, not an isolated per-call temp dir like most of the other tests use), then asserts all four expected filenames are present *and* that the shared default path (`model_selection_manifest.json`) does **not** exist afterward — i.e., it positively proves every rename fired, not merely that the four names happen to exist for unrelated reasons.
- This does not touch any of the four chronological-isolation properties verified in pass 07 (2023 unreachable in Phase 1, Phase 2 gets exactly the Phase-1 winner, final validation can't re-select, FAIL returns with no fallback) — it is a file-naming/persistence fix layered on top of unchanged selection logic.

## (3) Nothing else in the causal surface moved
`compiled_study.json` re-diffed against pass 10: `target.horizon_seconds=180`, `population.session="RTH"`/`age_gate_seconds=120`, `feature_contract.feature_list_sha256=4e46c0b3...df33`, `model.selection.tuning_years=[2021,2022]`/`final_train_validation_years=[2023]`/`secondary_metrics=["brier"]` all byte-identical. `audit/lint.json` unchanged (100/100, 0/0).

## Critical findings
None.

## Warnings
None.

## Notes
None.

## Referred to contract-checker
- (carried forward, unresolved) `discovered_parent_spec_md_drift`, `model_family_resolution` joblib-claim verification, `model.params` dormant `random_state` landmine, optional `pre_fit` gate adoption.

## Clean checks
A1–A5, B1–B7/B9/B10, C1–C3, F1–F4, G1–G4, H1–H4 clean — unchanged from pass 10; this fix touched only Phase-1 artifact persistence/naming, not timing, population, feature, or chronology.

<!-- AUDIT_SUMMARY_V2_START -->
{"audit_type": "causal", "auditor": "lookahead-auditor", "study": "clean_maturity_flip_model_180s_horizon", "verdict": "CLEAR", "critical": 0, "warning": 0, "note": 0, "audited_execution_composite_sha256": "72d474e824e4ddd3b42b221a3465b8de305f02118cf0bfb5cd49bc44f40006bf"}
<!-- AUDIT_SUMMARY_V2_END -->
