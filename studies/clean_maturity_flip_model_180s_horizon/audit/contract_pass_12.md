# Contract Review — Pass 12
study: clean_maturity_flip_model_180s_horizon
audited_execution_composite_sha256: 85efdcc4be7043072f8937e6eb112eee8ace6b7811b16b5493c73eb900c4e6ea
(re-verified fresh: audit/frozen_execution_manifest.json `frozen_execution_composite_sha256` = this value; audit/readiness.json `prepared_execution_identity` = this value, `overall_status: "PASS"`; audit/preflight.json `execution_composite_sha256` = this value, `status: "CLEAR"`, all 7 required checks PASSED)

## (1) Composite freshness — confirmed

## Unprompted first check: Phase 1 / Phase 2-3 real execution status (closes out pass 10/11)

Before addressing the new module, I re-checked whether my pass-10/11 remediation (re-run Phase 1 under the fixed code) actually happened. It did: `artifacts/` now contains all four durable Phase-1 manifests (`model_selection_manifest_phase1_{long,short}_{prauc,brier}.json`), plus real Phase 2/3 outputs (`model_selection_manifest_long.json`, `model_selection_manifest_short.json`) and a new `two_phase_selection_dispatch_summary.json`. I read the dispatch summary directly: both directions genuinely completed with **distinct, non-identical tuned hyperparameters** (LONG: `learning_rate=0.0289, max_depth=5, n_estimators=200`; SHORT: `learning_rate=0.0394, max_depth=5, n_estimators=100`) and both show `final_validation_status: "PASS"` against the 2023 gate with Arm C winning both directions — a genuine model-integrity signal (the two directions' results are not copy-pasted or identical) that the earlier pass-09/10 provenance gap is now fully closed for real, not just in a test.

## (2) Governance: threshold/decile derivation and selection binding

Read `research_workflow/modeling.py` directly, not just `implementation/final_train_freeze.py`:

- **Thresholds are genuinely derived by `freeze_train_artifacts`'s own internal logic, not reinvented by the new module.** `modeling.py:159-172`: when the caller does not supply `thresholds` explicitly (and `final_train_freeze.py` does not — it only passes `deciles`), `freeze_train_artifacts` computes `p90`/`p95`/`p97_5` itself via `pd.Series(values).quantile(...)`, each explicitly tagged `"derivation_population": "train"`. This satisfies the lifecycle-state requirement verbatim.
- The new module's own `deciles` computation (`DECILE_QUANTILES = (0.1..0.9)`, `implementation/final_train_freeze.py:118-123`) is a **separate, non-overlapping** diagnostic breakdown, not a duplicate or override of the threshold logic — it does not touch `p90`/`p95`/`p97_5` at all, and is itself tagged `"derivation": "TRAIN_ONLY"`. Verified by the test (`test_final_freeze_thresholds_and_deciles_are_train_only`) which asserts both independently.
- **`ModelSelectionBindingMismatch` is a real, enforced check, not a documentation claim.** `modeling.py:124-140`: `freeze_train_artifacts` reads the selection manifest from `model_selection_manifest_path`, and for each arm compares `frozen_rec.get("hyperparameters") != winner.get("hyperparameters")` and `frozen_rec.get("seed") != selection_manifest.get("random_seed")`, raising on mismatch. `test_final_freeze_binds_to_selection_manifest_and_rejects_mismatch` (read directly) proves both the accept path (matching hyperparameters) and the reject path (`n_estimators=999` vs. the declared winner) — a genuine negative test, not just a happy-path smoke test.
- `ModelSelectionFinalValidationFailed` (`modeling.py:141-148`) additionally refuses the freeze outright if the manifest's gated status isn't `PASS`, with no re-derivation path — consistent with this study's repeatedly-verified "no fallback after FAIL" discipline from Phase 2/3.

**Conclusion: yes, this satisfies the model-integrity-declaration standard.** The declared search protocol's actual winner is what gets frozen, verified by direct hash/value comparison against the selection manifest, not by trusting that the caller passed the right thing — and the threshold/decile provenance fields required by this checklist are present and correctly attributed.

## (3) Rename pattern — confirmed to prevent LONG/SHORT collision at the code level, same as pass 10

`implementation/final_train_freeze.py:38-46` (`_rename_off_default`) is applied to **both** governed writes: `fit_models`'s hardcoded `artifacts/experiment_models.json` (renamed to `experiment_models_{direction}.json`) and `freeze_train_artifacts`'s (via `write_train_freeze`) hardcoded `artifacts/train_experiment_freeze.json` (renamed to `train_experiment_freeze_{direction}.json`). Confirmed both hardcoded source paths by reading `research_workflow/modeling.py:68` and `research_workflow/experiment.py:201` directly. `test_final_freeze_no_clobber_across_directions` (read directly) asserts all four direction-specific files exist **and** that neither shared default path exists afterward — the same double-sided assertion style that made the Phase-1 fix's test convincing in pass 10.

## (4) TRAIN/OOS separation — unaffected, verified structurally

`run_final_train_fit_and_freeze` hard-asserts `meta_train_full["_partition"].nunique() != 1 or ... != "train"` before any fit is attempted (`final_train_freeze.py:91-95`), raising `FinalFreezeError` otherwise — proven by `test_final_freeze_rejects_non_train_partition`. Nothing in this module references 2024, `dev`, or OOS in any form. This operates purely on the already-collected, already-frozen 2021-2023 TRAIN partition; no new touchpoint into protected years.

## Standing findings re-confirmed unchanged

| Item | Status |
|---|---|
| model_family_resolution | PASS (same disclosed limitation) |
| `config/baseline.json` consistency | PASS |
| `model.params.random_state` dormant note | Still present, unchanged, hygiene-only |
| TRAIN/OOS chronology (`experiment_authorization.json`) | PASS, unchanged |
| `pre_fit` gate opt-in status | Unaffected — still `config/required_gates.json == []`; note `fit_models` (`modeling.py:54-62`) only calls `assert_gates_satisfied(stage="pre_fit", ...)` when `study_spec.required_gates` is truthy, consistent with pass 08's finding that this stage is opt-in, not silently mandatory |
| Deliverables, terminal-label reachability, `lineage.parent_manifest_sha256` | PASS, unaffected |
| No premature execution of *this* new module | Confirmed — `artifacts/` contains no `experiment_models_{long,short}.json` or `train_experiment_freeze_{long,short}.json` yet; `final_train_freeze.py` has been written and tested against synthetic fixtures only, consistent with the seal-before-execution discipline already established for Phase 1 |

## Blocking verdict

CLEAR

Composite is fresh. The new module composes only existing governed APIs, introduces no custom fitting/threshold logic, correctly delegates the actual p90/p95/p97.5 threshold derivation to `freeze_train_artifacts`'s own TRAIN-only quantile logic, and its own `deciles` computation is a genuinely separate, non-conflicting diagnostic. The `ModelSelectionBindingMismatch`/`ModelSelectionFinalValidationFailed` guards are real, verified by reading the enforcement code and a genuine negative test. The rename-after-write pattern is correctly and consistently applied to both of the module's hardcoded-path writes. TRAIN/OOS separation holds structurally. Real Phase 1 and Phase 2/3 execution (checked independently, not prompted) has now genuinely closed out the pass-10/11 remediation with distinct, non-duplicated per-direction results. Zero critical, zero warning, zero note against my own checklist this pass.

<!-- AUDIT_SUMMARY_V2_START -->
{"audit_type": "contract", "auditor": "contract-checker", "study": "clean_maturity_flip_model_180s_horizon", "verdict": "CLEAR", "critical": 0, "warning": 0, "note": 0, "not_verified": 0, "audited_execution_composite_sha256": "85efdcc4be7043072f8937e6eb112eee8ace6b7811b16b5493c73eb900c4e6ea"}
<!-- AUDIT_SUMMARY_V2_END -->
