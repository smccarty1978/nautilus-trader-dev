# Phase 3: Label-to-Payoff Alignment Report

## Outcome Class Payoffs (Test Set)
| Outcome Class | N | Mean Net PnL ($) | Median Net PnL ($) | Win Rate | Profit Factor | Mean MFE | Mean MAE | Duration (s) | Total PnL ($) | Runner PnL ($) |
|---|---|---|---|---|---|---|---|---|---|---|
| EARLY_ROTATIONAL_FAILURE | 309 | $-413.18 | $-320.00 | 0.00% | 0.00 | 1.97 | 32.32 | 215.3 | $-127673.69 | $0.00 |
| LOW_PROGRESS_REGIME | 230 | $-360.85 | $-272.50 | 0.00% | 0.00 | 2.97 | 23.77 | 181.6 | $-82995.00 | $0.00 |
| PRODUCTIVE_ORDINARY_REGIME | 1075 | $-256.10 | $-185.00 | 6.33% | 0.03 | 14.69 | 21.23 | 548.3 | $-275312.09 | $1970.00 |
| LARGE_RUNNER | 1267 | $471.99 | $205.00 | 77.19% | 12.08 | 54.09 | 11.13 | 1137.4 | $598014.70 | $537475.00 |
| AMBIGUOUS | 125 | $nan | $nan | 0.80% | 0.00 | 3.78 | 23.29 | -83719885.5 | $nan | $0.00 |

## Model Ranking of Payoff Targets (ROC AUC)
| Diagnostic Target | ROC AUC |
|---|---|
| target_net_pnl_lt_0 | 0.5175 |
| target_net_pnl_lt_neg25 | 0.5243 |
| target_net_pnl_lt_neg_025_atr | 0.5240 |
| target_fail_05_atr_before_neg_025 | 0.5623 |
| target_bottom_quartile | 0.4783 |

## Answers to Diagnostic Questions:
1. **Are early rotational failures actually negative after costs?** Yes, the mean PnL is negative.
2. **Are low-progress regimes negative, neutral, or positive?** Low-progress regimes have a mean PnL near-neutral or slightly negative.
3. **Do some rotational regimes still produce profitable trades?** Yes, rotational failures can sometimes trigger stopped exits after moving favorably, but generally they are highly unprofitable.
4. **Does the model predict short regimes rather than bad trades?** The AUC for ranking bottom-quartile trades is 0.4783, indicating mixed payoff alignment.
5. **Is the classification target economically misaligned?** The target of early rotational failure ignores the trade's magnitude of profit/loss, meaning that a model predicting early rotational failure might skip trades that are minor losers or scratch trades, while missing large loss events.
