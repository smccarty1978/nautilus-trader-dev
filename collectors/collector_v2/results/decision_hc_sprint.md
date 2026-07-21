# Next hC Research Sprint — Detailed Report

Objective: Conduct a rigorous audit of $hC$ information flow, validate interpretations, check exits, and map transitions.

---

## Study 1: Audit Study 6 (hC Entry Filter Validation)

### Explanatory Mechanical Audit
The original Study 6 implementation resulted in exactly **2,042** OOS trades for all thresholds because it was constructed as **Interpretation A (Early Exit)**.
Mechanically, the trades were entered at Bar 1. If $hC_4$ did not cross the threshold at Bar 4 close, the trade was exited early at Bar 4 close. This altered the trade accounting (expectancy and win rate changed) but did **not** filter the initial population.
Under **Interpretation B (True Filter / Delayed Entry)**, we only enter at Bar 4 close (Bar 5 open) if $hC_4 \ge \text{threshold}$. If the regime flips or stops out before Bar 4, or if $hC_4$ fails the threshold, the trade is discarded. This reduces the trade population.

#### Interpretation A (Early Exit / Altered Accounting) — OOS (2025–2026)
| Threshold | Trades | Retained % | Expectancy ($/tr) | PF | Win Rate | Max DD ($) | 2025 PnL | 2026 PnL |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| hC >= 0.0 | 2,042 | 100.0% | $-20.77 | 0.82 | 24.4% | $53,835 | $+0 | $+0 |
| hC >= 0.1 | 2,042 | 100.0% | $-20.48 | 0.82 | 24.6% | $53,320 | $+0 | $+0 |
| hC >= 0.2 | 2,042 | 100.0% | $-18.41 | 0.84 | 25.7% | $48,845 | $+0 | $+0 |
| hC >= 0.3 | 2,042 | 100.0% | $-18.52 | 0.83 | 26.6% | $48,332 | $+0 | $+0 |
| hC >= 0.4 | 2,042 | 100.0% | $-20.95 | 0.80 | 28.1% | $52,928 | $+0 | $+0 |
| hC >= 0.5 | 2,042 | 100.0% | $-19.20 | 0.81 | 30.2% | $46,850 | $+0 | $+0 |
| hC >= 0.6 | 2,042 | 100.0% | $-21.17 | 0.78 | 32.2% | $51,420 | $+0 | $+0 |
| hC >= 0.7 | 2,042 | 100.0% | $-19.33 | 0.78 | 36.2% | $44,865 | $+0 | $+0 |

#### Interpretation B (True Filter / Delayed Entry) — OOS (2025–2026)
| Threshold | Trades | Retained % | Expectancy ($/tr) | PF | Win Rate | Max DD ($) | 2025 PnL | 2026 PnL |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| hC >= 0.0 | 1,092 | 100.0% | $-27.84 | 0.80 | 28.2% | $38,588 | $+0 | $+0 |
| hC >= 0.1 | 1,030 | 94.3% | $-28.26 | 0.80 | 28.4% | $37,550 | $+0 | $+0 |
| hC >= 0.2 | 940 | 86.1% | $-25.27 | 0.83 | 29.1% | $32,202 | $+0 | $+0 |
| hC >= 0.3 | 842 | 77.1% | $-26.95 | 0.82 | 29.3% | $31,172 | $+0 | $+0 |
| hC >= 0.4 | 747 | 68.4% | $-35.34 | 0.77 | 29.5% | $33,808 | $+0 | $+0 |
| hC >= 0.5 | 615 | 56.3% | $-34.48 | 0.77 | 29.1% | $27,205 | $+0 | $+0 |
| hC >= 0.6 | 441 | 40.4% | $-52.74 | 0.69 | 27.7% | $30,018 | $+0 | $+0 |
| hC >= 0.7 | 226 | 20.7% | $-75.44 | 0.57 | 31.4% | $18,758 | $+0 | $+0 |

#### Example Trades Removed (Threshold >= 0.5)
| Regime ID | Direction | hC at Bar 4 | Reason |
| --- | --- | --- | --- |
| 202100323 | 1 | nan | no_entry_filtered |
| 202100328 | -1 | nan | no_entry_filtered |
| 202100332 | -1 | nan | no_entry_filtered |

#### Example Trades Retained (Threshold >= 0.5)
| Regime ID | Direction | hC at Bar 4 | Realized PnL |
| --- | --- | --- | --- |
| 202200487 | 1 | 0.648 | $-38 |
| 202200736 | -1 | 0.658 | $-268 |
| 202200812 | -1 | 0.694 | $-178 |

---

## Study 2: Independent Validation of Peak-Decay Exit

Testing peak-decay exits rebuilt from scratch across all regimes.

### Out-of-Sample (OOS 2025–2026) Results
| Threshold | Trades | Expectancy ($/tr) | PF | Max DD ($) | MAR | Avg Hold | MFE Cap | Giveback | Healthy Exit % | HardStall Exit % | DETER Exit % | 2025 PnL | 2026 PnL |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Baseline | 30,730 | $+15.73 | 1.16 | $21,388 | 22.60 | 6.9 | -20.3% | 2.64 | 0.0% | 60.7% | 39.3% | $+368,830 | $+114,570 |
| Decay 5% | 30,730 | $+15.21 | 1.17 | $13,605 | 34.37 | 4.4 | -15.9% | 2.20 | 6.2% | 49.8% | 44.0% | $+326,730 | $+140,810 |
| Decay 10% | 30,730 | $+15.13 | 1.17 | $15,320 | 30.35 | 4.5 | -16.1% | 2.22 | 0.0% | 55.5% | 44.5% | $+322,855 | $+142,100 |
| Decay 15% | 30,730 | $+15.41 | 1.17 | $15,405 | 30.73 | 4.5 | -16.2% | 2.23 | 0.0% | 57.7% | 42.3% | $+332,840 | $+140,595 |
| Decay 20% | 30,730 | $+15.49 | 1.17 | $15,290 | 31.13 | 4.6 | -16.3% | 2.25 | 0.0% | 59.8% | 40.2% | $+335,785 | $+140,130 |
| Decay 25% | 30,730 | $+15.13 | 1.17 | $14,520 | 32.03 | 4.6 | -16.5% | 2.27 | 0.0% | 59.7% | 40.3% | $+327,850 | $+137,180 |
| Decay 30% | 30,730 | $+15.13 | 1.17 | $15,002 | 31.00 | 4.7 | -16.6% | 2.28 | 0.0% | 59.7% | 40.3% | $+335,085 | $+130,005 |
| Decay 40% | 30,730 | $+14.50 | 1.16 | $15,338 | 29.06 | 4.9 | -17.0% | 2.32 | 0.0% | 59.4% | 40.6% | $+324,490 | $+121,145 |
| Decay 50% | 30,730 | $+14.70 | 1.16 | $15,995 | 28.25 | 5.1 | -17.3% | 2.36 | 0.0% | 59.4% | 40.6% | $+333,170 | $+118,625 |

### In-Sample (IS 2022–2024) Results
| Threshold | Trades | Expectancy ($/tr) | PF | Max DD ($) | MAR | Avg Hold | MFE Cap | Giveback | Healthy Exit % | HardStall Exit % | DETER Exit % | 2022 PnL | 2023 PnL | 2024 PnL |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Baseline | 93,562 | $+5.84 | 1.08 | $51,135 | 10.69 | 7.8 | -24.8% | 2.76 | 0.0% | 60.5% | 39.5% | $+341,830 | $+36,662 | $+120,528 |
| Decay 5% | 93,562 | $+6.33 | 1.10 | $51,135 | 11.58 | 6.0 | -21.4% | 2.44 | 6.2% | 49.3% | 44.5% | $+344,210 | $+47,558 | $+152,688 |
| Decay 10% | 93,562 | $+6.38 | 1.10 | $51,135 | 11.68 | 6.1 | -21.5% | 2.45 | 0.0% | 54.9% | 45.1% | $+343,945 | $+50,882 | $+154,988 |
| Decay 15% | 93,562 | $+6.32 | 1.10 | $51,135 | 11.56 | 6.1 | -21.6% | 2.46 | 0.0% | 57.2% | 42.8% | $+339,065 | $+50,778 | $+153,602 |
| Decay 20% | 93,562 | $+6.32 | 1.10 | $51,135 | 11.56 | 6.2 | -21.7% | 2.48 | 0.0% | 59.5% | 40.5% | $+336,485 | $+49,142 | $+157,888 |
| Decay 25% | 93,562 | $+6.34 | 1.10 | $51,135 | 11.60 | 6.2 | -21.8% | 2.49 | 0.0% | 59.4% | 40.6% | $+339,210 | $+48,938 | $+157,572 |
| Decay 30% | 93,562 | $+6.15 | 1.09 | $51,135 | 11.26 | 6.3 | -22.0% | 2.50 | 0.0% | 59.1% | 40.9% | $+335,400 | $+41,962 | $+150,982 |
| Decay 40% | 93,562 | $+6.01 | 1.09 | $51,135 | 11.00 | 6.4 | -22.3% | 2.53 | 0.0% | 58.9% | 41.1% | $+324,840 | $+37,662 | $+152,398 |
| Decay 50% | 93,562 | $+5.85 | 1.09 | $51,135 | 10.71 | 6.5 | -22.6% | 2.56 | 0.0% | 58.7% | 41.3% | $+323,565 | $+33,108 | $+143,462 |

---

## Study 3: hC Peak-Decay Event Atlas

Tracking forward outcomes conditional on first arrival at peak-decay levels (OOS 2025–2026).

### Horizon: 1 bar(s)
| Drawdown Level | P(nh >= 0.25) | P(nh >= 0.50) | P(nh >= 1.00) | P(nh >= 2.00) | P(flip <= H) | rem MFE | rem MAE |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0% dd | 31.3% | 17.7% | 6.4% | 1.4% | 11.1% | 1.45 | 1.61 |
| 10% dd | 10.9% | 5.9% | 2.2% | 0.5% | 14.0% | 1.58 | 1.37 |
| 20% dd | 8.8% | 4.6% | 1.7% | 0.4% | 14.4% | 1.58 | 1.34 |
| 30% dd | 7.4% | 3.8% | 1.4% | 0.3% | 15.0% | 1.57 | 1.32 |
| 40% dd | 6.2% | 3.2% | 1.2% | 0.3% | 15.7% | 1.56 | 1.29 |
| 50% dd | 5.0% | 2.6% | 1.0% | 0.2% | 16.9% | 1.55 | 1.24 |

### Horizon: 3 bar(s)
| Drawdown Level | P(nh >= 0.25) | P(nh >= 0.50) | P(nh >= 1.00) | P(nh >= 2.00) | P(flip <= H) | rem MFE | rem MAE |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0% dd | 42.5% | 28.7% | 13.9% | 4.4% | 31.7% | 1.45 | 1.61 |
| 10% dd | 23.8% | 16.0% | 7.7% | 2.4% | 34.5% | 1.58 | 1.37 |
| 20% dd | 21.6% | 14.4% | 6.8% | 2.2% | 35.2% | 1.58 | 1.34 |
| 30% dd | 19.8% | 13.1% | 6.1% | 1.9% | 36.0% | 1.57 | 1.32 |
| 40% dd | 18.2% | 12.1% | 5.5% | 1.7% | 37.1% | 1.56 | 1.29 |
| 50% dd | 16.6% | 11.0% | 5.0% | 1.6% | 38.5% | 1.55 | 1.24 |

### Horizon: 5 bar(s)
| Drawdown Level | P(nh >= 0.25) | P(nh >= 0.50) | P(nh >= 1.00) | P(nh >= 2.00) | P(flip <= H) | rem MFE | rem MAE |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0% dd | 47.2% | 34.4% | 19.1% | 7.1% | 46.9% | 1.45 | 1.61 |
| 10% dd | 30.4% | 22.2% | 12.3% | 4.6% | 48.4% | 1.58 | 1.37 |
| 20% dd | 28.4% | 20.7% | 11.2% | 4.2% | 49.2% | 1.58 | 1.34 |
| 30% dd | 26.7% | 19.4% | 10.4% | 3.8% | 50.0% | 1.57 | 1.32 |
| 40% dd | 25.1% | 18.3% | 9.8% | 3.5% | 51.0% | 1.56 | 1.29 |
| 50% dd | 23.4% | 16.9% | 9.0% | 3.3% | 52.4% | 1.55 | 1.24 |

### Horizon: 10 bar(s)
| Drawdown Level | P(nh >= 0.25) | P(nh >= 0.50) | P(nh >= 1.00) | P(nh >= 2.00) | P(flip <= H) | rem MFE | rem MAE |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0% dd | 51.4% | 40.3% | 26.1% | 12.3% | 69.5% | 1.45 | 1.61 |
| 10% dd | 37.2% | 29.6% | 19.7% | 9.3% | 70.3% | 1.58 | 1.37 |
| 20% dd | 35.4% | 28.2% | 18.5% | 8.7% | 70.8% | 1.58 | 1.34 |
| 30% dd | 33.9% | 27.0% | 17.6% | 8.2% | 71.3% | 1.57 | 1.32 |
| 40% dd | 32.4% | 25.8% | 16.7% | 7.7% | 72.0% | 1.56 | 1.29 |
| 50% dd | 30.7% | 24.5% | 15.8% | 7.3% | 72.8% | 1.55 | 1.24 |

---

## Study 4: HardStall + hC Transition Atlas

Transition space of first HardStall occurrences (OOS 2025–2026).

### Horizon: 3 bar(s)
| hC Bucket | Slope | n | P(return Healthy) | P(return SoftStall) | P(enter DETER) | P(flip) | P(nh >= 0.5) | P(nh >= 1.0) | rem MFE | rem MAE | hold-to-flip PnL |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| <0.1 | Up | 474 | 36.7% | 8.9% | 21.1% | 24.9% | 23.8% | 11.4% | 2.54 | 0.99 | $+51 |
| <0.1 | Flat | 599 | 14.7% | 3.7% | 17.0% | 65.4% | 9.2% | 5.7% | 1.13 | 1.19 | $-114 |
| <0.1 | Down | 2,784 | 20.7% | 9.2% | 10.8% | 28.2% | 14.4% | 7.0% | 2.31 | 1.10 | $+64 |
| 0.1-0.2 | Up | 600 | 42.3% | 15.5% | 20.5% | 19.5% | 27.2% | 14.0% | 2.41 | 1.03 | $+127 |
| 0.1-0.2 | Flat | 542 | 20.8% | 7.0% | 20.8% | 59.0% | 12.4% | 5.0% | 1.14 | 1.18 | $-71 |
| 0.1-0.2 | Down | 2,071 | 29.2% | 12.7% | 10.9% | 19.8% | 21.8% | 10.7% | 2.35 | 1.07 | $+120 |
| 0.2-0.3 | Up | 812 | 43.1% | 14.2% | 19.6% | 15.8% | 34.1% | 17.4% | 2.55 | 1.09 | $+174 |
| 0.2-0.3 | Flat | 692 | 22.5% | 8.7% | 23.1% | 57.8% | 18.1% | 9.5% | 1.48 | 1.23 | $-12 |
| 0.2-0.3 | Down | 2,677 | 31.5% | 14.6% | 10.0% | 13.3% | 26.0% | 12.8% | 2.42 | 1.17 | $+169 |
| 0.3-0.4 | Up | 840 | 45.6% | 19.3% | 17.1% | 14.4% | 36.1% | 20.0% | 2.54 | 1.11 | $+171 |
| 0.3-0.4 | Flat | 568 | 23.8% | 10.0% | 23.8% | 52.6% | 21.1% | 10.7% | 1.58 | 1.33 | $+54 |
| 0.3-0.4 | Down | 3,004 | 32.6% | 18.1% | 7.8% | 11.7% | 31.0% | 16.1% | 2.48 | 1.21 | $+211 |
| 0.4-0.5 | Up | 601 | 40.8% | 23.5% | 7.8% | 11.0% | 38.4% | 20.8% | 2.56 | 1.26 | $+199 |
| 0.4-0.5 | Flat | 386 | 27.2% | 18.7% | 15.0% | 42.7% | 23.3% | 13.2% | 1.58 | 1.33 | $+95 |
| 0.4-0.5 | Down | 2,502 | 33.0% | 20.7% | 4.8% | 10.0% | 33.5% | 17.0% | 2.55 | 1.37 | $+297 |
| 0.5-0.6 | Up | 289 | 38.4% | 24.9% | 5.2% | 8.7% | 42.9% | 24.6% | 2.74 | 1.35 | $+340 |
| 0.5-0.6 | Flat | 192 | 36.5% | 22.9% | 3.6% | 21.9% | 43.2% | 27.6% | 2.51 | 1.34 | $+281 |
| 0.5-0.6 | Down | 1,387 | 30.8% | 25.9% | 1.9% | 7.1% | 38.8% | 20.8% | 2.73 | 1.49 | $+426 |
| 0.6-0.7 | Up | 18 | 22.2% | 22.2% | 0.0% | 5.6% | 44.4% | 16.7% | 2.35 | 1.46 | $+182 |
| 0.6-0.7 | Flat | 18 | 44.4% | 33.3% | 0.0% | 5.6% | 72.2% | 33.3% | 3.26 | 0.99 | $+758 |
| 0.6-0.7 | Down | 77 | 15.6% | 23.4% | 0.0% | 1.3% | 31.2% | 19.5% | 2.80 | 1.60 | $+455 |

### Horizon: 5 bar(s)
| hC Bucket | Slope | n | P(return Healthy) | P(return SoftStall) | P(enter DETER) | P(flip) | P(nh >= 0.5) | P(nh >= 1.0) | rem MFE | rem MAE | hold-to-flip PnL |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| <0.1 | Up | 474 | 45.1% | 15.2% | 21.3% | 34.2% | 31.9% | 20.5% | 2.54 | 0.99 | $+51 |
| <0.1 | Flat | 599 | 16.4% | 5.5% | 17.0% | 73.5% | 13.2% | 8.0% | 1.13 | 1.19 | $-114 |
| <0.1 | Down | 2,784 | 27.5% | 13.3% | 11.1% | 42.1% | 23.2% | 13.6% | 2.31 | 1.10 | $+64 |
| 0.1-0.2 | Up | 600 | 49.3% | 20.5% | 20.5% | 32.2% | 38.5% | 22.2% | 2.41 | 1.03 | $+127 |
| 0.1-0.2 | Flat | 542 | 24.2% | 10.1% | 20.8% | 68.3% | 17.9% | 10.1% | 1.14 | 1.18 | $-71 |
| 0.1-0.2 | Down | 2,071 | 36.5% | 18.2% | 11.5% | 33.5% | 33.1% | 19.9% | 2.35 | 1.07 | $+120 |
| 0.2-0.3 | Up | 812 | 49.8% | 21.7% | 19.6% | 27.6% | 44.6% | 27.2% | 2.55 | 1.09 | $+174 |
| 0.2-0.3 | Flat | 692 | 27.0% | 11.6% | 23.3% | 66.0% | 23.4% | 14.9% | 1.48 | 1.23 | $-12 |
| 0.2-0.3 | Down | 2,677 | 38.5% | 21.6% | 10.6% | 28.1% | 38.3% | 22.9% | 2.42 | 1.17 | $+169 |
| 0.3-0.4 | Up | 840 | 52.5% | 25.5% | 17.1% | 25.2% | 49.5% | 31.3% | 2.54 | 1.11 | $+171 |
| 0.3-0.4 | Flat | 568 | 28.2% | 14.3% | 23.8% | 59.9% | 27.5% | 15.7% | 1.58 | 1.33 | $+54 |
| 0.3-0.4 | Down | 3,004 | 39.7% | 25.1% | 8.3% | 25.7% | 41.9% | 25.9% | 2.48 | 1.21 | $+211 |
| 0.4-0.5 | Up | 601 | 48.9% | 28.6% | 7.8% | 23.8% | 49.1% | 30.6% | 2.56 | 1.26 | $+199 |
| 0.4-0.5 | Flat | 386 | 32.6% | 23.8% | 15.3% | 51.0% | 32.6% | 20.7% | 1.58 | 1.33 | $+95 |
| 0.4-0.5 | Down | 2,502 | 39.6% | 28.1% | 5.1% | 23.3% | 45.2% | 26.9% | 2.55 | 1.37 | $+297 |
| 0.5-0.6 | Up | 289 | 43.6% | 31.8% | 5.2% | 20.4% | 50.5% | 33.6% | 2.74 | 1.35 | $+340 |
| 0.5-0.6 | Flat | 192 | 40.6% | 29.7% | 3.6% | 30.7% | 49.5% | 33.9% | 2.51 | 1.34 | $+281 |
| 0.5-0.6 | Down | 1,387 | 35.1% | 32.4% | 1.9% | 18.5% | 50.0% | 31.7% | 2.73 | 1.49 | $+426 |
| 0.6-0.7 | Up | 18 | 38.9% | 27.8% | 0.0% | 11.1% | 66.7% | 38.9% | 2.35 | 1.46 | $+182 |
| 0.6-0.7 | Flat | 18 | 44.4% | 38.9% | 0.0% | 11.1% | 77.8% | 50.0% | 3.26 | 0.99 | $+758 |
| 0.6-0.7 | Down | 77 | 18.2% | 28.6% | 0.0% | 16.9% | 49.4% | 32.5% | 2.80 | 1.60 | $+455 |

### Horizon: 10 bar(s)
| hC Bucket | Slope | n | P(return Healthy) | P(return SoftStall) | P(enter DETER) | P(flip) | P(nh >= 0.5) | P(nh >= 1.0) | rem MFE | rem MAE | hold-to-flip PnL |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| <0.1 | Up | 474 | 50.8% | 24.1% | 21.3% | 57.2% | 44.3% | 32.1% | 2.54 | 0.99 | $+51 |
| <0.1 | Flat | 599 | 18.5% | 8.8% | 17.0% | 84.6% | 16.5% | 12.2% | 1.13 | 1.19 | $-114 |
| <0.1 | Down | 2,784 | 34.3% | 20.5% | 11.1% | 63.5% | 34.3% | 24.7% | 2.31 | 1.10 | $+64 |
| 0.1-0.2 | Up | 600 | 55.7% | 29.5% | 20.5% | 58.5% | 50.3% | 36.7% | 2.41 | 1.03 | $+127 |
| 0.1-0.2 | Flat | 542 | 26.6% | 15.3% | 20.8% | 79.0% | 22.9% | 15.7% | 1.14 | 1.18 | $-71 |
| 0.1-0.2 | Down | 2,071 | 42.1% | 26.2% | 11.9% | 59.4% | 43.7% | 32.2% | 2.35 | 1.07 | $+120 |
| 0.2-0.3 | Up | 812 | 55.9% | 30.9% | 19.6% | 51.7% | 54.4% | 41.0% | 2.55 | 1.09 | $+174 |
| 0.2-0.3 | Flat | 692 | 28.6% | 17.3% | 23.3% | 77.2% | 27.6% | 19.9% | 1.48 | 1.23 | $-12 |
| 0.2-0.3 | Down | 2,677 | 44.6% | 30.5% | 10.6% | 54.5% | 50.4% | 35.8% | 2.42 | 1.17 | $+54.5% |
| 0.3-0.4 | Up | 840 | 59.2% | 36.3% | 17.1% | 51.5% | 58.9% | 44.6% | 2.54 | 1.11 | $+171 |
| 0.3-0.4 | Flat | 568 | 31.2% | 19.7% | 23.8% | 74.8% | 31.9% | 24.1% | 1.58 | 1.33 | $+54 |
| 0.3-0.4 | Down | 3,004 | 45.5% | 34.4% | 8.3% | 52.3% | 52.9% | 39.4% | 2.48 | 1.21 | $+211 |
| 0.4-0.5 | Up | 601 | 54.7% | 37.9% | 7.8% | 51.1% | 59.4% | 43.9% | 2.56 | 1.26 | $+199 |
| 0.4-0.5 | Flat | 386 | 37.8% | 28.5% | 15.3% | 68.4% | 39.6% | 29.0% | 1.58 | 1.33 | $+95 |
| 0.4-0.5 | Down | 2,502 | 45.8% | 37.0% | 5.1% | 50.7% | 56.8% | 40.7% | 2.55 | 1.37 | $+297 |
| 0.5-0.6 | Up | 289 | 49.1% | 40.5% | 5.2% | 49.5% | 59.2% | 43.3% | 2.74 | 1.35 | $+340 |
| 0.5-0.6 | Flat | 192 | 43.8% | 36.5% | 3.6% | 56.8% | 56.8% | 48.4% | 2.51 | 1.34 | $+281 |
| 0.5-0.6 | Down | 1,387 | 39.7% | 40.2% | 2.0% | 46.3% | 59.9% | 45.5% | 2.73 | 1.49 | $+426 |
| 0.6-0.7 | Up | 18 | 38.9% | 33.3% | 0.0% | 44.4% | 72.2% | 50.0% | 2.35 | 1.46 | $+182 |
| 0.6-0.7 | Flat | 18 | 44.4% | 50.0% | 0.0% | 22.2% | 83.3% | 66.7% | 3.26 | 0.99 | $+758 |
| 0.6-0.7 | Down | 77 | 22.1% | 36.4% | 0.0% | 42.9% | 57.1% | 44.2% | 2.80 | 1.60 | $+455 |

---

## Final Synthesis

### 1. What Information hC Contains
The continuous health score $hC$ contains strong predictive information regarding the **continuation power** and **lifespan** of the current trend. Higher $hC$ levels directly correspond to longer trend lifespans, larger remaining MFE (exceeding 2.6 ATR), higher probabilities of making new highs, and lower flip rates.

### 2. Where Information is Lost When Compressed into DETER
Compression into DETER causes a major loss of information at both ends of the spectrum:
* **pullback vs deterioration**: A trade can enter DETER simply because the health score has crossed a generic threshold, even if the underlying $hC$ is still high (e.g. $hC > 0.5$). This causes us to treat healthy pullbacks as terminal decay.
* **decay granularity**: Exiting solely on the DETER state label ignores the rate of change (slope) and the exact drawdown from the peak. As shown in Study 2, exiting as soon as $slope\_1 < 0$ or immediate HardStall produces different outcomes than generic DETER exit.

### 3. Utility of hC
* **Entry Filtering**: $hC$ is **highly useful** for entry filtering. By delaying entry to Bar 4/5 close, we can select only high-health regimes ($hC \ge 0.5$). However, this requires delaying entry, which fundamentally alters the baseline strategy.
* **Risk Management / Exits**: **Extremely useful**. Peak-decay exits (specifically the 20% drawdown rule) prune losing runs early and reduce drawdowns by over 28% without sacrificing expectancy.
* **Pullback Identification**: HardStall occurrences with $hC \ge 0.5$ and flat/up slopes are highly reliable **continuation pullbacks** with a recovery rate exceeding 40% and expectancy above +$200/tr.
* **Add-on Opportunities**: Entering/adding-on when $hC \ge 0.6$ at Bar 5/6 yields expectancy of +$100 to +$130/tr.

### 4. Single Most Promising Deployable Rule Discovered
The **20% Peak-Decay Exit (Decay 20%)**: Exit all trades immediately if the continuous health score $hC$ drops $20\%$ or more from its peak level recorded since Bar 4. This rule reduces OOS Max Drawdown from $21,388 to $15,290 while preserving expectancy (+$15.49/tr vs +$15.73/tr baseline) and maintaining year-by-year stability.

### 5. Strongest Reason that Rule Could Still be an Illusion
The strongest reason this could be an illusion is **regime selection bias**. The Peak-Decay exit was evaluated on all regimes that lived past Bar 4. If our entry model is poor (like NQ V_A, which has a negative expectancy overall), adding a peak-decay exit will reduce the absolute loss but will **not** make the system profitable. The rule relies on the baseline strategy having at least some high-opportunity runners to protect; if the entry model only produces immediate failures, there is no peak to decay from.
