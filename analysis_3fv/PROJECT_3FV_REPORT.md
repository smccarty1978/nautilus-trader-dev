# PROJECT 3F-V: ADVERSARIAL CAUSAL VALIDATION OF THE 1-SECOND REVERSAL TRIGGER
## Comprehensive Falsification & Validation Report

---

## 1. TERMINAL VERDICT

```
VERDICT: 3F_MATCHED_EVENT_ONLY_NOT_LIVE_TRIGGER
```

**Verdict Summary:**
The Project 3F edge exists strictly as a retrospective matched-event discriminator (50% synthetic prevalence) between known T0 reversal starts and known continuation pauses. When scanned continuously across all eligible P90 seconds in the natural population, the frozen rules repeatedly fire during trending regimes, incurring severe false positive decay and negative/untradeable economics.

The single question Project 3F-V set out to answer was:
> **Does the Project 3F 1-second edge still exist when the algorithm does not know where $T0$ is?**

The rigorous empirical answer is: **NO.**
The reported 3F edge (e.g. `THRUST_EXHAUSTION_REJECTION` Win Rate = 73.3%, Expectancy = +0.5333 ATR, OOS ROC-AUC = 0.7655) was an artifact of **retrospective matched-event sampling** (50% synthetic prevalence between known $T0$ winning-run starts and known continuation pauses selected with future lookahead). When evaluated on the complete, continuous natural population of P90-armed regimes where the algorithm receives every 1-second observation sequentially without knowing whether a turning point exists, the frozen rules suffer severe false-positive flooding during ongoing trends, destroying the headline economics.

---

## 2. WHAT SURVIVED FROM 3F

1. **Micro-Structure Divergence at Known Turning Points:**
   - When an actual durable reversal ($T0$) occurs, price action in the final 2 seconds ($T-2$ to $T0$) genuinely displays rejection wick expansion, momentum collapse, and lack of follow-through. The physical anatomy described in 3F at the turn is verified.
2. **Diagnostic Event Discrimination:**
   - In a synthetic 50/50 matched population of true turning points vs continuation pauses, 1-second OHLCV features discriminate substantially better than 5-second aggregated bars (OOS ROC-AUC = 0.7655 vs 0.5280).
3. **Causal Integrity of Feature Formulations:**
   - The feature calculations themselves (returns, ranges, wicks, volume acceleration) are causally computable at bar close without future data. The causal leakage audit confirmed all 12 executable assertions.

---

## 3. WHAT DID NOT SURVIVE

1. **Standalone Causal Tradability in Natural Streaming:**
   - `THRUST_EXHAUSTION_REJECTION`: In 3F, it was evaluated only on 21,236 matched checkpoints and fired 150 times with a 73.3% win rate (+0.5333 ATR). In the natural population of 3,703,806 seconds across 6,559 regimes, it fires **20,203 times**.
   - Natural pooled win rate collapses to **42.9%**, and gross expectancy collapses from **+0.5333 ATR** to **+0.0008 ATR**.
   - 2025 Q1 OOS expectancy collapses to **+0.0204 ATR**.
2. **First Trigger per Regime Localization:**
   - Evaluating first trigger only per regime does not salvage the rule: pooled win rate is **42.6%**, gross expectancy is **-0.0052 ATR**, and 2025 Q1 OOS expectancy is **+0.0233 ATR**.
   - Of the first triggers, **653** fire in regimes that never produce a $\ge 30	ext{s}$ winning run, and **1,544** fire prematurely before the true winning zone begins.
3. **The Other Interpretable States:**
   - `VOLUME_ABSORPTION`: Natural all-triggers expectancy collapses from +0.4717 ATR to **+0.0165 ATR** (2025 Q1: **+0.0444 ATR**).
   - `EXTREME_SPIKE_REVERSAL`: Natural all-triggers expectancy collapses from +0.3752 ATR to **+0.0270 ATR** (2025 Q1: **+0.0442 ATR**).
4. **Classifier Live Causality:**
   - The diagnostic classifier cannot function in live streaming without knowing event boundaries; its reported top-decile 87% win rate is entirely an artifact of 50% matched prevalence.
5. **MBP-1 Incremental Edge:**
   - MBP-1 status is strictly `INCONCLUSIVE` (tested on only N=100 samples with shuffled CV, and PR-AUC deteriorated by -11.7%).

---

## 4. NATURAL-POPULATION RESULTS

### Table 1: Population Overview & Trigger Frequency
| Rule | Natural Triggers | Unique Regimes Triggered | % Regimes Triggered | Mean Triggers / Regime | Max Triggers / Regime | Winning Starts Captured | Capture Rate |
|---|---|---|---|---|---|---|---|
| `THRUST_EXHAUSTION_REJECTION` | 20,203 | 3,471 | 52.9% | 5.82 | 79 | 1142 | 10.8% |
| `VOLUME_ABSORPTION` | 37,246 | 4,464 | 68.1% | 8.34 | 41 | 1864 | 17.6% |
| `EXTREME_SPIKE_REVERSAL` | 35,443 | 4,453 | 67.9% | 7.96 | 48 | 1730 | 16.3% |

### Table 2: Natural Economics (Next-Bar-Open Execution)
| State / Evaluation Mode | Sample Size ($N$) | Win Rate | Gross Expectancy (ATR) | 2023 Exp | 2024 Exp | 2025 Q1 OOS Exp | Mean MFE | Mean MAE |
|---|---|---|---|---|---|---|---|---|
| **THRUST_EXHAUSTION_REJECTION** | | | | | | | | |
| *3F Matched Event (Reported)* | 150 | 73.3% | +0.5333 | +0.5962 | +0.4596 | +0.5917 | — | — |
| *Natural: All Triggers* | 20,203 | 42.9% | **+0.0008** | -0.0132 | -0.0035 | **+0.0204** | 15.98 | 17.42 |
| *Natural: First Trigger Only* | 3,471 | 42.6% | **-0.0052** | -0.0045 | -0.0155 | **+0.0233** | 12.53 | 13.13 |
| **VOLUME_ABSORPTION** | | | | | | | | |
| *3F Matched Event (Reported)* | 997 | 69.8% | +0.4717 | +0.4448 | +0.5106 | +0.4217 | — | — |
| *Natural: All Triggers* | 37,246 | 43.8% | **+0.0165** | +0.0072 | +0.0187 | **+0.0444** | 10.71 | 11.04 |
| *Natural: First Trigger Only* | 4,464 | 43.2% | **+0.0062** | +0.0121 | -0.0061 | **+0.0330** | 10.56 | 10.99 |
| **EXTREME_SPIKE_REVERSAL** | | | | | | | | |
| *3F Matched Event (Reported)* | 1,126 | 64.3% | +0.3752 | +0.3379 | +0.3937 | +0.4661 | — | — |
| *Natural: All Triggers* | 35,443 | 44.4% | **+0.0270** | +0.0238 | +0.0257 | **+0.0442** | 11.21 | 11.31 |
| *Natural: First Trigger Only* | 4,453 | 44.8% | **+0.0343** | +0.0372 | +0.0270 | **+0.0530** | 10.60 | 11.04 |

---

## 5. EXECUTION-TIMING RESULTS

Comparing theoretical decision-close entry ($C_t$, zero execution latency) vs realistic executable entry ($O_{t+1}$, next 1s bar open):

### Table 3: Execution Degradation (Pooled All Triggers)
| Rule | Decision Close WR | Decision Close EV | Next Open WR | Next Open EV | Degradation (ΔEV) |
|---|---|---|---|---|---|
| `THRUST_EXHAUSTION_REJECTION` | 32.7% | -0.1772 ATR | 42.9% | +0.0008 ATR | +0.1780 ATR |
| `VOLUME_ABSORPTION` | 34.8% | -0.1418 ATR | 43.8% | +0.0165 ATR | +0.1583 ATR |
| `EXTREME_SPIKE_REVERSAL` | 35.6% | -0.1267 ATR | 44.4% | +0.0270 ATR | +0.1538 ATR |

Executing at next-bar open introduces substantial negative slippage/adverse selection because the trigger bar itself closed strongly in the fade direction. However, even with zero-latency close entry, the rules remain severely sub-commercial due to false-positive overfiring during trending regimes.

---

## 6. 2025 Q1 OOS RESULTS

Because 2025 Q1 was strictly untouched by threshold development:
- **`THRUST_EXHAUSTION_REJECTION` All Triggers 2025 Q1:** Expectancy = **+0.0204 ATR**, Win Rate = **44.0%** ($N = 5627$).
- **`THRUST_EXHAUSTION_REJECTION` First Trigger 2025 Q1:** Expectancy = **+0.0233 ATR**, Win Rate = **44.2%** ($N = 559$).
- Across both directions (FADE_BULL: +0.0264 ATR; FADE_BEAR: +0.0202 ATR), the edge fails to materialize in out-of-sample trading.

---

## 7. CAUSAL AUDIT

All 12 executable assertions in `causal_audit.json` passed with zero critical violations:
1. `feature_timestamp_availability`: PASS (all triggers satisfy $ts_{trig} \ge ts_{p90\_arm}$)
2. `current_bar_completion_semantics`: PASS (decisions on completed $C_t$; entry at $O_{t+1}$)
3. `running_extreme_causality`: PASS ($sec\_since\_extreme \ge 0$ throughout)
4. `no_future_regime_extreme`: PASS (running extrema only)
5. `label_isolation`: PASS (raw trigger ledger frozen with SHA256: `eb5ae2cbeab5d973...`)
6. `train_oos_isolation`: PASS (zero parameter tuning)
7. `event_matching_isolation`: PASS (evaluated on natural continuous timeline)
8. `duplicate_event_handling`: PASS (all triggers vs first trigger tracked)
9. `p90_arm_timestamp_causality`: PASS (starts at causal P90 arming)
10. `entry_after_decision`: PASS ($t_{entry} \ge t_{decision} + 1	ext{s}$)
11. `outcome_join_after_trigger_freeze`: PASS (ledger frozen prior to trade attachment)
12. `native_unfilled_1s_catalog`: PASS (sourced from `NQ_1S_V2_GLOBEX`)

---

## 8. IMPLICATION FOR NEXT RESEARCH STEP

1. **Do Not Trade 3F 1-Second Triggers Standalone:**
   The belief that 1-second price action alone solves the P90 reversal entry timing is falsified. The 1-second triggers cannot filter false exhaustion points during strong momentum continuation.
2. **Do Not Attempt MBP-1 Rescue:**
   MBP-1 cannot rescue a trigger that overfires by orders of magnitude across millions of non-turning seconds.
3. **Correct Architectural Framing:**
   A reversal transition cannot be localized purely by local micro-exhaustion patterns without a macro confirmation structure (e.g. regime boundary break, dual-timeframe momentum convergence, or higher-timeframe absorption). Local 1-second price action describes *how* a turn looks once it occurs, but cannot predict *that* a turn will occur rather than pause.
