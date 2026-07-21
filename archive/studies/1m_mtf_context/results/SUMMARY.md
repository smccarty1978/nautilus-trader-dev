# MTF Context Collector — Executive Summary

**Data**: 113,966 confirmed flip trades, NQ 2020-2025, 94 features collected
at bar+1 close.

**Bracket race (0.75/0.75 ATR, pre-computed):**
- PT-first: 55,459 (48.7%)
- SL-first: 56,819 (49.9%)
- Neither:  1,688 (1.5%)

**Top-line conclusion**: **No feature separates PT-first from SL-first.**
The MTF context collection doesn't find an edge.

---

## Cohen's d scan across all 85 tested features

Max |d| = **0.052** (`two_bar_close_vs_open_pct`). Breakdown:
- |d| ≥ 0.20 (meaningful): **0 features**
- |d| ≥ 0.10 (weak): **0 features**
- |d| ≥ 0.05 (noise-level): **1 feature**

Everything else is below 0.05. With N > 55K per group, even the tiniest
real signal would be detectable. The features genuinely don't
discriminate.

### Top 10 by |d| (all sub-noise)
```
two_bar_close_vs_open_pct   -0.052
bar1_close_vs_flip_close_atr -0.037
two_bar_body_atr             -0.032
micro_range_compression_5s   -0.019
high_vol_bar_count_10        +0.018
micro_max_retracement_5s     -0.016
ema_spread_15m_atr           -0.015
bar1_body_pct                -0.015
flip_close_location          +0.014
bar1_lower_wick_pct          +0.014
```

---

## What each category showed

### 1-2. Bar+1 Close Features (your priority)
| Split | PT% | Avg$ |
|---|---|---|
| bar1_close_above_flip_close=1 | 48.4% | -$7.4 |
| bar1_close_above_flip_close=0 | 49.2% | -$5.7 |
| bar1_close_above_50pct_range=1 | 48.2% | -$7.5 |
| bar1_close_above_50pct_range=0 | 49.2% | -$5.8 |

**Counter-intuitive**: bar+1 closing in the NON-flip direction (or lower
half of range) is slightly *less bad*. Both still net negative.

`bar1_hh_amount_atr` (strength of HH confirmation) **Q5** vs **Q1**:
- MFE: 3.07 vs 2.12 (big magnitude effect)
- PT-first: 48.7% vs 48.6% (**no direction effect**)

### 3. Multi-TF Alignment (biggest untested hypothesis)
| | PT% | Avg$ |
|---|---|---|
| all_regimes_aligned=1 (1m+5m+15m) | **48.4%** | -$7.2 |
| all_regimes_aligned=0 | 48.8% | -$6.5 |
| 5m aligned=1 | 48.5% | -$6.7 |
| 5m aligned=0 | 48.9% | -$6.7 |
| 15m aligned=1 | 48.7% | -$6.7 |
| 15m aligned=0 | 48.6% | -$6.7 |

**HTF alignment is slightly NEGATIVE.** Counter-flow entries do slightly
better. Likely because flips in established HTF trends are more often
the minor counter-move rather than the start of a new trend.

### 4. Volume at Flip + Bar+1
All Q5 (high volume) configs: MFE grows significantly (2.1 → 3.1) but
PT% remains flat at 48-49%. Classic magnitude-without-direction.

### 5. Pre-Flip Compression
- Smaller pre-flip range → slightly LARGER MFE but **no direction edge**
- `atr_14` Q5 (high vol): MFE 2.11 vs Q1's 2.80 — ATR-normalization works
- `prior_regime_mfe_atr` had an overflow bug on early bars (large values
  when ATR not yet warmed up) — treat its quintile data with skepticism

### 6. 5s Micro-Context
All quintiles 48-49% PT-first. `micro_trend_12bar_5s` (pre-flip 60s
momentum): Q5 = 49.2%, Q1 = 48.5%. Noise.
`bar1_internals_up_pct` (% of 5s bars within bar+1 closing up): no effect.

### 7. Cohen's d Full — see table above

### 8. Feature Interactions (pairwise Q5)
Best pair: `micro_max_retracement_5s ∩ ema_spread_15m_atr`
- N=5,819, PT=50.8%, SL=47.5%, Avg=**-$1.7**, PF=0.98

Closest any subset gets to breakeven. Still negative after commission.
3.3pp asymmetry (50.8 vs 47.5) but only on 5% of the population — not
statistically robust enough to trust.

---

## Interpretation

Everything the MTF collector captures — flip bar anatomy, bar+1
confirmation strength, HTF regime alignment, MA context, 1m volume
direction, 5m/15m regime state, 5s micro-context, time/session —
**collectively has zero directional edge.**

Features that DO exist (weakly):
- **Magnitude prediction**: volume, ATR, band width, flip bar size all
  correlate with larger MFE. Consistent with prior `cohens_d_mfe_magnitude.py`.
- **Regime identification**: alignment score, flip direction trivially
  identify which regime we're in.

Features that DON'T exist:
- **Direction prediction**: no observable characteristic at entry time
  predicts whether the bar+1-close-following price path will race to
  +0.75 ATR or -0.75 ATR first.

The EMA3/9 regime flip with bar+1 HH/LL confirmation is **fully priced
in** by the market. Subsequent 1 minute of price action is essentially
a random walk, coin-flipping between +0.75 and -0.75 ATR.

## Implications for next steps

1. **This entry signal cannot be filtered.** 94 features covering every
   reasonable angle (bar anatomy, HTF regime, micro-context, volume
   bullishness) yielded zero discrimination. No amount of feature
   engineering on this data set will produce a tradeable filter.

2. **Magnitude IS predictable but doesn't help brackets.** Confirmed
   in prior study and reconfirmed here. Volume/volatility expansion
   predicts bigger moves, but bigger moves land symmetrically.

3. **A fundamentally different signal is needed.** Candidates:
   - Different entry event (not regime flip)
   - Order flow or L2 book features (not in this collection)
   - Multi-asset / cross-correlation features
   - Longer-horizon context (daily, weekly regime)

4. **Or accept that NQ 1m regime flips are unpriced-in-but-random.**
   Mean MFE is real (2.4 ATR) but unextractable by any reactive exit.

## Output files

- `trades_all.parquet` — 113,966 trades × 156 columns
- `skipped_all.parquet` — 50,401 skipped flips (bar+1 no HH/LL)
- `cohens_d_full.parquet` — feature d scores sorted
- `report.md` — full analysis output (all 8 analyses concatenated)
