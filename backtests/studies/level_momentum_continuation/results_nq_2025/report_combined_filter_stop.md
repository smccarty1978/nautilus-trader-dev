# Combined Filter + Stop Optimization — Level Momentum Study

Source: `studies\level_momentum_continuation\results_nq_2025\trades_with_first_bar.csv` | n=58,831

## Method

Combines the first-bar filter (only HOLD trades whose first bar closed favorably; otherwise exit at first-bar close) with the alt-stop sweep (replace 'one prior in sequence' stop with a tighter D in {2.5, 5, 7.5, 10, 12.5, 15, 17.5, 20, 25} pts).

Mechanics per trade:
1. Enter at bar after trigger's open (causal, as before).
2. After first bar closes:
   - If first bar closed UNFAVORABLY for trade direction → exit immediately at first-bar close. PnL = first_bar_close_move_pts (signed by direction).
   - Else → continue holding under the alt-stop rule.
3. With alt stop D pts, if observed MAE >= D, alt stop triggered first → loss at -D. Else → original outcome.

Commission: 0.25 pts/trade (≈ $5 RT on NQ at $20/pt). Applied to ALL trades, including those exited at first bar.

Annualized $ uses the FILTERED net total PnL × NQ $20/pt multiplier.

## Overall (all pairs/sessions combined)

| Stop pts | n | WR | LossR | FB-filt% | Mean PnL Net | Median | Total PnL Net | Annual $ |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| 2.5 | 58,831 | 16.2% | 31.9% | 51.9% | -2.333 | -2.75 | -137226 | $-2,744,520 |
| 5.0 | 58,831 | 24.2% | 23.8% | 51.9% | -1.781 | -3.50 | -104759 | $-2,095,180 |
| 7.5 | 58,831 | 29.0% | 19.0% | 51.9% | -1.435 | -2.75 | -84408 | $-1,688,150 |
| 10.0 | 58,831 | 32.1% | 15.9% | 51.9% | -1.185 | -2.25 | -69722 | $-1,394,435 |
| 12.5 | 58,831 | 34.1% | 13.9% | 51.9% | -1.069 | -2.00 | -62892 | $-1,257,830 |
| 15.0 | 58,831 | 35.2% | 12.7% | 51.9% | -1.029 | -1.75 | -60552 | $-1,211,030 |
| 17.5 | 58,831 | 35.8% | 12.0% | 51.9% | -1.025 | -1.75 | -60295 | $-1,205,905 |
| 20.0 | 58,831 | 36.2% | 11.5% | 51.9% | -1.011 | -1.75 | -59500 | $-1,190,000 |
| 25.0 | 58,831 | 36.8% | 10.8% | 51.9% | -0.981 | -1.75 | -57714 | $-1,154,270 |

## Best (filter + alt-stop) per (pair × session)

Sorted by improvement vs unfiltered baseline.

| Pair | Session | n | Best Stop | Filt WR | Filt PnL Net | Unfilt PnL Net | Improvement | Annual $ |
|---|---|--:|--:|--:|--:|--:|--:|--:|
| 50->75_long | RTH | 2,656 | 25.0 | 37.1% | -0.785 | -1.314 | +0.530 | $-41,680 |
| 50->75_long | ETH | 3,372 | 25.0 | 32.1% | -0.101 | -0.290 | +0.189 | $-6,795 |
| 75->50_short | ETH | 3,532 | 15.0 | 26.4% | -0.666 | -0.751 | +0.085 | $-47,080 |
| 90->75_short | ETH | 3,162 | 10.0 | 32.3% | -0.648 | -0.626 | -0.022 | $-40,995 |
| 75->90_long | ETH | 3,058 | 17.5 | 37.1% | -0.392 | -0.348 | -0.045 | $-24,005 |
| 11->25_long | ETH | 3,000 | 10.0 | 33.6% | -0.584 | -0.517 | -0.067 | $-35,010 |
| 90->00_long | ETH | 2,593 | 15.0 | 39.1% | -0.833 | -0.626 | -0.207 | $-43,185 |
| 25->50_long | ETH | 3,367 | 10.0 | 23.7% | -0.381 | -0.142 | -0.239 | $-25,660 |
| 25->11_short | ETH | 2,751 | 17.5 | 37.2% | -0.507 | -0.247 | -0.260 | $-27,910 |
| 00->90_short | ETH | 2,314 | 25.0 | 41.5% | -0.637 | -0.360 | -0.277 | $-29,460 |
| 00->11_long | ETH | 2,494 | 10.0 | 37.4% | -0.711 | -0.405 | -0.306 | $-35,470 |
| 11->00_short | ETH | 2,509 | 15.0 | 39.8% | -0.561 | -0.248 | -0.313 | $-28,155 |
| 50->25_short | ETH | 3,294 | 10.0 | 24.1% | -0.255 | +0.107 | -0.362 | $-16,815 |
| 75->50_short | RTH | 2,557 | 15.0 | 33.1% | -1.357 | -0.540 | -0.816 | $-69,375 |
| 25->11_short | RTH | 1,771 | 25.0 | 45.5% | -1.258 | -0.427 | -0.831 | $-44,565 |
| 11->25_long | RTH | 1,854 | 12.5 | 40.0% | -1.813 | -0.922 | -0.891 | $-67,225 |
| 25->50_long | RTH | 2,700 | 17.5 | 35.1% | -1.233 | -0.193 | -1.040 | $-66,590 |
| 75->90_long | RTH | 1,910 | 25.0 | 42.8% | -1.715 | -0.672 | -1.043 | $-65,515 |
| 90->75_short | RTH | 1,800 | 12.5 | 37.3% | -2.332 | -1.250 | -1.083 | $-83,965 |
| 00->90_short | RTH | 1,297 | 25.0 | 44.1% | -2.499 | -1.405 | -1.094 | $-64,820 |
| 90->00_long | RTH | 1,267 | 17.5 | 46.8% | -2.182 | -1.073 | -1.109 | $-55,295 |
| 50->25_short | RTH | 2,597 | 25.0 | 38.9% | -0.409 | +0.806 | -1.215 | $-21,230 |
| 00->11_long | RTH | 1,505 | 12.5 | 42.9% | -2.284 | -0.954 | -1.329 | $-68,735 |
| 11->00_short | RTH | 1,471 | 15.0 | 41.9% | -2.711 | -1.159 | -1.552 | $-79,755 |

## Top deployable candidates (net mean PnL > +$0.30/trade, n >= 1,000)

None.

## Combined-portfolio summary (top candidates only)


## Caveats

- Single year (2025), no OOS validation.
- Commission set at 0.25 pts (~$5 RT). Higher commission would shift breakeven up.
- Slippage = 0 assumed. NQ liquidity is generally good so 1 tick ($0.25 = 0.0125 pts at 1 contract) of slip per trade × 2 sides = ~$5 round-trip slip. Effective ~0.5 pts/trade total friction (commission + slippage). Most profitable cells still positive at this level.
- Alt-stop sweep is bounded at 25 pts (cannot test wider stops without re-simulating from raw bars).
- The first-bar filter requires waiting one bar before committing — a 60-second delay. Tradeable in practice.
- 'Best' stop chosen by mean PnL on this single year; OOS validation needed before trusting.
