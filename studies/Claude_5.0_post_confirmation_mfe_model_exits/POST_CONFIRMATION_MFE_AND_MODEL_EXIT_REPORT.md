# Broad Post-Confirmation MFE Conservation and Opposing Fade-Model Exit Study

Study id: `Claude_5.0_post_confirmation_mfe_model_exits`
Stage: broad hypothesis generation. No production policy is nominated.

> **Population restriction.** This study covers the **first canonical Top-2.5%
> entry per regime (N = 5,836)**. It does **not** represent all 69,432 qualifying
> observations or repeated entries within a regime.

---

## 1. Executive summary

| Question | Answer |
| --- | --- |
| Does price-based MFE protection improve the baseline? | **Yes in magnitude, no in kind.** The best prespecified rule adds +0.050 / +0.060 / +0.062 ATR per trade (paired, t = 2.71 / 2.85 / 2.78) at the 0.75 / 1.00 / 1.25 ATR stops. But every policy, including the best, leaves mean expectancy **negative**, and the ranking is monotone toward the tightest corner of the grid — the signature of exposure reduction, not excursion conservation. |
| Does the opposing fade model give useful post-confirmation lead time? | **Structurally, no.** The opposing model is in domain for **0.0%** of trades at the confirmation instant, and the median wait from confirmation to its first eligible observation is **405 s**. 60.1% of trades never receive a single eligible post-confirmation observation. |
| Do warnings distinguish eventual losers from winners? | **Yes — in the wrong direction.** Top-5% crossing rate is **45.2% on eventual winners vs 11.0% on eventual losers** (Top-2.5%: 33.4% vs 8.6%). The warning marks a mature move, not an imminent reversal. |
| Do immediate model exits conserve MFE? | Marginally. `B_top_5_k1` adds +0.010 / +0.015 / +0.015 ATR and is the **only ALL-scope policy positive in all 5 years at all 3 stops**, but it contributes **+0.006 ATR** on the primary MFE-conservation population (baseline losing flip exits), improving only **0.4%** of them. |
| Is model-triggered tightening better than immediate exit? | **Not distinguishable.** Head-to-head on the identical comparable set, `C2` minus `B` is −0.0005 to +0.0012 ATR depending on threshold, with \|t\| ≤ 1.32 and the sign flipping between thresholds. An earlier unpaired reading favoured tightening; that gap was an artefact of differing censored sets. |
| Do results persist across 0.75, 1.00 and 1.25 ATR stops? | **Yes.** Every effect is directionally identical at all three widths, and 1.00 ATR interpolates smoothly between 0.75 and 1.25 for both the price and the model families. |
| Do combined rules improve capture without destroying the right tail? | **Partly.** Where a price rule is weak, the model adds real value (`C1_P2_top_5` +0.0276 vs +0.0149 for its price component alone). Where the price rule is already a trail, the model is inert (`C1_P3_top_5` fires the model exit on **2** of 5,836 trades). The best price rule truncates **550 of 575** baseline top-decile winners at a mean cost of **−3.26 ATR** each. |

**Central hypothesis — not supported as stated.** The opposing fade model does not
identify when the opportunity begins to reverse. Its domain gate only opens once
the *new* regime has become established, which by construction happens late and
only on trades that already ran far. What it provides instead is a late,
low-frequency "this move is mature" marker that lands near the MFE peak
(median remaining MFE after warning = **0.00 ATR**) on a minority of trades.

---

## 2. Feasibility and data coverage

### 2.1 Score availability, cadence and causality

| Question | Finding |
| --- | --- |
| Both model scores at each eligible timestamp? | Yes. `canonical_trade_paths_all.parquet` carries `bullish_*` and `bearish_*` probability, domain, source timestamp, age and carried-forward flag on **all 6,589,582** path bars, 100% non-null. |
| Cadence? | Native model cadence is **5 s** (`thresholds.json: cadence_seconds = 5`; modal `score_source_ns` gap = 5.0 s on 1,220,760 of 1,263,738 transitions). Scores are carried forward onto the 1-second path grid; median carry age 2 s, p90 4 s, but max 237,669 s across overnight gaps. |
| Exact join, no fuzzy matching? | Yes. Scores are pre-joined into the path grain by the builder; linkage is `trade_id` + `path_sequence`, contiguous 1..N for all 5,836 trades. No `merge_asof`, no interpolation. |
| Opposing model in domain after confirmation? | **Only partially.** 2,331 / 5,836 trades (39.9%) ever have an eligible post-confirmation observation. Median wait after confirmation = **405 s** (p25 290 s, p75 560 s). |
| Frozen Top-10 / Top-5 / Top-2.5 thresholds? | Bullish channel: all three frozen. Bearish channel: **`top_10` is NOT frozen** (`BEARISH_TOP_10_NOT_FROZEN`). |
| % of confirmed trades with usable opposing observations? | 39.9% pooled (SHORT 39.4%, LONG 40.7%). Among baseline losing regime-flip trades: **only 18.8%**. |
| Persistent state or newly recomputed causal scores? | Newly recomputed at each 5 s checkpoint from the frozen model, then carried forward. `is_carried_forward = false` identifies exactly one bar per distinct score. |
| Every score based only on information at its timestamp? | Verified: **0** path rows have `score_source_ns > timestamp_close_ns`, on either channel. |

### 2.2 Frozen thresholds actually used

| channel | model | opposes | top_10 | top_5 | top_2_5 |
| --- | --- | --- | --- | --- | --- |
| bullish | `BULLISH_STRICT_top25_gbt_v2` | LONG trades | 0.43167249785595935 | 0.5067081427626979 | 0.5697449423968936 |
| bearish | `LONG_STRICT_top25_gbt_v2` | SHORT trades | **NOT FROZEN** | 0.5084619230529974 | 0.5641320087327389 |

Consequence: **every Top-10% test is `policy_scope = LONG_ONLY` (2,507 trades)** and is
compared only against a LONG-restricted baseline. No Top-10% threshold was
estimated for SHORT from this population, and no threshold anywhere was derived
from realized outcomes.

### 2.3 What is unsupported

- Top-10% opposing-model tests for SHORT trades — threshold not frozen (3,329 trades).
- Frozen percentile / decile ranks — `bullish_percentile`, `bearish_percentile`,
  `*_is_top_*` are **all-Null dtype** in observations, summaries and paths. Only
  the three raw probability thresholds above exist.
- Pooled Top-10% figures across both directions. Reported LONG-only, always labelled.

### 2.4 Definition adopted for an "eligible model observation"

```
opposing channel is_carried_forward = false   (a genuinely new score arrival)
AND opposing channel in_domain = true
```

This simultaneously removes carried-forward repeats and stale overnight carries.
Persistence K counts consecutive **eligible observations**, not seconds; the
realised elapsed time is reported in §5.

---

## 3. Baseline reproduction

`policy_id = BASE` was recomputed from the canonical paths by this study's engine
and reconciled against both the frozen expected counts and the builder's stored
per-stop result parquets.

| Outcome | 0.75 exp | 0.75 got | 1.00 exp | 1.00 got | 1.25 exp | 1.25 got |
| --- | --- | --- | --- | --- | --- | --- |
| STOPPED BEFORE CONFIRMATION | 2,528 | **2,528** | 2,149 | **2,149** | 1,855 | **1,855** |
| STOPPED AFTER CONFIRMATION | 1,511 | **1,511** | 1,209 | **1,209** | 861 | **861** |
| REGIME-FLIP EXIT FOR PROFIT | 1,215 | **1,215** | 1,464 | **1,464** | 1,631 | **1,631** |
| REGIME-FLIP EXIT FOR LOSS | 504 | **504** | 905 | **905** | 1,357 | **1,357** |
| REGIME-FLIP EXIT FLAT | 15 | **15** | 17 | **17** | 20 | **20** |
| CENSORED / UNRESOLVED | 54 | **54** | 78 | **78** | 98 | **98** |
| AMBIGUOUS EVENT ORDER | 9 | **9** | 14 | **14** | 14 | **14** |
| **Total** | 5,836 | **5,836** | 5,836 | **5,836** | 5,836 | **5,836** |

Additionally, **0** per-trade classification mismatches and **0** per-trade
`realized_return_atr` mismatches (tolerance 1e-9) against the three stored
baseline parquets, on all 5,836 × 3 joined rows. Evidence:
`results/baseline_reconciliation.json` (`all_exact: true`).

One convention had to be matched exactly: the frozen baseline evaluates
**ambiguity before censoring**, so a stop touch landing on the final
(opposing-flip) bar is `AMBIGUOUS EVENT ORDER`, not `CENSORED`. The engine now
does the same.

### 3.1 Baseline economics (the frame for everything below)

| stop | mean ATR | median ATR | gross ATR | profit factor | win rate | max DD ATR | median hold s | time in market s |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0.75 | −0.0890 | −0.7113 | −513.9 | 0.841 | 0.211 | 517.5 | 186 | 2,564,977 |
| 1.00 | −0.0976 | −0.9195 | −560.5 | 0.853 | 0.255 | 591.7 | 312 | 3,358,575 |
| 1.25 | −0.1011 | −0.9766 | −578.9 | 0.863 | 0.285 | 600.6 | 415 | 3,891,598 |

**The baseline is a negative-expectancy population at all three stop widths.**
Every "improvement" below is loss reduction, never a move into profit.

---

## 4. Price-path management results (Branch A)

All 33 prespecified price rules were run against all three stops. Full table:
`results/post_confirmation_policy_cross_stop_comparison.parquet`.

### 4.1 Family ranking (paired mean incremental ATR vs the matched baseline)

| family | best member | 0.75 | 1.00 | 1.25 |
| --- | --- | --- | --- | --- |
| A2 peak giveback | `A2_act0_75_give0_50` | **+0.0504** | **+0.0599** | **+0.0624** |
| A3 fractional retention | `A3_act1_00_ret75` | +0.0446 | +0.0539 | +0.0554 |
| A1 fixed floor | `A1_act0_75_floor0_50` | +0.0426 | +0.0409 | +0.0426 |

A2 ≥ A3 > A1 at every stop (at 1.25 the best A1 is `A1_act1_00_floor0_50`,
+0.0449). Fixed floors are the weakest family, and the worst policy in the entire
grid is A1 with high activation and no protection: `A1_act1_50_floor0_00` is
negative at every stop (−0.0032 / −0.0074 / −0.0074).

### 4.2 The parameter surface has no interior optimum

Within A2 at the 1.00 ATR stop (paired mean Δ ATR):

| activation ↓ / giveback → | 0.50 | 0.75 | 1.00 |
| --- | --- | --- | --- |
| 0.75 | **+0.0599** | +0.0480 | +0.0465 |
| 1.00 | +0.0516 | +0.0379 | +0.0372 |
| 1.50 | +0.0422 | +0.0331 | +0.0342 |
| 2.00 | +0.0291 | +0.0280 | +0.0255 |

Improvement rises monotonically toward the **earliest activation and tightest
trail** — the corner of the prespecified grid. Time in market falls from
3,358,575 s (baseline) to 1,010,646 s (−70%) and median hold from 312 s to 124 s.
This is the single most important caveat in the study: what the grid measures is
consistent with **removing exposure to a negatively-drifting population**, not
with conserving favourable excursion.

### 4.3 What the best price rule actually does (`A2_act0_75_give0_50`, stop 1.00)

By original baseline outcome:

| baseline outcome | n | mean Δ ATR | % improved | % worsened | % loss→profit | % profit→smaller | right-tail Δ ATR |
| --- | --- | --- | --- | --- | --- | --- | --- |
| STOPPED AFTER CONFIRMATION | 1,209 | **+0.877** | 53.9 | 0.0 | 53.6 | 0.0 | 0 |
| REGIME-FLIP EXIT FOR LOSS | 905 | **+1.107** | 92.5 | 0.0 | 92.3 | 0.0 | 0 |
| REGIME-FLIP EXIT FOR PROFIT | 1,464 | **−1.184** | 37.4 | 62.0 | 0.0 | 62.0 | **−1,875.7** |

It converts 1,483 losses into profits and prevents a mean 1.44 ATR of giveback on
losing flip exits — and pays for it by truncating **550 of the 575** baseline
top-decile winners at a mean **−3.26 ATR** each (−1,875.7 ATR in total, against a
whole-population net gain of +344 ATR). Profit factor still improves
(0.853 → 0.952) and max drawdown falls (592 → 169 ATR), because the population's
right tail was not large enough to carry it.

### 4.4 Primary MFE-conservation population

Baseline losing regime-flip trades that first reached a given MFE (stop 1.00):

| reached MFE ≥ | n | `A2_act0_75_give0_50` mean Δ | % improved | `A3_act1_00_ret75` mean Δ | `B_top_5_k1` mean Δ | % improved |
| --- | --- | --- | --- | --- | --- | --- |
| 0.75 ATR | 837 | +1.197 | 100.0% | +1.199 | +0.007 | 0.5% |
| 1.00 ATR | 728 | +1.229 | 100.0% | +1.378 | +0.008 | 0.5% |
| 1.50 ATR | 449 | +1.306 | 100.0% | +1.401 | +0.013 | 0.9% |
| 2.00 ATR | 198 | +1.445 | 100.0% | +1.472 | +0.018 | 1.0% |

Price rules address this population completely; **model warnings do not address
it at all** — 81.2% of these trades have no eligible opposing observation.

### 4.5 Ambiguity and censoring are not inflated

At stop 1.00: baseline 14 ambiguous / 78 censored; `A2_act0_75_give0_50` 7 / 1;
`A3_act1_00_ret75` 8 / 2. Across all 33 A-family policies and all three stops the
maxima are 20 ambiguous and 93 censored, both at or below the baseline's own
98 censored at the 1.25 stop. The lagged-floor rule
produced **0** same-bar activation-and-violation cases across all 978,105 rows,
and **0** price/model ties. No policy materially increases either count.

---

## 5. Opposing fade-model results (Branch B)

### 5.1 Threshold state distribution

| threshold | scope | crosses after confirmation | never reaches | no valid observations | already active at confirmation |
| --- | --- | --- | --- | --- | --- |
| `top_10` | LONG only (2,507) | 678 (27.0%) | 342 | 1,487 (59.3%) | 0.72% |
| `top_5` | all (5,836) | 1,143 (19.6%) | 1,188 | 3,505 (60.1%) | 0.38% |
| `top_2_5` | all (5,836) | 871 (14.9%) | 1,460 | 3,505 (60.1%) | 0.22% |

Already-active cases are reported separately and are never counted as new
crossings. They are rare because the opposing channel's last in-domain reading
before confirmation usually dates from the *previous* regime era and is stale by
construction — a further reason not to treat it as a live warning.

### 5.2 Warning economics

| threshold | median conf→warning s | median MFE at warning ATR | median unrealised at warning ATR | median remaining MFE after warning ATR | median warning→opposing flip s |
| --- | --- | --- | --- | --- | --- |
| `top_10` (LONG) | 925 | 3.28 | 2.23 | **0.00** | 375 |
| `top_5` | 1,160 | 4.31 | 2.79 | **0.00** | 228 |
| `top_2_5` | 1,335 | 4.82 | 3.11 | **0.00** | 148 |

The warning arrives at a median of **19–22 minutes** after confirmation, on
trades already **2.2–3.1 ATR in profit**, with essentially **no MFE left to
capture**. As a peak marker it is well placed; as an early warning it is far too
late and far too selective.

### 5.3 Winner vs loser incidence — the hypothesis is inverted

| threshold | eventual winners: crossing rate | eventual losers: crossing rate | ratio |
| --- | --- | --- | --- |
| `top_10` (LONG) | 57.5% (n = 657) | 16.0% (n = 1,791) | 3.6× |
| `top_5` | 45.2% (n = 1,465) | 11.0% (n = 4,262) | 4.1× |
| `top_2_5` | 33.4% (n = 1,465) | 8.6% (n = 4,262) | 3.9× |

By baseline outcome at `top_5`: REGIME-FLIP PROFIT 45.2% crossing, REGIME-FLIP
LOSS **0.44%**, STOPPED AFTER CONFIRMATION **4.4%**. The two classes that give
back MFE are precisely the two the model almost never speaks about.

(These are incidence rates. No frozen binary reversal target is defined for this
population, so they are deliberately not described in classification terms.)

### 5.4 Persistence

Median elapsed time from the first crossing to the second consecutive eligible
observation above threshold is **5 s**, and to the third **10–20 s** — i.e. K = 2
and K = 3 cost one and two model cadence intervals respectively, not minutes.
Persistence monotonically reduces the effect: at stop 1.00, `top_5` gives
+0.0154 (K1) → +0.0135 (K2) → +0.0084 (K3). Requiring persistence loses more
by delay than it gains by filtering.

### 5.5 Where the model is live — B4 anchors

Fraction of trades with a **live (in-domain)** opposing reading at each anchor:

| anchor | n | live | median live probability | median 30 s change | median 60 s change |
| --- | --- | --- | --- | --- | --- |
| CONFIRMATION | 5,836 | **0 (0.0%)** | — | — | — |
| MFE 1.00 first reached | 4,039 | 209 (5.2%) | 0.186 | −0.044 | −0.062 |
| MFE 1.50 first reached | 3,201 | 577 (18.0%) | 0.202 | −0.030 | −0.044 |
| MFE 2.00 first reached | 2,514 | 887 (35.3%) | 0.189 | −0.037 | −0.054 |
| PEAK MFE | 5,836 | 2,107 (36.1%) | 0.159 | **−0.036** | **−0.057** |
| giveback 0.25 from peak | 5,800 | **5 (0.09%)** | 0.098 | −0.054 | −0.087 |
| giveback 0.50 from peak | 5,800 | **8 (0.14%)** | 0.110 | 0.000 | −0.022 |
| giveback 0.75 from peak | 5,798 | **28 (0.48%)** | 0.200 | +0.041 | +0.068 |
| giveback 1.00 from peak | 5,793 | **177 (3.1%)** | 0.292 | +0.074 | +0.103 |
| baseline final exit | 5,836 | 651 (11.2%) | 0.616 | +0.042 | +0.141 |

Two structural facts fall out:

1. **At the moment the trade tops out, the opposing probability is low (0.159,
   far below the 0.507 / 0.508 top-5% thresholds) and *falling* (−0.036 over 30 s).**
   The model is moving away from a warning exactly at the peak.
2. **At every giveback anchor the model is effectively offline** (0.09%–3.1% live).
   The events the study set out to anticipate happen in the model's blind spot.

### 5.6 Entry-model diagnostics (B5)

The entry model is in domain for 64.7% of trades at confirmation (median
probability 0.646–0.673, above its own entry threshold), but its domain collapses
immediately afterwards: 12.8% live at MFE 1.00, 3.9% at MFE 1.50, 1.8% at
MFE 2.00, 1.5% at the baseline final exit. The entry model's domain requires the
regime we just flipped *out of*, so its post-confirmation readings have no valid
meaning. **Per the SPEC it is used as a diagnostic only and never as an exit
rule** — the data confirms that was the correct restriction.

---

## 6. Combined rules (Branch C)

### 6.1 C1 — first event wins

Whether the model contributes depends entirely on how fast the price rule is
(stop 1.00, paired Δ ATR):

| policy | price mgmt exits | model warning exits | paired Δ | price component alone | model contribution |
| --- | --- | --- | --- | --- | --- |
| `C1_P1_top_5` | 1,906 | **421** | +0.0269 | +0.0189 (`A1_act1_00_floor0_25`) | **+0.0080** |
| `C1_P2_top_5` | 1,316 | **493** | +0.0276 | +0.0149 (`A1_act1_50_floor0_50`) | **+0.0127** |
| `C1_P3_top_5` | 2,155 | **2** | +0.0331 | +0.0331 (`A2_act1_50_give0_75`) | **+0.0000** |

Against the two fixed-floor rules the model exit fires on 7–8% of trades and adds
a real +0.008 to +0.013 ATR. Against the peak-giveback trail it is completely
crowded out — the trail fires roughly 15 minutes before the median warning, so
`C1_P3_top_5` is numerically identical to its price component. Note also that the
best combined result (+0.0331) is still just the price rule, and it is beaten by
`A2_act0_75_give0_50` alone (+0.0599).

### 6.2 C2 — warning arms the trail

Comparing the two interpretations **on the identical comparable set** (the only
valid comparison — the unconditional means differ mainly through censoring):

| threshold | stop | n | `C2` − `B` mean Δ ATR | t | trades where they differ |
| --- | --- | --- | --- | --- | --- |
| `top_5` | 0.75 | 5,768 | −0.00027 | −0.59 | 462 |
| `top_5` | 1.00 | 5,736 | −0.00048 | −0.98 | 567 |
| `top_5` | 1.25 | 5,716 | −0.00023 | −0.46 | 642 |
| `top_2_5` | 0.75 | 5,778 | +0.00042 | +1.30 | 361 |
| `top_2_5` | 1.00 | 5,751 | +0.00036 | +1.03 | 436 |
| `top_2_5` | 1.25 | 5,732 | +0.00049 | +1.32 | 497 |
| `top_10` (LONG) | 0.75 | 2,477 | +0.00066 | +0.35 | 291 |
| `top_10` (LONG) | 1.00 | 2,470 | +0.00120 | +0.46 | 357 |
| `top_10` (LONG) | 1.25 | 2,465 | +0.00117 | +0.44 | 396 |

**The two interpretations are indistinguishable.** The sign flips between
thresholds, every magnitude is under 0.0013 ATR, and no \|t\| exceeds 1.32. An
unpaired comparison of unconditional means appears to favour tightening by
+0.005 to +0.007 ATR; that gap is an artefact of a handful of trades that are
censored under one policy and resolved under the other, and it does not survive
pairing. `C2_P1` and `C2_P2` are near-inert (+0.0003 to +0.0008) because their
fixed floors rarely bind after a warning that already arrives ~2.8 ATR in profit.

---

## 7. Cross-stop robustness

Every finding is directionally identical at 0.75, 1.00 and 1.25 ATR, and **1.00
interpolates smoothly** between the two ends:

All figures are paired mean Δ ATR against the matched baseline.

| effect | 0.75 | 1.00 | 1.25 | smooth? |
| --- | --- | --- | --- | --- |
| best A2 rule `A2_act0_75_give0_50` | +0.0504 | +0.0599 | +0.0624 | yes, monotone |
| best A3 rule `A3_act1_00_ret75` | +0.0446 | +0.0539 | +0.0554 | yes, monotone |
| `A1_act0_75_floor0_00` | +0.0244 | +0.0183 | +0.0232 | yes, flat |
| `B_top_5_k1` | +0.0098 | +0.0154 | +0.0146 | yes, monotone |
| `C1_P2_top_5` | +0.0238 | +0.0276 | +0.0269 | yes, flat |
| `C2_P3_top_5` | +0.0096 | +0.0150 | +0.0143 | yes, monotone |
| `top_5` crossing rate | 19.6% at every stop — the warning population is stop-independent | | | n/a |

Of the 51 non-baseline ALL-scope policies, **45 improve at all three stops**, 3 at
two, 2 at one, 1 at none. Effects are not stop-specific. Wider stops give larger
absolute improvements simply because there is more baseline loss to remove.

`incremental_mean_return_vs_baseline_atr` in the comparison parquet is
**scope-matched**: LONG-only (`top_10`) policies are compared against the
LONG-restricted baseline (−0.0804 / −0.0788 / −0.0925), never the pooled one.

---

## 8. Stability

### 8.1 By year — this is where the price family breaks

Paired mean Δ ATR by entry year:

| policy | stop | 2021 | 2022 | 2023 | 2024 | 2025 | years > 0 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `A2_act0_75_give0_50` | 0.75 | +0.079 | +0.095 | **−0.043** | +0.112 | +0.010 | 4 |
| `A2_act0_75_give0_50` | 1.00 | +0.094 | +0.123 | **−0.060** | +0.143 | +0.001 | 4 |
| `A2_act0_75_give0_50` | 1.25 | +0.104 | +0.125 | **−0.064** | +0.148 | +0.001 | 4 |
| `A3_act1_00_ret75` | 1.00 | +0.093 | +0.119 | **−0.065** | +0.130 | **−0.007** | 3 |
| `A2_act1_50_give0_75` | 1.00 | +0.093 | +0.066 | **−0.077** | +0.100 | **−0.015** | 3 |
| `A1_act0_75_floor0_00` | 1.00 | +0.015 | +0.006 | +0.016 | +0.055 | +0.000 | **5** |
| `B_top_5_k1` | 1.00 | +0.028 | +0.003 | +0.016 | +0.022 | +0.009 | **5** |
| `C2_P3_top_5` | 1.00 | +0.025 | +0.003 | +0.016 | +0.021 | +0.010 | **5** |

The headline price rules are carried by 2021, 2022 and 2024; **2023 is negative
at all three stops and 2025 is flat**. Only two ALL-scope policies are positive in
all five years at all three stops: `A1_act0_75_floor0_00` (break-even after
0.75 ATR MFE) and `B_top_5_k1`.

### 8.2 By direction

| policy (stop 1.00) | LONG Δ | SHORT Δ |
| --- | --- | --- |
| `A2_act0_75_give0_50` | +0.041 | +0.074 |
| `A3_act1_00_ret75` | +0.042 | +0.063 |
| `A1_act0_75_floor0_00` | +0.012 | +0.023 |
| `B_top_5_k1` | +0.009 | +0.021 |
| `C2_P3_top_5` | +0.008 | +0.020 |

Positive for both directions at every stop; SHORT (the `BULLISH_STRICT` entry
model) benefits more from every family. No direction reversal anywhere.

### 8.3 Statistical scale

Paired t-statistics on the per-trade delta (n ≈ 5,724–5,773): best A2 rule
t = 2.71 / 2.85 / 2.78; `A1_act0_75_floor0_00` t = 2.32 / 1.38 / 1.62;
`B_top_5_k1` t = 1.37 / 2.03 / 1.74; `C2_P3_top_5` t = 1.33 / 1.97 / 1.71.
None of these are large for 5,800 observations, and the price-rule t-statistics
are inflated by the same exposure-reduction mechanism described in §4.2.

---

## 9. Interpretation

### Confirmed evidence

- The baseline is negative at all three stop widths; nothing in the frozen policy
  grid makes it positive. **Every result here is loss reduction.**
- Peak-giveback and fractional-retention trails dominate fixed protected floors
  at every stop and in both directions.
- On baseline losing regime-flip trades that reached ≥ 0.75 ATR MFE, a trail
  recovers +1.20 to +1.45 ATR and improves ~100% of them. That population is real
  and large (837 / 5,836 at stop 1.00).
- The opposing fade model is **out of domain at confirmation for 100% of trades**,
  has no eligible observation at all for 60.1%, and is offline at ≥ 96.9% of
  giveback anchors.
- Opposing-model warnings occur ~4× more often on eventual winners than on
  eventual losers, at all three thresholds.
- Model-triggered tightening and immediate model exit are **statistically
  indistinguishable** on the identical population (\|Δ\| ≤ 0.0013 ATR, \|t\| ≤ 1.32,
  sign varies by threshold).
- The model's contribution inside a combined rule is inversely proportional to
  how fast the price component is: +0.013 ATR alongside a slow fixed floor,
  +0.000 alongside a peak-giveback trail.
- Results are smooth and structural across 0.75 / 1.00 / 1.25 ATR.

### Plausible hypothesis

- The A2/A3 advantage is largely **exposure reduction**, not excursion
  conservation. Support: the surface is monotone to the tight corner with no
  interior optimum; time in market falls 70% at the best setting; and the two
  policies that survive all five years are the two that change the *least*
  (break-even floor; a warning that fires on 11.5% of trades).
- The `top_5` opposing crossing may be a usable **maturity marker**: median
  remaining MFE after the warning is 0.00 ATR, and its effect is small, positive
  in all five years, positive in both directions, and costs only ~130 of 584
  right-tail trades.
- 2023 appears to be a structurally different year for trail-based management
  (the only year where every A2/A3 member is negative). Not diagnosed here.

### Unsupported speculation

- That the opposing model "identifies when the opportunity is beginning to
  reverse". The live-domain evidence at PEAK_MFE (probability 0.159 and falling)
  contradicts it.
- Any Top-10% conclusion for SHORT trades. The threshold does not exist.
- Any conclusion about repeated entries within a regime, or about the other
  63,596 qualifying observations.

### Answers to the nine questions

1. **Can simple post-confirmation floors conserve meaningful MFE?** Yes
   mechanically — +1.2 to +1.45 ATR on the losing-flip population — but the net
   effect across the whole population is dominated by right-tail truncation and
   is likely exposure reduction.
2. **Which MFE activation region is most relevant?** The lowest tested, 0.75 ATR.
   Improvement falls monotonically as activation rises to 2.00 ATR. Because the
   optimum sits on the grid boundary, the honest reading is "earlier is better
   within this grid", not "0.75 ATR is the right level".
3. **Do eventual losers show opposing-model warnings before major giveback?**
   No. 11.0% at `top_5`, 8.6% at `top_2_5`, and 81.2% of losing flip exits have no
   eligible observation at all.
4. **How frequently do eventual winners show the same warning?** 45.2% at `top_5`,
   33.4% at `top_2_5`, 57.5% at `top_10` (LONG) — roughly 4× the loser rate.
5. **Exit or tightening trigger?** **The study cannot tell them apart.** Paired
   on the identical set, `C2` − `B` ranges from −0.0005 (`top_5`) to +0.0012
   (`top_10`) ATR with \|t\| ≤ 1.32. They differ on only 291–642 trades. What *can*
   be said is that the warning is worth more when it is combined with a *slow*
   price rule than with a fast one (§6.1).
6. **Does it differ by LONG vs SHORT?** Same sign everywhere; SHORT gains roughly
   twice as much from every family. LONG additionally has a frozen Top-10%
   threshold and 40.7% opposing coverage vs 39.4% for SHORT.
7. **Does it differ across stop widths?** No sign changes. Magnitudes scale with
   the size of the baseline loss being removed.
8. **Does 1.00 ATR interpolate smoothly?** Yes, for every family and every metric
   examined (see §7).
9. **Are improvements large enough to justify a refined causal study?** For the
   price family: not as a management result, because of the exposure-reduction
   confound — but yes as a *diagnostic* question about why 2023 inverts. For the
   model family: the effect is small (+0.015 ATR, t ≈ 2.0 at best) but it is the
   most year-stable and most tail-preserving signal in the study, and §6.1 gives a
   clean, prespecifiable follow-up: pair the warning with a rule slow enough that
   the warning still has something to do.

---

## 10. Refinement candidates

Three per branch, for a later **prespecified** study. **None is deployable, none
is nominated for production.**

### Price-management families

1. **`A1_act0_75_floor0_00` — break-even after 0.75 ATR MFE.** The only price rule
   positive in all five years at all three stops (worst +0.018 ATR). Minimal
   structural change to the baseline; truncates far less of the right tail than a
   trail.
2. **`A2_act0_75_give0_50` — earliest activation, tightest giveback.** Largest
   effect by a wide margin (+0.050 to +0.062 ATR, t ≈ 2.8), but must be
   re-examined *against a matched-holding-time control* before any causal claim.
3. **`A3_act1_00_ret75` — retain 75% of peak MFE from 1.00 ATR.** The best
   non-corner member; useful specifically as the interior-optimum test that this
   grid could not perform.

### Model-warning families

1. **`top_5` first crossing, K = 1.** Positive in 5/5 years at 3/3 stops, both
   directions, small right-tail cost (132 of 584 at stop 1.00).
2. **Opposing-model domain-onset timing itself.** The 405 s median wait and the
   60.1% never-eligible rate are the binding constraints. A refinement should ask
   whether the domain gate can be relaxed *before* asking anything about
   thresholds.
3. **`top_10` on LONG only.** The only threshold with meaningful coverage
   (40.7% eligible, 27.0% crossing) — worth studying as a LONG-specific
   diagnostic, conditional on a frozen bearish `top_10` being produced first.

### Combined families

1. **`C1_P2_top_5` — slow fixed floor plus `top_5` first crossing.** The
   configuration where the model contributes most (+0.0127 ATR over its price
   component; 493 model exits vs 1,316 price exits at stop 1.00) and where the two
   signals genuinely compete rather than one crowding out the other.
2. **`C1_P1_top_5` — the same structure with an earlier, tighter floor.** Model
   contribution +0.0080 ATR; useful as the second point on the "how slow must the
   price rule be for the warning to matter" curve.
3. **`C2` with a tighter armed trail.** The C2 trail at 0.75 ATR giveback fires
   ~2.8 ATR into profit and, as shown in §6.2, currently behaves the same as an
   immediate exit. The prespecified question is whether a tighter armed trail
   separates the two interpretations at all; it was not in this grid.

---

## Final verdict

```
BROAD EVIDENCE IS MIXED
```

**Strongest supported finding.** The opposing fade model's warning is inverted
relative to the hypothesis: it fires ~4× more often on eventual winners than on
eventual losers (45.2% vs 11.0% at `top_5`), is out of domain for 100% of trades
at confirmation, and is offline at ≥ 96.9% of MFE-giveback moments. It cannot
serve as a reversal warning for this population as currently gated.

**Largest methodological limitation.** The price-management improvement is
confounded with exposure reduction. Improvement increases monotonically toward
the tightest, earliest corner of the prespecified grid; the best setting cuts
time in market by 70% and truncates 550 of the 575 top-decile winners; and the
population has negative drift throughout. No matched-holding-time control existed
inside the frozen grid, so "conserves MFE" and "spends less time in a losing
population" are not separated by this study. Secondary limitations: 1-second OHLC
cannot resolve intrabar ordering, which is why the lagged-floor convention was
adopted; 219 trades (3.8%) have incomplete paths; and the whole result set is
confined to the first qualifying signal per regime.

**Most promising next hypothesis.** The opposing `top_5` crossing is not a
reversal warning but a **maturity marker** — it lands at a median remaining MFE of
0.00 ATR on 19.6% of trades, is positive in 5 of 5 years at all 3 stops, and costs
only ~130 of 575 right-tail trades. Its value depends entirely on what it is
paired with: it adds +0.013 ATR alongside a slow fixed floor and exactly nothing
alongside a fast trail. The prespecified follow-up is to hold the price rule
deliberately slow and ask how much of the marker's +0.013 ATR survives a
matched-holding-time control — which is the same control the price family needs
and did not have here.

---

## Appendix — validation

| check | result |
| --- | --- |
| Rows | 978,105 = 3 stops × (52 ALL × 5,836 + 9 LONG_ONLY × 2,507) |
| Duplicate (trade_id, stop, policy_id) keys | **0** |
| Policy population violations | **0** |
| Baseline reconciliation vs frozen counts | **exact, all 3 stops** |
| Baseline per-trade class / return vs stored parquets | **0 / 0** mismatches on 17,508 joined rows |
| Independent recompute | seed 20260727, **100 trades × 3 stops = 300 cases**, 292 unique trades, **3,000 policy checks**, **0 unexplained mismatches** |
| Independent implementation | bar-by-bar replay recomputing favourable/adverse excursion from raw path `high`/`low`; does not import the engine module |
| Future score usage | **0** path rows with `score_source_ns > timestamp_close_ns` |
| Fuzzy timestamp joins | none — all joins on `trade_id` / `path_sequence` |
| Path ordering | monotonic `timestamp_close_ns`, contiguous `path_sequence` 1..N, all 5,836 trades |
| Terminal outcomes | 9 classes, mutually exclusive and exhaustive |
| Same-bar activation and violation | **0** across all rows (lagged floor) |
| Price/model ties | **0** |
| Transaction costs | not applied |
| ATR→dollar conversion | not performed |

### Deliverables

```
SPEC.md
analysis/feasibility_probe.py
analysis/probe2.py
analysis/policy_defs.py
analysis/analyze_post_confirmation_mfe_and_model_exits.py
analysis/reconcile_baseline.py
analysis/validate_post_confirmation_study.py
analysis/aggregate_post_confirmation_results.py
results/feasibility_probe.json
results/feasibility_probe2.json
results/baseline_reconciliation.json
results/post_confirmation_mfe_model_exit_trade_policy_results.parquet   (978,105 rows)
results/post_confirmation_model_warning_events.parquet                  (17,508 rows)
results/post_confirmation_model_diagnostic_anchors.parquet              (50,453 rows)
results/post_confirmation_policy_cross_stop_comparison.parquet          (183 rows)
results/post_confirmation_mfe_model_exit_summary.json
results/post_confirmation_validation.json
POST_CONFIRMATION_MFE_AND_MODEL_EXIT_REPORT.md
```

No NautilusTrader run was performed. No canonical parquet was modified. The
research store was not rebuilt. No synthetic paths were created.
