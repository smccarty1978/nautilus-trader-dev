# Regime-Flip (Hold-to-Flip) Exit — Win Rate & MFE Capture

OOS 2025-26. Exit = close of terminal opposite-flip bar. Costs: $20/pt, $5 RT, 0.5t/1.0t slip.
**Give-back** = of trades reaching ≥1 ATR MFE, the % that STILL net-lose (flip caught them after the peak). 1m-bar excursions — diagnostic of give-back, not a deployable exit.

| Policy | n | Win% | ≥0.5 ATR | ≥1.0 ATR | ≥1.5 ATR | ≥2.0 ATR | give-back@1ATR | avg MFE | avg realized | net/tr | 2025 | 2026 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Bar 3 open · hold-to-flip · NO filter | 33,329 | 30.1% | 72.5% | 56.6% | 44.8% | 36.0% | 46.9% | 2.27 | -0.07 | $-15.71 | $-9.42 | $-34.76 |
| Bar 4 open · hold-to-flip · NO filter | 30,730 | 29.9% | 72.3% | 56.3% | 44.4% | 35.6% | 46.9% | 2.26 | -0.07 | $-15.59 | $-9.29 | $-34.69 |
| Bar 4 open · hold-to-flip · reject worst 20% (Model B) | 24,584 | 31.0% | 74.5% | 58.5% | 46.5% | 37.3% | 47.0% | 2.37 | -0.07 | $-14.22 | $-6.49 | $-37.50 |
| Bar 4 open · hold-to-flip · reject worst 40% (Model B) | 18,438 | 31.9% | 76.4% | 60.7% | 48.5% | 38.9% | 47.5% | 2.47 | -0.07 | $-14.54 | $-5.08 | $-42.97 |

## Read
- **Win%** = does the regime-flip exit win. **≥1.0 ATR** = % that reached ≥1 ATR favorable before the flip. **give-back@1ATR** = the leak: trades that touched +1 ATR and still lost.
- avg MFE (best excursion reached) vs avg realized (what the flip exit actually banked, ATR) quantifies how much of the favorable move the flip hands back.