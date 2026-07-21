# Feature Reduction + Dual-OOS Validation

Branch: bracket-aligned entry quality model v2

## 1. Executive summary

- Offline sweep ran 8 iterations: full, top-50, top-35, top-25, top-20, top-15, top-10, top-5.
- Smallest viable model under the stated criteria: **top_10** (10 features).
- Best reduced model by preserved economics: **top_15**.
- Over-pruned example: **top_5** (failed direction balance guardrail — 33% long / 67% short).
- Dual-OOS validation (2024 + 2025 NT): 3 of 3 finalists passed both years with PF > 1.10: full, top_15, top_10.

## 2. Feature-reduction sweep (offline, 2025 OOS)

Per-row: top-10% by model score on 2025 resolved rows. PnL includes commission + 1-tick slippage (scenario C). Unresolved rows excluded from training and economics.

| Iter | n_feat | AUC | PR-AUC | top10 hit | top10 Mean $ | Trim 5% | PF | Win % | Total $ | L/S % | Pass |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|---|---|
| full | 177 | 0.5440 | 0.4768 | 51.8% | $62.09 | $66.43 | 1.48 | 61.3% | $435,388 | 48/52 | ✅ |
| top_50 | 50 | 0.5446 | 0.4769 | 51.7% | $60.38 | $62.09 | 1.49 | 60.9% | $423,381 | 44/56 | ✅ |
| top_35 | 35 | 0.5404 | 0.4742 | 50.8% | $50.27 | $53.59 | 1.39 | 59.8% | $352,477 | 48/52 | ✅ |
| top_25 | 25 | 0.5421 | 0.4751 | 51.2% | $60.47 | $62.02 | 1.50 | 60.8% | $423,982 | 42/58 | ✅ |
| top_20 | 20 | 0.5428 | 0.4746 | 51.5% | $57.53 | $60.50 | 1.47 | 60.8% | $403,371 | 41/59 | ✅ |
| top_15 | 15 | 0.5450 | 0.4752 | 52.1% | $61.50 | $64.81 | 1.50 | 61.5% | $431,238 | 37/63 | ✅ |
| top_10 | 10 | 0.5441 | 0.4739 | 51.8% | $56.07 | $59.09 | 1.47 | 60.8% | $393,145 | 37/63 | ✅ |
| top_5 | 5 | 0.5473 | 0.4787 | 53.0% | $64.20 | $66.01 | 1.56 | 61.8% | $450,205 | 33/67 | ❌ |

## 3. Finalist selection criteria

Smallest viable = fewest features where ALL hold on 2025 OOS:

**Relative to full-feature baseline:**
- Top-10% mean $/trade ≥ 80% of full
- Top-10% trimmed-5% mean ≥ 80% of full
- Top-10% PF ≥ 90% of full
- Top-10% win rate ≥ 95% of full

**Absolute guardrails:**
- PF > 1.10
- Trimmed-5% mean > $0
- Direction balance in top-10%: 35-65% each side

Passing iterations: all except top_5. top_5 fails the direction guardrail (33% long / 67% short). **Smallest viable: top_10.**

## 4. NT backtest — 2025 OOS (3 finalists)

| Finalist | Trades | L/S | Mean $ (raw) | Mean $ (+slip) | Trim 5% | PF | Win % | Total $ (+slip) | Months + / – |
|---|--:|---|--:|--:|--:|--:|--:|--:|---|
| full | 2,880 | 1388/1492 (48.2%/51.8%) | $53.64 | $41.48 | $41.53 | 1.30 | 56.8% | $119,475 | 11/1 |
| top_15 | 2,697 | 1009/1688 (37.4%/62.6%) | $47.65 | $35.50 | $37.43 | 1.26 | 57.1% | $95,745 | 11/1 |
| top_10 | 2,815 | 1069/1746 (38.0%/62.0%) | $46.31 | $34.13 | $35.78 | 1.26 | 56.3% | $96,075 | 10/2 |

## 5. NT backtest — 2024 OOS (retrained on 2020-2022, val 2023)

| Finalist | Trades | L/S | Mean $ (raw) | Mean $ (+slip) | Trim 5% | PF | Win % | Total $ (+slip) | Months + / – |
|---|--:|---|--:|--:|--:|--:|--:|--:|---|
| full | 2,774 | 1317/1457 (47.5%/52.5%) | $36.20 | $24.02 | $24.89 | 1.24 | 56.5% | $66,630 | 11/1 |
| top_15 | 2,719 | 1049/1670 (38.6%/61.4%) | $32.97 | $20.79 | $22.23 | 1.21 | 56.5% | $56,540 | 12/0 |
| top_10 | 2,749 | 1091/1658 (39.7%/60.3%) | $28.49 | $16.27 | $16.96 | 1.15 | 55.7% | $44,735 | 11/1 |

## 6. Side-by-side: full vs best reduced vs smallest viable vs over-pruned

| Model | Features | 2025 top10 Mean | 2025 top10 PF | 2025 Win% | L/S % | Status |
|---|--:|--:|--:|--:|---|---|
| Full (baseline) | 177 | $62.09 | 1.48 | 61.3% | 48/52 | baseline |
| top_15 (best reduced) | 15 | $61.50 | 1.50 | 61.5% | 37/63 | selected |
| top_10 (smallest viable) | 10 | $56.07 | 1.47 | 60.8% | 37/63 | selected |
| top_5 (over-pruned) | 5 | $64.20 | 1.56 | 61.8% | 33/67 | rejected — direction imbalance |

## 7. Dual-OOS conclusion

| Finalist | 2024 PF | 2024 Mean $ | 2025 PF | 2025 Mean $ | Both PF > 1.10 |
|---|--:|--:|--:|--:|---|
| full | 1.24 | $24.02 | 1.30 | $41.48 | ✅ |
| top_15 | 1.21 | $20.79 | 1.26 | $35.50 | ✅ |
| top_10 | 1.15 | $16.27 | 1.26 | $34.13 | ✅ |
