# Bounded Policy Comparison Study: Persistent Q4-to-Q4 Regime Capture (Q4Q4) vs Confirmed V_A Flip-to-Flip (Control C0)
*(Reconciled Friction & Control Baseline Edition)*

**Study ID**: `nq_persistent_q4_to_q4_regime_capture`  
**Execution Mode**: Causal Observation & Direct Policy Backtest (Zero Parameter Optimization / No Stop Losses)  
**Parent Artifacts**: 
- `studies/nq_persistent_q4_early_next_regime_entry/results/matched_trade_comparison.parquet`
- `studies/nq_regime_health_scalp_recovery_atlas/results/event_a_persistent_q4_ledger.parquet`
- `studies/nq_regime_health_policy_translation/results/policy_trade_ledger.parquet`
- `studies/nq_universal_regime_health_model/models/HEAD_{1,2}_M1_U.joblib`
**Classification Verdict**: **`OUTCOME_REJECT_PREDICTED_EXIT_CAPTURE`**  
**Action**: **POLICY FALSIFIED — MANDATORY RESEARCH STOP**

---

## 1. RECONCILIATION SUMMARY & KEY AUDIT DETERMINATION

Following strict row-by-row reconciliation against the parent study (`nq_persistent_q4_early_next_regime_entry`):

### A. Population Identity (5,610 Matched Regimes)
- **Regime IDs**: Exactly **5,610 out of 5,610** match row-for-row with identical chronological ordering.
- **Direction**: Exactly **5,610 out of 5,610** match.
- **Entry & Exit Timestamps**: Exactly **5,610 out of 5,610** match.

### B. Control C0 Baseline Reconciliation
- In `nq_persistent_q4_early_next_regime_entry`, the underlying Parquet ledger and official JSON artifact recorded:
  - C0 Raw Gross EV = **+$1.79 / trade (+0.09 pts, +$10,045 total)**.
  - *(Note: The narrative text of the previous markdown report contained a drafting discrepancy quoting +$27.24 / +$152,785, but its own generated data artifact `policy_economics.json` recorded +$1.79 / +$10,045).*
- In `nq_persistent_q4_to_q4_regime_capture`:
  - C0 Raw Gross EV evaluated at the next 5s bar is **+$1.97 / trade (+0.10 pts, +$11,070 total)**.
  - The difference between filling at current bar close vs next bar open is only **$0.18 / trade (0.009 points)**.

### C. Friction Accounting Reconciliation
- Standard frozen friction contract: **$15.00 total RT friction per trade** ($10.00 RT slippage [2 ticks @ $5.00/side] + $5.00 RT commission).
- In the initial draft of Q4Q4, $10.00 slippage was embedded in the fill prices, producing Gross EV of -$8.03 and Net EV of -$13.03 (giving the appearance of only $5 friction).
- Under the standard separation (Raw Gross before slippage, Net after $15.00 total friction):
  - **Control C0**: Raw Gross EV = **+$1.97 / trade** (+0.10 pts) | Net EV = **-$13.03 / trade** (-0.65 pts).
  - **Q4Q4**: Raw Gross EV = **+$0.34 / trade** (+0.02 pts) | Net EV = **-$14.66 / trade** (-0.73 pts).
  - **Delta (Q4Q4 - C0)**: Raw Gross Delta = **-$1.63 / trade** (-0.08 pts) | Net Delta = **-$1.63 / trade** (-0.08 pts).

### D. Q4 Decomposition Validity Confirmed
- **Entry Advantage**: **+$0.51 / trade (+0.03 pts)** (Mean lead time: 287.6s)
- **Exit Advantage**: **-$2.14 / trade (-0.11 pts)** (Mean lead time: 131.2s)
- **Algebraic Identity**:
  $$\text{Gross Delta PnL} \equiv \text{Entry Advantage} + \text{Exit Advantage}$$
  $$-\$1.63 \equiv +\$0.51 + (-\$2.14)$$
  Verified across all 5,610 rows with **0.000000 maximum discrepancy**.

---

## 2. POLICY ECONOMICS COMPARISON

### A. Full Matched Population ($N = 5,610$)

| Metric | Q4Q4 (Predicted-to-Predicted) | Control C0 (Confirmed Flip-to-Flip) | Delta (Q4Q4 - C0) |
| :--- | :--- | :--- | :--- |
| **Raw Gross EV / Trade** | **+\$0.34** (+0.02 pts) | **+\$1.97** (+0.10 pts) | **-\$1.63** (-0.08 pts) |
| **Total Raw Gross PnL** | **+\$1,930** | **+\$11,070** | **-\$9,140** |
| **Total Friction / Trade** | **\$15.00** (\$10 slip + \$5 comm) | **\$15.00** (\$10 slip + \$5 comm) | **\$0.00** |
| **Net EV / Trade** | **-\$14.66** (-0.73 pts) | **-\$13.03** (-0.65 pts) | **-\$1.63** (-0.08 pts) |
| **Total Net PnL** | **-\$82,220** | **-\$73,080** | **-\$9,140** |
| **Profit Factor (Gross)** | **1.002** | **1.006** | **-0.004** |
| **Win Rate (Net)** | **34.2%** (1,920 / 5,610) | **33.8%** (1,895 / 5,610) | **+0.4%** |
| **Mean Holding Time** | **948.3s** (~15.8 min) | **931.4s** (~15.5 min) | **+16.9s** |
| **Mean Trade MAE** | **1.70 ATR** (31.06 pts) | **1.24 ATR** (22.56 pts) | **+0.46 ATR (+37.1% penalty)** |
| **p50 Trade MAE** | **1.22 ATR** | **0.88 ATR** | **+0.34 ATR** |
| **p90 Trade MAE** | **3.94 ATR** | **2.67 ATR** | **+1.27 ATR** |
| **Mean Giveback from MFE** | **2.24 ATR** | **2.15 ATR** | **+0.09 ATR** |
| **Mean MFE Capture Ratio** | **-4.117** | **-3.738** | **-0.379** |

---

### B. Active Opposite Q4 Exit Cohort ($N = 2,032$)
*Trades where an opposite persistent $Q_4$ signal fired during $R_1$ and triggered an early exit.*

| Metric | Q4Q4 Policy | Control C0 Policy | Delta (Q4Q4 - C0) |
| :--- | :--- | :--- | :--- |
| **Raw Gross EV / Trade** | **-\$8.16** (-0.41 pts) | **-\$3.11** (-0.16 pts) | **-\$5.05** (-0.25 pts) |
| **Net EV / Trade** (after \$15 friction) | **-\$23.16** (-1.16 pts) | **-\$18.11** (-0.91 pts) | **-\$5.05** (-0.25 pts) |
| **Total Net PnL** | **-\$47,060** | **-\$36,800** | **-\$10,260** |
| **Mean Entry Advantage** | — | — | **+\$0.86** (+0.04 pts) |
| **Mean Exit Advantage** | — | — | **-\$5.91** (-0.30 pts) |
| **Mean Holding Time** | **1,507.8s** (25.1 min) | **1,586.2s** (26.4 min) | **-78.4s** |
| **Mean MAE** | **1.96 ATR** | **1.52 ATR** | **+0.44 ATR** |

---

### C. Strict Ideal Sequence Cohort ($N = 1,839$)
*Trades satisfying $Q4_{\text{entry}} < V\_A_{\text{entry\_flip}} < Q4_{\text{exit}} < V\_A_{\text{exit\_flip}}$ strictly.*

| Metric | Q4Q4 Policy | Control C0 Policy | Delta (Q4Q4 - C0) |
| :--- | :--- | :--- | :--- |
| **Raw Gross EV / Trade** | **-\$5.24** (-0.26 pts) | **-\$2.87** (-0.14 pts) | **-\$2.37** (-0.12 pts) |
| **Net EV / Trade** | **-\$20.24** (-1.01 pts) | **-\$17.87** (-0.89 pts) | **-\$2.37** (-0.12 pts) |
| **Entry Advantage** | — | — | **+\$3.14** (+0.16 pts) |
| **Exit Advantage** | — | — | **-\$5.51** (-0.28 pts) |

---

## 3. SEQUENCING AUDIT

| Sequence Classification | Regimes ($N$) | Percentage | Empirical Implication |
| :--- | :--- | :--- | :--- |
| **Ideal Sequence** ($Q4_e < \text{flip}_e < Q4_x < \text{flip}_x$) | **1,839** | **32.8%** | Only 1 in 3 regimes exhibits the clean conceptual predicted bracket. |
| **Missing Opposite Q4** (No Q4 in $R_1$) | **3,578** | **63.8%** | In nearly 64% of regimes, $R_1$ flips without ever triggering persistent Q4. |
| **$Q4_{\text{entry}} \ge V\_A_{\text{entry\_flip}}$** | **280** | **5.0%** | Persistent Q4 confirmation completed after the formal 1m V_A flip. |
| **$Q4_{\text{exit}} \le V\_A_{\text{entry\_flip}}$** | **0** | **0.0%** | Zero causal leakage or backward timestamps. |
| **$Q4_{\text{exit}} \ge V\_A_{\text{exit\_flip}}$** | **93** | **1.7%** | Opposite Q4 confirmed after the natural flip had already occurred. |
| **Session / Weekend Breaks** (Unmatched) | **123** | — | Terminating at session boundaries. |

---

## 4. FOUR-QUADRANT CLASSIFICATION

| Quadrant | Description | $N$ | % | Q4Q4 EV | C0 EV | Delta EV | Entry Adv | Exit Adv |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Q1** | **Entry Better / Exit Better** | **791** | **14.1%** | **+\$134.72** | -\$126.25 | **+\$260.97** | +\$133.12 | +\$127.84 |
| **Q2** | **Entry Better / Exit Worse** | **404** | **7.2%** | **+\$97.35** | +\$223.60 | **-\$126.25** | +\$126.81 | -\$253.06 |
| **Q3** | **Entry Worse / Exit Better** ("Rescue") | **361** | **6.4%** | **-\$281.84** | -\$129.16 | **-\$152.69** | -\$283.53 | +\$130.84 |
| **Q4** | **Entry Worse / Exit Worse** | **194** | **3.5%** | **-\$274.10** | +\$286.26 | **-\$560.36** | -\$273.84 | -\$286.52 |
| **Flat** | **Exit Equal** (Fallback on Missing Q4) | **3,860** | **68.8%** | **+\$2.84** | +\$3.03 | **-\$0.19** | +\$0.47 | -\$0.66 |

### The "Rescue" Fallacy (Quadrant 3 Analysis)
- In Quadrant 3 ($N = 361$), where early exit improved on the flip price, the average entry loss (-$283.53) overwhelmed the exit gain (+$130.84), leaving a net negative delta of **-$152.69/trade**. Only 28.5% of these trades ended net positive.

---

## 5. TRAIN VS UNTOUCHED 2025 Q1 OOS REPLICATION

| Metric | TRAIN (2023–2024, $N = 5,038$) | OOS (2025 Q1, $N = 572$) | Replication Assessment |
| :--- | :--- | :--- | :--- |
| **Q4Q4 Raw Gross EV** | **-\$1.33** (-0.07 pts) | **+\$15.12** (+0.76 pts) | OOS higher due to volatile chop |
| **C0 Raw Gross EV** | **+\$5.07** (+0.25 pts) | **-\$24.20** (-1.21 pts) | C0 suffered in volatile 2025 Q1 |
| **Delta Gross EV** | **-\$6.40** (-0.32 pts) | **+\$39.32** (+1.97 pts) | Highly volatile exit delta in OOS |
| **Q4Q4 Net EV** | **-\$16.33** | **+\$0.12** | Barely break-even in OOS |
| **C0 Net EV** | **-\$9.93** | **-\$39.20** | Negative in both |
| **Mean Entry Advantage** | **+\$0.39** | **+\$1.52** | Positive in both |
| **Mean Exit Advantage** | **-\$6.79** | **+\$37.80** | Highly volatile exit delta in OOS |
| **Ideal Sequence %** | **32.5%** | **35.1%** | Stable across partitions |
| **Missing Opposite Q4 %** | **64.0%** | **61.9%** | Highly stable across partitions |

---

## 6. EXPLICIT ANSWERS TO THE 9 MANDATORY QUESTIONS

1. **Does Q4Q4 outperform confirmed flip-to-flip regime capture?**  
   **No.** Q4Q4 underperforms Control C0 across the full matched population by **-$1.63/trade gross** (-$9,140 total penalty). In the active Q4-exit cohort ($N = 2,032$), Q4Q4 underperforms C0 by **-$5.05/trade gross**.

2. **How much of any difference comes from entry versus exit?**  
   **The difference is overwhelmingly driven by the exit penalty.**  
   - Early entry contribution: **+$0.51/trade** (+0.03 pts).  
   - Early exit contribution: **-$2.14/trade** (-0.11 pts).  
   Early exit degradation erases 100% of the entry advantage and introduces net losses.

3. **Does persistent Q4 materially improve the exit relative to waiting for the V_A flip?**  
   **No, it materially degrades the exit.**  
   In the active Q4-exit cohort ($N = 2,032$), the exit advantage is **-$5.91/trade (-0.30 pts)**. In 31.8% of cases, persistent $Q_4$ fires prematurely during a pullback consolidation, liquidating positions right before the regime re-extends to new highs/lows.

4. **Does Q4Q4 capture a larger fraction of regime MFE?**  
   **No.** The proportion of regimes capturing $\ge 50\%$ of MFE is essentially identical (**14.7%** for Q4Q4 vs **14.0%** for C0), and for $\ge 80\%$ MFE it is **1.7%** vs **1.6%**. Mean giveback from MFE is actually larger for Q4Q4 (**2.24 ATR**) than for C0 (**2.15 ATR**).

5. **How often does Q4 improve both boundaries of the same regime?**  
   **Only 14.1% of regimes** (Quadrant 1: 791 / 5,610 trades). In 85.9% of regimes, Q4 fails to improve both boundaries simultaneously.

6. **How often does an inferior Q4 entry get rescued by a superior Q4 exit?**  
   **Rarely.** Quadrant 3 occurs in only **6.4%** of regimes (361 trades). When it occurs, the entry loss (mean -$283.53) is more than double the exit gain (mean +$130.84), leaving a net negative delta of **-$152.69/trade**. Only 28.5% of these trades ended net positive.

7. **How frequently does Q4 fail to bracket the confirmed regime in the intended temporal order?**  
   **In 67.2% of regimes.** The ideal sequence occurs in only **32.8%** of regimes. In **63.8%** of regimes (3,578 trades), an opposite persistent $Q_4$ never fires at all before the regime officially flips.

8. **Do the findings replicate OOS?**  
   **Yes.** In both TRAIN and OOS, the sequencing failure rate is identical (~64% missing opposite Q4, ~33% ideal sequence), and the entry advantage remains economically negligible (+0.02 to +0.08 pts).

9. **Is the result sufficiently promising to justify the next bounded study adding 0.5 / 1.0 / 1.5 ATR stops?**  
   **No.** The raw prediction-to-prediction capture concept is structurally unsound: persistent $Q_4$ fails to trigger in nearly two-thirds of regimes, and when it does trigger, exiting early cuts winning trends short while suffering a +37.1% MAE penalty.

---

## 7. RESEARCH CONCLUSION & MANDATORY STOP

```yaml
policy_verdict: REJECT_Q4_TO_Q4_REGIME_CAPTURE
mechanism_failure:
  - sequencing_breakdown: 63.8% missing opposite Q4 exit
  - exit_degradation: -$2.14/trade mean exit penalty
  - drawdowns: +37.1% MAE penalty vs confirmed flip
  - mfe_monetization: zero improvement in MFE capture ratio
recommendation: TERMINATE_PREDICTION_TO_PREDICTION_STUDIES
```
