# Event-anchored continuation — given the trade has reached X, what predicts what happens next?

**State at a first touch:** everything through the touching 1s bar, and regimes detected at or before it.
Only 2023 development trades are used.

| first touch of | N | P(+2A) | P(+3A) | P(win) | median s after T0 | 5m aligned at touch | −1A already hit |
|---|---|---|---|---|---|---|---|
| +0.5A | 4,519 | 49.1% | 31.9% | 44.3% | 54 | 41.7% | 13.4% |
| +1.0A | 3,528 | 62.9% | 40.8% | 56.5% | 152 | 43.9% | 18.7% |
| +1.5A | 2,791 | 79.5% | 51.6% | 70.4% | 250 | 47.7% | 19.9% |
| +2.0A | 2,220 | — | 64.9% | 83.2% | 358 | 53.0% | 20.4% |

(The unconditional +2A rate on development trades is 36.9%.)

## What else, observed at the touch, separates the continuation?

The variables tested at each touch were:
- time since T0;
- time since the previous level;
- MAE so far;
- whether −0.5A or −1A had already been hit;
- 5m, 15m and 1h alignment at the touch;
- whether the 5m had transitioned.

**Continuation to +2A / +3A / win, given +0.5A, +1A or +1.5A:** every AUC is between 0.46 and 0.51, and none
is meaningful. The largest is "reached the level faster": AUC 0.46–0.47 for +2A, so slightly faster trades
continue slightly more often. That is a negligible effect.

**MTF alignment at the touch:** 0.48–0.51 everywhere. Being 5m-aligned when a trade reaches +1A does not
change its chance of reaching +2A (AUC 0.499).

**Prior adverse excursion:** 0.47–0.50. How much heat a trade took before reaching the level does not
matter.

## Reading

**Given the price level reached, nothing else we can observe adds anything.** The probability of continuing
rises steeply with the level already reached: 49% → 63% → 80% for +2A. It is flat in every other dimension
we tested.

This is the signature of a path whose future depends on its **current location** and not on how it got
there. Everything the clock-time checkpoints showed is therefore location information, and none of it is an
independent mechanism.

This is **consistent with a distance-to-barrier (martingale-like) process**; it does not prove one. The study
did not include a matched placebo. A later study must compare these conditional rates against a
driftless-path baseline (see the summary).

Givebacks are covered separately in `PLUS2_GIVEBACK_ANALYSIS.md`.

Machine-readable: `artifacts/EVENT_ANCHORED_STATE.*`, `artifacts/GROUP_COMPARISONS_EVENT.*` and
`artifacts/EVENT_BASE_RATES.*`.
