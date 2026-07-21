# Pullback NT Runtime Parity Validation

**Rule**: HH/LL-confirmed 1m regime, wait for first 1.0 ATR pullback, decision/fill timing matches offline. Bracket: PT 1.0 ATR / SL 0.75 ATR. Exit on PT, SL, opposing 1m regime flip, or 30-min cap.

**NT runtime mechanics**: market entry order submitted 1 bar early so NT venue fills at OPEN of target fill_ts bar (matches collector's fill_price = bar.open[fill_ts] convention). PT/SL levels computed from ACTUAL NT fill price. PT/SL monitored intra-bar via 1s bar H/L. Regime flip detected on 1m bar processing → market exit submits → NT fills at next 1s bar OPEN.

**Known structural divergence**: collector exits regime trades at OPEN of next flip's 1m bar (~60s before flip can actually be detected). NT detects the flip only at 1m bar CLOSE, so the trade is exposed to ~60s of additional price action during the flip-bar's adverse move. Expect SL hits to be elevated vs collector.

## 2024

NT trades: 5,122, Offline trades: 4,179, Δ count: +943 (+22.6%)

| Population | n | PT% | SL% | Reg% | Mean $ | Median $ | PF | Total $ | Max DD |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| NT actual (real fills) | 5,122 | 38.2% | 46.4% | 15.3% | $-11.31 | $-80.00 | 0.88 | $-57,930 | $-61,605 |
| NT ref (collector exit price) | 4,337 | 38.2% | 46.4% | 15.3% | $-3.28 | $-106.70 | 0.97 | $-14,245 | $-23,725 |
| Offline collector | 4,179 | 46.6% | 36.3% | 17.1% | $29.17 | $26.06 | 1.39 | $121,909 | $-3,495 |

Exit slippage (NT actual vs expected):

| Exit reason | n | Mean $ slip | Total $ |
|---|--:|--:|--:|
| pt | 1,958 | $2.41 | $4,722 |
| regime | 785 | $0.00 | $0.00 |
| sl | 2,378 | $-2.80 | $-6,662 |
| timeout | 1 | $0.00 | $0.00 |
| **All** | 5,122 | $-0.38 | $-1,940 |

Trade pairing by signal_time: 4,179 matched, 943 NT-only, 0 offline-only.

Of 4,179 matched: outcome agreement 3,544 (84.8%).

Outcome cross-tab (rows = NT, cols = offline):

```
bracket_100_75_outcome    pt  regime    sl  timeout   All
exit_reason                                              
pt                      1894      11    29        0  1934
regime                     8     165     3        0   176
sl                        45     539  1484        0  2068
timeout                    0       0     0        1     1
All                     1947     715  1516        1  4179
```

On 4,179 matched pairs — NT mean $4.09, Offline mean $29.17, Δ **$-25.08**.

**Mismatches** (635 of 4,179):

```
bracket_100_75_outcome  pt  regime  sl
exit_reason                           
pt                       0      11  29
regime                   8       0   3
sl                      45     539   0
```

## 2026

NT trades: 1,488, Offline trades: 1,200, Δ count: +288 (+24.0%)

| Population | n | PT% | SL% | Reg% | Mean $ | Median $ | PF | Total $ | Max DD |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| NT actual (real fills) | 1,488 | 37.9% | 45.0% | 17.1% | $-17.01 | $-95.00 | 0.88 | $-25,310 | $-30,725 |
| NT ref (collector exit price) | 1,233 | 37.9% | 45.0% | 17.1% | $-2.68 | $-134.88 | 0.98 | $-3,310 | $-17,411 |
| Offline collector | 1,200 | 46.0% | 34.8% | 19.2% | $56.98 | $57.50 | 1.55 | $68,371 | $-7,663 |

Exit slippage (NT actual vs expected):

| Exit reason | n | Mean $ slip | Total $ |
|---|--:|--:|--:|
| pt | 564 | $2.67 | $1,504 |
| regime | 255 | $0.00 | $0.00 |
| sl | 669 | $-3.12 | $-2,088 |
| **All** | 1,488 | $-0.39 | $-584.52 |

Trade pairing by signal_time: 1,200 matched, 288 NT-only, 0 offline-only.

Of 1,200 matched: outcome agreement 1,010 (84.2%).

Outcome cross-tab (rows = NT, cols = offline):

```
bracket_100_75_outcome   pt  regime   sl  timeout   All
exit_reason                                            
pt                      534       7    7        0   548
regime                    2      68    2        0    72
sl                       16     155  408        1   580
All                     552     230  417        1  1200
```

On 1,200 matched pairs — NT mean $6.05, Offline mean $56.98, Δ **$-50.93**.

**Mismatches** (190 of 1,200):

```
bracket_100_75_outcome  pt  regime  sl  timeout
exit_reason                                    
pt                       0       7   7        0
regime                   2       0   2        0
sl                      16     155   0        1
```

## Cross-year NT vs Offline summary

| Year | NT n | Off n | NT mean $ | Off mean $ | Δ/trade | NT PT% | Off PT% | NT SL% | Off SL% | NT PF | Off PF | NT total | NT max DD |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 2024 | 5,122 | 4,179 | $-11.31 | $29.17 | **$-40.48** | 38.2% | 46.6% | 46.4% | 36.3% | 0.88 | 1.39 | $-57,930 | $-61,605 |
| 2026 | 1,488 | 1,200 | $-17.01 | $56.98 | **$-73.99** | 37.9% | 46.0% | 45.0% | 34.8% | 0.88 | 1.55 | $-25,310 | $-30,725 |

## Verdict

- **2024**: NT runtime unprofitable. PF 0.88, total $-57,930.
- **2026**: NT runtime unprofitable. PF 0.88, total $-25,310.
