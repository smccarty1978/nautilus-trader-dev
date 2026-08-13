# P80/P90-Primed Opportunity + Post-Confirm Continuation — ML Feasibility (2024)

**Study:** `p80_p90_opportunity_continuation_ml` · **Frozen:** 2026-08-11, before any model is fit.
**Type:** SIGNAL-FEASIBILITY. Not a strategy optimisation. Not a deployment study.
**Substrate:** `data/canonical/regime_complete_v1/` (policy-free) + the accepted
`studies/post_confirm_profit_ratchet/results/rung_events.parquet`.

**Predecessors treated as ACCEPTED EVIDENCE and not re-searched:**
`post_confirm_forward_opportunity` (E) · `post_confirm_profit_ratchet` (D) ·
`top10_fast_confirm_runner_path` (C) · `armed_fade_score_path_progression`.

---

## 0. The question, and what changed

The mechanical-exit line is closed. Four studies established that *imposing a stop
on overlapping populations* cannot monetise the 0.89808 ATR/original-entry
giveback pool: the best ratchet recovered ~1.7% of it and stayed net-negative,
and successful vs failed continuation overlap heavily once duration is controlled.

This study asks a different question — **is there causal predictive information
at the decision moment** — in two independent places:

> **MODEL A.** Once the fade model becomes concerned about the current regime
> (P80/P90 prime), does an attractive asymmetric forward payoff exist *right now*?

> **MODEL B.** Once a fade has confirmed and is profitable, does favourable
> continuation remain likely enough to justify continuing to hold?

These are separate prediction problems with separate labels. They share feature
infrastructure and the fold calendar; they share nothing else.

**Binding non-goals.** No mechanical exit grid. No stop-distance search. No
threshold optimisation. No horizon optimisation. No feature reduction to a
production set. No deployment threshold. No 2026. No years other than 2024.

---

## 1. Frozen scope and the 2024 seal

```text
instrument   NQ, *.v.0 volume-continuous only
YEAR         2024 ONLY. Exclusively.
SEALED       2021, 2022, 2023, 2025, 2026 — none may be read for fitting,
             feature selection, threshold selection, diagnostics or evaluation
2026         COMPLETELY SEALED, as in every study on this line
session      RTH only, [08:30, 15:00) CT, half-open; 15:00 CT is the forced flat
directions   LONG and SHORT, reported separately everywhere
cost         2 ticks round-turn = 0.50 points, charged once per completed trade
ATR          frozen at the decision timestamp of the observation in question
```

**Seal enforcement (validation gate V1).** Every loader filters
`entry_year == 2024` at the *source scan*, and every produced frame is asserted
to contain no observation timestamp outside calendar-2024 America/Chicago. The
assertion runs before any model is fit, not after.

**The one deliberate exception, disclosed.** The frozen threshold contracts and
the frozen scoring models carry historical lineage that predates this study and
cannot be re-derived without breaking their accepted contracts (§2.3). Their
provenance is documented, never laundered. **The NEW models fit here see 2024
observations only.**

---

## 2. Provenance — resolved from the repository, not assumed

### 2.1 The prime thresholds. Both exist. Neither is invented.

From `data/canonical/regime_complete_v1/canonical_model_threshold_contracts.parquet`,
all rows `is_frozen = True`:

| Prime | Contract label | Bullish model → **SHORT** fade | Bearish model → **LONG** fade |
|---|---|---|---|
| **P80** | `top_20` (upper-tail 0.200) | `0.34374423771129053` | `0.37451166510581970` |
| **P90** | `top_10` (upper-tail 0.100) | `0.4316724978559594` | `0.4455914924640810` |

Availability status, carried verbatim into `results/provenance.json`:

```text
P90 bullish   AVAILABLE_AND_FROZEN                              (reproduced exactly)
P90 bearish   RECONSTRUCTED_FROM_FROZEN_CALIBRATION_DISTRIBUTION
P80 bullish   RECONSTRUCTED_FROM_FROZEN_CALIBRATION_DISTRIBUTION
P80 bearish   RECONSTRUCTED_FROM_FROZEN_CALIBRATION_DISTRIBUTION
```

**P80 is not retrospectively derived from this study's 2024 distribution**, and no
intermediate threshold is optimised. Reconstruction happened in the accepted
canonical-store study from the *frozen 2025 calibration distribution*; this study
reads the value and never recomputes it.

### 2.2 Direction is one-to-one with model (inherited)

`bullish_in_domain & bearish_in_domain` is true for zero rows. Bullish model
in-domain ⇒ established bullish regime ⇒ **SHORT** fade. Bearish ⇒ **LONG**.
"By model" and "by direction" are the same partition.

### 2.3 Contaminations that are disclosed rather than fixed

Three, all inherited, all stated in the REPORT next to any number they touch:

1. **The scoring models were trained on 2021–2024.** `BULLISH_STRICT_top25_gbt_v2`
   and `LONG_STRICT_top25_gbt_v2` both carry `train_years = [2021,2022,2023,2024]`,
   `dev_year = 2025`. **2024 is IN-SAMPLE for the existing score.** The prime event
   itself, and every `MODEL_STATE` feature derived from the score, are therefore
   optimistically sharp on 2024 relative to a true out-of-sample year. This is a
   *ceiling* disclosure: a Model-A result that leans on score-state features would
   be weaker on unseen data, so a **negative** result under this contamination is
   strong, and a **positive** one is provisional. 2024 remains the correct choice —
   2025 is the models' dev year *and* the threshold calibration year, which is worse.
2. **Threshold calibration is calendar-2025**, i.e. after the evaluation window.
   Canonical waiver `studies/full_trade_path_builder/THRESHOLD_OVERLAP_WAIVER.json`.
   2024 is *not* described as threshold-out-of-sample anywhere, in either direction.
3. **`is_frozen` reconstruction** for three of the four thresholds (§2.1).

### 2.4 What is NOT contaminated

The canonical inline 25-feature vectors and the scores in
`canonical_regime_scores_all.parquet` are the **causally corrected** v2 artifacts.
`BULLISH_STRICT_top25_gbt_v2`'s model card records that it *"replaces the
provisional one-second-look-ahead Bullish artifact."* The long side was corrected
in `long_rth_mirrored_surface_top100_training` after a CRITICAL audit finding.
**Both directions in the canonical store are the fixed convention**
(`latest_source_ts_used < observation_time`).

---

## 3. The feature contract — resolved, and why it is not "Top-100"

The brief asked for the existing Top-100 causal features. Resolution from the
repository, recorded here because the answer changes the study:

| Option | Coverage of 2024 in-domain checkpoints | Causal status |
|---|---|---|
| Canonical inline **25** per direction | **100%** | Both directions CORRECTED (§2.4) |
| **Top-100** via join to `prepared_2024` / `prepared_long_2024` | **75.1% SHORT / 81.4% LONG** | SHORT surface carries a **disclosed, UNFIXED 1s look-ahead** in its OHLCV/price features; LONG surface fixed |

The Top-100 vectors are not in the canonical store. They exist only in per-year
training surfaces built on a *different* established-regime filter, so a join drops
19–25% of candidates with an unquantified selection effect, and the SHORT arm
would be ~1s optimistic while the LONG arm is not — making the mandatory
LONG/SHORT comparison not apples-to-apples on the exact axis this study must
report.

**FROZEN DECISION (study owner, before implementation): use the canonical 25 +
state families.** They are the deployed model's own feature set, causally clean in
both directions, and available for every candidate. This study therefore reports
on the `F25` market family, not `F100`. **The REPORT states this explicitly and
lists "does the wider Top-100 market library add information after a prime?" as
EXPLICITLY UNPROVEN (§12 Q20).**

### 3.1 The four feature families (frozen; every model is fit on each)

```text
FAM_MARKET   the 25 canonical inline features of the IN-DOMAIN model, verbatim,
             plus their __is_null companions
FAM_STATE    model-score state and trajectory (§5.3 / §8.3)
FAM_REGIME   regime/trade state carried by the store (§5.3 / §8.3)
FAM_PATH     1s price-path context computed from COMPLETED bars only (§5.4)

ABL_MARKET   FAM_MARKET only
ABL_STATE    FAM_STATE + FAM_REGIME only          } the brief's "model-state only"
ABL_ALL      all four                              } the brief's "combined"
```

`ABL_ALL` is the headline. All three are fit and reported for both models — that
comparison is the brief's A10/B3 question and is not optional.

---

# MODEL A — P80/P90-PRIMED FORWARD OPPORTUNITY

## 4. The candidate (A0/A1)

### 4.1 The prime event, inherited verbatim from the accepted arm contract

```text
prime(L) = the first true in-domain SCORED dispatch in a regime where
             probability >= threshold(L, direction)
           AND the immediately preceding in-domain SCORED dispatch in the SAME
             regime did NOT qualify                       (true crossing from below)
           AND seconds_from_regime_start > 600            (established, aged)
```

- A regime whose **first** in-domain dispatch already qualifies is **not** primed —
  no predecessor means no observed crossing, and accepting it asserts a rise from
  below on zero evidence.
- **Unscored dispatches are not observations.** ~8% of in-domain dispatches carry a
  null probability (a frozen feature was incomplete and the model declined to
  score). They are dropped from the observation stream *before* the crossing test,
  exactly as in the accepted contract. Causally, a null is not evidence of "below
  threshold"; numerically, a null poisons `np.maximum.accumulate`.
- **One candidate per regime per prime type.** Later re-crossings are counted into
  `n_recent_prime_crossings` but do not create a second row.

`L ∈ {P80, P90}` are run **independently**. The from-below and age gates are
applied separately per level, so **P80 is not a mechanical superset of P90.**

### 4.2 Reproduction gate — the rule must reproduce accepted lineage exactly

Running the P90 rule on 2024 must return **1,771 candidates (975 SHORT / 796 LONG)**,
matching `armed_fade_score_path_progression/results/armed_regime_score_paths.parquet`
sliced to `entry_year == 2024`, **regime-id for regime-id, timestamp for
timestamp**. Any mismatch aborts the study with verdict **A4/B4**.

*(Measured during SPEC preparation and frozen here as the target: P80 = 2,063
(1,110 SHORT / 953 LONG); P90 = 1,771. Overlap: 1,764 regimes carry both, 299 are
P80-only, **7** are P90-only. Median P80→P90 lag 60 s, p25 10 s, p75 ~215 s.)*

### 4.3 Frozen candidate reference state

```text
candidate_ns    = checkpoint_decision_ns of the priming dispatch
reference price = checkpoint_reference_price at that dispatch   (inherited arm_price)
frozen ATR      = atr_at_checkpoint at that dispatch            (inherited arm_atr)
fade direction  = +1 (LONG) if bearish model in-domain, -1 (SHORT) if bullish
```

The store carries **zero** dispatch latency in 2024
(`checkpoint_availability_ns == checkpoint_decision_ns` and
`score_available_ns == score_decision_ns` for every in-domain row, verified), so
decision time and availability time coincide and no latency adjustment applies.

**Disclosure, inherited not modified.** The accepted lineage anchors excursion at
`checkpoint_reference_price` rather than at an H4 next-bar-open fill. This study
inherits it so its numbers are comparable to the accepted pool, and additionally
reports a `REF_NEXT_OPEN` sensitivity on every Model-A baseline table.

### 4.4 Reported population breakdown (A1, mandatory)

`P80` · `P90` · `P80_only` · `P80_then_P90` · `P90_without_measurable_P80` ·
LONG / SHORT · month · quarter. Zero-count cells are retained with a flag.

## 5. Model-A labels, geometry and features

### 5.1 Forward payoff labels (A2) — frozen, not optimisable

```text
RISK   = 0.50 ATR      REWARD = 1.00 ATR      (from the candidate reference price)
HORIZONS = 180, 240, 300 s     PRIMARY = 300 s
```

The forward window begins at the **first 1s bar strictly after** `candidate_ns`
(`MarketData.index_strictly_after`, inherited) and is clamped to
`min(candidate_ns + H, 15:00 CT of the candidate's own session)`. No overnight
stitching; the window never leaves the candidate's session.

At each horizon:

```text
WIN        favourable +1.00 ATR barrier touched strictly before adverse -0.50 ATR
LOSS       adverse -0.50 ATR touched first
TIMEOUT    neither touched inside the horizon / session boundary
AMBIGUOUS  both touched on the SAME 1s bar; intrabar order unknowable from OHLC
```

**Primary economic labelling resolves AMBIGUOUS as LOSS.** An `optimistic`
label column resolving it as WIN is emitted alongside and reported as a
sensitivity on every baseline and bucket table. The ambiguous count is never
hidden.

**The confirming regime flip is NOT required for a WIN.** The question is whether
the *price opportunity* exists. The flip is a diagnostic (§5.2), never a target.

### 5.2 Forward geometry stored (A3) — LABELS AND DIAGNOSTICS ONLY

`MFE_180/240/300`, `MAE_180/240/300`, `time_to_+1ATR`, `time_to_-0.5ATR`,
`confirm_flip_occurred`, `seconds_to_confirm_flip`,
`confirmed_before_{180,240,300}`, `terminal_regime_outcome`,
`eventual_mfe_atr` (unconstrained, to the opposing flip or session close).

**Validation gate V4 asserts none of these column names appears in any feature
matrix**, by exact name-set intersection, for every model and every ablation.

### 5.3 `FAM_STATE` and `FAM_REGIME` (A5)

Computed from the regime's own dispatch history at times `<= candidate_ns` only.
Windowed statistics use true dispatches inside the window; a window with no
dispatch yields null (never forward-filled, never imputed).

```text
FAM_STATE
  relevant_model_score_now, opposite_model_score_now, opposite_in_domain
  score_at_prime, score_minus_prime
  distance_above_P80, distance_above_P90         (signed, in probability units)
  score_change_{5,15,30,60}s
  score_slope_{15,30,60}s                        (per second, OLS on true dispatches)
  score_max_{30,60}s, score_min_{30,60}s, score_range_{30,60}s
  seconds_since_P80, seconds_since_P90, P80_to_P90_seconds
  n_recent_prime_crossings                       (P80 and P90, within the regime)
  n_true_dispatches_{30,60}s, median_dispatch_gap_s
  score_in_domain, feature_complete, prime_type

FAM_REGIME  (verbatim from the store at the candidate dispatch)
  regime_age_seconds, seconds_from_established, score_sequence_in_regime
  running_mfe_atr, running_mae_atr, current_progress_atr
  new_progress_windows, retained_mfe_ratio, established_regime_gate
  atr_at_checkpoint, side
```

### 5.4 `FAM_PATH` (A5) — completed bars only

Computed from 1s bars with `path_init_ns <= candidate_ns`, i.e. the last bar to
*complete* at or before the decision second. Raw 1s bars are open-labelled
(`[t, t+1s)`), so this is the corrected `latest_source_ts_used < observation_time`
convention (§2.4) and admits **no** still-forming bar.

```text
ret_{15,30,60}s_atr           signed, in the FADE direction
realized_vol_{30,60}s_atr     stdev of 1s log-ish returns, ATR-normalised
dist_from_high_{60,300}s_atr, dist_from_low_{60,300}s_atr
dir_efficiency_{60,300}s      net move / summed absolute 1s moves
excursion_from_regime_start_atr, bar_range_{30,60}s_atr
```

## 6. Model class and training (A6)

The accepted family on this program, with the frozen hyperparameters carried by
the model manifests — no search, no tuning:

```text
PRIMARY   sklearn HistGradientBoostingClassifier
          max_depth=3, learning_rate=0.05, max_iter=200, random_state=42
BASELINE  LogisticRegression on median-imputed, standardised features
```

Native NaN handling is used for the GBT; nulls are **never** imputed for it.
Target: the primary 300 s `WIN` label, adverse-collision convention, binary
`WIN` vs `{LOSS, TIMEOUT}` — because an unresolved candidate is not a payoff.
`P(WIN | resolved)` is reported separately at every bucket.

**Two separate models (study owner's frozen decision): one fit on the P80
candidate set, one on the P90 candidate set.** They never share rows, never share
a fitted object, and are reported side by side. This is the clean read on "is P80
or P90 the better priming event" and costs training data, which is disclosed.

## 7. Temporal evaluation (A7) — no random split, ever

```text
FOLD 1   train 2024-01-01 .. 2024-06-30    evaluate 2024-07-01 .. 2024-09-30
FOLD 2   train 2024-01-01 .. 2024-09-30    evaluate 2024-10-01 .. 2024-12-31
```

Boundaries are America/Chicago calendar dates applied to `candidate_ns`, half-open
on the right. **Gate V5** asserts `max(train candidate_ns) < min(eval candidate_ns)`
for both folds, in integer nanoseconds. Headline results are the **pooled
temporal-OOS predictions** of folds 1+2 (Jul–Dec). Training metrics are computed,
stored, and never headlined.

Jan–Jun is train-only in both folds and never contributes an OOS prediction. This
is stated wherever pooled OOS `N` appears.

## 8. MODEL B — POST-CONFIRM CONTINUATION

### 8.1 Observations (B1)

Imported from the accepted `post_confirm_profit_ratchet/results/rung_events.parquet`,
sliced `entry_year == 2024`, `basis == POST_CONFIRM`. **Never re-derived** — the
lineage is accepted and re-deriving it is how a study silently forks a population.

```text
rungs      X in {1.0, 1.5, 2.0, 2.5, 3.0, 4.0} ATR
event      first causal achievement of X at or after confirmation
           (POST_CONFIRM basis = max(r_entry(X), confirmation index), inherited)
2024 N     2,991 rung observations over 781 trades
           1.0:781  1.5:658  2.0:522  2.5:426  3.0:356  4.0:248
           98.0-98.9% stop_live_reachable
           (856 is the 2024 MEASURABLE CONFIRMED trade panel; the 75 trades that
            never reach +1.0 ATR contribute no rung event and are absent here.
            Both numbers appear in population_reconciliation.json.)
```

A trade contributes to multiple rungs. **Every table reports `n_observations` and
`n_unique_trades`**, and all fold assignment is at TRADE level (§8.5).

Rungs are **pooled into one model with `rung_atr` as a feature** — 2024 alone
cannot support six per-rung models — and every result is broken out by rung.

`target_already_met_at_arm` rows are excluded from labels and models: their
required excursion is zero by construction, not by evidence. Count reported.

### 8.2 Continuation labels (B2)

From the causal high-water mark at the rung bar (`hwm_at_arm_atr`, entry-anchored,
inherited), over the window strictly after the rung bar and clamped to
`min(rung + H, unconstrained terminal, session close)`:

```text
FAVOURABLE   HWM + 0.50 ATR   (secondary: HWM + 1.00 ATR)
ADVERSE      HWM - 0.50 / -0.75 / -1.00 / -1.25 ATR      (all four, not optimised)
HORIZONS     180, 240, 300 s
```

The HWM used at bar `k` is the causal running MFE **through the previous completed
bar** — a bar that both sets a new high and breaches the adverse level counts as
adverse. Using the bar's own high would let it raise the reference before its own
low tests it: a same-bar look-ahead. Inherited from the ratchet contract D4.

Same-bar collision ⇒ **adverse** (primary); optimistic sensitivity reported.

```text
FROZEN PRIMARY TARGET (declared before training, per the brief's recommendation)
    +0.50 favourable before -0.75 adverse, within 300 s
```

**Baseline frequencies for all 4 × 3 × 2 frozen combinations are computed and
reported in Stage 2, BEFORE any model is fit.** If the frozen primary is changed
after seeing them, the change is labelled an explicit **SPEC AMENDMENT** with its
date and reason, and is never presented as pre-specified.

### 8.3 Model-B features (B3)

`FAM_MARKET` (the 25 canonical features of whichever model is in-domain at the rung)
plus:

```text
TRADE STATE (causal, from the inherited window)
  rung_atr, current_mfe_atr, return_from_entry_atr, return_since_confirm_atr
  drawdown_from_hwm_atr, hwm_at_arm_atr, rung_overshoot_atr
  seconds_since_confirm, seconds_since_entry, seconds_since_last_favourable_extreme
  progress_{15,30,60}s_atr, adverse_progress_{15,30,60}s_atr
  n_recent_favourable_extremes, side, entry_atr

EXIT-WARNING MODEL STATE
  After confirmation the prevailing regime has flipped INTO the trade direction, so
  the model that is in-domain is the OPPOSITE one — the model whose flip would END
  this trade. That is the causally correct "exit warning" score, and it is what
  FAM_STATE carries at a rung:
    exit_warning_score_now, exit_warning_in_domain
    exit_score_change_/slope_{15,30,60}s, exit_score_max/min/range_{30,60}s
    exit_distance_above_P80, exit_distance_above_P90
    exit_above_P80, exit_above_P90, seconds_since_exit_P80/P90 crossing
```

Coverage of the exit-warning score at rung time is **measured and reported**, not
assumed: the new regime must be established before its model is in domain, so
early rungs will carry nulls. Nulls are passed to the GBT natively and never
imputed. `exit_warning_in_domain` makes the missingness itself visible to the model.

`eventual_max_mfe_atr`, `runner_bucket`, terminal returns and terminal timestamps
are **retrospective labels** and may never enter a Model-B feature matrix (gate V4).

### 8.4 Model-B temporal folds (B4)

The **same calendar folds as Model A**, applied to the trade's `entry_ns`.
**All observations of a trade land on the same side of every boundary**, asserted
by gate V6 (`n_trades_spanning_boundary == 0`). A rung whose event time falls in a
later month than its entry stays with its entry — the alternative leaks a trade
across the boundary.

### 8.5 Dependence

Bootstrap intervals resample **trades** with replacement (1,000 draws, seed
20260811). No p-value is quoted from pooled rung observations. Every pooled table
carries `n_unique_trades` beside `n_observations`.

## 9. Evaluation (A8/A9/B5/B6)

### 9.1 Buckets — identical for both models

`all` · `top 50%` · `top 25%` · `top 20%` · `top 10%` · `top 5%` · `top 2.5%` ·
`top 1%`, cut on **pooled temporal-OOS predicted probability**.

Model A per bucket: `n`, `pct_retained`, `WIN%`, `LOSS%`, `TIMEOUT%`,
`P(WIN|resolved)`, mean/median `MFE300`, mean/median `MAE300`, `MFE/MAE`,
`confirmation_rate`, `median_secs_to_confirmation`,
`expected_gross_atr` (+1 WIN / −0.5 LOSS / timeout marked to horizon),
`expected_net_atr` (after 0.50 points, ATR-normalised per candidate).

Model B per bucket: `n_obs`, `n_unique_trades`, `continuation_success%`,
`favourable_hit%`, `adverse_hit%`, `timeout%`, forward MFE, forward MAE,
`eventual_natural_exit_return_atr`, and the EXIT-NOW vs CONTINUE comparison (§9.3).

Both broken out by: Fold 1 / Fold 2 / LONG / SHORT, plus prime type (A) and rung (B).

### 9.2 Monotonicity (A9) is the primary criterion, not AUC

Spearman rank correlation of bucket index against `WIN%` / `MFE300` / `MFE-MAE
ratio` / `expected_net_atr`, plus the count of adjacent-bucket inversions. A model
is **not** called useful because one small tail bucket makes money.

### 9.3 Model-B economic interpretation (B6) — diagnostic only

For each bucket, `EXIT NOW` (mark at the rung bar, one cost charged) versus
`CONTINUE` (the accepted natural management to its terminal). **No threshold is
selected. No exit is optimised.** The question answered is only: *do low-score
states have negative forward continuation value?*

## 10. Advancement gates — machine-evaluated, frozen

### Model A (all seven required to advance beyond 2024)

```text
A-1  MONOTONIC     WIN% is broadly monotone in bucket: Spearman >= 0.80 over the
                   8 buckets AND at most 1 adjacent inversion
A-2  TAIL          top-10% and top-5% WIN% each exceed the all-candidate WIN% by
                   >= 5 percentage points ABSOLUTE
A-3  BOTH FOLDS    A-2 holds in Fold 1 and Fold 2 separately (same sign, both > 0)
A-4  DIRECTION     no catastrophic inversion: neither LONG nor SHORT top-10% WIN%
                   is BELOW its own all-candidate WIN%
A-5  ECONOMICS     top-10% expected_net_atr > 0 AND > the all-candidate value, with
                   a bootstrap CI lower bound > 0
A-6  SAMPLE        top-5% bucket n >= 30 in pooled OOS
A-7  FAMILIES      ABL_ALL beats max(ABL_MARKET, ABL_STATE) on pooled-OOS AUC by
                   >= 0.02, OR one family alone already satisfies A-1..A-6
```

### Model B (all seven required)

```text
B-1  SEPARATION    top-decile minus bottom-decile continuation success >= 15pp
B-2  MONOTONIC     Spearman >= 0.80 over the 8 buckets, <= 1 adjacent inversion
B-3  BOTH FOLDS    B-1 holds in Fold 1 and Fold 2 separately
B-4  ECONOMICS     bottom-decile CONTINUE value < EXIT-NOW value, CI excluding 0
B-5  NOT-COMPOSITION  separation survives stratification by rung, and by
                   seconds_since_confirm tercile — i.e. it is not a restatement of
                   "which rung" or "how long the trade has run"
B-6  BOTH SIDES    LONG and SHORT agree in sign on B-1
B-7  SAMPLE        every reported bucket has n_unique_trades >= 20
```

**No deployment threshold is frozen by this study under any outcome.**

## 11. Deliverables Manifest (the completion gate checks this list literally)

| # | Path | Required |
|---|---|---|
| 1 | `results/provenance.json` | threshold values, availability status, model train-years, waiver path, feature-family decision + rejected Top-100 coverage numbers |
| 2 | `results/population_reconciliation.json` | P90 reproduction vs accepted arm table (regime-id + timestamp exact), P80/P90 counts and overlap, Model-B rung counts vs accepted artifact |
| 3 | `results/model_a_candidates.parquet` | one row per candidate: identity, reference state, all features |
| 4 | `results/model_a_forward_labels.parquet` | all §5.1/§5.2 labels and geometry, both collision conventions |
| 5 | `results/model_a_baselines.csv` | §A4 baseline table, per prime × slice, + `REF_NEXT_OPEN` sensitivity |
| 6 | `results/model_a_oos_predictions.parquet` | pooled temporal-OOS predictions, per model × ablation |
| 7 | `results/model_a_bucket_performance.csv` | §9.1 buckets |
| 8 | `results/model_a_fold_performance.csv` | per fold × prime × ablation × side |
| 9–14 | `results/model_b_{observations,forward_labels}.parquet`, `model_b_{baselines,bucket_performance,fold_performance}.csv`, `model_b_oos_predictions.parquet` | the Model-B equivalents |
| 15 | `results/feature_family_ablation.csv` | ALWAYS emitted (it is a gate input, not a bonus) |
| 16 | `results/feature_importance.csv` | **only if** a gate passes; else absent and the REPORT says why |
| 17 | `results/validation_report.json` | the §13 gates, `all_passed` |
| 18 | `results/summary.json` | Q1–Q20 answers + the three terminal labels |
| 19 | `SPEC.md` · `README.md` · `REPORT.md` | REPORT answers Q1–Q20 and ends with exactly three labels |
| 20 | `audit/lint.json` · `audit/status.json` · `audit/contract_status.json` | `critical: 0` required |

### Terminal labels — routing is total, every label reachable

```text
MODEL A   A1 STRONG SIGNAL — EXPAND        all 7 Model-A gates pass
          A2 WEAK BUT PLAUSIBLE            A-1 or A-2 passes, but not all 7
          A3 NO USEFUL SIGNAL              neither A-1 nor A-2 passes
          A4 INVALID / CAUSAL OR DATA FAILURE   any surviving CRITICAL, or §4.2
                                           reproduction fails, or a seal breach
MODEL B   B1 / B2 / B3 / B4                same structure on B-1, B-2, and the
                                           Model-B gate set
PROGRAM   P1 ENTRY MODEL IS THE PRIORITY        A1 and not B1
          P2 CONTINUATION MODEL IS PRIORITY     B1 and not A1
          P3 BOTH WARRANT FULL DEVELOPMENT      A1 and B1
          P4 NEITHER WARRANTS EXPANSION         neither A1 nor B1
          (if either model is A4/B4, PROGRAM is withheld and the defect reported)
```

## 12. Domain & completeness contract

- **Partitions:** 4 quarters × 2 sides × 2 primes = **16 Model-A partitions**; 4
  quarters × 2 sides × 6 rungs = **48 Model-B partitions**. All enumerated; empty
  cells retained with a flag, never dropped.
- **Bucket completeness:** 8 buckets × 2 primes × 3 ablations for A; 8 × 3 for B.
- **Label completeness:** every candidate carries a non-null label in
  `{WIN, LOSS, TIMEOUT}` at every one of the three horizons under both collision
  conventions. `n_candidates × 3 × 2 == n_label_rows` is a hard assertion.
- **Nulls are never imputed** for the GBT and never forward-filled anywhere. A
  quantile over `n < 20` is emitted null with the count visible.
- **Boundary convention:** America/Chicago; RTH `[08:30, 15:00)` CT; every window
  clamped to the observation's own session.

## 13. Validation gates (all must pass)

```text
V1  2024 SEAL. Every source scan filters entry_year == 2024; no produced frame
    holds a timestamp outside calendar-2024 CT. No path references 2021/2022/
    2023/2025/2026. Asserted at the source, before any fit.
V2  P90 prime rule reproduces the accepted 2024 arm population EXACTLY:
    1,771 rows, 975 SHORT / 796 LONG, zero regime-id or timestamp mismatches.
V3  Model-B observations reproduce the accepted 2024 rung counts exactly:
    2,991 observations / 781 trades and the six per-rung counts.
V4  NO LABEL IN FEATURES. Exact name-set intersection of every feature matrix
    with the label/diagnostic name set is EMPTY, for every model and ablation.
    Includes eventual MFE, runner bucket, terminal ts/return, confirm flip.
V5  FOLD CAUSALITY. max(train ts) < min(eval ts) in integer ns, both folds,
    both models. No random split anywhere in the code path.
V6  TRADE CONTAINMENT. Zero Model-B trades contribute observations to both the
    training and the evaluation side of any fold.
V7  FEATURE AVAILABILITY. Every FAM_PATH input bar satisfies
    path_init_ns <= decision_ns; every FAM_STATE dispatch satisfies
    score_decision_ns <= decision_ns. Verified by HARD-TRUNCATED replay of
    >= 250 observations rebuilt from the raw store with all later rows deleted,
    >= 6 quantities each, 0 mismatches.
V8  FORWARD LABELS STRICTLY AFTER. Every label window begins at
    index_strictly_after(decision_ns). Verified on the same truncated replay.
V9  SESSION CONTAINMENT. Every label window lies inside the observation's own
    RTH session; no overnight stitching; forced flat at 15:00 CT.
V10 COLLISIONS. Same-bar collisions counted, resolved adversely in the primary,
    optimistic bound present on every baseline and bucket table.
V11 DEPENDENCE. Every pooled Model-B table carries n_unique_trades; all
    bootstrap resampling is at trade level.
V12 PROVENANCE. Threshold values byte-match the frozen contract table;
    availability status and the 2021-2024 train-year contamination are recorded
    in provenance.json and stated in REPORT.
V13 causal_lint exits 0; lookahead-auditor and contract-checker both report
    critical = 0.
```

Any surviving CRITICAL forces **A4/B4** and withholds the program recommendation.

## 14. Staging (checkpointed; the brief's sequence)

```text
STAGE 1  provenance + SPEC + candidate/observation populations + labels
STAGE 2  baseline tables (both models) — BEFORE any fit
STAGE 3  Model A temporal OOS   (continue to Stage 4 even if A fails)
STAGE 4  Model B temporal OOS
STAGE 5  feature diagnostics + ablations — ablations ALWAYS (gate input);
         permutation/SHAP ONLY if a gate passes
STAGE 6  audits + REPORT
```

Pre-execution audit of the candidate/label construction runs after Stage 1 and
**before** Stage 3, per the standing pre-execution audit rule.

## 15. Questions the REPORT must answer (Q1–Q20 of the brief)

Verbatim from the brief, §"REPORT — ANSWER THESE QUESTIONS DIRECTLY". The REPORT
answers all twenty in plain English and ends with exactly three labels: one Model-A,
one Model-B, one PROGRAM.
