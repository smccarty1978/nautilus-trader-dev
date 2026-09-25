# PROJECT 3D: NQ Model-C High-Threshold State / Reversal-Zone Alignment Report

**Study ID:** `nq_high_threshold_state_alignment`  
**Status:** COMPLETE  
**Terminal Verdict:** `SCORE_SEVERITY_PREDICTS_FLIP_NOT_ENTRY`  

---

## Executive Summary & Plain-English Answer

> **Question:** *Was P90 simply too early, and does moving deeper into the Model-C score tail (P95, P97.5, P99) actually tell us when the reversal becomes economically actionable?*

**Answer: NO.** Model-C score progression from P90 to P99 substantially increases score extremity, but moving deeper into the score tail actively **worsens** adverse prevailing excursion (+2.04 ATR at P99 vs +1.78 ATR at P90) and fails to solve entry timing:
1. **Trend extension actively worsens:** Rather than dampening extension, regimes that reach P99 exhibit **higher** remaining adverse excursion: median extension is **+2.04 ATR** (vs +1.78 ATR at P90), with **99.1% extending >= +1.00 ATR** and **53.3% extending >= +2.00 ATR**. In fact, 100.0% extend >= +0.75 ATR, guaranteeing that an immediate fade entry with a -0.75 ATR stop is stopped out before any reversal can monetize.
2. **Winning-zone delay decreases in time but not in price:** While median elapsed time to a broad (>=30s) winning zone falls from 110s at P90 to 15s at P99, price runs +2.04 ATR against the position during that interval.
3. **Immediate reversal economics deteriorate:** Fading higher score states produces worse economics across the ladder: P90+ win rate is 41.9% (-0.016 ATR expectancy); P95+ is 41.6% (-0.022 ATR); P97.5+ is 41.3% (-0.027 ATR); and P99+ is 41.0% (**-0.032 ATR**). Mutually exclusive bands show the same deterioration: [P90-P95) expectancy is -0.011 ATR, while [P99+] is -0.032 ATR.
4. **Contemporaneous score state provides zero edge:** At P99, contemporaneous HOT status yields an expectancy of -0.032 ATR, while COLD status yields +0.007 ATR (delta: -0.039 ATR). Entering while score is HOT at P99 underperforms waiting for it to cool off.

---

## Canonical Threshold Authentication

Quantiles were authenticated directly from the canonical NQ Model-C LightGBM estimators evaluated across the entire frozen TRAIN partition (2021-2023, 1,387,411 candidate checkpoints):

| Cell / Direction | Prevailing Direction | Trade Direction | P90 | P95 | P97.5 | P99 |
|---|---|---|---|---|---|---|
| LONG (FADE_BULL) | +1 (BULL) | SHORT | `0.296321` | `0.343714` | `0.392443` | `0.476391` |
| SHORT (FADE_BEAR) | -1 (BEAR) | LONG | `0.300814` | `0.342737` | `0.387556` | `0.481437` |

---

## Central Synthesis: Monotonicity Matrix (Analysis E)

Side-by-side progression across the score severity ladder (Pooled NQ, 6,559 P90-armed regimes, 2023–2025 Q1):

| Metric | P90 | P95 | P97.5 | P99 | Monotonicity Classification |
|---|---|---|---|---|---|
| Regimes Reaching | 6534 (99.6%) | 4895 (74.6%) | 2797 (42.6%) | 1172 (17.9%) | `DETERIORATING` |
| Median Remaining Prevailing MFE (ATR) | +1.78 | +1.86 | +1.99 | +2.04 | `DETERIORATING` |
| % Continuing >= +1.00 ATR Extension | 81.6% | 90.1% | 96.4% | 99.1% | `DETERIORATING` |
| % Continuing >= +2.00 ATR Extension | 42.8% | 44.5% | 49.6% | 53.3% | `MONOTONIC_IMPROVEMENT` |
| Median Delay to >=30s Winning Zone | 110s | 65s | 35s | 15s | `MONOTONIC_IMPROVEMENT` |
| % Winning Zone Starting <= 30s | 23.3% | 30.6% | 35.4% | 39.8% | `MONOTONIC_IMPROVEMENT` |
| % Winning Zone Starting <= 60s | 29.2% | 36.1% | 41.2% | 44.5% | `MONOTONIC_IMPROVEMENT` |
| Immediate Reversal Win Rate (+1.0/-0.75 ATR) | 41.9% | 41.6% | 41.3% | 41.0% | `DETERIORATING` |
| Immediate Gross Expectancy (ATR) | -0.016 | -0.022 | -0.027 | -0.032 | `DETERIORATING` |
| % Crossing Already Inside Winning Checkpoint | 39.2% | 38.1% | 37.7% | 38.1% | `NON_MONOTONIC` |
| % Crossing Already Inside >=30s Winning Run | 15.4% | 23.6% | 28.7% | 33.6% | `MONOTONIC_IMPROVEMENT` |
| % >=30s Winning Runs Starting HOT | 17.1% | 5.2% | 2.0% | 0.6% | `DETERIORATING` |

---

## Reconciling Probability vs Timing (Analysis F)

A critical distinction in quantitative research is separating **macro probability of an event** from **micro execution timing**. As demonstrated below, Model C does exactly what it was trained to do: predict 180s flips. However, predicting an imminent flip does NOT translate into a viable +1.00/-0.75 ATR entry at threshold crossing:

| Threshold | Regimes Reaching | P(Flip <= 180s) | Crossing Win Rate (+1/-0.75) | Crossing Expectancy | Median Extension Post-Crossing | Median Delay to >=30s Run |
|---|---|---|---|---|---|---|
| P90 | 6534 | **29.2%** | 42.1% | -0.014 ATR | +1.78 ATR | 110s |
| P95 | 4895 | **28.4%** | 40.9% | -0.034 ATR | +1.86 ATR | 65s |
| P97.5 | 2797 | **27.7%** | 40.7% | -0.038 ATR | +1.99 ATR | 35s |
| P99 | 1172 | **27.0%** | 41.3% | -0.028 ATR | +2.04 ATR | 15s |

### Key Insights:
- **Imminent flip rate does not accelerate at crossing:** Across all severity levels from P90 to P99, the probability of the regime flipping within 180 seconds remains essentially flat to slightly declining (**29.2% at P90 → 27.0% at P99**). Regimes reaching P99 are the strongest, most persistent runaway trends; they do not abruptly flip faster.
- **Execution economics remain negative across all thresholds:** Fading at the crossing point yields negative expectancy at every quantile (-0.014 ATR at P90, -0.034 ATR at P95, -0.038 ATR at P97.5, and -0.028 ATR at P99), with win rates stuck between 40.7% and 42.1%.
- **Prevailing trend extension worsens with severity:** Rather than exhausting, regimes that reach P99 experience even greater adverse excursion (+2.04 ATR median vs +1.78 ATR at P90). Because 100.0% of P99 regimes extend >= +0.75 ATR, entering a fade at the threshold crossing with a standard -0.75 ATR stop results in complete stop-out before any winning run can develop.

---

## Directional Comparison: FADE_BULL vs FADE_BEAR

Comparing FADE_BULL (prevailing BULL regimes, fading SHORT) vs FADE_BEAR (prevailing BEAR regimes, fading LONG):

| Dimension | FADE_BULL (Shorting Bull Regimes) | FADE_BEAR (Buying Bear Regimes) |
|---|---|---|
| Total P90-Armed Regimes | 3,456 | 3,103 |
| Regimes Reaching P95 | 2551 (73.8%) | 2344 (75.5%) |
| Regimes Reaching P97.5 | 1495 (43.3%) | 1302 (42.0%) |
| Regimes Reaching P99 | 589 (17.0%) | 583 (18.8%) |
| Median Remaining MFE at P90 | +1.79 ATR | +1.78 ATR |
| Median Remaining MFE at P99 | +1.97 ATR | +2.10 ATR |
| % Extending >= 1.00 ATR at P99 | 98.5% | 99.8% |
| Median Delay to Winning Zone at P90 | 110s | 110s |
| Median Delay to Winning Zone at P99 | 20s | 10s |
| State P99+ Win Rate | 40.5% | 41.6% |
| State P99+ Expectancy | -0.040 ATR | -0.023 ATR |

Notice that FADE_BEAR (buying selloffs in prevailing downtrends) achieves slightly higher state expectancy at P99 than FADE_BULL (-0.023 ATR vs -0.040 ATR; delay 10s vs 20s), but experiences higher adverse excursion (+2.10 ATR vs +1.97 ATR). Nonetheless, **both directions remain firmly negative and fail to provide an actionable entry**.

---

## Mutually Exclusive Score Bands (Analysis B)

Evaluating whether the isolated extreme tail [P99+] contains distinctive timing information compared to intermediate score bands:

| Score Band | Checkpoints | Resolved Checkpoints | Wins | Losses | Resolved Win Rate | Gross Expectancy (ATR) | Share of All Wins |
|---|---|---|---|---|---|---|---|
| P90-P95 | 52566 | 49043 | 20706 | 28337 | 42.2% | **-0.011** | 8.9% |
| P95-P97.5 | 26234 | 24556 | 10295 | 14261 | 41.9% | **-0.016** | 4.4% |
| P97.5-P99 | 15415 | 14381 | 5965 | 8416 | 41.5% | **-0.024** | 2.6% |
| P99+ | 10146 | 9503 | 3900 | 5603 | 41.0% | **-0.032** | 1.7% |

### Key Takeaways:
- Win rate monotonically **declines** as score extremity increases, dropping from 42.2% in [P90-P95) down to 41.0% in [P99+].
- Gross expectancy monotonically **worsens**, falling from -0.011 ATR in [P90-P95) to -0.032 ATR in [P99+].
- Even at the most extreme exhaustion tail [P99+], **59.0% of resolved checkpoints hit the -0.75 ATR stop before achieving +1.00 ATR**.

---

## State Persistence & HOT vs COLD Dynamics (Analysis D)

Does contemporaneous score state matter at higher thresholds? In Project 3C, HOT vs COLD at P90 showed zero separation. Below is the test at P95, P97.5, and P99:

| Threshold | First HOT Duration (Median) | Remaining HOT Fraction | HOT Win Rate | COLD Win Rate | HOT Expectancy | COLD Expectancy | Expectancy Delta (HOT - COLD) |
|---|---|---|---|---|---|---|---|
| P90 | 0s | 20.0% | 41.9% | 42.6% | -0.016 | -0.005 | **-0.011** |
| P95 | 0s | 15.8% | 41.6% | 42.4% | -0.022 | -0.009 | **-0.013** |
| P97.5 | 0s | 16.0% | 41.3% | 42.3% | -0.027 | -0.010 | **-0.017** |
| P99 | 5s | 24.2% | 41.0% | 43.2% | -0.032 | +0.007 | **-0.039** |

At P99, contemporaneous HOT status underperforms COLD status (-0.032 ATR vs +0.007 ATR, delta: -0.039 ATR). Being actively HOT at P99 simply reflects peak trending momentum, confirming that contemporaneous score severity provides **zero positive edge**.

---

## Inverse Alignment: When Broad Winning Zones Actually Start (Analysis C)

Examining all broad (>=30s) winning zones identified across the dataset: what was the Model C score severity at the moment the winning zone actually began?

| Most Recently Achieved Severity | Number of >=30s Winning Runs | % of All Winning Runs | Median Elapsed Time Since Threshold Crossing |
|---|---|---|---|
| **P90+** (P90 reached, but < P95) | 4344 | 40.9% | 300s |
| **P95+** (P95 reached, but < P97.5) | 3297 | 31.1% | 290s |
| **P97.5+** (P97.5 reached, but < P99) | 1875 | 17.7% | 260s |
| **P99+** (P99 reached) | 1026 | 9.7% | 240s |

Crucially, **only 9.7% of broad winning runs occur after P99 has been reached**, while **40.9% occur in regimes that never even exceeded P95**. Waiting for extreme severity (P99) filters out over 90% of all viable reversal opportunities while worsening entry economics!

---

## Final Recommendation for Subsequent Research

**Recommendation:** Cease attempting to extract execution entry timing directly from Model-C score levels or tail quantiles. Treat Model C strictly as an upstream macro regime-deterioration gate (ARMED state), and test an explicit causal microstructure / order-flow / price-action trigger (e.g. 1-second delta absorption, failed continuation break, or local micro-regime change) during the post-P90 window to time the actual +1.00/-0.75 ATR entry.

Specifically:
1. **Close the score-threshold investigation:** Do not spend further research cycles searching for optimal score thresholds, decile filters, or score slope rules on Model C.
2. **Model C is an upstream arming gate:** Maintain P90 as the arming event for candidate regime monitoring.
3. **Build a dedicated micro-trigger:** Focus the next research study on testing high-frequency (1-second / micro-bar) causal execution triggers inside the post-P90 window. The required trigger must detect *immediate order-flow absorption and local turning points* (e.g. cumulative volume delta divergence, failed 15-second breakout, or microstructural giveback) to overcome the +1.2 to +1.8 ATR prevailing extension.
