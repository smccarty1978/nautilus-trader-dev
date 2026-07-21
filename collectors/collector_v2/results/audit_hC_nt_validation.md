# Audit Report — hC NautilusTrader Event-Driven Validation

This document certifies the execution integrity of the position-sizing validation.

## 1. Lookahead and Causality Audit
* **No Future Information**: All sizing adjustments are triggered at Bar 4 close (`s_1m.bars_in_regime == 5`). Sizing decisions utilize only the walk-forward KNN $hC$ score computed using past historical databases (strictly prior years).
* **Parity Check**: Sizing factors were verified against offline Study 7 outputs. Lookups match the regime's start timestamp exactly, ensuring zero retrospective state assignment or drift.
* **Event Timing Integrity**: Orders are executed in the event loop on 1s bar arrivals. Sizing changes are executed immediately following the Bar 4 close, meaning transaction prices include realistic market-driven execution and bid-ask spread.

## 2. Cost and Execution Integrity
* **Commission Model**: commission was applied at $2.50 per contract per side ($5 RT) and scaled exactly with position size.
* **Slippage**: Slippage is dynamically simulated by the backtest engine using market-fill logic on 1s bars, providing realistic execution friction.
* **Causality Check**: `ts_init` bounds check enforced. No state updates or feature calculations utilize information with timestamps ahead of the current engine time.
