# Rejection Power — Pre-Flip (A) & Early-Health (B) models

OOS 2025-26: 36,242 regimes. Base composition: Launch 3.4% / QuickFail 22.2% / Chop 74.4%. Score S = P(Launch) − P(QuickFail), walk-forward (IS 2021-24 → OOS), leak-corrected features (k=Nbar). High S = keep, bottom S = reject.

> [!NOTE]
> Model A is a PRE-COMMITMENT filter (flip-bar close only, no post-flip info — the true predictive test). Model B is an EARLY-EXIT filter (you have watched 3 bars); its QuickFail rejection partly reflects regimes that have ALREADY flipped by bar 3 (observed, not predicted). Read accordingly.

## Model A — Pre-Flip Runway

### D1 — Decile composition (decile 1 = lowest S = worst)
| Decile | Count | Launch % | QuickFail % | Chop % |
| --- | --- | --- | --- | --- |
| 1 | 3,625 | 3.1% | 23.8% | 73.1% |
| 2 | 3,624 | 2.7% | 22.2% | 75.1% |
| 3 | 3,624 | 3.0% | 22.7% | 74.3% |
| 4 | 3,624 | 3.2% | 22.4% | 74.4% |
| 5 | 3,624 | 3.0% | 21.9% | 75.1% |
| 6 | 3,624 | 3.2% | 23.3% | 73.5% |
| 7 | 3,624 | 3.7% | 21.9% | 74.4% |
| 8 | 3,625 | 3.8% | 22.1% | 74.1% |
| 9 | 3,623 | 3.6% | 21.0% | 75.4% |
| 10 | 3,625 | 4.6% | 20.8% | 74.6% |

### D2 — Rejection power (remove bottom X% by S)
| Removed | % QuickFail removed | % Launch removed | Ratio |
| --- | --- | --- | --- |
| bottom 10% | 10.7% | 9.1% | **1.18** · |
| bottom 20% | 20.7% | 17.2% | **1.21** · |
| bottom 30% | 30.9% | 26.1% | **1.18** · |
| bottom 40% | 41.0% | 35.7% | **1.15** · |

### D3 — Retained population quality
| Filter | Trades left | Launch % | QuickFail % |
| --- | --- | --- | --- |
| baseline (none) | 36,242 | 3.4% | 22.2% |
| drop bottom 10% | 32,618 | 3.4% | 22.0% |
| drop bottom 20% | 28,994 | 3.5% | 22.0% |
| drop bottom 30% | 25,370 | 3.6% | 21.9% |
| drop bottom 40% | 21,746 | 3.6% | 21.8% |

### D4 — Launch vs QuickFail retention curve
| % removed | Launch retained % | QuickFail retained % | separation (L−Q) |
| --- | --- | --- | --- |
| 10% | 90.9% | 89.3% | +1.6 |
| 20% | 82.8% | 79.3% | +3.5 |
| 30% | 73.9% | 69.1% | +4.8 |
| 40% | 64.3% | 59.0% | +5.3 |
| 50% | 55.5% | 49.1% | +6.4 |
| 60% | 46.1% | 38.6% | +7.5 |
| 70% | 35.2% | 28.8% | +6.4 |
| 80% | 24.0% | 18.8% | +5.2 |
| 90% | 13.5% | 9.4% | +4.2 |

## Model B — Early Health (thru Bar 3)

### D1 — Decile composition (decile 1 = lowest S = worst)
| Decile | Count | Launch % | QuickFail % | Chop % |
| --- | --- | --- | --- | --- |
| 1 | 3,625 | 0.0% | 97.5% | 2.5% |
| 2 | 3,624 | 0.0% | 65.3% | 34.7% |
| 3 | 3,624 | 0.4% | 22.2% | 77.4% |
| 4 | 3,624 | 0.5% | 11.9% | 87.6% |
| 5 | 3,624 | 0.7% | 5.2% | 94.1% |
| 6 | 3,624 | 3.3% | 9.2% | 87.6% |
| 7 | 3,624 | 5.5% | 5.2% | 89.2% |
| 8 | 3,624 | 6.5% | 3.2% | 90.3% |
| 9 | 3,624 | 8.2% | 1.4% | 90.4% |
| 10 | 3,625 | 8.8% | 1.0% | 90.2% |

### D2 — Rejection power (remove bottom X% by S)
| Removed | % QuickFail removed | % Launch removed | Ratio |
| --- | --- | --- | --- |
| bottom 10% | 43.9% | 0.0% | **inf** ✅ |
| bottom 20% | 73.3% | 0.1% | **900.37** ✅ |
| bottom 30% | 83.3% | 1.4% | **60.17** ✅ |
| bottom 40% | 88.6% | 2.9% | **31.10** ✅ |

### D3 — Retained population quality
| Filter | Trades left | Launch % | QuickFail % |
| --- | --- | --- | --- |
| baseline (none) | 36,242 | 3.4% | 22.2% |
| drop bottom 10% | 32,618 | 3.8% | 13.8% |
| drop bottom 20% | 28,994 | 4.2% | 7.4% |
| drop bottom 30% | 25,370 | 4.8% | 5.3% |
| drop bottom 40% | 21,746 | 5.5% | 4.2% |

### D4 — Launch vs QuickFail retention curve
| % removed | Launch retained % | QuickFail retained % | separation (L−Q) |
| --- | --- | --- | --- |
| 10% | 100.0% | 56.1% | +43.9 |
| 20% | 99.9% | 26.7% | +73.2 |
| 30% | 98.6% | 16.7% | +81.9 |
| 40% | 97.1% | 11.4% | +85.8 |
| 50% | 95.2% | 9.0% | +86.2 |
| 60% | 85.6% | 4.9% | +80.7 |
| 70% | 69.2% | 2.5% | +66.7 |
| 80% | 50.2% | 1.1% | +49.1 |
| 90% | 26.0% | 0.5% | +25.5 |

## D5 — Combined filter (keep high A AND high B)
| Filter | Trades | Launch % | QuickFail % | Chop % |
| --- | --- | --- | --- | --- |
| baseline | 36,242 | 3.4% | 22.2% | 74.4% |
| A≥p50 & B≥p50 | 9,644 | 6.8% | 4.3% | 89.0% |
| A≥p60 & B≥p60 | 6,535 | 7.5% | 3.0% | 89.5% |
| A≥p70 & B≥p70 | 3,876 | 8.1% | 2.1% | 89.8% |

## D6 — Model B: how much is PREDICTION vs OBSERVATION? (decisive)

QuickFailure ≡ flip within 5 bars (npost < 5). By bar 3 the decision is made having *watched* 3 bars, so many QuickFails have **already flipped** and are merely *observed*, not predicted.

OOS QuickFail npost split: npost=1 **9%**, =2 **27%**, =3 **32%**, =4 **32%**. → **68% of all QuickFails have already flipped by bar 3.**

Of Model B's bottom-20% rejected QuickFails: **91% had already flipped (observed)**, only **9% were still-alive-then-failed (npost=4, genuinely predicted).** So the headline ratio ~900 is **mostly mechanical observation** ("you're already in a loser"), not foresight.

**Predictive residual — restrict to regimes STILL ALIVE at bar 3 (npost>3, n=30,730; the only fair predictive test):**

| Drop bottom | QF (npost4) removed | Launch removed | Ratio | Model A same subset |
| --- | --- | --- | --- | --- |
| 10% | 32.3% | 0.2% | **132** | — |
| 20% | 52.1% | 1.8% | **29.1** | **1.07** |
| 30% | 64.7% | 3.0% | **21.5** | — |
| 40% | 70.7% | 4.6% | **15.5** | **1.07** |

Even after removing all the already-flipped regimes, **Model B's bar-1-3 health genuinely flags imminent (next-bar) failures** — ratio 15–29, sacrificing almost no launches. **Model A on the identical subset is 1.07 — random.**

## Final answer
> **If I reject the bottom X% of regimes by model score, do I eliminate Quick Failures substantially faster than Pure Orderly Launches?**

> **Model A (pre-flip runway) — NO.** Ratio 1.15–1.21 on the full pool, and **1.07 (random) on regimes still alive at the decision bar.** Dropping 40% of trades moves the retained QuickFail rate only 22.2% → 21.8%. The pre-flip runway carries **no usable rejection power** — you cannot avoid losers *before committing*. This is the definitive answer to the original thesis: pre-flip OHLCV cannot pre-screen losers.
>
> **Model B (early health, thru bar 3) — YES, but as an EARLY-EXIT filter, not an entry filter.** Its spectacular headline (ratio 900) is **91% observation** of already-flipped regimes. The real, non-trivial finding is the *predictive residual*: among regimes still alive at bar 3, the health score removes **52% of imminent failures while sacrificing 1.8% of launches (ratio 29)**. That is meaningful — but it requires you to already be 3 bars into the trade, so it is a **management/exit signal, not a pre-commitment gate.**
>
> ⚠️ Caveat: this rejection power is a *composition* result. Whether it converts to money is a separate question already answered NO — the telemetry Phase-4 adaptive-exit money gate ([[telemetry_money_gate]]) found no exit policy net-positive both years after costs ("telemetry fires too late/too noisily to time exits"). Rejection power exists; harvesting it after friction did not.