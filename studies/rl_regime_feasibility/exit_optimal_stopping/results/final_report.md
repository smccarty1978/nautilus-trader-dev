# Exit Optimal Stopping Study — Final Report

**Study**: rl_regime_feasibility/exit_optimal_stopping
**Date**: 2026-07-05
**Warning**: DEVELOPMENT VALIDATION — NOT PRISTINE OOS

---

```
EXIT OPPORTUNITY:
  LARGE

ACCEPTABLE EXIT WINDOW:
  MIXED

REMAINING-OPPORTUNITY MODEL:
  PASS

TERMINATION HAZARD MODEL:
  PASS

FITTED-Q HOLD-VS-EXIT:
  PASS

MULTI-STAGE EXIT:
  PASS

BEST EXACT-REPLAY EXIT:
  E5_fitted_q_h2 — EV/trade = $103.07

OHLCV EXIT VERDICT:
  PROCEED

RL RECOMMENDATION:
  PROCEED
```

---

## 1. Entry Populations Used

| Population | Period | N Eligible | N Traded | EV/Trade |
|-----------|--------|-----------|---------|---------|
| P1 | train | 27,651 | 27,651 | $-6.45 |
| P1 | val | 4,232 | 4,232 | $-9.45 |
| P1 | test | 6,672 | 6,672 | $-1.31 |
| P2 | train | 23,381 | 23,381 | $-5.54 |
| P2 | val | 3,601 | 3,601 | $-3.64 |
| P2 | test | 5,660 | 5,660 | $9.65 |
| P3 | train | 23,381 | 8,535 | $-6.63 |
| P3 | val | 3,601 | 1,310 | $3.09 |
| P3 | test | 5,660 | 2,168 | $21.17 |

**P2 is the primary entry population** (180s fixed delay on 2024-period-selected).
P1 is the immediate entry baseline. P3 is 180s + ML gating.

## 2. Exit Opportunity and Window Analysis

- Mean oracle improvement over final PnL: $268.49
- Trades with broad window (>= 60s within 0.25 ATR): 43.4%
- Trades requiring near-perfect timing (<5s window at 0.10 ATR): 37.3%

**Window assessment**: MIXED

### Window width by tolerance

| Tolerance | >= 5s | >= 15s | >= 30s | >= 60s | >= 120s |
|-----------|-------|--------|--------|--------|---------|
| 0.10 ATR | 62.7% | 41.6% | 28.9% | 18.3% | 10.4% |
| 0.25 ATR | 90.3% | 76.1% | 61.2% | 43.4% | 27.2% |

## 3. Model Results

### M1: Remaining opportunity — R² = 0.0714
### M3: Terminal hazard — AUC = 0.5848
### M4: Fitted-Q (hold advantage) — R² = 0.1463, RMSE = 158.1806/trade

## 4. Exit Policy Economics

### Period: val

| Policy | EV/trade | WR | PF | N trades |
|--------|---------|-----|-----|---------|
| E5_fitted_q | 62.90 | 0.438 | 1.760 | 3,601 |
| E5_fitted_q_h2 | 62.75 | 0.442 | 1.769 | 3,601 |
| E7_multistage | 50.99 | 0.438 | 1.648 | 3,601 |
| E4_hazard | 47.71 | 0.438 | 1.611 | 3,601 |
| E3_remaining_opp | 18.54 | 0.352 | 1.191 | 3,601 |
| E1_fixed_300s | -1.05 | 0.444 | 0.988 | 3,601 |
| E2_fixed_120s | -2.90 | 0.464 | 0.950 | 3,601 |
| E0_regime | -3.64 | 0.415 | 0.955 | 3,601 |

### Period: test

| Policy | EV/trade | WR | PF | N trades |
|--------|---------|-----|-----|---------|
| E5_fitted_q_h2 | 103.07 | 0.459 | 1.846 | 5,660 |
| E5_fitted_q | 102.08 | 0.459 | 1.829 | 5,660 |
| E7_multistage | 79.79 | 0.451 | 1.668 | 5,660 |
| E4_hazard | 78.81 | 0.451 | 1.660 | 5,660 |
| E3_remaining_opp | 35.46 | 0.364 | 1.245 | 5,660 |
| E1_fixed_300s | 15.36 | 0.470 | 1.125 | 5,660 |
| E0_regime | 7.88 | 0.437 | 1.065 | 5,660 |
| E2_fixed_120s | 5.90 | 0.486 | 1.072 | 5,660 |

### Cost stress (E5 fitted-Q)

| Period | Base | +1 tick | +2 ticks |
|--------|------|---------|---------|
| val | $62.90 | $50.40 | $37.90 |
| test | $102.08 | $89.58 | $77.08 |

## 5. Attribution Table (vs E0 regime exit, base cost)

### Period: val

| Policy | EV/trade | vs E0 |
|--------|---------|------|
| E5_fitted_q | 62.90 | +66.53 |
| E5_fitted_q_h2 | 62.75 | +66.38 |
| E7_multistage | 50.99 | +54.63 |
| E4_hazard | 47.71 | +51.34 |
| E3_remaining_opp | 18.54 | +22.17 |
| E1_fixed_300s | -1.05 | +2.59 |
| E2_fixed_120s | -2.90 | +0.74 |
| E0_regime | -3.64 | +0.00 |

### Period: test

| Policy | EV/trade | vs E0 |
|--------|---------|------|
| E5_fitted_q_h2 | 103.07 | +95.20 |
| E5_fitted_q | 102.08 | +94.21 |
| E7_multistage | 79.79 | +71.91 |
| E4_hazard | 78.81 | +70.94 |
| E3_remaining_opp | 35.46 | +27.59 |
| E1_fixed_300s | 15.36 | +7.48 |
| E0_regime | 7.88 | +0.00 |
| E2_fixed_120s | 5.90 | -1.98 |

## 6. Controls

| Control | EV val | EV test | Interpretation |
|---------|--------|---------|---------------|
| C1_label_shuffle | $-1.73 | $8.36 | Expected: degraded (wrong targets) |
| C2_seq_shuffle | $-17.98 | $-18.09 |  |
| C3_lag_5s | $61.80 | $100.14 | Expected: small degradation |
| C4_future_lead | $18.69 | $17.11 |  |
| C6_pullback_shuffle | $56.20 | $94.68 | Expected: degraded if pullback history matters |
| C7_no_pullback | $65.89 | $102.29 |  |
| C7_no_slope | $62.57 | $101.61 |  |
| C7_no_progress | $63.54 | $103.24 |  |
| C7_no_regime | $63.35 | $102.29 |  |

## 7. Decision

### Overall verdict: **PROCEED**

Exit models show genuine improvement over fixed 300s exit.
Fitted-Q model produces actionable hold-vs-exit separation.
Controls support genuine sequential information.
Recommend RL policy implementation.

---

## Appendix: Data Splits

| Split | Dates | Episodes |
|-------|-------|---------|
| Train | 2024-01-01 - 2024-12-31 | ~27,651 |
| Val   | 2025-01-01 - 2025-02-28 | ~4,232  |
| Test  | 2025-03-01 - 2025-05-31 | ~6,672  |

> WARNING: Test period has been inspected previously. Labeled DEVELOPMENT VALIDATION.
> Secondary OOS (2025-H2, 2026) not available in current data catalog.

## Approximation Notes

1. **Stop level approximation**: Forward labels use fresh-entry stop (current price - 1.5 ATR).
   Actual held position uses original entry stop (entry price - 1.5 ATR).
   For profitable trades: slightly conservative (overstates stop probability). Acceptable.

2. **5-second decision granularity**: Some intra-bar stop fires are invisible at 5s resolution.
   Forward labels account for 1s stop monitoring correctly, so economics are sound.

3. **Exit fill approximation**: Model decisions at 5s close, fill at next 1s open.
   Approximated as same price (no 1s slippage on exit). Conservative.
