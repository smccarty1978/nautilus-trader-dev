# NQ Regime State memory - Statistical Memory Summary

## 1. Out-of-Sample Probability Calibration
We evaluated the calibration of predicted outcome probabilities computed using KNN (k=500) historical similarity. 
If predicted probabilities are close to actual OOS rates, the statistical memory has robust predictive content.

### A. Next-Bar Continuation Calibration
| Predicted Bucket | Count | Actual Rate |
| --- | --- | --- |
| 0–5% | 54,905 | 2.0% |
| 5–10% | 52,510 | 5.6% |
| 10–15% | 39,042 | 10.5% |
| 15–20% | 31,792 | 15.4% |
| 20–25% | 28,185 | 21.0% |
| 25–30% | 25,363 | 27.0% |
| 30–35% | 23,571 | 33.2% |
| 35–40% | 22,848 | 39.2% |
| 40–45% | 22,223 | 44.7% |
| 45–50% | 22,296 | 50.9% |
| 50–55% | 22,507 | 56.9% |
| 55–60% | 22,767 | 62.8% |
| 60–65% | 19,214 | 68.9% |
| 65–70% | 11,229 | 74.5% |
| 70–75% | 3,556 | 78.9% |
| 75–80% | 205 | 78.0% |

### B. 0.50 ATR Race Win Rate Calibration
| Predicted Bucket | Count | Actual Rate |
| --- | --- | --- |
| 35–40% | 131 | 51.1% |
| 40–45% | 29,436 | 49.0% |
| 45–50% | 259,363 | 49.1% |
| 50–55% | 111,751 | 49.7% |
| 55–60% | 1,531 | 47.4% |
| 60–65% | 1 | 100.0% |

### C. 1.00 ATR Race Win Rate Calibration
| Predicted Bucket | Count | Actual Rate |
| --- | --- | --- |
| 30–35% | 672 | 38.1% |
| 35–40% | 27,384 | 40.3% |
| 40–45% | 116,792 | 44.5% |
| 45–50% | 202,724 | 48.3% |
| 50–55% | 54,099 | 49.1% |
| 55–60% | 542 | 50.0% |

---

## 2. Statistical Memory Adjudication
> [!WARNING]
> **No tradeable edge.** The next-bar continuation calibration spans 76.9pp, but this is near-tautological (KNN exact-matches `bar_index_in_regime`; it mostly re-reads regime age/strength). The **tradeable** PT-before-SL race calibration spans only 11.9pp (flat), and the top OOS opportunity decile is **$-12.12/trade after cost** (0/10 deciles net-positive). Monotonic continuation ≠ tradeable edge; see the policy backtest for the deployment-grade money verdict.