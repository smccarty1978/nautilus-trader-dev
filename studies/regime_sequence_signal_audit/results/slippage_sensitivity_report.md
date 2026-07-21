# Slippage Sensitivity Report (NOT real MBP-1 validation)

* **This is NOT streamed MBP-1 (market-by-price level-1) quote/tick validation.**
  The catalog (`data/catalog/NQ_v0_2020_2026`) contains only bar data — no
  quote_tick/trade_tick data has been ingested for NQ, so real top-of-book
  execution validation is not currently possible. This report applies a flat
  1-tick-per-side slippage assumption to the offline B1 PnL as a rough
  sensitivity check only, and should not be cited as MBP-1-validated.
* **Sensitivity Status**: **ECONOMICALLY_UNRESOLVED**
* **Assumed Bid/Ask Spread**: 1.0 tick (0.25 points)
* **Assumed Slippage Cost per Side**: $5.00 ($5.0 per contract)
* **Total warning-triggered trades simulated**: 1,933

| Metric | Raw Exit Value | Slipped Exit Value | Slippage Impact |
|---|---|---|---|
| **Average Trade PnL (Base)** | $-66.80 | $-66.80 | $0.00 |
| **Average Trade PnL (B1)** | $-79.22 | $-89.22 | -$10.00 |
| **EV Lift over Base** | $-12.42 | $-22.42 | -$10.00 |
