# Atlas Diagnostics — what the KNN scorer sees (OOS 2025–2026)

Opens the black box: per-bar score vs prediction vs actual outcome. NOT a profitability test — a perception test. Key question from the audit: does the score track actual forward **MFE** (opportunity) even though it failed on net PnL?

> **TL;DR.** score_opportunity ranks actual forward MFE at Spearman **+0.15** and actual forward MAE at **+0.23** — it sees BOTH the upside and the downside, so it nets to only **-0.03** vs actual PnL. The model sees *magnitude/opportunity*, not *direction-of-payoff*.
## 1. Does the score SEE opportunity (forward MFE) even if not payoff?
Spearman rank correlation of each prediction with the actual outcome (OOS).

| Prediction | vs Actual fwd MFE | vs Actual fwd MAE | vs Actual MFE−MAE | vs Actual fwd PnL$ |
| --- | --- | --- | --- | --- |
| pred_rem_mfe | +0.192 | +0.291 | +0.001 | -0.042 |
| pred_rem_mae | +0.198 | +0.299 | +0.001 | -0.045 |
| score_opportunity | +0.150 | +0.227 | +0.002 | -0.031 |
| pred_continuation | +0.125 | +0.186 | -0.001 | -0.040 |

## 2. Score-opportunity deciles vs actual (OOS) — explains the Decile 9/10 rollover
### score_opportunity deciles
| Decile | n | Mean score | Actual fwd MFE (ATR) | Actual fwd MAE (ATR) | Actual MFE−MAE | Actual fwd PnL ($) | Cont. rate | Mean bar idx | Mean rem. bars |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 40,222 | 0.646 | 1.78 | 0.94 | +0.84 | $-7.39 | 17% | 11.4 | 16.1 |
| 2 | 40,221 | 0.761 | 1.85 | 1.00 | +0.85 | $-8.11 | 19% | 10.1 | 16.1 |
| 3 | 40,221 | 0.827 | 1.94 | 1.04 | +0.90 | $-5.28 | 22% | 9.4 | 15.8 |
| 4 | 40,221 | 0.885 | 2.04 | 1.09 | +0.95 | $-6.44 | 25% | 9.1 | 16.7 |
| 5 | 40,222 | 0.941 | 2.10 | 1.13 | +0.97 | $-6.64 | 28% | 8.9 | 16.0 |
| 6 | 40,221 | 1.000 | 2.20 | 1.19 | +1.02 | $-5.76 | 31% | 8.7 | 17.0 |
| 7 | 40,221 | 1.066 | 2.31 | 1.25 | +1.06 | $-4.62 | 33% | 8.7 | 17.9 |
| 8 | 40,221 | 1.145 | 2.48 | 1.33 | +1.15 | $-0.89 | 35% | 8.8 | 18.3 |
| 9 | 40,221 | 1.257 | 2.70 | 1.44 | +1.26 | $+1.70 | 37% | 9.2 | 18.6 |
| 10 | 40,222 | 1.540 | 3.50 | 1.91 | +1.58 | $-4.62 | 40% | 11.3 | 20.8 |

## 3. False positives / negatives (score deciles 9–10 vs actual opportunity)
- **True positives** (top score & top-quintile actual opp): 20,893 | mean bar idx 10.8 | mean fwd PnL $+618.19
- **False positives** (top score, bottom-quintile actual opp): 22,165 | mean bar idx 10.4 | mean fwd PnL $-409.26
- **False negatives** (bottom score, top-quintile actual opp): 12,860 | mean bar idx 10.3 | mean fwd PnL $+620.56
- Of top-score states, **28%** are false positives (scored high, landed in the worst actual-opportunity quintile).

## 4. Example regime trajectories (OOS)
### Highest-MFE regimes
**Regime 202522572 (Long)** — total fwd MFE 90.8 ATR
| Bar | score_opp | pred_rem_mfe | pred_cont | actual_next_cont | act_rem_mfe | act_rem_mae |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 0.96 | 2.11 | 6% | No | 90.75 | -66.72 |
| 2 | 0.79 | 1.69 | 2% | No | 90.84 | -66.81 |
| 3 | 1.73 | 4.60 | 51% | No | 6.60 | 10.39 |
| 4 | 1.61 | 4.60 | 41% | No | 13.82 | 3.17 |
| 5 | 1.36 | 4.51 | 44% | No | 5.99 | 11.00 |
| 6 | 1.58 | 4.71 | 42% | No | 3.43 | 13.56 |
| 7 | 1.63 | 4.66 | 39% | No | 2.38 | 14.00 |
| 8 | 1.67 | 4.53 | 28% | No | 6.87 | 9.51 |
| 9 | 1.82 | 4.57 | 24% | No | 9.42 | 6.95 |
| 10 | 1.96 | 4.66 | 23% | No | 7.39 | 8.98 |

**Regime 202601411 (Short)** — total fwd MFE 86.9 ATR
| Bar | score_opp | pred_rem_mfe | pred_cont | actual_next_cont | act_rem_mfe | act_rem_mae |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 1.04 | 2.36 | 43% | Yes | 86.88 | 1.37 |
| 2 | 0.88 | 2.25 | 30% | No | 86.95 | 1.29 |
| 3 | 0.87 | 1.75 | 4% | No | 88.09 | 0.15 |
| 4 | 0.85 | 1.87 | 4% | No | 87.79 | 0.46 |
| 5 | 1.05 | 2.28 | 24% | No | 87.10 | 0.15 |
| 6 | 0.73 | 1.80 | 15% | No | 86.80 | 0.38 |
| 7 | 0.91 | 1.92 | 27% | No | 86.72 | 0.46 |
| 8 | 1.16 | 2.34 | 33% | No | 86.57 | -63.51 |
| 9 | 2.42 | 5.53 | 48% | No | 14.26 | 4.17 |
| 10 | 2.54 | 5.62 | 48% | No | 7.51 | 10.93 |

**Regime 202512773 (Short)** — total fwd MFE 83.7 ATR
| Bar | score_opp | pred_rem_mfe | pred_cont | actual_next_cont | act_rem_mfe | act_rem_mae |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 1.14 | 2.39 | 44% | No | 83.66 | 1.16 |
| 2 | 0.87 | 2.00 | 12% | No | 84.48 | -35.63 |
| 3 | 0.96 | 1.93 | 27% | No | 84.21 | -35.36 |
| 4 | 1.83 | 4.96 | 57% | No | 2.47 | 19.18 |
| 5 | 1.91 | 4.87 | 49% | No | 7.26 | 13.02 |
| 6 | 1.67 | 4.85 | 46% | No | 5.41 | 14.32 |
| 7 | 1.95 | 5.01 | 43% | No | 3.97 | 15.76 |
| 8 | 1.94 | 4.73 | 39% | No | 5.89 | 13.84 |
| 9 | 2.30 | 5.13 | 40% | No | 3.08 | 15.28 |
| 10 | 2.09 | 4.87 | 33% | No | 0.00 | 12.88 |

### Lowest-MFE regimes
**Regime 202502468 (Long)** — total fwd MFE -50.2 ATR
| Bar | score_opp | pred_rem_mfe | pred_cont | actual_next_cont | act_rem_mfe | act_rem_mae |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 0.83 | 2.24 | 60% | No | -50.17 | 84.93 |

**Regime 202604678 (Long)** — total fwd MFE -32.2 ATR
| Bar | score_opp | pred_rem_mfe | pred_cont | actual_next_cont | act_rem_mfe | act_rem_mae |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 1.07 | 2.39 | 8% | No | -32.22 | 46.57 |
| 2 | 1.12 | 2.07 | 4% | No | -32.11 | 46.46 |

**Regime 202512206 (Long)** — total fwd MFE -12.7 ATR
| Bar | score_opp | pred_rem_mfe | pred_cont | actual_next_cont | act_rem_mfe | act_rem_mae |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 0.77 | 1.74 | 32% | No | -12.74 | 29.11 |
