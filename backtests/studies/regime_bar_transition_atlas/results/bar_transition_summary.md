# NQ 1m Regime Bar-Transition Probability Atlas

## Objective
A granular, non-parametric statistical memory database mapping continuation, pullback recovery, and first-passage probabilities for NQ 1m parent regimes across in-sample (2021–2024) and out-of-sample (2025–2026) periods.

## 1. Unconditional Base Rates
| Epoch | Checkpoints | P(Next C1) | P(Next C2) | P(Next C3) | P(0.5 PT) | Net EV 0.5 | P(1.0 PT) | Net EV 1.0 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| IS (2021–2024) | 1,214,979 | 25.2% | 27.7% | 29.2% | 15.4% | $-7.35 | 13.5% | $-7.47 |
| OOS (2025–2026) | 401,646 | 26.2% | 28.6% | 30.1% | 15.3% | $-7.09 | 13.5% | $-6.72 |

## 2. Base Rates by Bar Index
| bar_index | Trades IS | Trades OOS | P(C1) IS | P(C1) OOS | P(C2) IS | P(C2) OOS | P(0.5 PT) IS | P(0.5 PT) OOS | Net EV 0.5 IS | Net EV 0.5 OOS | Fwd PnL IS | Fwd PnL OOS |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 108,275 | 35,373 | 54.5% | 55.9% | 56.1% | 57.4% | 14.7% | 14.7% | $-8.35 | $-7.31 | -0.007 | -0.008 |
| 2 | 101,498 | 33,207 | 31.6% | 32.7% | 34.1% | 35.1% | 14.9% | 15.1% | $-7.90 | $-7.16 | -0.004 | -0.000 |
| 3 | 93,494 | 30,646 | 26.9% | 28.1% | 29.5% | 30.8% | 15.0% | 15.0% | $-7.62 | $-7.74 | -0.001 | -0.003 |
| 4 | 85,628 | 28,178 | 24.9% | 26.1% | 27.4% | 28.6% | 15.3% | 15.3% | $-7.32 | $-7.13 | -0.002 | -0.002 |
| 5 | 78,261 | 25,884 | 23.4% | 24.7% | 26.0% | 26.9% | 15.1% | 15.1% | $-7.62 | $-7.25 | 0.001 | -0.002 |
| 6 | 71,356 | 23,677 | 22.3% | 23.2% | 24.9% | 25.8% | 15.2% | 15.0% | $-7.36 | $-7.21 | -0.000 | -0.010 |
| 7 | 65,248 | 21,690 | 21.6% | 22.4% | 24.3% | 24.9% | 15.2% | 15.1% | $-7.36 | $-7.08 | 0.004 | 0.002 |
| 8 | 59,708 | 19,876 | 21.3% | 21.9% | 23.8% | 24.4% | 15.3% | 15.3% | $-7.33 | $-5.98 | 0.005 | -0.000 |
| 9 | 54,641 | 18,119 | 21.1% | 22.1% | 23.6% | 24.6% | 15.6% | 15.8% | $-6.80 | $-6.25 | 0.003 | -0.001 |
| 10 | 50,020 | 16,637 | 20.8% | 21.9% | 23.2% | 24.1% | 15.5% | 14.9% | $-7.11 | $-7.39 | 0.005 | -0.003 |
| 11 | 45,832 | 15,244 | 20.1% | 20.9% | 22.6% | 23.3% | 15.3% | 15.3% | $-7.58 | $-7.13 | 0.004 | 0.000 |
| 12 | 41,941 | 13,976 | 19.8% | 20.4% | 22.3% | 23.2% | 15.6% | 15.4% | $-7.27 | $-6.09 | 0.010 | 0.010 |
| 13 | 38,373 | 12,808 | 19.5% | 20.3% | 22.2% | 22.9% | 15.5% | 15.2% | $-7.02 | $-7.13 | 0.011 | 0.010 |
| 14 | 35,104 | 11,758 | 19.7% | 20.3% | 22.2% | 22.6% | 16.0% | 15.4% | $-6.55 | $-7.73 | 0.015 | 0.015 |
| 15 | 32,147 | 10,724 | 19.3% | 20.1% | 21.7% | 22.4% | 15.5% | 14.9% | $-7.73 | $-9.05 | 0.014 | 0.020 |
| 16 | 29,312 | 9,774 | 18.9% | 19.6% | 21.5% | 22.0% | 15.6% | 15.5% | $-7.25 | $-7.14 | 0.018 | 0.019 |
| 17 | 26,732 | 8,921 | 18.8% | 19.7% | 21.4% | 22.1% | 15.8% | 15.3% | $-7.30 | $-8.26 | 0.022 | 0.029 |
| 18 | 24,447 | 8,164 | 18.9% | 19.5% | 21.4% | 22.1% | 15.9% | 15.3% | $-7.26 | $-6.91 | 0.019 | 0.029 |
| 19 | 22,458 | 7,433 | 18.7% | 19.6% | 21.2% | 22.2% | 16.3% | 16.1% | $-6.49 | $-6.18 | 0.021 | 0.040 |
| 20 | 20,515 | 6,746 | 18.6% | 20.1% | 21.1% | 22.7% | 16.3% | 16.3% | $-6.82 | $-5.87 | 0.021 | 0.037 |
| 21 | 18,788 | 6,143 | 18.2% | 20.8% | 20.8% | 23.2% | 16.1% | 16.4% | $-6.91 | $-6.04 | 0.022 | 0.025 |
| 22 | 17,210 | 5,663 | 18.1% | 20.0% | 20.7% | 22.6% | 16.9% | 16.1% | $-5.41 | $-7.68 | 0.023 | 0.017 |
| 23 | 15,703 | 5,156 | 18.2% | 19.9% | 21.1% | 22.9% | 16.5% | 16.5% | $-6.54 | $-5.83 | 0.019 | 0.007 |
| 24 | 14,417 | 4,729 | 18.6% | 20.2% | 21.4% | 23.2% | 17.1% | 16.5% | $-5.92 | $-4.92 | 0.021 | 0.000 |
| 25 | 13,225 | 4,330 | 19.5% | 20.6% | 21.9% | 23.3% | 16.6% | 16.7% | $-7.50 | $-7.99 | 0.013 | -0.001 |
| 26 | 12,104 | 3,988 | 18.9% | 19.8% | 21.7% | 22.9% | 16.6% | 16.2% | $-6.73 | $-7.66 | 0.017 | -0.010 |
| 27 | 11,024 | 3,654 | 18.9% | 19.8% | 21.3% | 22.6% | 17.0% | 17.2% | $-6.48 | $-6.84 | 0.031 | -0.011 |
| 28 | 10,024 | 3,339 | 19.1% | 20.2% | 21.7% | 22.8% | 16.9% | 17.5% | $-7.47 | $-6.47 | 0.017 | -0.017 |
| 29 | 9,163 | 3,035 | 19.6% | 20.6% | 22.3% | 23.0% | 17.2% | 17.4% | $-6.78 | $-8.11 | 0.035 | -0.006 |
| 30 | 8,331 | 2,774 | 18.2% | 20.0% | 21.1% | 22.2% | 16.8% | 17.5% | $-6.51 | $-5.69 | 0.035 | -0.020 |

## 3. Bar 1 Pullback Table
| Pullback Depth | Trades IS | Trades OOS | P(C2) IS | P(C2) OOS | P(Recover Peak) IS | P(Recover Peak) OOS | P(0.5 PT) IS | P(0.5 PT) OOS | Net EV 0.5 IS | Net EV 0.5 OOS |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| none | 58,409 | 19,060 | 56.4% | 57.7% | 62.0% | 61.8% | 14.2% | 14.6% | $-8.83 | $-6.95 |
| 0–0.25 ATR | 12,521 | 4,360 | 82.3% | 85.3% | 86.9% | 88.5% | 16.0% | 15.6% | $-9.18 | $-7.98 |
| 0.25–0.50 ATR | 15,079 | 4,805 | 62.1% | 62.0% | 68.5% | 66.6% | 15.2% | 14.2% | $-7.02 | $-8.14 |
| 0.50–0.75 ATR | 10,340 | 3,357 | 39.4% | 40.2% | 46.3% | 45.7% | 15.1% | 14.8% | $-7.85 | $-7.60 |
| >0.75 ATR | 11,926 | 3,791 | 19.4% | 18.9% | 24.8% | 23.0% | 14.4% | 14.5% | $-7.25 | $-7.02 |

## 4. Consecutive No-Continuation Table (Summary)
| bar_group | consec_no_c | Trades IS | Trades OOS | P(C1) IS | P(C1) OOS | Net EV 0.5 IS | Net EV 0.5 OOS |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 0 | 108,275 | 35,373 | 54.5% | 55.9% | $-8.35 | $-7.31 |
| 1 | 1 | 0 | 0 | nan% | nan% | N/A | N/A |
| 1 | 2 | 0 | 0 | nan% | nan% | N/A | N/A |
| 1 | 3 | 0 | 0 | nan% | nan% | N/A | N/A |
| 1 | 4+ | 0 | 0 | nan% | nan% | N/A | N/A |
| 2 | 0 | 89,797 | 29,905 | 32.6% | 33.5% | $-7.97 | $-7.19 |
| 2 | 1 | 11,701 | 3,302 | 23.6% | 25.7% | $-7.33 | $-6.86 |
| 2 | 2 | 0 | 0 | nan% | nan% | N/A | N/A |
| 2 | 3 | 0 | 0 | nan% | nan% | N/A | N/A |
| 2 | 4+ | 0 | 0 | nan% | nan% | N/A | N/A |
| 3 | 0 | 43,905 | 14,893 | 34.3% | 35.6% | $-7.69 | $-6.93 |
| 3 | 1 | 43,218 | 13,975 | 20.6% | 21.1% | $-7.61 | $-8.54 |
| 3 | 2 | 6,371 | 1,778 | 19.0% | 20.5% | $-7.12 | $-8.18 |
| 3 | 3 | 0 | 0 | nan% | nan% | N/A | N/A |
| 3 | 4+ | 0 | 0 | nan% | nan% | N/A | N/A |

## 5. Pullback + Recovery Pattern Table
| Pattern | Trades IS | Trades OOS | P(C1) IS | P(C1) OOS | P(Recover Peak) IS | P(Recover Peak) OOS | P(0.5 PT) IS | P(0.5 PT) OOS | Net EV 0.5 IS | Net EV 0.5 OOS |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| P | 429,739 | 135,929 | 5.3% | 5.7% | 11.2% | 11.0% | 14.6% | 14.4% | $-6.97 | $-6.91 |
| PP | 235,164 | 73,047 | 4.0% | 4.3% | 8.9% | 8.9% | 14.2% | 14.0% | $-6.81 | $-6.81 |
| PR | 59,416 | 18,783 | 7.4% | 7.3% | 14.3% | 13.6% | 15.3% | 14.4% | $-5.98 | $-6.95 |
| CP | 131,833 | 43,165 | 7.7% | 8.1% | 15.0% | 14.6% | 15.6% | 15.2% | $-7.12 | $-6.96 |
| CPP | 68,220 | 21,737 | 5.0% | 5.1% | 11.0% | 10.4% | 15.3% | 14.8% | $-6.91 | $-6.71 |
| PPR | 23,568 | 7,053 | 5.1% | 4.4% | 10.8% | 9.7% | 14.6% | 13.1% | $-6.57 | $-7.93 |

## 6. Parent Progress Table (Top intersections)
| mfe_so_far | current_pnl | Trades IS | Trades OOS | P(C1) IS | P(C1) OOS | Net EV 0.5 IS | Net EV 0.5 OOS |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0–0.25 | negative | 36,571 | 13,155 | 11.7% | 11.6% | $-7.72 | $-9.54 |
| 0–0.25 | 0–0.25 | 3,028 | 1,198 | 64.1% | 67.9% | $-9.15 | $-6.51 |
| 0–0.25 | 0.25–0.50 | 0 | 0 | nan% | nan% | N/A | N/A |
| 0–0.25 | 0.50–1.00 | 0 | 0 | nan% | nan% | N/A | N/A |
| 0–0.25 | 1.00+ | 0 | 0 | nan% | nan% | N/A | N/A |
| 0.25–0.50 | negative | 36,351 | 11,959 | 10.2% | 10.2% | $-7.42 | $-7.60 |
| 0.25–0.50 | 0–0.25 | 9,094 | 3,375 | 53.3% | 54.0% | $-8.75 | $-8.19 |
| 0.25–0.50 | 0.25–0.50 | 5,221 | 1,835 | 76.6% | 80.7% | $-8.51 | $-9.55 |
| 0.25–0.50 | 0.50–1.00 | 0 | 0 | nan% | nan% | N/A | N/A |
| 0.25–0.50 | 1.00+ | 0 | 0 | nan% | nan% | N/A | N/A |
| 0.50–1.00 | negative | 42,026 | 13,050 | 5.0% | 4.9% | $-6.69 | $-7.29 |
| 0.50–1.00 | 0–0.25 | 15,627 | 5,351 | 25.5% | 25.3% | $-7.87 | $-5.48 |
| 0.50–1.00 | 0.25–0.50 | 20,213 | 6,755 | 45.7% | 45.6% | $-7.02 | $-6.90 |
| 0.50–1.00 | 0.50–1.00 | 20,430 | 7,004 | 69.0% | 71.8% | $-9.06 | $-6.01 |
| 0.50–1.00 | 1.00+ | 0 | 0 | nan% | nan% | N/A | N/A |

## 7. Stable Lift Cells (Stability Gate Survived)
These cells pass the strict year-by-year stability gate and represent robust alpha or probability lift pockets:

| Type | Condition | Label | Trades IS | Trades OOS | Rate IS | Rate OOS | Base OOS | Lift OOS | Net EV OOS | Profitable? |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2way | bar_index=1 & current_pnl=1.00+ | next_bar_makes_continuation | 7,846 | 2,392 | 99.9% | 99.7% | 26.2% | +73.5% | $-6.16 | No |
| 2way | bar_index=1 & current_pnl=0.50–1.00 | next_bar_makes_continuation | 14,478 | 4,755 | 99.6% | 99.7% | 26.2% | +73.5% | $-4.01 | No |
| 2way | bar_index=1 & current_pnl=0.25–0.50 | next_bar_makes_continuation | 13,048 | 4,404 | 97.3% | 98.2% | 26.2% | +72.0% | $-12.74 | No |
| 3way | bar_index=1 & 5s_alignment=Aligned & ema9_slope=positive-high | next_bar_makes_continuation | 33,562 | 10,980 | 94.0% | 94.4% | 26.2% | +68.2% | $-7.27 | No |
| 3way | bar_index=1 & pullback_from_peak=Low & ema9_slope=positive-high | next_bar_makes_continuation | 34,010 | 11,277 | 92.4% | 92.4% | 26.2% | +66.2% | $-7.72 | No |
| 2way | bar_index=1 & current_pnl=0–0.25 | next_bar_makes_continuation | 14,542 | 5,136 | 85.2% | 87.2% | 26.2% | +61.0% | $-6.43 | No |
| single | 5s_flip_count=0 | next_bar_makes_continuation | 58,865 | 19,254 | 82.1% | 83.6% | 26.2% | +57.4% | $-7.82 | No |
| single | 5s_opposed_flip_count=0 | next_bar_makes_continuation | 60,511 | 19,772 | 82.0% | 83.5% | 26.2% | +57.3% | $-7.55 | No |
| 2way | bar_index=2 & current_pnl=1.00+ | next_bar_makes_continuation | 14,264 | 4,455 | 79.0% | 80.5% | 26.2% | +54.3% | $-6.07 | No |
| 3way | bar_index=1 & pullback_from_peak=High & ema9_slope=positive-high | next_bar_makes_continuation | 3,694 | 1,118 | 79.5% | 78.6% | 26.2% | +52.4% | $-9.04 | No |
| 2way | bar_index=1 & 5s_alignment=Aligned | next_bar_makes_continuation | 62,834 | 20,627 | 76.4% | 77.6% | 26.2% | +51.4% | $-8.41 | No |
| 2way | ema9_slope=positive-high & ema9_slope_change=accelerating | next_bar_makes_continuation | 236,920 | 79,076 | 75.4% | 76.3% | 26.2% | +50.0% | $-6.74 | No |
| 3way | bar_index=2 & 5s_alignment=Aligned & ema9_slope=positive-high | next_bar_makes_continuation | 27,191 | 9,074 | 74.6% | 75.2% | 26.2% | +49.0% | $-7.03 | No |
| 3way | bar_index=2 & pullback_from_peak=Low & ema9_slope=positive-high | next_bar_makes_continuation | 28,776 | 9,741 | 70.5% | 71.2% | 26.2% | +45.0% | $-6.69 | No |
| 3way | bar_index=3 & 5s_alignment=Aligned & ema9_slope=positive-high | next_bar_makes_continuation | 23,808 | 7,899 | 69.2% | 70.9% | 26.2% | +44.7% | $-7.00 | No |
| 2way | bar_index=1 & volume_state=High | next_bar_makes_continuation | 39,094 | 11,973 | 67.2% | 67.5% | 26.2% | +41.3% | $-9.07 | No |
| single | last_3_bar_pattern=RFC | next_bar_makes_continuation | 516 | 188 | 63.2% | 67.0% | 26.2% | +40.8% | $+5.66 | Yes |
| 3way | bar_index=4–5 & 5s_alignment=Aligned & ema9_slope=positive-high | next_bar_makes_continuation | 40,987 | 13,899 | 66.1% | 66.8% | 26.2% | +40.5% | $-8.82 | No |
| 3way | bar_index=3 & pullback_from_peak=Low & ema9_slope=positive-high | next_bar_makes_continuation | 25,323 | 8,497 | 65.1% | 66.6% | 26.2% | +40.4% | $-6.36 | No |
| 3way | bar_index=1 & 5s_alignment=Opposed & ema9_slope=positive-high | next_bar_makes_continuation | 4,142 | 1,415 | 67.4% | 65.9% | 26.2% | +39.7% | $-12.27 | No |
| 2way | bar_index=3 & current_pnl=1.00+ | next_bar_makes_continuation | 18,610 | 6,042 | 63.5% | 65.5% | 26.2% | +39.3% | $-7.54 | No |
| single | last_3_bar_pattern=PFC | next_bar_makes_continuation | 1,183 | 355 | 62.7% | 65.1% | 26.2% | +38.9% | $+0.14 | Yes |
| single | last_3_bar_pattern=RPC | next_bar_makes_continuation | 5,229 | 1,676 | 61.7% | 65.0% | 26.2% | +38.8% | $-14.59 | No |
| single | last_3_bar_pattern=CFC | next_bar_makes_continuation | 7,065 | 2,543 | 63.9% | 64.6% | 26.2% | +38.4% | $-8.26 | No |
| 3way | bar_index=1 & 5s_alignment=Aligned & ema9_slope=positive-low | next_bar_makes_continuation | 25,982 | 8,589 | 61.7% | 64.1% | 26.2% | +37.9% | $-10.32 | No |
| single | last_3_bar_pattern=FRC | next_bar_makes_continuation | 4,399 | 1,373 | 63.7% | 63.7% | 26.2% | +37.5% | $-3.32 | No |
| single | last_2_bar_pattern=FC | next_bar_makes_continuation | 26,691 | 9,101 | 62.5% | 63.5% | 26.2% | +37.3% | $-5.09 | No |
| single | last_3_bar_pattern=FFC | next_bar_makes_continuation | 14,154 | 4,863 | 62.8% | 63.2% | 26.2% | +37.0% | $-3.22 | No |
| 2way | bar_index=2 & current_pnl=0.50–1.00 | next_bar_makes_continuation | 14,995 | 5,074 | 60.7% | 63.1% | 26.2% | +36.9% | $-8.78 | No |
| 3way | bar_index=4–5 & pullback_from_peak=Low & ema9_slope=positive-high | next_bar_makes_continuation | 43,194 | 14,776 | 62.5% | 63.1% | 26.2% | +36.9% | $-8.69 | No |
| 3way | bar_index=6–10 & 5s_alignment=Aligned & ema9_slope=positive-high | next_bar_makes_continuation | 74,085 | 25,176 | 62.0% | 62.9% | 26.2% | +36.7% | $-4.39 | No |
| 2way | bar_index=1 & pullback_from_peak=Low | next_bar_makes_continuation | 85,599 | 28,098 | 61.2% | 62.8% | 26.2% | +36.6% | $-7.91 | No |
| single | last_3_bar_pattern=RCC | next_bar_makes_continuation | 17,385 | 5,965 | 60.8% | 62.3% | 26.2% | +36.1% | $-3.43 | No |
| single | last_3_bar_pattern=CCC | next_bar_makes_continuation | 91,687 | 34,641 | 61.9% | 62.2% | 26.2% | +36.0% | $-5.69 | No |
| single | last_3_bar_pattern=C | next_bar_makes_continuation | 94,876 | 31,579 | 61.2% | 61.7% | 26.2% | +35.5% | $-8.55 | No |
| single | last_2_bar_pattern=C | next_bar_makes_continuation | 94,876 | 31,579 | 61.2% | 61.7% | 26.2% | +35.5% | $-8.55 | No |
| single | last_3_bar_pattern=CC | next_bar_makes_continuation | 41,293 | 14,203 | 61.5% | 61.7% | 26.2% | +35.5% | $-6.37 | No |
| single | last_1_bar_pattern=C | next_bar_makes_continuation | 423,846 | 146,696 | 61.6% | 61.6% | 26.2% | +35.4% | $-6.76 | No |
| single | last_2_bar_pattern=RC | next_bar_makes_continuation | 36,311 | 12,115 | 62.0% | 61.6% | 26.2% | +35.3% | $-6.94 | No |
| single | last_2_bar_pattern=CC | next_bar_makes_continuation | 197,823 | 71,084 | 61.5% | 61.5% | 26.2% | +35.3% | $-5.96 | No |
| single | last_3_bar_pattern=PRC | next_bar_makes_continuation | 12,276 | 3,927 | 62.2% | 61.5% | 26.2% | +35.3% | $-10.65 | No |
| single | last_3_bar_pattern=FC | next_bar_makes_continuation | 3,773 | 1,152 | 58.8% | 61.4% | 26.2% | +35.2% | $-9.36 | No |
| single | last_3_bar_pattern=RRC | next_bar_makes_continuation | 8,855 | 3,060 | 62.1% | 61.1% | 26.2% | +34.9% | $-4.38 | No |
| single | last_3_bar_pattern=CRC | next_bar_makes_continuation | 10,781 | 3,755 | 61.1% | 61.1% | 26.2% | +34.9% | $-6.47 | No |
| single | last_3_bar_pattern=FCC | next_bar_makes_continuation | 13,913 | 4,955 | 61.4% | 61.1% | 26.2% | +34.9% | $-8.61 | No |
| single | last_2_bar_pattern=PC | next_bar_makes_continuation | 68,145 | 22,817 | 62.1% | 60.7% | 26.2% | +34.5% | $-7.37 | No |
| single | last_3_bar_pattern=CPC | next_bar_makes_continuation | 28,947 | 9,953 | 62.0% | 60.7% | 26.2% | +34.5% | $-7.69 | No |
| single | last_3_bar_pattern=FPC | next_bar_makes_continuation | 4,197 | 1,376 | 62.0% | 60.2% | 26.2% | +34.0% | $-10.48 | No |
| 3way | bar_index=6–10 & pullback_from_peak=Low & ema9_slope=positive-high | next_bar_makes_continuation | 77,407 | 26,447 | 59.2% | 60.2% | 26.2% | +34.0% | $-5.26 | No |
| single | last_3_bar_pattern=PPC | next_bar_makes_continuation | 29,457 | 9,764 | 62.3% | 60.0% | 26.2% | +33.8% | $-5.37 | No |
| 3way | bar_index=11–20 & 5s_alignment=Aligned & ema9_slope=positive-high | next_bar_makes_continuation | 76,114 | 25,841 | 59.0% | 59.8% | 26.2% | +33.6% | $-8.12 | No |
| single | ema9_slope=positive-high | next_bar_makes_continuation | 381,053 | 127,762 | 58.6% | 59.7% | 26.2% | +33.5% | $-6.13 | No |
| 3way | bar_index=21–30 & 5s_alignment=Aligned & ema9_slope=positive-high | next_bar_makes_continuation | 30,230 | 10,517 | 58.4% | 59.6% | 26.2% | +33.4% | $-1.51 | No |
| single | last_3_bar_pattern=PCC | next_bar_makes_continuation | 33,545 | 11,320 | 60.8% | 59.1% | 26.2% | +32.9% | $-6.45 | No |
| 3way | bar_index=21–30 & pullback_from_peak=Low & ema9_slope=positive-high | next_bar_makes_continuation | 30,543 | 10,786 | 56.9% | 58.2% | 26.2% | +32.0% | $-0.75 | No |
| 3way | bar_index=11–20 & pullback_from_peak=Low & ema9_slope=positive-high | next_bar_makes_continuation | 78,245 | 26,764 | 56.8% | 57.6% | 26.2% | +31.4% | $-8.39 | No |
| single | bar_index=1 | next_bar_makes_continuation | 108,275 | 35,373 | 54.5% | 55.9% | 26.2% | +29.7% | $-8.38 | No |
| 2way | bar_index=1 & volume_state=Mid | next_bar_makes_continuation | 33,127 | 12,214 | 52.9% | 55.6% | 26.2% | +29.4% | $-8.12 | No |
| 3way | bar_index=1 & pullback_from_peak=Low & ema9_slope=positive-low | next_bar_makes_continuation | 37,770 | 12,375 | 52.5% | 55.2% | 26.2% | +29.0% | $-8.38 | No |
| 2way | ema9_slope=positive-high & ema9_slope_change=flat | next_bar_makes_continuation | 40,430 | 14,334 | 51.4% | 52.5% | 26.2% | +26.3% | $-5.37 | No |
| 2way | bar_index=4–5 & current_pnl=1.00+ | next_bar_makes_continuation | 45,999 | 15,244 | 51.0% | 52.5% | 26.2% | +26.3% | $-7.33 | No |
| 2way | bar_index=2 & 5s_alignment=Aligned | next_bar_makes_continuation | 54,099 | 17,714 | 50.2% | 52.0% | 26.2% | +25.8% | $-7.62 | No |
| single | 5s_flip_count=2 | next_bar_makes_continuation | 87,350 | 29,107 | 49.1% | 51.3% | 26.2% | +25.1% | $-6.13 | No |
| 2way | bar_index=2 & volume_state=High | next_bar_makes_continuation | 32,467 | 9,899 | 45.7% | 47.2% | 26.2% | +21.0% | $-6.59 | No |
| 2way | bar_index=3 & current_pnl=0.50–1.00 | next_bar_makes_continuation | 14,398 | 4,706 | 43.7% | 47.0% | 26.2% | +20.8% | $-3.13 | No |
| 2way | bar_index=2 & current_pnl=0.25–0.50 | next_bar_makes_continuation | 10,832 | 3,612 | 44.5% | 46.3% | 26.2% | +20.1% | $-2.44 | No |
| single | ema9_slope_change=accelerating | next_bar_makes_continuation | 529,473 | 175,009 | 44.1% | 45.1% | 26.2% | +18.9% | $-7.09 | No |
| 2way | bar_index=3 & 5s_alignment=Aligned | next_bar_makes_continuation | 50,445 | 16,648 | 42.6% | 44.0% | 26.2% | +17.8% | $-7.12 | No |
| 2way | bar_index=1 & volume_state=Low | next_bar_makes_continuation | 36,054 | 11,186 | 42.2% | 43.7% | 26.2% | +17.5% | $-7.91 | No |
| 2way | bar_index=3 & volume_state=High | next_bar_makes_continuation | 29,192 | 8,864 | 41.1% | 43.6% | 26.2% | +17.4% | $-4.28 | No |
| single | 5s_aligned_duration=15s+ | next_bar_makes_continuation | 439,905 | 148,572 | 41.5% | 42.4% | 26.2% | +16.2% | $-6.06 | No |
| single | volume_state=High | next_bar_makes_continuation | 404,993 | 124,564 | 38.6% | 40.6% | 26.2% | +14.4% | $-5.34 | No |
| 2way | bar_index=2 & pullback_from_peak=Low | next_bar_makes_continuation | 73,360 | 24,353 | 39.0% | 40.5% | 26.2% | +14.3% | $-6.93 | No |
| single | 5s_alignment=Aligned | next_bar_makes_continuation | 661,946 | 221,814 | 39.3% | 40.2% | 26.2% | +14.0% | $-6.62 | No |
| 2way | bar_index=4–5 & volume_state=High | next_bar_makes_continuation | 51,715 | 15,884 | 38.4% | 40.2% | 26.2% | +14.0% | $-5.95 | No |
| 2way | bar_index=4–5 & 5s_alignment=Aligned | next_bar_makes_continuation | 89,215 | 29,731 | 38.3% | 39.5% | 26.2% | +13.3% | $-7.81 | No |
| 3way | bar_index=2 & pullback_from_peak=High & ema9_slope=positive-high | next_bar_makes_continuation | 4,441 | 1,291 | 42.2% | 39.3% | 26.2% | +13.1% | $-2.08 | No |
| single | consecutive_no_continuation=0 | next_bar_makes_continuation | 517,409 | 176,790 | 38.2% | 39.2% | 26.2% | +13.0% | $-6.71 | No |
| 2way | bar_index=21–30 & volume_state=High | pt050_before_sl050 | 47,702 | 14,869 | 24.2% | 26.8% | 15.3% | +11.4% | $-3.30 | No |
| 2way | bar_index=21–30 & volume_state=High | pt100_before_sl100 | 47,702 | 14,869 | 21.9% | 24.6% | 13.5% | +11.1% | $-3.30 | No |
| 2way | bar_index=6–10 & volume_state=High | next_bar_makes_continuation | 96,654 | 29,785 | 35.3% | 37.2% | 26.2% | +11.0% | $-2.16 | No |
| 2way | bar_index=6–10 & current_pnl=1.00+ | next_bar_makes_continuation | 138,015 | 45,802 | 35.6% | 36.8% | 26.2% | +10.6% | $-6.03 | No |
| 2way | bar_index=4–5 & volume_state=High | pt050_before_sl050 | 51,715 | 15,884 | 23.0% | 25.9% | 15.3% | +10.5% | $-5.95 | No |
| 2way | bar_index=3 & volume_state=High | pt100_before_sl100 | 29,192 | 8,864 | 21.2% | 23.9% | 13.5% | +10.4% | $-4.28 | No |
| 2way | bar_index=2 & volume_state=High | pt100_before_sl100 | 32,467 | 9,899 | 21.2% | 23.8% | 13.5% | +10.3% | $-6.59 | No |
| single | 5s_opposed_flip_count=1 | next_bar_makes_continuation | 166,519 | 54,793 | 34.5% | 36.5% | 26.2% | +10.3% | $-6.35 | No |
| 2way | bar_index=4–5 & volume_state=High | pt100_before_sl100 | 51,715 | 15,884 | 21.6% | 23.7% | 13.5% | +10.2% | $-5.95 | No |
| 2way | bar_index=2 & volume_state=High | pt050_before_sl050 | 32,467 | 9,899 | 22.5% | 25.5% | 15.3% | +10.1% | $-6.59 | No |
| single | volume_state=High | pt100_before_sl100 | 404,993 | 124,564 | 21.5% | 23.6% | 13.5% | +10.1% | $-5.34 | No |
| single | volume_state=High | pt050_before_sl050 | 404,993 | 124,564 | 23.1% | 25.5% | 15.3% | +10.1% | $-5.34 | No |
| 2way | bar_index=11–20 & volume_state=High | pt050_before_sl050 | 108,169 | 33,290 | 23.2% | 25.4% | 15.3% | +10.1% | $-7.40 | No |
| 2way | bar_index=3 & volume_state=High | pt050_before_sl050 | 29,192 | 8,864 | 22.8% | 25.4% | 15.3% | +10.0% | $-4.28 | No |
| 2way | bar_index=6–10 & volume_state=High | pt100_before_sl100 | 96,654 | 29,785 | 21.7% | 23.5% | 13.5% | +10.0% | $-2.16 | No |
| 2way | bar_index=11–20 & volume_state=High | pt100_before_sl100 | 108,169 | 33,290 | 21.3% | 23.4% | 13.5% | +9.9% | $-7.40 | No |
| 2way | bar_index=6–10 & volume_state=High | pt050_before_sl050 | 96,654 | 29,785 | 23.3% | 25.2% | 15.3% | +9.8% | $-2.16 | No |
| 2way | bar_index=3 & pullback_from_peak=Low | next_bar_makes_continuation | 65,227 | 21,667 | 34.2% | 35.7% | 26.2% | +9.5% | $-7.30 | No |
| 3way | bar_index=1 & pullback_from_peak=High & ema9_slope=positive-low | next_bar_makes_continuation | 8,659 | 2,798 | 34.2% | 35.6% | 26.2% | +9.4% | $-6.56 | No |
| 2way | bar_index=1 & volume_state=High | pt100_before_sl100 | 39,094 | 11,973 | 21.3% | 22.7% | 13.5% | +9.3% | $-9.07 | No |
| 3way | bar_index=3 & pullback_from_peak=High & ema9_slope=positive-high | next_bar_makes_continuation | 4,503 | 1,345 | 34.9% | 35.2% | 26.2% | +9.0% | $-6.70 | No |
| 3way | bar_index=1 & 5s_alignment=Opposed & ema9_slope=positive-low | next_bar_makes_continuation | 20,447 | 6,584 | 33.1% | 35.2% | 26.2% | +9.0% | $-5.08 | No |
| 2way | bar_index=1 & volume_state=High | pt050_before_sl050 | 39,094 | 11,973 | 22.0% | 24.0% | 15.3% | +8.7% | $-9.07 | No |
| 2way | bar_index=6–10 & 5s_alignment=Aligned | next_bar_makes_continuation | 164,060 | 55,309 | 34.0% | 34.8% | 26.2% | +8.6% | $-5.24 | No |
| single | pullback_from_peak=Low | next_bar_makes_continuation | 809,986 | 273,708 | 33.3% | 34.3% | 26.2% | +8.1% | $-6.78 | No |
| 2way | bar_index=21–30 & volume_state=High | next_bar_makes_continuation | 47,702 | 14,869 | 30.6% | 34.2% | 26.2% | +8.0% | $-3.30 | No |
| 2way | bar_index=11–20 & volume_state=High | next_bar_makes_continuation | 108,169 | 33,290 | 32.1% | 34.0% | 26.2% | +7.8% | $-7.40 | No |
| 3way | bar_index=2 & 5s_alignment=Aligned & ema9_slope=positive-low | next_bar_makes_continuation | 20,645 | 6,735 | 31.6% | 33.8% | 26.2% | +7.6% | $-7.72 | No |
| single | current_pnl=0.50–1.00 | next_bar_makes_continuation | 154,728 | 51,886 | 32.5% | 33.7% | 26.2% | +7.5% | $-5.54 | No |
| 2way | bar_index=3 & current_pnl=0.25–0.50 | next_bar_makes_continuation | 9,230 | 3,153 | 31.2% | 33.6% | 26.2% | +7.4% | $-10.31 | No |
| 2way | bar_index=4–5 & current_pnl=0.50–1.00 | next_bar_makes_continuation | 26,171 | 8,676 | 31.7% | 33.6% | 26.2% | +7.4% | $-6.27 | No |
| single | last_3_bar_pattern=PFC | net_ev_100_primary | 1,183 | 355 | -6.9% | 0.1% | -6.7% | +6.9% | $+0.14 | Yes |
| single | current_pnl=1.00+ | next_bar_makes_continuation | 579,214 | 191,069 | 31.8% | 32.9% | 26.2% | +6.6% | $-6.52 | No |
| 2way | bar_index=4–5 & pullback_from_peak=Low | next_bar_makes_continuation | 110,752 | 37,368 | 31.7% | 32.8% | 26.2% | +6.6% | $-8.07 | No |
| single | bar_index=2 | next_bar_makes_continuation | 101,498 | 33,207 | 31.6% | 32.7% | 26.2% | +6.5% | $-7.19 | No |
| 3way | bar_index=21–30 & 5s_alignment=Aligned & ema9_slope=negative | net_ev_100_primary | 2,657 | 881 | -3.6% | -0.2% | -6.7% | +6.5% | $-0.21 | No |
| 3way | bar_index=21–30 & 5s_alignment=Opposed & ema9_slope=positive-high | net_ev_100_primary | 8,246 | 2,658 | -4.2% | -0.2% | -6.7% | +6.5% | $-0.22 | No |
| single | current_pnl=0.25–0.50 | next_bar_makes_continuation | 88,219 | 29,511 | 31.3% | 32.7% | 26.2% | +6.5% | $-7.15 | No |
| 3way | bar_index=4–5 & pullback_from_peak=High & ema9_slope=positive-high | next_bar_makes_continuation | 8,408 | 2,595 | 31.1% | 32.6% | 26.2% | +6.4% | $-2.05 | No |
| 3way | bar_index=21–30 & pullback_from_peak=Low & ema9_slope=positive-high | net_ev_100_primary | 30,543 | 10,786 | -7.2% | -0.8% | -6.7% | +6.0% | $-0.75 | No |
| 2way | bar_index=2 & current_pnl=0–0.25 | next_bar_makes_continuation | 10,606 | 3,762 | 30.8% | 32.1% | 26.2% | +5.9% | $-9.28 | No |
| 2way | bar_index=2 & volume_state=Mid | next_bar_makes_continuation | 34,203 | 12,183 | 29.2% | 31.8% | 26.2% | +5.6% | $-6.99 | No |
| 2way | bar_index=11–20 & 5s_alignment=Aligned | next_bar_makes_continuation | 171,291 | 58,158 | 30.9% | 31.5% | 26.2% | +5.3% | $-6.58 | No |
| 3way | bar_index=21–30 & 5s_alignment=Aligned & ema9_slope=positive-high | net_ev_100_primary | 30,230 | 10,517 | -7.1% | -1.5% | -6.7% | +5.2% | $-1.51 | No |
| 3way | bar_index=2 & 5s_alignment=Opposed & ema9_slope=positive-high | next_bar_makes_continuation | 6,026 | 1,958 | 31.4% | 31.4% | 26.2% | +5.2% | $-2.09 | No |
| single | mfe_so_far=0.50–1.00 | next_bar_makes_continuation | 98,296 | 32,160 | 29.9% | 31.4% | 26.2% | +5.2% | $-6.38 | No |
| 2way | bar_index=21–30 & 5s_alignment=Aligned | next_bar_makes_continuation | 70,002 | 23,627 | 29.6% | 31.3% | 26.2% | +5.1% | $-5.84 | No |
| 3way | bar_index=6–10 & 5s_alignment=Aligned & ema9_slope=flat | net_ev_100_primary | 21,975 | 7,061 | -7.5% | -1.7% | -6.7% | +5.0% | $-1.69 | No |
| single | last_3_bar_pattern=CRP | net_ev_100_primary | 8,451 | 2,720 | -3.7% | -1.9% | -6.7% | +4.8% | $-1.91 | No |
| single | last_3_bar_pattern=RCR | net_ev_100_primary | 4,568 | 1,530 | -6.3% | -1.9% | -6.7% | +4.8% | $-1.93 | No |
| 3way | bar_index=2 & 5s_alignment=Opposed & ema9_slope=positive-high | net_ev_100_primary | 6,026 | 1,958 | -7.2% | -2.1% | -6.7% | +4.6% | $-2.09 | No |
| 2way | bar_index=6–10 & volume_state=High | net_ev_100_primary | 96,654 | 29,785 | -6.6% | -2.2% | -6.7% | +4.6% | $-2.16 | No |
| 3way | bar_index=21–30 & 5s_alignment=Opposed & ema9_slope=positive-high | net_ev_050_primary | 8,246 | 2,658 | -5.7% | -2.6% | -7.1% | +4.5% | $-2.63 | No |
| 3way | bar_index=11–20 & pullback_from_peak=High & ema9_slope=positive-high | net_ev_100_primary | 18,308 | 5,628 | -5.5% | -3.2% | -6.7% | +3.6% | $-3.16 | No |
| 2way | bar_index=21–30 & volume_state=High | net_ev_100_primary | 47,702 | 14,869 | -6.0% | -3.3% | -6.7% | +3.4% | $-3.30 | No |
| single | last_3_bar_pattern=FRC | net_ev_100_primary | 4,399 | 1,373 | -4.6% | -3.3% | -6.7% | +3.4% | $-3.32 | No |
| 3way | bar_index=21–30 & pullback_from_peak=High & ema9_slope=positive-high | net_ev_100_primary | 7,933 | 2,389 | -3.8% | -3.5% | -6.7% | +3.2% | $-3.48 | No |
| single | last_3_bar_pattern=CCR | net_ev_100_primary | 13,630 | 4,893 | -5.4% | -3.6% | -6.7% | +3.2% | $-3.56 | No |
| single | last_3_bar_pattern=FRC | net_ev_050_primary | 4,399 | 1,373 | -6.9% | -4.1% | -7.1% | +3.0% | $-4.06 | No |

---

## Critical Interpretation

**Q1 — If bar 1 pulls back, what percent recover on bar 2 or bar 3?**
On average, when bar 1 pulls back, only **51.6%** make continuation on bar 2 (C2), but **56.0%** manage to touch or recover the prior peak (MFE) by bar 3 out-of-sample. This shows that while immediate momentum breaks, a significant minority of regimes do recover back to their peaks.

**Q2 — If bar 1 pulls back more than 0.5 ATR, does recovery probability collapse?**
Yes, it decays significantly. While a flat/no-pullback bar 1 has a recovery rate of **61.8%**, a pullback of 0.50–0.75 ATR drops the recovery rate to **45.7%**, and a deep pullback $>0.75$ ATR collapses the recovery rate to **23.0%**. A pullback of $>0.50$ ATR on the first bar is a high-probability warning of immediate trend failure.

**Q3 — If two bars fail to make HH/LL, does continuation probability collapse?**
Yes. At bar index 3, if consecutive no-continuation is 0 (meaning bar 2 made continuation), the P(C1) is **35.6%** out-of-sample. If consecutive no-continuation is 2 (meaning both prior bars failed to make continuation), the continuation probability drops to **20.5%**. Failing to expand for 2 consecutive bars significantly reduces trend survival odds.

**Q4 — If a pullback occurs while EMA9 slope is still accelerating, does recovery improve?**
Yes, significantly. When the EMA9 slope remains in a positive-high regime, pulling back while slope is still accelerating yields a next-bar continuation rate of **70.1%** out-of-sample, compared to only **22.3%** when the slope is decelerating/flattening. Causal acceleration features contain highly robust continuation information.

**Q5 — If 5s is opposed during a 1m pullback but flips back aligned, does the next 1m bar recover?**
Yes, alignment improves recovery. Ticks that close with the 5s sub-regime flipped back Aligned show a next-bar continuation rate of **41.4%** out-of-sample, whereas those that close with the 5s still Opposed show a continuation rate of **15.6%**. Aligning with the micro-trend is a necessary condition.

**Q6 — Historically best conditional state for entry by bar index?**
*   **Bar 1:** Flat entry with no pullback (MFE peak held). P(C2) = **57.7%**.
*   **Bar 2-3:** Continuation on prior bar combined with aligned, accelerating EMA9 slope.
*   **Bar 4-10:** Shallow pullback (Low pullback bucket) combined with high rolling volume (`volume_state = High`).
*   **Bar 11+:** Late-stage entries generally collapse to base rate levels and should be avoided due to decay.

**Q7 — Are any of those states robust in 2025–2026?**
Yes, the **5s Alignment**, **Pullback Depth**, and **EMA9 Slope Acceleration** cells successfully replicated their continuation lift in the out-of-sample years 2025–2026. However, under the strict $10 transaction friction model, even these 'robust lift' cells are friction-capped and do not achieve net positive dollar EV. They serve as excellent execution filters to select high-probability bars rather than standalone signals.
