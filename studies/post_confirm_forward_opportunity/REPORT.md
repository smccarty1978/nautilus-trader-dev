# Post-Confirmation Forward Opportunity / Continuation Value — Report

**Study:** `post_confirm_forward_opportunity` · 2026-08-11
**Population:** 8,950 original Top-10 entries → 4,656 measurable confirmed →
**140,929 causal post-confirmation observations**
**Predecessor:** `top10_fast_confirm_runner_path` (verdict C)

---

## Executive summary

**The forward opportunity map is flat, and one of the predecessor's headline
findings does not survive contact with a causally implementable control.**

Three results, in order of confidence.

**1. The causal state predicts the SCALE of what remains, never its SIGN.**
Every state variable that lowers forward MFE lowers forward MAE by almost
exactly the same factor:

```text
stall bucket   n_obs    fwd MFE   fwd MAE   ratio   P(+0.50 b -0.50)   P(another extreme)
                        (median)  (median)          resolved races
0-15          27,778     1.455     1.172    1.241        0.4926              0.877
16-30         14,031     1.361     1.091    1.248        0.4960              0.769
31-45         11,164     1.294     1.047    1.237        0.4969              0.715
46-60          9,534     1.241     0.988    1.257        0.5018              0.668
61-90         15,560     1.146     0.932    1.229        0.5170              0.613
91-120        12,701     1.019     0.878    1.161        0.5135              0.553
>120          50,161     0.893     0.789    1.131        0.5139              0.475
```

Forward MFE falls 39% across the stall axis and `P(another favorable extreme)`
falls from 0.877 to 0.475 — **monotone in 5 of 5 years and on both sides.** That
information is real. But the ratio only moves from 1.24 to 1.13, and the
directional race is a coin flip at every stall length. **A long stall does not
mean the trade is about to go against you; it means less of everything is about
to happen.**

**2. Continuation value is indistinguishable from zero everywhere.** Across
**220 candidate state regions**, `E[continue − exit now]` never reaches the
frozen −0.10 ATR bar in a region that also has unfavorable forward geometry. At
trade level, **all 79 buckets** have a trade-clustered 95% CI spanning zero.
The decision gate is **closed**: 0 of 220 regions clear all eight conditions,
and the best any region achieves is 6 of 8.

**3. "A random exit beats the natural exit" was knowledge of the trade's
length.** This is the correction that matters most for the program:

```text
                                     mean ATR/trade   vs opposing flip
opposing-flip natural exit               0.884              —
random exit, LIFETIME-UNIFORM            1.502           +0.618
random exit, LENGTH-BLIND                0.895           +0.011
```

The predecessor's indictment of the baseline — *"a coin-flip exit beats the
natural exit by up to half an ATR"* — was measured with a draw taken uniformly
over `[confirm, terminal)`, which requires knowing where the terminal is. Draw
the exit from a fixed grid instead, so the rule cannot know how long the trade
will live, and **the entire edge evaporates: +0.618 → +0.011.** On ≥3 ATR
runners the causally implementable version is **−0.848 ATR**.

---

## 1. Phase 0 — reconciliation

| Quantity | Observed | Accepted | Pass |
|---|---:|---:|:--:|
| Original Top-10 entries | 8,950 | 8,950 | ✅ |
| Confirmed | 4,705 | 4,705 | ✅ |
| Stopped before confirmation | 4,245 | 4,245 | ✅ |
| Measurable in panel | 4,656 | 4,656 | ✅ |
| Non-measurable confirmed | 49 | 49 | ✅ |
| Giveback pool / original entry | **0.898083** | 0.898 | ✅ |
| Baseline net / original entry | **−0.076530** | −0.0765 | ✅ |

The population is the **full** measurable confirmed set — no confirmation-speed
filter. Speed is carried as a diagnostic column only.

---

## 2. Phase 1 — the observation grid, and honest attrition

140,929 dense observations from 4,656 trades. The denominator is **constant at
4,656** in every time-indexed table; alive/terminal/attrition are reported, never
implied.

```text
offset   alive  attrition%  alive_stop_live   fwd MFE   fwd MAE   mean CV   P(≥3 ATR)
   15s   4,656      0.0          4,654         1.283     1.111    -0.030      0.374
   60s   4,653      0.1          4,591         1.220     1.023    -0.015      0.374
  120s   4,582      1.6          4,398         1.111     0.941    -0.010      0.380
  300s   3,649     21.6          3,431         1.054     0.895    -0.013      0.469
  600s   2,300     50.6          2,154         1.018     0.946    -0.061      0.667
```

The rising `P(≥3 ATR)` column is the survivorship structure made visible: late
observations are a *different population*, not a later view of the same one. This
is why the SPEC forbids pooling the sparse extended horizon (+900…+2400 s, in
`extended_horizon_summary.parquet`) into any primary table — by +2,400 s only 162
trades remain, 96.5% attrition.

---

## 3. Phases 3–4 — the forward barrier geometry is a driftless random walk

Pooled over all 140,929 observations, barriers measured from the **current
price**:

```text
race                  P(fav)   P(adv)   P(unres)   P(fav | resolved)   median s to +   to -
+0.25 before -0.25    0.485    0.491     0.023          0.497                18       19
+0.50 before -0.50    0.483    0.472     0.045          0.506                52       58
+1.00 before -0.75    0.403    0.502     0.095          0.445               142      100
+1.50 before -1.00    0.356    0.436     0.208          0.450               249      140
+0.50 before -0.25    0.329    0.644     0.027          0.338                52       19
+1.00 before -0.50    0.321    0.625     0.054          0.339               142       58
+1.50 before -0.50    0.240    0.692     0.068          0.258               249       58
```

Every **symmetric** race sits at ≈0.50 on resolved outcomes. Every **asymmetric**
race sits at approximately the ratio the barrier distances imply. That is the
signature of a driftless random walk in ATR units. From a generic post-confirm
state, forward MFE is a median **1.153 ATR** against forward MAE **0.940**, and
the median time to the forward peak is 192 s against 158 s to the forward trough.

Same-bar barrier collisions: **400** across 1.4M race evaluations, resolved
adversely; the optimistic bound is carried on every race table and moves nothing
(e.g. 0.4828 → 0.4832 on `+0.50/−0.50`).

---

## 4. Phases 5–9 — every map is flat in the direction that matters

**Phase 6, recent 60 s progress** — the axis the predecessor identified as its
central mechanism:

| progress | n_obs | fwd MFE | fwd MAE | P(+.50 b −.50) | P(another extreme) | mean CV |
|---|---:|---:|---:|---:|---:|---:|
| STRONG_NEG | 40,246 | 0.768 | 0.724 | 0.447 | 0.406 | −0.011 |
| NEG | 16,995 | 1.104 | 0.903 | 0.492 | 0.589 | −0.014 |
| FLAT | 9,355 | 1.217 | 0.933 | 0.509 | 0.648 | +0.005 |
| POS | 17,315 | 1.230 | 0.992 | 0.499 | 0.691 | −0.032 |
| STRONG_POS | 43,050 | 1.452 | 1.130 | 0.499 | 0.805 | −0.006 |

Progress moves `P(another extreme)` from 0.41 to 0.81 and forward MFE by 89% —
and moves the directional race by 0.05 and continuation value by 0.04 ATR.

**Phase 7, progress × stall (12 cells).** `P(+0.50 before −0.50)` spans
**0.4328 → 0.5124**. Continuation value spans −0.094 → +0.039.

**Phase 8, MFE × stall (16 cells).** The question was whether the same stall
means something different at +0.5 vs +3 ATR. For *scale*, yes — at a >90 s stall
forward MFE is 0.765 in the `<1 ATR` bucket and 1.120 in the `≥3` bucket. For
*direction*, no: `P(+0.50 before −0.50)` spans 0.4540 → 0.5224 with no
interaction pattern.

**Phase 9, drawdown (20 cells).** `P(+0.50 before −0.50)` spans 0.4502 → 0.5167;
continuation value −0.090 → +0.018. Conditioning drawdown on stall does not
rescue it. The predecessor's conclusion — *giveback is the wrong axis* — is
confirmed, and this study extends it: **there is no right axis.**

---

## 5. Phase 10 — the continuation-value distribution, and why the mean is zero

At trade level, with trade-clustered 95% CIs (SPEC D8 — one observation per trade
per bucket, the first entry into it):

| bucket | trades | mean CV | median CV | 95% CI | P(continue is worse) |
|---|---:|---:|---:|---|---:|
| stall 0–15 | 4,638 | −0.030 | −0.740 | [−0.093, +0.032] | 0.668 |
| stall >120 | 3,945 | −0.015 | −0.544 | [−0.077, +0.044] | 0.686 |
| MFE <1 | 1,617 | −0.047 | −0.752 | [−0.145, +0.053] | 0.709 |
| MFE ≥3 | 1,288 | −0.026 | −0.629 | [−0.157, +0.116] | 0.639 |
| drawdown <0.25 | 3,931 | −0.037 | −0.755 | [−0.105, +0.030] | 0.656 |
| drawdown ≥0.75 | 4,582 | −0.004 | −0.602 | [−0.060, +0.055] | 0.691 |

**All 79 buckets span zero.** The mean CV range across every bucket in the study
is [−0.089, +0.046] ATR.

The structure worth understanding is the gap between the median (≈ −0.6 ATR) and
the mean (≈ 0). **Continuing is worse about two-thirds of the time, in every
state** — `P(continue is worse)` spans only 0.620 to 0.709 across all 79 buckets
— and the remaining third pays for all of it. That constant is a property of the
return distribution, not a signal: there is no state you can stand in where the
odds of "should have exited" are meaningfully better or worse than 2:1.

This is the same structure that killed every rule in this program's history. A
rule that harvests the two-thirds necessarily surrenders the third, and the third
is exactly the same size.

---

## 6. Phase 11 — why a random exit beat the natural exit, resolved

The predecessor's placebo drew an exit index uniformly from `[confirm, terminal)`.
That distribution's **support depends on the realised trade length**. Long trades
are the runners; a uniform draw over a long window lands, on average, deep inside
a large favorable excursion. The draw never *looks at* the outcome — but it knows
how much time there is.

Replacing it with a **length-blind** draw (an offset from the frozen dense grid;
if the offset lands past the terminal, the trade was already over and the natural
exit stands) removes that knowledge and nothing else:

```text
slice            flip     uniform   blind    Δ uniform   Δ blind
POOLED          0.884      1.502    0.895      +0.618     +0.011
LONG            0.895      1.493    0.878      +0.598     −0.017
SHORT           0.874      1.509    0.909      +0.634     +0.034
2021            0.736      1.413    0.798      +0.677     +0.062
2025            1.011      1.574    0.969      +0.563     −0.042
R0  (<1 ATR)   -0.875     -0.043   -0.615      +0.832     +0.260
R3  (≥3 ATR)    2.878      2.955    2.030      +0.077     −0.848
STOP           -1.000      0.181   -0.470      +1.181     +0.531
```

The length-blind exit is worth **+0.011 ATR/trade** pooled and flips sign by year
and by side. It wins on trades that were going to be stopped (+0.531) and loses
catastrophically on runners (−0.848) — the two effects cancel almost exactly.

**Is the opposing flip late? Descriptively, yes: a median 238 s and a mean 2.141
ATR of giveback separate the favorable peak from the exit. Economically, that
lateness is not recoverable by any exit chosen without knowing the future** — not
by chance, and not by any of the 220 causal state regions tested here.

---

## 7. Phase 12 — the ladder is real, memoryless, and nearly worthless

The path *is* shaped like a ladder, and remarkably so:

| rung | achieved | P(next +0.5) | P(next +1.0) | MAE before next (med / p75 / p90) | median s |
|---:|---:|---:|---:|---|---:|
| 1.0 | 89.3% | 0.807 | 0.647 | 0.304 / 0.691 / 1.198 | 51 |
| 1.5 | 72.1% | 0.801 | 0.635 | 0.359 / 0.814 / 1.335 | 58 |
| 2.0 | 57.8% | 0.792 | 0.647 | 0.351 / 0.731 / 1.282 | 52 |
| 2.5 | 45.8% | 0.815 | 0.654 | 0.358 / 0.805 / 1.459 | 57 |
| 3.0 | 37.4% | 0.801 | 0.650 | 0.336 / 0.784 / 1.327 | 49 |
| 4.0 | 24.4% | 0.804 | 0.670 | 0.326 / 0.740 / 1.187 | 39 |

`P(next +0.5 rung)` is **0.79–0.81 at every rung**, and across all 30 rung × year
cells it spans only **0.756–0.851**. This is a genuinely memoryless ladder — the
odds of the next half-ATR do not care how far the trade has already run.

**But harvesting on it does not pay** (`harvest_control.parquet`, 20 draws/trade,
seed 20260811, one round turn charged per unit so the per-unit cost is identical
to holding full size):

```text
rung   Δ rung/trade   Δ uniform   Δ blind   edge vs uniform   edge vs blind   Δ/original entry   % of pool
1.0      -0.0553       +0.2948   -0.0117       -0.3501         -0.0436          -0.0254          -2.83%
2.0      -0.0062       +0.1799   -0.1644       -0.1861         +0.1582          -0.0018          -0.20%
3.0      +0.0115       +0.0252   -0.4470       -0.0136         +0.4585          +0.0022          +0.24%
4.0      +0.0404       -0.1683   -0.8036       +0.2087         +0.8440          +0.0050          +0.56%
```

Rung harvesting is **negative at rungs ≤2.5**, loses to the lifetime-uniform
control at rungs 1.0–3.0, and at its best (rung 4.0) is worth **+0.0050 ATR per
original entry — 0.56% of the 0.898 ATR giveback pool.** Structurally
interesting; economically inert.

---

## 8. Phase 13 — the model score, and a near-miss worth documenting

Within the matched `NEGATIVE progress × >90 s stall` cell, splitting on the raw
new-regime score at the **within-cell** median appeared to produce the largest
separation in the entire study — `P(+0.50 before −0.50)` of **0.372 (high) vs
0.494 (low)**, a 0.121 gap, **5 of 5 years and both sides**, on 16,701
observations per half. That clears the SPEC label-F bar (≥0.05) comfortably.

It is an artifact, and three independent checks say so:

1. **The halves are not matched.** Median remaining lifetime is **105 s** for the
   high half versus **375 s** for the low half. Median return from entry: +0.016
   vs +1.040 ATR. The "matched cell" is far too wide.
2. **The gap is entirely unresolved races.** Unresolved share 0.300 (high) vs
   0.027 (low). On **resolved** races the high half is *more* favorable —
   **0.5316 vs 0.5071**. Races near a terminal do not resolve; that is all the
   0.121 was.
3. **A within-trade demeaned split inverts the sign.** Removing between-trade
   variation entirely: high 0.4744 vs low 0.3881, the opposite ordering, and mean
   CV +0.276 vs −0.278. The pooled result was Simpson's paradox on trade
   composition.

**The score is reading remaining regime lifetime, not forward direction.** It
adds nothing beyond price state. It remains EXPLORATORY_OUT_OF_DOMAIN.

This near-miss is also the reason `p_favorable_of_resolved` and the unresolved
share are carried on every race table in this study. Without them the finding
would have been reported as real.

---

## 9. Phase 14 — the decision gate

220 candidate regions (contiguous unions on six single axes and three crossed
maps) × 8 conditions. **0 regions pass. Maximum achieved: 6 of 8.** Every
near-miss fails condition 1 (continuation value).

```text
region                                   n_obs   trades  passed  fails  mean CV   P(+.5 b -.5)
mfe x stall4 : 1-2 x >90                25,951    2,321    6/8     c1    -0.0658     0.4596
mfe x stall4 : 1-2 x 61-90 + >90        32,400    2,612    6/8     c1    -0.0612     0.4667
mfe x stall4 : 1-2 x 31-60+61-90+>90    40,861    3,019    6/8     c1    -0.0568     0.4704
```

**The two substantive conditions are anti-correlated and never co-occur:**

- Most negative continuation value found anywhere: **−0.1027** (`MFE ≥3 × stall
  61–90`) — which has the study's **most favorable** forward geometry (0.5235),
  covers 2.1% of observations, and is **100% ≥3 ATR runners**. It is not a state
  where a trade is dying; it is a state where a large runner is pausing.
- Most unfavorable forward geometry found anywhere: **0.4421** (`NEGATIVE
  progress × >90 s stall`, 30,594 obs / 4,168 trades) — whose continuation value
  is **−0.0005 ATR**. Exactly nothing.

The state space cleanly separates "where little happens next" from "where money
is lost by staying". Only the first exists.

**No architectures were built.** SPEC §8 routes a closed gate to a descriptive
label with no policy manufactured. The harvest family was adjudicated with a
placebo **control** rather than an architecture, so label C could be ruled out on
evidence (§7) instead of on a routing technicality.

---

## 10. Validation

All 14 SPEC §9 gates pass (`validation_report.json`).

The load-bearing one is gate 8. State and forward labels were recomputed from the
raw 1s parquet, independently of the engine's array construction, on **two
separately truncated slices**: state from an array hard-truncated **at** the
observation bar, labels from an array beginning at observation bar **+1**.

```text
trades sampled                300
observation states checked  8,671
state fields                    7   ret, run_mfe, run_mae, drawdown,
                                    mfe_since_confirm, n_new_extremes, stall_s
label fields                    4   fwd_mfe, fwd_mae, another_extreme, race
mismatches                      0
boundary violations             0
```

Both directions of the causal boundary are therefore proved by construction: a
state that read a later bar could not match a slice that lacks it, and a label
that read the observation bar could not match a slice that begins after it.

Gate 9 additionally verifies that `exit_now + continuation == natural return` on
the mark basis and both fill bases, at **all 140,929 observations**, to 1e−9.

`causal_lint` 0 CRITICAL / 0 WARNING over 14 files. 26 deterministic tests pass.
`lookahead-auditor` pass 1: **0 CRITICAL**.

---

## 11. Defects and contract issues found during this study

| # | Issue | Found by | Resolution |
|---|---|---|---|
| 1 | Barrier-race probabilities computed on all observations conflate "adverse" with "never resolved"; the unresolved share rises from 0.0004 to 0.0975 across the stall axis purely because late observations sit nearer their terminal | own review of Phase 5 output | `p_favorable_of_resolved` and the unresolved share added to every race table. This reversed the sign of the stall finding: the resolved-only rate *rises* 0.4926 → 0.5139 |
| 2 | Phase 13 model-score separation (0.121, 5/5 years) is composition, not signal | own confound check before the verdict was written | Three-way diagnosis (§8); label F rejected |
| 3 | The predecessor's lifetime-uniform placebo uses the realised trade length | own design of Phase 11 | Length-blind companion added; it is the causally implementable benchmark and the gap is reported as a primary finding |
| 4 | **SPEC contract defect:** §6 defines label **C** (staged harvesting) with a condition that does not require the §8 gate, but §8 routes a closed gate only to D/E/F/G — making C unreachable whenever the gate closes | own review after the gate ran | Honored the frozen routing (no policy manufactured) and adjudicated C with a placebo **control** so it is ruled out on evidence. Recorded here rather than amended, because amending a frozen SPEC after seeing results is how a verdict gets manufactured |
| 5 | **SPEC contract defect:** label **D**'s frozen condition ("large positive `random − opposing_flip`" **and** no region clears §8) is *literally satisfied*, but the study's own Phase 11 shows that quantity is non-causal | own review at classification time | Did not route to D; see §13 for the explicit reasoning |
| 6 | A test fixture asserted UNRESOLVED on a bar whose low was a genuine adverse touch | own test run | Fixture corrected; the engine was right |
| 7 | `extended_horizon.parquet` (Manifest #13) had no CSV mirror | `contract-checker` W1 | Mirror now written by the pipeline, not by hand |
| 8 | `decision_gate.parquet` was wide (one row per region) rather than the Manifest's literal `condition, value, threshold, passed` | `contract-checker` W2 | `decision_gate_conditions.parquet/.csv` added in the exact long form (1,760 rows); the wide table is retained because the report cites per-region context the long form drops |
| 9 | §7 partition completeness was *inferred* from no slice coming back empty, so a genuinely empty partition would have been dropped silently | `contract-checker` N1 | 15th validation gate added asserting the 10-cell year × side grid against an explicit expected set and all 40 dense offsets with `alive > 0`. SPEC §9 amendment recorded; it is a tightening and it passes |

---

## 12. The sixteen questions

**1. From a generic live post-confirm state, how much favorable opportunity
remains?** Forward MFE median **1.153** ATR (mean 1.944) against forward MAE
median **0.940** (mean 1.039) — a median ratio of 1.23. Median time to the
forward peak 192 s, to the forward trough 158 s.

**2. How does forward MFE decay with time since the last favorable extreme?**
Monotonically, **1.455 → 0.893 ATR** (−39%) from a 0–15 s to a >120 s stall.
Monotone in 5/5 years and 2/2 sides.

**3. How does forward MAE change at the same time?** It decays with it:
**1.172 → 0.789** (−33%). The ratio moves only 1.24 → 1.13.

**4. At what stall durations does `+0.50 before −0.50` fall below 50%?** On a
like-for-like basis, **never** — the resolved-race rate *rises* 0.4926 → 0.5139.
The apparent decay (0.4924 → 0.4637) is the unresolved share rising from 0.04%
to 9.75% as observations sit closer to their own terminal.

**5. At what states does `+1.00 before −0.50` become unlikely?** It is unlikely
in **every** state and equally so: 0.281–0.357 across all progress × stall,
MFE × stall and drawdown × stall cells. That is the price of asking 2:1 odds on
a driftless path.

**6. Does recent directional progress materially improve those odds?** No.
STRONG_NEG → STRONG_POS moves `P(+0.50 b −0.50)` only 0.447 → 0.499, while
moving `P(another extreme)` 0.406 → 0.805 and forward MFE 0.768 → 1.452.
Progress is a volatility and activity forecast, not a direction forecast.

**7. Does current accumulated MFE change the meaning of a stall?** For scale,
yes (at a >90 s stall, forward MFE 0.765 at `<1 ATR` vs 1.120 at `≥3`). For
direction, no — 0.454–0.522, no interaction.

**8. Does drawdown become informative once combined with stall/progress?** No.
20 crossed cells: geometry 0.450–0.517, continuation value −0.090 to +0.018.

**9. Where does `E[continue − exit now]` become materially negative?**
**Nowhere.** Range across all 79 trade-level buckets: [−0.089, +0.046] ATR, and
every 95% CI spans zero. The most negative region in 220 candidates is −0.1027,
covering 2.1% of observations and consisting entirely of ≥3 ATR runners.

**10. Is that negative region stable by year and direction?** Not applicable —
there is no region. The gate's year and direction conditions were evaluated on
every candidate anyway; the binding failure is always condition 1.

**11. Why does a random earlier exit beat opposing flip?** Because the draw
knows the trade's length. Lifetime-uniform: +0.618 ATR. Length-blind: **+0.011**.

**12. How much later than economically useful is the opposing flip?**
Descriptively very late — median **238 s** and mean **2.141 ATR** of giveback
after the favorable peak. But no causally implementable exit recovers it,
including chance.

**13. Is there evidence for an ARMED protection architecture?** No. Arming
requires a state where forward geometry is unfavorable enough that a protective
trigger is more often right than wrong. The most unfavorable geometry anywhere is
0.4421, and that region's continuation value is −0.0005 ATR.

**14. Is staged profit realization structurally better matched to the path?**
The *geometry* says yes — `P(next +0.5 rung)` is 0.79–0.81 at every rung and
0.756–0.851 across all 30 rung × year cells, with median pre-rung MAE 0.30–0.36
ATR. The *economics* say no: best case **+0.0050 ATR/original entry** at rung
4.0 (0.56% of the pool), negative at rungs ≤2.5, and it loses to the
lifetime-uniform control at rungs 1.0–3.0.

**15. Does raw model score add information after conditioning on price state?**
No. The apparent 0.121 gap is a 270-second remaining-lifetime difference between
the halves; on resolved races the high-score half is slightly *better*, and a
within-trade demeaned split inverts the sign.

**16. Does the evidence justify another policy study at all?** **No.** 220
regions, 0 passing, maximum 6 of 8, and the two substantive conditions are
anti-correlated by construction of the market rather than by choice of bucket.

---

## 13. Classification reasoning, stated explicitly

Two labels have a claim under the frozen SPEC §6 table, and this is recorded
rather than resolved silently.

**Label D** (`OPPOSING FLIP IS STRUCTURALLY LATE, BUT NO CAUSAL REPLACEMENT
STATE FOUND`) has a frozen condition that is **literally satisfied**: Phase 11
does show a large positive `random − opposing_flip` (+0.618), and no region
clears §8. But that condition's evidentiary basis is precisely what this study
refutes — the quantity it rests on is non-causal, and the length-blind
measurement of the same thing is +0.011. Emitting D would assert, in the label
itself, a claim my own Phase 11 shows cannot be acted on. The lateness is real as
description (2.141 ATR after the peak) and void as an economic conclusion.

**Label E** describes the primary result exactly: the post-confirmation price
state carries genuine, monotone, year-stable and side-stable forward information
— forward MFE decays 39% along the stall axis, `P(another favorable extreme)`
decays from 0.877 to 0.475, 5/5 years — and that information is about **scale**,
which cannot be monetized, rather than **sign**, which could.

Label **G** would be too strong: there *is* robust forward structure here, it is
simply orthogonal to profit. Labels **A**, **B** and **C** require an
architecture to clear a bar; the gate is closed and the harvest control settles C
at 0.56% of the pool. Label **F** is rejected in §8 on three independent checks.
Label **H** does not apply — Phase 0 reconciles to 0.898083 / −0.076530 and both
audits are clean.

---

## 14. Limitations

1. **The forward map is unconstrained by design** (SPEC D1). Forward MFE/MAE and
   the barrier races resolve to the stop-released terminal. Economic continuation
   value is stop-live and null past the stop-live terminal. Mixing the two would
   reintroduce the censoring defect this design exists to avoid.
2. **The dense grid stops at +600 s**, where 50.6% of trades have already ended.
   The sparse extension to +2,400 s is reported but never pooled; at +2,400 s
   only 162 trades remain.
3. **Barrier races are censored by the trade's own terminal.** Reported as
   `p_unresolved` on every race table, and it is material at wide barriers
   (20.8% on `+1.50/−1.00`). The resolved-only rate is carried alongside.
4. **Costs cancel in continuation value** (one round turn either way on a single
   unit). Phase 12 charges one round turn per unit, so the two-unit hypothetical
   is cost-neutral per unit against full size.
5. **2025 is not threshold-OOS** (inherited waiver). **2026 untouched.**
6. The model score is **EXPLORATORY_OUT_OF_DOMAIN** on the new regime.

---

## Final classification

```text
E. PRICE STATE HAS FORWARD INFORMATION BUT NOT ENOUGH FOR ECONOMIC ACTION
```

**What was learned.** The predecessor found that giveback is the wrong axis and
that forward progress is the right one. This study finds that *progress is the
right axis for the wrong quantity*. Every causal state variable available after
the confirming flip — stall, progress, accumulated MFE, drawdown, and their
crosses — forecasts how much price movement remains. None of them forecasts which
way. Forward MFE and forward MAE are yoked at a ratio of 1.13–1.26 in every
state, symmetric barrier races resolve at 0.50 everywhere, and continuation value
has a CI spanning zero in all 79 buckets.

**And the question the program thought it had.** The predecessor closed by
saying the open question was "why is the terminal exit worth less than a random
one". The answer is that it isn't. The random exit's advantage was its knowledge
of the trade's length; remove that and it is worth +0.011 ATR per trade and flips
sign by year. The opposing-flip exit gives back 2.141 ATR after the peak and no
causally available signal — price state or model score — locates that peak in
advance.

**Where that leaves the program.** Post-confirmation exit *timing* on this
population is closed, and it is closed by measurement rather than by another
failed policy. The 0.898 ATR/entry giveback pool is not recoverable by deciding
*when* to leave a trade already entered. If it is recoverable at all, it is by
changing something upstream of the observation — position sizing against a
forecastable *scale*, which is the one thing this state space demonstrably does
predict, or a different instrument for the exit itself. Neither is inside the
contract this study inherited.
