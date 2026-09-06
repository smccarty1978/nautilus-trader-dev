# Analysis / Decision — `supv1_shape_a_flip_180s_r2`

**Phase D · analysis-decider · task `004_analysis_decision_f5693305`**
Branch `study/supv1_shape_a_flip_180s_r2` @ `03efe463` · platform `59c53310` · execution composite `ee051527aa24`

---

## Question

Supervisor V1 final clean validation: a rerun of the closed reference study `v2_shape_a_flip_180s`.
This is an infrastructure audit, not new research. Does the Research Supervisor drive a Shape-A study
from design through OOS scoring with disposable workers only, and does the rerun reconcile with the
reference within explained platform drift?

## Verdict

**`SUPERVISOR_V1_VALIDATED_END_TO_END`** — outcome `REPRODUCED_BIT_IDENTICAL_CLEAN_RUN`.

Both planes pass, and the research plane passes more strongly than the first validation did: this run
does not merely *reconcile* with the previous supervised rerun, it reproduces it **bit for bit** —
across a platform change.

---

## Control plane

| Check | Value | Artifact |
|---|---|---|
| Stages executed | `smoke, collection, reconcile, merge, fit, freeze, oos, analyze` → `READY_TO_CLOSE` | `_work/controller/status.json` |
| Tests | 110 passed / 0 failed at the executed composite | `_work/controller/test_summary.json` |
| Workers | 4 disposable (design/compile, causal audit, contract audit, this analysis) | supervisor `state.json` |
| Retries | none — every `attempts` entry is 0 or 1; `blocker_streak` 0, `last_blocker_code` null | supervisor `state.json` |
| Human input | `user_interventions` 0, `worker_permission_denials` 0, `user_intervention_required` false | supervisor `state.json` |
| Cost / turns / wall | $4.835764, 56 worker turns, 100 ticks, ~63 min (05:44:34Z → 06:47:30Z) | supervisor `state.json` |
| Causal audit | **CLEAR** — 0 critical, 0 warning, 3 note | `audit/status.json` |
| Contract audit | **CLEAR** — 0 critical, 0 warning, 3 note | `audit/contract_status.json` |
| Seal freshness | one composite `ee051527aa24…` across both audits, the seal, smoke, reconcile, the freeze and the controller card | `artifacts/preexec_audit_seal.json` |
| Smoke | ACCEPTED, 5/5 checks true, 1591/1591 candidates/observations, `pending_at_end` 0, dataset bytes VERIFIED | `artifacts/smoke_acceptance.json` |
| Worktree hygiene | `unsafe_dirty_paths []`; dirty paths only the study's own `artifacts/` + `audit/` | `_work/controller/status.json` |

The first validation (`supv1_shape_a_flip_180s`) needed a repair worker and closed its contract audit
with 4 warnings. This one needed neither: **0 critical and 0 warning on both audits**, no repair
worker, no retry.

The defect that validation found — the collection closure freezing tracker binding shims but not the
modules they import (finding **C-1**) — is closed at the root. This run's frozen execution manifest
carries **90 closure files** (transitive AST import walk; the pre-fix reference closure was 45), fix
commit `0baeb4ef`, regression test `research_workflow/tests/test_closure_transitive_imports.py`.

## Research plane

### vs. the previous supervised rerun — bit-identical

| Quantity | r2 | `supv1_shape_a_flip_180s` |
|---|---|---|
| 2021 candidates_sha256 | `fa67317ab842…` | **same** |
| 2021 observations_sha256 | `136855e9bd0a…` | **same** |
| Canonical booster bytes | `1fcba0d0af4d…` | **same** |
| OOS ROC-AUC | 0.6839063744812204 | **same** |
| OOS PR-AUC | 0.2833249768282369 | **same** |
| OOS Brier | 0.12747480848769988 | **same** |
| OOS n / rows | 472412 / 475484 | **same** |
| Dispositions | 3072 / 396149 / 76263 | **same** |

The compiled plans differ in **7 leaves**: `study.id`, the two spec/plan hashes it induces, three
closure composites, and exactly one closure **file** — `research_workflow/lifecycle_v2.py`, changed by
the supervisor efficiency-closeout merge `59c53310`. So the two runs executed at *different* composites
(`ee051527` vs `34a0dab4`) and produced identical candidates, identical observations, identical booster
bytes and identical scores. **That merge is demonstrably research-plane inert** — which is exactly what
a rerun-under-drift is supposed to establish.

### vs. the pre-supervisor reference — the same explained calendar drift

| Metric | r2 | reference `v2_shape_a_flip_180s` | Δ |
|---|---|---|---|
| ROC-AUC | 0.6839063744812204 | 0.6840183909705739 | −1.1202e−04 (−0.0164 %) |
| PR-AUC | 0.2833249768282369 | 0.2837433596501728 | −4.1838e−04 (−0.1475 %) |
| Brier | 0.12747480848769988 | 0.12743993396360057 | +3.4875e−05 (+0.0274 %) |
| rows | 475484 | 475529 | −45 (−0.0095 %) |
| CENSORED | 3072 (0.6461 %) | 3003 (0.6315 %) | **+69** |
| LABELED_NEGATIVE | 396149 | 396263 | **−114** |
| LABELED_POSITIVE | 76263 | 76263 | **0** |

The positive class is **exactly conserved**; 69 rows move negative → censored and 45 candidates leave
the population. Every delta lands where the 180s horizon meets the session close, never on the label
kernel — consistent with the platform additions the plan diff shows: `session.kind` `legacy` →
`calendar`, six session + six instrument reference tables, and `outcome` gaining `session_end_rule=censor`,
`horizon_end_rule=strict`, `strict_gap_rule` and `resolution_precedence [SESSION_END, GAP, BARRIER_TOUCH,
HORIZON_EXPIRY]`. Of 218 differing leaves, 22 sit outside hash/timestamp/closure fields: **21 are those
platform additions, 1 is `study.id`.** `study.yaml` itself is the reference verbatim except the id.

TRAIN: candidates are byte-identical to the reference (453768 rows, `fa67317ab842…`); 12 rows
(0.0027 %) lost their binary label (451089 vs 451101 fit rows) — the same session-boundary effect.

### Model integrity

Refit, not inherited: `new_models_trained` true, `reference_models []`, `model_id 1bc300d1…` ≠ previous
`9c470bd8…` ≠ reference `fad4c0e9…` (the lineage id binds `plan_sha256`). Authenticated against its own
lineage: golden **PASS**, `max_abs_diff` 0.0 on 256 rows, `identity_rule v2_lineage_sha256`, tier
`registry`. Single arm (`primary` / cell `all` / direction `both`), 13 features, 451089 fit rows over
3883 unique regimes.

### Authority

train `[2021]`, oos `[2022]`, prohibited `[2023, 2024, 2025, 2026]`; only `train-2021` and `oos-2022`
collections ran; `authorization_sha256 6381990dc94f…` is bound into the train freeze.

---

## Integrity checks performed

- **Arm-delta integrity** — *not applicable*, and no arm delta is claimed: one model, `paired_deltas_vs_baseline_arm {}`, `month_folds []`.
- **Refit vs. reuse** — PASS (`new_models_trained` true, `reference_models []`, distinct `model_id`).
- **Model authentication** — PASS (golden 0.0 max abs diff on 256 rows).
- **Seal freshness** — PASS (one composite across audits, seal, smoke, reconcile, freeze, controller).
- **Matched populations** — PASS (identical `candidates_sha256` across all three runs).
- **Censoring** — PASS (CENSORED never treated as resolved; unresolved fraction 0.6461 % reported; positive rate quoted over labeled rows only).
- **TRAIN/OOS separation** — PASS (contract year-role call table PASS; no prohibited year touched).
- **Worktree hygiene** — PASS (`unsafe_dirty_paths []`).

## Caveats

1. **Nothing was tuned.** Contract NOTE 1: `validation.model_selection.random` is declared with no
   `search_space` and no production caller, so the fit used `model.params` verbatim. `train_metrics`
   folds/tuning/final_validation are all null and no `tuning_trials.json` exists. No downstream text may
   call these hyperparameters tuned or validated.
2. **2022 is dev *and* OOS**, with `final_train_validation_years []` (contract NOTE 2). Read once here,
   which is legitimate — but the study holds no spare out-of-sample year.
3. **`dataset_id: NQ_1S_V2` is the SUPERSEDED pre-Globex build, and that is deliberate**: `SPEC.md`
   requires copying the reference study unchanged and `research_decision.yaml` sets
   `calendar_reference_parity: common_interval_exact`, so parity against the reference is the point
   (causal NOTE F1/F4, explicitly adjudicated). Tape bytes are identical to `NQ_1S_V2_GLOBEX`
   (`logical_digest 9e7aecb7…`); only the session reference table differs. PLATFORM_STATE warning
   **W-1** — no compile gate refuses a superseded dataset id — remains open. That is a platform finding,
   not a supervisor failure.
4. Causal NOTE C2: `inclusive_start: true` admits zero-lead positives the feature snapshot cannot see.
   The asymmetry runs the safe way (it dilutes the positive class); documented and tested convention.
5. Causal NOTE F2/G2: `GAP` sits in `resolution_precedence` but `max_gap_ns` is null, so an intra-RTH
   halt inside a 180s horizon resolves on post-halt regime state. Hygiene only; `SESSION_END` outranks it.
6. **Scope.** One study shape, one dataset, one instrument, two partition years, ~63 minutes, and
   nothing failed. This is not a proof of unattended readiness under adversarial conditions.

## What would change the verdict

- Any critical finding in either pre-execution audit, or an audited composite ≠ the executed one.
- Any divergence from the previous supervised rerun, or drift beyond the calendar envelope vs. the
  reference, without a named platform change that accounts for it.
- A disposition delta touching `LABELED_POSITIVE`, or population change away from the session boundary
  — that would mean the label kernel moved, not the calendar.
- A reused model (`reference_models` non-empty, or `model_id` equal to the reference's), or a golden
  authentication other than PASS.
- Any collection touching a prohibited year, or a worker writing outside its declared surface.

## Verdict scope

This is evidence about the **supervisor and the platform**, not new evidence about the research
question. Whether the 13-feature causal surface at T predicts a prevailing 1m regime flip within 180s
remains the reference study's conclusion; this rerun only shows the machinery reproduces it — now
twice, and the second time bit-identically.

## Next decision

1. Supervisor V1 reproduces a Shape-A study deterministically **when nothing goes wrong**. The open
   question is failure behaviour: does it recover correctly from an injected worker `BLOCKED`, a stale
   seal and a killed controller, with no human input and without widening a worker's write surface?
2. Does the same end-to-end reproduction hold for Shape B (deep pullback 5s) and Shape C (barrier race
   fade), or is this validation Shape-A specific?
3. Should the platform refuse a superseded dataset id at compile time (W-1), given a study can still
   silently bind the pre-Globex session table?
