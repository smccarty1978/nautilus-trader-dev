# Short-RTH Policy A — 1.50 ATR Post-Alignment Stop Isolation

## Decision

**`POSTALIGN_STOP_HELPS`**

The inherited 1.50 ATR post-alignment stop is **helping** the short-RTH pocket.
Removing it (H1: hold to the opposing bullish flip after alignment) **worsens
both PnL and drawdown, in both years**. Per the study's own interpretation
guide ("if H1 worsens both: keep current Policy A"), the post-alignment stop
should stay in the baseline before any threshold testing.

Offline 1-second OHLC research simulation. H0 and H1 share the identical
fixture-parity-tested Policy A engine and the identical frozen 807-entry
short-RTH schedule, differing **only** in the post-alignment stop, so the
H1−H0 delta is a clean single-component attribution.

## H0 baseline reproduction (gate)

H0 reconciled **trade-for-trade** to the frozen offline Policy A benchmark
(0 mismatches): 604 trades / +$20,304 in 2025 and 203 / +$6,709 in 2026, exact
to the cent. This offline H0 (+$27,013, 36 `stop_after_flip`) differs from the
NT Phase 1 run (+$23,270, 38) only by the fill model — expected and disclosed;
the component conclusion is fill-model-agnostic in direction.

## H0 vs H1

| Split | Variant | Trades | Net $ | $/tr | PF | Max closed DD |
|:--|:--|--:|--:|--:|--:|--:|
| Combined | H0 (current) | 807 | **27,013** | 33.47 | 1.174 | **14,331** |
| Combined | H1 (no post stop) | 807 | **21,710** | 26.90 | 1.135 | **17,377** |
| 2025 | H0 | 604 | 20,304 | 33.62 | 1.183 | 14,331 |
| 2025 | H1 | 604 | 15,813 | 26.18 | 1.136 | 17,377 |
| 2026 | H0 | 203 | 6,709 | 33.05 | 1.153 | 11,144 |
| 2026 | H1 | 203 | 5,896 | 29.05 | 1.132 | 12,008 |

Removing the post stop costs **−$5,303 combined** (−$4,491 in 2025, −$813 in
2026) and **increases max closed-trade drawdown by +$3,046** (14,331 → 17,377).
Both effects are consistent across both years. Win rate is essentially
unchanged (32.8% → 33.1%); the average loser gets worse (−$290 → −$302).

## Exit-reason distribution (combined)

| Exit reason | H0 count | H0 $ | H1 count | H1 $ |
|:--|--:|--:|--:|--:|
| opposing bullish flip | 372 | +137,200 | **408** | +131,896 |
| pre-alignment stop (1.25) | 255 | −94,765 | 255 | −94,765 |
| confirmation timeout | 144 | −115 | 144 | −115 |
| post-alignment stop (1.50) | 36 | −15,307 | **0** | — |

H1 simply reclassifies the 36 post-stop trades as opposing-flip exits; the 255
pre-stops and 144 timeouts are byte-identical (clean isolation — 0 non-cohort
trades changed). The opposing-flip bucket's PnL falls by exactly the −$5,303
those 36 trades lose by being held.

## The 36 post-alignment-stop trades (H0 stop vs H1 hold-to-flip)

| Measure | Value |
|:--|--:|
| H0 total PnL (stopped at 1.50) | −$15,307 |
| H1 total PnL (held to opposing flip) | −$20,610 |
| Delta (H1 − H0) | **−$5,303** |
| Improved by holding / worsened / unchanged | 18 / 18 / 0 |
| Losses that got larger | 18 |
| Recovered to profit | **2** |
| Became a large winner (≥ $500) | **0** |
| Avg H0 result / Avg H1 result / Median H1 | −$425 / −$573 / −$405 |
| Median adverse excursion **after** the H0 stop | **1.87 ATR** |
| Max adverse excursion after the H0 stop | 8.29 ATR |
| Median time from H0 stop to opposing flip | 39 s |

The count splits evenly (18 better / 18 worse if held), but the **magnitude is
asymmetric**: the trades that worsen do so far more than the ones that improve.
After the 1.50 stop fires, price moves a further **1.87 ATR against** the trade
at the median (up to 8.29 ATR), and only 2 of 36 ever recover to profit before
the opposing flip — which itself arrives just ~39 s later. The stop is cutting
genuinely deteriorating post-alignment trades and capping the left tail; that
tail is what re-opens under H1.

## Answers

1. **Removing the stop → PnL?** Worse: −$5,303 combined (−20% of the pocket's
   net edge).
2. **→ Max closed-trade drawdown?** Worse: +$3,046 (14,331 → 17,377).
3. **Stable across years?** Yes — H1 worsens both PnL and DD in 2025 and 2026.
4. **What happens to the 36 stop trades?** They hold to the opposing flip and
   lose $5,303 more in aggregate (−$15,307 → −$20,610); avg −$425 → −$573.
5. **How many recover to profit if held?** 2 of 36.
6. **How many get worse?** 18 of 36 (18 improve), and 18 losses get larger.
7. **Keep the post-alignment stop before threshold testing?** **Yes.** It is
   economically useful risk control, not dead weight — keep H0 as the baseline.

## Convention / audit

- RTH 08:30–15:00 America/Chicago (frozen schedule; entry only). Cost $10 RT,
  $20/pt, 1 contract. Fill: offline next-open entry; stop at trigger
  (gap→open); opposing flip next-open — identical for H0 and H1.
- Pre-execution lookahead audit: **PASS, 0 CRITICAL** (`audit/pre_execution_audit.md`).
  One diagnostic WARNING (a swapped MFE/MAE branch in the post-stop excursion
  stat) was fixed before this run; H0's exact trade-for-trade reproduction of
  the frozen benchmark is the engine-correctness gate. No signal, threshold,
  RTH, ATR, or entry change was made — single-component isolation only.

The Parquet/JSON deliverables are authoritative for every trade, the 36-trade
attribution, and all splits.
