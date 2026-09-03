---
audit_type: "contract"
study: v2_shape_c_barrier_race_fade
auditor: contract-checker
---

# Contract & Governance Audit — v2_shape_c_barrier_race_fade — pass 03

Composite audited: `51bc1054629d2a65b8e00489778bf7143cc00af1c6348f4ccb3e6399230420ce`
(`audit/frozen_execution_manifest.json`, generated `2026-09-02T23:15:01Z`).

Delta since pass 02: a host kernel change only (`research_workflow/host/outcomes.py` and
`research_workflow/target_replay_oracle.py` — the `first_bar_at_or_after` rule is now bounded
by the arm's session close). `study.yaml` itself was **not** edited.

**Correction to the initial task framing, confirmed:** `plan_sha256` changed
(`5655c7fbf30180566076fb433bc615ae1846c9b3ecdb25da6b40a1b43d866831` → `b252d6c0fc405a24d2c79546efef5fe3f5d62bf6e33a26df1dd7370c46ce58bb`)
while `spec_sha256` did **not** (`6af88d1207b9c60f3f81bfa3a97aa772df4430c76d3c12fea20194dd3f3cd069`
unchanged). The compiled plan folds the resolved execution closure into its own identity, so a
kernel-only change (no spec edit) still produces a new `plan_sha256`. This is expected behavior,
not a spec/plan binding defect — `PLAN_BOUND_TO_SPEC` still checks plan-vs-spec consistency, not
plan stability across kernel versions.

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| Plan bound to spec on the new composite | PASS | `compiled_plan.json` plan_sha256=`b252d6c0fc405a24d2c79546efef5fe3f5d62bf6e33a26df1dd7370c46ce58bb` (line 883), spec_sha256=`6af88d1207b9c60f3f81bfa3a97aa772df4430c76d3c12fea20194dd3f3cd069` (line 996); both match packet and `frozen_execution_manifest.json` exactly; spec_sha256 identical to pass 02, confirming no spec edit accompanied this kernel change | `readiness.json` `PLAN_BOUND_TO_SPEC`=PASSED | none |
| Readiness PASS bound to new composite | PASS | `overall_status: PASS`, `execution_composite_sha256` matches; R9 `current=51bc1054629d frozen=51bc1054629d`; R5 "16 primitives bound; unbound=[]" | R1/R3/R5/R8/R9 all `passed: true` | none |
| Preflight CLEAR bound to new composite | PASS | `status: CLEAR`, composite matches; all 7 required checks PASSED | — | none |
| Tests PASS bound to new composite | PASS | 37 passed / 0 failed (up from 36 in pass 02, consistent with new coverage for the session-close-bounded horizon-end rule), composite matches | 3 test files | none |
| Causal CLEAR bound to new composite | PASS | `audit/status.json`: `audit_report_path: pass_04.md`, `verdict: CLEAR`, `auditor: lookahead-auditor`, `audited_execution_composite_sha256` matches, `critical: 0` — correctly the newly-ingested pass 04, not a stale carryover | — | none |
| Chronology unchanged | PASS | `experiment_authorization.json` train=[2021], oos=[2022], prohibited=[2023-2026] — identical to pass 02 | `readiness.json` `CHRONOLOGY_ROLE_TABLE`=PASSED | none |
| Six model ids, labels unchanged | PASS | Same six ids/labels as pass 02 (`a9878a03...`→`target_tp1_sl0_5_label`, `98ab6190...`→`target_tp1_sl1_0_label`, `546e1a09...`→`target_tp1_sl1_5_label`, `1b285fe3...`→`target_tp1_sl0_5_label`, `45c2c622...`→`target_tp1_sl1_0_label`, `36ba0ed6...`→`target_tp1_sl1_5_label`); no `study.yaml` edit means no re-verification against the model store was needed beyond confirming the file is unchanged from pass 02 | — | none |
| Primary arm and expiry unchanged | PASS | `primary_arm: "barrier_tp_1_0_sl_1_0"`; all three arms still `"expiry": "censor"` | — | none |
| `model.mode: score` unchanged | PASS | packet top-level `model` block still `{"arms": [], "family": null, "params": {}, "validation": null}`; `study.yaml` unedited | — | none |
| No study Python | PASS | Unchanged from pass 02; kernel change is entirely inside `research_workflow/host/` and `research_workflow/target_replay_oracle.py`, not the study directory | — | none |

## Referred to lookahead-auditor
None — causal pass 04 already reviewed the session-close-bounded horizon-end-rule kernel change and returned CLEAR under distinct identity `lookahead-auditor`.

## Blocking verdict
CLEAR

All lifecycle artifacts (readiness, preflight, causal pass 04, tests, authorization) reconcile to the new audited composite `51bc1054629d...`. The plan is bound to the spec; `plan_sha256` changed because the plan folds in the resolved execution closure, while `spec_sha256` is unchanged, confirming no spec edit occurred alongside this host-kernel-only change. The six model ids, their labels, primary arm, censor expiry, score mode, and chronology are all unchanged from pass 02. No governance violation found.

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "contract", "study": "v2_shape_c_barrier_race_fade", "auditor": "contract-checker", "audited_execution_composite_sha256": "51bc1054629d2a65b8e00489778bf7143cc00af1c6348f4ccb3e6399230420ce", "critical": 0, "warning": 0, "note": 1}
<!-- AUDIT_SUMMARY_V2_END -->
