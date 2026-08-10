# Post-Confirmation Score Deterioration / Runner Protection — Report

**Study:** `post_confirmation_score_deterioration` · 2026-08-10
**Substrate:** `data/canonical/regime_complete_v1/`
**Predecessor:** `studies/armed_fade_score_path_progression/`
**Population:** 4,705 confirmed armed regimes (panel: 658,331 observations over 4,656 trades)

---

## Executive summary

**The post-confirmation score predicts failure well and cannot be used to manage
the trade.** Both halves of that sentence are strongly supported.

Answering the brief's seven questions directly:

**1. Does post-confirmation score deterioration predict regime failure?**
Yes, and strongly — but only after fixing the sign. Landmark AUC for failure on
the domain-model score is **0.684 / 0.735 / 0.753 / 0.780** at 60 / 120 / 180 /
300s, monotone in horizon, on 100% coverage of failed trades. Precision at a
0.85-quantile cutoff reaches 0.75 against a 0.45 base rate.

**2. Which deterioration behaviour is most informative?**
The score **level at a fixed elapsed time**. Nothing else. Path-threshold events
are worthless here: every escalation event fires on ~100% of trades with
precision exactly equal to the base rate (§3).

**3. Does failed re-expansion matter more than simple threshold crossing?**
Neither applies. Threshold-crossing events are **NOT APPLICABLE** — the frozen
percentile contracts were calibrated in-domain and do not transfer to the only
usable stream (§2.3). Re-expansion-style path events all degenerate to firing on
everything.

**4. At the time deterioration becomes detectable, how much open profit remains?**
**None — the position is already underwater.** Median open PnL when the flag
fires is **−0.20 to −1.04 ATR** at every early landmark. Failures are already at
a median −0.21 ATR at 60s and −0.34 ATR at 120s.

**5. How many failed trades could potentially be protected?**
25–45% at usable operating points (e.g. 484 of 1,933 alive failures at
t=120s/q=0.85). The ledger for acting on this is net positive: +43 to +246 ATR
depending on the operating point.

**6. How often would the same signal interfere with ≥2 / ≥2.5 / ≥3 ATR runners?**
Less than feared. At t=120s/q=0.85 it touches 6.0% of ≥2.5 ATR runners; at
q=0.95, 1.2%. Runner damage is **not** the binding constraint.

**7. Is there enough evidence to justify a dedicated trade-management study?**
**No.** The entire economic gain is non-specific. Against matched controls, the
score-based flag does not beat a random flag of the same size at **any** of 25
operating points, and loses to a plain "worst open PnL" ranking at 11 of 25. The
net-positive ledger is measuring *"exiting early beats holding to the opposing
flip"* — which is the predecessor study's own published conclusion, not new
information.

---

## 1. Population reconciliation

Derived, not assumed (`results/population_reconciliation.json`).

| Terminal label | Derived | Brief | Match |
|---|---:|---:|:--:|
| CONFIRMED_THEN_STOPPED | 822 | 822 | ✓ |
| FINAL_FLIP_EXIT_LOSER | 1,359 | 1,359 | ✓ |
| FINAL_FLIP_EXIT_WINNER | 2,350 | 2,350 | ✓ |
| SESSION_EXIT | 174 | 174 | ✓ |

Confirmed via the continuation walk = 4,705; via Walk A = 4,656. **The 49-trade
delta is exactly Walk A's `SESSION_CLOSE_UNRESOLVED` set**, which the continuation
walk folds into `SESSION_EXIT`. New-regime join matched 4,705 of 4,705.

Hold time after confirmation is the fact that shapes everything downstream:

| label | n | median hold s | median MFE ATR |
|---|---:|---:|---:|
| FINAL_FLIP_EXIT_WINNER | 2,350 | 960 | 3.67 |
| FINAL_FLIP_EXIT_LOSER | 1,359 | 300 | 1.48 |
| CONFIRMED_THEN_STOPPED | 822 | 217.5 | 1.05 |
| SESSION_EXIT | 174 | 419 | 3.56 |

**"Failure" is largely "the new regime was short-lived."** Some of the predictive
power below is therefore near-definitional, which is precisely why the economic
tests, not the AUC, decide this study.

---

## 2. Two Phase-0 findings that redefined the study

### 2.1 The polarity is inverted relative to the brief

Verified at rate 1.0: `bullish_in_domain` is true exactly when
`regime_direction == +1`. After confirmation we hold a position **aligned with**
the new regime — fading a bullish regime SHORT means confirmation is a *bearish*
regime starting, and we are short in a bearish regime. The model whose domain is
the new regime therefore predicts **that regime's own flip**, i.e. the end of our
position.

```text
domain-model score RISING  = our regime is likely ending = DANGER
domain-model score FALLING = our regime is persisting    = RUNNER
```

Every event the brief phrases as a score *retreat* is sign-flipped on the primary
stream. Had the brief's framing been implemented literally, the study would have
measured the exact opposite of its intent. Events are named `ESCALATION_*`
throughout to keep the sign error from re-entering through vocabulary.

### 2.2 Three score streams; the semantically ideal one is unusable

The `*_in_domain` flag is a **contract gate**, not an **availability gate** — a
distinction that inverts the feasibility verdict, and which I initially got
wrong.

| Stream | Coverage on the 2,181 failed trades | Verdict |
|---|---:|---|
| **A** in-domain-flagged | **7.7%** | excluded |
| **B** domain-model raw *(primary)* | **100%** | used |
| **C** other-model raw | ~100% | secondary |

Stream A is the semantically correct signal and it is structurally unusable. The
established-regime gate opens a median **352–448s** after confirmation while
failed trades die at a median **217–300s**:

```text
CONFIRMED_THEN_STOPPED  gate never opens before exit in 95.7% of trades;
                        median gate delay = 197% of the trade's whole duration
FINAL_FLIP_EXIT_LOSER   90.1% never opens before exit
FINAL_FLIP_EXIT_WINNER  only 30.6% never opens
```

**Availability is determined by the outcome.** Any stream-A analysis would
compare 159 failures against 1,628 winners on a population selected by having
survived long enough to be scored. Stream B carries an actual probability at
91.5–92.2% of rows *regardless* of the flag, giving complete coverage with a
median 41–59 observations even on the shortest-lived failures.

### 2.3 Threshold events are NOT APPLICABLE

Stream B reads each model outside its contractual domain. The number is causally
available at runtime, but the Top-10/5/2.5/1 contracts were calibrated in-domain
and do not transfer. The brief's *"loss of Top-1 / Top-2.5 / Top-5 / Top-10"*
events are therefore reported **NOT APPLICABLE with that reason**; synthesising
new cutoffs would create a second incompatible threshold definition, which the
brief's own Phase 0 rule 4 forbids.

---

## 3. Path-threshold events: a clean null

`results/deterioration_event_table.json`. Base failure rate 0.481.

| Event | fired | sensitivity | winner touch | precision |
|---|---:|---:|---:|---:|
| ESCALATION_0.03_from_min | 4,529 / 4,531 | 0.999 | 1.000 | **0.481** |
| ESCALATION_0.05_from_min | 4,528 | 0.999 | 1.000 | 0.481 |
| ESCALATION_0.10_from_confirm | 4,472 | 0.984 | 0.990 | 0.480 |
| STREAMC_RETREAT_0.05 | 4,528 | 0.999 | 1.000 | 0.481 |
| DIVERGENCE_price_high_score_high | 157 | 0.024 | 0.044 | **0.338** |

**Precision equals the base rate to three decimals — zero information.** Over a
trade carrying 41–179 dispatches the score is near-certain to rise 0.03–0.10 off
its running minimum at some point, so "did the score ever escalate" is always
yes. This is a property of the event definition, not of the market, and it
applies equally to every retreat/re-expansion construction the brief proposes.

Price/score divergence (Phase 3) fires on 157 trades at precision **0.338, below
the 0.481 base rate** — it weakly predicts *winners*. A null.

---

## 4. Where the information actually is

The signal is the **score level at a fixed elapsed time**, evaluated among trades
still open at that time (`results/phase0_gate1.json`, `landmark_tradeoff.json`).

| horizon | n alive | fail / win | AUC (level) | AUC (Δ from confirm) |
|---|---:|---|---:|---:|
| 60s | 4,471 | 2,121 / 2,350 | 0.684 | 0.659 |
| 120s | 4,283 | 1,933 / 2,350 | 0.735 | 0.706 |
| 180s | 3,795 | 1,475 / 2,320 | 0.753 | 0.712 |
| 300s | 3,117 | 884 / 2,233 | 0.780 | 0.723 |

**The landmark design is not a stylistic choice.** Path summaries over a window
ending at the terminal event are confounded with duration, and that confound has
now corrupted a result in this research line twice — the shape classes in the
predecessor study, and Phase 0 probe 1 of this study, where winners' apparently
higher peak score (0.540 vs 0.331) was almost entirely an artifact of observing
them for 111 dispatches versus 16 for losers.

Selected operating points (`landmark_tradeoff.json`):

| t | q | sens | winner touch | touch ≥2.5 ATR | precision | median open PnL at flag |
|---|---|---:|---:|---:|---:|---:|
| 120s | 0.70 | 0.449 | 0.177 | 0.162 | 0.676 | **−0.63** |
| 120s | 0.85 | 0.250 | 0.068 | 0.060 | 0.753 | **−0.86** |
| 120s | 0.95 | 0.093 | 0.015 | 0.012 | 0.837 | **−1.04** |
| 300s | 0.70 | 0.562 | 0.196 | 0.171 | 0.532 | **−0.46** |
| 600s | 0.95 | 0.200 | 0.029 | 0.026 | 0.500 | **−0.31** |

Discrimination is genuine and runner damage is modest. **But the open PnL column
is negative at every operating point at every early landmark.** By the time the
score identifies a failure, the position is already down 0.3–1.0 ATR. This is the
brief's own disqualifying condition: *"A deterioration signal that predicts
failure only after the profit has already disappeared is NOT useful."*

---

## 5. Gate 2: the ledger says yes, the placebo says no

### 5.1 The ledger, taken alone, is positive

`results/gate2_ledger.json`. Counterfactual per flagged trade =
`open PnL at flag − realized confirmation-anchored terminal PnL`.

| t | q | flagged | ATR saved on failures | ATR lost on winners | **net** |
|---|---|---:|---:|---:|---:|
| 60s | 0.50 | 2,236 | +1,325 | −1,079 | **+246** |
| 120s | 0.95 | 215 | +82 | −40 | **+42** |
| 300s | 0.70 | 935 | +413 | −269 | **+144** |
| 600s | 0.95 | 98 | +38 | −9 | **+29** |

Net positive at 24 of 25 operating points.

An earlier estimate in this study's own checkpoint predicted the opposite, by
conflating *remaining MFE* (the peak a winner would still reach) with *PnL
forgone* (exit-now minus realized exit). Winners give back most of their MFE by
the opposing flip, so ejecting one early costs far less than its remaining MFE
suggests. The correction is recorded because it is the same class of error the
report warns about elsewhere.

### 5.2 The placebo removes the entire result

`results/placebo.json`. The baseline being beaten is *holding to the opposing
flip* — which the predecessor study already identified as the worst-capture exit
of the eighteen it screened, with the explicit recommendation to *"exit at thesis
confirmation, not at the opposing flip."* So any rule that exits earlier can look
profitable while containing no information at all. Two matched controls:

- **RANDOM** — flag a random subset of the same size, 400 draws.
- **WORST_PNL** — flag the k trades with the most negative open PnL at the
  landmark. The sharper control: the score flag preferentially selects trades
  already losing, and exiting a loser early is mechanically good when the
  baseline is a 1 ATR stop.

| t | q | score net ATR | random mean | random p95 | score pctile | worst-PnL net |
|---|---|---:|---:|---:|---:|---:|
| 60s | 0.50 | +246 | +236 | +353 | 0.57 | +215 |
| 120s | 0.50 | +239 | +205 | +307 | 0.72 | +216 |
| 180s | 0.50 | **+78** | **+156** | +258 | **0.08** | +105 |
| 300s | 0.70 | +144 | +90 | +173 | 0.87 | +101 |
| 600s | 0.85 | +19 | +46 | +90 | 0.18 | +29 |

**Across all 25 operating points, not one exceeds the random p95.** The score's
percentile against the random distribution ranges 0.08–0.87 with a median of
≈0.55 — the dead centre of chance. At t=180s/q=0.50 the score returns +78 ATR
against a random mean of **+156**: worse than picking trades at random. Against
WORST_PNL the score loses at **11 of 25** points and wins at 14, with no pattern.

**The signal contributes nothing beyond exiting early, and adds nothing beyond
knowing the trade is currently down.**

This is the identical failure mode that closed
`contextual_runner_exit_v3_investigate` in this research line: an exit-timing rule
that looks profitable until it is compared against a matched random exit.

---

## 5.3 Most flagged escalations are temporary — and almost all runner flags are

`results/escalation_recovery.json`. A flagged trade **recovers** if `score_b`
falls back below the same cutoff before the terminal event. (This block's alive
population includes `SESSION_EXIT`, so counts run slightly above §4's.)

| t | q | flagged | recovery rate | P(fail \| recovered) | P(fail \| not recovered) | **≥2.5 ATR runner recovery rate** |
|---|---|---:|---:|---:|---:|---:|
| 60s | 0.85 | 689 | 0.778 | 0.621 | 0.994 | **0.988** |
| 120s | 0.85 | 661 | 0.661 | 0.620 | 0.960 | **0.930** |
| 180s | 0.85 | 587 | 0.750 | 0.602 | 0.959 | **0.951** |
| 300s | 0.85 | 482 | 0.718 | 0.512 | 0.802 | **0.858** |

Two things follow.

**58–78% of all flags are temporary**, and among the big runners that get
flagged, **86–99% recover.** Acting on the flag would eject, almost without
exception, runners that were never actually in trouble — which is the brief's
runner-protection concern arriving through a different door than the touch rates
in §4 suggested.

**"Flagged and did not recover" is a far sharper failure indicator** (P(fail)
0.80–0.99 versus 0.41–0.71 for recovered). But that distinction is only available
after waiting to see whether recovery happens, by which point the median trade
has resolved. It sharpens the prediction without making it actionable — the same
wall §4 hit.

## 6. Stability

`results/stability.json` carries pooled / LONG / SHORT / 2021–2025 breakdowns for
every event. They are reported for completeness but carry no weight: the events
they describe are the degenerate path-threshold events of §3, whose precision
equals the base rate in every slice by construction.

**2025 is NOT threshold-out-of-sample.** Both frozen calibration populations are
calendar-2025 and overlap the evaluation window; canonical waiver
`studies/full_trade_path_builder/THRESHOLD_OVERLAP_WAIVER.json`. No 2026 data was
touched.

---

## 7. Phase 8 not run

Per the brief — *"If the tradeoff is clearly unattractive: STOP. Do not optimize
further."* Gate 1 passed on information content. The economic case did not
survive its control. Running a policy simulation on a signal that does not beat a
random flag would manufacture a result rather than test one.

---

## 8. Limitations

1. **Stream B is read outside its contractual domain.** Causally available, but
   uncalibrated; no frozen threshold applies to it. This is what forced the
   distribution-free operating-point sweep instead of threshold events.
2. **The counterfactual is a single-decision exit**, not a full policy. It ignores
   re-entry and assumes an exit fills at the observed reference price. Both would
   have to be modelled properly before any policy claim — but the placebo result
   means there is nothing to model.
3. **Terminal price is reconstructed** from the predecessor's arm-anchored gross,
   which applies a 0.125-point flat band before normalising. Sub-tick imprecision
   only; it cannot move a result of this magnitude.
4. **`SESSION_EXIT` (174) is excluded from the failure target** as an artifact of
   the intraday constraint, and 49 of those trades have no stream-B observation.
5. **"Failure" correlates strongly with short regime duration**, so part of the
   AUC is near-definitional rather than predictive of anything actionable.

---

## Terminal classification

```text
POST-CONFIRMATION SCORE PREDICTS FAILURE BUT TOO LATE TO MONETIZE
```

**(Label B.)**

- Not **A** — separation is real and strong: AUC 0.684 → 0.780, precision
  0.68–0.84 against a 0.45 base rate, on complete coverage.
- Not **C** — runner damage is modest (6.0% of ≥2.5 ATR runners touched at
  t=120s/q=0.85) and was never the binding constraint.
- Not **D** or **E** — the placebo removes the entire economic case.

The disqualifying facts are that the median open PnL when the signal fires is
already **−0.20 to −1.04 ATR**, and that the apparent gain from acting on it is
fully explained by exiting early rather than by the signal.

**What this changes for the research program.** The predecessor concluded that
stop room, not signal quality, is the binding constraint on this signal family.
This study tested whether post-confirmation model information could substitute
for stop room, and it cannot: the model tells you the regime is dying only after
the position is underwater, and at that point acting on it is indistinguishable
from acting at random. The open question from the predecessor — whether a wider
stop is affordable — is untouched by this result and remains the more promising
direction.
