---
audit_type: "contract"
study: v2_shape_c_barrier_race_fade
auditor: contract-checker
---

# Contract & Governance Audit — v2_shape_c_barrier_race_fade — pass 01

Composite audited: `7676acfb42fa863b0d0aaae57ae1859e3340b4d549c66367cd68f871d04e1515`
(`audit/frozen_execution_manifest.json`, generated `2026-09-02T19:19:45Z`; same platform-fix
composite shared with Shape A pass 02).

**Path correction:** the task specified the model store at
`.nt_research\models\registry\<id>\manifest.json`. That path does not exist — no
`.nt_research\models\registry\` directory exists at all. The live model store is
`.nt_research\models\models\<id>\manifest.json`. All six declared model ids were located and
verified there; this is noted as a path-naming discrepancy in the task brief, not a study
defect.

| Requirement | Verdict | Code evidence | Test evidence | Smallest remediation |
|---|---|---|---|---|
| Plan bound to spec | PASS | `compiled_plan.json:882` plan_sha256=`1d10914656e732f42af1fc16b63c05d01cb13babbdc825ae8ef2802814748df5`, `:995` spec_sha256=`22c65108c2db9bb14b58ff5ba88a35f30138be9eef8da3145ff288494d3ed20a`; matches packet and manifest | `readiness.json` `PLAN_BOUND_TO_SPEC`=PASSED | none |
| Chronology disjoint | PASS | `study.yaml:73-77`, `experiment_authorization.json` train=[2021], oos=[2022], prohibited=[2023-2026] | `readiness.json` `CHRONOLOGY_ROLE_TABLE`=PASSED | none |
| Readiness PASS bound to composite | PASS | `overall_status: PASS`, composite matches; R9 `current=7676acfb42fa frozen=7676acfb42fa`; R5 "16 primitives bound; unbound=[]" | R1/R3/R5/R8/R9 all `passed: true` | none |
| Preflight CLEAR bound to composite | PASS | `status: CLEAR`, composite matches; all 7 checks PASSED | — | none |
| Tests PASS bound to composite | PASS | 34 passed / 0 failed, composite matches | 3 test files | none |
| Causal status CLEAR, distinct auditor | PASS | `verdict: CLEAR`, `auditor: lookahead-auditor`, composite matches, `critical: 0` | — | none |
| Six model ids exist in the model store with tier=registry, selection_status=selected, train_years=[2021] only | PASS | Read `.nt_research\models\models\<id>\manifest.json` for all six ids in `study.yaml:81-86`. Each: `"tier": "registry"`, `"selection_status": "selected"`, `lineage.train_years: [2021]`, `lineage.validation_years: []` — no id shows 2022+ in train_years. Cell/direction/target_arm fields align exactly with the study's declared name/subset/label per id (e.g. `a9878a03...` → `cell_id: LONG_SL0_5`, `direction: LONG`, `target_arm: SL0_5`, matching `study.yaml:81` `LONG_SL0_5`/`regime_direction:-1`/`target_tp1_sl0_5_label`) | — | none |
| Each declared label is an arm label column of the plan | PASS | `compiled_plan.json` observation columns include `target_tp1_sl0_5_label`, `target_tp1_sl1_0_label`, `target_tp1_sl1_5_label` (lines 407-418, 863-874) — the three labels referenced across the six `model.models[].label` entries in `study.yaml:81-86` are exactly this set | — | none |
| Primary arm and expiry policy declared | PASS | `compiled_plan.json:876` `primary_arm: "barrier_tp_1_0_sl_1_0"`; each of the 3 arms carries `"expiry": "censor"` (lines 815, 823, 831), matching `study.yaml:66-72` `barrier.expiry: censor` and per-arm definitions | — | none |
| `model.mode: score` — no new models trained | PASS | `study.yaml:79` `mode: score`; `compiled_plan.json:756` `"mode": "score"`. Packet's top-level `model` block is `{"arms": [], "family": null, "params": {}, "validation": null}` — no training hyperparameters or validation protocol declared, consistent with a pure scoring study. The `fit` stage deliverable (`artifacts/experiment_models.json`) in score mode records the six frozen model references only; no `train_experiment_freeze.json`-style fitting occurs for this study's own models (Shape C freezes and trains nothing — it consumes pre-selected registry models) | — | none |
| No study Python | PASS | `Glob **/*.py` under `studies/v2_shape_c_barrier_race_fade` returns none | — | none |

## Referred to lookahead-auditor
None — causal review already CLEAR on this composite under distinct identity `lookahead-auditor`.

## Blocking verdict
CLEAR

All lifecycle artifacts reconcile to the audited composite `7676acfb42fa...`. Chronology is
disjoint. All six frozen models declared in `study.yaml` were verified to exist in the live
model store (at `.nt_research\models\models\<id>\`, not the `registry\<id>\` path named in the
task — a path-naming discrepancy in the brief, not a defect in the study or store), each with
`tier: registry`, `selection_status: selected`, and `train_years: [2021]` only — never 2022 or
later. Each model's declared label, direction and subset match the plan's arm label columns
exactly. `model.mode: score`, the primary arm, and censor expiry are all declared and compiled
consistently, and the packet's empty top-level `model` block confirms no new-model training
protocol exists for this study. No study Python exists. No governance violation found.

<!-- AUDIT_SUMMARY_V2_START -->
{"verdict": "CLEAR", "audit_type": "contract", "study": "v2_shape_c_barrier_race_fade", "auditor": "contract-checker", "audited_execution_composite_sha256": "7676acfb42fa863b0d0aaae57ae1859e3340b4d549c66367cd68f871d04e1515", "critical": 0, "warning": 0, "note": 1}
<!-- AUDIT_SUMMARY_V2_END -->
