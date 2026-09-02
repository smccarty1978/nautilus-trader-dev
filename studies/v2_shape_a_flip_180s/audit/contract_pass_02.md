---
audit_type: "contract"
study: v2_shape_a_flip_180s
auditor: contract-checker
---

# Contract & Governance Audit — v2_shape_a_flip_180s — pass 02

Re-audit trigger: closure changed (platform fix — coarser external timeframes now compile as
context streams). New composite `7676acfb42fa863b0d0aaae57ae1859e3340b4d549c66367cd68f871d04e1515`
supersedes pass 01's `b7792ad8515f...`. `research_workflow/grammar/compiler.py` hash changed
(`5413fd42...` → `46125a0c...`); `study.yaml` content unchanged (`spec_sha256` still
`c2b5daad43ac...`); `plan_sha256` changed (`1571ff25...` → `c291d966...`) reflecting the
recompiled plan.

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| Plan bound to spec, freshness bound to new composite | PASS | `compiled_plan.json:835` plan_sha256=`c291d96614549145e3295d3bb99c43b2275ffc34d75279cda52cc1154033093a`, `:948` spec_sha256=`c2b5daad43ac19fd23d453306398772febc26753fbf6fd41c2b67ae245c07856`; identical in `audit_packet_contract.json` and `audit/frozen_execution_manifest.json` | `readiness.json` `PLAN_BOUND_TO_SPEC`=PASSED | none |
| TRAIN/OOS/prohibited chronology disjoint | PASS | `experiment_authorization.json` train=[2021], oos=[2022], prohibited=[2023-2026]; packet chronology unchanged from pass 01 | `readiness.json` `CHRONOLOGY_ROLE_TABLE`=PASSED | none |
| Model year-role table: tuning-only 2021, no final-validation year | PASS | packet `model.validation.tuning_years=[2021]`, `final_train_validation_years=[]`, `year_role_table` unchanged from pass 01 | — | none |
| Authorization present, bound to new composite | PASS | `artifacts/experiment_authorization.json` regenerated `2026-09-02T19:19:08` (same timestamp as manifest), years unchanged | — | none |
| Readiness PASS bound to new composite | PASS | `audit/readiness.json`: `overall_status: PASS`, `execution_composite_sha256: 7676acfb42fa...` matches manifest; R9 `current=7676acfb42fa frozen=7676acfb42fa` | R1/R3/R5/R8/R9 all `passed: true` | none |
| Preflight CLEAR bound to new composite | PASS | `audit/preflight.json`: `status: CLEAR`, composite matches manifest; all 7 required checks PASSED | — | none |
| Tests PASS bound to new composite | PASS | `_work/controller/test_summary.json`: 34 passed / 0 failed (one more test than pass 01, consistent with the compiler fix), composite matches manifest | test files: `test_golden_fixture.py`, `test_grammar_v2.py`, `test_host_core.py` | none |
| Causal status CLEAR, distinct auditor, bound to new composite | PASS | `audit/status.json`: `verdict: CLEAR`, `auditor: lookahead-auditor`, `audited_execution_composite_sha256` matches manifest, `critical: 0`, report path `pass_02.md` (correctly re-audited, not stale `pass_01.md`) | — | none |
| Deliverables reachable: label column, entry reference | PASS | `compiled_plan.json:400,821` `target_flip_within_horizon`; `:803` `entry_reference: "next_bar_open"`; `:812` `label_column` matches | `readiness.json` `ENTRY_REFERENCE_EXECUTABLE`=PASSED | none |
| Dataset provenance | PASS | packet/manifest `instruments.NQ.dataset_digest=9e7aecb7a291...` unchanged, matches `research/datasets/NQ_1S_V2.yaml` | `R1_NQ` verified | none |
| No study Python | PASS | `Glob **/*.py` under study dir returns none | — | none |
| Model integrity: lightgbm, explicit params + random_state | PASS | packet `model.params` unchanged: `random_state:42`, single arm (`model.arms: []`) — arm-delta checks NOT APPLICABLE | — | none |

## Referred to lookahead-auditor
None — causal review already CLEAR on this composite under distinct identity `lookahead-auditor`.

## Blocking verdict
CLEAR

The re-freeze correctly produced a new composite (`7676acfb42fa...`) after the compiler fix, and every lifecycle artifact — readiness, preflight, causal status, test summary, authorization — was regenerated and reconciles to it (no stale pass-01 artifact was silently reused; `status.json` points at `pass_02.md`). `plan_sha256` changed as expected from the recompile while `spec_sha256` (study.yaml) is unchanged, confirming the plan/spec binding survived the platform fix without a spec edit. Chronology, label column, entry reference, dataset digest, absence of study Python, and model params are all unchanged and still compliant. No governance violation found.

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "contract", "study": "v2_shape_a_flip_180s", "auditor": "contract-checker", "audited_execution_composite_sha256": "7676acfb42fa863b0d0aaae57ae1859e3340b4d549c66367cd68f871d04e1515", "critical": 0, "warning": 0, "note": 1}
<!-- AUDIT_SUMMARY_V2_END -->
