# Model-B Low-Tail Deterioration Forensic (2024)

**Study:** `model_b_low_tail_deterioration` · **Frozen:** 2026-08-11, before any low-tail
table is computed.
**Type:** FORENSIC EXTENSION. Not a model study. Not a policy study. Not a deployment study.
**Substrate:** the frozen result artifacts of `studies/p80_p90_opportunity_continuation_ml/`
**only**. No catalog scan except the Phase-7 timing re-derivation (§7), which is confined to
the identical 2024 trade windows the predecessor already measured.

---

## 0. The question

The predecessor's Model B failed six of seven advancement gates and earned
`B2 WEAK BUT PLAUSIBLE`. One quantity inside it did not fail:

```text
bottom-decile  continue_return - exit_now_return  =  -0.7198 ATR
trade-clustered 95% CI                            =  [-1.3032, -0.1799]
```

The general continuation classifier is dead and is not revisited here. The single
question is whether the **LOW** tail of the frozen Model-B out-of-sample prediction
identifies a deterioration state in which EXIT NOW is worth materially more than
CONTINUE UNDER ACCEPTED MANAGEMENT.

We are **not** asking whether high scores find runners. The predecessor answered that:
they do not.

### Binding non-goals

```text
NO retraining. NO refitting. NO recalibration. Not for any target, fold, side or rung.
NO feature changes. NO feature selection. NO new features.
NO new exit policy. NO threshold search. NO horizon search. NO barrier derivation.
NO years other than 2024. 2021, 2022, 2023, 2025, 2026 remain SEALED.
NO retrospective selection of a "best" cut as a deployment threshold.
```

The frozen grids in this SPEC are **diagnostic**. If several neighbouring cuts agree,
that is evidence. If exactly one cut works, that is suspicion, and the REPORT must say so.

---

## 1. Frozen scope and the 2024 seal

```text
instrument   NQ, *.v.0 volume-continuous only (inherited; never re-selected here)
YEAR         2024 ONLY, inherited from the predecessor's own seal
SEALED       2021, 2022, 2023, 2025, 2026 — none may be read, for any purpose
session      RTH only, [08:30, 15:00) CT, half-open — inherited
cost         COST_POINTS = 0.50 (2 ticks round-turn), charged as 0.50 / entry_atr
             per observation, exactly as the predecessor charged it
ATR          entry_atr, frozen at the observation, inherited row-for-row
```

**Seal enforcement (gate V1).** Every input is a file under
`studies/p80_p90_opportunity_continuation_ml/results/`. The Phase-7 re-derivation filters
`entry_year == 2024` at the source scan. Every produced frame is asserted to carry no
observation timestamp outside calendar-2024 America/Chicago before any table is written.

---

## 2. Population — resolved, not assumed

The brief names 2,991 observations / 781 trades. That is the **dataset**. It is not the
analysis population.

```text
FULL rung dataset            2,991 observations / 781 unique trades
  per rung  1.0:781  1.5:658  2.0:522  2.5:426  3.0:356  4.0:248

OOS ANALYSIS POPULATION      1,410 observations / 380 unique trades   <- everything below
  has_oos == True; Jul-Dec 2024. Jan-Jun is train-only in both folds and
  carries no out-of-sample prediction.
  per rung  1.0:380  1.5:315  2.0:248  2.5:197  3.0:161  4.0:109
  FOLD_1  720 obs / 188 trades      FOLD_2  690 obs / 192 trades
  SHORT   807 obs                   LONG    603 obs
```

The brief's own headline confirms this is the intended population: the quoted baseline
`48.4397163%` is exactly `683 / 1410`. On the full 2,991 the same baseline is 49.1809%.

**Consequence, disclosed up front.** The tails are thin, and no amount of analysis will
thicken them:

| cut | observations | approx. unique trades |
|---|---|---|
| bottom 25% | 352 | ~200 |
| bottom 20% | 282 | ~165 |
| bottom 10% | 141 | **78** |
| bottom 5% | 70 | ~37 |
| bottom 2.5% | 35 | **~17 — below the 20-trade floor** |

Cells whose unique-trade count is `< 20` are emitted and stamped `UNDERPOWERED`. They are
never dropped and never used to support a verdict.

---

## 3. The EXIT-NOW definition — the study's one substantive amendment

The predecessor computed, in `analysis/gates.py` B-4:

```python
diff = nat_terminal_return_atr - current_mfe_atr
```

`current_mfe_atr` is the trade's **running high-water mark** at the rung. It is not a
price anyone can transact at. The executable value of EXIT NOW is the **mark**,
`return_from_entry_atr`, which sits below the HWM by `drawdown_from_hwm_atr`:

```text
drawdown_from_hwm_atr over the 1,410 OOS observations
  mean 0.1300   median 0.0751   p75 0.1584   max 1.2514
```

Grading an exit rule against the HWM credits it with 0.130 ATR of fill it cannot obtain.
This is the accepted `running_extremum_mechanically_contains_eventual_extremum` failure
mode. Measured, the amendment is not cosmetic:

| quantity | HWM-based (frozen) | MARK-based (executable) |
|---|---|---|
| pooled continue − exit | −0.2846 | **−0.1546** |
| bottom decile continue − exit | −0.7198 | **−0.2764** |

**Frozen decision.** Both are computed and both are reported in every economics table.

```text
EXIT_HWM   = current_mfe_atr        - COST_POINTS / entry_atr    (lineage only)
EXIT_MARK  = return_from_entry_atr  - COST_POINTS / entry_atr    (PRIMARY)
CONTINUE   = nat_terminal_return_atr - COST_POINTS / entry_atr

continue_minus_exit_hwm  = nat_terminal_return_atr - current_mfe_atr
continue_minus_exit_mark = nat_terminal_return_atr - return_from_entry_atr   <- PRIMARY
```

Cost cancels in both differences — one exit is taken either way. `EXIT_HWM` exists solely
to reproduce the frozen lineage in Phase 0. **The D1/D2/D3/D4 gate reads the MARK column.**

**Note on the barriers.** The predecessor's forward barriers are HWM-anchored
(`hwm + f` favourable, `hwm − a` adverse, per `observations_b._continuation_labels`).
The adverse leg therefore *already is* a drawdown-from-HWM rule. This makes the Phase-9
drawdown-only control the single most important placebo in the study, not a formality.

---

## 4. Frozen cut grid

### 4.1 Nested cuts (the brief's grid — the deliverable)

```text
ALL, bottom 50, 40, 30, 25, 20, 15, 10, 7.5, 5, 2.5   (percent of observations)
```

Ranked by `oos_prob` **ascending**. Ties broken by stable sort on the frozen row order,
identical to the predecessor's `np.argsort(..., kind="stable")`.

### 4.2 Disjoint decile bands (the honest monotonicity test)

```text
[0,10) [10,20) [20,30) [30,40) [40,50) [50,60) [60,70) [70,80) [80,90) [90,100]
```

Nested cuts share most of their observations with each other, so a rank correlation over
them is inflated by construction rather than by signal. **Spearman and the inversion count
are computed on the DISJOINT bands.** The nested-cut Spearman is also reported, labelled
`spearman_nested_CONSTRUCTION_CORRELATED`, and is not a gate input.

### 4.3 Fold percentile construction

Percentiles are re-ranked **within** each fold, exactly as the predecessor's `gates.py`
built `fold_sep` (`prf = pr[m]; o = argsort(-prf); kk = 0.10 * prf.size`). The two folds are
separate fits with separate calibrations, so a pooled probability threshold is not
comparable across them. The pooled-threshold-applied-within-fold variant is emitted as a
secondary column, `cut_basis = POOLED_THRESHOLD`, and is diagnostic only.

---

## 5. Metrics emitted for every cut

```text
identity      cut, cut_basis, scope, n_obs, n_unique_trades,
              pct_obs_retained, pct_trades_touched, underpowered (bool)
score         mean_model_score, score_boundary
outcome       continuation_success_pct, favourable_pct, adverse_pct, timeout_pct
economics     exit_now_hwm_atr, exit_now_mark_atr, continue_atr,
              continue_minus_exit_hwm_atr, continue_minus_exit_mark_atr,
              ci95_lo_mark, ci95_hi_mark, ci95_lo_hwm, ci95_hi_hwm
geometry      fwd_mfe_300_mean, fwd_mae_300_mean
eventual      nat_terminal_return_atr_mean  (accepted-management return)
composition   mean_rung, median_seconds_since_confirm
```

**Bootstrap.** Trade-clustered, resampling unique `regime_id` with replacement,
1,000 draws, `np.random.default_rng(20260811)` — the predecessor's seed and draw count, so
the Phase-0 CI reproduces bit-for-bit.

---

## 6. Phases

| Phase | Question | Output |
|---|---|---|
| 0 | Does the lineage reproduce exactly? | `lineage_reconciliation.json` |
| 1 | Does the low tail deteriorate monotonically? | `low_tail_curve.csv` |
| 2 | In both temporal folds? | `low_tail_by_fold.csv` |
| 3 | On both sides? | `low_tail_by_side.csv` |
| 4 | Within rung, or is it rung composition? | `low_tail_by_rung.csv` |
| 5 | Within trade age, or is it just old trades? | `low_tail_by_time_since_confirm.csv` |
| 6 | Does it clean up as the adverse barrier widens? | `alternative_barrier_results.csv` |
| 7 | What does a low score physically mean? | `low_tail_forward_geometry.csv` |
| 8 | How many trades would actually be signalled? | `first_trigger_*.csv` |
| 9 | Does it beat matched simple rules? | `placebo_controls.csv` |
| 10 | Is the low tail economically interpretable? | `feature_forensics.csv` |

### Phase 0 — reproduction, and the STOP condition

Reproduce, to the stated precision:

```text
2,991 observations · 781 trades · per-rung 781/658/522/426/356/248
1,410 OOS observations · 380 OOS trades
baseline (+0.50 favourable before -0.75 adverse, 300 s) = 48.4397163 %
bottom-decile continue-minus-exit (HWM) = -0.7197866 ATR
trade-clustered 95 % CI                 = [-1.3032425, -0.1799056]
```

Any material failure is a **STOP**: no downstream phase runs, and the REPORT diagnoses
lineage instead of answering the research question.

### Phase 5 — frozen time strata

Inherited verbatim from the predecessor, terciles of `seconds_since_confirm` over the full
2,991-row frame — **not** re-derived on the OOS subset, so the boundaries stay frozen:

```text
SINCECONF_T1   seconds_since_confirm <=  10
SINCECONF_T2   10 < seconds_since_confirm <= 194
SINCECONF_T3   seconds_since_confirm >  194
```

### Phase 6 — frozen barrier grid, no refit

12 frozen label families: favourable `+0.50` × adverse `{0.50, 0.75, 1.00, 1.25}` ×
horizon `{180, 240, 300}` s. Unconditional base rates over the full frame, already frozen:

| adverse | 180 s | 240 s | 300 s |
|---|---|---|---|
| 0.50 | 36.643 | 37.078 | 37.212 |
| **0.75** | 47.141 | 48.546 | **49.181 (primary)** |
| 1.00 | 52.524 | 55.166 | 56.436 |
| 1.25 | 54.731 | 58.108 | 60.181 |

`OOS AUC` for an alternative target means **the frozen predictions scored against that
target's labels**. Retraining is forbidden, so this measures whether the existing ranking
happens to order a different question better — not what a model trained on that target
could do. The REPORT must state this limit wherever it quotes one of these AUCs.

### Phase 7 — timing re-derivation, and its own gate

`median seconds to next favourable extreme` and `median seconds to adverse barrier` were
never persisted; `_continuation_labels` kept only `fwd_mfe / fwd_mae / fwd_bars`. They are
re-derived by re-running the accepted `top10_fast_confirm_runner_path.implementation.engine
.prepare()` over the identical 2024 trade windows and recording first-hit bar indices.

**Gate V7 (hard).** Before any newly derived field is used, the re-derivation must
reproduce the frozen `fwd_mfe_{180,240,300}` and `fwd_mae_{180,240,300}` and all 12
`lab_f050_a*_*` labels on all 2,991 rows with **zero** mismatches. If it does not, the
timing fields are dropped and reported `NOT_AVAILABLE`; nothing else in the study changes.

The re-derivation inherits the predecessor's same-bar convention exactly: a bar that both
sets a new high and breaches the adverse level counts **ADVERSE**.

### Phase 8 — first trigger per trade

For each of bottom 25 / 20 / 10 / 5, take the **first chronological** qualifying
observation per trade and evaluate it once. Reported per cut:

```text
n_triggered_trades, pct_of_380
trigger_rung distribution, median seconds_since_confirm at trigger
return_at_trigger, mfe_at_trigger
exit_now_mark_atr, exit_now_hwm_atr, accepted_management_atr, difference (both bases)
pct_R3_intercepted (eventual_max_mfe_atr >= 3), pct_ge4_intercepted
pct_eventual_losers_intercepted, pct_eventual_winners_intercepted
```

This is a translation, not a policy. It is not optimised and produces no threshold.

### Phase 9 — mandatory matched controls

Each is matched to the ML trigger on **trigger count**, and on rung and
`seconds_since_confirm` distribution as closely as a discrete population permits (stratified
draw within rung × SINCECONF tercile cells, deficits reported, never silently absorbed):

```text
C1  random matched observations                (200 replications, seed 20260811)
C2  rung-only rule
C3  seconds-since-confirm-only rule
C4  drawdown-from-HWM-only rule
```

Each of C2–C4 runs in **both** rank directions (`_ASC` / `_DESC`) and the ML trigger must
beat the better of the pair. Picking the direction that happens to lose would build a
strawman, which is the failure this phase exists to prevent.

**Amendment, `audit/pass_01.md` CRITICAL-1, applied 2026-08-11.** C2–C4 were first built
by taking each trade's *most extreme* observation on the control variable. That is
hindsight — at rung 2 nobody knows whether rung 4 will later show a deeper drawdown, a
higher rung, or a later timestamp — and it is the accepted
`running_extremum_mechanically_contains_eventual_extremum` defect applied to a control
rather than to a signal. It materially flattered the controls. They are now **causal
threshold rules**: a threshold is walked out from the extreme of the pooled observation
distribution until exactly `n` distinct trades have at least one crossing, and each trade
fires at its **first** crossing — the same shape of rule as the ML trigger, so the
comparison is like-for-like. Both the pre- and post-correction numbers appear in the
REPORT.

C1 is composition-matched (stratified on rung × SINCECONF cell), not length-blind. A
uniform draw over a realised lifetime is itself a mild look-ahead
(`placebo_must_be_length_blind`); the stratification controls the rung and age imbalance
that drives it, but C1 is disclosed as the weaker of the four controls and is not the
binding one.

**The ML trigger must beat the matched controls.** Beating accepted management is not a
result — the predecessor established that continue-minus-exit is negative in *every*
bucket, including the top decile. C4 is the decisive one, because the adverse barrier is
itself a drawdown rule (§3).

---

## 7. Deliverables Manifest (the completion gate checks this list literally)

| # | Path | Required content |
|---|---|---|
| 1 | `results/lineage_reconciliation.json` | every Phase-0 quantity, accepted vs reproduced vs delta, plus `stop_triggered` |
| 2 | `results/low_tail_curve.csv` | §5 metrics × 11 nested cuts × 10 disjoint bands, pooled |
| 3 | `results/low_tail_by_fold.csv` | FOLD_1, FOLD_2 × {ALL, 25, 20, 10, 5} × both `cut_basis` |
| 4 | `results/low_tail_by_side.csv` | LONG, SHORT × {25, 20, 10, 5} |
| 5 | `results/low_tail_by_rung.csv` | 6 rungs × {ALL, 20, 10}, `underpowered` stamped |
| 6 | `results/low_tail_by_time_since_confirm.csv` | 3 frozen strata × {ALL, 25, 20, 10, 5} |
| 7 | `results/alternative_barrier_results.csv` | 12 targets × {unconditional, AUC} × {25, 20, 10, 5} |
| 8 | `results/low_tail_forward_geometry.csv` | Phase-7 table for ALL / 20 / 10 / 5; timing columns or an explicit `NOT_AVAILABLE` |
| 9 | `results/first_trigger_per_trade.csv` | one row per triggered trade per cut |
| 10 | `results/first_trigger_economics.csv` | the Phase-8 aggregate per cut |
| 11 | `results/placebo_controls.csv` | C1–C4 vs ML per cut, with match-quality columns |
| 12 | `results/feature_forensics.csv` | named §Phase-10 features × {25, 10, 5} vs ALL |
| 13 | `results/validation_report.json` | V1–V8, `all_passed` |
| 14 | `results/summary.json` | the 17 REPORT answers + the terminal label |
| 15 | `SPEC.md` · `README.md` · `REPORT.md` | REPORT answers Q1–Q17 and ends with exactly one label |
| 16 | `audit/lint.json` · `audit/status.json` · `audit/contract_status.json` | `critical: 0` required |

Every listed file is emitted on every run. A phase that cannot be computed emits its file
with an explicit reason column, never an absent file.

**Version control.** `*.csv` is gitignored repo-wide (`.gitignore:82`), so rows 2–12 are
run artifacts, not committed ones — the same convention the predecessor followed, which
committed its four result JSONs and none of its CSVs or parquets. The committed record is
the code, the SPEC/README/REPORT, the audit files, and `lineage_reconciliation.json` /
`validation_report.json` / `summary.json`. Every number quoted in REPORT.md is
reproducible from those plus one `run_study.py` invocation (~13 s), and the ones that
carry a verdict are additionally mirrored into `summary.json.report_answers`.

---

## 8. Domain & completeness contract

- **Partitions.** 11 nested cuts + 10 disjoint bands, × {POOLED, FOLD_1, FOLD_2, LONG,
  SHORT, 6 rungs, 3 SINCECONF strata}. All enumerated; empty and underpowered cells are
  **retained with a flag**, never dropped.
- **Row conservation.** Every cut table asserts `n_obs` equals the exact count implied by
  its percentile, and that the disjoint bands sum to 1,410 with no observation in two bands.
- **Trade conservation.** Union of unique trades across the 10 disjoint bands is asserted
  ≤ 380, and the first-trigger table is asserted to hold at most one row per
  `(cut, regime_id)`.
- **Nulls are never imputed and never forward-filled.** A quantile over `n < 20` is emitted
  null with the count visible.
- **Integer nanoseconds** for every timestamp comparison and every chronological ordering
  in Phase 8. No float seconds anywhere in a comparison.
- **Boundary convention.** America/Chicago; RTH `[08:30, 15:00)` CT.

---

## 9. Validation gates (all must pass)

```text
V1  2024 SEAL. No input path outside the predecessor results dir and the 2024 windows;
    no produced frame holds a timestamp outside calendar-2024 CT.
V2  LINEAGE. All six Phase-0 quantities reproduce to the stated precision. STOP on failure.
V3  NO REFIT. No estimator is constructed, fit, or loaded for fitting anywhere in this
    study. Asserted by static check over the implementation package.
V4  POPULATION. n_obs == 1410 and n_unique_trades == 380 for every POOLED table.
V5  DISJOINT BANDS partition the population exactly: sum(n) == 1410, pairwise empty
    intersection.
V6  FIRST TRIGGER is chronological and unique. BOTH clauses are checked:
      UNIQUENESS  at most one row per (cut, regime_id);
      MINIMALITY  that row's rung_ts equals the minimum rung_ts among the trade's
                  qualifying observations, recomputed by a DIFFERENT code path
                  (groupby-min, not sort-then-head) so the gate does not audit itself.
V7  TIMING RE-DERIVATION reproduces the frozen fwd_mfe/fwd_mae and all 12 labels on all
    2,991 rows with zero mismatches, or the timing fields are withheld.
V8  PLACEBO MATCH QUALITY. Each control's trigger count equals the ML trigger count, and
    its rung / SINCECONF cell deficits are reported.
```

## 10. Decision gate — D1 / D2 / D3 / D4

Read on the **MARK** economics (§3). The predecessor's Model-B gate set is not used.

```text
D1 STRONG LOW-TAIL DETERIORATION SIGNAL
   requires ALL of:
     disjoint-band Spearman >= 0.70 with <= 2 inversions
     bottom 10 and bottom 20 both materially worse than ALL (>= 0.15 ATR worse)
     same SIGN in FOLD_1 and FOLD_2
     same SIGN in LONG and SHORT
     survives rung control: negative in a majority of rungs, no sign flip in a
       rung with >= 20 unique trades
     survives time control: negative in all three frozen SINCECONF strata
     beats C1-C4 matched controls on the first-trigger economics
     bottom-10 unique trades >= 20 at every stratum quoted in support
   -> warrants a larger multi-year dedicated deterioration model

D2 PLAUSIBLE BUT UNDERPOWERED
   economic effect substantial and direction broadly coherent, but 2024 sample size
   prevents a strong conclusion (CIs span zero, or supporting cells underpowered)
   -> warrants a larger study explicitly as VALIDATION, not development

D3 COMPOSITION / PLACEBO EFFECT
   the low-tail advantage disappears under rung, time, or drawdown control, or fails
   to beat a matched placebo
   -> do not expand ML

D4 UNSTABLE / NO SIGNAL
   non-monotonic curve, folds disagree materially, sides invert, or the economics
   do not persist
```

**Routing precedence is total and explicitly ordered** `D1 > D3 > D4 > D2`:

```text
all eight conditions pass          -> D1
else a control killed the effect   -> D3   (rung, time, or matched placebo)
else the evidence is incoherent    -> D4   (folds disagree, sides invert, non-monotone)
else the tail effect is material   -> D2
else                               -> D4
```

`D3` outranks both `D2` and `D4`. An effect that a control *explains* has been diagnosed;
an effect that is merely unstable has not. Diagnosing it is the more informative and the
more restrictive verdict, so it wins whenever both apply. `D3` over `D2` specifically:
an underpowered effect that a placebo already accounts for is a composition effect, not a
power problem, and more data would only measure the composition more precisely.

**If D1 or D2:** the REPORT recommends the next study's architecture (a compact
15–30-feature causal state/path model, market features dropped) and **does not begin
training.** That is out of scope here.

---

## 11. Honesty clause

A negative result is not softened. If the −0.72 ATR is a small-sample or composition
artifact — and §3 already shows more than half of it is an unexecutable HWM fill — the
REPORT says so plainly and closes the branch.
