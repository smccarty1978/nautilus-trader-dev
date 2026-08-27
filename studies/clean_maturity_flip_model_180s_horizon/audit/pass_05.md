# Look-Ahead & Timestamp Audit — Pass 05

**Date** 2026-08-27 · **Scope** `research_decision.yaml` (`inner_train_selection_protocol`, `architecture_selection_protocol`, `bounded_tuning_protocol`, new `train_only_threshold_derivation`), cross-verified against `research_workflow/model_selection.py` (`_walk_forward_folds`, `run_model_selection`, `_evaluate_final_validation`, `_assert_partition_and_years`) and `config/model_selection.json`/`compiled_study.json:model.selection` (unchanged) · **Scope hash (frozen execution composite)** `a7e7d07d54f71de4df0895c62cbebdca157c41520cce4a99b8374486d6785132` · **Lint** 0 critical / 0 warning (`audit/lint.json`, 98/98 files, 100% coverage) · **Verdict** `CLEAR`

## Summary
Critical: 0 · Warning: 0 · Note: 1

## Prior findings adjudicated
| # | Finding | Status | Evidence |
|---|---|---|---|
| 1 | pass 04 NOTE — `compiler.py` config/*.json mirror-staleness (repo-wide) | WITHDRAWN (not re-raised; unrelated to this edit; carried on contract-checker's side) | not touched this pass |
| 2 | pass 03/04 referrals — `discovered_parent_spec_md_drift`, `model_family_resolution` joblib claim | WITHDRAWN (not re-raised; still open on contract-checker's side) | unchanged this pass |

## (1) Composite freshness
`a7e7d07d54f71de4df0895c62cbebdca157c41520cce4a99b8374486d6785132` matches exactly across `audit/frozen_execution_manifest.json` (`frozen_execution_composite_sha256`), `audit/preflight.json` (`execution_composite_sha256`, `status: CLEAR`), and `audit/readiness.json` (`prepared_execution_identity`, `overall_status: PASS`). Not stale.

## (2) Does the corrected protocol genuinely eliminate the 2023 double-use? — YES, mechanically verified against code, not just prose

**The contradiction that existed before correction** (visible in pass 01's record of the original `research_decision.yaml`): `architecture_selection_protocol` declared `fit_years: [2021, 2022]` / `evaluation_year: 2023`, while `inner_train_selection_protocol.final_train_validation_years: [2023]` simultaneously declared 2023 as a "reject-only gate, never re-selects." Using 2023 to *rank* A vs B vs C and *also* as the independent accept/reject check is a genuine selection-on-the-gate-year defect (C3: temporal splits must not let the same year serve both an adaptive-selection role and an independent-confirmation role).

**The corrected two-phase protocol, checked against the actual code it claims to invoke:**

- **`_walk_forward_folds(tuning_years=[2021, 2022])`** (`research_workflow/model_selection.py:244-246`): `years = sorted([2021,2022])`; `range(1, len(years))` = `range(1,2)` = `[1]` → returns exactly one fold, `{"fit_years": [2021], "val_year": 2022}`. This is a mechanical, deterministic consequence of the two-element list — confirms the claim "deterministically produces exactly one causal chronological fold: fit=2021, val=2022" is literally what the code does, not an assertion.
- **Phase 1 (architecture selection) skips 2023 entirely when `final_train_validation_years=None`:** in `run_model_selection` (line 382), `fv = _evaluate_final_validation(...) if spec.final_train_validation_years else {"metrics": {}, "status": "PASS", "reasons": []}` — when the field is empty/`None`, `_evaluate_final_validation` (the only function that reads `_selection_role == "final_validation"` rows) is never called. So a Phase-1 invocation using a spec copy with `final_train_validation_years` cleared genuinely cannot touch 2023-tagged rows, provided the caller also never includes 2023 rows under `meta["_year"]` for the `X_by_arm` matrices passed in (a data-construction responsibility outside this module, not yet exercised since no TRAIN COLLECT has run — flagged as an implementation-time responsibility, not a defect today).
- **Phase 2 structurally cannot let 2023 re-select the architecture or the hyperparameter trial:** within a single `run_model_selection` call, for any arm, `winner = tied[0]` (line 380) is computed from `scored`, which is built exclusively from `_fit_and_score` over `folds` — and `folds` comes from `_walk_forward_folds(spec.tuning_years)`, i.e. only the fit=2021/val=2022 fold. `_evaluate_final_validation` is invoked *after* `winner` is already fixed (line 382-384), takes `winner` as a plain argument, and — per the module's own docstring invariant ("no code path back into the candidate loop") — has no mechanism to feed its 2023 score back into `scored`/`tied`. Because Phase 2 is additionally invoked with `X_by_arm={<winning_arm>: X_winner}` (a single arm), there is no cross-architecture comparison happening in Phase 2 at all, so 2023 cannot influence which of A/B/C was chosen (that was already fixed by Phase 1) — and by the same call-graph property, it cannot influence which of the 24 hyperparameter trials was chosen either. Both claims hold.
- **Defense-in-depth data check:** `_assert_partition_and_years` (line 73-101) independently raises `SelectionPartitionMismatch` if any row tagged `_selection_role="tuning"` carries a year outside `tuning_years`, or any row tagged `"final_validation"` carries a year outside `final_train_validation_years` — a second, data-level layer (not just a declared-intent check) that would catch an implementation mistake that leaked a 2023 row into the tuning role or vice versa.

**Conclusion:** the corrected protocol, as described, maps onto real, already-existing code paths whose structure genuinely prevents 2023 from influencing architecture selection (Phase 1 never sees it) or hyperparameter selection (Phase 2's winner is fixed before `_evaluate_final_validation` runs, and only one architecture is even present in that call). This is not merely a better-worded assertion — the "no retuning after final validation" property is enforced by the call graph itself, independent of what any future orchestration script does, provided that script actually passes the described spec copies/arm subsets (an implementation-time obligation to re-check once Phase 1/2 orchestration code exists — flagged, not blocking, since no such code has been written or executed yet).

## (3) Nothing else in the causal surface changed
`compiled_study.json` re-diffed against pass 04: `target.horizon_seconds=180`, `population.session="RTH"`, `qualification.age_gate_seconds=120`, `feature_contract.feature_list_sha256=4e46c0b3...df33`, and `model.selection.tuning_years=[2021,2022]`/`final_train_validation_years=[2023]` are all byte-identical to prior passes. `config/model_selection.json` unchanged (confirmed the coordinator's claim that `study.yaml`/`model.selection` was not touched — only `research_decision.yaml` prose changed). `audit/lint.json`: 0 critical/0 warning, 98/98 files, unchanged.

## Critical findings
None.

## Warnings
None.

## Notes
### [NOTE] `research_decision.yaml:129-139` — Phase 1's "parent's exact frozen hyperparameters" claim needs a Phase-1-specific spec object, not the declared `model.selection.allowed_families`
`config/model_selection.json`/`compiled_study.json:model.selection.allowed_families[0].fixed_hyperparameters` is `{verbosity: -1, random_state: 42}` only — `n_estimators`, `learning_rate`, `max_depth`, `num_leaves` are declared as *tunable*, not fixed. If a future Phase-1 implementation invokes `run_model_selection` with `search_method="none"` against that same `allowed_families` object (only clearing `final_train_validation_years`, as the prose could be read to imply), `_enumerate_candidates`'s `"none"` branch (`model_selection.py:178-185`) uses only `fixed_hyperparameters`, so the untuned comparison would run at LightGBM's library defaults for those four parameters, not the parent's `n_estimators=200, learning_rate=0.05, max_depth=3, num_leaves=8` as the text states. This is a hyperparameter-fidelity/model-integrity question (whether the future implementation's spec object literally encodes all six frozen values as fixed), not a chronology/look-ahead defect — Phase 1's *year* handling is independently correct regardless of which hyperparameters it fixes. Flagged for whoever implements Phase 1's orchestration and for contract-checker's model-integrity-declaration scope; does not affect this pass's `CLEAR` verdict.

## Referred to contract-checker
- (carried forward, unresolved) `discovered_parent_spec_md_drift` and `model_family_resolution` joblib-claim verification.
- (carried forward, unresolved) `compiler.py` config/*.json mirror-staleness (repo-wide).
- (new) Phase 1's declared "parent's exact frozen hyperparameters" vs. `model.selection.allowed_families[0].fixed_hyperparameters` only covering 2 of 6 parameters (see Note above) — a model-integrity-declaration question for whoever reviews the Phase-1/Phase-2 orchestration code once it exists.

## Clean checks
A1–A5, B1–B7/B9/B10, C1 (unchanged), **C3 (re-verified against code this pass — corrected two-phase protocol structurally eliminates the 2023 double-use)**, F1–F4, G1–G4, H1–H4 clean.

<!-- AUDIT_SUMMARY_V2_START -->
{"audit_type": "causal", "auditor": "lookahead-auditor", "study": "clean_maturity_flip_model_180s_horizon", "verdict": "CLEAR", "critical": 0, "warning": 0, "note": 1, "audited_execution_composite_sha256": "a7e7d07d54f71de4df0895c62cbebdca157c41520cce4a99b8374486d6785132"}
<!-- AUDIT_SUMMARY_V2_END -->
