# Contract Review — Pass 10
study: clean_maturity_flip_model_180s_horizon
audited_execution_composite_sha256: 72d474e824e4ddd3b42b221a3465b8de305f02118cf0bfb5cd49bc44f40006bf
(re-verified fresh: audit/frozen_execution_manifest.json `frozen_execution_composite_sha256` = this value; audit/readiness.json `prepared_execution_identity` = this value, `overall_status: "PASS"`; audit/preflight.json `execution_composite_sha256` = this value, `status: "CLEAR"`, all 7 required checks PASSED)

## (1) Composite freshness — confirmed

## (2) Does the fix resolve the provenance gap? — Code-level: yes. This study's own real evidence trail: not yet.

I read the actual diff, not just the description:

- `_run_model_selection_to_named_manifest` (`implementation/two_phase_selection.py:127-144`) calls `run_model_selection`, then immediately `default_path.replace(out_path)` off the shared hardcoded path onto a caller-supplied name. `run_phase1_architecture_selection` now calls this helper for both its pr_auc and brier calls (lines 169-178), naming them `model_selection_manifest_phase1_{direction}_{prauc,brier}.json`. This is the exact rename-after-write pattern Phase 2/3 already used, applied correctly and consistently to Phase 1's two calls.
- `test_phase1_manifests_do_not_clobber_across_directions_or_metrics` (`tests/test_two_phase_selection.py:176-198`) runs Phase 1 for both LONG and SHORT against a shared temp study directory, asserts all four named files exist, and — importantly — also asserts `not (artifacts_dir / "model_selection_manifest.json").exists()`, i.e. the shared default path is never left behind either. I read this test body directly; it is a genuine, correctly-targeted regression proof, not a superficial existence check. **In a fresh/future run of Phase 1, this gap is now code-level guaranteed closed, not just this-run-lucky.**

**However — checking the real study's own artifacts, not only the test, surfaces something the coordinator's message does not claim to have addressed:** `studies/clean_maturity_flip_model_180s_horizon/artifacts/` still contains only the **old, stale, pre-fix** `model_selection_manifest.json` (I re-read it: `primary_selection_metric: "brier"`, the SHORT-direction call's leftover content, unchanged from pass 09) and `two_phase_selection_phase1_only_summary.json`. **None of the four new `model_selection_manifest_phase1_{long,short}_{prauc,brier}.json` files exist in this study's real `artifacts/` directory** — I globbed for them specifically and found zero matches. The real Phase 1 execution that already happened (and produced the Arm-C-wins-both decision this study is relying on) was run under the **old, buggy** code; it has not been re-run under the fix. The fix is proven correct in a sandboxed `tempfile.mkdtemp()` test, but this study's own actual evidence trail for its real, already-completed Phase 1 selection still exhibits exactly the defect I found in pass 09 — three of the four real governed calls (LONG pr_auc, LONG brier, SHORT pr_auc) still have no durable, independently-hashed artifact on disk; only `two_phase_selection_phase1_only_summary.json` (a hand-assembled capture, not a code-guaranteed one) covers the gap for this study's real results, exactly as before.

**This is not the same finding restated for its own sake — it is a narrower, more precise version of it:** the code defect is fixed and will not recur on any *future* invocation; what remains open is that this study's own already-executed Phase 1 has not yet been re-run to benefit from that fix and produce the four durable artifacts a real audit of *this study's* results would want to find. Since Phase 1 uses only frozen 2021/2022 TRAIN data that has not changed, re-running it is cheap and deterministic (no new data collection, no re-authorization) — but it has not happened yet.

## (3) Standing findings re-confirmed unchanged

| Item | Status | Evidence |
|---|---|---|
| model_family_resolution | PASS (same disclosed limitation) | untouched this pass |
| `config/baseline.json` consistency | PASS | still no stale hash present |
| `model.params.random_state` dormant note | Still present, unchanged | not touched by this pass |
| TRAIN/OOS separation | PASS | `experiment_authorization.json` unchanged, disjoint years |
| `pre_fit` gate opt-in status, deliverables, terminal-label reachability, `lineage.parent_manifest_sha256` | PASS | unaffected by this pass |

## Blocking verdict

CLEAR, with one WARNING (narrowed from pass 09, not newly invented)

The code fix and its regression test are real, correctly targeted, and verified by direct reading — this closes the gap for any future run. I am not marking warning=0, because the actual artifact trail for **this study's own already-completed real Phase 1 selection** still lacks durable per-call manifests for three of its four real governed calls; only re-running Phase 1 under the now-fixed code (cheap, since 2021/2022 TRAIN data is unchanged and frozen) closes this for the results this study will actually rely on going into Phase 2/3 and FIT. Smallest remediation: re-run `run_phase1_architecture_selection` for both directions now that the fix exists, confirm the four named manifests appear in the real `artifacts/` directory (not just in a test's tempdir), and only then treat this finding as fully closed.

<!-- AUDIT_SUMMARY_V2_START -->
{"audit_type": "contract", "auditor": "contract-checker", "study": "clean_maturity_flip_model_180s_horizon", "verdict": "CLEAR", "critical": 0, "warning": 1, "note": 0, "not_verified": 0, "audited_execution_composite_sha256": "72d474e824e4ddd3b42b221a3465b8de305f02118cf0bfb5cd49bc44f40006bf"}
<!-- AUDIT_SUMMARY_V2_END -->
