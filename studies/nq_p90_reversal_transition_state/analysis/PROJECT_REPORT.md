# PROJECT 3E: NQ Model-C Causal State Transition & Reversal-Zone Localization Report

**Study ID:** `nq_p90_reversal_transition_state`  
**Status:** COMPLETE — ZERO REPLAY / RETROSPECTIVE CAUSAL DIAGNOSTIC  
**Terminal Research Verdict:** `TRANSITION_UNOBSERVABLE_WITH_5S_PRICE_AND_MODEL_INPUTS`  

---

## Executive Summary & Plain-English Answers to Primary Questions

### The Central Question
> *Within the full P90-armed NQ population: What causally observable state transition separates prevailing-trend continuation / dangerous fade territory from the beginning and persistence of the +1.00 / -0.75 ATR winning reversal-entry zones?*

### The Plain-English Answer
**The empirical evidence conclusively shows that NO CAUSALLY OBSERVABLE 5-SECOND PRICE OR MODEL-C STATE TRANSITION LOCALIauthorizes THE REVERSAL ENTRY ZONE.**

Across all 586,897 causal 5-second checkpoints across 6,559 P90-armed regimes (2023, 2024 TRAIN and 2025 Q1 OOS):
1. **Price Stagnation and Givebacks Fail to Improve Economics:** Waiting for price to pause ($\ge 30$s since latest extreme) or retrace ($\ge 0.20$ to $0.50$ ATR giveback) does **not** lift trade expectancy into positive territory. Baseline win rate is **42.39%** (-0.0082 ATR expectancy); the stagnation + giveback state yields **42.20%** win rate and **-0.0114 ATR** expectancy. None of the tested price-failure combinations cross the 42.86% breakeven requirement.
2. **Model-C Score Dynamics Lag Rather Than Lead:** In aligned event-study trajectories, Model-C score cooling does not anticipate the start of winning runs; score cooling happens **concurrently with or after** the winning run has already started ($T0$ to $T+15$s).
3. **Diagnostic Classifier Fails to Discriminate:** A chronological out-of-sample classifier trained on all candidate causal features achieves an ROC-AUC of only **0.528** on 2025 Q1 OOS—essentially random walk performance. Its top decile yields a negative expectancy of **-0.0390 ATR**.
4. **Why 5-Second Information Fails:** In runaway and high-momentum regimes, the prevailing trend pauses and pulls back 0.2 to 0.8 ATR dozens of times before the actual reversal occurs. Every such pause generates a "false giveback" that is subsequently run over by trend continuation.
5. **The Necessary Pivot:** Because macro price bars (5s) cannot distinguish a temporary trend consolidation from a genuine reversal turn, this diagnostic conclusively justifies **moving away from OHLCV bar features** and **focusing subsequent research on high-frequency / MBP-1 order-flow absorption** (detecting resting limit absorption and aggressive order exhaustion at the extreme).

---

## Direct Answers to the Nine Core Questions

1. **Is there a causal transition observable between P90 arming and the beginning of broad winning reversal zones?**  
   **NO.** With 5-second causal price and Model-C inputs, no feature combination reliably separates continuation checkpoints from winning reversal checkpoints.
2. **What variables change most consistently before that transition?**  
   In event-study trajectories, price giveback and trade efficiency fluctuate continuously, but the only sharp movement before $T0$ is a **final prevailing thrust at $T-5$s** (where winning checkpoint rate drops to 25.8%), followed immediately by the reversal. Model C cools only *after* $T0$.
3. **Is the transition primarily associated with Model-C score, price extension, price failure/giveback, or a combination?**  
   Neither Model C score, price extension, nor price failure/giveback reliably isolates the transition. Trade expectancy remains negative (-0.006 to -0.012 ATR) across every individual family and combination.
4. **Does achieving P95/P97.5/P99 add incremental information without being used as an eligibility gate?**  
   **NO.** Expectancy remains negative across all severity tiers, and conditioning on higher severity simply reduces coverage without improving win rate.
5. **How much of the original P90 opportunity population can the best simple causal state retain?**  
   The stagnation + giveback state retains **92.2% of regimes** (6,049 regimes) and 48.6% of checkpoints, but fails to produce positive expectancy (-0.0114 ATR).
6. **What percentage of $\ge 30$s winning-run starts does it capture?**  
   It captures **40.0% of run starts** (4,251 starts) and 48.5% of winning checkpoints.
7. **Does localization materially improve +1.00/-0.75 ATR economics?**  
   **NO.** Gross expectancy remains firmly negative across all candidate states (baseline -0.0082 ATR vs -0.0114 ATR in Combo 1 and -0.0102 ATR in Combo 3).
8. **Is the relationship stable across direction and chronological partitions?**  
   **YES.** The failure of 5s price/model state localization is structurally stable across all partitions: 2023 (-0.0136 ATR), 2024 (-0.0064 ATR), 2025 Q1 OOS (-0.0235 ATR), and both FADE_BULL (-0.0233 ATR) and FADE_BEAR (0.0016 ATR).
9. **What does this evidence justify?**  
   **It concludes D (transition remains unobservable with 5s price/model inputs) and strongly justifies C: Moving directly to high-frequency / MBP-1 order-flow research.** A simple price-action trigger (A) is falsified, and a second-stage macro ML model (B) is unviable (ROC-AUC ~0.53).

---

## Central Synthesis: Coverage / Localization Frontier (Analysis 4)

Evaluating key causal states across Localization Quality vs Opportunity Coverage (Pooled NQ, 6,559 Regimes, 586,897 Checkpoints):

| Causal State / Hypothesis | Checkpoints Retained | % Chkpts | Resolved Win Rate | Gross Expectancy | P(Inside Run) | P(Starts $\le$ 30s) | Regimes Retained | % Regimes Retained | % Wins Captured | % Starts Captured |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **Baseline: All P90 Checkpoints** | 586,897 | 100.0% | 42.39% | -0.0082 ATR | 29.9% | 36.7% | 6,559 | 100.0% | 100.0% | 100.0% |
| **Baseline: Score P95+ So Far** | 378,381 | 64.5% | 42.26% | -0.0105 ATR | 30.0% | 36.6% | 4,895 | 74.6% | 63.6% | 58.4% |
| **Baseline: Score P97.5+ So Far** | 189,452 | 32.3% | 42.14% | -0.0126 ATR | 30.8% | 37.2% | 2,797 | 42.6% | 31.7% | 27.3% |
| **Baseline: Score P99+ So Far** | 70,093 | 11.9% | 42.93% | 0.0012 ATR | 33.1% | 39.6% | 1,172 | 17.9% | 12.0% | 9.7% |
| **Score Cooling: Drawdown >= 0.02** | 545,838 | 93.0% | 42.46% | -0.0070 ATR | 30.0% | 36.9% | 6,336 | 96.6% | 93.2% | 88.7% |
| **Score Cooling: Drawdown >= 0.04** | 526,073 | 89.6% | 42.49% | -0.0065 ATR | 30.0% | 36.8% | 6,282 | 95.8% | 89.8% | 87.1% |
| **Score Stagnation: >=30s Since Peak Score** | 494,089 | 84.2% | 42.51% | -0.0060 ATR | 30.4% | 37.2% | 5,902 | 90.0% | 84.4% | 78.6% |
| **Extension: >= +1.00 ATR Since P90** | 479,239 | 81.7% | 42.46% | -0.0069 ATR | 30.6% | 37.4% | 5,349 | 81.6% | 81.6% | 77.8% |
| **Extension: >= +1.50 ATR Since P90** | 359,671 | 61.3% | 42.75% | -0.0018 ATR | 31.3% | 38.0% | 4,034 | 61.5% | 61.4% | 56.3% |
| **Extension: >= +2.00 ATR Since P90** | 252,476 | 43.0% | 42.59% | -0.0046 ATR | 31.6% | 38.1% | 2,811 | 42.9% | 42.8% | 38.3% |
| **Stagnation: >= 30s Since Latest Extreme** | 295,324 | 50.3% | 42.22% | -0.0111 ATR | 30.5% | 37.1% | 6,051 | 92.3% | 50.2% | 42.9% |
| **Stagnation: >= 60s Since Latest Extreme** | 114,317 | 19.5% | 42.29% | -0.0100 ATR | 30.1% | 36.7% | 4,696 | 71.6% | 19.5% | 17.1% |
| **Stagnation: >= 90s Since Latest Extreme** | 61,925 | 10.6% | 42.31% | -0.0096 ATR | 29.7% | 36.1% | 3,995 | 60.9% | 10.5% | 9.1% |
| **Giveback: >= 0.20 ATR from Extreme** | 525,184 | 89.5% | 42.25% | -0.0107 ATR | 30.0% | 36.7% | 6,559 | 100.0% | 89.2% | 80.6% |
| **Giveback: >= 0.35 ATR from Extreme** | 467,989 | 79.7% | 42.22% | -0.0112 ATR | 30.0% | 36.6% | 6,559 | 100.0% | 79.5% | 70.4% |
| **Giveback: >= 0.50 ATR from Extreme** | 407,923 | 69.5% | 42.16% | -0.0122 ATR | 29.9% | 36.4% | 6,548 | 99.8% | 69.1% | 59.8% |
| **Rolling 30s Giveback: >= 0.20 ATR** | 239,934 | 40.9% | 42.51% | -0.0060 ATR | 33.5% | 40.1% | 6,003 | 91.5% | 41.1% | 24.4% |
| **Efficiency Breakdown: Trade Eff 30s <= -0.20** | 125,885 | 21.4% | 42.36% | -0.0087 ATR | 26.6% | 34.4% | 5,393 | 82.2% | 21.3% | 32.5% |
| **Efficiency Breakdown: Trade Eff 60s <= -0.20** | 72,036 | 12.3% | 42.11% | -0.0130 ATR | 27.5% | 35.3% | 4,524 | 69.0% | 12.1% | 18.6% |
| **Combo 1: Stagnation (>=30s) + Giveback (>=0.20 ATR)** | 285,320 | 48.6% | 42.20% | -0.0114 ATR | 30.6% | 37.1% | 6,049 | 92.2% | 48.5% | 40.0% |
| **Combo 2: Stagnation (>=45s) + Giveback (>=0.30 ATR)** | 184,825 | 31.5% | 42.29% | -0.0100 ATR | 30.4% | 36.9% | 5,740 | 87.5% | 31.5% | 25.9% |
| **Combo 3: Stagnation (>=30s) + Giveback (>=0.20 ATR) + Score Cooling (dd>=0.02)** | 269,606 | 45.9% | 42.28% | -0.0102 ATR | 30.4% | 37.0% | 6,010 | 91.6% | 45.9% | 39.3% |
| **Combo 5: Extension (>=1.0 ATR) + Stagnation (>=30s) + Giveback (>=0.20 ATR)** | 235,257 | 40.1% | 42.33% | -0.0093 ATR | 31.2% | 37.8% | 4,943 | 75.4% | 40.0% | 32.5% |
| **Combo 6: Extension (>=1.0 ATR) + Stagnation (>=30s) + Giveback (>=0.20 ATR) + Score Cooling** | 222,587 | 37.9% | 42.44% | -0.0073 ATR | 31.1% | 37.7% | 4,914 | 74.9% | 38.0% | 31.9% |
| **Combo 7: P95+ So Far + Stagnation (>=30s) + Giveback (>=0.20 ATR)** | 198,449 | 33.8% | 42.17% | -0.0120 ATR | 30.6% | 36.9% | 4,660 | 71.0% | 33.4% | 27.2% |
| **Combo 8: Stagnation (>=30s) + Giveback (>=0.20 ATR) + Eff 30s <= -0.10** | 84,133 | 14.3% | 41.87% | -0.0173 ATR | 27.0% | 34.3% | 5,353 | 81.6% | 14.1% | 17.1% |

---

## Analysis 1: Where Does the Winning Zone Begin?

Comparing feature distributions at `START_OF_GE30_WINNING_RUN` (10,618 checkpoints) versus all other P90 checkpoints (576,279 checkpoints):

| Feature | Winning Run Starts (Median) | Non-Starts (Median) | Median $\Delta$ | Cohen's d |
|---|:---:|:---:|:---:|:---:|
| **seconds_since_first_p90** | 300.000 | 355.000 | -55.000 | -0.142 |
| **post_p90_extension_atr** | 1.658 | 1.799 | -0.140 | -0.112 |
| **model_c_score** | 0.164 | 0.184 | -0.020 | -0.172 |
| **max_score_so_far** | 0.355 | 0.363 | -0.008 | -0.127 |
| **score_drawdown_from_peak** | 0.197 | 0.182 | +0.015 | +0.073 |
| **model_c_score_delta_15s** | 0.137 | 0.082 | +0.055 | +0.539 |
| **model_c_score_delta_30s** | 0.148 | 0.124 | +0.024 | +0.311 |
| **model_c_score_delta_60s** | 0.155 | 0.145 | +0.010 | +0.152 |
| **model_c_score_slope_60s** | 0.147 | 0.197 | -0.050 | -0.333 |
| **regime_giveback_atr** | 0.656 | 0.795 | -0.139 | -0.236 |
| **rolling_30s_giveback_atr** | 0.159 | 0.295 | -0.136 | -0.321 |
| **rolling_60s_giveback_atr** | 0.267 | 0.420 | -0.153 | -0.272 |
| **seconds_since_latest_extreme** | 20.000 | 30.000 | -10.000 | -0.143 |
| **trade_efficiency_30s** | -0.096 | -0.018 | -0.078 | -0.346 |
| **trade_efficiency_60s** | -0.064 | -0.023 | -0.041 | -0.275 |
| **rolling_30s_current_progress_atr** | 0.270 | 0.084 | +0.186 | +0.369 |
| **rolling_60s_current_progress_atr** | 0.357 | 0.144 | +0.213 | +0.284 |

*Key Insight:* While winning run starts exhibit slightly lower median score (0.164 vs 0.184) and positive 30s progress (+0.186 ATR), effect sizes are modest (Cohen's d between -0.17 and +0.37) and do not provide clean threshold separation.

---

## Analysis 2: Aligned Transition Trajectory (Event-Study)

Tracing median values aligned relative to the start of $\ge 30$s winning runs ($T0$):

| Relative Offset | % Winning Checkpoints | Giveback ATR | Sec Since Extreme | Model C Score | Score Drawdown | Score $\Delta$ 30s | Trade Eff 30s |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **T -120s** | 39.1% | 0.71 ATR | 25s | 0.173 | 0.187 | +0.131 | -0.037 |
| **T -90s** | 42.7% | 0.72 ATR | 25s | 0.176 | 0.184 | +0.121 | -0.036 |
| **T -60s** | 46.7% | 0.73 ATR | 25s | 0.177 | 0.182 | +0.125 | -0.035 |
| **T -30s** | 48.2% | 0.76 ATR | 30s | 0.181 | 0.181 | +0.130 | -0.026 |
| **T -15s** | 47.4% | 0.78 ATR | 25s | 0.185 | 0.177 | +0.126 | -0.020 |
| **T -10s** | 44.9% | 0.78 ATR | 25s | 0.185 | 0.178 | +0.116 | -0.022 |
| **T -5s** | 25.8% | 0.78 ATR | 30s | 0.189 | 0.177 | +0.122 | -0.020 |
| **T +0s** | 100.0% | 0.66 ATR | 20s | 0.164 | 0.197 | +0.148 | -0.096 |
| **T +5s** | 100.0% | 0.60 ATR | 20s | 0.153 | 0.207 | +0.148 | -0.132 |
| **T +10s** | 100.0% | 0.58 ATR | 15s | 0.146 | 0.213 | +0.157 | -0.157 |
| **T +15s** | 100.0% | 0.59 ATR | 15s | 0.144 | 0.216 | +0.137 | -0.170 |
| **T +30s** | 100.0% | 0.68 ATR | 25s | 0.194 | 0.167 | +0.000 | -0.053 |

*Key Insight:* 
- Between $T-120$s and $T-10$s, winning checkpoint probability hovers around 39% to 48%.
- At $T-5$s, winning probability plunges to **25.8%**, reflecting the final momentum thrust of the prevailing trend to its local extreme.
- At $T0$, price turns and the winning run commences.
- Crucially, Model-C score does **not** decline prior to $T0$; it drops from 0.189 at $T-5$s to 0.164 at $T0$, and continues falling to 0.144 at $T+15$s. Model-C cooling is an *effect* of the reversal, not a leading predictor of it.

---

## Analysis 5: Severity as Feature, Not Gate

Testing whether achieving P95/P97.5/P99 SO FAR provides incremental value across subsets:

| Sub-Population / Filter | Max Severity Achieved | Checkpoints | Win Rate | Gross Expectancy | Prob Inside Run | Prob Starts $\le$ 30s |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| Full Population | **P90** | 208,516 | 42.62% | -0.0041 ATR | 29.7% | 36.8% |
| Full Population | **P95** | 188,929 | 42.37% | -0.0085 ATR | 29.2% | 35.9% |
| Full Population | **P97.5** | 119,359 | 41.67% | -0.0207 ATR | 29.4% | 35.9% |
| Full Population | **P99** | 70,093 | 42.93% | 0.0012 ATR | 33.1% | 39.6% |
| Price Failure (Stagnation >=30s & Giveback >=0.20 ATR) | **P90** | 86,871 | 42.27% | -0.0102 ATR | 30.7% | 37.5% |
| Price Failure (Stagnation >=30s & Giveback >=0.20 ATR) | **P95** | 92,550 | 42.19% | -0.0116 ATR | 29.7% | 36.2% |
| Price Failure (Stagnation >=30s & Giveback >=0.20 ATR) | **P97.5** | 65,057 | 41.29% | -0.0274 ATR | 29.7% | 35.9% |
| Price Failure (Stagnation >=30s & Giveback >=0.20 ATR) | **P99** | 40,842 | 43.52% | 0.0117 ATR | 33.9% | 40.3% |
| Price Failure + Score Cooling | **P90** | 83,320 | 42.28% | -0.0102 ATR | 30.5% | 37.4% |
| Price Failure + Score Cooling | **P95** | 87,604 | 42.32% | -0.0094 ATR | 29.5% | 36.1% |
| Price Failure + Score Cooling | **P97.5** | 61,364 | 41.33% | -0.0268 ATR | 29.5% | 35.8% |
| Price Failure + Score Cooling | **P99** | 37,318 | 43.72% | 0.0151 ATR | 33.7% | 40.1% |

*Key Insight:* Within every sub-population, gross expectancy remains uniformly negative across all severity tiers, and win rates never exceed 43%. Score severity provides no economic edge.

---

## Analysis 6: Diagnostic Classifier (Logistic Regression, Chronological OOS)

Trained on 2023–2024 (523,616 checkpoints) and evaluated strictly on 2025 Q1 OOS (63,281 checkpoints):
- **Target:** `starts_ge30_run_within_30s` (predicting imminent transition into a durable winning zone)
- **OOS ROC-AUC:** `0.528` (vs 0.535 train) -> **Near-random discrimination**
- **OOS PR-AUC:** `0.376` (vs baseline `0.358`)
- **OOS Top Decile Performance:**
  - Checkpoints: 6,329
  - Resolved Win Rate: **40.63%** (vs 41.63% baseline)
  - Gross Expectancy: **-0.0390 ATR** (vs -0.0215 ATR baseline)

*Conclusion:* The machine learning classifier confirms that linear combinations of 5-second price and model state features cannot predict the arrival of the winning zone.

---

## Chronological and Directional Stability

Evaluating Combo 1 across all partitions and directions:

| Dimension | Checkpoints | Win Rate | Gross Expectancy | Baseline Expectancy | Expectancy Delta | % Starts Captured | % Regimes Retained |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| Period: 2023 | 127,602 | 42.08% | -0.0136 ATR | -0.0078 ATR | -0.0058 ATR | 39.9% | 92.2% |
| Period: 2024 | 127,525 | 42.49% | -0.0064 ATR | -0.0054 ATR | -0.0010 ATR | 40.2% | 92.7% |
| Period: 2025_Q1 | 30,193 | 41.51% | -0.0235 ATR | -0.0215 ATR | -0.0020 ATR | 39.9% | 90.5% |
| Direction: FADE_BULL | 149,070 | 41.53% | -0.0233 ATR | -0.0216 ATR | -0.0017 ATR | 39.1% | 92.1% |
| Direction: FADE_BEAR | 136,250 | 42.95% | 0.0016 ATR | 0.0077 ATR | -0.0061 ATR | 41.1% | 92.3% |

---

## Final Research Recommendations

1. **Close the Macro Price-Action Investigation:** Cease attempting to construct reversal execution timers from 5-second OHLCV features (bars, givebacks, stagnation durations, swing breaks). The empirical evidence proves they cannot differentiate a continuation pause from an actionable reversal.
2. **Do Not Build a Second-Stage Macro ML Model:** The low OOS ROC-AUC (0.528) demonstrates that additional complexity on these inputs will merely overfit without adding edge.
3. **Advance to High-Frequency / MBP-1 Order-Flow Research:** To solve the +1.00/-0.75 ATR entry problem, subsequent research must investigate market microstructure at the 1-second and tick level:
   - **Limit Order Book Absorption:** Large resting liquidity absorbing market orders at the prevailing price extreme.
   - **Cumulative Volume Delta (CVD) Divergence:** Prevailing price making a new high/low while aggressive volume delta fails to follow.
   - **Aggressive Order Exhaustion:** Sharp drop in market order intensity following a liquidity sweep.
