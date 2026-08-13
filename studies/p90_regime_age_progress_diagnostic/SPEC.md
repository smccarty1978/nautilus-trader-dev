# P90 Edge by Regime Age × Realized Progress — Frozen Specification

**Study:** `p90_regime_age_progress_diagnostic` · **Frozen:** 2026-08-13, before implementation.
**Branch:** `study/p90_regime_age_progress_diagnostic`
**Type:** QUICK DIAGNOSTIC. No model training, no entry policy, no exit work, no optimisation.
**Substrate:** `data/canonical/regime_complete_v1/` (REGIME-COMPLETE STORE ACCEPTED)
**Population years:** 2021–2025. **2026 SEALED.**

---

## 0. The question

The recent P90 lineage (`armed_fade_score_path_progression` → `p90_5s_regime_impulse`
→ `p90_conditional_losing_5s_exit` → `p90_5m_regime_context` → `post_confirm_5m_forward_opportunity`)
inherited an arm rule of *first fresh Top-10 crossing from below at regime age > 600 s*.
The frozen models' own eligibility contract is broader. This study asks:

> Is P90 genuinely identifying imminent regime termination across the model's
> broader eligible domain, or is its usefulness concentrated in old / low-progress
> regimes that are simply stale?

Two objectives are deliberately separated throughout, because they are not the
same thing and the model was only ever trained on the first:

1. **Classifier objective** — `P(prevailing 1m regime flips within 300 s)`. This is
   the literal training target.
2. **Economic objective** — does that termination become a confirmed, tradeable
   reversal with meaningful opposite excursion?

---

## 1. Phase 0 — the ORIGINAL contract, VERIFIED not inferred

### 1.1 Source of truth

`studies/full_trade_path_builder/artifacts/BULLISH_STRICT_top25_gbt_v2/config.yaml`
(the accepted frozen training artifact) and its mirror
`studies/freeze_long_strict_models_v2/artifacts/LONG_STRICT_top25_gbt_v2/manifest.json`.

| Contract item | Config value (accepted artifact) | Realized in store (verified) |
|---|---|---|
| `age_min_seconds` | `120` | min in-domain age **125.0 s** |
| `running_mfe_min_atr` | `1.0` | min `running_mfe_atr` **1.0000177** |
| `progress_windows_min` | `2` | min `new_progress_windows` **2** |
| `progress_gap_seconds` | `120` | (not directly observable per-row) |
| `retained_mfe_ratio_min` | `0.5` | min `retained_mfe_ratio` **0.5000** |
| `excursion_direction` | `prevailing_regime` | — |
| `atr_anchor` | `confirmed_regime_start` | — |
| session | RTH `[08:30,15:00)` CT | **100 %** of in-domain rows `session == RTH` |
| checkpoint cadence | 5 s | 5 s |
| target | `bearish_regime_flip_within_300s`, interval `(T, T+300s]` | — |
| target (long model) | `bullish_regime_flip_within_300s` | — |
| `established_regime_gate` | — | **True for 100 %** of in-domain rows |

`bullish_in_domain` ⟺ `prevailing_regime == +1` (fade SHORT);
`bearish_in_domain` ⟺ `prevailing_regime == −1` (fade LONG). `bullish_in_domain &
bearish_in_domain` is true for **0 rows**, so direction and model are one partition.
`is_regime_confirmed` is True on 100 % of in-domain rows.

**The user's remembered values are confirmed exactly.** No discrepancy to report on
the four eligibility numbers.

### 1.2 Two discrepancies that ARE recorded, not silently reconciled

**(a) `age_min_seconds: 120` but the realized floor is 125 s.** The checkpoint grid
runs at 5 s cadence from `regime_start + 5 s`. A `>= 120` gate on that grid would
admit a 120 s checkpoint; the observed floor of 125 s means the gate is applied
strictly (`> 120`). **Consequence for this SPEC:** the first frozen age bucket is
`125–240 s` in fact, and is *labelled* `120–240s` to keep the brief's frozen edges.
It is not widened, narrowed, or re-optimised.

**(b) The training grid ceiling is NOT the store's ceiling.** The config freezes
`checkpoint_grid: regime_start_plus_5s_through_less_than_1800s`. The canonical store
scores in-domain checkpoints out to **8,760 s**, and **430,767 of 2,205,823 in-domain
checkpoints (19.5 %) sit at age ≥ 1800 s** — beyond the age range the model was
trained on. **8.6 % of this study's population-A events and 8.8 % of population-B
events are armed at age ≥ 1800 s.** Every table carrying the `>900s` age bucket must
disclose the share of that bucket beyond the training ceiling. This is an
extrapolation disclosure, not a defect, and it is not corrected for.

### 1.3 The 0.5–2 ATR progress bucket — resolved, and it is NOT a contradiction

Prior discovery's `path_dev_0.5_2.0` family
(`studies/model_driven_entry_exit_discovery/implementation/candidates.py::path_development`)
buckets **`current_progress_atr`**, a *different column* from `running_mfe_atr`:

```text
running_mfe_atr      running MAXIMUM favorable excursion of the prevailing regime
current_progress_atr CURRENT favorable excursion at the checkpoint (the mark)
retained_mfe_ratio   current_progress_atr / running_mfe_atr
```

Eligibility requires `running_mfe_atr >= 1.0` **and** `retained_mfe_ratio >= 0.5`,
which *jointly imply* `current_progress_atr >= 0.5`. Verified directly: in-domain
`min(current_progress_atr) = 0.5004`, `min(implied retained ratio) = 0.5000` exactly,
and 27.5 % of in-domain checkpoints fall in `current_progress_atr ∈ [0.5, 2.0]`. The
0.5 floor is a **derived floor on retained progress**, fully consistent with a 1.0 ATR
floor on running progress.

**Therefore:** this study's PRIMARY DIMENSION 2 uses `running_mfe_atr` (the brief's
"running favorable progress"), whose floor is 1.0 ATR, and **the `0.5–1.0` bucket is
NOT manufactured.** `current_progress_atr` is carried as a disclosed secondary column
so the two are never conflated again.

---

## 2. Population

### 2.1 No retraining, no rescoring

Frozen scores are read from `canonical_regime_scores_all.parquet` as collected.
Frozen direction-specific Top-10 thresholds from
`model_driven_entry_exit_discovery/implementation/candidates.py::THRESHOLDS`
(`top_10` = bullish `0.43167249785595935`, bearish `0.44559149246408103`), never
derived from this study's population. The calendar-2025 threshold-overlap waiver
(`studies/full_trade_path_builder/THRESHOLD_OVERLAP_WAIVER.json`) is inherited by
reference: **2025 is not threshold-out-of-sample and may not be reported as such.**

### 2.2 The observation stream

In-domain dispatches that actually produced a score. `load_observations()` is reused
verbatim from `armed_fade_score_path_progression/implementation/arming.py`: 177,429
of 2,205,823 in-domain dispatches carry a null probability (the model declined to
score) and are dropped **before** any crossing test, because a null is not evidence
of "below threshold" and NaN would propagate through `np.maximum.accumulate`.
Verified: 94,629 bullish-null + 82,800 bearish-null = 177,429 exactly.

### 2.3 The two arm definitions

Identical code path, one parameter differs. The accepted
`armed_fade_score_path_progression.arming.arm_population` hard-codes
`MIN_REGIME_AGE_S = 600` at module scope, so this study **restates that crossing
filter with the age gate as a parameter** rather than widening an accepted module
that other studies import. Equivalence at `min_age_s = 600` is proven twice: on a
synthetic frame covering every branch
(`tests/test_diagnostic_contracts.py::test_matches_accepted_arm_rule_at_600s`), and
on the real store by gate `V_PARITY_population_b_8950`. The accepted module's
`_assert_arming_population_is_complete` partial-year guard is **imported and called**,
not reimplemented. (An earlier draft of this SPEC claimed the function was "reused
verbatim"; lookahead-auditor pass 1 flagged that as inaccurate and it is corrected
here rather than left standing.)

```text
arm = first true crossing of Top-10 from below in a regime,
      at a checkpoint whose regime age exceeds MIN_AGE

A (ORIGINAL DOMAIN)  MIN_AGE = 0    -> model eligibility alone gates age (>120s)
B (INHERITED)        MIN_AGE = 600  -> the recent-study population
```

All three accepted conventions are inherited unchanged: the predecessor dispatch
must **exist** (a regime whose first in-domain dispatch already qualifies is not
armed — no crossing was observed); arming runs on the **full 2021–2025** population
before any year slicing (a partial slice drops the predecessor at each boundary and
manufactures phantom crossings); **one arm per regime**.

Every population-A row carries `qualifies_under_600s_gate` and, where it exists,
the population-B arm timestamp for that same regime.

### 2.4 Expected counts (measured during Phase 0, frozen here as gates)

```text
in-domain scored observations   2,028,394
distinct eligible regimes          15,076
POPULATION A arms                   9,189
POPULATION B arms                   8,950   <- reproduces the accepted reference EXACTLY
A ∩ B                               8,950   (B ⊆ A at regime level; only-in-B = 0)
  same arm timestamp                8,596
  DIFFERENT arm timestamp             354   <- B is NOT a clean subset (§5)
only in A (no >600s arm at all)       239
```

### 2.5 The population fact that constrains this study — stated up front

**The >600 s gate is barely a restriction. The model itself is what excludes young
regimes.** Eligibility admits young regimes freely — 1,818 regimes first become
eligible in 120–240 s, 2,002 in 240–300 s, 7,559 in 300–600 s, and there are 38,463
eligible checkpoints below 300 s. But the **P90 qualify rate among eligible
checkpoints** rises ~180× with age:

| age bucket | eligible checkpoints | P90-qualifying | rate |
|---|---:|---:|---:|
| 120–240 s | 11,700 | 12 | **0.10 %** |
| 240–300 s | 26,763 | 53 | **0.20 %** |
| 300–600 s | 319,805 | 2,452 | **0.77 %** |
| 600–900 s | 414,891 | 13,862 | **3.34 %** |
| > 900 s | 1,255,235 | 232,427 | **18.52 %** |

Consequently population A's young cells are near-empty (`120–240s` **n = 5**,
`240–300s` **n = 14**) and **no choice of age boundary rescues them**:

```text
arms EXCLUDED by the inherited gate (age <= 600s, B requires > 600s)   593  (6.5%)
  ... of which strictly below 600s (buckets 120-240 / 240-300 / 300-600)  581
  ... at exactly age == 600.0s (fall in the 600-900s bucket, closed-left)   12
```

Both counts are reported; `n_a_arms_below_600s` in `population_lineage.json` is the
**593** figure (the gate-relevant one), and the 581 is the bucket-sum. They are never
used interchangeably. This is reported as a **primary finding**, not a limitation
buried in a footnote. Cells with `n < 30` are reported with their N and are **barred
from any inferential claim** (§6.1 thin-cell rule).

---

## 3. Frozen dimensions

Frozen **before** looking at any economics. Never tuned.

```text
AGE (s, from regime start, at the arm)      PROGRESS (running_mfe_atr at the arm)
  120-240   [labelled; realized floor 125]    1.0-2.0
  240-300                                     2.0-3.0
  300-600                                     3.0-5.0
  600-900                                     >5.0
  >900      [disclose share >=1800s]
```

Closed-left / open-right on every bucket. The `0.5–1.0` progress bucket is **not**
created (§1.3). Both bucket sets are exhaustive and mutually exclusive over the
population by construction.

### 3.1 Progress velocity — descriptive only

```text
regime_progress_rate = running_mfe_atr / (regime_age_seconds / 60)     [ATR per minute]
```

Reported as **quartiles of the population-A P90 distribution** (edges computed once
on population A, frozen, and reused for every velocity table including population
B's). No cutoff is optimised. Phase-0 measured quartile edges for reference:
p25 ≈ 0.160, p50 ≈ 0.212, p75 ≈ 0.284 ATR/min.

---

## 4. Causal contract

Everything read at the arm is a column already present on the score row, i.e. it was
computed by the collector at the checkpoint's own decision timestamp under the
frozen `feature_source_invariant`. This study computes **no new state variable**.

| # | Item | Enforcement |
|---|---|---|
| 1 | Running regime MFE frozen at the P90 timestamp | `running_mfe_atr` read from the arm's own score row; never recomputed from a path, never a regime-final value; gate V-FROZEN |
| 2 | Regime age is causal | `seconds_from_regime_start` on the arm row; gate V-FROZEN |
| 3 | ATR denominator is causal | `atr_at_checkpoint`, frozen at the decision timestamp; the trade walk uses that same value as its frozen entry ATR; gate V-ATR |
| 4 | Future regime flip is a LABEL | `seconds_to_prevailing_flip` and every `P(flip<=X)` are outcomes; may never enter a bucket definition or a row filter; gate V-LABEL |
| 5 | Eventual trade MFE is a LABEL | `eventual_max_mfe_atr`; same rule; gate V-LABEL |
| 6 | Eligibility read from accepted artifacts | §1.1 table reproduced into `results/phase0_contract.json` with `config_value` / `observed_value` / `match` per row; gate V-CONTRACT |
| 7 | No 2026 | `max(entry_year) <= 2025` on every output; gate V-SEALED |
| 8 | Frozen scores only, no refit | no model is loaded anywhere in this study; `probability` is read from the store; gate V-NOFIT |

### 4.1 Outcome 1 — the model's actual target

```text
prevailing_flip_ns          = regime_end_decision_ns of the arm's own regime
seconds_to_prevailing_flip  = (prevailing_flip_ns - arm_ns) / 1e9
flip_within_120/180/300s    = 0 < seconds_to_prevailing_flip <= X
```

Taken from `canonical_regimes_all.parquet`, matching the training target's
`(T, T+300s]` half-open interval exactly. **Reconciliation gate V-TILE:** regimes
tile time and strictly alternate, so `regime_end_decision_ns` of the prevailing
regime must equal the next regime start; asserted against the independently-built
`RegimeIndex`, not assumed.

**Verified during Phase 0, recorded rather than silently reconciled.** The tiling
holds for **137,619 of 137,672** consecutive regime pairs, and direction alternation
holds for **137,672 of 137,672**. The **54** exceptions all carry
`regime_end_reason == 'sealed_boundary_censored'` with a **NULL**
`regime_end_decision_ns` — dataset/partition boundaries, matching the training
labeller's own `dataset_end_unresolved_action: right_censor`. Gate V-TILE therefore
asserts equality on every armed regime with a **non-null** end, and any armed regime
with a null end is flagged `flip_censored`, **excluded from Outcome-1 rates**, and
its count disclosed in `population_lineage.json` and every Outcome-1 table. It is
never imputed and never counted as "did not flip".

**Session disclosure, not a filter.** The training labeller was not session-gated, so
the primary `P(flip<=300s)` is measured on the raw regime timeline. `secs_to_session_close`
and `flip_window_crosses_session_close` are carried per event, the affected share is
disclosed in every Outcome-1 table, and a session-gated variant is reported as a
clearly-labelled SECONDARY. Neither is silently substituted for the other.

### 4.2 Outcome 2 — does termination become our confirmed reversal?

`measure_to_confirm` reused **verbatim** from
`armed_fade_score_path_progression/implementation/walks.py`. Entry at the arm
dispatch, `direction = -prevailing_regime`, `entry_price = checkpoint_reference_price`,
`atr = atr_at_checkpoint`, stop 1.00 ATR, window clamped to the arm's own RTH session,
confirming flip resolved `inclusive=True`. Reported: `P(CONFIRMED)` (the conservative
bound — a bar satisfying both stop and flip resolves adversely and is flagged
`ambiguous`), median `seconds_to_confirm`, and for confirmers `mae_to_confirm_atr`
p50/p75/p90 and `return_at_confirm_atr` median/mean.

**One stop only (1.00 ATR). No stop grid.** Terminal labels are the accepted four:
`CONFIRMED` / `STOPPED_BEFORE_CONFIRM` / `SESSION_CLOSE_UNRESOLVED` / `CENSORED`.
`SESSION_CLOSE_UNRESOLVED` is reported as its own share and never folded into either
resolved outcome.

### 4.3 Outcome 3 — is the reversal economically interesting?

For confirming trades only, `prepare()` reused **verbatim** from
`top10_fast_confirm_runner_path/implementation/engine.py`:

```text
eventual_max_mfe_atr = run_mfe[unc_i]      UNCONSTRAINED terminal
                                           (first of opposing flip / session close,
                                            1 ATR stop RELEASED)
```

This is the accepted definition used by `post_confirm_forward_opportunity` and
`post_confirm_5m_forward_opportunity`. **Unconstrained is mandatory here**: measuring
how much opposite move a reversal produces while a 1 ATR stop truncates the
measurement is the censored-population defect that understated required stop room 5×
in a prior study. Reported: median `eventual_max_mfe_atr`, `P(>=1 / >=2 / >=3 ATR)`.
Descriptive only — no exit-policy economics, no capture curve, no continuation value.

---

## 5. The A-vs-B comparison — B is NOT treated as a subset

354 regimes carry a **different arm timestamp** under A than under B (A's fires
earlier: median age 507.5 s vs 707.5 s on that subset). Reported explicitly:

```text
regimes with a P90 event before 600s                          581 arms in A
  ... absent from B entirely                                  239
  ... present in B at a DIFFERENT, later timestamp            354
  ... A and B arm on the same timestamp                     8,596
```

Population B is regenerated by this study's own code and gate V-PARITY asserts it
reproduces **8,950** and matches `armed_regime_score_paths.parquet`'s `regime_id` set
exactly (0 missing / 0 extra). Every A-vs-B metric is computed by the same functions
on both populations in the same run, so no comparison crosses a code boundary.

---

## 6. Deliverables Manifest <!-- frozen before implementation -->

| # | Path | Type | Required contents |
|---|---|---|---|
| 1 | `results/phase0_contract.json` | json | §1.1 table: `item, config_value, observed_value, source_artifact, match`; plus §1.2 (a)/(b) discrepancies and §1.3 progress-column resolution, each with the evidence numbers |
| 2 | `results/population_lineage.json` | json | §2.4 counts, each `expected`/`observed`/`match`; §5 A-vs-B breakdown |
| 3 | `results/p90_events.parquet` | table | one row per arm per population: `regime_id, population(A/B), arm_ns, entry_year, side, direction, prevailing_regime, regime_age_s, running_mfe_atr, current_progress_atr, retained_mfe_ratio, new_progress_windows, atr_at_checkpoint, probability, age_bucket, mfe_bucket, velocity_atr_per_min, velocity_quartile, age_ge_1800s, qualifies_under_600s_gate, b_arm_ns, seconds_to_prevailing_flip, flip_le_120s/180s/300s, secs_to_session_close, flip_window_crosses_session_close, terminal_label, ambiguous, confirmed, seconds_to_confirm, mae_to_confirm_atr, return_at_confirm_atr, eventual_max_mfe_atr, mfe_ge_1/2/3` |
| 4 | `results/p90_eligibility_base_rates.csv` | table | §2.5: `age_bucket, n_eligible_checkpoints, n_p90_qualifying, qualify_rate` — the mechanism table |
| 5 | `results/primary_matrix.csv` | table | **THE MAIN DELIVERABLE.** `population, age_bucket, mfe_bucket, n, p_flip_le_300s, p_confirm_before_1atr, median_return_at_confirm, median_eventual_mfe`, plus `n_confirmed, thin_cell` |
| 6 | `results/outcome1_target.csv` | table | `population, age_bucket, mfe_bucket, n, median_secs_to_flip, p_flip_le_120s, p_flip_le_180s, p_flip_le_300s, pct_window_crosses_close, p_flip_le_300s_session_gated` |
| 7 | `results/outcome2_confirmation.csv` | table | `population, age_bucket, mfe_bucket, n, p_confirmed, p_stopped, p_session_unresolved, p_ambiguous, median_secs_to_confirm, mae_to_confirm_p50/p75/p90, return_at_confirm_median/mean` |
| 8 | `results/outcome3_opportunity.csv` | table | `population, age_bucket, mfe_bucket, n_confirmed, median_eventual_mfe, p_mfe_ge_1, p_mfe_ge_2, p_mfe_ge_3` |
| 9 | `results/velocity_table.csv` | table | `population, velocity_quartile, n, edge_lo, edge_hi, median_age_s, median_running_mfe, p_flip_le_300s, p_confirm_before_1atr, median_return_at_confirm, median_eventual_mfe, p_mfe_ge_3` |
| 10 | `results/population_comparison.csv` | table | `population(A/B), n, median_age_s, median_running_mfe, median_velocity, p_flip_le_300s, p_confirm_before_1atr, median_return_at_confirm, median_eventual_mfe, p_mfe_ge_3` + the §5 timestamp-difference counts |
| 11 | `results/year_side_stability.csv` | table | the **single strongest** age/progress relationship only, sliced `LONG/SHORT` × 5 years: `slice_kind, slice, cell, n, metric, value` |
| 12 | `results/validation_report.json` | json | every gate, `expected`/`observed`/`pass` |
| 13 | `results/summary.json` | json | verdict D1–D5, headline numbers, the answered final question |
| 14 | `results/partition_manifest.json` | json | input paths + row counts, code hash, frozen thresholds, frozen bucket edges, frozen velocity quartile edges |
| 15 | `SPEC.md` / `README.md` / `REPORT.md` | docs | this contract; how to run; the answer |
| 16 | `audit/status.json` | json | roll-up with a key per agent; `critical: 0` required |

`*.parquet` / `*.csv` under `results/` are generated, **not committed**. JSON manifests
and the three docs are committed.

### 6.1 Domain & completeness contract

- **Partition grid:** 2 populations × 5 age buckets × 4 progress buckets = **40 cells**
  in every cell-level table. Empty cells are retained with `n = 0`, never dropped.
- **Thin-cell rule (gate V-THIN):** every cell carries `thin_cell = n < 30`. Thin cells
  appear in every table with their N and are excluded from every verdict test in §7.
  A verdict may never rest on a thin cell.
- **Rate denominators are explicit:** `p_confirm_before_1atr` is over all arms in the
  cell; `median_return_at_confirm`, `median_secs_to_confirm`, `mae_to_confirm_*`,
  `median_eventual_mfe` and every `p_mfe_ge_*` are over **confirmers only** and carry
  `n_confirmed` alongside. `p_flip_le_*` is over arms with a **measurable** (non-censored)
  flip and carries `n_flip_censored`. The three denominators are never interchanged.

  **A null check is NOT sufficient here, and gate `V-DENOM` enforces the difference.**
  `measure_to_confirm` populates `seconds_to_confirm` / `mae_to_confirm_atr` /
  `return_at_confirm_atr` whenever the confirming flip was *reached inside the window*
  — including trades that hit the 1 ATR stop **first** and are labelled
  `STOPPED_BEFORE_CONFIRM`. **4,186 of 4,427** population-A non-confirmers therefore
  carry a non-null `return_at_confirm_atr`, so an omitted `.filter(confirmed)` pools two
  populations *silently* rather than failing. Its measured effect on the main
  deliverable before the fix: `>900s` median return **0.558 (pooled) vs 0.833
  (confirmers)**, MAE p50 **0.891 vs 0.329** — the MAE distortion being the larger,
  since a stopped trade has MAE ≥ 1.0 by construction. `V-DENOM` independently
  recomputes every confirmer-denominated cell from the event frame with an explicit
  filter and requires an exact match. Raised as a CRITICAL by lookahead-auditor pass 2
  after it had already reached `primary_matrix.csv`; recorded here rather than quietly
  patched.

  **"Every" is enforced, not asserted.** `V-DENOM` covers all **10** confirmer-denominated
  columns — `median/mean_return_at_confirm`, `mae_to_confirm_p50/p75/p90`,
  `median_secs_to_confirm`, `median_eventual_mfe`, `p_mfe_ge_1/2/3` — matched to the
  exact statistic `AGGS` uses for each (median / mean / **linear** quantile).
  `V_DENOM_coverage_is_complete` fails if `AGGS` emits a column that is neither covered
  nor explicitly declared non-confirmer-denominated, and `V_DENOM_all_columns_present`
  fails if a covered column disappears (so deleting one cannot make its gate vacuously
  pass). An earlier revision of this gate covered only 4 of the 10 while this SPEC
  already claimed it covered all — leaving `p_mfe_ge_3`, which feeds `classify()`'s
  primary verdict, with no regression coverage against a leak that had already happened
  once. Raised as a CRITICAL by lookahead-auditor pass 3.

  **The gate is proven non-vacuous.** `tests/test_denominator_gate.py` feeds
  `check_denominators` a cell table built deliberately *without* `.filter(confirmed)`
  and asserts the gate FAILS, and separately asserts the covered-column list matches
  what `AGGS` actually emits. A gate exercised only by a passing pipeline run is not
  evidence of anything.
- **Extrapolation disclosure:** every table row touching the `>900s` bucket carries
  `pct_age_ge_1800s` (§1.2b).
- **Global validation:** row counts reconcile to 9,189 (A) and 8,950 (B) at every phase.

### 6.2 Terminal decision labels

`D0_UNCLASSIFIED`, `D1`–`D5` (§7) and `ABORT_LINEAGE_FAILURE` are the complete,
exhaustive, reachable set.

**`D0_UNCLASSIFIED` exists because D1–D5 are NOT logically exhaustive**, and pretending
otherwise is how a false null gets published. Worked example: if the old age bucket has
both a ≥25 % higher `p_flip_le_300s` **and** a ≥0.25 ATR larger `median_eventual_mfe`,
D2 fails (its `d_mfe > −0.25` clause) and D3 fails (it requires the *young* bucket to
run further) — yet that is a strong, interpretable result meaning "old regimes are
better on both axes". Aliasing the empty case to `D5_NOTHING_CHANGES` would have
written exactly that outcome into `summary.json` as "nothing changes". Raised as a
CRITICAL by lookahead-auditor pass 1 and fixed before execution. `D0` always carries
the full `facts` block so the report can state what actually happened.

---

## 7. Decision classification — computed, not asserted

Evaluated mechanically in `validate.py`, in this order. Thin cells (§6.1) are excluded
from every test. The **age contrast is evaluated on `300–600s` vs `>900s`** — the
youngest and oldest buckets with usable N — and this substitution (forced by §2.5, not
chosen by result) is recorded in `summary.json`.

| Verdict | Condition |
|---|---|
| `D1_WORKS_ACROSS_MATURITY` | `p_flip_le_300s` and `p_confirm_before_1atr` each differ by < 25 % **relative** between the young and old age contrast, AND `median_eventual_mfe` differs by < 0.25 ATR |
| `D2_STALE_REGIME_TERMINATION_DETECTOR` | old-bucket `p_flip_le_300s` exceeds young-bucket by ≥ 25 % relative, AND old-bucket `median_eventual_mfe` does **not** exceed young by ≥ 0.25 ATR |
| `D3_YOUNGER_TRADES_BETTER` | young-bucket `p_flip_le_300s` is **lower** than old, AND young-bucket `median_eventual_mfe` exceeds old by ≥ 0.25 ATR (or `p_mfe_ge_3` by ≥ 5 pp) |
| `D4_AGE_PROGRESS_INTERACTION` | neither age alone nor progress alone orders the outcome monotonically, but the velocity quartile table orders `p_flip_le_300s` or `median_eventual_mfe` monotonically across all four quartiles |
| `D5_NOTHING_CHANGES` | population A and population B agree within 2 pp on `p_flip_le_300s` and `p_confirm_before_1atr` and within 0.15 ATR on `median_eventual_mfe`, and no D1–D4 condition fires |
| `D0_UNCLASSIFIED` | **none** of D1–D5 fires (§6.2). Never an alias for D5 |
| `ABORT_LINEAGE_FAILURE` | any gate fails or any §8 stop condition trips |

Multiple verdicts may be **reported as co-firing** (e.g. D2 and D5 are not mutually
exclusive); `summary.json` carries the ordered list plus a single `primary_verdict`.
Thresholds are frozen illustrative defaults for this run, not settled science.

---

## 8. Stop conditions

1. Population B does not reproduce **8,950** arms, or its `regime_id` set does not match
   `armed_regime_score_paths.parquet` exactly → **ABORT**.
2. Phase 0 finds any eligibility value differing from the accepted artifact **and** the
   artifact is not adopted verbatim with the discrepancy recorded → **ABORT**.
3. `regime_end_decision_ns` ≠ next regime start for any armed regime with a **non-null**
   end (gate V-TILE) → **ABORT**. Null-end (`sealed_boundary_censored`) regimes are
   right-censored and disclosed, per §4.1 — they are not a stop condition.
4. Any retrospective field (`seconds_to_prevailing_flip`, `eventual_max_mfe_atr`, any
   `flip_le_*` / `mfe_ge_*`) is used as a bucket key or row filter → **ABORT**.
5. 2026 appears in any output → **ABORT**.
6. Any model artifact is loaded, or any score is recomputed → **ABORT**.
7. Any audit CRITICAL survives → **ABORT**.

No new parity harness is built. Upstream engine parity (`load_observations`,
`arm_population`, `measure_to_confirm`, `prepare`) is inherited by
reference-reproduction of the 8,950 population (condition 1).

---

## 9. Audit plan

- Pre-execution: `python scripts/causal_lint.py --study studies/p90_regime_age_progress_diagnostic`.
- Pre-execution: `lookahead-auditor`, scoped to the genuinely new surface only —
  the `MIN_AGE = 0` arming variant, the Outcome-1 flip-label construction and its
  session disclosure, the bucket/velocity derivations, and the A-vs-B join. The reused
  functions (`measure_to_confirm`, `prepare`, `load_observations`) are already
  causally audited and need provenance verification only, not a fresh causal proof.
- Completion: re-run against final `results/`; new numbered pass file each time; prior
  findings adjudicated before new ones; max 3 new CRITICALs per pass; `audit/status.json`
  shows `critical: 0`.
- Executed via `scripts/run_bounded_study.py` wrapping `run_study.py`.

---

## 10. No optimisation, and STOP AFTER THIS

Forbidden in this study: any model training or retraining, bucket-specific models,
5m-ATR normalisation, exit rules, stop grids, entry policies, threshold tuning, or
tuning of any bucket edge / velocity cutoff to maximise a separation. Every phase is
descriptive.

The likely NEXT study (explicitly **out of scope** here, gated on the D-verdict) is
model performance by regime-survival bucket, possibly adding `running regime move /
5m ATR` normalisation. This study does not begin it.
