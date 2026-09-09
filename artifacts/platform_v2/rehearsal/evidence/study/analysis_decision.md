# Analysis decision — `rehearsal_checkpoint_norm` (phase D)

**Terminal decision: `REHEARSAL_COMPLETE`**
**Outcome label: `LIFECYCLE_CLOSED_SINGLE_ARM_OOS_TAIL_LIFT_PRESENT`**

Decided by `claude` / `analysis-decider`, task `007_analysis_decision_a1f72277`, session `7a062aee`,
against study branch `study/rehearsal_checkpoint_norm` @ `54eba1f3`, platform commit `8bf26857`.
Machine-readable twin: `studies/rehearsal_checkpoint_norm/artifacts/analysis_decision.json`.

---

## Question (restated from `research_decision.yaml`)

SINGLE-ARM, per the deviation ratified at the binding level in `research_decision.yaml`: does a
regime-flip classifier fitted on the three ratified feature instances — prior `regime_efficiency`
at 1m and 5m, `rolling_giveback_atr` over 300s, and `structural_max_expansion_atr` (frozen-ATR
normalization) — carry out-of-sample tail lift on NQ, TRAIN 2023 → OOS 2024, measured on the
study's own fitted-model scores with thresholds frozen on TRAIN?

The checkpoint-epoch normalization `structural_max_expansion_checkpoint_atr` is **withdrawn from
scope**. It has no comparator frame, no fit and no deliverable here. **This report claims no
comparison between the two normalizations.** That question is untouched and remains open.

## Verdict

`REHEARSAL_COMPLETE`. Every clause of the declared label holds, and no clause of
`REHEARSAL_INCOMPLETE` does.

| Declared clause of `REHEARSAL_COMPLETE` | Status |
|---|---|
| lifecycle ran to closure on full-year TRAIN 2023 / OOS 2024 | ✅ 8/8 stages, `state: READY_TO_CLOSE`, 137 tests passed / 0 failed |
| fitted feature surface is EXACTLY the three ratified instances, nothing dropped/renamed/substituted/re-parameterized | ✅ 4 physical columns from 3 instances, identical in plan, models, freeze and the scored frames |
| `tail_lift.json` exists for the study's OWN fitted-model scores with TRAIN-frozen thresholds | ✅ model `d3cfd7621897` (golden PASS), thresholds = TRAIN-frame quantiles applied to OOS rows |

## Evidence

Result — `studies/rehearsal_checkpoint_norm/artifacts/tail_lift.json`
(sha256 `9e0eb6a5…`, equal to the digest declared inside `experiment_analysis_v2.json`):

| TRAIN quantile | threshold | OOS n_tail | tail_share | tail rate | base rate | **lift** |
|---|---|---|---|---|---|---|
| 0.900 | 0.43142 | 83 748 | 9.75 % | 0.5009 | 0.3271 | **1.531** |
| 0.950 | 0.49536 | 40 656 | 4.73 % | 0.5564 | 0.3271 | **1.701** |
| 0.975 | 0.57294 | 19 582 | 2.28 % | 0.6466 | 0.3271 | **1.977** |

`n_reference` = 877 040 TRAIN 2023 rows (threshold source); `n_rows` = 859 153 evaluable OOS 2024
rows of 867 422 scored. The monotone rise of lift with the quantile, and OOS tail shares
(9.75 / 4.73 / 2.28 %) close to their nominal 10 / 5 / 2.5 %, say the score ranks OOS rows and the
score distribution barely drifted between the years.

Lifecycle evidence, each with its artifact:

- `_work/controller/status.json` — `actions_executed = [smoke, collection, reconcile, merge, fit, freeze, oos, analyze]`, `STATUS: OK`, `blocker_code: null`.
- `artifacts/preexec_audit_seal.json` (`e3cb9805…`) — seal binds causal audit **CLEAR** (`lookahead-auditor:004_causal_audit_300a825d`, 0 critical / 0 warning) and contract audit **CLEAR** (`contract-checker:owner-pass02-20f45ea6`, 0 critical / 0 warning) to execution composite `73db2ed0f213…`.
- `artifacts/smoke_acceptance.json` (`974370e1…`) — `ACCEPTED` on the authorized date 2023-03-01, six of six checks true, 3 866 candidates = 3 866 observations, `pending_at_end: 0`.
- `artifacts/experiment_authorization.json` — train [2023], oos [2024], prohibited [2020, 2021, 2022, 2025, 2026]; only the two authorized partitions exist on disk.
- `_work/controller/reconcile.json` — `passed: true`, 0 findings, 877 040 TRAIN rows, dataset digest `9e7aecb7a291…` (`NQ_1S_V2_GLOBEX`).
- `artifacts/train_experiment_freeze.json` (`3e06c161…`) — written 14:19:30Z, **before** the OOS partition ran and before analyze (14:27Z).
- `artifacts/experiment_analysis_v2.json` (`5534e511…`) — declared analysis, `source: oos` years [2024], `reference: train_frame` years [2023].

## Integrity checks performed

| Check | Result |
|---|---|
| Model authentication / golden replay | **PASS** — `max_abs_diff 0.0` over 256 rows, on both the OOS frame and the train_frame; `identity_rule v2_lineage_sha256`, canonical `27bc73fb54a9…` |
| Arm-delta integrity (identical fit / prediction identity) | **N/A** — one ratified arm; `paired_deltas_vs_baseline_arm` is empty and no delta is claimed |
| Added features populated and with variance | **PASS** (NON-AUTHORITATIVE frame read) — see below |
| TRAIN/OOS separation, thresholds frozen on TRAIN | **PASS** — freeze precedes OOS; `tail_lift()` takes thresholds from `reference`, never from the evaluated rows (`research/analysis/diagnostic_ops.py:931`) |
| Protected-period authority | **PASS** — no prohibited year in any manifest |
| Censoring respected, unresolved fraction reported | **PASS** — 8 269/867 422 OOS (0.953 %) and 7 754/877 040 TRAIN (0.884 %) non-binary labels excluded, never coerced to 0 |
| Signal rate reported with the effect | **PASS** — the rule fires on 9.75 / 4.73 / 2.28 % of evaluable OOS rows |
| Declared deliverables present and digest-matched | **PASS** — `tail_lift.json` `9e0eb6a5…`, `tail_lift.parquet` `f00fd887…` equal the digests declared in `experiment_analysis_v2.json` |
| Composite consistency across seal / freeze / partitions / analysis | **PASS** — `73db2ed0f213…` and `plan_sha256 9eb2ff0d6e63…` agree everywhere |
| Replay closure escapes | **PASS** — `escapes: []` for `oos-2024`, 92 closure files |

Feature population (NON-AUTHORITATIVE read of
`_work/controller/partitions/{train/2023,oos/2024}/candidates.parquet`; no fit, no re-run):

| column | TRAIN non-null / nunique / sd | OOS non-null / nunique / sd |
|---|---|---|
| `prior_1m_regime_efficiency` | 877 040 / 3 801 / 0.235 | 867 422 / 4 122 / 0.232 |
| `prior_5m_regime_efficiency` | 877 040 / 4 129 / 0.256 | 867 422 / 4 437 / 0.255 |
| `rolling_300s_giveback_atr` | 241 450 / 164 959 / 0.946 | 213 318 / 153 923 / 1.002 |
| `structural_max_expansion_atr` | 877 040 / 67 319 / 2.502 | 867 422 / 64 506 / 2.627 |

No column is dead or constant — the declared surface is a real surface, not a nominal one.
`compiled_plan.json` contains four verified instances and the string `checkpoint_atr` does not
occur anywhere in it.

## Caveats

- **Single arm.** The checkpoint-epoch normalization was withdrawn (unregistered capability; the
  capability flow ended in `SUPERVISOR_ESCALATION_REQUIRED` and the owner intervened). No
  normalization contrast is measurable from this study and none is claimed.
- **Row-level, not episode-level.** 859 153 evaluable OOS rows come from 6 680 regime episodes
  (~130 five-second checkpoints each). The effective independent sample is thousands of episodes,
  not hundreds of thousands of rows. No confidence interval is declared or claimed, and no
  entity-level metric was declared.
- **Pooled.** The declared analysis has `group_by: null`, so long/short and young/mature regimes
  are pooled. Re-slicing after seeing OOS is prohibited, so an inverted slice would be invisible
  here — that is a limit of this contract, not a finding.
- `rolling_300s_giveback_atr` is null on ~72.5 % TRAIN / ~75.4 % OOS rows by construction;
  LightGBM routes NaN natively, so it contributes mainly through its non-null quarter.
- The label is a 300s forward flip of the same regime tracker that defines the population, sampled
  every 5s, so adjacent rows share overlapping horizons. Intended for the rehearsal, but it makes a
  row-level lift optimistic as a test statistic.
- `experiment_models.json` echoes hyperparameters **without** `random_state`, which
  `compiled_plan.json` `model.params` does declare (42). Determinism is additionally pinned by
  `deterministic: true` and `n_jobs: 1`, and the golden replay reproduces scores exactly.
- At decision time `studies/rehearsal_checkpoint_norm/artifacts/` is still **untracked in git**.
  This worker's write surface is `analysis_decision.json` / `.md` only, so every evidence file is
  pinned here by sha256 instead; the closing session should commit the directory.
- **No economic result.** Tail lift is a classification-tail statistic, not a tradeable edge.
  Nothing here has been through fills, costs or a live-style NT run.

## What would change the verdict

1. A declared deliverable missing, or its on-disk digest disagreeing with `experiment_analysis_v2.json`.
2. The fitted feature surface differing from the four ratified columns.
3. Any claim of the checkpoint-vs-frozen contrast appearing in the study record.
4. A stage or gate found to have been skipped, or an audit verdict other than CLEAR at the sealed composite.

## Next decision

Does `structural_max_expansion_checkpoint_atr` add OOS tail lift over the frozen-ATR
normalization? Answering it needs the capability registered first, then a genuinely two-armed
study with an episode-level metric and direction/maturity slices declared up front — a new
decision contract, never a revision of this one.
