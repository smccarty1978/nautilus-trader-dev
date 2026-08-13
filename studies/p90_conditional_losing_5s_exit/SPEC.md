# P90 Conditional Losing-5s-Flip Failure Exit — Frozen Specification

**Study:** `p90_conditional_losing_5s_exit` · **Frozen:** 2026-08-12, before implementation.
**Branch:** `study/p90_conditional_losing_5s_exit`
**Predecessor:** `studies/p90_5s_regime_impulse/` (verdict `F4`, gates 26/26, both audits clear)
**Substrate:** `data/canonical/regime_complete_v1/`
**Population:** the frozen **8,950** Top-10 (P90) arms · 2021–2025 RTH · **2026 sealed**

---

## 0. The narrow question

The predecessor showed that exiting on **every** adverse 5s flip is too
aggressive: it cut 75.6% of trades before the thesis resolved and did not beat a
length-blind placebo. It also showed that crude rule made failures dramatically
cheaper (−1.052 → −0.363 ATR per failure arm).

> Can we tolerate normal 5s counter-regimes **while the trade is at or above its
> entry price**, and treat a 5s counter-regime occurring **below entry** as
> evidence the P90 attempt is failing?

This is a **failure-control** study. The 5s regime is not permitted to become a
profit-taking mechanism.

**Frozen conditional rule — the only threshold in this study:**

```text
at EVERY completed causal adverse 5s regime flip while the position is open:
    current_return_atr <  0   ->  LOSING_5S_FLIP_EXIT
    current_return_atr >= 0   ->  IGNORE_FLIP, continue
```

---

## 1. Inherited verbatim — NOT rebuilt

Consumed from the predecessor and its lineage without modification:

| Item | Source |
|---|---|
| P90 ≡ Top-10 arm definition and the 8,950-arm population | `armed_fade_score_path_progression/results/armed_regime_score_paths.parquet` |
| 5s regime engine, bucketing, flip timeline | `studies.p90_5s_regime_impulse.implementation.regime_5s` (imported, not reimplemented) |
| Entry qualification (5s already aligned at the arm) | `p90_5s_regime_impulse` SPEC §4.2 |
| Entry fill convention (open of first 1s bar with `path_init_ns > arm_ns`) | `p90_5s_regime_impulse` SPEC §4.3 |
| ATR (`arm_atr` = `atr_at_checkpoint` at the arm, frozen for the trade) | `p90_5s_regime_impulse` SPEC §2.4 |
| Cost: 2 ticks round turn = 0.50 points; flat band 0.125 points | `engine.py` `COST_POINTS` / `FLAT_POINTS` |
| Session: RTH, forced flat 15:00 CT of the entry session | shared engine |

The 5s flip timeline is **loaded** from the predecessor's `_work/` build
(2,054,398 flips), which is bit-parity-tested against a literal
`TimeframeAggregator` + `RegimeStateEngine` replay. It is not rebuilt here.

---

## 2. The accepted baseline lifecycle — resolved, not inferred

The brief said "continue toward the accepted natural opposing-regime exit /
session exit" and required a Phase 8 `AFTER_CONFIRM` decomposition. **Two
accepted lifecycles exist in the frozen artifact**, and they are different
animals:

| | **FULL** (`full_*`) | WALK A (`walk_a_*`) |
|---|---|---|
| exit | hold through confirmation → **opposing flip** | **at** the confirming flip |
| mean gross / net ATR | −0.0177 / −0.0751 | +0.0019 / −0.0555 |
| median net ATR | **−0.9629** | — |
| win rate | 27.1% | 51.5% |
| mean MFE | 1.7738 | — |
| Phase 8 `AFTER_CONFIRM` | **reachable** | structurally empty |

**Decision: the FULL lifecycle is the baseline.** It is what the brief describes,
and it is the only one under which `AFTER_CONFIRM` is a reachable label rather
than a declared-empty category. Walk A is still reproduced in Phase 0 and still
defines the confusion-matrix TARGET (§6).

Terminal labels of the accepted FULL lifecycle, reproduced exactly:

```text
STOPPED_BEFORE_CONFIRM  4245     FINAL_FLIP_EXIT_WINNER  2350
FINAL_FLIP_EXIT_LOSER   1359     CONFIRMED_THEN_STOPPED   822
SESSION_EXIT             174
```

### 2.1 Baseline mechanics, reproduced from `walks.py::continuation_label`

```text
entry        next-1s-open after arm_ns (predecessor convention)
horizon      min(session_close, opposing_ns)
             opposing_ns = next_start_after(entry_ns, -direction, inclusive=True)
             regimes strictly alternate, so from inside the pre-flip regime this
             resolves to the start of the regime AFTER the confirming one --
             i.e. the flip that ends the winning regime
stop         first bar with run_mae >= stop_atr; fills at the NEXT bar's open
flip/session fills at the CLOSE of the last bar in the window (no next-bar open
             exists for an exit caused by the window itself ending)
labels       STOPPED_BEFORE_CONFIRM / CONFIRMED_THEN_STOPPED /
             FINAL_FLIP_EXIT_WINNER / FINAL_FLIP_EXIT_LOSER / SESSION_EXIT
             (a FINAL_FLIP_EXIT_WINNER with gross <= 0 is relabelled LOSER)
```

**Parity gate (V2).** The baseline at `stop_atr = 1.00` entered at `arm_price`
must reproduce `terminal_label_full`, `full_gross_atr`, `full_net_atr`,
`full_mfe_atr` and `full_mae_atr` **exactly** for all 8,950 arms. The study then
runs on the next-1s-open fill; both conventions are reported.

---

## 3. Policies — exactly four, plus one control

| Name | Stop | Conditional losing-5s exit |
|---|---|---|
| `BASELINE_1.00` | 1.00 ATR | no |
| `COND_1.00` | 1.00 ATR | **yes** |
| `BASELINE_0.75` | 0.75 ATR | no |
| `COND_0.75` | 0.75 ATR | **yes** |
| `PLACEBO_COND_1.00` | 1.00 ATR | matched losing-state control (§7) |

Within a stop distance the baseline and conditional variant differ **only** by
the conditional rule (gate V6). The 0.75 and 1.00 variants share an identical
entry population (gate V7).

No break-even, no trail, no ratchet, no profit target, no other stop distance.

---

## 4. The conditional exit — causal contract

### 4.1 Adverse flip, mark, and fill

```text
adverse flip   a completed 5s bucket closing at C, C > arm_ns, whose regime
               is -direction. The engine is sticky binary, so this is exactly a
               flip AWAY from the trade direction.
mark           the CLOSE of the 1s bar whose path_init_ns == C. That bar covers
               (C-5s, C] and is the last bar in the flip bucket, so its close is
               the price at the instant the flip becomes known -- available AT C,
               not before, not after.
test           current_return_atr = (mark - entry_price) * direction / atr
               < 0  -> exit;  >= 0 -> ignore and continue
fill           the OPEN of the first 1s bar with path_init_ns > C
```

The trigger price is never credited: the mark decides, the **next** bar's open
fills. This is the same separation the stop uses.

### 4.2 Repeated flips — every one, not just the first

Every adverse flip is evaluated while the position remains open. A flip ignored
because the trade was above entry does **not** disarm the rule; the next adverse
flip is tested afresh against the same frozen threshold. The rule therefore
tolerates arbitrarily many profitable 5s oscillations and fires on the first
adverse flip that finds the trade below its entry price.

### 4.3 Collisions resolve adversely

If the stop's fill index ≤ the conditional exit's fill index, the **stop** wins,
the trade is flagged `ambiguous`, and both bounds are reported.

### 4.4 Confirmation is diagnostic only

The 1m confirmation never triggers, blocks, or modifies an exit. It is recorded
so that Phase 8 can split `BEFORE_CONFIRM` from `AFTER_CONFIRM`. Gate V5 asserts
that no exit label depends on it and that the conditional exit set is exactly
`{STOP, LOSING_5S_FLIP_EXIT, FLIP_EXIT, SESSION_EXIT}`.

---

## 5. Causal contract

- **Decision timestamps:** the arm (`arm_top10_ns`, a 5s clock boundary) for
  entry; each adverse flip `close_ts` for the conditional test.
- **Snap rule:** 5s regime state uses `close_ts <= decision_ts`; the mark uses
  the 1s bar with `path_init_ns == close_ts`; path bars use `path_init_ns` as the
  availability clock.
- **Regime/session mapping, separate from the snap rule:** 5s buckets are formed
  on `path_event_ns` (bar OPEN) and become available at `close_ts`.
- **Censoring:** trades end at stop / conditional exit / opposing flip / 15:00 CT.
  Nothing is dropped; non-entries and censored arms stay in the denominator.
- **Load-bearing checklist rules:** **A**, **B**, **C1–C3**, **F**, **G**, **H4**.

### 5.1 The ten audit items from the brief

| # | Item | Enforced by |
|---|---|---|
| 1 | 5s state known before the conditional decision | flip `close_ts` is the decision instant; gate V8 |
| 2 | `current_return_atr` uses a causally available mark | mark = close of the bar at `close_ts`; gate V9 |
| 3 | exit fills after the losing-flip state is known | fill = open of first bar with `path_init_ns > close_ts`; gate V9 |
| 4 | same-bar stop/conditional collision adverse | §4.3; `ambiguous` flag |
| 5 | future confirmation never affects exits | §4.4; gate V5 |
| 6 | baseline and conditional differ ONLY by the rule | gate V6 (identical entries, identical stop, label-set difference only) |
| 7 | 0.75 and 1.00 share entry populations | gate V7 |
| 8 | repeated flips processed causally | flips walked in ascending `close_ts`; gate V10 asserts monotone flip times and that the firing flip is the first losing one |
| 9 | placebo does not use future lifetime | §7; counts and times drawn from POOLED distributions |
| 10 | 2026 sealed | gate V11 |

---

## 6. Confusion matrix — frozen definitions

```text
SIGNAL  a losing adverse 5s flip occurring before the accepted WALK-A horizon
        (before the confirming flip, or before the 1.00 ATR stop, whichever
        bounds that walk)
TARGET  eventual failure to reach 1m confirmation under the accepted 1.00 ATR
        lifecycle  ==  NOT walk_a_confirm_reached_censored
```

TP/FP/TN/FN, sensitivity, specificity, PPV, NPV — reported overall, per year and
per side. **No threshold is tuned**; the threshold is `current_return_atr < 0`.

---

## 7. Matched placebo — mandatory in this family

The predecessor's `PLACEBO_EXIT` is what turned an apparent 65% failure-cost
reduction into a null. The control here must answer a sharper question:

> Is "losing **at an adverse 5s flip**" informative, or would testing "is it
> losing?" at similarly-timed observations that are **not** flips do the same?

**Construction.** The placebo keeps the losing test **identical** and removes only
the flip identity:

```text
k       ~ pooled distribution of per-trade adverse-flip COUNTS
tau_1..k~ pooled distribution of adverse-flip ELAPSED TIMES since entry
        both pooled across all entered trades, seeded default_rng(20260812)
check   snap each tau to the 5s grid, evaluate in ascending order
exit    at the first check where current_return_atr < 0, same mark and same
        next-bar-open fill as the real rule
```

Both `k` and the times come from **pooled** distributions, never from the trade's
own realised flip count or lifetime — a per-trade draw over its own realised span
is itself look-ahead (`placebo_must_be_length_blind`). Checks falling beyond the
trade's natural end are simply never reached; `p_unreached` is reported.

If the real rule does not beat this control, the informative variable is
**"the trade is losing at time t"**, not the 5s regime transition — verdict G2.

---

## 8. Deliverables Manifest  <!-- frozen before implementation -->

| # | Path | Type | Required contents |
|---|---|---|---|
| 1 | `results/lineage_reconciliation.json` | json | predecessor arm/entry/coverage/side/year counts; FULL-lifecycle parity (label + 4 metrics, exact); walk-A confirming MAE p50/p75/p80/p90/p95; each with `expected`/`observed`/`match` |
| 2 | `results/adverse_5s_flip_events.parquet` | table | `regime_id, side, entry_year, flip_number, flip_ns, seconds_since_entry, current_return_atr, current_mfe_atr, current_mae_atr, giveback_from_hwm_atr, is_losing, before_confirm, walk_a_confirmed, terminal_label_full` |
| 3 | `results/flip_state_geometry.csv` | table | `group, cohort(confirming/failure), n_flips, pct_losing, median_return_atr, median_seconds_since_entry, median_giveback_atr` by ALL/LONG/SHORT/year |
| 4 | `results/trade_level_signal_coverage.csv` | table | `cohort, n_trades, pct_any_adverse_flip, pct_any_losing_flip, pct_losing_before_1atr, pct_losing_before_075, median_seconds_to_first_losing, median_return_at_first_losing` |
| 5 | `results/failure_confusion_matrix.csv` | table | `group, tp, fp, tn, fn, sensitivity, specificity, ppv, npv, prevalence` for ALL/LONG/SHORT/year |
| 6 | `results/baseline_100.parquet` | table | one row per arm: `regime_id, side, direction, entry_year, arm_ns, entry_ns, entry_price, exit_ns, exit_price, atr, outcome, gross_atr, net_atr, mfe_atr, mae_atr, hold_s, ambiguous, confirm_ns, confirmed_before_exit, n_adverse_flips, n_losing_flips, terminal_label_full` |
| 7 | `results/conditional_100.parquet` | table | same columns + `fired_flip_number`, `return_at_fire_atr` |
| 8 | `results/baseline_075.parquet` | table | as #6 |
| 9 | `results/conditional_075.parquet` | table | as #7 |
| 10 | `results/primary_economics.csv` | table | `policy, n_original_arms, n_entered, entry_coverage, win_rate, mean_atr, median_atr, mean_winner, mean_loser, profit_factor, gross_atr_total, net_atr_total, exp_per_entry_gross, exp_per_entry_net, exp_per_arm_gross, exp_per_arm_net, ci_low, ci_high, max_dd_atr` |
| 11 | `results/failure_harvest.csv` | table | `policy, n_failure_arms, n_intercepted, interception_pct, mean_baseline_failure, mean_conditional_failure, median_baseline_failure, median_conditional_failure, atr_saved_per_intercepted, atr_saved_per_failure_arm, atr_saved_per_original_arm, n_still_reaching_stop` |
| 12 | `results/good_trade_destruction.csv` | table | `policy, source(losing_5s/tighter_stop), n_confirming_baseline, n_destroyed, pct_destroyed, mean_exit_return, mean_eventual_return, mean_eventual_mfe, atr_forfeited_total, atr_forfeited_per_confirming, atr_forfeited_per_original_arm` |
| 13 | `results/savings_vs_sacrifice.csv` | table | `policy, failure_atr_saved, good_trade_atr_forfeited, net_difference, net_atr_per_original_arm, d_max_dd, savings_sacrifice_ratio` |
| 14 | `results/pre_post_confirm.csv` | table | `policy, phase(BEFORE_CONFIRM/AFTER_CONFIRM), n, pct, mean_net_atr, median_net_atr, mean_return_at_fire, mean_eventual_baseline_atr, atr_delta_vs_baseline` |
| 15 | `results/flip_sequence.csv` | table | `policy, fired_flip_number(1/2/3/4+), n, pct, median_seconds_since_entry, median_return_at_fire, mean_net_atr, pct_baseline_failures` |
| 16 | `results/stop_interaction.csv` | table | `category, n, pct, mean_net_atr_100, mean_net_atr_075, delta` for the four Phase-10 categories |
| 17 | `results/matched_placebo.csv` | table | `policy, n_fired, mean_net_atr, exp_per_arm_net, ci_low, ci_high, delta_vs_conditional, delta_ci_low, delta_ci_high, delta_ci_excludes_zero, p_unreached` |
| 18 | `results/by_year.csv` | table | `policy, entry_year, n_entered, win_rate, exp_per_entry_net, exp_per_arm_net, max_dd_atr` |
| 19 | `results/by_side.csv` | table | `policy, side,` same columns as #18 |
| 20 | `results/validation_report.json` | json | every gate V1–V13 with `expected`, `observed`, `pass` |
| 21 | `results/summary.json` | json | verdict ∈ {G1,G2,G3,G4}, headline numbers, the 16 report answers keyed `q1`–`q16` |
| 22 | `results/partition_manifest.json` | json | input paths + sizes + row counts, code hash, seeds, frozen constants |
| 23 | `SPEC.md` / `README.md` / `REPORT.md` | docs | this contract; how to run; the answered questions |
| 24 | `audit/status.json` | json | roll-up with a key per agent; `critical: 0` required |

`*.parquet` and `*.csv` under `results/` are generated data and are **not
committed**, per the project rule; the JSON manifests are. All are regenerable
from `run_study.py`.

### 8.1 Terminal decision labels

| Label | Condition |
|---|---|
| `G1_CONDITIONAL_5S_FAILURE_EXIT_WORKS` | net delta per ORIGINAL arm > 0 vs its own baseline, **and** MaxDD improves, **and** ≥4/5 years positive delta, **and** no LONG/SHORT sign inversion, **and** the delta vs `PLACEBO_COND` CI excludes zero |
| `G2_LOSS_STATE_WORKS_5S_FLIP_DOES_NOT` | net delta per ORIGINAL arm > 0, **but** the placebo matches or beats it (delta-vs-placebo CI includes zero, or placebo delta ≥ conditional delta) |
| `G3_5S_INFORMATIVE_THRESHOLD_TOO_CRUDE` | failure interception is strong (≥50% of failure arms intercepted **and** PPV > prevalence) **but** net delta per ORIGINAL arm ≤ 0 because confirming-trade destruction outweighs it |
| `G4_NO_USEFUL_EDGE` | net delta per ORIGINAL arm ≤ 0 **and** interception is not strong, or no stable improvement |
| `ABORT_LINEAGE_FAILURE` | any §9 stop condition, or any gate V1–V13 fails |

Verdict is **computed** in `validate.py` from the gate table. An unrun gate is a
failure, not a pass.

### 8.2 Amendment, 2026-08-12 — recorded, not silently applied

Two defects in the labels above were found **after** the first run and are
corrected rather than overwritten, because the correction changed the answer.

1. **The branches were not mutually exclusive**, so the *ordering* decided the
   verdict rather than the evidence. G2 and G4 both matched the first run
   (delta > 0, but no stable improvement) and the `elif` chain returned G2.
2. **"Improves" was a bare point estimate.** A delta of **+0.0043 ATR/arm with a
   CI of [−0.0222, +0.0295]** — seven times wider than the estimate — is not an
   improvement. `improves` now requires the paired delta to be positive **and**
   its bootstrap CI to exclude zero, which is the standard the rest of the
   project already applies to every placebo comparison.

**The placebo is now evaluated first**, because it decides what may be
attributed to what. If the rule does not separate from the matched losing-state
control, nothing may be credited to the 5s **flip**: the confusion matrix's PPV
then describes "the trade is losing", not the regime transition. **G3 is
therefore unreachable while the placebo is unbeaten** — a property of the
question, not an oversight, and stated here so an auditor does not read it as a
dead label.

Both changes make the verdict **stricter**, and together they move this study's
answer from G2 to **G4** — against interest.

---

## 9. Stop conditions — abort rather than produce a weak result

1. Predecessor entry population does not reproduce (8,379 aligned entries of
   8,950 arms) → **ABORT**.
2. FULL-lifecycle parity (§2.1, gate V2) fails on any of the 8,950 arms →
   **ABORT**.
3. Walk-A confirming-trade MAE percentiles differ materially from
   p50 0.330 / p75 0.596 / p80 0.660 / p90 0.818 / p95 0.907 → **STOP and
   explain**. These are references, **not** permission to repair a discrepancy.
4. Any exit label outside the frozen set appears → **ABORT**.
5. A conditional exit is found whose firing flip is not the first losing adverse
   flip in the trade → **ABORT** (the repeated-flip walk is broken).

---

## 10. Audit plan

- Pre-execution: `python scripts/causal_lint.py --study studies/p90_conditional_losing_5s_exit` exits 0.
- Pre-execution: `lookahead-auditor` on §4–§5.
- Pre-execution: `contract-checker` on §8–§9.
- Completion: both re-run; `audit/status.json` shows `critical: 0`.
- Bounded re-audits: pass 2+ adjudicates all prior findings first, max 3 new
  CRITICALs, new file per pass.

---

## 11. No optimisation

Forbidden: any conditional threshold other than `current_return_atr < 0`; any
stop other than 1.00 / 0.75; 5s persistence counts; flip-count gates; time gates;
P80/P95; profit targets; trailing stops. Phases 1, 2, 9 and 10 are
**descriptive** and may not produce a rule used by any policy in this study.
