# Confirmation Economics + Post-Confirmation Excursion Map — Report

**Study:** `confirmation_economics_excursion_map` · 2026-08-10
**Substrate:** `data/canonical/regime_complete_v1/`
**Populations:** 8,988 / 7,396 / 5,823 / 3,415 (Top-10/5/2.5/1) + 8,950 armed
**Panel:** 49,345 per-(trade, path-mode) rows · all 11 validation gates pass

---

## Executive summary

**The money is not being lost at entry. It is being given back after the trade is
already right.** The median confirmed trade at Top-2.5 reaches **+2.59 ATR of MFE
and exits at +0.36** — a capture ratio of **0.138**. That is the finding.

Answering the eleven executive questions directly:

**1. At confirmation close, how profitable is the typical surviving trade?**
+0.477 ATR median at Top-2.5; +0.854 at Top-10. 90.2% are positive at Top-2.5,
99.0% at Top-10.

**2. How much MFE has already occurred by confirmation?**
+0.652 ATR median (Top-2.5), +1.036 (Top-10).

**3. How much pre-confirm MFE is already given back at confirmation?**
Very little — **median 0.150 ATR**, p90 0.393. Confirmation arrives near the
high-water mark. The giveback problem is entirely *after* confirmation.

**4. How profitable are eventual winners vs eventual losers AT confirmation?**
**Barely distinguishable.** Flip-exit winners +0.607, flip-exit losers +0.517,
later-stopped +0.284. **59.6% of confirmed trades are profitable at confirmation
and still end in a loss.**

**5. How much post-confirm retracement do ≥2 / ≥2.5 / ≥3 ATR runners require?**
Modest. Before first reaching their threshold, median **0.43 / 0.46 / 0.48 ATR**
from the confirmation close (armed); p75 0.82–0.87, p90 1.26–1.32.

**6. Is there a deterioration level that catches losers without killing runners?**
**Yes, and the separation is wide.** At 0.75 ATR below the confirmation close,
**94.3% of eventual losers** touch it while only **31.4% of ≥2.5 ATR runners**
ever needed that much room to develop — a 63-point gap.

**7. Does the risk budget depend on profit already owned at confirmation?**
**No — and this is a genuine surprise.** The retracement *requirement* is
essentially flat across profit buckets (median 1.14→1.31 ATR, p90 1.99→2.45).
What changes enormously is the *probability of success*: P(stop) falls 0.643 → 0.124
and P(≥2.5 ATR) rises 0.240 → 0.586 from the `<0` bucket to the `≥1.0` bucket.
Profit at confirmation should drive **selection**, not **stop width**.

**8. Once at +1 / +1.5 / +2 / +2.5 ATR, how much room to the next landmark?**
**A near-memoryless ladder.** Transition probability is ~0.79 at *every* rung
(0.788 / 0.777 / 0.790 / 0.798), and successful transitions need a median
**~0.6 ATR** of giveback at every rung (0.591 / 0.627 / 0.634 / 0.617), p90
~1.5–1.7. **Management should not tighten as the runner matures** — the geometry
does not change.

**9. What percentage of maximum MFE does the current regime-flip exit capture?**
**13.8% median, 6.7% mean** (Top-2.5). Median absolute giveback **2.03 ATR** per
flip-exit trade. Winners capture 38.1%; losers capture −28.8%.

**10. How much expectancy could improving capture theoretically gain?**
The recoverable pool is **+0.89 ATR per entry** (5,183 ATR over 5,823 entries).
Against that, +0.05 / +0.10 / +0.15 / +0.25 ATR per trade require capturing only
**5.6% / 11.2% / 16.9% / 28.1%** of currently-given-back MFE.

**11. Is the primary opportunity (A) preventing confirmed losers, (B) improving
runner exits, (C) both, or (D) neither?**
**C — both, with (B) larger.** The loser problem is 59.6% of confirmed trades
worth ~0.3–0.5 ATR each at their peak; the runner-exit problem is 2.03 ATR of
median giveback across 40.7% of all entries.

---

## 1. Phase 0 — contract and population parity

All four base counts reproduce the accepted `regime_lifecycle_600s` figures
**exactly** (validation gate 1):

| Level | Required | Observed |
|---|---:|---:|
| top_10 | 8,988 | **8,988** |
| top_5 | 7,396 | **7,396** |
| top_2_5 | 5,823 | **5,823** |
| top_1 | 3,415 | **3,415** |
| armed | 8,950 | **8,950** |

Confirmed counts bracket the accepted survival figures exactly, with the gap
equal to the same-bar ambiguous-tie count — this study resolves a stop/confirm
tie adversely where the accepted lifecycle resolved it optimistically.

---

## 2. Phase 1 — confirmation economics

Constrained mode. At the confirming flip **bar close**, in ATR frozen at entry.

| Population | entries | confirmed | rate | return med | MFE med | MAE med | giveback med | %pos | %≥0.50 | %≥1.00 | %<0 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| top_10 | 8,988 | 4,678 | 0.520 | **+0.854** | 1.036 | 0.330 | 0.150 | 99.0 | 82.4 | 36.9 | 0.8 |
| top_5 | 7,396 | 4,362 | 0.590 | +0.656 | 0.834 | 0.280 | 0.150 | 96.4 | 64.5 | 23.7 | 2.8 |
| **top_2_5** | 5,823 | 3,774 | 0.648 | **+0.477** | 0.652 | 0.237 | 0.150 | 90.2 | 47.6 | 14.8 | 8.0 |
| top_1 | 3,415 | 2,496 | 0.731 | +0.296 | 0.486 | 0.201 | 0.155 | 80.9 | 32.6 | 8.2 | 16.6 |
| armed | 8,950 | 4,656 | +0.854 | 0.520 | 1.035 | 0.330 | 0.150 | 99.0 | 82.3 | 36.9 | 0.8 |

Top-2.5 return-at-confirmation quantiles: p10 +0.017 · p25 +0.199 · p50 +0.477 ·
p75 +0.786 · p90 +1.133 · p95 +1.347.

**A clean inversion runs through the threshold ladder.** Deeper thresholds
confirm more often but own *less* when they do: Top-10 confirms 52.0% of the time
holding +0.854 ATR; Top-1 confirms 73.1% holding +0.296. This is the same
trade-off `armed_fade_score_path_progression` found — waiting for conviction
means entering later in the move — arriving here from a completely different
measurement.

**Giveback at confirmation is negligible** (median 0.150 ATR at every threshold).
The predicted flip arrives essentially at the local high-water mark. Whatever is
wrong with this strategy is not happening before confirmation.

---

## 3. Phase 2 — the same trade, split by how it ended

Top-2.5, 3,774 confirmed trades.

| Terminal outcome | n | % | return at confirm | MFE at confirm | giveback | secs to confirm | eventual MFE |
|---|---:|---:|---:|---:|---:|---:|---:|
| CONFIRMED_THEN_STOPPED | 1,305 | 34.6 | **+0.284** | 0.460 | 0.156 | 40 | 0.780 |
| FINAL_FLIP_EXIT_LOSER | 945 | 25.0 | **+0.517** | 0.703 | 0.143 | 55 | 1.499 |
| FINAL_FLIP_EXIT_WINNER | 1,425 | 37.8 | **+0.607** | 0.782 | 0.148 | 70 | 3.659 |
| SESSION_EXIT | 99 | 2.6 | +0.830 | 1.057 | 0.171 | 80 | 4.405 |

**This is the study's most uncomfortable table.** Eventual losers are already
*profitable* at confirmation — the 945 flip-exit losers hold **+0.517 ATR** at
the flip and hand all of it back plus more. The 1,305 later-stopped trades hold
+0.284 and end at −1 ATR. **2,250 of 3,774 confirmed trades (59.6%) are in profit
at confirmation and end in a loss.**

And winners are not meaningfully richer at confirmation than losers: +0.607 vs
+0.517. **Nothing in the confirmation-close mark separates them.** By eventual
MFE bucket the return at confirmation is flat from +0.54 to +0.64 across every
bucket from 1–1.5 ATR up to ≥3 ATR. Only the `<1 ATR` bucket is distinguishable
(+0.196).

---

## 4. Phase 3 — how much room a runner actually needs

Unconstrained mode, Top-2.5. Entry-relative landmarks, first achievement
**strictly after** confirmation; landmarks already held at the flip are excluded
and counted separately.

| Landmark | reached after | already held | **A** med | A p75 | A p90 | A p95 | B med | B p90 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| +0.50 | 1,103 | 2,398 | 0.252 | 0.576 | 1.009 | 1.283 | 0.459 | 1.240 |
| +1.00 | 1,911 | 970 | 0.322 | 0.697 | 1.148 | 1.427 | 0.621 | 1.492 |
| +1.50 | 2,026 | 261 | 0.415 | 0.803 | 1.244 | 1.512 | 0.864 | 1.732 |
| +2.00 | 1,714 | 70 | 0.485 | 0.872 | 1.299 | 1.549 | 1.051 | 1.944 |
| +2.50 | 1,393 | 22 | 0.509 | 0.888 | 1.320 | 1.530 | 1.221 | 2.067 |
| +3.00 | 1,120 | 10 | 0.526 | 0.920 | 1.362 | 1.627 | 1.356 | 2.259 |

**A** = adverse excursion from the confirmation close. **B** = giveback from the
running favorable extreme. Armed population is tighter still: median 0.43 / 0.46 /
0.48 at +2.0 / +2.5 / +3.0.

**The requirement grows only weakly with ambition.** Getting to +3.0 ATR needs a
median 0.526 ATR of room versus 0.322 for +1.00 — a 63% increase in room for a
200% increase in target. The p90 barely moves at all (1.148 → 1.362).

---

## 5. Phase 4 — separability, and GATE A

**Losers** are measured over their whole post-confirmation path; **runners**
before first reaching their threshold. Those are different questions and using
one clock for both was a defect caught during this study.

| Deterioration (A, from confirm close) | eventual losers touched | ≥2 ATR runners needed | ≥2.5 needed | ≥3 needed | **separation vs ≥2.5** |
|---|---:|---:|---:|---:|---:|
| 0.250 | 99.6% | 68.0% | 71.2% | 73.7% | 28.4 |
| 0.375 | 99.2% | 56.2% | 59.1% | 61.8% | 40.2 |
| 0.500 | 98.5% | 47.1% | 50.0% | 51.5% | 48.5 |
| 0.625 | 96.5% | 38.2% | 40.0% | 41.5% | 56.5 |
| **0.750** | **94.3%** | 30.3% | **31.4%** | 33.1% | **62.8** |
| **1.000** | **85.2%** | 18.7% | **20.0%** | 21.6% | **65.2** |

> ### GATE A — YES
>
> **Most ≥2.5 ATR runners (68.6%) never needed more than 0.75 ATR of retracement
> from the confirmation close in order to develop, while 94.3% of eventual losers
> exceed it.** The separation is 63 points at 0.75 ATR and 65 at 1.00 ATR, and it
> is monotone across the whole grid.
>
> This is a structural region worth testing, **not an optimal stop.** No level is
> recommended and none was tuned.

**Method B is a null and is reported as one.** Measured from the running
favorable extreme, 100% of every group — losers, winners, ≥3 ATR runners alike —
touches every level from 0.25 to 1.00 ATR. By the opposing flip essentially every
trade has given back more than 1 ATR, so the measure cannot discriminate. Same
degeneracy class as the path-threshold events that failed in
`post_confirmation_score_deterioration`.

---

## 6. Phase 5 — conditioning on profit already owned

Top-2.5, unconstrained excursions with constrained labels.

| Profit at confirm | n | P(stop) | P(flip loser) | P(flip winner) | P(≥2 ATR) | P(≥2.5) | P(≥3) | A med | A p90 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| <0 | 300 | **0.643** | 0.170 | 0.187 | 0.300 | 0.240 | 0.183 | 1.140 | 2.013 |
| 0–0.25 | 801 | 0.521 | 0.220 | 0.251 | 0.342 | 0.277 | 0.220 | 1.148 | 1.988 |
| 0.25–0.50 | 876 | 0.371 | 0.266 | 0.345 | 0.421 | 0.321 | 0.267 | 1.141 | 2.074 |
| 0.50–0.75 | 764 | 0.272 | 0.272 | 0.428 | 0.496 | 0.384 | 0.288 | 1.151 | 2.149 |
| 0.75–1.00 | 475 | 0.196 | 0.297 | 0.474 | 0.579 | 0.463 | 0.385 | 1.232 | 2.168 |
| ≥1.00 | 558 | **0.124** | 0.244 | **0.563** | 0.712 | **0.586** | 0.469 | 1.312 | 2.452 |

**Outcome probability swings by 5×; the risk requirement does not move.** P(stop)
falls from 0.643 to 0.124 and P(≥2.5 ATR) rises from 0.240 to 0.586 — but the
median post-confirm adverse excursion is 1.14–1.31 ATR in *every* bucket and p90
is 1.99–2.45 in every bucket.

The hypothesis the brief offered — that a trade +0.75 ATR at confirmation
deserves a different risk budget than one at +0.10 — **is not supported**. What
the profit bucket predicts is *whether the trade works*, not *how much room it
needs*. That argues for conditioning selection or size on profit-at-confirmation,
not stop width.

---

## 7. Phase 6 — profit-floor feasibility

Top-2.5. Floors are entry-relative and evaluated only where they sit below the
open profit at confirmation. Floors trigger on the intrabar extreme.

| Floor | % placeable | ambiguous | failures intercepted | flip losers intercepted | winners touched | ≥2 ATR | ≥2.5 | ≥3 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| −0.25 | 99.3 | 1 | **97.1%** | 93.1% | 29.1% | 42.5% | **36.7%** | 34.9% |
| 0.00 (BE) | 90.2 | 2 | 100.0% | 100.0% | 48.7% | 57.1% | 51.3% | 48.4% |
| +0.25 | 70.8 | 8 | 100.0% | 100.0% | 64.7% | 68.2% | 62.3% | 58.7% |
| +0.50 | 47.6 | 11 | 100.0% | 100.0% | 75.8% | 76.6% | 71.3% | 66.8% |
| +0.75 | 27.4 | 2 | 100.0% | 100.0% | 82.0% | 82.4% | 78.6% | 75.5% |

**Read "touched" as an event count, not as damage.** A floor is a live order, so
whole-path touch is the correct measure — but a floor touched *after* a runner
has already developed is very likely an *improvement*, because the alternative
exit captures only 13.8% of MFE (§8). The table quantifies interception, not harm.

The only floor with clearly favourable asymmetry on its own terms is **−0.25 ATR**
(97.1% of failures intercepted against 36.7% of ≥2.5 runners touched) — and that
is really a tighter stop rather than a profit floor. Breakeven and above intercept
every failure but touch half to four-fifths of everything else.

---

## 8. Phase 7 — the runner ladder is memoryless

Top-2.5, clock reset at each landmark's first causal achievement.

| Transition | n eligible | n reached | **P(next)** | giveback, successful (med / p75 / p90) | giveback, failed (med) | secs |
|---|---:|---:|---:|---|---:|---:|
| +1.0 → +1.5 | 2,881 | 2,270 | **0.788** | 0.591 / 1.034 / 1.504 | 2.195 | 47 |
| +1.5 → +2.0 | 2,287 | 1,778 | **0.777** | 0.627 / 1.048 / 1.603 | 2.262 | 51 |
| +2.0 → +2.5 | 1,784 | 1,410 | **0.790** | 0.634 / 1.044 / 1.626 | 2.402 | 50 |
| +2.5 → +3.0 | 1,415 | 1,129 | **0.798** | 0.617 / 1.096 / 1.674 | 2.438 | 47 |

**Every rung is the same rung.** Transition probability is ~0.79 regardless of
maturity, the room a successful transition needs is ~0.6 ATR median / ~1.6 ATR p90
regardless of maturity, and it takes ~50 seconds regardless of maturity.

This directly answers the brief's question about progressive tightening: **the
geometry gives no reason to tighten as the runner matures.** A rule that tightens
with maturity would be imposing structure the data does not contain.

Failed transitions are unambiguous when they happen — median giveback 2.2–2.4 ATR
versus ~0.6 for successful ones — but that is measured to final exit, so it
describes the collapse rather than predicting it.

---

## 9. Phase 8 — exit efficiency, and GATE B

Constrained mode. Capture = realized flip-exit return / max MFE; trades with max
MFE below 0.10 ATR are excluded rather than divided through.

| Population | entries | flip-exit | share | capture mean | capture med | giveback med | max MFE med | exit return med |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| top_10 | 8,988 | 3,724 | 41.4% | 0.127 | 0.172 | 2.008 | 2.606 | 0.421 |
| top_5 | 7,396 | 3,152 | 42.6% | 0.082 | 0.141 | 2.017 | 2.563 | 0.352 |
| **top_2_5** | 5,823 | 2,370 | 40.7% | **0.067** | **0.138** | **2.032** | 2.586 | 0.358 |
| top_1 | 3,415 | 1,371 | 40.2% | 0.086 | 0.135 | 2.046 | 2.664 | 0.379 |
| armed | 8,950 | 3,709 | 41.4% | 0.126 | 0.173 | 2.008 | 2.607 | 0.422 |

By outcome (Top-2.5): winners capture **38.1%** (giveback 2.13 ATR); losers
capture **−28.8%** (giveback 1.94 ATR). By max-MFE bucket, capture rises
monotonically from −0.895 (`<1 ATR`) to +0.488 (`≥3 ATR`) — the biggest runners
are handled least badly, but still surrender 2.38 ATR each.

**Current expectancy** (Top-2.5, over ALL 5,823 entries): **−0.069 gross,
−0.126 net** per entry.

> ### GATE B — YES, and it is the larger opportunity
>
> **Total recoverable giveback is 5,183 ATR across 5,823 entries = +0.89 ATR per
> entry.** Against that pool:
>
> | Expectancy target | ATR needed | % of recoverable giveback |
> |---|---:|---:|
> | +0.05 / trade | 291 | **5.6%** |
> | +0.10 / trade | 582 | **11.2%** |
> | +0.15 / trade | 873 | **16.9%** |
> | +0.25 / trade | 1,456 | **28.1%** |
>
> Turning this strategy from −0.13 net to positive requires capturing well under a
> fifth of what it currently hands back. The ratios are near-identical across all
> five populations (5.4–5.6% for +0.05), so this is a property of the exit, not of
> the entry threshold.

**A better runner exit can only reach 40.7% of entries** — the flip-exit share.
The other 59.3% are stopped before or after confirmation and are untouched by any
exit improvement.

---

## 10. Phase 9 — model overlay (EXPLORATORY OUT-OF-DOMAIN, NOT DEPLOYABLE)

The gate in SPEC §4 is satisfied — the reconciliation established the raw
post-confirmation score is a true dispatch, causally available at its decision
timestamp — but its domain status is the reason this section is labelled, not
quoted. **In-domain share at the event is 0.0%–0.6%.**

Top-2.5, at price states the price-only work flags as interesting:

| Price state | n | price-only P(fail) | + high model danger | **lift** | **runner cost** |
|---|---:|---:|---:|---:|---:|
| B ≥ 0.25 | 1,020 | 0.586 | 0.639 | +0.053 | −0.042 |
| B ≥ 0.50 | 2,952 | 0.594 | 0.682 | +0.088 | −0.085 |
| B ≥ 0.75 | 3,567 | 0.594 | 0.704 | +0.110 | −0.106 |
| A ≥ 0.50 | 2,995 | 0.713 | 0.748 | +0.035 | −0.032 |

**The lift and the runner cost are the same number in every single cell.** Adding
model danger buys failure precision at an almost exactly offsetting loss of
≥2.5 ATR runner retention — it re-ranks the population uniformly rather than
separating it. The armed population behaves identically (+0.008/−0.013 to
+0.129/−0.131).

**The model adds nothing to the price geometry here.** That is a clean secondary
null, and it is consistent with the predecessor study's conclusion.

---

## 11. Validation

`results/validation_report.json` — **all eleven gates pass**.

```text
population_parity        8,988 / 7,396 / 5,823 / 3,415 exact; armed 8,950
confirmation_parity      confirmed counts bracket the accepted survival figures,
                         gap == the same-bar ambiguous-tie count
independent_recompute    254 deterministic paths re-derived from raw 1s through a
                         separate code path; 0 mismatches on all six checks
entry_to_confirm_parity  0 MFE / 0 MAE mismatches
confirm_close_parity     0 close / 0 return mismatches
landmark_first_touch     0 timestamp mismatches, 0 "not actually first"
session_containment      0 events past the session close
no_overnight_stitching   0 paths spanning a session boundary
direction_normalization  0 negative MFE/MAE rows either side; synthetic LONG/SHORT
                         mirror test exact
same_bar_accounting      all collisions flagged, resolved adversely, counted
audit_gates              lint 0/0 · lookahead-auditor PASS · contract-checker
```

### Defects found and fixed

| # | Defect | Found by | Effect if shipped |
|---|---|---|---|
| 1 | Phase 7 clock reset checked the post-confirm re-touch **before** "already held at confirmation" | `lookahead-auditor` pass 1 (CRITICAL) | For runners already past a landmark at the flip, the entire intervening pullback was dropped from the transition giveback — inverting exactly what Phase 7 measures. |
| 2 | Same-bar collisions accounted for stop-vs-confirm only; stop-vs-landmark and floor-vs-landmark were silently credited optimistically | `lookahead-auditor` pass 1 (CRITICAL) | Violated SPEC §1.1 and validation gate 10; landmarks would have been credited on bars where the stop may have fired first. |
| 3 | Phase 1/8 fields computed whenever the flip fell in the window, even if the stop had already ended the trade | `lookahead-auditor` pass 1 (WARNING) | Confirmation economics for trades that never confirmed. |
| 4 | Giveback measured against a floored favorable level | own unit test | Would have reported 2.0 ATR giveback where the true figure was 1.6, whenever the pullback low stayed above entry. |
| 5 | Runner touch-rates used a whole-path maximum | own review of Phase 4 output | Counted deterioration occurring *after* the runner developed, overstating runner damage and understating Gate A's separation. |
| 6 | Validator's "independent" recompute used the last bar *at or before* the flip; the panel uses the first bar *at or after* | own validation run (6/196 mismatches) | A false failure, not a real one — but it would have masked a real one. |

**The pre-execution audit gate earned its keep**: it blocked the first full run
over defects 1–3, both of which would have corrupted headline tables.

---

## 12. Limitations

1. **This is geometry, not a policy.** Nothing here has been simulated as a rule,
   and no cost of acting has been charged beyond the frozen round turn.
2. **The Gate B pool is not free money.** Capturing giveback requires an exit that
   also truncates winners; the 28.1% figure assumes harvest at zero cost, which is
   not established.
3. **No placebo control has been run, and the next study must run one.**
   `post_confirmation_score_deterioration` showed that because the flip exit is so
   bad, *any* earlier exit looks profitable — its entire +246 ATR result vanished
   against a matched random exit. The Gate B pool here is the same pool. What is
   new is that this study identifies *structure* a random exit does not have
   (§5 separation, §8 memoryless ladder); that structure is what the next study
   must test against a count-matched random control.
4. **Phase 4 runner rates are measured on the unconstrained path.** Under a live
   1 ATR stop some of those losers are already gone.
5. **Phase 6 "touched" is an event count, not damage** (§7).
6. **2025 is not threshold-OOS**; 2026 untouched.

---

## Terminal classification

```text
E. BOTH CONFIRMED-LOSS CONTAINMENT AND RUNNER HARVESTING WARRANT
   BOUNDED POLICY STUDIES
```

Both gates pass materially, and they are not the same opportunity.

- **Gate A — YES.** 94.3% of eventual losers retrace ≥0.75 ATR from the
  confirmation close; only 31.4% of ≥2.5 ATR runners ever needed that much room
  to develop. A 63-point separation, monotone across the grid.
- **Gate B — YES, larger.** The flip exit captures 13.8% of MFE and hands back
  2.03 ATR per trade. The recoverable pool is +0.89 ATR/entry, and +0.15 ATR/trade
  of expectancy needs only 16.9% of it.

**Candidate regions — described, NOT evaluated as rules. None of the figures
below is a recommended parameter, and none was tuned; every number is read
directly off a phase table above.**

1. The **loser/runner separation is widest between 0.625 and 1.00 ATR below the
   confirmation close** (§5), where loser interception stays ≥85% while the share
   of ≥2.5 ATR runners that ever needed that much room falls below ~21%. That is a
   description of where the curves are furthest apart, not a proposed stop.
2. **The runner ladder shows no maturity effect** (§8): transition probability
   ~0.79 and room requirement ~0.6 ATR median / ~1.6 ATR p90 at every rung. The
   implication is negative rather than prescriptive — a rule that tightens with
   maturity would impose structure the data does not contain.
3. **Profit at confirmation moves outcome probability 5× while leaving the room
   requirement flat** (§6). If it is used at all, the evidence points at selection
   or sizing rather than stop width.

**What must come first in the next study:** a count-matched random-exit placebo.
Everything in Gate B is measured against a baseline already known to be terrible,
and this research line has twice mistaken "exiting earlier than a bad exit" for an
edge.
