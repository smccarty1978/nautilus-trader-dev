# Pullback Lifecycle — does price-only severity separate rest from exhaustion?

OOS 2025-26. Trades reaching +1 ATR then pulling back ≥0.25: **17,180**. First pullback-of-X event per trade (1s, adverse-extreme touch). Forward outcomes measured to the 1m flip. Costs $20/pt, $5 RT, 0.5t/1.0t slip.

## Pullback depth → forward outcome
| Pullback X (ATR) | n | P(new peak) | P(give back +0.5 first) | median remaining MFE | exit-now $/tr | hold-to-flip $/tr | exit−hold |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0.25 | 17,180 | 87% | 34% | 1.27 | $+169 | $+168 | $+1 |
| 0.50 | 17,172 | 77% | 49% | 0.99 | $+168 | $+168 | $+1 |
| 0.75 | 17,143 | 67% | 58% | 0.66 | $+167 | $+167 | $+1 |
| 1.00 | 17,059 | 57% | 63% | 0.30 | $+166 | $+166 | $+1 |

## P(new peak) year split (robustness)
| Pullback X | P(new peak) 2025 | 2026 |
| --- | --- | --- |
| 0.25 | 87% | 87% |
| 0.50 | 77% | 76% |
| 0.75 | 67% | 66% |
| 1.00 | 57% | 56% |

## Verdict

P(new peak): shallow (0.25) **87%** → deep (1.00) **57%** (separation +30pp, year-robust). Best exit-now − hold across depths: **$+1/tr**.
> [!WARNING]
> **Price carries the ODDS but they are MONETARILY INERT — the clean falsification.** P(new peak) separates strongly and robustly with depth (87%→57%, +30pp), so pullback severity is NOT noise — it genuinely tracks recovery probability. **But exiting on it gains nothing: exit-now ≈ hold-to-flip (~$167/tr) at EVERY depth (best edge $+1/tr).** The deep pullbacks that DO recover (57% even at 1.0 ATR) recover by enough to exactly pay for the ones that don't — magnitude compensates probability. The pullback is already PRICED; the forward EV equals the current exit value at every depth (a martingale-like surface). This is the precise answer to *'at what give-back does the trend stop being worth holding?'* → **never — the EV is flat, so no price-only pullback exit can beat holding.** It is exactly why simple trails fail. To beat it you must distinguish WHICH deep pullbacks are the 57% that recover vs the 43% that don't, and pullback depth alone provably cannot (it's priced). That residual is the narrow, falsifiable job for **order-flow** (absorption / renewed participation vs exhaustion during the bleed) — the next RATIONAL test, not a promised land. [[regime_health_decay_no_leadtime_1m]]