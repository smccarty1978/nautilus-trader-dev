# ANALYSIS / DECISION — `es_180s_model_c_portability`

- worker: `analysis-decider:010_analysis_decision_1b98ed49` (agent `claude`, session `6d88212a-6b2b-428c-a926-649e1cddd548`)
- study head: `85a7724da335bb98166035a5c3e47411e9f181bc`, branch `study/es_180s_model_c_portability`
- execution composite: `6d44da61d0649a99f3491ee413ae449c71de8dd1aaf793b64aa8ddadc0bf0222`
- plan `e1f5dfb86789741516379416b7d646fc6e2cc6688464f0f457dd02dfdd9d22e5` · TRAIN freeze `1cd76ba07e9245d4f1231f2cc0b00eedad8d11340d4a3f3497faca9faee5e7ed`
- **status: BLOCKED — `RESEARCH_CONTRACT_CONFLICT`. `analysis_decision.json` is deliberately NOT written.**
  Nothing was fitted, tuned, re-run or re-sliced to produce this report.

---

## Question (restated from `research_decision.yaml`)

**PRIMARY.** Does the validated NQ 180-second Model C architecture transfer to ES? Trained natively on
ES 2020–2023 with the 13-feature Model C surface and the NQ parent's own frozen direction-specific
hyperparameters, frozen, then evaluated once on untouched ES 2024 — does ES show meaningful forward
discrimination for an imminent prevailing 1m regime flip within `(T, T+180s]`?

**SECONDARY.** Does ES independently learn a similar dominant feature structure to NQ (`ema_slope`,
`arrival_velocity`, rolling retention, rolling giveback, rolling current progress)?

---

## Verdict

**The declared closure vocabulary cannot express what this evidence shows. I am not picking a label.**

- The evidence that exists supports **`STRONG_PORTABILITY`** on every conjunct that was actually
  measured, and it is strong — see the Evidence section.
- But `STRONG_PORTABILITY` is declared as a four-part conjunction, and **two of its four parts have
  zero evidence** because the artifacts were never produced (score-tail lift at the frozen ES TRAIN
  P90/P95/P97.5; learned feature structure). Certifying it would assert facts I cannot cite a path for.
- And `PARTIAL_PORTABILITY` is declared as an affirmative claim of weakness — "materially weaker or
  one-sided transfer ... one direction only ... calibration or timing discrimination degrades ...
  feature ranking diverges substantially". **None of those is what the data shows.** Transfer is
  two-sided and near-parity with NQ. Closing `PARTIAL` would put a factually wrong record on the study.

Both admissible labels would state something untrue. That is the conflict. **`NO_MEANINGFUL_PORTABILITY`
is decisively excluded** — that much is safe to say.

---

## Evidence

All numbers from `studies/es_180s_model_c_portability/artifacts/experiment_analysis_v2.json` unless a
different path is given. `base_rate` and `lift` are derived as `positives/n` and `pr_auc/base_rate`
(the artifact reports `pr_auc_over_base_rate` directly for TRAIN folds only).

### ES 2024 OOS — scored once, per direction cell

| cell | n | positives | base rate | ROC-AUC | PR-AUC | PR/base lift | Brier |
|---|---|---|---|---|---|---|---|
| `primary:LONG` (dir +1) | 287,264 | 45,072 | 0.156901 | **0.668657** | 0.274162 | **1.7474** | 0.125844 |
| `primary:SHORT` (dir −1) | 226,160 | 39,836 | 0.176141 | **0.676425** | 0.302954 | **1.7200** | 0.136722 |

Unique-regime counts for OOS are **not reported** by the artifact (see Missing deliverables).

### TRAIN to OOS transfer

TRAIN reference is the last expanding fold (`fold_2023`, fit 2020–2022), the closest analogue to a
held-out year; the 3-fold mean is given alongside because the frozen model was fit on all of 2020–2023
and no final validation exists (`metrics.final_validation: null`).

| cell | TRAIN `fold_2023` ROC / lift | 3-fold mean ROC / lift | OOS ROC / lift | ROC above-chance retention (fold_2023 / mean) | lift retention (fold_2023 / mean) |
|---|---|---|---|---|---|
| LONG | 0.677764 / 1.7521 | 0.685887 / 1.8029 | 0.668657 / 1.7474 | **94.9% / 90.7%** | **99.7% / 96.9%** |
| SHORT | 0.690591 / 1.7898 | 0.694371 / 1.8139 | 0.676425 / 1.7200 | **92.6% / 90.8%** | **96.1% / 94.8%** |

Brier moved *down* on both cells (LONG 0.133080 to 0.125844; SHORT 0.139882 to 0.136722), but the 2024
base rate also fell on both (LONG 0.170471 to 0.156901; SHORT 0.184550 to 0.176141), so part of that is
mechanical and Brier alone is not a calibration statement.

### ES vs the frozen NQ 180s parent, same OOS year

NQ numbers read from `studies/clean_maturity_flip_model_180s_horizon/artifacts/2024_OOS_CARD.json`
(frozen historical reference; **nothing about NQ was retrained, recollected or recomputed here**).

| direction | NQ base / ROC / lift / Brier / ECE | ES base / ROC / lift / Brier | ES/NQ above-chance ROC | ES/NQ lift |
|---|---|---|---|---|
| LONG | 0.162666 / 0.691509 / 1.8185 / 0.127465 / 0.00887 | 0.156901 / 0.668657 / 1.7474 / 0.125844 / — | **88.1%** | **96.1%** |
| SHORT | 0.137795 / 0.674621 / 1.7715 / 0.113867 / 0.02420 | 0.176141 / 0.676425 / 1.7200 / 0.136722 / — | **101.0%** | **97.1%** |

ES SHORT slightly *exceeds* NQ SHORT on OOS ROC-AUC. ES LONG is ~2.3 ROC points below NQ LONG. On the
PR/base-rate lift — the metric the contract names first — ES lands within 3–4% of NQ on both directions.

### Censoring

`dispositions`: `LABELED_POSITIVE` 84,908 · `LABELED_NEGATIVE` 428,516 · `CENSORED` 3,185, total
516,609 = `rows`. **Unresolved fraction = 0.6165%.** Censored rows were excluded from scoring, not
labelled 0 (287,264 + 226,160 = 513,424 scored = 516,609 − 3,185). This matches the declared
`session_end: censor` semantics. Pooled labelled base rate 0.165376.

---

## Integrity checks performed

| Check | Result |
|---|---|
| The two cells are genuinely different models, not one model scored twice | **PASS.** `model_id` `6514583f...` vs `8ebbb08b...`; `model_canonical_sha256` `167f9b5d...` vs `230b745e...` (`train_experiment_freeze.json`). Distinct. |
| The two cells produce genuinely different scores | **PASS.** OOS `score_digest` `3b045d7d...` (LONG) vs `7417dc2a...` (SHORT). |
| Frozen model bytes authenticate at score time | **PASS.** `model_authentication.golden.status = PASS`, `max_abs_diff = 0.0` over 256 rows, both cells; `identity_rule v2_lineage_sha256`, `tier registry`, `selection_status selected`. |
| Populations are disjoint and account exactly | **PASS.** `subset.regime_direction` +1 / −1; scored + censored = rows, exactly (above). |
| Chronology — no 2024 in the fit, no 2025/2026 anywhere | **PASS.** Both `lineage.train_years = [2020,2021,2022,2023]`; `oos_years = [2024]`; `metrics_by_year` has only `2024`; `experiment_authorization.json` train 2020–23 / oos 2024 / prohibited 2025–26, `authorization_sha256 b900205b...` matches the one bound into the TRAIN freeze. |
| No refit / retune / threshold change after OOS opened | **PASS (structural).** `compiled_plan.json` `model.search_space: {}`, `model.validation: null`, `model.mode: train`; contract audit pass 03 verified the `analyze` stage only *scores* frozen models (`lifecycle_v2.py:1339-1347`). |
| Feature contract identical across cells (contract requires LONG_C == SHORT_C) | **PASS.** `feature_contract_sha256 c60e2838...` on both; 13 inputs, identical order, matching `train_experiment_freeze.json feature_sets.primary`. |
| Hyperparameters are the NQ parent's, unchanged | **PASS.** `experiment_models.json`: LONG lr 0.039440343780424526 / n_est 100, SHORT lr 0.028861842631876633 / n_est 200, both `max_depth 5`, `num_leaves 4`; `random_state 42` in `compiled_plan.json model.params`. Matches `research_decision.yaml` section 7 verbatim. |
| Pre-execution audits clear at the executed composite | **PASS.** causal `pass_03` CLEAR (0/0/7) and contract `pass_03` CLEAR (0/0/6), both at `6d44da61...`, which equals `status.json` `execution_composite` = `plan_closure_composite` = `current_execution_composite`. |
| Smoke acceptance | **PASS.** `smoke_acceptance.json` ACCEPTED at the same composite; `no_outcome_columns_in_candidates: true`, `pending_at_end: 0`. |
| **Per-feature population and variance** | **NOT VERIFIABLE.** No per-feature null-rate or variance artifact was emitted. Contract section 17 requires "no all-null feature columns ... feature variance checks"; nothing in `artifacts/` reports them. Both models did learn (ROC well above 0.5 on held-out years), so the surface is not wholly dead, but a single dead column among the 13 would not be visible here. |
| **Calibration** | **NOT VERIFIABLE beyond Brier.** No ECE, no reliability curve. NQ's card reports `expected_calibration_error_180s`; ES has no counterpart. |

---

## Missing deliverables (why this is BLOCKED, not DONE)

`research_decision.yaml` section 18 REQUIRED OUTPUTS lists deliverables that **do not exist**, because
the compiled plan never declared them and Platform V2 does not currently produce them:

1. **Frozen ES TRAIN P90/P95/P97.5 thresholds** (sections 10, 13, 18). `train_experiment_freeze.json`
   has `"thresholds": {}` and `"deciles": {}`. `compiled_plan.json` has `thresholds: null`. These are
   not empty because the run failed — `research_workflow/lifecycle_v2.py:1144` and `:1181` write
   `"thresholds": {}, "deciles": {}` as **literals**. V2 has no threshold-derivation capability at all.
   Contract audit pass 03 recorded this as NOT APPLICABLE ("the plan declares no thresholds"), which is
   true of the plan but leaves the contract's section 10 unsatisfied.
2. **2024 score-tail summary** — retained fraction, flip-within-180s probability, lift vs the 2024 base
   rate, median seconds-to-flip at each frozen threshold (section 13). Follows from (1). This is the
   single most load-bearing missing number: NQ's own tail lift (2.15–2.60 at P90–P97.5) is materially
   higher than its aggregate lift (1.77–1.82), so aggregate agreement does not imply the tails agree.
3. **Feature importance table** (sections 12, 18) — gain, gain %, split count, split %, top-3/top-5
   cumulative gain, zero-gain features, per direction. Not in `experiment_models.json`;
   `feature_importances_` appears nowhere under `research_workflow/` or `scripts/`. **The SECONDARY
   research question is therefore entirely unanswered.**
4. **Maturity-bucket summary** (section 11) — 0–300 / 300–600 / 600–900 / 900–1800 / >=1800s. The
   bucketing column `regime_age_seconds` is collected as metadata (`study.yaml features.metadata`), but
   no artifact slices on it. The role's "keep slices separate" rule cannot be honoured.
5. **Median seconds-to-flip / timing discrimination** (sections 13, 15) — nowhere.
6. **First-P90 diagnostic** (section 14) — declared conditional ("if supported"); not produced. The
   `analysis_source` decision in `research_decision.yaml` deliberately declined a declarative
   `analysis:` block to protect the section-13 OOS metrics, so `compiled_plan.json analysis: null` is a
   *documented* choice — but it means section 14 is unavailable by construction.
7. **OOS unique-regime counts** (section 13 requires "rows, unique regimes, base rate"). TRAIN folds
   report `unique_regimes`; `metrics_by_year.2024` does not. Section 11's "keep checkpoint counts and
   unique-regime counts distinct" cannot be applied to OOS.
8. **`artifacts/ES_180S_MODEL_C_PORTABILITY_CARD.json`** (section 22) — does not exist, and most of its
   fields are unfillable given 1–7.

Per `.claude/agents/analysis-decider.md`: *"If an artifact needed for the declared deliverable does not
exist, that is a missing deliverable — report it as INCOMPLETE rather than answering a narrower question
and presenting it as the answer."*

---

## The two readings (role-file escalation: report both, do not pick one silently)

**Reading A — conjunctive.** `terminal_decisions.STRONG_PORTABILITY` is a four-part `and`: comparable
ROC/lift retention **and** stable lift at the frozen ES TRAIN P90/P95/P97.5 **and** reasonable
calibration **and** NQ-like learned feature structure. Two parts are unevidenced and one is only partly
evidenced, so STRONG cannot be certified; the conservative label inside the declared vocabulary is
**`PARTIAL_PORTABILITY`**.

**Reading B — evidentiary.** `terminal_decisions.PARTIAL_PORTABILITY` requires a *demonstrated*
weakness (one-sided transfer, degraded calibration/timing, diverging feature ranking). No such weakness
exists in the data; the measured evidence — both directions, 91–100% lift retention, 91–95%
above-chance ROC retention, ES within 3–4% of NQ's own OOS lift, ES SHORT ROC slightly above NQ's —
satisfies STRONG's leading clause. The verdict is **`STRONG_PORTABILITY`** with the unevidenced
conjuncts carried as caveats.

The contract itself carries this tension. Section 15 says: *"Judge whether the same frozen architecture
yields, on ES: genuine forward discrimination, stable tail lift, reasonable calibration, useful timing
discrimination, **and/or** comparable learned feature structure"* — disjunctive, favouring Reading B.
The `terminal_decisions` block, which is the authoritative closure vocabulary the supervisor writes into
`study_closure.json`, is conjunctive, favouring Reading A. Two readings, different verdicts.

**If forced to one label on the evidence that exists, it is `STRONG_PORTABILITY`** — Reading A's
fallback is affirmatively contradicted, Reading B's is merely under-evidenced, and an under-evidenced
true statement is a smaller error than a well-formed false one. I am not writing it unilaterally
because doing so would assert tail lift and feature structure that were never measured.

---

## Caveats (true in the observed data, not structurally enforced)

- **The TRAIN reference is a fold, not a held-out final validation.** `final_validation: null` on both
  cells; the frozen model was fit on all of 2020–2023. Retention percentages against `fold_2023` compare
  a model fit on 2020–2022 to a model fit on 2020–2023 — like-for-like in architecture, not in fit rows.
  The 3-fold mean is reported alongside for that reason; it lowers ROC retention to ~91% on both cells.
- **Aggregate lift agreement does not prove tail agreement.** NQ's P90–P97.5 lift (2.15–2.60) sits well
  above its aggregate lift (1.77–1.82). ES's aggregate lift matches NQ's; its tail is simply unmeasured.
- **The ES/NQ base rates differ by direction and in opposite directions** (ES LONG 0.1569 vs NQ 0.1627;
  ES SHORT 0.1761 vs NQ 0.1378). PR-AUC is base-rate sensitive, which is exactly why the contract
  compares `pr_auc / base_rate`; the raw PR-AUC column is not comparable across instruments and is not
  used as evidence above.
- **Brier is not calibration.** ES has no ECE. The Brier improvement TRAIN to OOS is partly a base-rate
  artefact on both cells.
- **No per-feature null/variance report exists**, so contract section 17's feature-availability
  requirement is unverified. A single dead ES column would be invisible in these artifacts.
- **The signal rate is the whole qualified population.** Every 5s checkpoint that passes the frozen
  parent predicates is scored; 513,424 scored rows across ~1 year. Without the P90 tail there is no
  "rule fires on X% of the population" number — this study reports a scorer, not a rule.
- This is a **predictive** result. No economics, no fills, no entries (contract section 16). Nothing
  here says the edge is monetizable.

---

## What would change the verdict

- **Producing (1)–(3) above.** The ES TRAIN score-tail at the frozen P90/P95/P97.5 and the LightGBM
  importance table are deterministic given the already-frozen models and the already-collected TRAIN
  scores. The percentile *definitions* were fixed in the contract before any data existed, so deriving
  them now is not a post-hoc threshold nudge — but it requires a governed re-score, which this role must
  not run. If the tail lift lands near NQ's 2.15–2.60 on both directions and the ES importance ranking
  is recognisably NQ-like, Reading A and Reading B converge on `STRONG_PORTABILITY`.
- Tail lift materially below NQ's on one or both directions, or a substantially diverging ES feature
  ranking, would make `PARTIAL_PORTABILITY` the correct and *accurate* label.
- A maturity-bucket slice showing the discrimination lives in one bucket only would also argue
  `PARTIAL_PORTABILITY`, and would be the most interesting negative result available here.

---

## Next decision (a question, not an optimization)

Two things are open, in this order:

1. **Governance:** does Platform V2 acquire TRAIN-score-threshold derivation and native model-importance
   export as declarable deliverables? Every study whose contract asks for a frozen score tail hits this
   same wall. That is a `chore/*` capability question, not a study question.
2. **Science, only once (1) lands:** given that ES reproduces NQ's *aggregate* 180s discrimination almost
   exactly on both directions — does it reproduce NQ's *tail concentration and timing*? NQ's value was
   never the aggregate AUC; it was that the top 2.5% of scores flipped 42% / 36% of the time within a
   median 55 seconds. Whether that structure is instrument-invariant is the question this study set out
   to ask and cannot currently answer.
