# 2025 Q2 EXIT-ARCHITECTURE COMPARISON REPORT: C1 BASELINE VS. PURE CONFIRMED REGIME-FLIP EXIT

**Study Identifier:** `studies/nq_h050_q2_c1_vs_regime_flip_exit`  
**Execution Environment:** Streaming NautilusTrader `BacktestEngine` (Hedging OMS, Margin Account, 1s CME Data)  
**Evaluation Window:** 2025 Q2 (`2025-04-01 00:00:00` to `2025-06-30 23:59:59` UTC)  
**Total Census Data:** 3,163,350 CME 1-second bars  
**Tested Architectures:**
1. **C1 Baseline (Control):** $H050_0$ entry $\to$ wait for $R_1$ confirmation $\to$ first opposing $H050_1$ after $R_1$ if present; otherwise $R_2$ fallback exit.
2. **Pure Confirmed Regime-Flip Exit:** Same $H050_0$ entry $\to$ ignore $H050_1$ entirely $\to$ hold until first opposite confirmed V_A regime flip ($R_2$ flip at `r1_end_ts`).

**Friction Standard:** Exact institutional friction: 1 tick entry slippage ($5.00), 1 tick exit slippage ($5.00), $5.00 RT commission = **$15.00 RT / 0.75 NQ pts**  

---

## 1. Executive Summary & Core Comparison

This diagnostic study evaluates whether the 2025 Q2 weakness in the NQ H050 strategy was driven by the underlying $H050_0$ entry population itself or by the $C_1$ ($H050_1$) exit mechanism cutting trades prematurely before the confirmed $V_A$ regime flip.

Both exit architectures were executed through the streaming NautilusTrader `BacktestEngine` on identical 1-second bar sequencing, identical order types, identical fill models, and identical entry executions (confirmed `ENTRY_PARITY_PASS` with 0 ns timestamp diff and 0.00 fill price diff across all 8,087 trades).

### Primary Scorecard: Active Top 10% Cohort ($N=1,083$)

| Metric | C1 Baseline (Control) | Pure Regime Flip Exit | Delta (Pure - C1) | Interpretation |
|---|:---:|:---:|:---:|---|
| **Trade Count ($N$)** | 1,083 | 1,083 | 0 | Exact match |
| **Mean Net PnL (ATR / trade)** | **-0.1336** | **-0.1799** | **-0.0463** | C1 is superior in mean EV |
| **Median Net PnL (ATR / trade)** | **+0.3676** | **-0.2556** | **-0.6232** | C1 massive +0.62A median boost |
| **Total Net Dollars ($)** | -$66,565 | -$65,520 | +$1,045 | Approximately equal dollars |
| **Win Rate (%)** | **61.7%** | **42.1%** | **-19.6%** | C1 delivers +19.6% win rate |
| **Profit Factor** | 0.82 | 0.83 | +0.01 | Strategy unprofitable in Q2 |
| **Max Drawdown (ATR)** | **147.47** | **210.34** | **+62.87** | Pure worsens DD by +42.6% |
| **Max Drawdown ($)** | **$67,210** | **$82,580** | **+$15,370** | Pure worsens dollar DD |
| **10th Percentile Net ATR** | **-2.5353** | **-2.7848** | **-0.2495** | C1 cushions left tail |
| **5th Percentile Net ATR** | **-3.8631** | **-4.6298** | **-0.7667** | C1 cushions extreme tail |
| **Losses $\le -1.00$A** | **230** | **338** | **+108 (+47.0%)** | Pure has 108 more large losses |
| **Losses $\le -2.00$A** | **144** | **196** | **+52 (+36.1%)** | Pure has 52 more severe losses |
| **Losses $\le -3.00$A** | **86** | **100** | **+14 (+16.3%)** | Pure has 14 more catastrophe losses |
| **Winners $\ge +1.00$A** | **272** | **259** | **-13** | C1 produces more +1A winners |
| **Winners $\ge +2.00$A** | 54 | 144 | +90 | Pure allows runners to reach +2A |
| **Winners $\ge +3.00$A** | 10 | 98 | +88 | Pure allows runners to reach +3A |

---

## 2. Important Semantic Verification & Lifecycle Definition

### What Constitutes the Pure Confirmed Regime-Flip Exit?

In the validated streaming runtime:
1. **$H050_0$ Entry**: Occurs during incumbent regime $R_0$ (which is adverse to the trade thesis). Counter-direction is $C = -D_0$.
2. **$R_1$ Confirmation (`r0_end_ts`)**: Regime $R_0$ terminates and flips to $R_1$ ($D_1 = C$). This event confirms the thesis and moves in favor of the trade.
3. **During $R_1$**: Price advances and eventually experiences a minor pullback.
   - **In C1 Architecture**: At the very first bar where giveback from the $R_1$ peak reaches 0.50 ATR, an opposing $H050_1$ checkpoint is emitted. C1 immediately exits on the next bar.
   - **In Pure Architecture**: The strategy ignores all $H050_1$ signals, holding through pullbacks.
4. **$R_2$ Confirmed Flip (`r1_end_ts`)**: Regime $R_1$ terminates and flips to $R_2$ ($D_2 = -C$). This is the **first opposite confirmed regime flip relative to the trade direction**.
   - The Pure exit executes a market order to close the position at the first bar where `ts >= r1_end_ts`.

This strictly adheres to causal confirmed V_A event semantics:
- It does **not** use the raw/unconfirmed flip.
- It does **not** exit at $R_1$ (which would prematurely close at entry breakeven).
- It does **not** use synthetic end-of-bar prices, but executes live through NautilusTrader OMS fills.

---

## 3. Trade-Level Paired Comparison ($N=1,083$)

Because entry executions, prices, and timestamps are bit-for-bit identical, every trade forms an exact paired observation:

- **Trades where C1 Improved PnL:** **761 trades (70.3%)**
- **Trades where Pure Improved PnL:** **319 trades (29.5%)**
- **Exact Ties:** **3 trades (0.3%)**
- **Mean Paired ATR Delta (Pure - C1):** **-0.0463 ATR** (C1 ahead by +0.0463 ATR / trade)
- **Median Paired ATR Delta (Pure - C1):** **-0.5704 ATR** (C1 ahead by +0.5704 ATR / trade)
- **Total Net Dollar Delta:** **+$1,045** (-$65,520 Pure vs -$66,565 C1)

### Exit Timing & Mechanism Decomposition
- **Active $H050_1$ Exits:** In 2025 Q2, an opposing $H050_1$ fired before $R_2$ on **1,083 out of 1,083 trades (100.0%)**.
- **Exit Lead Time:**
  - Median Lead Time from $H050_1$ to $R_2$: **526.0 seconds (8.8 minutes)**.
  - Mean Lead Time: **785.2 seconds (13.1 minutes)**.
  - 10th Percentile: 108.2 seconds; 90th Percentile: 1,765.4 seconds (29.4 minutes).
- **Excursion Dynamics (Between $H050_1$ and $R_2$):**
  - **Favorable Continuation Sacrificed by C1:** Mean = **1.90 ATR** (Median = **1.07 ATR**, P90 = **4.64 ATR**).
  - **Adverse Movement Avoided by C1:** Mean = **1.04 ATR** (Median = **0.92 ATR**, P90 = **1.98 ATR**).
  - **Saved Giveback Realized by C1:** Mean = **+0.0463 ATR** (Median = **+0.5704 ATR**).

---

## 4. Directional Analysis: Counter-LONG vs. Counter-SHORT

The pooled results conceal an extraordinary directional polarization:

| Metric | Counter-LONG ($N=413$) | Counter-SHORT ($N=670$) |
|---|:---:|:---:|
| **C1 Baseline Mean ATR** | -0.0305 ATR (-$12,555) | -0.1972 ATR (-$54,010) |
| **Pure Regime Flip Mean ATR** | **+0.0692 ATR (+$23,405)** | **-0.3334 ATR (-$88,925)** |
| **Delta (Pure - C1) Mean ATR** | **+0.0996 ATR** | **-0.1362 ATR** |
| **Delta (Pure - C1) Net Dollars** | **+$35,960** | **-$34,915** |
| **C1 Win Rate** | 65.1% | 59.6% |
| **Pure Win Rate** | 46.2% | 39.6% |
| **C1 Profit Factor** | 0.96 | 0.73 |
| **Pure Profit Factor** | **1.07** | 0.69 |
| **Trades Where Pure Improved** | 158 (38.3%) | 161 (24.0%) |
| **Trades Where C1 Improved** | 255 (61.7%) | **506 (75.5%)** |

### Key Directional Insights:
1. **Counter-LONG Trades Benefit from Holding to $R_2$:**
   - Under Pure Regime Flip, Counter-LONG is net profitable (+0.0692 ATR / +$23,405) with PF 1.07.
   - C1 cuts long runners too early: Pure generates +$35,960 more in profit by capturing extended upward momentum.
2. **Counter-SHORT Trades Are Crushed by Holding to $R_2$:**
   - Under Pure Regime Flip, Counter-SHORT suffers catastrophic decay (-0.3334 ATR / -$88,925).
   - On 75.5% of short trades, C1 is vastly superior. In a structural bull regime like 2025, counter-trend short pullbacks evaporate quickly; holding short positions into confirmed $R_2$ flips results in severe adverse giveback.

---

## 5. Month-by-Month Temporal Breakdown

| Month | Top 10 Trades | C1 Mean ATR | Pure Mean ATR | Delta ATR | C1 Net Dollars | Pure Net Dollars | Dollar Delta |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **2025-04 (April)** | 483 | -0.1587 | -0.3339 | **-0.1752** | -$48,055 | -$68,325 | **-$20,270** |
| **2025-05 (May)** | 327 | +0.0657 | +0.2916 | **+0.2259** | +$2,725 | +$28,440 | **+$25,715** |
| **2025-06 (June)** | 273 | -0.3279 | -0.4722 | **-0.1443** | -$21,235 | -$25,635 | **-$4,400** |
| **Full 2025 Q2** | **1,083** | **-0.1336** | **-0.1799** | **-0.0463** | **-$66,565** | **-$65,520** | **+$1,045** |

### Temporal Dynamics:
- **April (Volatile / Choppy):** C1 heavily protected the strategy, saving -$20,270 versus Pure. 72.0% of trades were better under C1.
- **May (Trending Counter-Regimes):** Pure Regime Flip strongly outperformed (+0.2916 ATR vs +0.0657 ATR, +$25,715 gain) as extended counter-moves ran without giving back.
- **June (Macro Headwind):** Both architectures lost, but C1 was less negative (-0.3279 ATR vs -0.4722 ATR, saving +$4,400).

---

## 6. Full Population Context ($N=8,087$)

| Metric | C1 Baseline | Pure Regime Flip Exit | Delta (Pure - C1) |
|---|:---:|:---:|:---:|
| **Total Trades** | 8,087 | 8,087 | 0 |
| **Mean Net PnL (ATR / trade)** | -0.1939 | -0.1101 | **+0.0838** |
| **Total Net Dollars ($)** | -$678,120 | -$247,575 | **+$430,545** |
| **Win Rate (%)** | 62.2% | 48.4% | -13.8% |
| **Profit Factor** | 0.82 | 0.92 | +0.10 |
| **Max Drawdown (ATR)** | 2,252.0 | 1,555.0 | -697.0 |
| **Max Drawdown ($)** | $776,500 | $525,845 | -$250,655 |
| **Super Runners ($\ge +3.00$A)** | 377 | 1,077 | **+700** |

Across the unconditional census, holding to $R_2$ unlocked massive runner gains (+700 super runners), reducing total loss by $430,545. However, in the **curated Top 10% cohort** (which filters specifically for high-probability, quick-exhaustion reversals), C1's giveback-protection mechanism is what preserved the win rate and capped drawdown.

---

## 7. Explicit Decision Answers

### 1. What was Q2 Top-10% EV using C1?
**-0.1336 ATR / trade** (-$66,565 total net dollars; median **+0.3676 ATR**, win rate **61.7%**, profit factor **0.82**).

### 2. What was Q2 Top-10% EV using pure confirmed regime-flip exit?
**-0.1799 ATR / trade** (-$65,520 total net dollars; median **-0.2556 ATR**, win rate **42.1%**, profit factor **0.83**).

### 3. What was the paired ATR difference per trade?
- **Mean Paired Delta (Pure - C1):** **-0.0463 ATR / trade** (C1 outperformed by +0.0463 ATR).
- **Median Paired Delta (Pure - C1):** **-0.5704 ATR / trade** (C1 outperformed by +0.5704 ATR).

### 4. What was the total dollar difference?
**+$1,045** (-$65,520 for Pure vs -$66,565 for C1). Pure made $1,045 more in net dollars due to high-ATR runners in May, despite worse mean ATR.

### 5. Did C1 improve or worsen max drawdown?
C1 **greatly improved** Max Drawdown:
- C1 Max DD was **147.47 ATR** ($67,210).
- Pure Max DD was **210.34 ATR** ($82,580).
- Holding to Pure worsened Max Drawdown by **+62.87 ATR (+42.6%)** and **+$15,370 in dollars**.

### 6. Did C1 improve or worsen P5/P10?
C1 **improved** both left-tail percentiles:
- 10th Percentile: C1 was **-2.5353 ATR** vs Pure **-2.7848 ATR** (+0.25 ATR cushion).
- 5th Percentile: C1 was **-3.8631 ATR** vs Pure **-4.6298 ATR** (+0.77 ATR cushion).

### 7. Did C1 reduce large losses?
**Yes, decisively:**
- Losses $\le -1.00$A: 230 (C1) vs 338 (Pure) $	o$ C1 prevented **108** large losses.
- Losses $\le -2.00$A: 144 (C1) vs 196 (Pure) $	o$ C1 prevented **52** severe losses.
- Losses $\le -3.00$A: 86 (C1) vs 100 (Pure) $	o$ C1 prevented **14** catastrophic losses.

### 8. Did C1 sacrifice large winners?
**Yes, on the extreme right tail:**
- Big winners ($\ge +2.00$A): 54 (C1) vs 144 (Pure) $	o$ Pure had 90 more big winners.
- Super runners ($\ge +3.00$A): 10 (C1) vs 98 (Pure) $	o$ Pure had 88 more super runners.
- However, for $+1.00$A winners, C1 had 272 vs Pure's 259 (13 more under C1 due to much higher win rate).

### 9. How often did H050_1 actually fire before the regime-flip exit?
In 2025 Q2 Top-10%, an opposing $H050_1$ fired on **1,083 out of 1,083 trades (100.0%)**. Median warning lead time was **526.0 seconds (8.8 minutes)**.

### 10. When it fired, what was its average value versus simply waiting?
- On **761 trades (70.3%)**, firing $H050_1$ was superior to waiting for $R_2$.
- On **319 trades (29.5%)**, waiting for $R_2$ was superior.
- C1 saved giveback was **+0.0463 ATR mean** and **+0.5704 ATR median**.

### 11. Did the answer differ for LONG vs SHORT?
**Yes, diametrically opposed:**
- **Counter-LONG:** Pure Regime Flip won by **+0.0996 ATR / +$35,960** (PF rose to 1.07).
- **Counter-SHORT:** C1 won by **+0.1362 ATR / +$34,915** (Pure short win rate collapsed to 39.6%).

### 12. Did the answer differ materially in April versus May/June?
**Yes:**
- **April:** C1 was superior by **+0.1752 ATR / +$20,270** (choppy regime).
- **May:** Pure was superior by **+0.2259 ATR / +$25,715** (trending counter-regime).
- **June:** C1 was superior by **+0.1443 ATR / +$4,400** (adverse macro).

### 13. Was Q2 poor mainly because of the underlying H050 entries, or did C1 materially worsen it?
**Q2 was poor primarily because of the underlying macro environment for H050 entries, NOT because C1 worsened it.**
C1 buffered the strategy: it raised the win rate by nearly 20% (61.7% vs 42.1%), shifted the median PnL from negative (-0.26A) to positive (+0.37A), beat Pure on 70.3% of trades, and prevented a massive 42.6% expansion in drawdown.

### 14. Is there evidence that pure regime-flip exit is structurally cleaner than C1 in this period?
**Evidence only (no policy promotion):**
- For the aggregate Top 10% portfolio, **there is no evidence** that Pure Regime Flip is structurally cleaner: it suffers a 42.1% win rate, -0.26A median return, +42.6% worse drawdown, and loses on 7 out of 10 trades.
- However, there is undeniable evidence of **directional asymmetry**: Pure Regime Flip was clean and profitable on **Counter-LONG** trades (+0.07A EV, +$23k profit), whereas C1 was indispensable on **Counter-SHORT** trades.

---

## 8. Mandatory Stop & Deliverables

All artifacts have been produced and verified in `studies/nq_h050_q2_c1_vs_regime_flip_exit/results/`:

- `paired_trade_comparison.parquet`: Trade-level paired accounting across all 8,087 trades.
- `exit_architecture_summary.json`: Complete metrics for Top 10% and full population.
- `directional_summary.json`: Counter-LONG vs Counter-SHORT breakdown.
- `monthly_summary.json`: April, May, June monthly analysis.
- `study_manifest.json`: Lineage and SHA-256 hashes.

*Per repository protocol, execution is complete and halted. No parameter tuning, stop optimization, or policy changes have been made.*
