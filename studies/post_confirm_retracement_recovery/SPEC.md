# Post-Confirmation HWM Retracement → Recovery / Failure Map

**Status:** FROZEN before implementation · **Tier:** 2 (research study)
**Branch:** `study/post_confirm_retracement_recovery`
**Immediate predecessor:** `studies/model_b_low_tail_deterioration/` (accepted, **D3 COMPOSITION / PLACEBO EFFECT**)
**Substrate lineage:** `post_confirm_profit_ratchet` → `top10_fast_confirm_runner_path` → `armed_fade_score_path_progression`

---

## 1. Purpose and hypothesis

Determine whether profitable confirmed Top-10 trades can be managed better by
treating drawdown from the high-water mark as an **ARMING EVENT** rather than an
**EXIT**.

This is a PRICE-PATH / STATE study. **No model is trained.** No estimator library
may be imported anywhere in this package (gate V3). No deployable exit policy is
optimised during the descriptive phases.

The hypothesis under test:

> Drawdown itself is normal runner behaviour. The economically useful distinction
> is `RETRACEMENT → RECOVERY` versus `RETRACEMENT → FAILURE TO RECOVER → TERMINAL
> DETERIORATION`.

### 1.1 Why the predecessor motivates this

`model_b_low_tail_deterioration` established (accepted):

| Finding | Value |
|---|---|
| HWM-based continue-minus-exit, bottom decile | −0.7198 ATR |
| Mark-based (executable) continue-minus-exit | −0.2764 ATR |
| Mark-based 95% CI | [−0.845, +0.247] — spans zero |
| Share of headline that was an unreachable HWM price | 61.6% |
| Disjoint-decile Spearman (economic ranking) | −0.0545 |
| Step inversions | 4 |

Model-B was found to be substantially a restatement of `drawdown_from_HWM` plus
near-term volatility, and the most extreme apparent-deterioration states
**frequently recovered**: at bottom-5, P(new favourable extreme) = 65.7%, median
forward MFE 0.779 ATR, median final return **+0.552 ATR**.

Therefore a large or fast retracement is **not** sufficient evidence that a
runner is over. This study asks what happens *after* the retracement.

### 1.2 Prior art that constrains the expected answer

`post_confirm_profit_ratchet` (accepted, verdict D) already established, on this
exact population, that the *depth* axis is close to memoryless:

- Required retracement for successful continuation: median 0.526–0.595 ATR,
  p90 1.388–1.699 ATR, essentially flat across rungs 1.0 → 4.0.
- Successful continuations draw down **more** than failures (median 2.35–2.75 vs
  1.97–2.36 ATR), because they live ~3× longer.
- Raw AUC 0.96–0.97 collapsed to 0.56–0.75 on matched elapsed windows.

**Consequence for this SPEC:** Phases 1, 3 and 5 are expected to come back
approximately flat in the rung dimension. That is a reproduction, not a null.
The genuinely new axis in this study is **TIME-TO-RECOVER**, which the ratchet
study did not measure. The REPORT must state this explicitly so a flat
rung table is not read as an absence of result.

---

## 2. Questions the REPORT must answer directly

| # | Question |
|---|---|
| Q1 | How frequently do confirmed trades retrace 0.50 / 0.75 / 1.00 / 1.25 ATR after reaching each MFE rung? |
| Q2 | After each retracement, how often do trades recover 25% / 50% / 75% / 100% / new HWM? |
| Q3 | How quickly do healthy trades recover? |
| Q4 | How much additional adverse excursion do eventual recoverers require? |
| Q5 | Does failure to recover become progressively more informative with time? |
| Q6 | At what frozen horizons, if any, does continuation value turn negative? |
| Q7 | Does failure to recover predict economic deterioration better than the retracement itself? |
| Q8 | Does it outperform simple drawdown / trade age / rung age / current return controls? |
| Q9 | How many ≥3 ATR and ≥4 ATR runners would each state destroy? |
| Q10 | Does the relationship survive LONG / SHORT separation? |
| Q11 | Is there an obvious broad recovery-time knee rather than an isolated optimised cell? |
| Q12 | Does the evidence support R1 / R2 / R3 / R4? |
| Q13 | Next step: ML recovery/failure model, price-only exit architecture, more descriptive years, or abandonment? |

---

## 3. Population — inherited, never re-invented

Source of truth: `studies/post_confirm_profit_ratchet/results/rung_events.parquet`
(rung population) and `trade_panel.parquet` (trade population). The trade window
is rebuilt with the accepted
`studies.top10_fast_confirm_runner_path.implementation.engine.prepare()` so the
bar arrays are the same objects the accepted geometry was measured on.

**Scope: 2021–2025, all five years. 2026 remains sealed and is never read.**
No model is trained, so no fold calendar is required; Phase 14 mandates per-year
breakouts, which a single year cannot support.

### 3.1 Accepted counts to reproduce in Phase 0 (gate V2)

| Quantity | Accepted |
|---|---|
| Original Top-10 entries | 8,950 |
| Confirmed | 4,705 |
| Stopped before confirm | 4,245 |
| Measurable confirmed | 4,656 |
| Non-measurable | 49 |
| Giveback pool / entry | 0.89808 ATR |
| Baseline net / entry | −0.07653 ATR |
| Trades reaching ≥1.0 ATR rung | 4,160 |
| Rung events, POST_CONFIRM basis | 15,220 |

Per-rung, POST_CONFIRM basis:

| Rung | 1.0 | 1.5 | 2.0 | 2.5 | 3.0 | 4.0 |
|---|---|---|---|---|---|---|
| N | 4,160 | 3,358 | 2,692 | 2,134 | 1,742 | 1,134 |

If lineage materially fails, **STOP**. Do not repair silently.

### 3.2 Rung basis

`POST_CONFIRM` is primary — the arming index is clamped to the confirmation bar,
matching the accepted ratchet SPEC D2. Requiring a fresh re-touch after
confirmation would select on a retracement, which is the variable under study.
`FROM_ENTRY` is not used.

---

## 4. Dual path — mandatory labelling

| Path | Terminal | Used for |
|---|---|---|
| **A. UNCONSTRAINED DESCRIPTIVE** | `unc_i` — first of opposing flip / 15:00 CT session close, 1 ATR stop released | Phases 1–7, 10. What price naturally does after retracement. |
| **B. STOP-LIVE ECONOMIC** | `nat_i` — first of 1 ATR stop / opposing flip / session close | Phases 8, 9, 11, 12. Realisable economics and accepted-management comparison. |

Every table carries an explicit `path` column. The two are never combined
without labels (gate V8). Recovery geometry is **not** censored merely because
the accepted 1 ATR stop would have fired — that is the censoring trap recorded in
`censored_population_cannot_answer_its_own_premise`.

Economic phases restrict to arms and decision bars that are stop-live reachable
(`arm_idx <= nat_i` and `decision_idx <= nat_i`); the retained fraction is
reported per cell, never silently dropped.

---

## 5. Frozen grids — none of these is optimisable

```
RUNGS          X ∈ (1.00, 1.50, 2.00, 2.50, 3.00, 4.00)   ATR
RETRACEMENTS   D ∈ (0.50, 0.75, 1.00, 1.25)               ATR
RECOVERY       (R25, R50, R75, R100, NEW_HWM)
HORIZONS_S     T ∈ (15, 30, 60, 120, 180, 300)            seconds
CURVE_GRID_S   0..300 seconds, 1 s resolution (Phase 10 only)
RUNNER_TIERS   (3.0, 4.0) ATR — Phase 9 destruction test
COST_POINTS    0.50 (2 ticks round-turn), charged as COST_POINTS / entry_atr
SEED           20260811
N_BOOT         1000
UNDERPOWERED   < 20 unique trades → quantiles and CIs emitted NULL, count visible
PLACEBO_OFFSETS_S  range(15, 601, 15)     # dense, length-blind
N_PLACEBO      20
```

The NO-OPTIMIZATION RULE governs: no threshold outside these grids may be
reported as a result. If several neighbouring cells show the same transition the
evidence strengthens; a single isolated working cell is treated as suspicion, not
as a finding.

---

## 6. Core definitions

All quantities are direction-normalised and expressed in frozen entry ATR.
`w` is the accepted `Window`. `hwm_prev = concat(([-inf], run_mfe[:-1]))` is the
running high-water mark **through the previous completed bar**.

### 6.1 Rung index

```
r = max(first(bar_hi[:unc_i+1] >= X), ci)          # POST_CONFIRM basis
```

### 6.2 Retracement arm — intrabar trigger, causal HWM

```
a = first k in (r, unc_i]  such that  bar_lo[k] <= hwm_prev[k] - D
```

`hwm_prev[k]`, never `run_mfe[k]`: a bar's own high may not lift the reference
above its own low. This is the same causal/adverse rule the accepted ratchet
uses for its HWM architecture. The breach surface is a function of the path
alone and is **independent of the rung**, so four surfaces per trade serve all
24 cells — one implementation of the trigger, not twenty-four.

**RETRACEMENT IS AN ARM. IT IS NOT AN EXIT.**

### 6.3 Arm strata (Phase 0 of every cell)

| Stratum | Condition | Treatment |
|---|---|---|
| `ALREADY_AT_D` | `run_mfe[r] - mark[r] >= D` OR `bar_lo[r] <= hwm_prev[r] - D` — the trade is already D below its HWM at the rung bar | Counted per cell, **excluded from every primary distribution**. Its time-to-arm is zero by construction, not by evidence. |
| `ARM_FRESH` | drawdown < D at the rung bar, and a breach subsequently occurs at some `k > r` | **PRIMARY.** |
| `NO_ARM` | no breach in `(r, unc_i]` | Counted; contributes to the denominator of "% of rung trades retracing". |

This mirrors the ratchet study's `ALREADY_MET` handling, where including
by-construction rows inflated a probability ladder by 21.9 points.

### 6.4 Frozen recovery anchors

At the arm bar `a`, freeze and never update:

```
HWM_ARM  = hwm_prev[a]          # the causal reference the breach was measured against
MARK_ARM = mark[a]              # close of the arm bar
DD       = HWM_ARM - MARK_ARM
```

Later HWM updates **do not** move the recovery targets (gate V5).

Because the trigger is intrabar and `MARK_ARM` is the close, `DD` is an observed
quantity and is **not** guaranteed to equal `D`. This is deliberate and is
itself reportable:

| Case | Label | Treatment |
|---|---|---|
| `DD <= 0` | `ARM_CLOSED_AT_HWM` — the bar spiked down and closed at or above the HWM | Counted per cell, excluded from recovery-timing primaries (recovery is trivially satisfied at t=0). |
| `0 < DD < D` | partial intrabar recovery within the arm bar | Retained in primary; the fraction is reported per cell. |
| `DD >= D` | close confirms the retracement | Retained in primary. |

`retracement_frequency.csv` reports the `DD` distribution against `D` per cell so
the gap between trigger depth and realised close depth is visible rather than
assumed away.

### 6.5 Recovery events — intrabar, anchored, scanned from `a+1`

```
R25      first k in (a, unc_i]  with  bar_hi[k] >= MARK_ARM + 0.25 * DD
R50      ...                          bar_hi[k] >= MARK_ARM + 0.50 * DD
R75      ...                          bar_hi[k] >= MARK_ARM + 0.75 * DD
R100     ...                          bar_hi[k] >= HWM_ARM
NEW_HWM  ...                          bar_hi[k] >  HWM_ARM
```

Recovery is detected on the intrabar high, symmetrically with the intrabar-low
arm. The arm bar itself is excluded. `R100` and `NEW_HWM` differ by strict
versus non-strict comparison — on a 0.25-tick grid this is the difference
between touching the old high and setting a new one; both are reported.

---

## 7. Phase contract

| Phase | Output | Path | Population |
|---|---|---|---|
| 0 | Lineage reconciliation | both | all |
| 1 | Retracement frequency map, rung × D | A | all arms + strata counts |
| 2 | Recovery anchors frozen | A | ARM_FRESH |
| 3 | Recovery probability, constant-population | A | ARM_FRESH |
| 4 | Time to recovery, paired with resolution rate | A | ARM_FRESH recoverers |
| 5 | Additional adverse excursion before recovery | A | ARM_FRESH recoverers (censored count reported) |
| 6 | Recovery-vs-failure geometry at fixed horizons | A | ARM_FRESH |
| 7 | Failed-recovery states (frozen) | A | ARM_FRESH |
| 8 | Conditional economics | B | ARM_FRESH, stop-live reachable |
| 9 | Runner destruction test | B | ARM_FRESH, stop-live reachable |
| 10 | Recovery curves, 0–300 s | A | ARM_FRESH |
| 11 | Conditional value curve | B | ARM_FRESH, stop-live reachable |
| 12 | Price-only exit diagnostics, first-trigger-per-trade | B | all trades (denominator = entries) |
| 13 | Placebo / simple controls | B | count-matched |
| 14 | LONG/SHORT and per-year stability | both | as applicable |

### 7.1 Phase 3 — constant-population accounting (gate V6)

The denominator for every headline recovery probability is **all ARM_FRESH arms
in the cell**. A trade that terminates before recovering counts as a **failure to
recover**, never as a removal from the denominator. Alive-only variants are
emitted as clearly-suffixed secondary diagnostics (`_alive_only`) and may not be
used for any verdict.

### 7.2 Phase 4 — conditional statistics are never reported alone (gate V7)

Every conditional recovery-time statistic is emitted on the same row as its
resolution rate. `recovery_timing.csv` carries `p_recovered_by_T` and
`median_secs_to_recovery_given_recovery` together; a row with one and not the
other is a gate failure.

### 7.3 Phase 7 — the frozen failed-recovery states

| State | Definition | Horizons T (s) |
|---|---|---|
| `NO_R25` | failed to recover 25% of DD within T | 15, 30, 60, 120, 180 |
| `NO_R50` | failed to recover 50% of DD within T | 15, 30, 60, 120, 180 |
| `NO_R75` | failed to recover 75% of DD within T | 30, 60, 120, 180 |
| `NO_HWM_RECLAIM` | failed to reclaim `HWM_ARM` within T | 30, 60, 120, 180, 300 |
| `NO_NEW_HWM` | no new favourable extreme within T | 30, 60, 120, 180, 300 |

A state's decision bar is `j = first k with ts[k] >= arm_ts + T*NS`. The label
uses only information in `(a, j]` (gate V4).

### 7.4 Phase 8 — EXIT NOW is executable, always (gate V3)

```
exit_now_atr  = realise(j, fill_next=True) - cost      # bar j+1 OPEN
continue_atr  = nat_terminal_return_atr    - cost      # accepted management
cme_mark      = nat_terminal_return_atr - realise(j, fill_next=True)   # cost cancels
```

**HWM is never an exit price.** It is reported as descriptive state only. The
predecessor's headline lost 61.6% of its magnitude at the mark and its CI stopped
excluding zero; that defect is invisible to `causal_lint` because no future
information is used — the price is simply unreachable. An `exit_now_hwm_atr`
column is emitted **for contrast only** and is barred from every verdict.

### 7.5 Phase 13 — placebo contract

Every apparently-useful failed-recovery state is compared against, matched on
rung, retracement depth, trade age and trigger count:

1. `TIME_SINCE_CONFIRM_ONLY`
2. `TIME_SINCE_RUNG_ONLY`
3. `DRAWDOWN_FROM_HWM_ONLY`
4. `CURRENT_RETURN_ONLY`
5. `RETRACEMENT_ONLY` — the arm with no recovery condition. **This is the
   decisive control**: it operationalises "retracement itself is not sufficient".
6. `RANDOM_TIMING` — count-matched, **LENGTH-BLIND**.

The random control draws an offset from the frozen `PLACEBO_OFFSETS_S` grid
applied to the arm bar, 20 draws. It **may not** draw uniformly over the
realised lifetime: that is itself look-ahead and has twice destroyed a headline
in this repo (`placebo_must_be_length_blind`, `early_exit_rules_need_a_matched_placebo`).
When a drawn offset falls past the terminal the control simply does not fire, the
same treatment the real rule receives, so denominators stay equal.

---

## 8. Deliverables Manifest — frozen before implementation

The completion gate checks this list literally. Anything not listed here cannot
be demanded later.

| # | Path | Type | Required contents |
|---|---|---|---|
| 1 | `SPEC.md` | doc | this file |
| 2 | `README.md` | doc | how to run, module map, path/label conventions |
| 3 | `REPORT.md` | report | answers Q1–Q13 of §2 verbatim; emits one terminal label from §9 |
| 4 | `results/lineage_reconciliation.json` | json | every row of §3.1: `quantity`, `observed`, `accepted`, `delta`, `status` |
| 5 | `results/retracement_frequency.csv` | table | `rung_atr, retracement_d, path, n_rung_trades, n_armed, pct_retracing, n_arm_fresh, n_already_at_d, n_no_arm, n_arm_closed_at_hwm, pct_dd_lt_d, median_secs_rung_to_arm, p25/p75/p90_secs_rung_to_arm, mark_at_arm_atr_median, hwm_at_arm_atr_median, dd_median, dd_p25, dd_p75, pct_stop_live_reachable` |
| 6 | `results/recovery_probability.csv` | table | `rung_atr, retracement_d, recovery_level, n_arm_fresh, p_recover_before_terminal, p_recover_15/30/60/120/180/300, p_recover_*_alive_only, n_alive_*` |
| 7 | `results/recovery_timing.csv` | table | `rung_atr, retracement_d, recovery_level, n_arm_fresh, n_recovered, p_recovered, median_secs, p25_secs, p75_secs, p90_secs, underpowered` |
| 8 | `results/adverse_before_recovery.csv` | table | `rung_atr, retracement_d, recovery_level, n_recovered, n_censored, median_add_adverse_atr, p75, p90, p95, underpowered` |
| 9 | `results/recovery_state_panel.parquet` | table | one row per (arm, horizon): all Phase 6 state fields, `path='UNCONSTRAINED'`, `alive`, `alive_stop_live`, retrospective labels suffixed and enumerated |
| 10 | `results/failed_recovery_economics.csv` | table | `state, recovery_level, horizon_s, rung_atr, retracement_d, n_obs, n_unique_trades, pct_of_entries, pct_of_confirmed, pct_of_armed, exit_now_mark_atr, exit_now_hwm_atr, continue_atr, cme_mark_mean, cme_mark_median, ci95_lo, ci95_hi, remaining_mfe, remaining_mae, final_return, p_winner, p_loser, p_mfe_ge3, p_mfe_ge4, underpowered` |
| 11 | `results/conditional_value_curve.csv` | table | `recovery_level, horizon_s, rung_atr, retracement_d, n_obs, n_unique_trades, cme_mark_mean, ci95_lo, ci95_hi, remaining_mfe, remaining_mae, runner_survival_rate, underpowered` |
| 12 | `results/runner_interception.csv` | table | `state, recovery_level, horizon_s, pct_runners_ge3_intercepted, pct_runners_ge4_intercepted, pct_winners_intercepted, pct_losers_intercepted, loser_winner_ratio, n_*` |
| 13 | `results/price_only_diagnostics.csv` | table | `rule_id, rung_atr, retracement_d, recovery_level, horizon_s, n_triggered_trades, exit_return_atr, continuation_return_atr, delta_atr, ci95_lo, ci95_hi, pct_runners_ge3, pct_runners_ge4, n_winners_intercepted, n_losers_intercepted, side, entry_year` |
| 14 | `results/placebo_controls.csv` | table | `rule_id, control_id, n_triggered, delta_atr, ci95_lo, ci95_hi, delta_vs_control, control_beats_rule` |
| 15 | `results/by_side.csv` | table | every headline result split LONG / SHORT, with a `sign_inverted` flag |
| 16 | `results/by_year.csv` | table | every headline result split 2021–2025, with `years_consistent` |
| 17 | `results/recovery_curves.parquet` | table | `rung_atr, retracement_d, recovery_level, secs_since_arm (0..300), p_recovered, n_denominator` |
| 18 | `results/validation_report.json` | json | every gate in §10: `gate_id, description, passed, detail` |
| 19 | `results/summary.json` | json | terminal label, Q1–Q13 one-line answers, headline numbers, population counts |
| 20 | `audit/status.json` | json | machine-readable audit verdict; gates read this, never prose |

### 8.1 Terminal decision labels

Exactly one is emitted to `results/summary.json`. Every label is reachable.

| Label | Condition |
|---|---|
| `R1_STRONG_FAILED_RECOVERY_STATE` | Retracement alone is not sufficient (RETRACEMENT_ONLY control ≈ 0); failed recovery produces **ordered** economic deterioration with continuation value worsening monotonically as failure duration increases across ≥3 adjacent horizons; ≥2 neighbouring (rung, D) cells agree; survives rung and trade-age controls; beats all six §7.5 controls; same sign LONG and SHORT; preserves materially more ≥3 ATR runners than a direct drawdown exit at the same trigger count. |
| `R2_PRICE_ONLY_RULE_SUFFICIENT` | Failed recovery clearly identifies deterioration, but simple recovery/time geometry performs as well as anything richer. **DO NOT TRAIN ML** — test the price-only state as an exit architecture. |
| `R3_PLAUSIBLE_BUT_UNDERPOWERED` | Geometry coherent and economically meaningful, but cell counts below the underpowered floor or CIs spanning zero prevent a reliable conclusion. Expand years before any ML. |
| `R4_NO_USEFUL_FAILED_RECOVERY_STATE` | Healthy runners and eventual failures recover similarly; OR continuation value does not deteriorate with failed recovery; OR useful-looking cells disappear under §7.5 controls; OR runner destruction remains unacceptable. **STOP** predicting terminal deterioration from local post-confirm price behaviour under this architecture. |

An R4 result is **not to be softened**.

### 8.2 What would justify ML afterward

ML is out of scope for this study entirely. It becomes justified only if the
descriptive result establishes a real state (`reached ≥X ATR`, `retraced ≥D ATR`,
`failed to recover Y% within T s`) where continuation value is materially
negative, runner destruction is acceptably low, the effect survives §7.5, and
neighbouring cells agree. The ML problem would then be the clean one — *given a
retracement has occurred, which trades will fail to recover?* — not "predict
deterioration" at arbitrary post-confirm observations.

---

## 9. Domain & completeness contract

"Complete" means, for every one of the 24 (rung × D) cells and every one of the
five years:

- Every measurable confirmed trade reaching rung X is classified into exactly one
  of `{ARM_FRESH, ALREADY_AT_D, NO_ARM}`. The three counts must sum to
  `n_rung_trades` exactly (gate V9). A missing partition is a failure, not a gap.
- Every ARM_FRESH arm is classified for every recovery level into exactly one of
  `{recovered before terminal, terminated first}`. Counts sum to `n_arm_fresh`.
- Cells with `< 20` unique trades emit counts but NULL quantiles/CIs, flagged
  `underpowered=True`. They may not carry a verdict.
- No cell may be silently absent from an output table; an empty cell is emitted
  with `reason='EMPTY_CELL'`.

---

## 10. Validation gates

Written to `results/validation_report.json`. All must pass.

| Gate | Description |
|---|---|
| V1 | **2026 sealed.** Every `entry_ns` and every arm/decision timestamp resolves to calendar year 2021–2025 in America/Chicago, checked on timestamps, not partition columns. |
| V2 | **Lineage reproduced.** Every §3.1 quantity matches to the stated tolerance; per-rung counts exact. |
| V3 | **No estimator.** No sklearn/xgboost/lightgbm/torch import anywhere in the package. No `exit_now_hwm_atr` column feeds any verdict computation. |
| V4 | **Causal HWM.** The arm reference is `hwm_prev[k]`; asserted that no arm index satisfies the breach only under `run_mfe[k]`. Failed-recovery labels read only `(a, j]`. |
| V5 | **Frozen anchors.** `HWM_ARM` and `MARK_ARM` are captured at `a` and are bit-identical wherever re-read; recovery targets are asserted invariant to later HWM updates. |
| V6 | **Constant-population accounting.** For every cell and recovery level, `n_recovered + n_terminated_first == n_arm_fresh`. Alive-only columns carry the `_alive_only` suffix. |
| V7 | **Paired conditionals.** No row in `recovery_timing.csv` carries a conditional median without its resolution rate. |
| V8 | **Path non-contamination.** Every emitted row carries `path`; no descriptive statistic is computed on a stop-live-truncated array and no economic statistic on an unconstrained one. |
| V9 | **Partition completeness.** `n_arm_fresh + n_already_at_d + n_no_arm == n_rung_trades` for all 24 cells × 5 years. |
| V10 | **Fill convention.** The vectorised `fill_ret[i]` equals `w.realise(i, fill_next=True)` bar-for-bar on a sampled subset; a trigger on bar `i` is priced at bar `i+1`'s OPEN. |
| V11 | **First-trigger integrity.** Phase 12 first-trigger-per-trade indices are genuinely the earliest causal trigger; no later trigger precedes the recorded one. |
| V12 | **Length-blind placebo.** The random control draws from `PLACEBO_OFFSETS_S`, never from the realised lifetime; asserted that the control's denominator equals the rule's. |
| V13 | **Same-bar adversity.** Where intra-second ordering is unknowable, the adverse reading is taken; the optimistic bound is carried alongside and never substituted. |
| V14 | **No optimisation.** Every threshold appearing in any result is a member of a §5 frozen grid. |

Mandatory audit gate, in order, **before first full execution**:
`python scripts/causal_lint.py --study studies/post_confirm_retracement_recovery`
→ `lookahead-auditor` (causality) → `contract-checker` (deliverables).
Findings land in `audit/pass_NN.md` + `audit/status.json`, new file per pass.

---

## 11. Amendment A1 — manifest column-name reconciliation

Raised by `contract-checker` pass 1 as a WARNING. The §8 manifest named columns
before implementation; several shipped under different literals. **No manifest
quantity is missing** — every value is emitted, under the name below. This
amendment records the emitted names rather than renaming columns, because the
names are load-bearing for `validate.py`, the tests, and the emitted artifacts.

| Table | Manifest name | Emitted name | Note |
|---|---|---|---|
| `retracement_frequency.csv` | `n_armed` | `n_arm_fresh` | the armed count *is* the fresh-arm count |
| `retracement_frequency.csv` | `pct_retracing` | `pct_retracing_any`, `pct_retracing_fresh` | split; the manifest's single figure was ambiguous between the two |
| `retracement_frequency.csv` | `median_secs_rung_to_arm`, `p25/p75/p90_secs_rung_to_arm` | `secs_rung_to_arm_median`, `secs_rung_to_arm_p25/p75/p90` | prefix ordering only |
| `recovery_timing.csv` | `median_secs`, `p25_secs`, `p75_secs`, `p90_secs` | `secs_median`, `secs_p25`, `secs_p75`, `secs_p90` | prefix ordering only |
| `runner_interception.csv` | `pct_runners_ge3_intercepted`, `pct_runners_ge4_intercepted` | `pct_runners_ge3_0_intercepted`, `pct_runners_ge4_0_intercepted` | generated from `RUNNER_TIERS` via `tag()`, so the tier value is explicit |
| `price_only_diagnostics.csv` | `pct_runners_ge3_intercepted`, `pct_runners_ge4_intercepted` | `pct_runners_ge3_0_intercepted_of_triggered`, `pct_runners_ge4_0_intercepted_of_triggered` | same tier tagging, plus `_of_triggered`: the denominator here is the rule's **triggered** trades, not all runners as in `runner_interception.csv`. The two columns are not interchangeable and the suffix is what says so. |
| `placebo_controls.csv` | `n_triggered`, `ci95_lo`, `ci95_hi`, `delta_vs_control` | `rule_n_triggered`, `rule_ci95_lo`, `rule_ci95_hi`, `rule_minus_control` | `rule_`-prefixed to separate rule from control on the same row |
| `failed_recovery_economics.csv` | `exit_now_hwm_atr` | `exit_now_hwm_atr_CONTRAST_ONLY` | **deliberate**, per §7.4 and gate V3 — the suffix is what makes the gate enforceable |

### Amendment A2 — terminal-label decision thresholds

`run_study.py::_terminal_label` uses five scalars that are not members of any §5
grid: `MATERIAL_ATR = 0.05`, decisive-control win rate `< 0.25`, monotone-cell
count `>= 2`, side-inversion rate `< 0.5`, loser:winner ratio `>= 2.0`. §5 governs
thresholds appearing in *results*; these appear only in the label decision and are
disclosed here and in `REPORT.md` §9 rather than silently applied.

Each is set to favour the hypothesis, and the observed values miss by wide
margins (recovery-condition gap 0.0023 against 0.05; inversion 0.833 against
0.5), so the R4 label is not threshold-sensitive. `results/summary.json` emits
every clause with the number that decided it, so the label can be recomputed
under different thresholds without re-running the study.
