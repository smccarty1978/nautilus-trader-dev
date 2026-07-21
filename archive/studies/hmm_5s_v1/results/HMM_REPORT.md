# HMM 5s State Layer — 2025 Raw-Flip Study

**Setup**: 4-state Gaussian HMM on 5s bars, fit on 2023-2024, evaluated on 2025 RTH raw 1m flips. No HH/LL gate.

**Trade simulation**: decision at flip close, fill at flip+30s (open of first available 1s bar), 1 ATR PT / 1 ATR SL bracket, 30-min max horizon. Cost: $5 commission + 1 tick adverse entry + 1 tick adverse SL exit.

## 1. Executive summary

- Population PT% on raw flips: 50.0%
- Best state (2): 53.2% PT (+3.2pp lift)
- Worst state (3): 48.8% PT (-1.2pp)
- State PT% spread: 4.4pp

## 2. State characterization (5s feature means)

| State | Range | Body % | Close Loc | Vol Z | RV |
|--:|--:|--:|--:|--:|--:|
| 0 | 0.855 | 0.759 | 1.000 | -0.104 | 0.00005 |
| 1 | 1.557 | 0.426 | 0.493 | 0.266 | 0.00007 |
| 2 | 0.426 | 0.419 | -0.000 | -0.366 | 0.00005 |
| 3 | 4.131 | 0.546 | 0.485 | 0.460 | 0.00017 |

**Plain-English interpretation** (heuristic):
- State 0: directional clean-body (range 0.86, body 76%, close-loc 1.00, vol-z -0.10)
- State 1: indecisive mid-bar (chop) (range 1.56, body 43%, close-loc 0.49, vol-z +0.27)
- State 2: decisive small-range close-at-extreme (range 0.43, body 42%, close-loc -0.00, vol-z -0.37)
- State 3: wide-range high-volume volatility burst (range 4.13, body 55%, close-loc 0.49, vol-z +0.46)

## 3. Trade economics by HMM state

| State | n | Mean $ | Median | Trim 5% | PF | Win% | PT% | SL% | Unr% | Median res | Total $ |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 0 | 375 | $-10.38 | $64.01 | $-9.78 | 0.88 | 51.7% | 51.7% | 48.0% | 0.3% | 129s | $-3,891 |
| 1 | 2,275 | $-6.14 | $83.18 | $-5.85 | 0.93 | 51.6% | 51.6% | 48.4% | 0.0% | 127s | $-13,965 |
| 2 | 299 | $-6.21 | $59.20 | $-4.80 | 0.92 | 53.2% | 53.2% | 46.8% | 0.0% | 117s | $-1,857 |
| 3 | 4,346 | $-18.73 | $-170.23 | $-19.48 | 0.91 | 48.8% | 48.8% | 51.1% | 0.1% | 117s | $-81,415 |
| **ALL** | **7,295** | **$-13.86** | **$26.58** | **$-13.87** | **0.91** | **50.0%** | **50.0%** | **49.9%** | **0.1%** | **120s** | **$-101,129** |

## 4. Confirmed vs unconfirmed raw flips, by state

| State | Conf n | Conf PT% | Conf Mean $ | Unconf n | Unconf PT% | Unconf Mean $ |
|--:|--:|--:|--:|--:|--:|--:|
| 0 | 259 | 52.1% | $-8.86 | 116 | 50.9% | $-13.77 |
| 1 | 1,739 | 53.5% | $0.21 | 536 | 45.7% | $-26.73 |
| 2 | 209 | 51.7% | $-10.59 | 90 | 56.7% | $3.97 |
| 3 | 3,387 | 49.5% | $-10.87 | 959 | 46.3% | $-46.50 |

**Aggregate (all states)**:

- HH/LL confirmed: n=5,594, PT% 50.9%, mean $-7.32, PF 0.95
- Unconfirmed: n=1,701, PT% 47.0%, mean $-35.37, PF 0.78
- Δ PT% (confirmed minus unconfirmed): +4.0pp

## 5. Transition analysis

Did a state change happen in the 30s before the flip?

| Group | n | PT% | Mean $ | PF |
|---|--:|--:|--:|--:|
| No recent transition | 5,003 | 49.9% | $-14.09 | 0.92 |
| Recent transition | 2,292 | 50.2% | $-13.37 | 0.87 |

Dwell-time effect (consecutive 5s bars in current state):

| Dwell bucket | n | PT% | Mean $ | PF |
|---|--:|--:|--:|--:|
| ≤ 30s | 3,672 | 50.7% | $-10.47 | 0.90 |
| 30-60s | 790 | 49.4% | $-17.35 | 0.87 |
| 60-120s | 698 | 49.6% | $-7.22 | 0.95 |
| 120-300s | 527 | 49.1% | $-20.38 | 0.89 |
| > 300s | 1,608 | 49.3% | $-20.64 | 0.93 |

## 6. Simple filter experiments

| Filter | n | PT% | Mean $ | PF | Total $ |
|---|--:|--:|--:|--:|--:|
| No filter (ALL) | 7,295 | 50.0% | $-13.86 | 0.91 | $-101,129 |
| Exclude state 3 | 2,949 | 51.8% | $-6.68 | 0.93 | $-19,714 |
| Only state 2 | 299 | 53.2% | $-6.21 | 0.92 | $-1,857 |
| Exclude recent transitions | 5,003 | 49.9% | $-14.09 | 0.92 | $-70,474 |
| HH/LL confirmed only | 5,594 | 50.9% | $-7.32 | 0.95 | $-40,962 |
| HH/LL conf + state 2 | 209 | 51.7% | $-10.59 | 0.87 | $-2,214 |
| HH/LL conf + excl state 3 + no transition | 1,086 | 52.6% | $-2.89 | 0.97 | $-3,140 |

## 7. Verdict

- State PT% spread on raw flips: 4.4pp (best 2 53.2% vs worst 3 48.8%)
- Excluding worst state: mean Δ $7.18 per trade
- Trading only best state: mean Δ $7.65 per trade vs baseline ($-13.86)
- Verdict: **MODEST state separation — interpretable but small**
