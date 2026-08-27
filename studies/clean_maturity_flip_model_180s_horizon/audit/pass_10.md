# Look-Ahead & Timestamp Audit — Pass 10

**Date** 2026-08-27 · **Scope** `study.yaml:model.selection.secondary_metrics` fix, `research_workflow/model_selection.py::_METRIC_FNS`, `research_decision.yaml` (checked for a stray inconsistent metric list), new test `test_study_yaml_secondary_metrics_are_registry_supported` (`tests/test_two_phase_selection.py`), `audit/{preflight,readiness,lint,frozen_execution_manifest}.json` · **Scope hash (frozen execution composite)** `864a2a1ff2039bdc20571e0b228396699f6f3ffe8f609953e3f379218e91039d` · **Lint** 0 critical / 0 warning (`audit/lint.json`, 100/100 files, 100% coverage) · **Verdict** `CLEAR`

## Summary
Critical: 0 · Warning: 0 · Note: 1

## Prior findings adjudicated
| # | Finding | Status | Evidence |
|---|---|---|---|
| 1 | pass 09 referrals (parent SPEC.md drift, `model_family_resolution` joblib claim, `model.params` random_state landmine, optional `pre_fit` gate adoption) | WITHDRAWN (not re-raised; untouched this pass, still open on contract-checker's side / researcher's discretion) | unchanged this pass |

This is not itself a causal (look-ahead/timestamp) defect — it is a metric-registry naming mismatch that fails at Phase 2/3 dispatch time, not a timing or feature/label-separation issue — but I traced it fully since it was flagged for this pass and touches the same `model.selection` object I've been verifying since pass 05.

## (1) Composite freshness
`864a2a1ff2039bdc20571e0b228396699f6f3ffe8f609953e3f379218e91039d` matches exactly across `audit/frozen_execution_manifest.json`, `audit/preflight.json` (`status: CLEAR`), and `audit/readiness.json` (`prepared_execution_identity`, `overall_status: PASS`). `audit/lint.json` unchanged at 100/100 files (this fix only edited existing tracked files' content).

## (2) `secondary_metrics` fix — complete and correct
- `study.yaml:192-193` now declares `secondary_metrics: [brier]` only. `compiled_study.json` (both the raw `spec.model.selection.secondary_metrics` at line 263 and the `contracts.model_selection.secondary_metrics` at line 1126) reflects exactly `["brier"]` — the fix reached the compiled artifact, not just the source file.
- `research_workflow/model_selection.py::_METRIC_FNS = {"roc_auc": roc_auc, "pr_auc": pr_auc, "brier": brier}` (confirmed by direct read, not assumption) — `"brier"` is a registered key; the four removed names (`brier_score`, `precision_at_p90`, `precision_at_p95`, `precision_at_p97_5`, `resolved_count`) never were.
- **`research_decision.yaml` does not declare an inconsistent list anywhere.** Grepped for `brier_score`/`secondary_metric`/`_METRIC_FNS`/`deterministic_tie_break_order`: the only hits are two prose strings — `"brier_score (lower wins)"` in `architecture_selection_protocol`/`bounded_tuning_protocol`'s `deterministic_tie_break_order` (a human-readable tie-break description, not a list consumed by any parser) and `"calibration_curve_and_brier_score"` in `required_diagnostics_not_selection_criteria` (a descriptive diagnostic label). I checked `scripts/check_research_decision_fidelity.py` directly — **zero** references to `brier_score`, `_METRIC_FNS`, `secondary_metric`, or `deterministic_tie_break_order` — confirming research_decision.yaml has no machine-consumed field this bug could also live in, matching the claim exactly. (Minor, non-blocking naming inconsistency: the prose still says "brier_score" where the registry key is "brier" — cosmetic, never parsed as a metric name; noted below, not filed as a finding.)
- Confirmed `two_phase_selection.py`'s own Phase 1 code (`phase1_selection_spec(primary_metric="brier", direction="minimize")`, read in pass 07) already used the correct registry name — the bug was isolated to `study.yaml`'s declared object used by the real Phase 2/3 dispatch, exactly as described.

## (3) Would the new test have caught the original bug? Traced the mechanics, not assumed
`test_study_yaml_secondary_metrics_are_registry_supported` (`tests/test_two_phase_selection.py:277-297`) re-reads `study.yaml` from disk on every run (no baked/cached expectation) and imports `_METRIC_FNS` live from `research_workflow.model_selection`. Substituting the **original** declared value (recorded independently in my own pass-01 read of `config/model_selection.json`: `secondary_metrics: [brier_score, precision_at_p90, precision_at_p95, precision_at_p97_5, resolved_count]`):
```
declared   = ["brier_score", "precision_at_p90", "precision_at_p95", "precision_at_p97_5", "resolved_count"]
_METRIC_FNS = {"roc_auc", "pr_auc", "brier"}
unsupported = [m for m in declared if m not in _METRIC_FNS]   # -> all 5 names, non-empty
assert not unsupported                                        # -> FAILS
```
All five original names are absent from `_METRIC_FNS`, so `unsupported` is non-empty and the `assert not unsupported` statement fails deterministically — this is a mechanical trace against the actual registry contents and the actual original file content, not a description of what the test is *supposed* to do. The test is genuinely a regression guard for this exact defect class, not a test that happens to pass either way.

## Critical findings
None.

## Warnings
None.

## Notes
### [NOTE] `research_decision.yaml`'s prose still says "brier_score" where the registry key is "brier"
Cosmetic only — confirmed (§2) this string is never parsed as an executable metric name by any deterministic gate (`check_research_decision_fidelity.py` has no reference to it). Worth a documentation touch-up for a future pass, not a defect.

## Referred to contract-checker
- (carried forward, unresolved) `discovered_parent_spec_md_drift`, `model_family_resolution` joblib-claim verification, `model.params` dormant `random_state` landmine, optional `pre_fit` gate adoption.

## Clean checks
A1–A5, B1–B7/B9/B10, C1–C3, F1–F4, G1–G4, H1–H4 clean — this fix touched only a search-time metric-name declaration (not a timing, population, feature, or chronology field); re-confirmed `session`, `age_gate_seconds`, `horizon_seconds`, `feature_list_sha256`, `tuning_years`, `final_train_validation_years` all byte-identical to pass 09.

<!-- AUDIT_SUMMARY_V2_START -->
{"audit_type": "causal", "auditor": "lookahead-auditor", "study": "clean_maturity_flip_model_180s_horizon", "verdict": "CLEAR", "critical": 0, "warning": 0, "note": 1, "audited_execution_composite_sha256": "864a2a1ff2039bdc20571e0b228396699f6f3ffe8f609953e3f379218e91039d"}
<!-- AUDIT_SUMMARY_V2_END -->
