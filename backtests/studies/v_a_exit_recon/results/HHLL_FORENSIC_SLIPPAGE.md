# HH/LL Tick-NT Forensic Slippage Audit

Forensic audit of high-slip exits in the tick-NT HH/LL validation. Tests whether large slippage tail is caused by session boundaries / halts / data gaps that we would never trade through live.

- Population: 438 crossed armed trades (Feb-Sep 2025 RTH)

## Slippage threshold buckets

| Bucket (ticks) | n | % of crosses | Mean slip $ | Total slip $ |
|---|--:|--:|--:|--:|
| (>0, ≤5] | 133 | 30.4% | $12.26 | $1,630 |
| (>5, ≤10] | 27 | 6.2% | $37.41 | $1,010 |
| (>10, ≤25] | 17 | 3.9% | $74.71 | $1,270 |
| (>25, ≤50] | 3 | 0.7% | $190.00 | $570.00 |
| (>50, ≤∞] | 2 | 0.5% | $1,578 | $3,155 |
| exactly 0 | 97 | 22.1% | $0 | $0 |

## Top 20 worst-slip trades

| Cross time CT | Dir | Slip ticks | Slip $ | Min→RTHclose | Min→ETHclose | Next-tick gap s | Held past ETH close | Crossed session |
|---|---|--:|--:|--:|--:|--:|---|---|
| 2025-09-18 08:54:31 | +1 | 467 | $2,335 | -366 | -426 | 0.01 | no | no |
| 2025-03-20 09:07:01 | +1 | 164 | $820.00 | -353 | -413 | 0.00 | no | no |
| 2025-06-18 14:18:32 | +1 | 45 | $225.00 | -42 | -102 | 0.30 | no | no |
| 2025-09-18 10:09:37 | +1 | 43 | $215.00 | -291 | -351 | 0.07 | no | no |
| 2025-06-17 08:59:59 | +1 | 26 | $130.00 | -361 | -421 | 0.21 | no | no |
| 2025-04-09 10:04:44 | -1 | 25 | $125.00 | -296 | -356 | 0.00 | no | no |
| 2025-03-20 08:43:05 | +1 | 23 | $115.00 | -377 | -437 | 0.00 | no | no |
| 2025-03-20 14:40:31 | +1 | 20 | $100.00 | -20 | -80 | 0.25 | no | no |
| 2025-04-07 10:00:30 | +1 | 20 | $100.00 | -300 | -360 | 0.00 | no | no |
| 2025-04-10 11:28:57 | -1 | 15 | $75.00 | -212 | -272 | 0.00 | no | no |
| 2025-02-20 09:45:29 | -1 | 14 | $70.00 | -315 | -375 | 0.00 | no | no |
| 2025-08-27 12:00:14 | +1 | 14 | $70.00 | -180 | -240 | 0.00 | no | no |
| 2025-02-19 10:21:43 | +1 | 13 | $65.00 | -279 | -339 | 0.01 | no | no |
| 2025-02-27 14:51:37 | -1 | 13 | $65.00 | -9 | -69 | 0.00 | no | no |
| 2025-04-17 09:47:51 | +1 | 13 | $65.00 | -313 | -373 | 0.00 | no | no |
| 2025-04-24 10:18:53 | +1 | 13 | $65.00 | -282 | -342 | 0.00 | no | no |
| 2025-07-24 14:25:36 | +1 | 13 | $65.00 | -35 | -95 | 0.00 | no | no |
| 2025-04-14 12:27:16 | +1 | 12 | $60.00 | -153 | -213 | 0.06 | no | no |
| 2025-05-08 13:03:22 | -1 | 12 | $60.00 | -117 | -177 | 0.10 | no | no |
| 2025-07-01 09:32:03 | -1 | 12 | $60.00 | -328 | -388 | 0.00 | no | no |

## High-slip cohort diagnostics (slip > 5 ticks)

- Total high-slip: **49** (11.2% of crosses)
- Held past 16:00 CT (ETH close): **0** (0.0% of high-slip)
- Crossed ETH session boundary: **0** (0.0%)
- After RTH close (≥15:00 CT): **0** (0.0%)
- Within last 15 min RTH (≥14:45 CT): **3** (6.1%)
- Tick gap > 1s nearby: **0** (0.0%)
- Tick gap > 5s nearby: **0**
- Tick gap > 60s nearby (halt/close-like): **0**

## Forensic verdict

- Top 5 worst-slip trades alone account for $3,725 of slippage
- Top 20 worst account for $4,885
