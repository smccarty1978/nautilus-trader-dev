# Post-Confirmation Score Deterioration / Runner Protection — Frozen Specification

**Study:** `post_confirmation_score_deterioration`
**Substrate:** `data/canonical/regime_complete_v1/` (REGIME-COMPLETE STORE ACCEPTED)
**Predecessor:** `studies/armed_fade_score_path_progression/` (ARMED SCORE PROGRESSION SUPPORTS REFINEMENT)
**Frozen:** 2026-08-10, after Phase 0 feasibility probes, before Phase 1 implementation.

---

## 0. Objective

After regime confirmation, can causal change in the model score identify trades
that will fail **early enough to preserve meaningful open profit**, without
materially damaging the large regime runners?

This is an **exit / trade-management diagnostic study**. It is not an exit-policy
optimization. A clean negative is a successful outcome.

The unit of analysis begins at the **regime confirmation timestamp**. Pre-confirmation
score state may be retained as frozen context; every explanatory variable must be
observable at or after confirmation.

---

## 1. Phase 0 findings that redefine the study

Three Phase 0 results change what the brief asked for. All are reproduced in
`results/phase0_probe.json`, `phase0_probe2.json`, `phase0_gate1.json`,
`stream_b_coverage.json`.

### 1.1 The polarity is inverted relative to the brief

`bullish_in_domain` is true exactly when `regime_direction == +1` (verified, rate
1.0). After confirmation we hold a position **aligned with** the new regime:
fading a bullish regime SHORT means confirmation is a *bearish* regime starting,
and we are short in a bearish regime. The model whose domain is the new regime
therefore predicts **that regime's own flip** — the end of our position.

```text
domain-model score RISING  = our regime is likely ending = DANGER
domain-model score FALLING = our regime is persisting    = RUNNER
```

**Every event in the brief phrased as a score *retreat* is sign-flipped on the
primary stream.** The deterioration event is score **escalation**. Events are
named `ESCALATION_*` in this study to prevent the sign error from re-entering
through vocabulary. The brief's retreat framing is preserved and tested on the
secondary stream (§1.2 stream C), where it is the correct sign.

### 1.2 Three score streams; one is structurally unusable

The `*_in_domain` flag is a **contract gate** (may this score qualify a trade?),
not an **availability gate** (does a number exist?). Conflating them inverts the
feasibility verdict.

| Stream | Definition | Coverage on the 2,181 failed trades |
|---|---|---:|
| **A** in-domain-flagged score | score where the `*_in_domain` flag is true | **7.7%** |
| **B** domain-model raw *(PRIMARY)* | `bullish_probability` if new-regime direction is +1, else `bearish_probability`, ungated | **100%** |
| **C** other-model raw *(secondary)* | the opposite column, exploratory | ~100% |

**Stream A is excluded, and the reason is structural, not statistical.** The
established-regime gate opens a median 352–448s after confirmation while failed
trades die at a median 217–300s, so the gate never opens before exit for 95.7% of
`CONFIRMED_THEN_STOPPED` and 90.1% of `FINAL_FLIP_EXIT_LOSER`, versus only 30.6%
of winners. **Availability is determined by the outcome.** Any stream-A analysis
compares 159 failures against 1,628 winners on a population selected by having
survived long enough to be scored. Stream A may not be resurrected.

### 1.3 Frozen percentile thresholds do not transfer to stream B

Stream B reads each model **outside its contractual domain**. The number is
causally available at runtime, but the Top-10/5/2.5/1 contracts were calibrated
in-domain and do not apply.

Consequently the brief's events *"loss of Top-1 / Top-2.5 / Top-5 / Top-10"* are
reported **NOT APPLICABLE, with this reason stated**. Inventing new cutoffs would
create a second incompatible threshold definition, which Phase 0 rule 4 forbids.
All stream-B events are therefore **distribution-free**: absolute moves in raw
probability units, and within-trade relative moves.

---

## 2. Landmark design — mandatory

Every diagnostic is evaluated at a **fixed elapsed time from confirmation, among
trades still open at that time**.

This is non-negotiable for two reasons. It is the deployable question — you can
only act on a trade still open. And path-summary statistics over a window ending
at the terminal event are confounded with duration, which has now corrupted a
result in this research line **twice**: the shape classes in the predecessor
study, and Phase 0 probe 1 of this study, where winners' apparently higher peak
score (0.540 vs 0.331) was almost entirely an artifact of observing them for 111
dispatches versus 16 for losers.

**No statistic computed over a window that ends at the terminal event may be used
as a predictor.** Terminal labels are targets only.

Horizons: **60, 120, 180, 300, 600 seconds**.

---

## 3. Population

The 4,705 confirmed armed regimes from the predecessor event table, reconciled
exactly in Phase 0:

```text
CONFIRMED_THEN_STOPPED    822      FINAL_FLIP_EXIT_WINNER  2,350
FINAL_FLIP_EXIT_LOSER   1,359      SESSION_EXIT              174
```

Confirmed via continuation walk 4,705 = Walk A 4,656 + the 49 Walk A
`SESSION_CLOSE_UNRESOLVED` that the continuation walk folds into `SESSION_EXIT`.
New-regime join matched 4,705 of 4,705.

**Failure target** = `CONFIRMED_THEN_STOPPED` + `FINAL_FLIP_EXIT_LOSER` (2,181).
**Winner** = `FINAL_FLIP_EXIT_WINNER` (2,350). `SESSION_EXIT` is excluded from the
AUC target as an artifact of the intraday constraint, and reported separately.

Note for interpretation: *failure* is largely *"the new regime was short-lived"*
(median hold 217–300s vs 960s for winners). Some predictive power is therefore
near-definitional, so the **economic** questions in §5–6 decide this study, not
the AUC.

---

## 4. Frozen conventions

Inherited unmodified; this study defines no second version of any of them.

```text
regime confirmation   the new regime's regime_start_decision_ns, == walk_a_confirm_ns
terminal event        full_exit_ns from the predecessor continuation walk
terminal labels       terminal_label_full, unmodified
ATR                   arm_atr (frozen at the arm) for continuity with the
                      predecessor's PnL; atr_at_confirmation recorded alongside
                      and used for any confirmation-anchored excursion
cost                  2 ticks round-turn = 0.50 points
session               RTH only, forced flat 15:00 CT
direction             +1 LONG / -1 SHORT, == the new regime's regime_direction
```

Open PnL is measured from the **confirmation price** and normalized by ATR. Both
the arm-anchored and confirmation-anchored variants are emitted; every table
states which it uses.

---

## 5. Analyses

**Phase 1** — post-confirmation panel, one row per (trade, dispatch):
timestamp, elapsed seconds, price, stream B and C scores, favorable and adverse
excursion from confirmation, open PnL in points and ATR, running MFE and MAE.
Actual dispatch timing only; **no synthesized observations at missing timestamps**.

**Phase 2** — landmark features on stream B: level, running max/min since
confirmation, escalation from the confirmation score, escalation from the running
minimum, persistence above/below, and causal slope over 15/30/60/120s. Slopes are
computed only where two real dispatches bracket the interval; **no interpolation
across missing dispatches**.

**Phase 3** — price/score divergence: price makes a new favorable extreme while
stream B fails to make a correspondingly lower score (i.e. conviction in the
regime's continuation is not confirming the price move). Simple, interpretable
definitions only; no parameter search.

**Phase 4** — outcome comparison, A+B vs C first, then A and B separately. For
every candidate event: population, occurrence rate overall and per group,
sensitivity, winner-touch rate, and precision. **And the economic state when the
event fires** — median and P25/P75 open PnL ATR, MFE already achieved, giveback
already suffered, remaining MFE after the signal, and time from signal to
terminal. A signal that fires only after the profit is gone is not useful.

**Phase 5 / Gate 2** — runner protection. Winner MFE buckets `<1 · 1–2 · 2–2.5 ·
2.5–3 · >=3 ATR`. For each event: what share of `>=2`, `>=2.5`, `>=3 ATR` runners
does it touch, what MFE remained after the touch, and how often was the
escalation temporary (score recovers, regime continues)?

**Phase 6** — the compact event table.

**Phase 7** — pooled / LONG / SHORT / by year 2021–2025.

**Phase 8** — only if Gates 1 and 2 pass: a small policy simulation of
conceptually distinct actions (immediate exit, tighten stop, wait for failed
recovery, require price confirmation). Existing cost model. No parameter sweep.

---

## 6. Gates

**Gate 1 — information.** PASSED in Phase 0 and recorded here as frozen evidence.
Landmark AUC for failure on stream B `last`: 0.684 / 0.735 / 0.753 / 0.780 at
60 / 120 / 180 / 300s, monotone in horizon, on 100% coverage of failed trades.
Stream C is a corroborating mirror (0.31→0.29, i.e. 0.69–0.71 inverted).

**Gate 2 — runner protection.** If the promising events touch an unacceptable
share of `>=2.5 ATR` runners, STOP and write the negative. There is no
pre-selected cutoff; show the trade-off curve — failed trades saved versus
runners touched, and ATR of giveback avoided versus remaining MFE destroyed.

---

## 7. Deliverables Manifest

Frozen before implementation. The completion gate checks this list literally.

| # | Path | Contents |
|---|---|---|
| 1 | `SPEC.md` | this document |
| 2 | `README.md` | reproduce steps, module map, the three streams, the polarity warning |
| 3 | `REPORT.md` | executive summary answering the brief's 7 questions, then §5 analyses, ending in exactly one §8 terminal label |
| 4 | `CHECKPOINT.md` | resumable state |
| 5 | `results/population_reconciliation.json` | the §3 counts, independently derived |
| 6 | `results/phase0_probe.json`, `phase0_probe2.json`, `stream_b_coverage.json` | stream selection evidence |
| 7 | `results/post_confirm_paths.parquet` | the Phase 1 panel (gitignored; manifest committed) |
| 8 | `results/landmark_features.json` | Phase 2 landmark AUCs and medians by outcome |
| 9 | `results/deterioration_event_table.json` | Phase 6 compact table |
| 10 | `results/escalation_recovery.json` | Phase 2/5 escalation-then-recovery analysis |
| 11 | `results/divergence.json` | Phase 3 |
| 12 | `results/runner_touch.json` | Phase 5 / Gate 2 |
| 13 | `results/stability.json` | Phase 7 |
| 14 | `results/validation_report.json` | the §9 gates, each with `passed`, plus `all_passed` |
| 15 | `results/partition_manifest.json` | conventions, horizons, code hashes |
| 16 | `audit/lint.json`, `audit/status.json`, `audit/contract_status.json` | gate verdicts |

### Terminal decision labels

Exactly one, from the brief. All reachable.

| Label | Condition |
|---|---|
| **A** `POST-CONFIRMATION SCORE HAS NO USEFUL MANAGEMENT INFORMATION` | no landmark feature separates failure from winner beyond AUC ~0.55 |
| **B** `POST-CONFIRMATION SCORE PREDICTS FAILURE BUT TOO LATE TO MONETIZE` | separation exists, but at the median firing time the open PnL and remaining MFE are already at or below what the terminal outcome would have delivered |
| **C** `POST-CONFIRMATION SCORE PREDICTS FAILURE BUT DAMAGES TOO MANY RUNNERS` | separation is timely, but protecting a meaningful share of failures touches an unacceptable share of `>=2.5 ATR` runners |
| **D** `POST-CONFIRMATION SCORE SUPPORTS FURTHER TRADE-MANAGEMENT RESEARCH` | timely separation with a tolerable runner trade-off, but the Phase 8 simulation is not decisive |
| **E** `POST-CONFIRMATION SCORE SUPPORTS A BOUNDED POLICY VALIDATION` | as D, and the Phase 8 simulation shows a positive economic effect stable across both directions and >= 4 of 5 years |

## 8. Domain and completeness

| Dimension | Domain | Rule |
|---|---|---|
| Instrument | NQ `*.v.0` | anything else is out of scope, not missing |
| Years | 2021–2025 | 2026 forbidden; a missing year is a defect |
| Session | RTH only | forced flat 15:00 CT |
| Population | the 4,705 confirmed armed regimes | reconciled, never assumed |
| Score stream | B primary, C secondary | **A excluded, §1.2** |
| Thresholds | none introduced | frozen contracts do not transfer to stream B, §1.3 |
| Horizons | exactly the five in §2 | no tuned horizon |
| 2025 | **NOT threshold-OOS** | inherited disclosure, kept visible in every year table |

## 9. Validation

Written to `results/validation_report.json`, each gate with `passed`, plus
`all_passed`.

```text
 1  population_reconciliation   the four terminal counts derived, not assumed;
                                the 49-trade Walk A delta explained
 2  event_ordering              confirmation <= every observation <= terminal;
                                no confirmation after terminal
 3  no_duplicate_observations   no duplicate (regime, timestamp) score rows
 4  monotonic_events            event timestamps non-decreasing within a trade
 5  independent_recompute       running score peak, escalation magnitude, MFE,
                                MAE and open PnL re-derived by a separate code
                                path on a deterministic sample
 6  session_containment         no observation or event crosses the session close
 7  same_dispatch_ordering      explicit, documented policy for ties
 8  no_terminal_leakage         no predictor reads a window ending at the
                                terminal event; landmark design enforced
 9  audit_gates                 causal_lint clean; lookahead-auditor and
                                contract-checker verdicts machine-read
```

## 10. Non-goals

No retraining, no feature changes, no regime redefinition, no new thresholds, no
2026 data, no modification of the canonical store or any accepted upstream
artifact, no combinatorial event search, no parameter sweep, and no policy
advanced to deployment.
