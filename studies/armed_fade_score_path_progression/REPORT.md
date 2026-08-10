# Armed Fade Score-Path Progression and MAE-to-Flip — Report

**Study:** `armed_fade_score_path_progression` · 2026-08-09
**Substrate:** `data/canonical/regime_complete_v1/` (REGIME-COMPLETE STORE ACCEPTED)
**Population:** 8,950 armed regimes, 2021–2025, RTH, from 2,028,394 scored
in-domain observations over 28,383,730 RTH 1s bars.
**Status:** every figure below comes from an artifact under `results/`. Both
audit gates ran **before** these numbers were generated.

---

## 1. Executive summary

**Top-10 is a good arm, deeper thresholds are genuinely informative, and waiting
for them is still not worth it.** All three statements are supported; the third
is the one that matters.

| Question | Answer |
|---|---|
| Does Top-10 function as an early-warning arm? | **Yes, and better than expected.** 97.5% of armed regimes reach their confirming flip before the session close. |
| Does confirmation probability improve at deeper levels? | **Yes, monotonically.** 0.520 → 0.589 → 0.648 → 0.731 (Walk B), stable across both directions and all five years. |
| How much opportunity is lost by waiting? | **More than the probability is worth.** Median return to confirmation falls 0.578 → 0.242 ATR, a 58% cut, for +0.211 confirmation. |
| What MAE do successful flips require? | **Far more than 1 ATR.** From the arm, p90 = **4.14 ATR**, p95 = **5.72 ATR**. Only 53.4% of successful confirmations survive a 1.0 ATR stop. |
| Which score-path shape is informative? | **Re-expansion, and only re-expansion.** It is the one shape that survives duration-matching. |

**The single most important finding is that direction is not the problem.** The
model is nearly always eventually right: 8,725 of 8,950 armed regimes (97.5%)
see their confirming flip before 15:00 CT the same day. Yet 47.4% of them are
stopped out at 1.0 ATR first. **The binding constraint on this entire signal
family is stop room, not signal quality.**

That reframes the predecessor study's negative result. `model_driven_entry_exit_discovery`
concluded that no entry rule reached breakeven and that "the loss side is
untouched" by every exit tested. This study says why: the confirming flip is
close to certain, and a 1.0 ATR stop destroys 46.6% of the trades that would
have reached it.

---

## 2. Top-10 arm funnel

Walk A, arm-anchored. Every metric measured **from the arm**; deeper levels
subset the population and never move the measurement origin. Confirmation is the
conservative censored bound.

| Stage | n | % of armed | P(confirm) | P(stop first) | median s to confirm | median return | median MAE |
|---|---:|---:|---:|---:|---:|---:|---:|
| armed Top-10 | 8,950 | 100.0 | 0.5202 | 0.4743 | 115.5 | +0.854 | 0.330 |
| → reached Top-5 | 5,404 | 60.4 | 0.6188 | 0.3756 | 130.0 | +0.827 | 0.371 |
| → reached Top-2.5 | 3,290 | 36.8 | 0.7033 | 0.2921 | 135.0 | +0.841 | 0.378 |
| → reached Top-1 | 1,482 | 16.6 | 0.8003 | 0.1943 | 155.0 | +0.916 | 0.400 |

Incremental lift: **+0.099 → +0.085 → +0.097**. Remarkably even.

**Walk A overstates the lift, and Walk B is the honest version.** In Walk A a
level counts only if it was reached while the arm-anchored lifecycle was still
alive, so "reached Top-5" already conditions on not having been stopped. Walk B
re-enters independently at each level with its own reference price, own frozen
ATR, and own 1.0 ATR stop:

| Level | reached n | P(confirm) | lift vs arm |
|---|---:|---:|---:|
| Top-10 (arm) | 8,950 | 0.5202 | — |
| Top-5 | 7,371 | 0.5892 | +0.069 |
| Top-2.5 | 5,803 | 0.6478 | +0.128 |
| Top-1 | 3,401 | 0.7313 | +0.211 |

The lift survives the correction — +0.211 rather than +0.280 from arm to Top-1 —
so **progression is real predictive content, not purely a survivorship artifact.**

**Terminal outcomes, Walk A** (8,950): CONFIRMED 4,656 · STOPPED_BEFORE_CONFIRM
4,245 · SESSION_CLOSE_UNRESOLVED 49 · CENSORED 0. **Ambiguous same-bar
stop/confirm collisions: 0**, so the conservative and optimistic bounds coincide
exactly and no result here depends on the tie-break.

**Held to the opposing flip** (descriptive context, so that "confirmed" is not
read as "profitable"): STOPPED_BEFORE_CONFIRM 4,245 · CONFIRMED_THEN_STOPPED 822
· FINAL_FLIP_EXIT_WINNER 2,350 · FINAL_FLIP_EXIT_LOSER 1,359 · SESSION_EXIT 174.
Of the 4,656 that confirm, 822 are still stopped out afterwards.

---

## 3. Risk required to survive

**This section is the study's second central question, and reporting it two ways
is the reason the answer is trustworthy.**

Walk B, MAE from each level's own entry to the confirming flip.

### Uncensored — every entry reaching the flip before the session close, no stop applied

| Level | n | median | p75 | p90 | p95 | max | ≤0.25 | ≤0.50 | ≤0.75 | ≤1.00 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Top-10 | 8,725 | 0.883 | 2.212 | **4.141** | **5.717** | 60.32 | 21.6% | 35.6% | 45.8% | **53.4%** |
| Top-5 | 7,209 | 0.681 | 1.849 | 3.713 | 5.215 | 33.69 | 27.9% | 42.5% | 52.4% | 60.2% |
| Top-2.5 | 5,699 | 0.492 | 1.519 | 3.302 | 4.802 | 33.83 | 34.2% | 50.4% | 59.5% | 66.0% |
| Top-1 | 3,344 | 0.331 | 1.043 | **2.565** | **3.892** | 18.42 | 43.1% | 59.0% | 68.4% | **74.4%** |

### Censored at 1.0 ATR — the Walk A survivor population

| Level | n | median | p75 | p90 | p95 | max | ≤0.25 | ≤0.50 | ≤0.75 | ≤1.00 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Top-10 | 4,656 | 0.330 | 0.596 | 0.818 | 0.907 | 1.00 | 40.4% | 66.7% | 85.8% | **100.0%** |
| Top-5 | 4,343 | 0.281 | 0.559 | 0.803 | 0.891 | 1.00 | 46.4% | 70.5% | 87.0% | 100.0% |
| Top-2.5 | 3,759 | 0.237 | 0.480 | 0.744 | 0.866 | 1.00 | 51.9% | 76.3% | 90.3% | 100.0% |
| Top-1 | 2,487 | 0.201 | 0.432 | 0.696 | 0.837 | 1.00 | 58.0% | 79.4% | 92.0% | 100.0% |

**The censored table is an artifact of its own premise and must not be read as
an answer.** Its population is *defined* by surviving 1.0 ATR, so it is bounded
above by 1.0 ATR, its ≤1.00 survival column is necessarily 100%, and its p90/p95
are truncation points rather than measurements.

The difference is not cosmetic. At the arm, the censored table says successful
flips need **0.82 ATR** of stop room at p90. The uncensored table says
**4.14 ATR** — a **5.0× understatement**. Had this study reported only the
population implied by the original brief, its central risk number would have
been wrong by a factor of five in the dangerous direction.

**The honest answer to Q2:** 90% of flips that reach confirmation require up to
**4.14 ATR** of adverse excursion from the Top-10 arm; 95% require up to
**5.72 ATR**. Entering later shrinks the requirement substantially — 2.57 and
3.89 ATR from Top-1 — but never to anything a 1 ATR stop covers.

---

## 4. Remaining opportunity

Walk B, confirmed entries, measured from each level's own entry.

| Level | n | P(confirm) | median return | p25 | p75 | median **net** | median MFE | median regime progress at entry |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Top-10 | 8,725 | 0.520 | **+0.578** | −0.101 | +0.974 | +0.523 | 0.826 | 2.22 ATR |
| Top-5 | 7,209 | 0.589 | +0.465 | +0.029 | +0.837 | +0.409 | 0.704 | 2.59 ATR |
| Top-2.5 | 5,699 | 0.648 | +0.341 | 0.000 | +0.696 | +0.286 | 0.579 | 2.93 ATR |
| Top-1 | 3,344 | 0.731 | **+0.242** | −0.030 | +0.564 | +0.184 | 0.467 | 3.32 ATR |

The trade-off is clean and it goes the wrong way. Multiplying confirmation
probability by median remaining return as a crude expectancy proxy:

```text
Top-10   0.520 x 0.578 = 0.301   <- best
Top-5    0.589 x 0.465 = 0.274
Top-2.5  0.648 x 0.341 = 0.221
Top-1    0.731 x 0.242 = 0.177   <- worst
```

**Every step deeper buys less than it costs.** Median regime progress at entry
rises from 2.22 to 3.32 ATR across the levels, which is the mechanism: the score
reaches its deepest percentiles only after the move it is fading has already
travelled a further ATR, and that ATR is taken out of the trade's remaining
return.

This corroborates the predecessor study's strongest structural result — *fade
early in the regime's move, not late* — from an entirely different direction.
There, entering at 0.5–2.0 ATR of realized progress was gross-positive at 4 of 6
thresholds while 2.0–5.0 ATR was negative at all 6. Here, waiting for score
confirmation is precisely a mechanism for entering later in the move.

---

## 5. Score-path shape

**Four of the five shape classes are confounded with trade duration and must not
be read as predictors.** The shape is computed over post-arm dispatches bounded
by the terminal event, so a trade that ends quickly has few observations and
little opportunity to display a retreat:

| Class (r = 0.05) | n | % | median post-arm observations | P(confirm) |
|---|---:|---:|---:|---:|
| TOP10_ONLY | 3,546 | 39.6 | 13 | 0.370 |
| RETREAT_REEXPANSION | 1,822 | 20.4 | 24 | 0.617 |
| OSCILLATING | 1,557 | 17.4 | 45 | 0.696 |
| RETREAT_NO_RECOVERY | 1,317 | 14.7 | 18 | 0.331 |
| MONOTONIC_PROGRESS | 708 | 7.9 | **6** | **0.989** |

`MONOTONIC_PROGRESS` at P(confirm) = 0.989 is not a finding. Binning all armed
regimes by post-arm observation count exposes the mechanism directly:

| Observation quintile | median obs | P(confirm) | share classified "no retreat" |
|---|---:|---:|---:|
| Q1 | 5 | 0.735 | 53.5% |
| Q2 | 12 | 0.518 | 13.3% |
| Q3 | 19 | 0.439 | 2.0% |
| Q4 | 30 | 0.423 | **0.0%** |
| Q5 | 58 | 0.459 | **0.0%** |

Past roughly 30 dispatches it is *impossible* to be classified "no retreat".
`MONOTONIC_PROGRESS` therefore means "this trade ended before the score had time
to retreat", and trades end quickly mostly because they confirmed. The class is
partly determined by the outcome it is being used to predict.

### Re-expansion is the exception, and it is real

Conditional on having retreated at all, whether the score recovers is strongly
informative — and it holds inside every duration bin, which is exactly the test
the other classes fail:

| Post-arm observation quartile (retreaters only) | median obs | P(confirm), re-expanded | P(confirm), no recovery | separation |
|---|---:|---:|---:|---:|
| Q1 | 9–10 | 0.850 | 0.306 | **+0.544** |
| Q2 | 17–18 | 0.692 | 0.179 | **+0.513** |
| Q3 | 28–30 | 0.582 | 0.167 | **+0.415** |
| Q4 | 52–58 | 0.500 | 0.240 | **+0.260** |

Durations are matched within each row (9 vs 10, 17 vs 18, 28 vs 30, 52 vs 58),
so the separation is not a duration effect. Pooled at r = 0.05: re-expansion
0.611 (n = 4,127) vs retreat-without-recovery 0.238 (n = 3,500). At r = 0.03:
0.605 vs 0.260. **Stable across both retreat definitions, neither of which was
tuned.**

The `no_retreat` comparator (P(confirm) = 0.983) is the same duration artifact as
`MONOTONIC_PROGRESS` and is excluded from that comparison.

**Repeated threshold crossing**, the fourth pattern the brief asked about, is
carried as the raw `band_changes` field rather than folded into `OSCILLATING`: a
single retreat-and-recovery through one band already produces three band changes,
so a band-count disjunct would have swallowed `RETREAT_REEXPANSION` almost
entirely and hidden the one real finding in this section.

---

## 6. Progression speed

**Speed does not predict confirmation.** Within-level elapsed-time quartiles,
Top-10 → Top-5 (n = 5,404, quartile edges 5 / 15 / 45 s):

| Quartile | range (s) | n | P(confirm) | median MAE to confirm | median return | median progress ATR |
|---|---|---:|---:|---:|---:|---:|
| Q1 (fastest) | ≤ 5 | 1,907 | 0.589 | 0.247 | +0.777 | 2.53 |
| Q2 | 5–15 | 978 | 0.615 | 0.201 | +0.835 | 2.64 |
| Q3 | 15–45 | 1,194 | **0.676** | 0.345 | +0.896 | 2.48 |
| Q4 (slowest) | > 45 | 1,325 | 0.613 | 0.637 | +0.815 | 2.28 |

Non-monotone, with the peak in the middle — there is no fast-is-better or
slow-is-better story. The same shape holds for Top-10 → Top-2.5 (0.664 / 0.742 /
0.734 / 0.682) and Top-10 → Top-1 (0.785 / 0.813 / 0.818 / 0.787).

**Speed does predict required stop room, monotonically.** Median MAE-to-confirm
rises 0.247 → 0.201 → 0.345 → 0.637 across the quartiles. Slow escalation costs
roughly 2.5× the stop room for no gain in confirmation.

The brief asked specifically whether rapid escalation is simply later in the
price move. It is not: median regime progress at entry is essentially flat across
quartiles (2.28–2.64 ATR), so speed and move-maturity are separable here, and
speed is the one that carries no signal.

---

## 7. Persistence

Counted in true dispatches. Cadence is 5.0s modal (p95 = 5.0s), but 5.0% of
intervals exceed 5s and the per-regime maximum gap has median 10s, p90 50s, p95
85s, max 835s — so a three-observation run is not reliably 15 seconds.

| Cell | n | P(confirm) | median MAE to confirm | median return | median s to confirm |
|---|---:|---:|---:|---:|---:|
| Top-10 × 1 | 8,950 | 0.520 | 0.330 | +0.854 | 115.5 |
| Top-10 × 2 | 5,582 | 0.555 | 0.289 | +0.840 | 115.0 |
| Top-10 × 3 | 4,138 | 0.577 | 0.263 | +0.830 | 115.0 |
| Top-5 × 2 | 3,280 | 0.659 | 0.341 | +0.826 | 120.0 |
| Top-5 × 3 | 2,394 | 0.685 | 0.320 | +0.820 | 115.0 |

Persistence helps modestly and monotonically: +0.057 confirmation for three
consecutive Top-10 observations, at a cost of 54% of the population and almost no
loss of median return (+0.854 → +0.830). It also *reduces* required stop room
(0.330 → 0.263). This is the cheapest of the refinements tested — but +0.057 is
small next to the +0.211 available from Top-1, and it is bought with the same
kind of delay.

---

## 8. Direction and year stability

**This is the strongest part of the result.** Walk B P(confirm), censored bound:

| | Top-10 | Top-5 | Top-2.5 | Top-1 | lift (Top-1 − Top-10) |
|---|---:|---:|---:|---:|---:|
| SHORT (n = 4,902) | 0.524 | 0.596 | 0.653 | 0.745 | +0.221 |
| LONG (n = 4,048) | 0.515 | 0.580 | 0.640 | 0.716 | +0.201 |
| 2021 (n = 1,828) | 0.550 | 0.610 | 0.676 | 0.756 | +0.206 |
| 2022 (n = 1,825) | 0.531 | 0.587 | 0.644 | 0.739 | +0.208 |
| 2023 (n = 1,763) | 0.526 | 0.608 | 0.678 | 0.759 | +0.233 |
| 2024 (n = 1,771) | 0.483 | 0.573 | 0.642 | 0.702 | +0.219 |
| 2025 (n = 1,763) | 0.509 | 0.567 | 0.598 | 0.700 | +0.191 |

**Monotone in every direction and every year, with no exceptions.** The Top-1
lift clears +0.19 in all five years and both directions. The Top-2.5 lift clears
+0.10 in four of five years (2025 is +0.089).

Median return to confirmation is equally stable — Top-10: 0.80 / 0.85 / 0.83 /
0.91 / 0.90 across 2021–2025; Top-1: 0.31 / 0.26 / 0.27 / 0.31 / 0.39.

This is a marked contrast with the predecessor study, where all six strongest
composites were negative on the 2024 selection year and five of six on 2025. The
difference is that this study measures a **structural property of the score
path**, not a PnL edge — and structural properties of this signal family are
evidently stable even where its economics are not.

**2025 is not threshold-out-of-sample.** Both frozen calibration populations are
calendar-2025 and overlap the evaluation window; every 2025 row inherits
`THRESHOLD_OVERLAP_WAIVER.json`.

---

## 9. Candidate entry concepts

Five hypotheses. **None is a policy, none is optimized, and none is recommended
for advancement.** Metrics are Walk B, measured from the entry level itself.

| # | Concept | n | P(confirm) | median MAE (unc.) | p90 MAE (unc.) | median return | median net | median s |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | Arm Top-10 → enter first Top-5 | 7,371 | 0.589 | 0.681 | 3.71 | +0.655 | +0.600 | 85 |
| 2 | Arm Top-10 → enter after 2 persistent Top-5 | 3,280 | 0.621 | 0.584 | 3.38 | +0.645 | +0.592 | 80 |
| 3 | Arm Top-10 → enter Top-5 on re-expansion | 3,767 | 0.607 | 0.710 | 3.43 | +0.674 | +0.618 | 110 |
| 4 | Arm Top-10 → enter Top-5 in fastest quartile (≤5s) | 1,907 | 0.566 | 0.752 | 3.88 | +0.685 | +0.632 | 95 |
| 5 | Arm Top-10 → enter first Top-2.5 | 5,803 | 0.648 | 0.492 | 3.30 | +0.475 | +0.418 | 55 |

Year stability, P(confirm) 2021→2025: #1 0.610/0.587/0.608/0.573/0.567 · #2
0.650/0.643/0.630/0.600/0.577 · #3 0.648/0.609/0.623/0.578/0.577 · #5
0.676/0.644/0.678/0.642/0.598. Direction splits are within 0.03 for all five.

**#2 (persistence) is the best of these** — highest confirmation among the Top-5
variants, lowest required stop room, and the shortest median wait — but its
advantage over #1 is +0.032 confirmation for 55% of the population.

Every one of these carries a p90 uncensored MAE between 3.30 and 3.88 ATR. **No
concept here is executable under a 1 ATR stop**, which is the same wall the
funnel hits.

---

## 10. Caveats and limitations

1. **Duration confounds four of five shape classes.** Documented in §5. Only
   re-expansion survives duration-matching; `MONOTONIC_PROGRESS` and `no_retreat`
   are artifacts and are labelled as such wherever they appear.
2. **Walk A's funnel is path-dependent by construction** and overstates the lift
   by roughly 0.07 absolute. Walk B is the honest comparison and is what §1 and
   §8 quote.
3. **2025 is not threshold-OOS** (§8).
4. **Intraday only.** The forced 15:00 CT flat truncates 49 unresolved regimes
   and every excursion measured here; these figures are not comparable to
   overnight-hold baselines.
5. **This is not an economic result.** No policy was simulated end-to-end, no
   exit was optimized, and the crude P × return products in §4 are a proxy, not
   an expectancy. Against these frozen models the predecessor study found 0 of 65
   entries and 0 of 18 exits net-positive; nothing here contradicts that.
6. **The 1 ATR stop is a study parameter, not a recommendation.** It was frozen
   before the run and is the reason the censored/uncensored split exists. §3 is
   an argument that it is too tight, not evidence that any wider stop is
   profitable — that requires a separate study with the loss side simulated.

---

## 11. Validation

`results/validation_report.json` — **`all_passed = true`**, all eight SPEC §9
gates.

```text
lifecycle_parity          PASS  first-qualifying reproduced exactly:
                                top_10 8,988 · top_5 7,396 · top_2_5 5,823 · top_1 3,415
                                arm delta 38 = 22 predecessor already qualified
                                + 16 no predecessor dispatch; 0 unexplained
true_dispatch_cadence     PASS  2,205,823 in-domain dispatches, 177,429 unscored
                                dropped, 2,028,394 observations, 0 nulls remaining,
                                0 duplicate (regime, ts) pairs, carry-forward
                                column absent from scores and present on paths
arm_definition            PASS  8,950 arms, one per regime, all age > 600s,
                                all >= Top-10, all crossings from below verified
                                by as-of join independent of the positional shift
event_ordering            PASS  0 confirm-before-arm · 0 non-monotonic level
                                sequences · 0 level-before-arm · 0 censored MAE
                                above 1 ATR · 0 confirmed-and-stopped ·
                                0 Walk A/Walk B Top-10 disagreements
                                2,757 multi-level same-dispatch pairs · 0 ambiguous
session_containment       PASS  0 terminals, confirms, or level reaches past the
                                session close
mae_independent_recompute PASS  100 confirmed trades per level re-derived from
                                canonical_regime_paths_all.parquet via a separate
                                code path; 0 mismatches at all four levels
assertions                PASS  0 violations across 14 checks
audit_gates               PASS  causal_lint 0 CRITICAL · lookahead-auditor PASS
                                (0 CRITICAL) · contract-checker CLEAR (0 blocking)
```

### Defects found and fixed during this study

| # | Defect | Found by | Effect |
|---|---|---|---|
| 1 | Empty measurement window when the confirming flip is stamped at the entry second — the horizon equalled the entry, so the walk returned CENSORED | own unit test `test_confirming_flip_stamped_at_the_entry_second_is_in_the_future` | Would have silently censored exactly the boundary case the inclusive resolver exists to capture. Fixed with a `max(..., start + 1)` window floor, verified not to cross the session end. |
| 2 | `band_changes >= 3` as an `OSCILLATING` disjunct | own test `test_every_shape_class_is_reachable` | A single retreat-and-recovery through one band produces three band changes, so the disjunct swallowed `RETREAT_REEXPANSION` — the one real finding in §5 — almost entirely. |
| 3 | `shift(1, fill_value=False)` could not distinguish "no prior observation" from "prior observation did not qualify" | `lookahead-auditor` pass 1 (WARNING) | A regime whose first in-domain dispatch was post-600s and already ≥ Top-10 was accepted as a crossing from below on zero evidence. 16 regimes. |
| 4 | Dormant cross-year partition bug: a `years` filter before arming would drop each regime's predecessor dispatch at year boundaries | `lookahead-auditor` pass 1 (NOTE) | Inert at the time, closed by a hard guard; `build()` no longer accepts a `years` argument at all. |
| 5 | Gate 3 verified the from-below property by recomputing the identical shift expression over the identical table | `lookahead-auditor` pass 1 (NOTE) | The check could only agree with itself. Rewritten as an as-of join; gate 1's reconciliation was rewritten the same way. |
| 6 | **Unscored dispatches treated as observations** | own gate 1 failure — 13 of 38 excluded regimes unexplained | 177,429 in-domain dispatches (8%) carry a null probability. A null is not evidence of "below threshold", and it renders as NaN and propagates through every running maximum it touches. No output was contaminated in the event, but the exposure was unbounded. Filtered at source; gate 2 now asserts zero nulls in the stream. |

Defect 6 surfaced only because gate 1 was written to reconcile its population
delta to *exactly zero unexplained*, rather than to a plausible number. A gate
that merely checked "the delta is small" would have passed and hidden it.

### Audit gates

- `causal_lint`: 0 CRITICAL / 0 WARNING, 11 files, at every checkpoint.
- `lookahead-auditor` pass 1 (**pre-execution**): PASS — 0 CRITICAL, 1 WARNING,
  2 notes. All three remediated (defects 3–5 above).
- `lookahead-auditor` pass 2 (bounded re-audit): PASS — 0 CRITICAL, 0 WARNING,
  0 notes; all pass-1 findings adjudicated RESOLVED. The new `join_asof` usage
  was verified against an isolated polars reproduction.
- `contract-checker` pass 1: **CLEAR** — 0 blocking, 2 hygiene findings, both
  since resolved. CC-1: SPEC and README cited `THRESHOLD_OVERLAP_WAIVER.json`
  without a path; the store's own `waiver_artifact` column names
  `studies/full_trade_path_builder/THRESHOLD_OVERLAP_WAIVER.json` as the
  canonical waiver for all six percentiles, so the citation was corrected rather
  than a local copy forked. CC-2: SPEC §3's pre-implementation estimate of
  8,953 arms / 35-regime delta is superseded by the reconciled 8,950 / 38;
  §3 now carries a dated amendment preserving both.

Both auditor passes ran before the reported results were generated. REPORT.md
and its assigned terminal label postdate `contract-checker` pass 1 and are
therefore not yet gate-verified (findings CC-3 and CC-4, open for pass 2).

---

## Verdict

```text
ARMED SCORE PROGRESSION SUPPORTS REFINEMENT
```

Per the criteria frozen in SPEC §9a, this label requires all §9 gates to pass and
at least one deeper level to lift confirmation probability over the Top-10 arm by
≥ 10 absolute points while retaining positive median remaining return, stable in
sign across both directions and ≥ 4 of 5 years. Top-2.5 (+0.128, median return
+0.341, 4 of 5 years ≥ +0.10) and Top-1 (+0.211, median return +0.242, 5 of 5
years) both clear it.

**The label is about whether progression is informative, not about whether it is
profitable.** It is informative and remarkably stable. It is also not worth
waiting for on any expectancy proxy computed here, and no candidate in §9 is
executable under the 1 ATR stop this study used.

- **Best early-warning level:** **Top-10**, and it is stronger as a warning than
  as a filter — 97.5% of armed regimes reach their confirming flip before the
  session close.
- **Best confirmation level:** **Top-1** for confirmation probability alone
  (0.731, +0.211 over the arm, stable in all five years). **Top-2.5** for the
  balance of probability against remaining return. **On the crude P × return
  proxy the arm itself beats all three deeper levels** (0.301 vs 0.274 / 0.221 /
  0.177).
- **MAE required by 90% of successful flips:** **4.14 ATR** from the arm;
  3.71 from Top-5, 3.30 from Top-2.5, 2.57 from Top-1.
- **MAE required by 95% of successful flips:** **5.72 ATR** from the arm;
  5.22 from Top-5, 4.80 from Top-2.5, 3.89 from Top-1.
- **Largest opportunity-cost trade-off from waiting:** Top-10 → Top-1 buys
  +0.211 confirmation probability for a **58% cut in median return to
  confirmation** (+0.578 → +0.242 ATR), and median regime progress at entry rises
  from 2.22 to 3.32 ATR. Waiting is a mechanism for entering later in the move.
- **Most promising score-path hypothesis:** **post-arm re-expansion** — the only
  shape that survives duration-matching, separating confirmation by +0.26 to
  +0.55 absolute inside every post-arm observation quartile, consistent at both
  frozen retreat definitions.

**What this study most changes:** the next question for this signal family is not
which threshold to enter on. It is what to do about a stop, given that the model
is eventually right 97.5% of the time and a 1 ATR stop destroys 46.6% of the
trades that would have reached confirmation. Whether a wider stop is affordable
is not answerable from here — it requires the loss side simulated end-to-end,
which this study deliberately did not do.
