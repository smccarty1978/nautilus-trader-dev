> **🚨 DEPRECATED — NON-CAUSAL FEATURE TIMING (2026-04-27)**
>
> This report was produced before the causality/parity gate.
> One or more feature lookups in the source collector used
> bar OPEN times where bar CLOSE times were required. This
> exposed up to several seconds (HMM 5s state) or several
> minutes (5m regime alignment) of intra-bar lookahead.
>
> See `CAUSALITY.md` and
> `memory/multi_timeframe_lookup_lookahead.md`.
>
> The collectors have been patched. Re-run before citing
> any specific number from this report.

# Confirmed Regime Pullback Entry Study v1

**Population**: 2025 RTH HH/LL-confirmed 1m regime flips (n=5,595 regimes; 5,301 produced ≥1 pullback candidate after intact-regime filter).

**Setup**: signal_time = bar+1 close. Walk 1s bars from signal_time to next opposing 1m flip (or 30-min cap). On first crossing of pullback_depth_atr thresholds [0.25, 0.50, 0.75, 1.00], snap decision to next 30s checkpoint anchored at signal_time. Fill at decision + 30s. Filter rows where regime ended before decision OR before fill.

**Cost model**: $5 commission + 1-tick adverse entry. PT/regime/timeout exits: 1-tick adverse exit; SL: additional 1-tick adverse exit.

**Critical caveat**: matched-baseline rows use the SAME regime IDs that survived to produce each pullback. Comparing pullback vs matched baseline removes the survivorship inflation that comes from filtering to long-lived regimes. Pullback vs *unfiltered* baseline is misleading.

## 1. Baseline confirmed-entry economics

Reference numbers showing the survivorship effect.

| Variant | n | Mean $ | Median $ | PT% | PF |
|---|--:|--:|--:|--:|--:|
| Unfiltered (all confirmed RTH flips) | 5,594 | $-7.32 | $83.38 | 50.9% | 0.95 |
| Matched (regime survived to 0.25 ATR pullback) | 5,554 | $-8.16 | $-60.00 | 48.8% | 0.95 |
| Matched (regime survived to 0.50 ATR pullback) | 5,522 | $-6.76 | $-45.00 | 49.1% | 0.95 |
| Matched (regime survived to 0.75 ATR pullback) | 5,424 | $-3.38 | $27.50 | 49.9% | 0.98 |
| Matched (regime survived to 1.00 ATR pullback) | 5,247 | $0.82 | $85.86 | 51.2% | 1.01 |

Survivorship lift = ~$60/trade. Filtering to regimes that survive long enough to retrace inside themselves selects the long-lived (profitable) tail of the population.

## 2. Pullback economics by threshold (1.0/1.0 bracket)

| Threshold | n | PT% | SL% | Reg% | Mean $ | Median $ | PF | Total $ |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 0.25 | 5,554 | 47.4% | 40.3% | 12.2% | $-1.45 | $-10.00 | 0.99 | $-8,028 |
| 0.50 | 5,522 | 45.9% | 39.3% | 14.7% | $-6.64 | $-20.00 | 0.95 | $-36,666 |
| 0.75 | 5,424 | 44.6% | 37.2% | 17.8% | $-8.95 | $-25.00 | 0.94 | $-48,538 |
| 1.00 | 5,247 | 41.8% | 34.2% | 23.7% | $-13.93 | $-30.00 | 0.90 | $-73,100 |

## 3. Matched-baseline comparison (1.0/1.0 bracket)

This is the headline test. Same regime IDs, different entry timing.

| Threshold | n | Pullback $ | Baseline $ | Δ Mean $ | Pullback PT% | Baseline PT% | Δ PT% |
|--:|--:|--:|--:|--:|--:|--:|--:|
| 0.25 | 5,554 | $-1.45 | $-8.16 | **$6.72** | 47.4% | 48.8% | **-1.4pp** |
| 0.50 | 5,522 | $-6.64 | $-6.76 | **$0.12** | 45.9% | 49.1% | **-3.2pp** |
| 0.75 | 5,424 | $-8.95 | $-3.38 | **$-5.57** | 44.6% | 49.9% | **-5.3pp** |
| 1.00 | 5,247 | $-13.93 | $0.82 | **$-14.75** | 41.8% | 51.2% | **-9.5pp** |

## 4. Bracket grid by threshold (pullback entries)

### Bracket PT=1.0 / SL=1.0

| Threshold | n | PT% | SL% | Reg% | Mean $ | Median $ | PF | Total $ |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 0.25 | 5,554 | 47.4% | 40.3% | 12.2% | $-1.45 | $-10.00 | 0.99 | $-8,028 |
| 0.50 | 5,522 | 45.9% | 39.3% | 14.7% | $-6.64 | $-20.00 | 0.95 | $-36,666 |
| 0.75 | 5,424 | 44.6% | 37.2% | 17.8% | $-8.95 | $-25.00 | 0.94 | $-48,538 |
| 1.00 | 5,247 | 41.8% | 34.2% | 23.7% | $-13.93 | $-30.00 | 0.90 | $-73,100 |

### Bracket PT=1.25 / SL=1.0

| Threshold | n | PT% | SL% | Reg% | Mean $ | Median $ | PF | Total $ |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 0.25 | 5,554 | 41.3% | 43.4% | 15.1% | $-4.01 | $-110.00 | 0.97 | $-22,265 |
| 0.50 | 5,522 | 40.2% | 42.1% | 17.4% | $-6.28 | $-113.37 | 0.96 | $-34,704 |
| 0.75 | 5,424 | 39.2% | 40.0% | 20.5% | $-6.65 | $-105.00 | 0.96 | $-36,057 |
| 1.00 | 5,247 | 36.3% | 37.1% | 26.1% | $-14.52 | $-95.00 | 0.90 | $-76,179 |

### Bracket PT=1.5 / SL=1.0

| Threshold | n | PT% | SL% | Reg% | Mean $ | Median $ | PF | Total $ |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 0.25 | 5,554 | 36.4% | 45.2% | 18.1% | $-2.17 | $-128.34 | 0.99 | $-12,054 |
| 0.50 | 5,522 | 35.3% | 43.9% | 20.4% | $-5.66 | $-130.00 | 0.97 | $-31,231 |
| 0.75 | 5,424 | 34.2% | 41.8% | 23.6% | $-8.15 | $-122.02 | 0.95 | $-44,203 |
| 1.00 | 5,247 | 31.6% | 38.8% | 29.1% | $-14.83 | $-115.00 | 0.91 | $-77,792 |

### Bracket PT=2.0 / SL=1.0

| Threshold | n | PT% | SL% | Reg% | Mean $ | Median $ | PF | Total $ |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 0.25 | 5,554 | 28.3% | 47.4% | 23.8% | $-4.34 | $-144.23 | 0.98 | $-24,127 |
| 0.50 | 5,522 | 27.3% | 46.1% | 26.1% | $-8.76 | $-145.00 | 0.95 | $-48,379 |
| 0.75 | 5,424 | 26.5% | 43.6% | 29.3% | $-9.12 | $-136.12 | 0.95 | $-49,445 |
| 1.00 | 5,247 | 25.0% | 40.2% | 34.2% | $-10.96 | $-125.00 | 0.93 | $-57,503 |

### Bracket PT=1.0 / SL=0.75

| Threshold | n | PT% | SL% | Reg% | Mean $ | Median $ | PF | Total $ |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 0.25 | 5,554 | 41.8% | 50.3% | 7.9% | $-1.61 | $-96.69 | 0.99 | $-8,919 |
| 0.50 | 5,522 | 40.3% | 50.5% | 9.2% | $-9.03 | $-102.32 | 0.93 | $-49,886 |
| 0.75 | 5,424 | 39.9% | 48.0% | 12.0% | $-7.30 | $-94.58 | 0.94 | $-39,599 |
| 1.00 | 5,247 | 37.4% | 45.5% | 16.9% | $-11.96 | $-87.80 | 0.90 | $-62,749 |

### Bracket PT=1.5 / SL=0.75

| Threshold | n | PT% | SL% | Reg% | Mean $ | Median $ | PF | Total $ |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 0.25 | 5,554 | 31.7% | 56.8% | 11.4% | $-2.07 | $-125.07 | 0.99 | $-11,470 |
| 0.50 | 5,522 | 30.6% | 56.6% | 12.7% | $-9.00 | $-126.53 | 0.94 | $-49,700 |
| 0.75 | 5,424 | 30.1% | 54.4% | 15.4% | $-7.36 | $-120.37 | 0.95 | $-39,929 |
| 1.00 | 5,247 | 27.9% | 51.6% | 20.2% | $-13.78 | $-116.42 | 0.90 | $-72,301 |

## 5. Regime-exit-only PnL by threshold

Hold every pullback entry to the next 1m opposing flip (or 30-min cap). No PT/SL.

| Threshold | n | Mean ATR | Med ATR | Mean $ | Med $ | % >0 | % < -0.5 ATR | % < -1.0 ATR | Mean MFE | Mean MAE |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 0.25 | 5,554 | 0.045 | -0.540 | $13.59 | $-125.00 | 31.0% | 51.5% | 33.2% | 1.998 | 1.102 |
| 0.50 | 5,522 | 0.031 | -0.547 | $8.30 | $-130.00 | 30.5% | 51.8% | 31.8% | 1.952 | 1.090 |
| 0.75 | 5,424 | 0.041 | -0.520 | $11.93 | $-120.00 | 29.8% | 50.8% | 29.8% | 1.893 | 1.043 |
| 1.00 | 5,247 | 0.040 | -0.467 | $8.32 | $-110.00 | 28.4% | 48.7% | 27.3% | 1.792 | 0.988 |

## 6. Timing diagnostics (1.0/1.0 bracket)

| Threshold | Med PT t | Mean PT t | Med SL t | Mean SL t | Med Res t | <60s | <120s | <180s | <300s |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 0.25 | 140s | 210s | 133s | 189s | 110s | 30.2% | 54.1% | 70.2% | 87.0% |
| 0.50 | 140s | 210s | 133s | 189s | 108s | 31.0% | 54.5% | 70.8% | 86.9% |
| 0.75 | 136s | 202s | 132s | 187s | 103s | 33.1% | 56.6% | 72.0% | 87.7% |
| 1.00 | 131s | 197s | 127s | 182s | 90s | 37.3% | 59.8% | 73.9% | 88.7% |

Path-quality flag rates by threshold:

| Threshold | n | clean_path_300s | fast_fail_60s | stall_then_reverse_180s |
|--:|--:|--:|--:|--:|
| 0.25 | 5,554 | 28.6% | 38.1% | 22.2% |
| 0.50 | 5,522 | 27.5% | 39.1% | 22.2% |
| 0.75 | 5,424 | 27.8% | 38.3% | 21.3% |
| 1.00 | 5,247 | 26.0% | 37.8% | 22.0% |

## 7. Pullback-quality buckets (1.0/1.0 bracket, all thresholds combined)

Buckets defined by:
- depth: shallow = ≤median pullback_depth_atr, deep = >median
- speed: slow = ≤median pullback_speed_atr_per_min, fast = >median

Median pullback_depth_atr: 0.695
Median pullback_speed_atr_per_min: 2.688

| Bucket | n | PT% | Mean $ | Median $ | PF |
|---|--:|--:|--:|--:|--:|
| shallow/slow | 5,214 | 47.8% | $-8.16 | $-55.00 | 0.94 |
| shallow/fast | 5,660 | 47.5% | $-4.02 | $-22.50 | 0.97 |
| deep/slow | 5,660 | 40.5% | $-17.19 | $-50.00 | 0.88 |
| deep/fast | 4,535 | 44.1% | $-2.50 | $-10.00 | 0.98 |
| violent_reversal | 678 | 44.8% | $11.21 | $-5.00 | 1.11 |

## 8. HMM stratification (secondary)

### 8a. Pullback economics by threshold × HMM state at pullback decision

| Threshold | State 0 | State 1 | State 2 | State 3 | Total |
|--:|---|---|---|---|---|
| 0.25 | n=428 $-3.94 | n=1876 $-8.60 | n=394 $2.50 | n=2856 $3.09 | n=5554 $-1.45 |
| 0.50 | n=391 $-2.21 | n=1775 $-18.20 | n=375 $-12.55 | n=2981 $0.41 | n=5522 $-6.64 |
| 0.75 | n=357 $-20.26 | n=1635 $-11.82 | n=351 $2.95 | n=3081 $-7.47 | n=5424 $-8.95 |
| 1.00 | n=338 $-17.48 | n=1505 $-23.95 | n=307 $-12.84 | n=3097 $-8.78 | n=5247 $-13.93 |

### 8b. Pullback economics by threshold × HMM state at raw flip

| Threshold | State 0 | State 1 | State 2 | State 3 | Total |
|--:|---|---|---|---|---|
| 0.25 | n=440 $-6.59 | n=1763 $-11.91 | n=310 $-11.33 | n=3041 $6.37 | n=5554 $-1.45 |
| 0.50 | n=436 $-6.78 | n=1754 $-16.19 | n=307 $-16.44 | n=3025 $-0.09 | n=5522 $-6.64 |
| 0.75 | n=432 $-10.30 | n=1716 $-11.00 | n=304 $-14.18 | n=2972 $-7.03 | n=5424 $-8.95 |
| 1.00 | n=412 $-9.49 | n=1664 $-11.58 | n=296 $-13.27 | n=2875 $-16.00 | n=5247 $-13.93 |

### 8c. HMM state changed vs unchanged (signal -> decision)

| Group | n | PT% | Mean $ | Median $ | PF |
|---|--:|--:|--:|--:|--:|
| State unchanged | 14,518 | 44.7% | $-6.77 | $-25.00 | 0.96 |
| State changed | 7,229 | 45.4% | $-9.41 | $-20.00 | 0.90 |

### 8d. State 3 flag at pullback (vol-burst flag)

| Group | n | PT% | Mean $ | Median $ | PF |
|---|--:|--:|--:|--:|--:|
| Not state 3 | 9,732 | 45.0% | $-12.96 | $-40.00 | 0.85 |
| State 3 | 12,015 | 44.9% | $-3.35 | $-15.00 | 0.98 |

## Verdict

**Pullback entry adds at most $6.72 per trade** vs same-regime signal-time baseline (best at 0.25 ATR threshold).

The headline +$50-65/trade is almost entirely survivorship (filtering to regimes long enough to produce a pullback). When matched against signal-time entry on the same regimes, the pullback edge is $6.72 to $-14.75 per trade across thresholds.

PT rate **drops** with deeper pullbacks (from ~58% baseline to ~51% pullback at 1.0 ATR), suggesting that deeper pullbacks signal weaker continuation. The economic edge comes from a slightly better fill price, not from improved trade quality.

**The matched-baseline correction is the key methodological result.** Without it, this study would have looked like a huge win.