# P90 Conditional Losing-5s-Flip Failure Exit — Report

**Verdict: `G4_NO_USEFUL_EDGE`.** Computed from the gate table. 27/27 gates ·
`causal_lint` 0/0 · agent gates in `audit/status.json`.

Population: the frozen **8,950** Top-10 (P90) arms, **8,379** 5s-aligned entries,
2021–2025 RTH, NQ. 2026 sealed. Baseline = the accepted **FULL** lifecycle
(hold through confirmation → opposing flip), reproduced bit-exactly. All figures
net ATR after the accepted 2-tick round turn, on both denominators.

---

## The one-paragraph answer

**The hypothesis is correct as a description and worthless as a rule.** Losing
adverse 5s flips really are concentrated in failures — 70.6% of the adverse flips
inside eventual failures are below entry, against 15.4% inside eventual
confirmers, and the rule intercepts **90.8%** of failures saving 0.594 ATR each.
But the same test fires on 56.0% of eventual confirmers too, cutting **2,403 of
4,376** of them at −0.335 ATR when they were going on to +0.837. The two effects
cancel to three significant figures: **+2,158.30 ATR saved on failures against
−2,119.58 forfeited on good trades, a savings/sacrifice ratio of 1.018**, leaving
+0.0043 ATR per original arm with a CI of [−0.0222, +0.0295]. And it does not
separate from a matched losing-state placebo, so even that residue cannot be
credited to the 5s flip.

---

## The 16 questions, answered directly

### 1. Among eventual P90 failures, what % have a LOSING adverse 5s flip before the 1 ATR stop?

**90.0%** have one before the accepted 1.00 ATR stop; **98.4%** before the walk-A
horizon; **98.7%** at some point. Median time to the first: **39s**, at a median
return of **−0.408 ATR**.

### 2. Among eventual confirming trades, what % have the same signal before confirmation?

**42.3%** before confirmation; **56.0%** at some point. Median time **49s**, at a
median return of **−0.275 ATR**. This is the whole problem in one line: the signal
is near-universal among failures *and* present in over half the winners.

> The `pct_losing_before_1atr_stop` column reads 0.000 for the confirming cohort
> **by construction** — those trades never reached the 1.00 ATR stop, so they
> have no stop timestamp to compare against. The column is meaningful only for
> the failure cohort; it is not a finding.

### 3. PPV of "adverse 5s flip + current_return < 0" for eventual P90 failure?

| | value |
|---|---:|
| **PPV** | **0.6638** |
| prevalence (base rate of failure) | 0.4777 |
| **lift** | **+18.6pp** |
| sensitivity | 0.9138 |
| specificity | 0.5766 |
| NPV | 0.8797 |
| signal rate | 0.6577 |

TP 3,658 · FP 1,853 · TN 2,523 · FN 345. The lift is **real** — a 65.8% signal
rate that is 66.4% precise against a 47.8% base rate is genuine information. It
is simply not precise enough to act on, because acting costs the FPs their
runners. Stable by side: PPV 0.674 LONG, 0.655 SHORT.

### 4. At what median loss does the conditional exit occur?

**−0.354 ATR** at the firing flip (mean −0.353). The realised exit averages
−0.416 ATR after the fill and cost.

### 5. How much ATR does it save on eventual failures?

**+2,158.30 ATR total** across 3,633 intercepted failures — **0.594 ATR per
interception**, **+0.2412 ATR per original arm**. Mean failure improves from
**−1.038 to −0.499 ATR**. Only 8.6% of failures still reach the stop.

### 6. How much does it forfeit on eventual successful confirmations?

**−2,119.58 ATR total** across **2,403 destroyed confirmers** (54.9% of the 4,376
confirming entries), **−0.2368 ATR per original arm**. Those trades exit at a
mean −0.335 ATR having been on their way to a mean **+0.837** at confirmation.

### 7. Savings / sacrifice ratio?

**1.018.** Net +38.72 ATR over 8,950 arms. For `COND_0.75` the ratio is **0.945**
— net **−76.37 ATR**, actively worse than its own baseline.

### 8. Does COND_1.00 improve net expectancy per ORIGINAL P90 arm?

**No, not distinguishably.** −0.0805 → −0.0762, delta **+0.0043 ATR/arm**, CI
**[−0.0222, +0.0295]**. The CI is seven times wider than the estimate. Only
**2 of 5 years** are positive (2021 +0.034, 2022 −0.000, 2023 −0.008, 2024
+0.023, 2025 −0.029).

### 9. Does COND_0.75 improve it further?

**No — it makes things worse.** Delta **−0.0085 ATR/arm** against its own
baseline, CI [−0.0306, +0.0130], and MaxDD **rises** by 60.7 ATR. The two effects
that cancelled at 1.00 ATR stop cancelling when the stop is tight: the stop takes
the failures first, so the rule keeps the destruction and loses the harvest.

### 10. Once conditional 5s exits exist, does the 0.75 stop still add value?

**No.** The decomposition (`stop_interaction.csv`):

| category | n | % | Δ (0.75 − 1.00) | total ATR |
|---|---:|---:|---:|---:|
| conditional fires before either stop | 5,517 | 65.8% | 0.000 | 0.0 |
| 0.75 stops, but at 1.00 the conditional catches it | 519 | 6.2% | −0.072 | −37.3 |
| 0.75 stops and the conditional never catches it | 553 | 6.6% | **+0.221** | **+122.1** |
| 0.75 kills an eventual confirmation | 274 | 3.3% | **−0.389** | **−106.6** |

Net **−21.8 ATR**. Two-thirds of trades are already resolved by the conditional
exit before either stop is reachable, so the stop distance is irrelevant there.
The one place 0.75 genuinely helps (slow failures the rule misses, +122 ATR) is
paid back by the confirmations it kills (−107 ATR).

**Note the asymmetry that matters more:** `BASELINE_0.75` — tightening the stop
with **no** conditional rule — is the best policy in the study at −0.0677/arm and
MaxDD 694. The conditional rule's only real competitor is not the 1.00 baseline;
it is the tighter stop on its own, and it loses to it.

### 11. Does the conditional rule improve MaxDD?

At 1.00 ATR, **yes**: 801.0 → 752.1 (−48.9). At 0.75, **no**: 694.1 → 754.8
(+60.7). The drawdown improvement exists only where the baseline was loosest, and
is not available on top of the better baseline.

### 12. Is the effect stable across 2021–2025?

**No. 2 of 5 years positive**, and the sign alternates without pattern: +0.034 /
−0.000 / −0.008 / +0.023 / −0.029. The two positive years contribute essentially
the whole point estimate.

### 13. Is it directionally consistent LONG/SHORT?

**Yes** — both slightly positive, LONG +0.0017, SHORT +0.0065 per arm. No
inversion. Consistency here is not evidence of value; both are ≈0.

### 14. Do BEFORE_CONFIRM and AFTER_CONFIRM losing flips differ?

They do, and the decomposition matters more than the aggregate:

| phase | n | % | Δ vs baseline / trade | total ATR |
|---|---:|---:|---:|---:|
| `BEFORE_CONFIRM` | 5,485 | 90.9% | **+0.0044** | +24.0 |
| `AFTER_CONFIRM` | 551 | 9.1% | **+0.0268** | +14.7 |

The **after-confirmation** firings are **6× more valuable per trade** and supply
38% of the total net gain from 9% of the events. As a failed-start detector
(before) the rule is worth essentially nothing; as giveback management (after) it
is six times better — on a tenth of the sample. Under `COND_0.75` the split is
sharper still: BEFORE is **−0.0209/trade (−105.2 ATR total)** while AFTER is
**+0.0585/trade (+28.9)**. The aggregate hides a sign disagreement, which is why
the SPEC forbids combining them.

This points where the predecessor's lineage already pointed — post-confirmation
giveback, not failed starts — but the sample is small and it was not tested here.

### 15. Does it beat a matched losing-state placebo?

**No.** The placebo keeps the "is it losing?" test identical and removes only the
flip identity, drawing both the check count `k` and the check times from **pooled**
distributions (never the trade's own realised flip count or lifetime).

```text
placebo - conditional, per original arm:  -0.0046
                                     CI:  [-0.0242, +0.0145]   spans zero
```

The real rule is statistically indistinguishable from testing "is the trade
losing?" at similarly-timed observations that are not flips. And the placebo does
it with far fewer exits — **3,543 vs 6,036** firings, intercepting roughly half
the failures (47.6%) but saving **more per interception** (0.613 vs 0.594 ATR).

**Disclosure — `p_unreached` = 0.365.** 36.5% of the drawn placebo check times
(32,997 of 90,381) landed beyond the receiving trade's natural end and could
never fire. That is an unavoidable consequence of drawing length-blind: the draw
cannot consult the trade's own lifetime, so a short trade will be handed checks
it never reaches. It makes the placebo a **conservative** control — it gets
strictly fewer opportunities to fire than the real rule — which means the real
rule failing to beat it is a **stronger** negative, not a weaker one. Reported
because a control whose draws mostly fall outside the window would not be matched
at all, and that is only visible in this number.

**So the 5s flip is not the active ingredient.** What little the rule does comes
from "the trade is underwater at around this elapsed time".

### 16. G1 / G2 / G3 / G4?

**G4.** The gate table:

| criterion | required | observed |
|---|---|---|
| net delta per original arm improves | > 0 **and CI excludes zero** | **no** (+0.0043, CI [−0.0222, +0.0295]) |
| MaxDD improves | yes | yes at 1.00, **no** at 0.75 |
| years positive | ≥4/5 | **2/5** |
| no LONG/SHORT inversion | yes | yes ✓ |
| beats matched placebo | CI excludes zero | **no** |
| failure interception strong | — | **yes** (90.8%, PPV 0.664 > prevalence 0.478) |

**Why not G3.** G3 ("the 5s signal has information, the threshold is too crude")
is a claim *about the 5s flip*. The placebo says the flip is not what carries the
information, so that claim cannot be made — the PPV of 0.664 describes "the trade
is losing", not the regime transition. **G3 is unreachable while the placebo is
unbeaten**, by design, and this is stated in SPEC §8.2 rather than left for an
auditor to discover as a dead label.

**Why not G2.** G2 requires the loss-state rule to *improve economics*. It does
not: +0.0043 ATR/arm with a CI seven times wider, and 2/5 years.

---

## Disclosure — the verdict logic was corrected after the first run

**The first run returned G2.** Two defects in the frozen label definitions caused
it, both fixed and recorded in SPEC §8.2 rather than overwritten:

1. **The branches were not mutually exclusive**, so the `elif` ordering decided
   the verdict rather than the evidence — G2 and G4 both matched.
2. **"Improves" was a bare point estimate.** +0.0043 with a CI of [−0.0222,
   +0.0295] is not an improvement. It now requires the CI to exclude zero, the
   standard applied to every placebo comparison elsewhere in this project.

The placebo is now evaluated **first**, because it governs what may be attributed
to what. Both changes make the verdict stricter and moved the answer from G2 to
G4 — **against interest**. No policy, threshold, population or measurement was
touched; only the label logic.

---

## What this establishes that outlives the study

**1. The descriptive hypothesis is confirmed and it is not enough.** Phase 1
answers its own central question cleanly: of 90,437 adverse flips, **70.6% inside
eventual failures are losing** versus **15.4% inside eventual confirmers**;
median return at the flip is **−0.666** in failures against **+1.204** in
confirmers. A 46-point separation. It still does not monetise, because "is it
losing?" is also true of half the winners at some point. **Association with
failure is not the same as separation from success.**

**2. Another exact cancellation on this axis — the fourth.** Ratio 1.018 joins
`p90_marks_the_top_but_arrives_after_the_giveback` (loss containment exactly
cancelled by runner destruction) and `stop_already_collects_the_progress_edge`.
When a rule fires on two-thirds of the population, its harvest and its damage
scale together. **Signal rate is the thing to check first**: 65.8% here, 93.6%
alignment in the predecessor.

**3. The placebo family has now killed four rules.** It is the single highest-yield
control in this research programme; nothing on this axis should be believed
without it.

**4. Where the residual value actually sits.** The `AFTER_CONFIRM` firings are 6×
more valuable per trade than `BEFORE_CONFIRM`, and under the tighter stop the two
have **opposite signs**. The rule is a mediocre failed-start detector and a
better giveback manager. That is a post-confirmation question, and it is the same
place `confirmation_giveback_is_where_the_money_goes` points.

**5. The honest competitor was the simpler policy.** `BASELINE_0.75` beats every
conditional variant. A new rule should be benchmarked against the cheapest
alternative that changes the same thing, not only against the incumbent.

## Recommendation

**Stop this branch.** The specific question the brief posed is answered: no, a
losing 5s counter-regime is not usable evidence that the P90 attempt is failing —
not because it lacks information, but because the information is in the loss
state, is already priced into the outcome, and cannot be harvested without
cutting the winners that pay for everything.

If the post-confirmation `AFTER_CONFIRM` result is pursued, it should be as a
**giveback-management** study on the confirmed population with its own matched
placebo, not as more 5s-regime logic.

## Audit trail

| Gate | Result |
|---|---|
| `causal_lint` | 0 CRITICAL, 0 WARNING (8 files) |
| FULL-lifecycle parity (V2) | **exact on all 8,950 arms** — label + 4 metrics |
| validation gates V1–V13 | **28/28 pass** |
| `lookahead-auditor` pass 1 | 0 CRITICAL, 0 WARNING, 2 NOTE → **PASS** |
| `contract-checker` pass 1 | 2 CRITICAL, 1 WARNING → BLOCKED; all fixed |
| `contract-checker` pass 2 | see `audit/status.json` |

Findings that changed the code, all raised by the gates and none self-reported:

- **CRITICAL** — `trade_level_signal_coverage.csv` was missing the manifest's
  `pct_losing_before_075`. The accepted lifecycle has only a 1.00 ATR stop, so
  `walk_a_stop_ns` could not answer it; the baseline walk now records
  `adverse_075_ns` / `adverse_100_ns` path landmarks and the column is computed
  from those. **Failures: 80.8% have a losing flip before 0.75 ATR adverse;
  confirmers: 25.5%.**
- **CRITICAL** — `matched_placebo.csv` was missing `p_unreached`, which SPEC §7
  makes mandatory, and the count was never tracked. Now computed and reported
  (0.365).
- **NOTE N1** — the placebo's pooled elapsed-time draws were anchored on
  `arm_ns` while the pool itself is measured from `entry_ns`, putting the control
  ~1s off the treatment's clock. Re-anchored on `entry_ns`. The placebo delta
  moved from −0.0022 to −0.0046; the conclusion did not change.
- **Referral** — gate V10 (fires on the first losing flip) covered only
  `COND_1.00`, leaving the 0.75 walk unverified. Extended to both; gate count
  27 → 28.
- **NOTE N2, accepted not fixed** — the mark lookup requires an exact
  `path_init_ns == close_ts` match and drops a flip with no such bar rather than
  snapping to a neighbour. That is the causally safe choice and is left as-is.
- **Referral** — `tests/` had no executable coverage. Added
  `tests/test_conditional_rule.py`, **23 passing tests** on synthetic paths whose
  answers are arithmetic: the frozen threshold (including that a return of
  exactly 0 is *not* losing), long/short mirroring, the repeated-flip walk (the
  brief's ignore/ignore/exit example), causal fill timing, the adverse tie
  resolution, baseline isolation, the adverse-level landmarks, the placebo's
  unreached counting and `entry_ns` anchoring, and every branch of
  `determine_verdict` — including that a positive point estimate with a CI
  spanning zero returns G4, and that G3 is unreachable while the placebo is
  unbeaten. FULL-lifecycle parity is deliberately *not* retested there: gate V2
  already checks it on all 8,950 arms, which is stronger than any fixture.
- **Two report figures were wrong and were corrected**, both caught by the gates
  rather than self-reported: the unreached-draw count (32,981 → **32,997**, copied
  from the run before the clock fix) and three Phase-2 percentages restated from
  the coverage table.

## Other disclosures

- **2025 is not threshold-out-of-sample.** Both frozen calibration populations
  are calendar-2025 and overlap the evaluation window. Inherits
  `full_trade_path_builder/THRESHOLD_OVERLAP_WAIVER.json`.
- The 5s regime is the predecessor's artifact, imported not rebuilt, and is
  parity-tested there against a literal engine replay.
- `n=551` for `AFTER_CONFIRM` under `COND_1.00`; the 6× per-trade advantage rests
  on that sample and is reported as a pointer, not a result.
