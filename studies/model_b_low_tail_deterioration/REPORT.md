# Model-B Low-Tail Deterioration Forensic (2024) — Report

**`D3 COMPOSITION / PLACEBO EFFECT`** — 2 of 8 D1 conditions pass.
**Do not train a dedicated multi-year deterioration model.** This branch closes.

`causal_lint` 0 CRITICAL / 0 WARNING. All 8 validation gates pass. 2024 only; 2021,
2022, 2023, 2025 and 2026 were never read. No estimator was constructed anywhere in
this package (gate V3, static AST scan).

---

## The headline

The predecessor's −0.72 ATR reproduces to the seventh decimal. It is still not a
result, for two independent reasons.

**First, 61.6% of it is a fill nobody can get.** The predecessor priced `EXIT NOW` at
the trade's running high-water mark. Repriced at the mark — the only thing that
transacts — the bottom decile goes from **−0.7198 ATR [−1.303, −0.180]** to
**−0.2764 ATR [−0.845, +0.247]**. The property that made it interesting, a confidence
interval excluding zero, does not survive the correction. **No bottom-percentile cut in
this study has a mark-based CI that excludes zero** — pooled, by fold, by side, by rung,
or by time stratum. (Exactly one cell in the whole study does: the disjoint band 50–60,
which is the *middle* of the score distribution, not a tail. See below.)

**Second, there is no deterioration curve.** On disjoint decile bands — the honest
test, because nested cuts share most of their rows and correlate by construction —
Spearman is **−0.0545 with 4 inversions**, and the direction is *improvement*, not
deterioration. The worst band is not the bottom one:

| band (score, worst first) | continue − exit (mark) | continuation success % |
|---|---|---|
| 0–10 | −0.276 | 31.2 |
| 10–20 | **+0.215** | 48.2 |
| 20–30 | −0.211 | 44.7 |
| 30–40 | −0.209 | 55.3 |
| 40–50 | +0.119 | 48.2 |
| **50–60** | **−0.516** | 58.9 |
| 60–70 | +0.016 | 53.2 |
| 70–80 | −0.196 | 51.8 |
| 80–90 | −0.342 | 44.7 |
| 90–100 | −0.146 | 48.2 |

The single worst decile for continuing is band **50–60** — the middle of the
distribution — at nearly twice the bottom decile's disadvantage, and it is the *only*
cell in this study whose mark-based CI excludes zero ([−0.829, −0.176]). A model whose
one statistically distinguishable harmful state sits at its median score, while its
lowest scores do not, is not ranking deterioration.

There is one genuinely monotone column, and it is instructive: continuation success
falls cleanly from 48.4% (all) to 8.6% (bottom 2.5%). **The model orders the barrier
label and does not order the money.** That is the fourth independent replication of
`post_confirm_state_predicts_scale_not_sign`, arriving this time as label-versus-value
rather than scale-versus-sign.

---

## Answers

**1. Is the bottom-decile −0.72 ATR reproduced exactly? Yes — all 14 lineage
quantities.** −0.7197866 (δ 3.3e−08), CI [−1.3032425, −0.1799056] (δ 4.4e−08),
baseline 48.4397163%, 2,991 observations / 781 trades, all six per-rung counts exact.
The analysis population is the 1,410-observation / 380-trade OOS subset; the brief's
own baseline is exactly 683/1410, which confirms it.

**2. Broad monotonic deterioration curve? No.** Spearman −0.0545, 4 inversions,
direction *improvement*. The nested-cut Spearman on the HWM basis is −0.915, which
looks impressively monotone and is an artifact of overlap plus the HWM fill; on
disjoint bands the same quantity is +0.103 with 4 inversions.

**3. Where does deterioration become economically meaningful? Nowhere it can be
relied on.** Bottom-10 is −0.276 against a population −0.155 — a delta of −0.122,
below the 0.15 ATR materiality bar, with a CI spanning zero. Bottom-5 is *less*
negative (−0.213) than bottom-10, and bottom-2.5 less again (−0.051). The effect does
not intensify as the score worsens.

**4. Both temporal folds? Directionally yes, and the agreement is hollow.** At
bottom-10: FOLD_1 −0.178, FOLD_2 −0.375. Same sign — this is one of only two D1
conditions that pass. But the *populations* disagree by 0.64 ATR (FOLD_1 **+0.157**,
FOLD_2 **−0.479**), so the two folds are not measuring the same world, and within
FOLD_1 the tail is **positive** at bottom-25 (+0.207) and bottom-20 (+0.053), negative
only at bottom-10, then positive again at bottom-5 (+0.083). Exactly one cut works in
FOLD_1. Per the brief's own rule, that is suspicion, not evidence.

**5. LONG and SHORT? They invert, which the brief names a major warning.**

| cut | LONG | SHORT |
|---|---|---|
| ALL | +0.106 | −0.349 |
| bottom 25 | **+0.519** | −0.461 |
| bottom 20 | **+0.637** | −0.447 |
| bottom 10 | **+0.312** | −0.288 |
| bottom 5 | +0.139 | **+0.233** |

On the LONG side the low tail is *better* than the population at every cut — the
opposite of deterioration. The pooled −0.72 is a SHORT-side effect wearing a pooled
label, and even SHORT flips positive at bottom-5.

**6. Survive rung composition? No.** Low-tail economics relative to each rung's own
baseline, at bottom-10: rung 1.0 −0.453 (vs −0.111, real), 1.5 −0.579 (vs −0.160),
2.0 **+0.348** (vs −0.136, inverted), 2.5 −0.126 (vs −0.133, flat), 3.0 −0.165 (vs
−0.194, flat), 4.0 **+0.306** (vs −0.316, inverted, and `UNDERPOWERED` at 11 trades).
The effect lives at rungs 1.0–1.5 and reverses at 2.0. It is which rung the trade
occupies, not deterioration within one.

**7. Survive time-since-confirm composition? No — and this is the cleanest kill.**
Within the frozen terciles, bottom-10 is **positive** in two of three:

| stratum | ALL | bottom 10 |
|---|---|---|
| T1 (≤10 s) | −0.090 | **+0.216** |
| T2 (10–194 s) | −0.156 | −0.007 |
| T3 (>194 s) | −0.222 | **+0.030** |

Once trade age is held fixed, the low tail carries no disadvantage at all. The pooled
effect is age composition — and not in the direction the brief anticipated. The low
tail is not old trades, it is **young** ones: 68.1% of bottom-decile observations sit
at `seconds_since_confirm == 0`, against 27.0% of the population; median age collapses
from 75 s to 0 s.

**8. Outperform drawdown-from-HWM alone? Narrowly, and inside the noise.**
ML vs the better direction of C4 — bottom-25 −0.279 vs −0.211, bottom-20 −0.314 vs
−0.278, bottom-10 −0.424 vs −0.365, bottom-5 −0.224 vs −0.164. The ML trigger wins all
four by 0.03–0.07 ATR with entirely overlapping CIs, while **sharing 64–75% of its
triggered trades with the pure drawdown rule**. Score-versus-drawdown Spearman is
**−0.483**, the strongest relationship in the study.

**9. Outperform matched random/placebo exits? No.** It beats C1 random-matched at all
four cuts, but loses at the two cuts where the claimed effect lives: at **bottom-10**
`C2_RUNG_ONLY_DESC` reaches −0.452 against ML's −0.424; at **bottom-5** both
`C2` (−0.235) and `C3_TIME_SINCE_CONFIRM_DESC` (−0.324) beat ML's −0.224. A
single-variable threshold rule with no model in it does the job at least as well.

> **Audit correction, disclosed.** Pass 1 of `lookahead-auditor` found these controls
> selected each trade's *global extreme* observation — hindsight the ML trigger does
> not get, and the accepted `running_extremum_mechanically_contains_eventual_extremum`
> defect applied to a control. It flattered them badly: `C3_DESC` at bottom-25 read
> −1.0992 before the fix and −0.1238 after. The controls are now causal threshold
> rules. The verdict did not change; the reasoning did, and the pre-correction numbers
> should not be quoted.

**10. What happens as the adverse barrier widens? Discrimination gets *worse*, not
better.** Frozen predictions scored against each frozen target at 300 s:

| adverse | base rate | AUC | AUC (resolved only) |
|---|---|---|---|
| **0.50** | 36.10% | **0.5602** | **0.5610** |
| 0.75 (primary) | 48.44% | 0.5322 | 0.5317 |
| 1.00 | 55.67% | 0.5414 | 0.5449 |
| 1.25 | 59.50% | 0.5395 | 0.5450 |

The model is at its best against the **tightest** barrier and its worst against the
one it was trained on. Widening to −1.00 or −1.25 raises the base rate but does not
clean the model up. (These AUCs measure whether the *existing* ranking happens to order
a different question better; retraining was forbidden, so they are not what a model
fit on those targets could achieve.)

**11. Is +0.50/−0.75 simply too tight relative to normal runner behaviour? No.** The
premise was reasonable and the data refuses it. If the model were finding genuine
deterioration and the tight barrier were merely catching normal retracement,
discrimination would rise as the barrier widened. It falls. The −0.50 barrier — the
one most contaminated by ordinary noise — is where the model looks best, which points
at near-term volatility rather than trade failure.

**12. What does the model actually identify? Drawdown-from-HWM, plus near-term
volatility.** Standardised mean differences at bottom-5: `drawdown_from_hwm_atr`
**+3.18** (0.130 → 0.663 ATR, 5.1×), `rung_overshoot_atr` +1.43, `exit_score_now`
+1.24, `seconds_since_last_favourable_extreme` +1.18, `realized_vol_60s_atr` +0.83.
Nothing else is close. Combined with the 64–75% trigger overlap with the pure drawdown
rule and the −0.483 score-drawdown correlation: the low tail is *"price is well off its
high, usually right at confirmation, in a fast tape."* It is not genuine deterioration,
it is not age, it is not rung — it is **drawdown**, which is also what the HWM-anchored
adverse barrier measures. The model is partially restating its own label.

**13. Under first-trigger-per-trade, how many trades get a signal?** bottom-25: **190
trades (50.0%)**; bottom-20: 152 (40.0%); bottom-10: 78 (20.5%); bottom-5: 36 (9.5%).
Median age at trigger is 0–1 s and 55–83% of triggers land on rung 1.0.

**14. What fraction of major runners would it intercept? Enough to be disqualifying.**

| cut | ≥3 ATR runners cut | ≥4 ATR runners cut |
|---|---|---|
| bottom 25 | **63.4%** | **63.3%** |
| bottom 20 | 49.7% | 52.3% |
| bottom 10 | 25.5% | 26.6% |
| bottom 5 | 10.6% | 9.2% |

At bottom-25 the rule fires on half the trades and destroys nearly two-thirds of the
≥3 ATR runners — it is *more* likely to hit a runner than a random trade.

**15. What fraction of eventual bad outcomes would it catch? Fewer than the good
ones.** Losers intercepted 38.0 / 32.0 / 19.3 / 8.0% at bottom-25/20/10/5; winners
intercepted **57.8 / 45.2 / 21.3 / 10.4%**. At the two widest cuts the signal is
anti-selective, and at the two tightest it is indistinguishable from firing at random
with respect to outcome.

**16. Final classification: `D3 COMPOSITION / PLACEBO EFFECT`.** Two conditions pass
(`both_folds`, `sample`); six fail (`monotonic`, `tail_material`, `both_sides`,
`rung_control`, `time_control`, `beats_placebo`). D3 dominates D2 by the SPEC's routing
rule: an underpowered effect that composition and a placebo already explain is a
composition effect, not a power problem.

**17. Should we train a dedicated multi-year deterioration model next? No.** Not on
this target, this label geometry, or this state representation. The compact
15–30-feature architecture the brief sketched would be built on the finding that the
low tail is economically interpretable — and it is, but what it means is
`drawdown_from_hwm_atr`, a single feature already in the set, already beatable by a
one-line threshold rule, and already most of what the HWM-anchored adverse barrier
measures. More years would estimate that circularity more precisely.

---

## What a low score physically means (Phase 7)

Of the brief's five candidate readings, the answer is **D — deep retracement, often
followed by recovery** — with the important qualifier that the adverse move is not
forecast, it is *already underway at the observation instant*.

Every median below is **resolved-only** — computed on the observations where the event
actually occurred — so each is paired with its resolution rate on the line above it. An
unpaired median in this table would be unreadable, because the resolution rate itself
moves by 24 points across the cuts.

| | ALL | bottom 20 | bottom 10 | bottom 5 |
|---|---|---|---|---|
| P(−0.50 adverse) | 81.0% | 86.5% | 94.3% | **98.6%** |
| └ median s to −0.50, given it happens | 23 | 6 | **1** | **1** |
| P(−1.00 adverse) | 57.2% | 64.2% | 71.6% | 82.9% |
| └ median s to −1.00, given it happens | 79 | 44 | 17 | 3 |
| P(new favourable extreme) | 89.3% | 80.5% | 71.6% | **65.7%** |
| └ median s to new extreme, given it happens | 3 | 8 | 17 | 27.5 |
| fwd MFE 300 median | 0.821 | 0.717 | 0.746 | 0.779 |
| fwd MAE 300 median | 1.172 | 1.422 | 1.597 | 1.597 |
| median final return | 1.430 | 1.291 | 0.843 | 0.552 |
| % of windows reaching the full 300 s | 77.7% | 70.2% | 67.4% | 55.7% |

The adverse barrier arrives in **one second** at the bottom decile. That is not
prediction, it is measurement of a move in progress. Yet two-thirds still make a new
favourable extreme afterwards, and forward MFE barely moves across cuts while forward
MAE rises 36%. Not collapse (A), not stagnation (B), not exhaustion (E). And even at
bottom-5 the trade is still worth **+1.24 ATR** held to accepted management against
**+1.46 ATR** exited — the "deterioration" is giving back 0.22 ATR on a profitable
trade.

**Censoring caveat.** The low tail is measured over systematically shorter windows —
the share reaching the full 300 s falls from 77.7% to 55.7%, and the share with no new
favourable extreme rises from 10.7% to 34.3%. The favourable timings are therefore
optimistic in the tail: the third of bottom-5 observations that never make a new high
contribute no value to the 27.5 s median. The adverse timings are unaffected in
direction — a 1-second median cannot be produced by truncation, and 98.6% of the
bottom-5 population resolves.

**Underpowered cells.** Per SPEC §8, the trade-clustered CI is suppressed wherever a
cell rests on fewer than 20 unique trades — `bottom_2_5` pooled (17 trades) and the
rung-3.0 / rung-4.0 bottom-10 cells (16 and 11). The point estimates are published with
their counts visible and stamped `UNDERPOWERED`; no verdict rests on them.

## Verification

| gate | result |
|---|---|
| V1 SEAL | PASS — inputs are frozen predecessor artifacts; all timestamps in 2024 CT |
| V2 LINEAGE | PASS — 14/14 quantities, worst δ 4.4e−08 |
| V3 NO REFIT | PASS — static AST scan, 0 estimator constructions in 11 files |
| V4 POPULATION | PASS — 1,410 obs / 380 trades |
| V5 DISJOINT BANDS | PASS — 10 bands, sum 1,410, pairwise overlap 0 |
| V6 FIRST TRIGGER | PASS — uniqueness and minimality, minimality recomputed by an independent code path |
| V7 TIMING REDERIVATION | PASS — **0 mismatches** across 53,838 re-derived quantities (6 geometry × 12 labels over 2,991 rows) |
| V8 PLACEBO MATCH | PASS — every control count-matched exactly, 0 deficit |

## What remains unproven

- **Whether 2024 is representative.** 1,410 observations over 380 trades. A D4 label
  would overclaim; the controls, not the sample size, are what produce D3.
- **Whether a mark-anchored barrier behaves differently.** Every frozen label is
  HWM-anchored, which is why the adverse leg and the dominant feature are near-duplicates.
  A barrier measured from the mark was never built and is the one structural change
  that would make this question non-circular.
- **Whether the LONG-side positive tail is real.** LONG's low tail beats its own
  population at every cut. On 171 trades that is far more likely noise than a finding,
  but it was not chased, and chasing it would be optimisation.
- **What a model trained on the −0.50 barrier would do.** Retraining was forbidden.
  The frozen ranking orders that target best, which is suggestive of a volatility
  signal rather than a deterioration one — untested, not disproven.

---

**Terminal label: `D3 COMPOSITION / PLACEBO EFFECT`**
