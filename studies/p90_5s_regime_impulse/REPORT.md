# P90-Primed 5-Second Regime Impulse — Report

**Verdict: `F4_NO_USEFUL_5S_EDGE`.** Computed from the gate table, not asserted.
26/26 validation gates pass · `causal_lint` 0 CRITICAL / 0 WARNING · agent gates
in `audit/status.json`.

Population: the frozen **8,950** Top-10 (P90) arms, 2021–2025 RTH, NQ. 2026 sealed
and never read. Every figure below is net ATR after the accepted 2-tick round
turn unless labelled gross, and is carried on **both** denominators.

---

## The one-paragraph answer

The 5s regime is not a timing state around the P90 prime — **it is very nearly
the prime itself.** 93.6% of P90 arms already have the 5s regime moving in the
fade direction, against a 47.7% base rate at comparable checkpoints, so the
alignment filter removes almost nothing and selects nothing. And because the
sticky 5s regime flips back after a **median 50 seconds** while the median
confirmation takes **116 seconds**, exiting on the first non-aligned 5s bucket
cuts 75.6% of trades before the thesis ever resolves. It does make failed P90
signals dramatically cheaper — −0.363 vs −1.052 ATR per failure arm — but a
length-blind random hold achieves −0.377, i.e. essentially the same saving, and
the whole S1-minus-placebo difference is −0.0045 ATR/arm with a CI spanning zero.
The saving comes from *leaving early at all*, not from the 5s regime.

---

## The 15 questions, answered directly

### 1. What percentage of P90 arms already have the 5s regime aligned?

**93.6%** (8,379 of 8,950). Zero uninitialised. Remarkably stable: 93.0–94.2%
across the five years, 93.5% LONG vs 93.7% SHORT.

For context this study measured but the brief did not ask for: across **all
2,439,534** RTH scoring checkpoints in regimes older than 600s, 2021–2025, the 5s
regime is counter to the 1m regime **47.65%** of the time — 48.1 / 48.0 / 47.7 /
47.5 / 47.0% by year (`results/five_second_base_rate.json`).

**So the P90 score fires almost exclusively once the fast regime has already
turned: 93.6% against a 47.7% base rate, a 46-point selection effect, stable to
within one point in every year.** That is a real structural finding about what
the fade model keys on, and it is the reason every downstream result is what it
is — an entry filter that keeps 93.6% of its population is not a filter.

### 2. Verified p50/p75/p80/p90/p95 entry→confirmation MAE among successful P90 trades?

**Two populations, because they answer different questions.** Reporting only one
is the defect in `censored_population_cannot_answer_its_own_premise`.

| percentile | **censored** (confirm before the 1 ATR stop, n=4,656) | **uncensored** (all eventual confirms, n=8,725) |
|---|---:|---:|
| p50 | 0.3302 | 0.8831 |
| p75 | 0.5956 | 2.2125 |
| p80 | 0.6604 | 2.6679 |
| p90 | 0.8184 | 4.1414 |
| p95 | 0.9068 | 5.7166 |

The censored row is bounded below 1.00 ATR **by construction** — that population
was selected by surviving the stop. It legitimately answers "of trades that
survive 1.00, what share does 0.75 kill?" (**14.22%** have MAE ∈ (0.75, 1.00]),
and nothing else. The uncensored row is the honest stop-room requirement and
reproduces `armed_fade_stop_room_is_the_constraint` exactly: **p90 4.14, p95 5.72
ATR**. Successful fades routinely need four to six ATR of room.

### 3. How many eventual confirmers would 0.75 eliminate that survive 1.00?

**54 trades, 1.23%** of the entered confirming population, forfeiting 5.71 ATR in
total. Far below the 14.22% the censored MAE distribution implies, and the reason
is question 10's answer: at a 50-second median hold, most trades are already out
before price travels 0.75 ATR either way.

### 4. Expectancy of the 5s policy?

| policy | net / entered | net / **original arm** | gross / original arm |
|---|---:|---:|---:|
| A — accepted lifecycle | −0.0518 | −0.0516 | **+0.0057** |
| **S1** (1.00 ATR) | −0.0746 | **−0.0698** [−0.0831, −0.0571] | −0.0161 |
| **S075** (0.75 ATR) | −0.0735 | **−0.0688** [−0.0818, −0.0561] | −0.0151 |
| PLACEBO_EXIT | −0.0698 | −0.0654 | −0.0116 |
| PLACEBO_ENTRY (count-matched band) | — | −0.0481 [−0.0534, −0.0431] | — |

Both variants are **negative gross**, so this is not a cost problem, and both are
worse than the accepted lifecycle on both denominators. Note the accepted
lifecycle itself is only ≈ breakeven gross (+0.006) and negative net — 52% × +0.854
against 47% × −1.00 nets to roughly nothing. The bar was low and the policy did
not clear it.

### 5. How much of the known P90→confirmation move does it capture?

Among the 1,934 trades still open when confirmation arrived: median return at
confirmation **+0.765**, median realised at the eventual 5s exit **+0.633**.
Capture **0.759 of the confirmation return** and **0.604 of the confirmation
MFE**. But that is capture on the 23% of entries that got there — measured per
original arm the contribution is negative.

### 6. Does the 5s exit usually occur before or after 1m confirmation?

**Overwhelmingly before.**

| class | n | % of entries | mean net ATR |
|---|---:|---:|---:|
| 5S_EXIT_BEFORE_1M_CONFIRM | 6,335 | **75.6%** | **−0.309** |
| 1M_CONFIRM_BEFORE_5S_EXIT | 1,953 | 23.3% | **+0.722** |
| STOP_BEFORE_1M_CONFIRM | 69 | 0.8% | −1.143 |
| STOP_AFTER_1M_CONFIRM | 3 | 0.04% | −0.948 |
| SESSION / other | 19 | 0.2% | +0.276 |

This is the entire result in one table. Three quarters of trades are cut at −0.31
before the thesis resolves; the quarter that survives earns +0.72. The arithmetic
does not close.

### 7. When confirmation comes first, does continuing to the 5s flip add or subtract?

**Neither, reliably.** Median incremental return from holding past confirmation to
the eventual 5s flip is slightly negative, CI **[−0.0069, +0.0065] — spans zero**
(S075: [−0.0064, +0.0033], also spans zero). Holding through confirmation is a
coin flip. Worth noting the contrast: the same measurement on PLACEBO_EXIT gives a
CI that *does* exclude zero on the negative side, so the 5s flip is marginally
better than a random exit at this one sub-question — and it is the only place in
the study where that is true.

### 8. What happens to P90 signals that never confirm?

This is where the policy genuinely works. On the 4,294 arms the accepted lifecycle
could not monetise:

| | accepted lifecycle | S1 | S075 | PLACEBO_EXIT |
|---|---:|---:|---:|---:|
| net ATR per failure arm | **−1.052** | **−0.363** | −0.359 | **−0.377** |
| % exited before 0.75 ATR adverse | — | 90.5% | 90.5% | 64.9% |
| % exited before 1.00 ATR adverse | — | 98.3% | 99.5% | 77.8% |

**The failure cost falls by 0.69 ATR per failure arm — a 65% reduction.** 6.8% of
failure arms are never entered at all.

**But the placebo gets −0.377.** The 5s exit contains adverse excursion far better
(90.5% vs 64.9% under 0.75 ATR) and still ends up economically level with a random
hold, because tighter containment on the losers costs proportionally on the
winners inside the same cohort. The saving is a property of leaving early, not of
the 5s regime.

### 9. Does 5s management turn ~1 ATR failures into smaller losses?

Yes, mechanically: mean loss on entered failure arms is **−0.389** (S1) against an
accepted **−1.052**, and 98.3% are out before 1.00 ATR adverse. It does exactly
what the brief hoped. It just does not pay, because question 6's 75.6% cohort
includes most of the eventual winners too.

### 10. Does 0.75 improve economics or just reduce DD while killing good trades?

**Neither — it is very nearly inert.** Difference in expectancy per arm
**+0.0010 ATR** in favour of 0.75; max drawdown falls 8.7 ATR (630.4 → 621.7);
54 confirming trades destroyed forfeiting 5.71 ATR against 8.96 ATR total saved.

The reason is structural: under S1 only **72 of 8,379 trades (0.9%)** exit on the
stop at all — the 5s flip gets there first 98.9% of the time. Under S075 it is 439
(5.2%). At a 50-second median hold the stop is nearly unreachable, so its distance
barely matters. **The stop grid is not the interesting axis in this policy, and
would not have been at any distance.**

### 11. Are results stable by year?

**Yes — uniformly negative. 0 of 5 years positive** for S1, S075 and the placebo.

| year | S1 | S075 | PLACEBO_EXIT |
|---|---:|---:|---:|
| 2021 | −0.0894 | −0.0895 | −0.0755 |
| 2022 | −0.0474 | −0.0474 | −0.0482 |
| 2023 | −0.0695 | −0.0687 | −0.0708 |
| 2024 | −0.0753 | −0.0736 | −0.0961 |
| 2025 | −0.0676 | −0.0650 | −0.0364 |

Net ATR per original arm. This is the rare case where stability strengthens the
negative rather than a positive.

### 12. Are LONG and SHORT consistent?

**Yes, no inversion.** S1: LONG −0.0722, SHORT −0.0679 per arm; win rates 31.8%
and 30.3%. The two sides agree closely, which rules out the result being one
side's pathology.

### 13. For non-aligned arms, does a fresh aligned 5s regime appear soon after?

**Always, and fast.** Of the 571 non-aligned arms, **0 never align**; 31.7% align
within 15s, 18.2% within 16–30s, 25.6% within 31–60s. **100% of them align before
the 1m confirmation** — but only ~41% before the 1 ATR stop.

Eventual confirmation rate by latency: 54.1% (≤15s), 60.6% (16–30s), 53.4%
(31–60s), 37.6% (61–120s), 12.8% (>120s). The fast bucket does sit above the
52.0% base rate — but on n=181, and against a per-arm expectancy that is negative
everywhere else in this study. This is descriptive only and was not traded.

### 14. F1 / F2 / F3 / F4?

**F4.** The gate table:

| criterion | required | observed |
|---|---|---|
| beats benchmark A per arm | yes | **no** (−0.0688 vs −0.0516) |
| positive after cost | yes | **no** (negative even gross) |
| separates from PLACEBO_EXIT | CI excludes 0 | **no** ([−0.0159, +0.0078]) |
| years positive | ≥4/5 | **0/5** |
| no LONG/SHORT inversion | yes | yes ✓ |
| failure cost materially cheaper | yes | yes ✓ (−1.052 → −0.363) |
| confirmer preservation | <50% cut pre-confirm | **no — 55.8% cut** |

**F3 was the live alternative and it fails on its own second clause.** F3 requires
the failure saving *without destroying too many eventual confirming trades*. The
saving is real, but **55.8% of eventual confirmers are cut by the 5s flip before
they ever confirm**, at −0.195 ATR each, on trades that would have reached +0.982
return and +1.168 MFE. You cannot keep the loss control and discard that.

**F2 is ruled out by direct measurement, not by inference.** F2 requires that
already-aligned entry looks late or choppy. Phase 11 says it does not: median net
ATR is flat at −0.238 / −0.231 / −0.257 / −0.267 / −0.254 across the
exactly-on-flip / 1–5s / 6–15s / 16–30s / >30s age buckets, with a ~50s median
hold in every one. **Entering exactly on the fresh 5s flip performs the same as
entering 30+ seconds late.** Timing is not the defect. And PLACEBO_ENTRY confirms
there is nothing to select: the aligned subset's benchmark-A expectancy is
−0.0503, inside the count-matched random band [−0.0534, −0.0431], and its
confirmation rate 0.5223 is inside [0.5175, 0.5229].

### 15. Next study: fresh-5s-flip entry, 5s early-failure exit, or abandonment?

**Abandon the branch.** Not one of the three, because the study rules out the
first two on measurement rather than leaving them open:

- **Fresh-5s-flip entry is dead on arrival.** It is the F2 hypothesis, and Phase
  11 shows fresh entries perform identically to stale ones. It would also apply
  to the 6.4% of arms that are not already aligned — 571 trades — against a
  population where the aligned 93.6% loses money.
- **5s-as-early-failure-exit is dead on the placebo.** It is the F3 hypothesis,
  and the failure saving does not separate from a length-blind random hold
  (−0.363 vs −0.377), while costing 55.8% of the eventual confirmers.

---

## What this study establishes that outlives it

**1. The P90 score is largely a restatement of "the fast regime has already
turned."** 93.6% vs a 47.7% base rate. Any future work that treats a fast-regime
state as *independent confirmation* of the fade model is double-counting one
piece of evidence. This is new and was not previously measured.

**2. The exit-speed mismatch is quantitative and general.** Median 5s hold 50s;
median censored confirmation 116s. Any exit keyed to a state that mean-reverts
faster than the thesis resolves will cut most trades pre-resolution regardless of
how good the state is. That is the same shape as
`giveback_is_the_wrong_axis_progress_is` and `p90_marks_the_top_but_arrives_after_the_giveback`,
reached from a third direction.

**3. The placebo earned its place again — third time on this axis.** Read without
a control, this study's failure-cost table is a headline: a 65% reduction in the
cost of failed signals, from −1.052 to −0.363 ATR. The length-blind random hold
gets −0.377. Without `PLACEBO_EXIT` the honest read would have been F3 and a
follow-up study would have been commissioned.

**4. The stop grid was the wrong axis and the data says so structurally.** 0.9%
of S1 trades ever reach their stop. Any stop distance study on a 50-second policy
measures almost nothing.

## Adverse prior, as required by SPEC 1.1

`backtests/studies/regime_5s_scalps/` measured the 5s regime held to its next
opposite flip at **gross +$0.66/trade, 45% win rate → net −$6.84** over 183,827 NQ
scalps (ES worse), concluding the 5s regime has ~zero standalone gross directional
edge. That was *with* the 1m regime and without a prime, so it was not
dispositive going in. It is now corroborated from the opposite direction: adding a
rare, high-quality, counter-trend prime does not rescue the 5s hold-to-flip.

## Disclosures

- **The 5s regime is an artifact of this study**, not inherited lineage. None
  existed. It uses the same sticky EMA3/EMA9 rule as the 1m regime, built from the
  store's own 1s rows, proven bit-equal to a literal `TimeframeAggregator` +
  `RegimeStateEngine` replay in `tests/`. A different 5s definition could give
  different numbers; the *mechanism* (a state that mean-reverts in 50s cannot
  hold a 116s thesis) would not change.
- **2025 is not threshold-out-of-sample.** Both frozen calibration populations are
  calendar-2025 and overlap the evaluation window. Inherits
  `full_trade_path_builder/THRESHOLD_OVERLAP_WAIVER.json`.
- **Benchmark A is restated on the study's own next-1s-open fill** so B and C are
  compared like for like; the lineage `checkpoint_reference_price` version is in
  `results/lineage_reconciliation.json` as the parity anchor. The two differ by
  0.004 ATR/arm, so no conclusion depends on the choice.
- **22 of 8,950 arms have no reachable fill bar** inside their own session. They
  are retained as non-entries contributing 0.0 and never removed from the
  denominator.
- Max drawdown figures are large (≈620–630 ATR) simply because a negative-edge
  policy accumulates monotonically over 8,379 trades; they are not a risk finding.
- **The 5s build discards the final partial bucket**, matching the real
  aggregator, which closes a bucket only when a bar in the next bucket arrives.
  `lookahead-auditor` pass 1 caught that the build kept it while asserting
  otherwise; the flag is now computed rather than hardcoded. The discarded bucket
  held 1 row, lay outside RTH, and was not a regime change — the flip count is
  unchanged at 2,054,398 and no result moved.

## Audit trail

| Gate | Result |
|---|---|
| `causal_lint` | 0 CRITICAL, 0 WARNING (10 files) |
| `tests/test_regime_5s_parity.py` | 7/7 — vectorised build bit-equal to a literal engine replay |
| `lookahead-auditor` pass 1 | 0 CRITICAL, 0 WARNING, 1 NOTE → PASS |
| `lookahead-auditor` pass 2 | re-run after the NOTE was remediated; see `audit/pass_02.md` |
| `contract-checker` pass 1 | 2 CRITICAL, 3 WARNING → BLOCKED, all 5 fixed |
| `contract-checker` pass 2 | all 5 confirmed fixed, 0 new CRITICAL → **CLEAR** |
| validation gates V1–V14 | **26/26 pass** |

Machine-readable verdicts in `audit/status.json`; per-pass reports in
`audit/pass_NN.md` and `audit/contract_pass_NN.md`.
