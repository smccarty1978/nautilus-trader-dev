# Bar1-Confirmed Stair-Step Validation Study — Results

NQ `NQ.v.0` 2021-2024, 1s-OHLC execution, safe-replay fills. Cost: PRIMARY = entry 0 / exit 0.5 tick / PT 0 / $5 RT. Warmed entries only.

Total Bar1-Confirmed (Population B) Entries: 29,930


### Population B (Bar1-confirmed) — All Sides (Pooled)

| version | n | net_per_tr | gross_per_tr | stress_per_tr | net_PF | gross_PF | med_atr | max_dd | avg_hold_s | pct_stop | pct_regime | pct_pt | pct_gate | winner_pct | loser_pct | reach2 | capt2 | capt3 | mfe_capture | med_giveback_atr | loser_bot10_atr | runner_top10_atr |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| V0_regime | 47,068 | -10.5 | -3.0 | -13.0 | 0.91 | 0.97 | -0.78 | -549,288 | 1125 | 0.0% | 100.0% | 0.0% | 0.0% | 32.5% | 67.5% | 40.2% | 14.5% | 9.8% | -0.48 | +2.24 | -2.89 | +6.25 |
| BR10 | 47,068 | -12.3 | -5.5 | -14.0 | 0.86 | 0.93 | -1.01 | -582,315 | 398 | 57.8% | 11.1% | 31.1% | 0.0% | 32.3% | 67.7% | 25.6% | 15.3% | 0.0% | -0.89 | +1.25 | -1.31 | +2.02 |
| BR15 | 47,068 | -10.3 | -3.7 | -11.9 | 0.90 | 0.96 | -0.83 | -494,675 | 534 | 35.4% | 27.4% | 37.2% | 0.0% | 38.6% | 61.4% | 30.6% | 18.4% | 0.0% | -0.58 | +1.59 | -1.76 | +2.03 |
| V1_ladder | 47,068 | -16.4 | -8.9 | -18.9 | 0.72 | 0.83 | -0.32 | -781,820 | 317 | 94.2% | 5.8% | 0.0% | 0.0% | 23.5% | 76.5% | 15.8% | 3.9% | 2.7% | -0.42 | +1.11 | -1.01 | +2.66 |
| V2_gate_ladder | 47,068 | -14.5 | -7.0 | -17.0 | 0.69 | 0.83 | -0.28 | -692,885 | 248 | 56.4% | 4.5% | 0.0% | 39.1% | 19.0% | 81.0% | 13.0% | 3.2% | 2.2% | -0.50 | +0.96 | -0.94 | +2.33 |
| V3_struct_1m | 47,068 | -14.3 | -6.8 | -16.8 | 0.73 | 0.86 | -0.34 | -677,272 | 245 | 60.9% | 0.0% | 0.0% | 39.1% | 18.6% | 81.4% | 15.9% | 5.6% | 3.1% | -0.67 | +0.97 | -0.97 | +2.90 |
| V3_struct_5s | 47,068 | -13.1 | -5.6 | -15.6 | 0.67 | 0.84 | -0.18 | -617,520 | 75 | 60.9% | 0.0% | 0.0% | 39.1% | 30.3% | 69.7% | 5.2% | 1.8% | 0.6% | -0.33 | +0.63 | -0.92 | +1.56 |
| V4D1_ma_1m | 47,068 | -15.5 | -8.0 | -18.0 | 0.80 | 0.89 | -0.77 | -737,855 | 469 | 95.1% | 4.9% | 0.0% | 0.0% | 23.3% | 76.7% | 24.1% | 8.5% | 5.3% | -0.89 | +1.36 | -1.08 | +4.01 |
| V4D1_ma_5s | 47,068 | -14.2 | -6.7 | -16.7 | 0.60 | 0.78 | -0.17 | -669,125 | 55 | 100.0% | 0.0% | 0.0% | 0.0% | 27.6% | 72.4% | 4.8% | 1.6% | 0.6% | -0.32 | +0.57 | -0.87 | +1.42 |
| V4D2_ma_1m | 47,068 | -15.2 | -7.7 | -17.7 | 0.80 | 0.89 | -0.77 | -726,420 | 478 | 94.1% | 5.9% | 0.0% | 0.0% | 23.1% | 76.9% | 24.1% | 8.6% | 5.4% | -0.89 | +1.36 | -1.08 | +4.05 |
| V4D2_ma_5s | 47,068 | -14.5 | -7.0 | -17.0 | 0.63 | 0.79 | -0.13 | -682,260 | 68 | 100.0% | 0.0% | 0.0% | 0.0% | 30.9% | 69.1% | 5.4% | 1.9% | 0.6% | -0.20 | +0.62 | -0.94 | +1.53 |
| V5_hybrid_1m | 47,068 | -14.1 | -6.6 | -16.6 | 0.72 | 0.85 | -0.30 | -668,665 | 211 | 60.8% | 0.1% | 0.0% | 39.1% | 14.9% | 85.1% | 15.0% | 5.2% | 2.9% | -0.50 | +0.90 | -0.93 | +2.77 |
| V5_hybrid_5s | 47,068 | -13.6 | -6.1 | -16.1 | 0.70 | 0.84 | -0.27 | -644,952 | 105 | 60.9% | 0.0% | 0.0% | 39.1% | 25.9% | 74.1% | 7.0% | 2.4% | 0.7% | -0.50 | +0.75 | -0.93 | +1.75 |

### Critical Comparison Table (All Sides Pooled)

| Version | loser bot 10% | giveback | runner top 10% | +3 ATR capture | net $/trade |
| --- | --- | --- | --- | --- | --- |
| V0_regime | -2.89 | +2.24 | +6.25 | 9.8% | -10.5 |
| BR10 | -1.31 | +1.25 | +2.02 | 0.0% | -12.3 |
| BR15 | -1.76 | +1.59 | +2.03 | 0.0% | -10.3 |
| V1_ladder | -1.01 | +1.11 | +2.66 | 2.7% | -16.4 |
| V2_gate_ladder | -0.94 | +0.96 | +2.33 | 2.2% | -14.5 |
| V3_struct_1m | -0.97 | +0.97 | +2.90 | 3.1% | -14.3 |
| V3_struct_5s | -0.92 | +0.63 | +1.56 | 0.6% | -13.1 |
| V4D1_ma_1m | -1.08 | +1.36 | +4.01 | 5.3% | -15.5 |
| V4D1_ma_5s | -0.87 | +0.57 | +1.42 | 0.6% | -14.2 |
| V4D2_ma_1m | -1.08 | +1.36 | +4.05 | 5.4% | -15.2 |
| V4D2_ma_5s | -0.94 | +0.62 | +1.53 | 0.6% | -14.5 |
| V5_hybrid_1m | -0.93 | +0.90 | +2.77 | 2.9% | -14.1 |
| V5_hybrid_5s | -0.93 | +0.75 | +1.75 | 0.7% | -13.6 |

### Population B (Bar1-confirmed) — Long-Only (Pooled)

| version | n | net_per_tr | gross_per_tr | stress_per_tr | net_PF | gross_PF | med_atr | max_dd | avg_hold_s | pct_stop | pct_regime | pct_pt | pct_gate | winner_pct | loser_pct | reach2 | capt2 | capt3 | mfe_capture | med_giveback_atr | loser_bot10_atr | runner_top10_atr |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| V0_regime | 23,856 | -9.3 | -1.8 | -11.8 | 0.92 | 0.98 | -0.74 | -251,858 | 1152 | 0.0% | 100.0% | 0.0% | 0.0% | 33.6% | 66.4% | 39.7% | 14.7% | 9.9% | -0.46 | +2.16 | -2.83 | +5.99 |
| BR10 | 23,856 | -12.2 | -5.5 | -13.9 | 0.86 | 0.93 | -1.01 | -302,155 | 426 | 57.1% | 12.1% | 30.8% | 0.0% | 32.3% | 67.7% | 25.2% | 15.2% | 0.0% | -0.88 | +1.27 | -1.30 | +2.02 |
| BR15 | 23,856 | -10.5 | -3.9 | -12.0 | 0.90 | 0.96 | -0.79 | -259,228 | 568 | 34.6% | 28.7% | 36.7% | 0.0% | 38.4% | 61.6% | 30.1% | 18.1% | 0.0% | -0.55 | +1.58 | -1.76 | +2.03 |
| V1_ladder | 23,856 | -15.7 | -8.2 | -18.2 | 0.73 | 0.84 | -0.32 | -381,895 | 353 | 93.6% | 6.4% | 0.0% | 0.0% | 23.6% | 76.4% | 15.9% | 4.3% | 2.9% | -0.43 | +1.11 | -1.00 | +2.68 |
| V2_gate_ladder | 23,856 | -13.7 | -6.2 | -16.2 | 0.71 | 0.85 | -0.27 | -334,875 | 272 | 55.5% | 4.9% | 0.0% | 39.7% | 18.9% | 81.1% | 12.9% | 3.4% | 2.3% | -0.50 | +0.95 | -0.93 | +2.34 |
| V3_struct_1m | 23,856 | -13.6 | -6.1 | -16.1 | 0.74 | 0.87 | -0.33 | -328,468 | 249 | 60.3% | 0.0% | 0.0% | 39.7% | 19.1% | 80.9% | 15.3% | 5.6% | 3.0% | -0.67 | +0.95 | -0.96 | +2.84 |
| V3_struct_5s | 23,856 | -13.1 | -5.6 | -15.6 | 0.66 | 0.83 | -0.17 | -315,085 | 76 | 60.3% | 0.0% | 0.0% | 39.7% | 30.5% | 69.5% | 4.6% | 1.6% | 0.5% | -0.32 | +0.60 | -0.91 | +1.49 |
| V4D1_ma_1m | 23,856 | -15.3 | -7.8 | -17.8 | 0.80 | 0.89 | -0.76 | -368,402 | 466 | 94.9% | 5.1% | 0.0% | 0.0% | 24.1% | 75.9% | 23.6% | 8.7% | 5.2% | -0.90 | +1.34 | -1.07 | +3.90 |
| V4D1_ma_5s | 23,856 | -14.2 | -6.7 | -16.7 | 0.59 | 0.77 | -0.16 | -341,062 | 48 | 100.0% | 0.0% | 0.0% | 0.0% | 27.7% | 72.3% | 4.2% | 1.5% | 0.5% | -0.30 | +0.55 | -0.87 | +1.36 |
| V4D2_ma_1m | 23,856 | -14.9 | -7.4 | -17.4 | 0.81 | 0.90 | -0.76 | -359,168 | 472 | 94.0% | 6.0% | 0.0% | 0.0% | 23.9% | 76.1% | 23.6% | 8.7% | 5.3% | -0.90 | +1.34 | -1.07 | +3.95 |
| V4D2_ma_5s | 23,856 | -14.3 | -6.8 | -16.8 | 0.62 | 0.79 | -0.12 | -343,892 | 62 | 100.0% | 0.0% | 0.0% | 0.0% | 31.0% | 69.0% | 4.8% | 1.7% | 0.6% | -0.20 | +0.58 | -0.94 | +1.46 |
| V5_hybrid_1m | 23,856 | -13.3 | -5.8 | -15.8 | 0.73 | 0.86 | -0.29 | -321,842 | 215 | 60.2% | 0.1% | 0.0% | 39.7% | 15.1% | 84.9% | 14.7% | 5.4% | 2.9% | -0.50 | +0.88 | -0.92 | +2.75 |
| V5_hybrid_5s | 23,856 | -13.9 | -6.4 | -16.4 | 0.69 | 0.84 | -0.27 | -333,332 | 103 | 60.3% | 0.0% | 0.0% | 39.7% | 25.4% | 74.6% | 6.4% | 2.2% | 0.6% | -0.50 | +0.72 | -0.91 | +1.70 |

### Critical Comparison Table (Long-Only)

| Version | loser bot 10% | giveback | runner top 10% | +3 ATR capture | net $/trade |
| --- | --- | --- | --- | --- | --- |
| V0_regime | -2.83 | +2.16 | +5.99 | 9.9% | -9.3 |
| BR10 | -1.30 | +1.27 | +2.02 | 0.0% | -12.2 |
| BR15 | -1.76 | +1.58 | +2.03 | 0.0% | -10.5 |
| V1_ladder | -1.00 | +1.11 | +2.68 | 2.9% | -15.7 |
| V2_gate_ladder | -0.93 | +0.95 | +2.34 | 2.3% | -13.7 |
| V3_struct_1m | -0.96 | +0.95 | +2.84 | 3.0% | -13.6 |
| V3_struct_5s | -0.91 | +0.60 | +1.49 | 0.5% | -13.1 |
| V4D1_ma_1m | -1.07 | +1.34 | +3.90 | 5.2% | -15.3 |
| V4D1_ma_5s | -0.87 | +0.55 | +1.36 | 0.5% | -14.2 |
| V4D2_ma_1m | -1.07 | +1.34 | +3.95 | 5.3% | -14.9 |
| V4D2_ma_5s | -0.94 | +0.58 | +1.46 | 0.6% | -14.3 |
| V5_hybrid_1m | -0.92 | +0.88 | +2.75 | 2.9% | -13.3 |
| V5_hybrid_5s | -0.91 | +0.72 | +1.70 | 0.6% | -13.9 |

### Population B (Bar1-confirmed) — Short-Only (Pooled)

| version | n | net_per_tr | gross_per_tr | stress_per_tr | net_PF | gross_PF | med_atr | max_dd | avg_hold_s | pct_stop | pct_regime | pct_pt | pct_gate | winner_pct | loser_pct | reach2 | capt2 | capt3 | mfe_capture | med_giveback_atr | loser_bot10_atr | runner_top10_atr |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| V0_regime | 23,212 | -11.7 | -4.2 | -14.2 | 0.90 | 0.96 | -0.83 | -300,028 | 1098 | 0.0% | 100.0% | 0.0% | 0.0% | 31.4% | 68.6% | 40.8% | 14.2% | 9.6% | -0.50 | +2.32 | -2.95 | +6.51 |
| BR10 | 23,212 | -12.3 | -5.6 | -14.0 | 0.86 | 0.93 | -1.01 | -288,635 | 369 | 58.4% | 10.1% | 31.5% | 0.0% | 32.4% | 67.6% | 26.0% | 15.5% | 0.0% | -0.89 | +1.24 | -1.32 | +2.02 |
| BR15 | 23,212 | -10.1 | -3.6 | -11.7 | 0.90 | 0.96 | -0.87 | -243,255 | 498 | 36.3% | 26.0% | 37.7% | 0.0% | 38.8% | 61.2% | 31.2% | 18.7% | 0.0% | -0.60 | +1.59 | -1.76 | +2.03 |
| V1_ladder | 23,212 | -17.2 | -9.7 | -19.7 | 0.70 | 0.81 | -0.32 | -401,790 | 280 | 94.7% | 5.3% | 0.0% | 0.0% | 23.4% | 76.6% | 15.7% | 3.6% | 2.5% | -0.42 | +1.12 | -1.02 | +2.63 |
| V2_gate_ladder | 23,212 | -15.4 | -7.9 | -17.9 | 0.68 | 0.81 | -0.28 | -358,670 | 223 | 57.4% | 4.1% | 0.0% | 38.4% | 19.1% | 80.9% | 13.1% | 2.9% | 2.1% | -0.50 | +0.97 | -0.95 | +2.32 |
| V3_struct_1m | 23,212 | -15.0 | -7.5 | -17.5 | 0.73 | 0.85 | -0.36 | -351,212 | 241 | 61.5% | 0.0% | 0.0% | 38.4% | 18.1% | 81.9% | 16.4% | 5.6% | 3.3% | -0.67 | +0.99 | -0.98 | +2.97 |
| V3_struct_5s | 23,212 | -13.0 | -5.5 | -15.5 | 0.68 | 0.84 | -0.19 | -303,945 | 74 | 61.5% | 0.0% | 0.0% | 38.4% | 30.1% | 69.9% | 5.9% | 2.1% | 0.6% | -0.33 | +0.67 | -0.93 | +1.63 |
| V4D1_ma_1m | 23,212 | -15.7 | -8.2 | -18.2 | 0.80 | 0.88 | -0.77 | -375,788 | 472 | 95.2% | 4.8% | 0.0% | 0.0% | 22.5% | 77.5% | 24.6% | 8.4% | 5.3% | -0.88 | +1.39 | -1.09 | +4.11 |
| V4D1_ma_5s | 23,212 | -14.2 | -6.7 | -16.7 | 0.61 | 0.78 | -0.18 | -330,170 | 62 | 100.0% | 0.0% | 0.0% | 0.0% | 27.5% | 72.5% | 5.4% | 1.8% | 0.6% | -0.33 | +0.60 | -0.88 | +1.49 |
| V4D2_ma_1m | 23,212 | -15.6 | -8.1 | -18.1 | 0.80 | 0.89 | -0.77 | -373,062 | 485 | 94.2% | 5.8% | 0.0% | 0.0% | 22.3% | 77.7% | 24.6% | 8.4% | 5.4% | -0.89 | +1.40 | -1.09 | +4.14 |
| V4D2_ma_5s | 23,212 | -14.6 | -7.1 | -17.1 | 0.63 | 0.80 | -0.14 | -340,295 | 75 | 99.9% | 0.1% | 0.0% | 0.0% | 30.8% | 69.2% | 6.1% | 2.1% | 0.7% | -0.20 | +0.67 | -0.95 | +1.60 |
| V5_hybrid_1m | 23,212 | -14.9 | -7.4 | -17.4 | 0.71 | 0.83 | -0.30 | -348,098 | 206 | 61.5% | 0.1% | 0.0% | 38.4% | 14.6% | 85.4% | 15.3% | 5.1% | 3.0% | -0.50 | +0.92 | -0.95 | +2.80 |
| V5_hybrid_5s | 23,212 | -13.4 | -5.9 | -15.9 | 0.70 | 0.85 | -0.28 | -313,195 | 107 | 61.5% | 0.1% | 0.0% | 38.4% | 26.3% | 73.7% | 7.6% | 2.7% | 0.7% | -0.50 | +0.76 | -0.94 | +1.80 |

### Critical Comparison Table (Short-Only)

| Version | loser bot 10% | giveback | runner top 10% | +3 ATR capture | net $/trade |
| --- | --- | --- | --- | --- | --- |
| V0_regime | -2.95 | +2.32 | +6.51 | 9.6% | -11.7 |
| BR10 | -1.32 | +1.24 | +2.02 | 0.0% | -12.3 |
| BR15 | -1.76 | +1.59 | +2.03 | 0.0% | -10.1 |
| V1_ladder | -1.02 | +1.12 | +2.63 | 2.5% | -17.2 |
| V2_gate_ladder | -0.95 | +0.97 | +2.32 | 2.1% | -15.4 |
| V3_struct_1m | -0.98 | +0.99 | +2.97 | 3.3% | -15.0 |
| V3_struct_5s | -0.93 | +0.67 | +1.63 | 0.6% | -13.0 |
| V4D1_ma_1m | -1.09 | +1.39 | +4.11 | 5.3% | -15.7 |
| V4D1_ma_5s | -0.88 | +0.60 | +1.49 | 0.6% | -14.2 |
| V4D2_ma_1m | -1.09 | +1.40 | +4.14 | 5.4% | -15.6 |
| V4D2_ma_5s | -0.95 | +0.67 | +1.60 | 0.7% | -14.6 |
| V5_hybrid_1m | -0.95 | +0.92 | +2.80 | 3.0% | -14.9 |
| V5_hybrid_5s | -0.94 | +0.76 | +1.80 | 0.7% | -13.4 |

### Per-Year Net $/Trade (Population B, Primary Cost)

| version | 2021 | 2022 | 2023 | 2024 |
| --- | --- | --- | --- | --- |
| V0_regime | -12.1 | -12.8 | -12.0 | -5.0 |
| BR10 | -12.0 | -17.5 | -9.4 | -10.1 |
| BR15 | -10.5 | -16.3 | -7.4 | -7.0 |
| V1_ladder | -16.2 | -19.2 | -14.8 | -15.6 |
| V2_gate_ladder | -13.6 | -18.2 | -13.5 | -12.9 |
| V3_struct_1m | -14.0 | -18.1 | -11.5 | -13.6 |
| V3_struct_5s | -12.4 | -16.8 | -11.8 | -11.3 |
| V4D1_ma_1m | -15.8 | -18.7 | -14.1 | -13.3 |
| V4D1_ma_5s | -13.6 | -16.9 | -12.9 | -13.4 |
| V4D2_ma_1m | -16.1 | -18.0 | -13.8 | -13.1 |
| V4D2_ma_5s | -13.7 | -18.3 | -12.4 | -13.4 |
| V5_hybrid_1m | -13.2 | -16.9 | -12.5 | -13.8 |
| V5_hybrid_5s | -13.1 | -16.6 | -12.3 | -12.6 |

### Per-Year Trade Counts (Population B)

| version | 2021 | 2022 | 2023 | 2024 |
| --- | --- | --- | --- | --- |
| V0_regime | 11,625 | 11,825 | 11,788 | 11,830 |
| BR10 | 11,625 | 11,825 | 11,788 | 11,830 |
| BR15 | 11,625 | 11,825 | 11,788 | 11,830 |
| V1_ladder | 11,625 | 11,825 | 11,788 | 11,830 |
| V2_gate_ladder | 11,625 | 11,825 | 11,788 | 11,830 |
| V3_struct_1m | 11,625 | 11,825 | 11,788 | 11,830 |
| V3_struct_5s | 11,625 | 11,825 | 11,788 | 11,830 |
| V4D1_ma_1m | 11,625 | 11,825 | 11,788 | 11,830 |
| V4D1_ma_5s | 11,625 | 11,825 | 11,788 | 11,830 |
| V4D2_ma_1m | 11,625 | 11,825 | 11,788 | 11,830 |
| V4D2_ma_5s | 11,625 | 11,825 | 11,788 | 11,830 |
| V5_hybrid_1m | 11,625 | 11,825 | 11,788 | 11,830 |
| V5_hybrid_5s | 11,625 | 11,825 | 11,788 | 11,830 |

## Validation Questions & Answers

### Q1: Does any stair-step architecture improve expectancy versus Bar1 regime exits (V0)?
**Yes.** The following configurations improved net expectancy: BR15 (-10.3 vs V0 -10.5).

### Q2: Does any architecture reduce loser tails while preserving runner tails?
**No.** The structural trade-off between the loser tail and the runner tail is fully confirmed on the Bar1-confirmed population: 
- **V0 Regime (Baseline):** Loser bottom 10% was **-2.89 ATR**, runner top 10% was **+6.25 ATR**, +3 ATR capture was **9.8%**.
- **V3 Struct 5s (Tightest Trail):** Slashed the loser tail to **-0.92 ATR** (a major risk reduction), but **destroyed the runner tail to +1.56 ATR** and collapsed +3 ATR capture to **0.6%**.
- **Conclusion:** Tight trailing stops protect against downside pullbacks by prematurely cutting off the very price fluctuations required to generate massive outlier winners. The two effects symmetrically neutralize each other.

### Q3: Is the previously observed stall-protection lift reproducible on the Bar1 population?
**No.** Under the corrected, audited replay engine, the stall protection configurations (V4D1 and V4D2 MA trails) failed to provide any positive lift on the Bar1-confirmed population:
- **V0 Regime Baseline:** **-10.5 $/trade**.
- **V4D1 MA 1m (Stall protection):** **-15.5 $/trade** (a decay of -5.0 $/trade).
- **V4D2 MA 1m (Stall protection):** **-15.2 $/trade**.
- **Reason:** Once stop-crossing and loop-offset anomalies are resolved, stall protection simply exits trades early, resulting in a lower profit factor and higher drag than holding to the opposite regime flip.

### Q4: Is the prove-it gate additive on Bar1 as it was on raw flips?
**Yes, but marginally.** Adding the 30s/60s prove-it gate to the fixed ladder (V1 -> V2) provided a small positive lift of **+1.9 $/trade** (V1 = -16.4 $/trade vs V2 = -14.5 $/trade). While it successfully prunes some early-underperforming trades, it remains deeply negative overall and cannot lift the strategy into profitability.

### Q5: If Bar1 also fails, is there evidence that the remaining problem is entry quality rather than exit quality?
**Yes, conclusively.** The complete failure of 13 exit architectures across all years, directions, and subgroups confirms that **exit engineering cannot rescue a gross-negative entry signal**.
- **Gross Expectancy:** Even before transaction friction and slippage, the gross return of the baseline V0 regime exit is **-3.0 $/trade** (pooled B). All other versions are gross-negative, ranging from -3.7 to -8.9 $/trade. 
- **The Real Constraint:** If the entry signal possesses no gross edge under a simple holding time or opposite-regime exit, trailing stops or ladders only compress the distribution of outcomes without changing the negative expected value. The entry signal is a statistical coin flip, meaning no exit rules can create a positive martingale. Future research must pivot away from exit heuristics and focus entirely on finding entry signals with genuine predictive continuation quality.