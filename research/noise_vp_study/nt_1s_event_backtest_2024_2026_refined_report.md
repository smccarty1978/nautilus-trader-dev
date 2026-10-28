# NautilusTrader Event-Driven 1-Second Audit Report: 2024–2026 (Refined Institutional Frictions)

**Author:** Quantitative Research & Microstructure Systems
**Execution Engine:** NautilusTrader `BacktestEngine` (v1.230.0)
**Data Resolution:** 1-Second Raw Bars (`NQ.XCME-1-SECOND-LAST-EXTERNAL`)
**Catalog Source:** `data/catalog/NQ_1S_V2`
**Execution Venue:** `XCME` (OMS: `OmsType.HEDGING`, Account: `AccountType.MARGIN`)
**Refined Slippage Model:** `0.125 pt per side` = **0.25 pt / 1 tick total slippage per round-turn**
**Refined Fee Model:** `PerContractFeeModel` ($2.50 per side = **$5.00 NQ RT commission**)
**Evaluation Window:** 2024-01-02 to 2026-04-29 (All 597 Trading Sessions)
**Generated:** 2026-10-22 19:22:13

---

## 1. Executive Summary & Microstructure Parameters

This audit evaluates the synchronized ATR-calibrated strategy under realistic institutional trading costs:
1. **Realistic Spread / Slippage (1 Tick RT)**: Rather than assuming 1 tick of adverse slippage on both entry and exit (0.50 pt RT), execution is calibrated to **1 tick of total slippage per round-turn** (`0.125 pt per side = 0.25 pt RT`).
2. **Standard Institutional Futures Commission**: Applied at **$5.00 per contract round-turn for full NQ** ($2.50 per side) in NautilusTrader's `PerContractFeeModel` (or $2.50 RT for MNQ).
3. **True Event-Driven Execution**: Evaluated on raw 1-second bars with `OmsType.HEDGING`, checking Pillar 2's dynamic ATR Stop Loss (`0.50x ATR_15m`) and Take Profit (`0.25x ATR_15m`) continuously on every individual second.

---

## 2. Year-by-Year Performance Ledger (2024, 2025, 2026 & Combined Total)

| Period | Strategy Pillar | Trades (N) | Win Rate % | Net PnL (pts) | Net PnL ($20 NQ) | Net PnL ($2 MNQ) | Max DD (pts) | Max DD ($20 NQ) | RoMaD | Sharpe (252d) | Sortino | Profit Factor |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **2024** | **Pillar 1 (Trend V2)** | 163 | 39.26% | +1,509.00 | $+30,180.00 | $+3,018.00 | 479.00 | $9,580.00 | 3.15 | 2.38 | 5.36 | 1.40 |
| **2024** | **Pillar 2 (VP Fade)** | 195 | 67.69% | -127.00 | $-2,540.00 | $-254.00 | 426.25 | $8,525.00 | -0.30 | -1.00 | -1.55 | 0.92 |
| **2024** | **Unified Portfolio** | **358** | **54.75%** | **+1,382.00** | **$+27,640.00** | **$+2,764.00** | **516.00** | **$10,320.00** | **2.68** | **1.86** | **3.81** | **1.26** |
| **2025** | **Pillar 1 (Trend V2)** | 143 | 46.15% | +2,935.75 | $+58,715.00 | $+5,871.50 | 785.25 | $15,705.00 | 3.74 | 2.24 | 9.02 | 1.72 |
| **2025** | **Pillar 2 (VP Fade)** | 176 | 69.89% | +1,336.00 | $+26,720.00 | $+2,672.00 | 160.75 | $3,215.00 | 8.31 | 4.39 | 18.83 | 1.77 |
| **2025** | **Unified Portfolio** | **319** | **59.25%** | **+4,271.75** | **$+85,435.00** | **$+8,543.50** | **709.00** | **$14,180.00** | **6.03** | **2.62** | **11.77** | **1.74** |
| **2026** | **Pillar 1 (Trend V2)** | 48 | 41.67% | +1,420.00 | $+28,400.00 | $+2,840.00 | 435.25 | $8,705.00 | 3.26 | 4.14 | 10.96 | 1.89 |
| **2026** | **Pillar 2 (VP Fade)** | 37 | 64.86% | -49.25 | $-985.00 | $-98.50 | 124.25 | $2,485.00 | -0.40 | -1.73 | -2.00 | 0.89 |
| **2026** | **Unified Portfolio** | **85** | **51.76%** | **+1,370.75** | **$+27,415.00** | **$+2,741.50** | **492.75** | **$9,855.00** | **2.78** | **3.79** | **9.47** | **1.67** |
| **TOTAL** | **Pillar 1 (Trend V2)** | 354 | 42.37% | +5,864.75 | $+117,295.00 | $+11,729.50 | 804.75 | $16,095.00 | 7.29 | 2.40 | 7.79 | 1.62 |
| **TOTAL** | **Pillar 2 (VP Fade)** | 408 | 68.38% | +1,159.75 | $+23,195.00 | $+2,319.50 | 426.25 | $8,525.00 | 2.72 | 2.18 | 6.42 | 1.31 |
| **TOTAL** | **Unified Portfolio** | **762** | **56.30%** | **+7,024.50** | **$+140,490.00** | **$+14,049.00** | **712.00** | **$14,240.00** | **9.87** | **2.38** | **7.90** | **1.53** |

### Year-by-Year Daily PnL Correlation ($r_{P1, P2}$)

| Year | Trading Days | Daily PnL Correlation ($r_{P1, P2}$) | Regimes & Cushion Characterization |
| :---: | :---: | :---: | :--- |
| **2024** | 153 | **+0.0025** | Low Correlation (Excellent Buffer) |
| **2025** | 134 | **+0.1562** | Low Correlation (Excellent Buffer) |
| **2026** | 45 | **-0.1315** | Orthogonal (Negative Correlation - Peak Cushion) |
| **Total** | 332 | **+0.1176** | Low Correlation (Excellent Buffer) |

---

## 3. Top 5 Major Drawdown Episodes Across 2024–2026

Deepest peak-to-trough drawdowns experienced by the Unified Strategy in the 1-second event-driven simulation under refined frictions:

| Rank | Start Date | Trough Date | Recovery Date | Duration | Drawdown (pts) | Drawdown ($20 NQ) | Pillar 1 PnL | Pillar 2 PnL | Fade Cushion Ratio |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **#1** | 2025-11-24 | 2026-02-02 | 2026-02-24 | 70 days | **-712.00 pt** | **-$14,240.00** | -545.00 pt | +84.00 pt | +15.4% cushioned |
| **#2** | 2025-03-05 | 2025-03-18 | 2025-04-08 | 13 days | **-709.00 pt** | **-$14,180.00** | -660.25 pt | -10.25 pt | -10.2 pt |
| **#3** | 2024-03-08 | 2024-04-05 | 2024-05-01 | 28 days | **-516.00 pt** | **-$10,320.00** | -346.00 pt | -37.00 pt | -37.0 pt |
| **#4** | 2024-08-01 | 2024-08-13 | 2024-11-15 | 12 days | **-377.50 pt** | **-$7,550.00** | +72.50 pt | -135.00 pt | -135.0 pt |
| **#5** | 2025-04-08 | 2025-04-09 | 2025-04-09 | 1 days | **-312.50 pt** | **-$6,250.00** | -186.50 pt | -91.00 pt | -91.0 pt |

---

## 4. Sensitivity: Impact of Refined Frictions (1 Tick RT vs 2 Ticks RT)

Comparison of 2024-2026 performance between conservative 2-tick slippage (0.50 pt RT) vs refined institutional 1-tick slippage (0.25 pt RT):

- **Slippage savings**: Saving 0.25 pt per round-turn across ~780 completed trades adds **+195.0 points ($+3,900.00)** directly to net PnL.
- **Commission adjustment**: At $5.00/contract full NQ commission (0.25 pt RT) vs $1.30/contract MNQ (0.065 pt RT), the institutional structure accounts for full-size futures clearing and exchange fees.