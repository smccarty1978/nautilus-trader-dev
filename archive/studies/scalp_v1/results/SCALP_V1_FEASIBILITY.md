# Pullback Scalp v1 — Feasibility Report

First-cut feasibility test of the micro pullback continuation scalp on NQ 2025 RTH. Four mechanical variants, no grid search. Goal: determine whether this strategy class can approach 20-30 trades/day at ~55% WR with ~$500/day average.

## Variants tested

| Variant | Impulse |body|/atr | Pullback range | Re-accel | Bracket PT/SL | Max Hold | Cooldown |
|---|--:|--:|--:|--:|--:|--:|
| v1_base | 0.4 | 0.15-0.55 | 0.1 | 0.35/0.35 | 60s | 0s |
| v2_tight | 0.8 | 0.15-0.55 | 0.1 | 0.35/0.35 | 60s | 60s |
| v3_asym | 0.4 | 0.15-0.55 | 0.1 | 0.5/0.3 | 90s | 0s |
| v4_tight_asym | 0.8 | 0.15-0.55 | 0.1 | 0.5/0.3 | 90s | 60s |
| v5_2to1 | 0.4 | 0.15-0.55 | 0.1 | 1.0/0.5 | 180s | 30s |

## Per-variant feasibility scoreboard

| Variant | n | trades/day (med/mean) | WR | Mean $ | Median $ | PF | Total $ | Max DD | Roll-20 DD | Roll-50 DD | Avg Win | Avg Loss | Med Hold s | Daily $ med | Worst day | Win days % | PT/SL/Hold mix |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| v1_base (NQ 2025) | 50,672 | 201 / 196 | 49.1% | $-10.39 | $-30.96 | 0.75 | $-526,712 | $-526,872 | $-3,704 | $-6,297 | $65.27 | $-83.28 | 8.0 | $-2,200 | $-5,574 | 6.6% | 49.0% / 50.7% / 0.4% |
| v2_tight (NQ 2025) | 18,126 | 72 / 70 | 49.3% | $-10.14 | $-30.55 | 0.76 | $-183,794 | $-184,274 | $-3,563 | $-5,763 | $66.37 | $-84.50 | 8.0 | $-743.88 | $-4,303 | 13.2% | 49.2% / 50.5% / 0.4% |
| v3_asym (NQ 2025) | 50,362 | 200 / 195 | 37.5% | $-9.30 | $-42.72 | 0.80 | $-468,410 | $-468,606 | $-3,558 | $-5,520 | $97.34 | $-73.35 | 9.0 | $-2,000 | $-5,970 | 7.8% | 37.4% / 62.4% / 0.2% |
| v4_tight_asym (NQ 2025) | 18,028 | 71 / 70 | 37.4% | $-9.55 | $-43.41 | 0.79 | $-172,211 | $-172,698 | $-3,872 | $-5,377 | $98.79 | $-74.35 | 9.0 | $-733.18 | $-4,524 | 17.4% | 37.3% / 62.5% / 0.1% |
| v5_2to1 (NQ 2025) | 34,070 | 135 / 132 | 34.0% | $-9.18 | $-68.47 | 0.88 | $-312,724 | $-312,900 | $-5,004 | $-8,344 | $198.21 | $-115.89 | 27.0 | $-1,221 | $-9,706 | 23.6% | 32.9% / 65.6% / 1.5% |

## Daily PnL distribution

| Variant | Best day | p90 | p75 | Median | p25 | p10 | Worst day |
|---|--:|--:|--:|--:|--:|--:|--:|
| v1_base (NQ 2025) | $7,178 | $-577.85 | $-1,370 | $-2,200 | $-2,980 | $-3,589 | $-5,574 |
| v2_tight (NQ 2025) | $2,662 | $106.23 | $-287.27 | $-743.88 | $-1,153 | $-1,482 | $-4,303 |
| v3_asym (NQ 2025) | $10,159 | $-337.51 | $-1,048 | $-2,000 | $-2,665 | $-3,423 | $-5,970 |
| v4_tight_asym (NQ 2025) | $2,434 | $372.85 | $-291.01 | $-733.18 | $-1,142 | $-1,599 | $-4,524 |
| v5_2to1 (NQ 2025) | $8,044 | $1,129 | $-39.19 | $-1,221 | $-2,415 | $-3,460 | $-9,706 |

## Goal alignment per variant

### v1_base
  - ❌ trades/day ~20-30 (got 201)
  - ❌ WR ~55%+ (got 49.1%)
  - ❌ daily $ ~500 (got $-2,200)
  - ✅ low outlier dep (top-1%-share = 27.1%)

### v2_tight
  - ❌ trades/day ~20-30 (got 72)
  - ❌ WR ~55%+ (got 49.3%)
  - ❌ daily $ ~500 (got $-743.88)
  - ✅ low outlier dep (top-1%-share = 28.6%)

### v3_asym
  - ❌ trades/day ~20-30 (got 200)
  - ❌ WR ~55%+ (got 37.5%)
  - ❌ daily $ ~500 (got $-2,000)
  - ✅ low outlier dep (top-1%-share = 40.7%)

### v4_tight_asym
  - ❌ trades/day ~20-30 (got 71)
  - ❌ WR ~55%+ (got 37.4%)
  - ❌ daily $ ~500 (got $-733.18)
  - ✅ low outlier dep (top-1%-share = 40.5%)

### v5_2to1
  - ❌ trades/day ~20-30 (got 135)
  - ❌ WR ~55%+ (got 34.0%)
  - ❌ daily $ ~500 (got $-1,221)
  - ⚠️ check (top-1%-share = 77.5%)

## Verdict

- Variants in 20-30 trades/day band with ≥50% WR AND positive mean: **0/5**
- Variants with ANY positive mean per-trade: **0/5**

⚠️ **All five variants are net negative.** This strategy class as designed cannot approach the target profile. The diagnosis is clear and repeats across bracket geometries:

### The signature of "no edge"

| Variant | Bracket | Breakeven WR (with $10 cost) | Observed WR | Gap |
|---|---|--:|--:|--:|
| v1_base, v2_tight | 0.35/0.35 (1:1) | ~53.6% | **49.1-49.3%** | -4.5 pts |
| v3_asym, v4_tight_asym | 0.50/0.30 (1.67:1) | ~40% | **37.4-37.5%** | -2.6 pts |
| v5_2to1 | 1.00/0.50 (2:1) | ~35.7% | **34.0%** | -1.7 pts |

**Every variant lands at "random WR for the chosen R:R, minus a cost penalty."** That is the signature of a setup with no directional edge — the impulse+pullback+re-accel mechanic is selecting randomly from 1s NQ price action and the cost model erodes the small inefficiencies.

The "tight" variants (v2, v4) reduce trade count from ~200/day to ~70/day but **WR is unchanged** — fewer trades, same expected value per trade. Tightening the entry threshold doesn't add edge; it just samples less.

The 2:1 R:R variant (v5) hits the lowest WR-vs-breakeven gap (1.7 pts), but its top-1% share is **77.5%** — almost all of the PnL would come from a tiny number of outlier wins, the opposite of the user's "smoother equity, low outlier dependence" profile.

### The math conflict with the profile

Target: 25 trades/day × $20 net/trade = $500/day. After $10 commission/round-trip, gross expected per trade must be $30.

For PT = SL (symmetric bracket):
- Need WR × PT$ - (1-WR) × PT$ - cost = $20
- → 0.55 × PT - 0.45 × PT - 10 = 20
- → 0.10 × PT = 30 → **PT must be $300** (= 1.5 ATR if ATR(30s) = 10 pts)
- NQ ATR(30s) is rarely above 8 pts → 1.5 ATR PT requires holding through ~120s typically — no longer a "scalp"

For PT = 2 × SL:
- 0.40 × PT - 0.60 × (PT/2) - 10 = 20
- → 0.10 × PT = 30 → PT must be $300 again
- Same constraint

**The profile demands either a real signal worth ≥3 percentage points of WR over random, OR much wider targets (no longer a scalp).** The current mechanics provide neither.

### Conclusion: the strategy class needs a real signal, not just a timing trick

The "impulse + pullback + re-acceleration" pattern is intuitively appealing but operates on the same noisy data the random walk does. The pullback "filter" doesn't actually filter — it simply delays entry by 30s without selecting better setups (~64% of impulses become trades, and outcome is random).

This study cannot reach the target profile by tuning parameters alone. To make this strategy class viable would require:

1. **A real predictive signal** added to the entry — orderflow imbalance (delta/CVD bias at impulse moment), book-pressure asymmetry, options-implied skew, or a multi-bar context filter that genuinely separates 60% WR setups from 40% WR setups.
2. **A different setup family entirely** — opening range break with retest, prior-day VWAP/POC reversion, gap fade with first pullback, news-driven breakouts. These have known structural mechanics (mean-reversion to value, range expansion at session open) that don't depend solely on price-action geometry.

I recommend pivoting to one of those alternatives rather than continuing to tune the pullback-scalp parameters.

## Funnel diagnostics (per variant)

| Variant | RTH impulses | Pullback confirmed | Re-accel entries | Trades completed | PT exits | SL exits | Hold-stop exits |
|---|--:|--:|--:|--:|--:|--:|--:|
| v1_base | 79,017 | 62,382 | 50,672 | 50,672 | 24,806 | 25,673 | 193 |
| v2_tight | 28,057 | 22,368 | 18,126 | 18,126 | 8,911 | 9,146 | 69 |
| v3_asym | 78,555 | 62,010 | 50,362 | 50,362 | 18,849 | 31,430 | 83 |
| v4_tight_asym | 27,911 | 22,251 | 18,028 | 18,028 | 6,731 | 11,271 | 26 |
| v5_2to1 | 53,271 | 41,935 | 34,070 | 34,070 | 11,212 | 22,358 | 500 |
