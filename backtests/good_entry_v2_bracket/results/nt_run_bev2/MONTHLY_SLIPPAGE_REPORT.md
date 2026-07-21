# Monthly & Slippage Sensitivity — Bracket-Aligned v2

- N trades merged: 2,949
- Exit mix: {'pt': 1650, 'sl': 1231, 'regime_exit': 68}
- Classification: `exit_reason` derived from `(avg_px_close - avg_px_open) / atr_at_signal`

## Scenario totals

| Scenario | n | Mean $ | Median $ | Win% | PF | Total $ |
|---|--:|--:|--:|--:|--:|--:|
| A — NT raw ($0 commission, no slippage) | 2,949 | $46.75 | $135.00 | 56.0% | 1.35 | $137,870 |
| B — + $5 commission | 2,949 | $41.75 | $130.00 | 56.0% | 1.31 | $123,125 |
| C — + 1-tick slippage (entry + SL/regime exit) | 2,949 | $34.55 | $125.00 | 56.0% | 1.25 | $101,885 |

## Monthly PnL under each scenario

| Month | n | A: raw $ | B: +comm | C: +slip | C Mean $/tr | C Win% | C PF |
|---|--:|--:|--:|--:|--:|--:|--:|
| 2025-01 | 256 | $10,345 | $9,065 | $7,225 | $28.22 | 56.2% | 1.20 |
| 2025-02 | 202 | $10,060 | $9,050 | $7,585 | $37.55 | 55.0% | 1.30 |
| 2025-03 | 281 | $22,405 | $21,000 | $19,020 | $67.69 | 59.1% | 1.38 |
| 2025-04 | 296 | $32,250 | $30,770 | $28,640 | $96.76 | 56.1% | 1.39 |
| 2025-05 | 290 | $8,970 | $7,520 | $5,415 | $18.67 | 54.8% | 1.14 |
| 2025-06 | 230 | $7,410 | $6,260 | $4,580 | $19.91 | 53.9% | 1.20 |
| 2025-07 | 252 | $2,860 | $1,600 | $-250.00 | $-0.99 | 53.2% | 0.99 |
| 2025-08 | 233 | $3,810 | $2,645 | $920.00 | $3.95 | 51.9% | 1.04 |
| 2025-09 | 199 | $10,610 | $9,615 | $8,210 | $41.26 | 58.8% | 1.47 |
| 2025-10 | 275 | $8,260 | $6,885 | $4,910 | $17.85 | 56.4% | 1.14 |
| 2025-11 | 200 | $10,300 | $9,300 | $7,860 | $39.30 | 56.5% | 1.20 |
| 2025-12 | 235 | $10,590 | $9,415 | $7,770 | $33.06 | 60.0% | 1.30 |

## Scenario C breakdown by exit reason

| Exit | n | Mean $ | Median $ | Total $ |
|---|--:|--:|--:|--:|
| pt | 1,650 | $311.40 | $255.00 | $513,810 |
| regime_exit | 68 | $-264.12 | $-217.50 | $-17,960 |
| sl | 1,231 | $-320.04 | $-265.00 | $-393,965 |

## Scenario C by direction

| Direction | n | Mean $ | Median $ | Win% | PF | Total $ |
|---|--:|--:|--:|--:|--:|--:|
| Short | 1,533 | $36.64 | $125.00 | 56.0% | 1.27 | $56,175 |
| Long | 1,416 | $32.28 | $120.00 | 55.9% | 1.22 | $45,710 |

## Approximate Sharpe across scenarios

| Scenario | Daily mean | Daily std | Sharpe (252d) |
|---|--:|--:|--:|
| A — raw | $538.55 | $1,394 | 6.13 |
| B — +comm | $480.96 | $1,389 | 5.50 |
| C — +slip | $397.99 | $1,390 | 4.54 |

## Stability summary (scenario C)

- Positive months: 11 / 12
- Negative months: 1 / 12
- Best month: $28,640 (2025-04)
- Worst month: $-250.00 (2025-07)
- Std dev across months: $7,929
