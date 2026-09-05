# Analysis / Decision — `supv1_shape_a_flip_180s`

- **Role:** analysis-decider · **Task:** `007_analysis_decision_603846c1` · **Phase:** D
- **Source commit:** `1149543b` · **Platform commit:** `66578afa`
- **Plan:** `1c61753e6e00…` · **Execution composite:** `34a0dab471d8…`
- **Machine-readable twin:** `artifacts/analysis_decision.json`

---

## Question

From `research_decision.yaml`:

> Supervisor V1 validation rerun of the closed reference study `v2_shape_a_flip_180s`.
> **This is an infrastructure audit, not new research.**

`terminal_decisions: {reference_study: v2_shape_a_flip_180s, purpose: supervisor_v1_validation}`.
The scientific question in `study.yaml` — *does the 13-feature causal surface at T predict a
prevailing 1m regime flip within 180s?* — is the **reference study's** question. It is answered
here only in the sense of "does the machinery land on the same number".

## Verdict

| | |
|---|---|
| **outcome** | `REPRODUCED_WITHIN_PLATFORM_DRIFT` |
| **terminal_decision** | `SUPERVISOR_V1_VALIDATED_END_TO_END` |

The Research Supervisor drove the whole Shape-A lifecycle with one disposable worker per phase
and zero study Python, and landed on the reference study's result. Every residual difference is
bounded, one-directional, and traces to **declared platform-version drift** — not to the
supervisor.

## Evidence

Every number below carries its artifact path. A number without a path is not evidence.

### 1. The spec is the reference, verbatim

| check | result | source |
|---|---|---|
| `study.yaml` diff vs reference | **1 line** — `study.id` only | `studies/{supv1,v2}_shape_a_flip_180s/study.yaml` |
| compiled-plan differing leaves | 218 total | `compiled_plan.json`, both studies |
| … outside closure / hash / timestamp fields | 22 | ” |
| … that are platform-version additions | **21** | ” |
| … study-authored | **1** (`study.id`) | ” |

The 21 platform additions, in full:

- `session.kind`: `legacy` → `calendar`, plus 6 `session.reference_tables`
  (`gaps, holidays, maintenance, out_of_calendar, rolls, sessions`) and the same 6 under
  `instruments.NQ.reference_tables` (`instruments.NQ.calendar_table` `false` → absent)
- `outcome.session_end_rule: censor`, `outcome.horizon_end_rule: strict`,
  `outcome.strict_gap_rule`, and `outcome.resolution_precedence:
  [SESSION_END, GAP, BARRIER_TOUCH, HORIZON_EXPIRY]`

No population, feature, chronology, model or outcome-kernel field moved.

### 2. The lifecycle actually ran

`_work/controller/status.json`: `actions_executed = [collection, reconcile, merge, fit, freeze,
oos, analyze]`, `state = READY_TO_CLOSE`, tests **110 passed / 0 failed**,
`unsafe_dirty_paths = []`.

Smoke (`artifacts/smoke_acceptance.json`): `ACCEPTED` / `PASS` at the sealed composite,
all five checks true, 1591 candidates → 1591 observations, `pending_at_end 0`,
dataset `bytes_verification: VERIFIED`.

### 3. 2021 TRAIN candidates are **byte-identical** to the reference

| | rerun | reference |
|---|---|---|
| `candidates_sha256` | `fa67317ab842…` | `fa67317ab842…` |
| `candidates_identity` | `0d2166efae01…` | `0d2166efae01…` |
| merged rows | 453 768 | 453 768 |
| `observations_sha256` | `136855e9bd0a…` | `cc3dc51b5662…` |
| binary fit rows | 451 089 | 451 101 |

Source: `artifacts/train_experiment_freeze.json` in both studies, and
`artifacts/experiment_models.json`.

Candidate *generation* is bit-reproducible across the platform version. Only **12 TRAIN rows**
(0.0027%) changed from binary-labeled to censored.

### 4. OOS 2022 metrics reproduce to four decimal places

| metric | rerun | reference | Δ | Δ rel |
|---|---|---|---|---|
| ROC-AUC | 0.683906374 | 0.684018391 | −1.1202e−4 | **−0.0164 %** |
| PR-AUC | 0.283324977 | 0.283743360 | −4.1838e−4 | −0.1475 % |
| Brier | 0.127474808 | 0.127439934 | +3.4875e−5 | +0.0274 % |
| n | 472 412 | 472 526 | −114 | −0.0241 % |

Source: `artifacts/experiment_analysis_v2.json`, both studies. Authority
`plan.chronology.dev` = 2022.

### 5. The label kernel is untouched — the drift sits on the session boundary

| disposition | rerun | reference | Δ |
|---|---|---|---|
| `LABELED_POSITIVE` | 76 263 | 76 263 | **0** |
| `LABELED_NEGATIVE` | 396 149 | 396 263 | −114 |
| `CENSORED` | 3 072 | 3 003 | +69 |
| rows | 475 484 | 475 529 | −45 (0.0095 %) |

This is the load-bearing observation. The positive class is **exactly conserved**; 69 negatives
became censored and 45 candidates left the population. That is the signature of
`resolution_precedence` putting `SESSION_END` first against a calendar-derived session boundary
— it can only reclassify rows whose 180 s horizon crosses the close, and a row that flipped
inside the horizon flips regardless. Had the flip kernel itself moved, positives would have moved.

- unresolved (CENSORED) fraction: **0.6461 %** vs 0.6315 %
- OOS positive rate among labeled rows: **16.1433 %** vs 16.1394 %

### 6. The model is this run's, and it authenticates

- `model_id` `9c470bd8bb51…` ≠ reference `fad4c0e93766…` → genuinely refit, not inherited
- `new_models_trained: true`, `reference_models: []`
- feature list (13) and hyperparameter dict identical to the reference,
  `label_column: target_flip_within_horizon` in both
- golden replay **PASS**, `max_abs_diff 0.0` over 256 rows, `identity_rule v2_lineage_sha256`,
  `canonical_sha256 1fcba0d0af4d…`, tier `registry`, `selection_status selected`

Sources: `artifacts/experiment_models.json`, `artifacts/experiment_analysis_v2.json`.

### 7. Governance held

- causal audit **CLEAR** — 0 critical / 0 warning / 4 note (`audit/status.json`)
- contract audit **CLEAR** — 0 critical / 4 warning / 4 note (`audit/contract_status.json`)
- both `audited_execution_composite_sha256 = 34a0dab471d8…`, which equals the train freeze's
  `execution_composite_sha256` and the smoke's `execution_manifest_composite_sha256` — the
  audits vouch for the bytes that actually ran
- `artifacts/preexec_audit_seal.json` binds both audit reports into
  `composite_seal_hash 8bfc08a39c8c…`, matching the smoke's `sealed_composite_sha256`
- years: train `[2021]`, oos `[2022]`, prohibited `[2023, 2024, 2025, 2026]` untouched;
  `authorization_sha256 7a745b4ce183…` bound into the freeze

### 8. The audit found a real defect — that is the point of running it

Contract-audit finding **C-1**: the collection closure froze the tracker *binding shims* but not
the modules they import — including `features/trackers/regime_dual_ema.py`, which **is the label
event**. Editing those left `R9_closure_current`, the preflight `EXECUTION_MANIFEST`, the freeze
and every seal passing. Fixed at the root by a transitive AST import walk over repo-local modules
(closure **45 → 90 files**), regression test
`research_workflow/tests/test_closure_transitive_imports.py`, fix commit `0baeb4ef`
(`PLATFORM_STATE.json` → `closure_resolution`).

## Integrity checks performed

| check | result |
|---|---|
| arm-delta integrity (identical `fit_identity` / `prediction_identity`) | **N/A** — single arm `primary`, `paired_deltas_vs_baseline_arm` empty, `month_folds` empty. **No arm delta is claimed anywhere in this decision.** |
| model artifact is this run's, not the reference's | PASS — `model_id` and `canonical_sha256` both differ; `reference_models` empty |
| model authenticates (golden replay) | PASS — `max_abs_diff 0.0` / 256 rows |
| feature contract + hyperparameters identical to reference | PASS — element-for-element |
| audits CLEAR **and** bound to the composite that executed | PASS — `34a0dab471d8` throughout |
| censoring respected, unresolved fraction reported | PASS — 0.6461 % CENSORED, excluded from `n` |
| population matching before comparing metrics | **PARTIAL** — 2021 byte-identical; 2022 differs by 45 rows with no row-level parity artifact |
| base rate / signal rate reported with the effect | PASS — 16.14 % in both; positives exactly equal |
| TRAIN/OOS separation and year authority | PASS — fit 2021 only, scored 2022 only |
| no refit / retune / re-slice after seeing OOS | PASS — read-only worker; `thresholds {}`, `deciles {}` unchanged |

## Caveats

1. **Model integrity is not scientific validity** (`docs/RESEARCH_WORKFLOW.md` §6.2). Reproducing
   a metric proves the machinery, not the edge.
2. **No row-level parity artifact for 2022.** The reference study declared
   `parity_a_train_2021.json` and `parity_a_oos_2022.json`; this study declares no parity
   deliverable (`compiled_plan.deliverables` is `null`), so nothing is *missing*. But the 45-row
   2022 population difference is attributed to the calendar/session change **by argument**
   (positives conserved, deltas confined to the boundary), not verified row by row.
3. **15 paths were uncommitted** in the worktree at decision time (7 modified, 8 untracked),
   including every artifact cited above. The evidence here is on-disk bytes at HEAD `1149543b`,
   not committed bytes. **The closure step must commit them.**
4. **`artifacts/SUPERVISOR_V1_VALIDATION_CARD.json` is committed but stale.** Written
   2026-09-05T16:19Z, it records the earlier STOPPED-at-escalation state and asserts *"the
   research plane was NOT EXERCISED"*. This run (through 19:00Z) supersedes it. Correcting it is
   outside this worker's write surface.
5. **W-1** (`PLATFORM_STATE.json`): the study binds the SUPERSEDED dataset id `NQ_1S_V2`, which no
   compile gate refuses. Here that is deliberate and correct — the packet mandated a verbatim copy
   of a reference study that binds it. PLATFORM_STATE records the bars as byte-identical to
   `NQ_1S_V2_GLOBEX` with only the session reference table differing — and that table is precisely
   the surface the observed drift sits on.
6. **W-4**: `research_workflow/workflow_engine.py` executes on the V2 path via
   `governed_controller.py` and supplies the `_read`/`_sha` used by the audit-currency check, yet
   sits outside the frozen closure. It affected no number here, but it is an unfrozen executing
   module.
7. `train_metrics` (tuning / folds / final_validation) are all `null` — protocol
   `model_selection.random` with empty `final_train_validation_years` yields no in-train metric.
   The 2022 OOS score is the only reported metric. The reference is null there too.
8. The 12 TRAIN and 69 OOS rows that changed disposition were **not individually inspected**; only
   their aggregate direction (labeled → censored, never the reverse; positives never touched) was
   verified.

## What would change the verdict

- Any spec-surface leaf differing between the two compiled plans that is **not** a platform-version
  addition or `study.id`.
- A different OOS `LABELED_POSITIVE` count — positives conserved at exactly 76 263 is what
  localizes the drift to the session boundary.
- An OOS ROC-AUC shift beyond ~1e−3, or one large enough to look like selection rather than
  boundary drift.
- A critical in either pre-execution audit, or an audited composite ≠ the executed composite.
- A 2021 `candidates_sha256` mismatch — byte-identical candidate generation across a platform
  version is the strongest single piece of evidence here.
- Evidence that the *supervisor*, rather than a worker or the controller, produced or edited a
  scientific artifact.

## Next decision (a question, not an optimization)

1. Should the compiler **refuse SUPERSEDED dataset ids** for new studies (W-1), given that the only
   observed drift in this rerun sits on the session reference table those ids select?
2. Should `research_workflow/workflow_engine.py` be **pulled into the frozen execution closure**
   (W-4), or is its exclusion structurally justified?
3. Should a supervisor validation rerun declare an explicit **row-level parity deliverable** against
   its reference study, so that "reproduced" is verified per row rather than argued from conserved
   aggregates?
