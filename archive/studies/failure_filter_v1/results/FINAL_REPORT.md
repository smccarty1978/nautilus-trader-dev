# Failure-Filter Sweep — Final Report

Label: `is_failure = 1 iff mfe_300s_atr<0.25 AND pt100!=1` (SL/regime/unresolved with no traction).
Mode: `exclude` — skip trades when failure score >= threshold (val percentile).
Cost model: $5 commission + 1-tick adverse entry + 1-tick exit slip on SL/regime.

## 2024 OOS — economics by filter level (ALL stratum)

| Level | n | Mean $ | Median $ | Trim 5% | PF | Win% | PT% | SL% | Regime% | Total $ |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| baseline | 37,710 | $-14.28 | $-40.00 | $-14.14 | 0.81 | 47.6% | 46.4% | 43.1% | 10.5% | $-538,390 |
| excl_top5 | MISSING |
| excl_top10 | 36,967 | $-14.22 | $-40.00 | $-14.07 | 0.81 | 47.7% | 46.7% | 43.5% | 9.8% | $-525,490 |
| excl_top20 | MISSING |
| excl_top30 | MISSING |

## 2026 OOS — economics by filter level (ALL stratum)

| Level | n | Mean $ | Median $ | Trim 5% | PF | Win% | PT% | SL% | Regime% | Total $ |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| baseline | 11,034 | $-11.55 | $-55.00 | $-12.02 | 0.90 | 48.3% | 48.0% | 42.9% | 9.1% | $-127,400 |
| excl_top5 | MISSING |
| excl_top10 | 10,845 | $-11.92 | $-60.00 | $-12.46 | 0.90 | 48.4% | 48.2% | 43.4% | 8.4% | $-129,260 |
| excl_top20 | MISSING |
| excl_top30 | MISSING |

## Outcome-mix shift — does the filter reduce failures?

Compare baseline vs each exclusion level on PT% / SL% / Regime% — improvement means PT% rises and SL%/Regime% drops.

### 2024

| Level | n | PT% | SL% | Regime% | Δ PT pp | Δ SL pp | Δ Regime pp |
|---|--:|--:|--:|--:|--:|--:|--:|
| baseline | 37,710 | 46.4% | 43.1% | 10.5% | +0.0 | +0.0 | +0.0 |
| excl_top10 | 36,967 | 46.7% | 43.5% | 9.8% | +0.2 | +0.4 | -0.7 |

### 2026

| Level | n | PT% | SL% | Regime% | Δ PT pp | Δ SL pp | Δ Regime pp |
|---|--:|--:|--:|--:|--:|--:|--:|
| baseline | 11,034 | 48.0% | 42.9% | 9.1% | +0.0 | +0.0 | +0.0 |
| excl_top10 | 10,845 | 48.2% | 43.4% | 8.4% | +0.1 | +0.5 | -0.7 |

## Stratified — best filter per stratum × year

### 2024

| Stratum | Best level | n | Mean $ | PF | Total $ |
|---|---|--:|--:|--:|--:|
| all | excl_top10 | 36,967 | $-14.22 | 0.81 | $-525,490 |
| long | baseline | 17,856 | $-15.12 | 0.80 | $-270,065 |
| short | excl_top10 | 19,457 | $-13.35 | 0.82 | $-259,770 |
| T_0_90 | excl_top10 | 12,345 | $-13.45 | 0.82 | $-166,010 |
| T_90_180 | baseline | 5,769 | $-14.60 | 0.80 | $-84,205 |
| T_180_300 | excl_top10 | 6,352 | $-16.36 | 0.78 | $-103,920 |
| T_300_450 | baseline | 6,518 | $-12.99 | 0.81 | $-84,670 |
| T_450_600 | excl_top10 | 6,278 | $-12.91 | 0.82 | $-81,050 |

### 2026

| Stratum | Best level | n | Mean $ | PF | Total $ |
|---|---|--:|--:|--:|--:|
| all | baseline | 11,034 | $-11.55 | 0.90 | $-127,400 |
| long | excl_top10 | 5,178 | $-14.90 | 0.87 | $-77,130 |
| short | baseline | 5,783 | $-8.23 | 0.92 | $-47,605 |
| T_0_90 | baseline | 3,806 | $-17.95 | 0.85 | $-68,315 |
| T_90_180 | baseline | 1,609 | $-15.53 | 0.87 | $-24,990 |
| T_180_300 | excl_top10 | 1,869 | $-9.85 | 0.91 | $-18,415 |
| T_300_450 | baseline | 1,898 | $-10.66 | 0.90 | $-20,230 |
| T_450_600 | excl_top10 | 1,779 | $4.15 | 1.04 | $7,385 |

## Verdict

**Filter does not produce profitable strategy on either year. The signal exists in classification but doesn't translate to economic improvement after costs.**