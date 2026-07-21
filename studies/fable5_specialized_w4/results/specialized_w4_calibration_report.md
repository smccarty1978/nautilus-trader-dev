# Specialized W4 — Calibration Report

1-second OHLC research simulation. Probabilities are the model estimate of
`candidate_policy_net_positive` (candidate immediate-entry Policy A net PnL
> 0). Bins are deciles of predicted probability (0–9). "Realized rate" is the
actual net-positive fraction in the bin; "mean net PnL" is the actual mean
Policy A net PnL of candidates in the bin.

## Reliability summary

- **2025-H2 development:** all retrainable structures are weakly but correctly
  ordered — win rate and profit factor rise monotonically as retention bands
  tighten (e.g. `B_side` PF 0.87 at ~50% retention → 1.44 at ~10% retention).
  ROC-AUC is nonetheless low (0.49–0.53), so the ranking is thin.
- **2026 final test:** calibration **inverts** in the confident bins. Higher
  predicted-positive probability is associated with *worse* realized economics,
  not better. This is the concrete form of the generalization failure.

## 2026 calibration — `B_side` (representative)

| Pred. bin | count | mean predicted | realized net-positive | mean net PnL $ |
|--:|--:|--:|--:|--:|
| 0 | 64 | 0.08 | 0.484 | +92.5 |
| 1 | 489 | 0.16 | 0.352 | +24.3 |
| 2 | 1041 | 0.25 | 0.324 | +18.3 |
| 3 | 818 | 0.35 | 0.257 | −67.7 |
| 4 | 454 | 0.44 | 0.322 | −33.8 |
| 5 | 172 | 0.54 | 0.279 | +34.8 |
| 6 | 61 | 0.64 | 0.197 | −141.5 |
| 7 | 19 | 0.73 | 0.474 | −134.8 |
| 8 | 6 | 0.85 | 0.000 | −608.4 |
| 9 | 2 | 0.91 | 1.000 | +75.0 |

The lowest-confidence bins (0–2) carry the only positive economics; the
high-confidence bins the model would preferentially select (3, 6, 8) are the
worst. `A_pooled` and `C_side_session` show the same shape: `A_pooled` bin 6
(pred 0.66) realizes −$275/trade; `C_side_session` bin 5 (pred 0.55) realizes
−$69/trade. Brier scores are near the base-rate-constant reference in both
windows, confirming the probabilities carry little out-of-sample information.

Full per-structure, per-window bins are in
`specialized_w4_calibration.parquet`.
