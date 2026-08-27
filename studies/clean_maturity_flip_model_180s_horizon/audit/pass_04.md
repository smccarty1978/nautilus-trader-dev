# Look-Ahead & Timestamp Audit — Pass 04

**Date** 2026-08-27 · **Scope** re-freeze verification only — `config/baseline.json` (regenerated), `compiled_study.json:baseline`, `audit/{preflight,readiness,lint,frozen_execution_manifest}.json`; spot-checked `config/target_contract.json` and `config/population_contract.json` against `compiled_study.json`'s embedded contracts for mirror-staleness given the compiler bug disclosed this pass · **Scope hash (frozen execution composite)** `3280bcceb4e2ffcf266ce0af1bee122d92dc3de2d4e9b59cc1e07d8a26729c53` · **Lint** 0 critical / 0 warning (`audit/lint.json`, 98/98 files, 100% coverage) · **Verdict** `CLEAR`

## Summary
Critical: 0 · Warning: 0 · Note: 1

## Prior findings adjudicated
| # | Finding | Status | Evidence |
|---|---|---|---|
| 1 | pass 03 — `discovered_parent_spec_md_drift` referred to contract-checker | WITHDRAWN (not re-raised; unrelated to this edit, still open on contract-checker's side) | `research_decision.yaml:discovered_parent_spec_md_drift` unchanged this pass |
| 2 | pass 02/03 — `model_family_resolution` joblib claim referred to contract-checker | WITHDRAWN (not re-raised; still open on contract-checker's side) | unchanged this pass |
| 3 | (new) `config/baseline.json` was stale (`c150bee7...41843c`) relative to the dropped pin | **FIXED** | `config/baseline.json` now reads `manifest_sha256: null`, matching `compiled_study.json:303-307` and `:1056-1061` exactly |

## Re-verification
1. **Composite consistency** — `3280bcceb4e2ffcf266ce0af1bee122d92dc3de2d4e9b59cc1e07d8a26729c53` matches exactly across `audit/frozen_execution_manifest.json`, `audit/preflight.json` (`status: CLEAR`), and `audit/readiness.json` (`prepared_execution_identity`, `overall_status: PASS`). Not stale.
2. **Causal surface unchanged.** Re-diffed against pass 03: `config/target_contract.json` (`horizon_seconds: 180`, `decision_reference: decision_ts`) and `config/population_contract.json` (`session: RTH`, `age_gate_seconds: 120`, `causal_checkpoint`) are byte-identical to pass 01–03 and to `compiled_study.json`'s embedded copies. `audit/lint.json`: 0 critical/0 warning, 98/98 files, unchanged.
3. **Direct out-of-band edit vs. compiler.** The coordinator regenerated `config/baseline.json` by hand rather than via `research_workflow/compiler.py::compile_study`, and reports (not independently re-verified by me — out of my scope, a code-path claim) that `compile_study` only refreshes `compiled_study.json` and `config/deliverables_contract.json` on recompile, leaving the other `config/*.json` mirrors write-once-at-scaffold. That is a real *determinism/reproducibility* risk in principle (a mirror could silently diverge from the authoritative `compiled_study.json` after a study.yaml edit), but I checked it empirically for this study's causally-relevant mirrors (`target_contract.json`, `population_contract.json`, `feature_contract.json` — all confirmed in item 2 and unchanged since pass 01) and none are currently stale. `research_workflow/causal_audit.py` and this study's own readiness/preflight machinery read `compiled_study.json` directly for the causal checks (`instances`, `target`, `decision_reference`), not the `config/*.json` mirrors, so a stale mirror would not itself cause a wrong causal decision to be made by the tooling that gates this study — but a human or a script trusting `config/target_contract.json` as authoritative after a future study.yaml edit could be misled. See Note.

## Critical findings
None.

## Warnings
None.

## Notes
### [NOTE] `research_workflow/compiler.py::compile_study` — config/*.json mirrors are write-once, not refreshed on recompile
**Not a causal defect in this study** (verified: this study's `target_contract.json`/`population_contract.json`/`feature_contract.json` mirrors are currently consistent with `compiled_study.json`, and the machinery that actually gates causality reads `compiled_study.json`, not the mirrors). It is a latent repo-wide reproducibility risk: after any future `study.yaml` edit + recompile, a `config/*.json` mirror could silently retain pre-edit values while `compiled_study.json` (the file `causal_audit.py` and `preflight` actually read) shows the new ones — an auditor or human comparing `config/target_contract.json` against `study.yaml` prose could be looking at stale evidence without any signal that it's stale. Confirmed out of scope for this pass (affects the shared compiler, not this study's own causal contracts) and already disclosed by the coordinator as knowingly unfixed. Referred below rather than blocked on, per scope-split protocol.

## Referred to contract-checker
- `research_workflow/compiler.py::compile_study`'s config/*.json mirrors not being refreshed on recompile is a repo-wide deterministic-artifact-freshness gap (affects reproducibility/provenance guarantees across all studies, not just this one) — contract-checker or `implementer` should track it as a shared-infrastructure defect; not filed as a per-study causal finding since it does not currently affect this study's actual contracts.
- (carried forward, unresolved) `discovered_parent_spec_md_drift` and `model_family_resolution` joblib-claim verification — both still open on contract-checker's side.

## Clean checks
A1–A5, B1–B7/B9/B10, C1–C3, F1–F4, G1–G4, H1–H4 clean — unchanged from pass 01–03; this re-freeze touched only the baseline comparison-reference mirror.

<!-- AUDIT_SUMMARY_V2_START -->
{"audit_type": "causal", "auditor": "lookahead-auditor", "study": "clean_maturity_flip_model_180s_horizon", "verdict": "CLEAR", "critical": 0, "warning": 0, "note": 1, "audited_execution_composite_sha256": "3280bcceb4e2ffcf266ce0af1bee122d92dc3de2d4e9b59cc1e07d8a26729c53"}
<!-- AUDIT_SUMMARY_V2_END -->
