# P90-Primed 5-Second Regime Impulse — Frozen Specification

**Study:** `p90_5s_regime_impulse` · **Frozen:** 2026-08-12, before implementation.
**Branch:** `study/p90_5s_regime_impulse`
**Substrate:** `data/canonical/regime_complete_v1/`
**Armed population:** frozen from `studies/armed_fade_score_path_progression/` — **8,950**
**Years:** 2021–2025, RTH only. **2026 remains sealed and is not read.**

---

## 0. Objective

> The P90 (Top-10) arm identifies an increasingly likely 1-minute regime reversal.
> A 5-second regime already moving in the intended fade direction may indicate the
> directional impulse has begun. Instead of waiting for the 1-minute lifecycle,
> enter while the 5s regime agrees and exit when it stops agreeing.

Does that produce a **better payoff distribution per ORIGINAL P90 ARM** — enough
successful impulses monetised, failed P90 signals made materially cheaper?

**This is a first-pass policy study.** No threshold optimisation, no model
training, no profit target, no trailing stop, no break-even, no ratchet, no
management change at the 1m confirmation. Exactly two stop distances.

---

## 1. This is NOT the prior 5s scalp study

`backtests/studies/regime_5s_scalps/` evaluated 5s flips **aligned with** the
active 1m regime, as continuation scalps inside that regime.

Here:

| | prior scalp study | this study |
|---|---|---|
| prime | none — every aligned 5s flip | the **P90 / Top-10 arm** |
| direction vs 1m regime | **with** the 1m regime | **against** it (fade) |
| 5s regime's role | the entry signal itself | causal **timing / holding** state around a rare prime |
| population | 183,827 NQ scalps | ≤ 8,950 arms |

### 1.1 Stated adverse prior, carried into the report

The prior study measured the exact exit rule proposed here — the 5s regime held
to its next opposite flip — as **gross +$0.66/trade, 45% win rate → net −$6.84**
(NQ, 183,827 scalps; ES worse). The 5s regime has **~zero standalone gross
directional edge held to flip**.

That is not dispositive: it was measured *with* the 1m regime and without a
prime. But it means **any edge found here must come from the P90 prime, not from
the 5s regime**. The report must state this prior explicitly wherever a positive
result is claimed. See memory `regime_5s_scalp_dead`.

---

## 2. Lineage — the accepted contract wins

### 2.1 P90 ≡ the frozen Top-10 arm (no discrepancy)

`studies/p80_p90_opportunity_continuation_ml/SPEC.md:76` maps `P90 → top_10` at
bullish `0.43167249785595935` / bearish `0.44559149246408103` — the same frozen
contract values in `canonical_model_threshold_contracts.parquet`. The brief's
"P90" and the accepted "Top-10 arm" are **one population**. No reconstruction.

The arm is consumed as-is: this study reads the frozen artifact
`studies/armed_fade_score_path_progression/results/armed_regime_score_paths.parquet`
(8,950 rows) directly, via `implementation/lineage.py::load_arms`. It does **not**
re-run that study's `implementation/arming.py::arm_population` builder — reading
the frozen output is what makes the population inherited rather than
reconstructed. Its contract:

```text
regime age > 600s at the arm
true in-domain Top-10 crossing FROM BELOW (a prior in-domain scored
  observation exists in the regime and is below the threshold)
direction-specific frozen threshold
first arm per regime, one arm per regime
RTH only, 2021-2025
```

### 2.2 Verified Phase 0 targets (measured, not copied from the brief)

Reproduced from the frozen artifact before this SPEC was written. Phase 0 must
reproduce every one of these **exactly** or the study aborts (§9).

| Quantity | Verified | Brief |
|---|---:|---:|
| arms | 8,950 (4,048 LONG / 4,902 SHORT) | — |
| arms per year | 1828 / 1825 / 1763 / 1771 / 1763 | — |
| P(confirm before 1 ATR stop) | **0.5202** | ≈52% |
| stopped before confirm | 0.4743 | — |
| session-close unresolved | 0.0055 | — |
| median return at confirm | **+0.8541** | +0.854 |
| median MFE through confirm | **1.0347** | 1.036 |
| median MAE through confirm | **0.3302** | 0.330 |

Confirmation timing from P90 (censored, n=4,656):
`≤60s` 1,174 · `61–120s` 1,206 · `121–300s` 1,525 · `>300s` 751.

### 2.3 The MAE distribution must be reported TWICE — this is load-bearing

The brief asks for the confirming-trade MAE distribution "for interpreting the
0.75 ATR stop". There are two populations and they answer different questions.
Reporting only one is the defect recorded in memory
`censored_population_cannot_answer_its_own_premise`.

| percentile | **censored** (confirm *before* the 1 ATR stop, n=4,656) | **uncensored** (all eventual confirms, n=8,725) |
|---|---:|---:|
| p50 | 0.3302 | 0.8831 |
| p75 | 0.5956 | 2.2125 |
| p80 | 0.6604 | 2.6679 |
| p90 | 0.8184 | 4.1414 |
| p95 | 0.9068 | 5.7166 |

- The **censored** row is bounded below 1.00 ATR **by construction** — the
  population was selected by surviving that stop. It may **only** be used for the
  conditional question "of trades that survive 1.00, what share does 0.75 kill?"
  Answer: **14.22%** have MAE ∈ (0.75, 1.00].
- The **uncensored** row is the true stop-room requirement and is the honest
  answer to "how much room do successful fades need": median 0.88, **p90 4.14,
  p95 5.72 ATR**. It reproduces memory `armed_fade_stop_room_is_the_constraint`.

Both go in `results/confirming_trade_mae.csv` with an explicit `population`
column. Any sentence about the 0.75 stop must name which one it uses.

### 2.4 Frozen values that may not change

```text
stop grid       {1.00, 0.75} ATR only. Frozen before Phase 0 percentiles were
                seen and NOT revisable after seeing them.
cost            2 ticks round-turn = 0.50 points (COST_POINTS in engine.py)
flat band       |return| < 0.125 points is flat (accepted contract)
ATR             arm_atr = atr_at_checkpoint at the P90 arm dispatch, frozen for
                the trade. Same snapshot the accepted lifecycle uses.
session         RTH 08:30-15:00 CT; forced flat at 15:00 CT of the ENTRY session
```

---

## 3. The 5-second regime — definition and disclosure

### 3.1 There was no accepted 5s regime artifact. This SPEC creates one.

The canonical store's "5s checkpoints" are **model-scoring dispatch slots**, not
a regime. No 5s regime column exists anywhere in the store. The definition frozen
here is the **same sticky rule as the 1m regime**, applied to 5s buckets:

```text
engine   collectors/collector_v2/regime_engine.py::RegimeStateEngine
         (lookahead-audited, 0 CRITICAL, used by the audited regime_5s_scalps replay)
buckets  collectors/collector_v2/aggregator.py::TimeframeAggregator, tf="5s"
input    canonical_regime_paths_all.parquet, ALL sessions (RTH+ETH), fed in
         path_event_ns order with (open, high, low, close, volume)
rule     +1 if close > EMA3_high and close > EMA9_high
         -1 if close < EMA3_low  and close < EMA9_low
         else CARRY FORWARD (sticky)
```

**Bucketing, stated precisely** (`aggregator.py:122`): `bucket_id =
path_event_ns // 5e9`, `open_ts = bucket_id * 5e9`, `close_ts = open_ts + 5e9`.
The bucket closing at `C` contains exactly the 1s bars covering `(C-5s, C]`, i.e.
`path_event_ns ∈ [C-5s, C)` ≡ `path_init_ns ∈ (C-5s, C]`. A bucket is closed
**only by the arrival of a bar in the next bucket**; the in-progress bucket is
never readable. The final partial bucket of the feed is discarded.

**Consequence — no NEUTRAL state.** The engine is sticky binary after warmup;
`0` occurs only before the first qualifying bar. The brief's "neutral /
unconfirmed" branch is therefore **vacuous** and is reported as `n=0` rather than
silently dropped. "5s no longer aligned" always means "flipped to the opposite".

**Warmup.** The engine runs continuously across ETH so the state entering each
RTH open is real, not cold. A 5-day lead-in precedes the first evaluated year.
Any arm whose 5s state is still `0` is a NON-ENTRY and is counted as such.

### 3.2 Why this is not a redefinition

The brief forbids reconstructing or redefining the **P90 arm**, which this study
consumes verbatim. The 5s regime had to be built because it did not exist. It is
built from the **existing audited engine and the store's own rows**, with the
identical rule the 1m regime uses, so no new regime concept is introduced. This
is disclosed in the report as a **new artifact of this study**, not as inherited
lineage.

### 3.3 Availability at the arm — verified, not assumed

**All 8,950 arm timestamps satisfy `arm_top10_ns mod 5s == 0`** (verified: the
unique value of `arm_top10_ns % 5_000_000_000` is `{0}`). The score-dispatch grid
and the 5s bucket grid are the same clock grid. Therefore the bucket closing
**exactly at** the arm timestamp is complete and available at the arm instant
(`close_ts <= decision_ts`, the `CompletedBarRegistry` invariant), and it is the
freshest legal state. This is a Phase 1 validation gate, not an assumption.

---

## 4. Policy

### 4.1 Direction

The intended trade is **opposite** the established 1m regime (a fade).

| 1m regime | P90 arms | required 5s state | trade | exit when |
|---|---|---|---|---|
| BULLISH | bearish fade | 5s = **BEARISH** | SHORT | 5s ≠ BEARISH |
| BEARISH | bullish fade | 5s = **BULLISH** | LONG | 5s ≠ BULLISH |

`direction` is taken from the arm row; no direction is re-derived.

### 4.2 Entry — primary rule

At the arm timestamp, read the completed 5s regime state.

- **Aligned** (5s regime == trade direction) → **candidate qualifies immediately**.
- **Not aligned** (opposite, or still `0`) → **NON-ENTRY. Do not wait.**
  Waiting for a later 5s flip is explicitly out of scope (Phase 10 measures it
  descriptively only).

### 4.3 Causal fill chain — audit-critical

```text
t0   P90 decision timestamp          arm_top10_ns  (5s clock boundary)
     5s state availability           close_ts <= t0, freshest = exactly t0
t0   entry decision                  taken on state available at t0
t0+  entry FILL                      open of the first 1s bar with
                                     path_init_ns > t0  (next executable bar)
```

`entry_price = market.open_[index_strictly_after(t0)]`. The bar filled at covers
`(t0, t0+1s]`, so its open is the price at the instant after the decision. The
position is live for that bar, so **MFE/MAE measurement starts AT the fill bar**,
not after it.

Per §2.4 of the answered brief, benchmark A (the accepted P90 lifecycle) is
**re-run on this identical fill convention** so B and C are compared
apples-to-apples. The lineage `checkpoint_reference_price` version is reported
alongside in `lineage_reconciliation.json` as the parity anchor. Neither
supersedes the other; the report names which is used for every claim.

### 4.4 Exit

Terminal event is whichever comes **first**:

| Event | Trigger | Fill |
|---|---|---|
| `STOP` | `run_mae >= stop_atr` on a completed 1s bar | open of the **next** 1s bar (trigger price is never credited) |
| `FIVE_S_EXIT` | first 5s bucket with `close_ts > t0` whose regime ≠ trade direction | open of the first 1s bar with `path_init_ns > close_ts` |
| `SESSION_CLOSE` | 15:00 CT of the entry session | close of the last RTH bar |

**Same-instant ties resolve adversely**: if the stop's fill index ≤ the 5s exit's
fill index, `STOP` wins. Every such trade sets `ambiguous = True` and both bounds
are reported.

**The 1m confirmation flip does NOT exit, does not move the stop, does not arm
anything.** It is diagnostic only. A trade may run through its own confirming
flip and through a subsequent opposing regime; only SL / 5s / session end it.

### 4.5 Variants — exactly two, plus two controls

| Name | Entry | Stop | Exit |
|---|---|---|---|
| `S1` | P90 + 5s aligned | 1.00 ATR | first non-aligned 5s |
| `S075` | P90 + 5s aligned | 0.75 ATR | first non-aligned 5s |
| `PLACEBO_EXIT` | identical entries to S1 | 1.00 ATR | **length-blind** drawn hold |
| `PLACEBO_ENTRY` | count-matched random arms | 1.00 ATR | accepted lifecycle (benchmark A) |

**`PLACEBO_EXIT` construction** (memory `early_exit_rules_need_a_matched_placebo`,
`placebo_must_be_length_blind`): the hold duration is drawn from the **pooled**
distribution of realised S1 5s-hold durations across all entered trades, seeded
`numpy.random.default_rng(20260812)`, **not** uniformly over each trade's own
realised lifetime — that would itself be look-ahead. A draw exceeding the
remaining session resolves at session close and is counted in `p_unresolved`,
which is reported alongside the resolved-only rate.

**`PLACEBO_ENTRY` construction**: 1,000 count-matched random subsamples of the
8,950 arms, each scored under benchmark A, producing a null band for confirmation
rate and expectancy. The actual 5s-aligned subset's benchmark-A statistics are
reported against that band. This separates *selection* (does alignment pick a
better population?) from *management* (does the 5s exit add value?).

### 4.6 Both denominators, everywhere — mandatory

Every economic figure is reported **per ENTERED trade** and **per ORIGINAL P90
ARM** (denominator 8,950, non-entries contributing 0.0). Memory
`immediate_top10_entry_is_optimal` and `baseline_must_include_prefilter_losers`:
a per-entered-trade figure alone flatters any selective trigger. No table may
carry only one denominator.

---

## 5. Causal contract

- **Decision timestamp:** `arm_top10_ns` (`checkpoint_decision_ns`), a 5s clock
  boundary. Available at that instant: the arm's own score/ATR/price, and every
  5s bucket with `close_ts <= t0`.
- **Snap rule:** 5s regime state uses `close_ts <= decision_ts`
  (`CompletedBarRegistry.audit_provenance`). Path bars use `path_init_ns` as the
  availability clock (`= path_event_ns + 1s`, verified single-valued).
- **Regime/session mapping, stated separately:** the 5s regime is bucketed on
  `path_event_ns` (bar OPEN) per `aggregator.py:122`; the *availability* of a
  bucket is its `close_ts`. These are different clocks and are never conflated
  (memory `center_feature_dual_implementation`).
- **Label horizon / censoring:** trades end at SL / 5s exit / 15:00 CT of the
  entry session. Trades open at the session close are `SESSION_CLOSE`, retained,
  and reported with an explicit unresolved rate — never dropped.
- **Load-bearing checklist rules** (`docs/CAUSAL_CHECKLIST.md`): **A** (decision
  timestamps), **B** (feature snap), **C1–C3** (fill feasibility, next-bar fills,
  no trigger-price credit), **F** (session gating on the availability clock, not
  `ts_event`), **G** (label horizon / censoring), **H4** (no trigger-price fills).

### 5.1 The ten audit items from the brief, mapped

| # | Item | Where enforced |
|---|---|---|
| 1 | P90 arm uses only causally available model state | consumed verbatim from the accepted arm artifact; not rebuilt |
| 2 | 5s regime completed and available before entry | §3.3 grid proof + registry invariant; Phase 1 gate V4 |
| 3 | Entry cannot fill before the qualifying 5s state exists | §4.3 fill chain; gate V5 |
| 4 | 5s exit cannot fill on a price preceding the flip's knowledge | §4.4 fill = open of bar after `close_ts`; gate V6 |
| 5 | 1m confirmation is diagnostic only | no confirmation term in the simulator's exit set; gate V7 asserts exits ∈ {STOP, FIVE_S_EXIT, SESSION_CLOSE} |
| 6 | ATR frozen causally at the arm snapshot | `arm_atr` from the arm row, never recomputed |
| 7 | SL / 5s same-instant ordering adverse | §4.4 tie rule; `ambiguous` flag; both bounds reported |
| 8 | Non-entered arms stay in the denominator | §4.6; gate V8 asserts per-arm denominator == 8,950 |
| 9 | No future confirmation label influences entry eligibility | entry depends only on `arm_top10_ns` and the 5s state; gate V9 |
| 10 | 2026 sealed | year filter 2021–2025; gate V10 asserts no row with `entry_year >= 2026` |

---

## 6. Deliverables Manifest  <!-- frozen before implementation -->

| # | Path | Type | Required contents |
|---|---|---|---|
| 1 | `results/lineage_reconciliation.json` | json | arms, by side, by year; confirm/stop/session rates; return & MFE & MAE at confirm (mean, median); benchmark A under BOTH fill conventions; every §2.2 target with `expected`/`observed`/`match` |
| 2 | `results/confirming_trade_mae.csv` | table | `population` ∈ {censored, uncensored} × `side` ∈ {ALL,LONG,SHORT} × cols `n, mean, p50, p75, p80, p90, p95`, plus `pct_mae_gt_075` |
| 3 | `results/confirmation_timing.csv` | table | `bucket` ∈ {≤60,61–120,121–300,>300} × `population` × `n, pct, median_return_atr, median_mfe_atr` |
| 4 | `results/p90_5s_alignment.csv` | table | `group` (ALL/LONG/SHORT/year/session) × `n_arms, n_aligned, pct_aligned, n_opposite, pct_opposite, n_uninit, pct_uninit` |
| 5 | `results/five_second_geometry.csv` | table | per entered trade: `regime_id, side, entry_year, age_5s_at_arm_s, age_5s_at_entry_s, secs_since_5s_flip, secs_to_next_nonaligned, mfe_atr, mae_atr, realized_atr, arm_offset_bucket` |
| 6 | `results/trades_s1.parquet` | table | one row per entered trade: `regime_id, side, direction, entry_year, arm_ns, entry_ns, entry_price, exit_ns, exit_price, atr, outcome, gross_atr, net_atr, mfe_atr, mae_atr, hold_s, ambiguous, confirm_ns, confirmed_before_exit, walk_a_terminal_label` |
| 7 | `results/trades_s075.parquet` | table | identical columns to #6 |
| 8 | `results/policy_comparison.csv` | table | `policy` ∈ {A_LIFECYCLE, S1, S075, PLACEBO_EXIT, PLACEBO_ENTRY} × `n_arms, n_entries, entry_coverage, n_stop, n_5s_exit, n_session, win_rate, mean_atr, median_atr, mean_winner, median_winner, mean_loser, median_loser, profit_factor, gross_atr_total, net_atr_total, exp_per_entry_gross, exp_per_entry_net, max_dd_atr` |
| 9 | `results/per_original_arm.csv` | table | same policies × `n_original_arms (=8950), exp_per_arm_gross, exp_per_arm_net, total_net_atr, atr_per_100_arms, ci_low, ci_high` |
| 10 | `results/exit_vs_confirmation.csv` | table | `policy` × `class` ∈ {5S_EXIT_BEFORE_1M_CONFIRM, 1M_CONFIRM_BEFORE_5S_EXIT, STOP_BEFORE_1M_CONFIRM, STOP_AFTER_1M_CONFIRM, SESSION_OTHER} × `n, pct, mean_net_atr, median_net_atr` |
| 11 | `results/confirmation_capture.csv` | table | for confirm-before-exit trades: `policy, n, return_at_confirm, mfe_at_confirm, return_at_5s_exit, mfe_at_5s_exit, incremental_atr (median, mean, CI), capture_vs_confirm_return, capture_vs_confirm_mfe, n_zero_denominator` |
| 12 | `results/failure_cost.csv` | table | non-confirming arms: `policy, pct_never_entered, n_entered, mean_loss, median_loss, p75_adverse, p90_adverse, pct_exited_before_075_adverse, pct_exited_before_100_adverse, net_atr_per_arm`, vs accepted failure cost |
| 13 | `results/successful_trade_preservation.csv` | table | eventually-confirming arms: `policy, pct_qualifying, pct_stopped_before_confirm, pct_5s_exit_before_confirm, pct_open_at_confirm` × per-category `eventual_return, eventual_mfe`; plus `n_killed_by_075_surviving_100`, `pct_killed_by_075_surviving_100` |
| 14 | `results/stop_comparison.csv` | table | `d_exp_per_entry, d_exp_per_arm, d_max_dd, n_losses_avoided, atr_saved_on_failures, n_winners_destroyed, atr_forfeited_on_successes, n_confirm_trades_destroyed, net_tradeoff_atr` |
| 15 | `results/nonentry_future_alignment.csv` | table | `bucket` ∈ {≤15,16–30,31–60,61–120,>120,never} × `n, pct, pct_before_confirm, pct_before_1atr_stop, pct_before_invalidation`, plus eventual confirmation rate |
| 16 | `results/five_second_age_diagnostic.csv` | table | `age_bucket` (5s regime age at arm) × `n, pct, win_rate, mean_net_atr, median_net_atr, mean_mfe, mean_mae` for S1 and S075 |
| 17 | `results/by_year.csv` | table | `policy × entry_year × n_arms, n_entries, exp_per_entry_net, exp_per_arm_net, win_rate, max_dd_atr` |
| 18 | `results/by_side.csv` | table | `policy × side ×` same columns as #17 |
| 19 | `results/validation_report.json` | json | every gate V1–V14 with `expected`, `observed`, `pass` |
| 20 | `results/summary.json` | json | verdict ∈ {F1,F2,F3,F4}, headline numbers, the 15 report answers keyed `q1`–`q15` |
| 21 | `results/partition_manifest.json` | json | input file paths + sizes + row counts, code hash, 5s regime build counts, seeds, frozen constants |
| 22 | `SPEC.md` / `README.md` / `REPORT.md` | docs | this contract; how to run; the answered questions |
| 23 | `audit/status.json` | json | machine-readable audit verdict, `critical: 0` required |

`results/regime_5s_flips.parquet` (the built 5s regime timeline) is a **generated
data artifact**: written under `_work/`, listed in the manifest with its row
count and hash, and **not committed**.

### 6.1 Terminal decision labels

Every label is reachable through the real workflow.

| Label | Condition |
|---|---|
| `F1_STRONG_5S_IMPULSE_EDGE` | net `exp_per_arm` > accepted benchmark A **and** > 0 after cost, **and** the S1−PLACEBO_EXIT difference CI excludes zero, **and** ≥4/5 years positive, **and** no LONG/SHORT sign inversion, **and** failure-cohort net loss materially reduced vs accepted |
| `F2_PROMISING_ENTRY_TIMING_NEEDS_WORK` | the aligned population beats the `PLACEBO_ENTRY` band on benchmark A (selection is real) but the realised 5s-managed expectancy does not beat benchmark A, **and** Phase 10 shows a fresh aligned 5s state commonly appears before confirmation |
| `F3_5S_USEFUL_ONLY_AS_LOSS_CONTROL` | failure-cohort net loss materially reduced **and** confirming-trade destruction bounded, but no upside-capture improvement and `exp_per_arm` not improved |
| `F4_NO_USEFUL_5S_EDGE` | `exp_per_arm` not improved over benchmark A, **or** S1 does not separate from `PLACEBO_EXIT`, **or** the 5s exit chops eventual confirmers without a compensating failure saving |
| `ABORT_LINEAGE_FAILURE` | any §2.2 target fails to reproduce, or any V-gate fails |

Verdict is **computed** in `validate.py` from the gate table, never asserted in
prose. An unrun gate is a failure, not a pass.

---

## 7. Domain & completeness contract

- **Partition grid:** 5 years × 2 sides = 10 cells, all required non-empty.
  Expected arm counts per §2.2 exactly.
- **5s regime grid:** one bucket per 5s clock slot covered by the path feed.
  Expected bucket count = number of distinct `path_event_ns // 5e9` values in
  `canonical_regime_paths_all.parquet`, computed and reconciled, not assumed.
  The final partial bucket is discarded by contract (`aggregator.py:83`) and that
  discard is counted and reported.
- **Boundary convention:** RTH `[08:30, 15:00)` CT, half-open, on the
  availability clock (`path_init_ns`), never `path_event_ns`. Day boundary via
  `America/Chicago`.
- **Zero-row partition:** retained with a flag and surfaced in
  `validation_report.json`; never silently dropped.
- **Missing state:** an arm whose 5s regime is `0` (uninitialised) is retained as
  an explicit NON-ENTRY category with its own count. Never imputed.
- **Global validation before finalisation:** `n_entered + n_nonentry == 8950`
  for every variant; the union of terminal labels covers every entered trade with
  no `OPEN`; `PLACEBO_ENTRY` draws all have exactly `n_entered` members.

---

## 8. Stop conditions — abort rather than produce a weak result

1. Any §2.2 lineage target fails to reproduce exactly → **ABORT**, report the
   discrepancy, change nothing.
2. The 5s bucket grid fails to reconcile against the independently counted 1s
   path rows → **ABORT**.
3. Any arm timestamp is found off the 5s clock grid → **ABORT** (the availability
   argument in §3.3 would no longer hold).
4. Entry coverage < 2% of arms → the study cannot answer its own question;
   report coverage and stop before Phase 3.
5. Any exit label outside {STOP, FIVE_S_EXIT, SESSION_CLOSE} appears → **ABORT**
   (a confirmation term leaked into management).

---

## 9. Audit plan

- **Pre-execution:** `python scripts/causal_lint.py --study studies/p90_5s_regime_impulse` must exit 0.
- **Pre-execution:** `lookahead-auditor` on §5 (the causal contract and the fill chain).
- **Pre-execution:** `contract-checker` on §6–§7.
- **Completion:** both agents re-run; `audit/status.json` must show `critical: 0`.
- Bounded re-audits: pass 2+ adjudicates all prior findings before raising new
  ones, max 3 new CRITICALs per pass, new file per pass (`audit/pass_NN.md`).

---

## 10. No optimisation — explicit prohibitions

No retrospective tuning of: stop distance (only 1.00 / 0.75), the 5s regime
definition, the P90 threshold, regime age, 5s regime age, confirmation horizon,
profit target, trailing rule. Phases 2, 10 and 11 are **descriptive only** and
may not produce a filter used by S1 or S075. If a Phase 11 age bucket looks
attractive, that is a finding for a *future* study, stated as such.
