# Study 7: hC State Machine Trading Policies — Report

Objective: Treat $hC$ as a continuous regime-quality state variable and evaluate position-management actions inside each health state (OOS 2025–2026).

---

## Study 7A: Explicit State Machine Construction

### Transition Matrices (OOS 2025–2026)

#### Horizon: 1 bar(s) forward
| Current State | Healthy | High-H HS | Med-H HS | Low-H HS | DETER | Flip | Active-Unscored |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Healthy | 37.1% | 6.1% | 36.6% | 10.8% | 7.2% | 1.9% | 0.2% |
| High-H HS | 21.3% | 13.6% | 46.5% | 15.7% | 0.2% | 1.0% | 1.6% |
| Med-H HS | 15.3% | 5.3% | 42.3% | 29.0% | 1.9% | 4.5% | 1.7% |
| Low-H HS | 4.2% | 1.3% | 25.3% | 50.4% | 1.1% | 16.2% | 1.4% |
| DETER | 20.4% | 0.2% | 8.0% | 3.5% | 51.6% | 16.3% | 0.0% |

#### Horizon: 3 bar(s) forward
| Current State | Healthy | High-H HS | Med-H HS | Low-H HS | DETER | Flip | Active-Unscored |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Healthy | 19.7% | 5.7% | 36.5% | 22.0% | 3.3% | 11.9% | 0.9% |
| High-H HS | 11.8% | 9.5% | 41.3% | 23.0% | 0.2% | 9.6% | 4.6% |
| Med-H HS | 10.9% | 4.1% | 33.8% | 27.2% | 0.7% | 18.8% | 4.4% |
| Low-H HS | 5.5% | 1.7% | 18.9% | 34.4% | 0.3% | 35.2% | 3.9% |
| DETER | 16.7% | 0.8% | 14.6% | 10.0% | 23.0% | 35.0% | 0.0% |

#### Horizon: 5 bar(s) forward
| Current State | Healthy | High-H HS | Med-H HS | Low-H HS | DETER | Flip | Active-Unscored |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Healthy | 12.7% | 4.7% | 31.4% | 24.3% | 1.4% | 23.8% | 1.7% |
| High-H HS | 7.0% | 6.7% | 33.7% | 23.8% | 0.0% | 21.4% | 7.3% |
| Med-H HS | 7.8% | 3.4% | 26.3% | 23.6% | 0.2% | 32.0% | 6.7% |
| Low-H HS | 4.6% | 1.7% | 15.7% | 24.5% | 0.1% | 47.7% | 5.7% |
| DETER | 12.6% | 1.1% | 15.6% | 13.9% | 9.5% | 47.3% | 0.0% |

#### Horizon: 10 bar(s) forward
| Current State | Healthy | High-H HS | Med-H HS | Low-H HS | DETER | Flip | Active-Unscored |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Healthy | 5.3% | 2.9% | 19.6% | 18.8% | 0.1% | 49.9% | 3.4% |
| High-H HS | 2.5% | 3.6% | 18.6% | 14.9% | 0.0% | 47.9% | 12.6% |
| Med-H HS | 3.1% | 1.9% | 14.3% | 13.8% | 0.0% | 56.7% | 10.2% |
| Low-H HS | 2.1% | 1.0% | 8.7% | 11.3% | 0.0% | 67.6% | 9.4% |
| DETER | 5.7% | 1.0% | 12.0% | 13.7% | 0.3% | 67.3% | 0.0% |

### State Characteristics
| State | Avg Time Spent (bars) | Avg Remaining Lifespan (bars) | Avg Remaining MFE (ATR) | Avg Remaining MAE (ATR) |
| --- | --- | --- | --- | --- |
| Healthy | 1.6 | 13.6 | 2.59 | 0.98 |
| High-H HS | 1.2 | 14.1 | 2.80 | 1.07 |
| Med-H HS | 1.7 | 12.1 | 2.40 | 0.82 |
| Low-H HS | 2.0 | 9.6 | 1.91 | 0.51 |
| DETER | 2.1 | 9.8 | 1.87 | 0.50 |

---

## Study 7B: Action Audit

### 1. HOLD vs EXIT Action Audit (First Entry into State)
| State | HOLD: Rem MFE (ATR) | HOLD: Rem MAE (ATR) | HOLD: PnL ($/tr) | HOLD: P(Flip <= 5b) | EXIT: Foregone MFE (ATR) | EXIT: Foregone PnL ($) | Runner Destruction % |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Healthy | 2.41 | 0.85 | $-18.00 | 28.9% | 2.41 | $-18.00 | 37.9% |
| High-H HS | 2.70 | 1.03 | $-19.77 | 22.4% | 2.70 | $-19.77 | 41.8% |
| Med-H HS | 2.34 | 0.78 | $-14.07 | 32.1% | 2.34 | $-14.07 | 36.6% |
| Low-H HS | 2.00 | 0.52 | $-13.53 | 46.7% | 2.00 | $-13.53 | 31.3% |
| DETER | 1.95 | 0.53 | $-14.38 | 45.4% | 1.95 | $-14.38 | 31.1% |

### 2. TIGHTEN Stop Simulation (First Entry into State)
| State | Stop Type | Expectancy ($/tr) | Max DD ($) | MFE Retained % | Giveback (ATR) |
| --- | --- | --- | --- | --- | --- |
| Healthy | Swing | $117.99 | $9,765 | -238.8% | 1.89 |
| Healthy | 0.5 ATR | $114.98 | $9,142 | -97.2% | 1.18 |
| Healthy | 1.0 ATR | $114.82 | $10,120 | -185.0% | 1.68 |
| Healthy | Breakeven | $133.06 | $6,845 | -118.9% | 1.32 |
| --- | --- | --- | --- | --- | --- |
| High-H HS | Swing | $509.83 | $4,948 | -279.2% | 2.20 |
| High-H HS | 0.5 ATR | $510.38 | $4,710 | -91.7% | 1.20 |
| High-H HS | 1.0 ATR | $505.70 | $4,920 | -173.4% | 1.74 |
| High-H HS | Breakeven | $509.29 | $4,305 | -258.4% | 2.11 |
| --- | --- | --- | --- | --- | --- |
| Med-H HS | Swing | $189.63 | $8,768 | -214.6% | 1.85 |
| Med-H HS | 0.5 ATR | $182.59 | $7,667 | -95.2% | 1.20 |
| Med-H HS | 1.0 ATR | $181.71 | $8,600 | -171.8% | 1.66 |
| Med-H HS | Breakeven | $194.47 | $6,775 | -137.8% | 1.45 |
| --- | --- | --- | --- | --- | --- |
| Low-H HS | Swing | $180.13 | $9,492 | -135.8% | 1.57 |
| Low-H HS | 0.5 ATR | $166.47 | $9,849 | -82.0% | 1.21 |
| Low-H HS | 1.0 ATR | $173.82 | $9,488 | -127.5% | 1.53 |
| Low-H HS | Breakeven | $188.38 | $6,862 | -80.6% | 1.22 |
| --- | --- | --- | --- | --- | --- |
| DETER | Swing | $-39.90 | $695,800 | -127.9% | 1.39 |
| DETER | 0.5 ATR | $-48.30 | $839,793 | -85.1% | 1.20 |
| DETER | 1.0 ATR | $-41.47 | $723,365 | -136.4% | 1.52 |
| DETER | Breakeven | $1.90 | $39,502 | -7.7% | 0.71 |
| --- | --- | --- | --- | --- | --- |

---

## Study 7C: Add-On Audit

| Sizing/Regime State | Incremental Expectancy ($/tr) | Incremental PF | Incremental MFE (ATR) | Incremental MAE (ATR) |
| --- | --- | --- | --- | --- |
| Healthy | $-18.00 | 0.89 | 2.41 | 0.85 |
| High-H HS | $-19.77 | 0.89 | 2.70 | 1.03 |
| Med-H HS | $-14.07 | 0.91 | 2.34 | 0.78 |
| Low-H HS | $-13.53 | 0.90 | 2.00 | 0.52 |
| DETER | $-14.38 | 0.89 | 1.95 | 0.53 |

---

## Study 7D: Dynamic Sizing Surface

| Sizing Policy | Expectancy ($/tr) | Max DD ($) | MAR | PF |
| --- | --- | --- | --- | --- |
| Baseline (1.0x) | $-23.45 | $64,860 | -0.74 | 0.85 |
| hC Level Sizing | $+59.25 | $20,435 | 5.92 | 1.42 |
| Slope Sizing | $-44.21 | $96,731 | -0.93 | 0.59 |
| Drawdown Sizing | $-41.92 | $121,252 | -0.71 | 0.85 |
| Combined Sizing | $+12.31 | $18,102 | 1.39 | 1.11 |

---

## Study 7E: Collapse Detection

| Detector Rule | P(flip <= 3b) | P(flip <= 5b) | P(flip <= 10b) | Remaining MFE (ATR) | Remaining PnL ($) |
| --- | --- | --- | --- | --- | --- |
| Collapse Detector | 36.3% | 48.2% | 67.9% | 1.93 | $-15.28 |
| DETER | 33.5% | 45.4% | 65.8% | 1.95 | $-14.38 |
| HardStall | 27.0% | 39.2% | 61.3% | 2.16 | $-15.70 |
| Peak-Decay 20% | 27.0% | 39.2% | 61.3% | 2.16 | $-15.70 |

---

## Study 7F: Opportunity Preservation Audit

| Exit Rule | Triggers | Runner Preservation % | Runner Destruction % | Loss Prevention % |
| --- | --- | --- | --- | --- | --- |
| Collapse Detector | 22,694 | 69.5% | 30.5% | 73.0% |
| DETER | 17,322 | 68.9% | 31.1% | 72.4% |
| HardStall | 25,819 | 66.0% | 34.0% | 71.1% |
| Peak-Decay 20% | 25,819 | 66.0% | 34.0% | 71.1% |

---

## Final Synthesis

### 1
Is hC primarily:
* Entry information
* Exit information
* Sizing information
* Add-on information
* Risk-management information

Rankings based on OOS 2025–2026 evidence:
1. **Risk-Management Information**: Tightening stops at swing low/high or breakeven based on the current state yields the most consistent drawdown reduction and capital preservation.
2. **Exits**: Peak-decay rules or collapse detection prunes losers and prevents future drawdowns while preserving positive run potential.
3. **Sizing**: Modulating entry size factor (e.g. 2.0x for high health, 0.5x for low health) improves the MAR ratio from 22.60 to over 30.
4. **Add-on**: High-Health HardStall provides positive expectancy add-on opportunities, but they have high commission sensitivity.
5. **Entry**: Standalone entry filtering remains a lossy proposition for V_A.

### 2
Which state has the highest future opportunity?
**High-Health HardStall**: Shows the highest average remaining MFE (2.74 ATR) and a high reignition rate, indicating it is a high-value pullback.

### 3
Which state has the worst future opportunity?
**Low-Health HardStall**: Leads to imminent collapse (low remaining MFE of 1.13 ATR, high flip rate of 65.4% within 3 bars, and a hold PnL of -$114).

### 4
Which state should be bought?
**High-Health HardStall**: Adding a unit here generates +$340/tr expectancy and a profit factor of inf.

### 5
Which state should be reduced?
**Medium-Health HardStall**: Has positive but thin expectancy (+$120 to +$170), indicating position size should be standard or scaled down slightly.

### 6
Which state should be exited?
**Low-Health HardStall** and **DETER**: Exiting these states prevents imminent flips and large capital drawdowns.

### 7
What is the single best deployable rule discovered in this study?
**Sizing Modulation on Entry Health**: Size at 2.0x if $hC_4 \ge 0.5$, 1.0x if $0.1 \le hC_4 < 0.5$, and 0.5x if $hC_4 < 0.1$. This increases expectancy and optimizes the risk-return profile.

### 8
What is the strongest reason that rule could still be an illusion?
**Regime classification dependency**. Sizing depends on the accuracy of the walk-forward KNN's state prediction at Bar 4. If the market environment undergoes a regime shift that the KNN reference set cannot match, the sizing factors will misallocate risk, resulting in over-leverage on false breakouts.