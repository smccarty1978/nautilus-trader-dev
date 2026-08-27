# Contract Review — Pass 05
study: clean_maturity_flip_model_180s_horizon
audited_execution_composite_sha256: c8edd1e928e82898c0354179c72219898798d96c87a546209c6e5c01d60aa3ba
(re-verified fresh: audit/frozen_execution_manifest.json `frozen_execution_composite_sha256` = this value; audit/readiness.json `prepared_execution_identity` = this value, `overall_status: "PASS"`; audit/preflight.json `execution_composite_sha256` = this value, `status: "CLEAR"`, all 7 required checks PASSED, none missing)

## (1) Composite freshness — confirmed

Fresh and consistent across all three artifacts. Not stale.

## Adjudication of standing/referred findings

| Finding | Source | Disposition | Evidence |
|---|---|---|---|
| Pass-04 (contract) BLOCKED: `preexec_audit_seal.json` LOCKED at a superseded composite | my own pass 04 | **Adjudicated, not a fresh defect** | The coordinator has now confirmed the seal is intentionally not yet regenerated and will only be re-issued after *both* the causal reviewer's and this contract review's passes land `CLEAR` against `c8edd1e9...` — consistent with `AGENTS.md` §3's lifecycle order (`CAUSAL REVIEW -> CONTRACT REVIEW -> SEAL`). `artifacts/preexec_audit_seal.json` still shows `LOCKED` at `3280bcce...` — I re-confirm this is expected, current-and-not-yet-superseded-by-execution (no TRAIN COLLECT or model artifact exists, confirmed below), so it presents no live risk of a stale seal being relied upon. This is not re-raised as blocking this pass, but it remains true and must be resolved (re-run SEAL) before this study can proceed past this pair of reviews — noting it here so it isn't lost. |
| `research_decision.yaml:discovered_parent_spec_md_drift`, `model_family_resolution` joblib-claim | carried forward from causal pass 05 (`## Referred to contract-checker`) | **Already addressed in prior contract passes (01-03), unchanged this pass** | Baseline pin dropped + explicitly documented (pass 02/03); model_family_resolution corroborated via `models_long.json`/`models_short.json` manifest cross-check, joblib-deserialization limitation disclosed (pass 01, still true — no Python execution tool available this session). Neither file touched by this pass's edit. |
| `compiler.py` config/*.json mirror-staleness (repo-wide) | carried forward from causal pass 05 | **Unchanged, out of scope for this study, correctly not fixed repo-wide** | Root cause named in pass 02/03 (`compile_study.py` only rewrites `compiled_study.json`/`config/deliverables_contract.json` on recompile, other `config/*.json` mirrors are scaffold-once). `config/baseline.json` was hand-corrected as a study-local fix in pass 03 and remains correct (`"manifest_sha256": null`, still matches `compiled_study.json`). A repo-wide fix is out of scope for a single study's contract review. |

## (2) Hyperparameter-fidelity fix — verified adequate, does not reintroduce anything

Mechanically re-derived, not just re-read:

- `_enumerate_candidates` (`research_workflow/model_selection.py:178-185`), `search_method == "none"` branch: `Candidate(f.family, tuple(sorted((f.fixed_hyperparameters or {}).items())))` — reads **only** `fixed_hyperparameters`, nothing from `tunable_hyperparameters`, and injects no library defaults itself (those come later from whatever `fit_model(..., hyperparameters=cand.as_dict())` does with a partial dict, i.e. LightGBM's own constructor defaults for any key not supplied).
- `study.yaml`'s declared `model.selection.allowed_families[0]` (`study.yaml:129-132`, unchanged by this edit) fixes only `{verbosity: -1, random_state: 42}` and declares `num_leaves`/`max_depth`/`learning_rate`/`n_estimators` as `tunable_hyperparameters`. This **confirms the bug causal pass 05 caught was real**: reusing that object for a `search_method="none"` Phase-1 call would have produced candidates carrying only 2 of the 6 hyperparameters the study claims to hold fixed for the untuned comparison, silently substituting LightGBM library defaults for the other 4 — a genuine "declared vs. actual" experimental-control violation, distinct from (but adjacent to) the `model_family_resolution` finding.
- The fix (`research_decision.yaml:139-153`): Phase 1 now documents constructing its **own, separate** `ModelFamilySpec` with all six parent values (`n_estimators=200, learning_rate=0.05, max_depth=3, num_leaves=8, verbosity=-1, random_state=42`) as `fixed_hyperparameters` and no tunable domains — distinct from, and never substituted for, `study.yaml`'s declared object (which remains, unmodified, the correct input for Phase 2's bounded search). I confirmed `study.yaml:129-132`/`config/model_selection.json` were **not** touched by this edit (byte-identical to prior passes) — the fix lives entirely in the documented Phase-1 invocation protocol, which is the correct layer: `ModelSelectionSpec`'s schema has exactly one `allowed_families` slot per spec object, so a second, Phase-1-only spec object is the only way to hold six parameters fixed for Phase 1 while leaving four of them tunable for Phase 2 without the two phases interfering.
- Nothing is reintroduced: Phase 2's `mechanism` (`research_decision.yaml:182-190`) is untouched by this edit and still correctly uses the full `study.yaml` object including the bounded search space — the Phase-1 fix only adds a new, separate object; it does not alter Phase 2's.
- Same category of residual as before (already flagged by both reviewers, not new): this is a **documented instruction for a future implementation** — no Phase-1/Phase-2 orchestration code exists yet (no TRAIN COLLECT or FIT has run), so this is unverifiable against running code until that code is written. It is adequately flagged as such in both `research_decision.yaml` and causal pass 05's note, not overstated as already-enforced.

## (3) Standing findings re-confirmed unchanged

| Item | Status | Evidence |
|---|---|---|
| model_family_resolution | PASS (same disclosed limitation) | untouched this pass |
| Deliverables contract | PASS | `config/deliverables_contract.json` untouched |
| No premature TRAIN/OOS execution | PASS | `artifacts/` still contains only `phase0_source_manifest.json`, `research_decision_fidelity_report.json`, and the (expected-stale) `preexec_audit_seal.json` — no `train_*`/`models_*`/`oos_*` artifacts |
| `config/baseline.json` consistency | PASS | still `{"manifest_sha256": null, ...}`, matching `compiled_study.json` |
| Terminal label reachability, `lineage.parent_manifest_sha256` | PASS | unchanged |

## Blocking verdict

CLEAR

The hyperparameter-fidelity gap causal pass 05 referred to contract-checker is now fixed at the correct layer (a Phase-1-only `ModelFamilySpec`, documented as distinct from and never substituted for Phase 2's declared, unmodified object), verified against the actual `_enumerate_candidates`/`run_model_selection` code rather than taken on faith, and does not reintroduce the earlier 2023 chronology issue or alter Phase 2. Zero critical, zero warning against my own checklist this pass. The one outstanding item — `artifacts/preexec_audit_seal.json` still `LOCKED` at the superseded `3280bcce...` composite — is expected and by design per the stated review order (SEAL follows both reviews), not a defect I am raising against this pass; it must still be regenerated once the causal reviewer's parallel pass against `c8edd1e9...` also lands `CLEAR`, before any execution proceeds.

<!-- AUDIT_SUMMARY_V2_START -->
{"audit_type": "contract", "auditor": "contract-checker", "study": "clean_maturity_flip_model_180s_horizon", "verdict": "CLEAR", "critical": 0, "warning": 0, "note": 3, "not_verified": 0, "audited_execution_composite_sha256": "c8edd1e928e82898c0354179c72219898798d96c87a546209c6e5c01d60aa3ba"}
<!-- AUDIT_SUMMARY_V2_END -->
