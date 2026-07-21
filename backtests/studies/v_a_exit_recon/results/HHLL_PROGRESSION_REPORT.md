# V_A HH/LL Progression Exit Study v1

Tests 3 mechanical exit families using structural HH/LL progression at 1s/5s/30s granularities. All replayed from the existing trade tape — no new NT runs.

- Population: 7,659 unfiltered V_A trades (NQ 2024+2025+2026 RTH)
- Tape: 6,203,529 per-1s-bar rows
- Cost: $5 commission + $5 tick = $10 RT
- Each rule re-uses the SAME entry. Only exit logic changes.

## Rule scoreboard — full per-year stats

| Rule | %fired | Med Hold s | 2024 mean / total / WR | 2025 mean / total / WR | 2026 mean / total / WR | All mean | All total | All PF | %base-W cut | %base-L improved | MFE capt | Top-1% share |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| BASELINE_regime | 0.0% | 631 | $7.51 / $24,965 / 35.4% | $17.67 / $58,465 / 34.1% | $-18.74 / $-18,400 / 35.1% | $8.30 | $63,605 | 1.04 | 0.0% | 0.0% | -3.41 | 506.6% |
| REF_E_ltf_deterioration_T600 | 8.1% | 600 | $8.45 / $28,105 / 38.0% | $19.75 / $65,350 / 36.8% | $-18.24 / $-17,910 / 37.2% | $9.67 | $74,075 | 1.04 | 7.0% | 4.4% | -3.40 | 430.2% |
| A_stall_1s_5 | 76.7% | 91 | $-12.81 / $-42,590 / 75.0% | $-6.87 / $-22,745 / 75.2% | $-9.47 / $-9,295 / 76.4% | $-9.95 | $-76,205 | 0.91 | 80.3% | 64.2% | -2.89 | -77.2% |
| A_stall_1s_10 | 76.4% | 93 | $-12.88 / $-42,835 / 72.5% | $-6.33 / $-20,930 / 73.6% | $-6.31 / $-6,200 / 74.0% | $-9.36 | $-71,660 | 0.92 | 79.4% | 63.6% | -2.92 | -100.2% |
| A_stall_1s_20 | 75.3% | 121 | $-12.21 / $-40,595 / 68.0% | $-2.94 / $-9,715 / 69.7% | $-10.41 / $-10,220 / 68.9% | $-8.12 | $-62,185 | 0.93 | 79.0% | 62.0% | -2.96 | -136.1% |
| A_stall_1s_30 | 74.2% | 148 | $-14.26 / $-47,415 / 64.4% | $-4.85 / $-16,065 / 66.7% | $-8.58 / $-8,430 / 67.7% | $-9.62 | $-73,650 | 0.92 | 77.6% | 60.3% | -2.99 | -129.6% |
| A_stall_5s_5 | 75.3% | 125 | $-11.69 / $-38,895 / 68.3% | $-4.90 / $-16,225 / 70.0% | $-6.88 / $-6,755 / 70.8% | $-8.36 | $-64,005 | 0.93 | 79.5% | 62.0% | -2.95 | -136.9% |
| A_stall_5s_10 | 72.9% | 165 | $-11.42 / $-37,985 / 63.0% | $-0.34 / $-1,140 / 65.8% | $0.02 / $20.00 / 66.3% | $-5.37 | $-41,145 | 0.96 | 75.7% | 58.3% | -3.01 | -284.6% |
| A_stall_5s_20 | 67.4% | 260 | $-12.32 / $-40,990 / 57.0% | $-2.94 / $-9,725 / 58.5% | $6.34 / $6,225 / 60.1% | $-6.09 | $-46,620 | 0.96 | 68.8% | 49.8% | -3.11 | -363.6% |
| A_stall_5s_30 | 61.5% | 330 | $-8.41 / $-27,975 / 52.7% | $2.72 / $8,990 / 54.1% | $5.97 / $5,865 / 54.8% | $-2.02 | $-15,465 | 0.99 | 61.0% | 41.2% | -3.18 | -1299.9% |
| A_stall_30s_5 | 60.6% | 331 | $-6.05 / $-20,125 / 52.6% | $2.37 / $7,830 / 53.7% | $7.21 / $7,080 / 54.4% | $-1.05 | $-8,060 | 0.99 | 59.4% | 39.8% | -3.18 | -2578.7% |
| A_stall_30s_10 | 40.5% | 496 | $-5.67 / $-18,870 / 44.8% | $15.41 / $50,995 / 43.7% | $-1.31 / $-1,285 / 44.0% | $3.88 | $29,690 | 1.02 | 39.4% | 19.8% | -3.31 | 875.8% |
| A_stall_30s_20 | 13.7% | 631 | $3.70 / $12,305 / 37.6% | $21.67 / $71,705 / 36.3% | $-3.08 / $-3,020 / 38.5% | $10.42 | $79,825 | 1.05 | 12.5% | 4.8% | -3.38 | 386.1% |
| A_stall_30s_30 | 4.3% | 631 | $6.84 / $22,740 / 36.2% | $17.87 / $59,140 / 34.7% | $-17.96 / $-17,635 / 36.0% | $8.19 | $62,760 | 1.04 | 4.4% | 1.3% | -3.41 | 514.3% |
| B_be_5s_5 | 62.4% | 212 | $-4.41 / $-14,665 / 14.5% | $12.59 / $41,670 / 14.5% | $3.38 / $3,315 / 15.2% | $3.66 | $28,040 | 1.03 | 58.2% | 63.4% | -3.04 | 981.3% |
| B_be_5s_10 | 60.9% | 240 | $5.06 / $16,830 / 15.8% | $23.80 / $78,770 / 15.9% | $10.31 / $10,120 / 16.1% | $13.63 | $104,400 | 1.12 | 54.4% | 63.2% | -3.04 | 268.4% |
| B_be_5s_20 | 55.9% | 296 | $19.18 / $63,785 / 18.8% | $48.09 / $159,145 / 19.2% | $45.20 / $44,390 / 20.4% | $34.73 | $266,000 | 1.28 | 45.0% | 60.6% | -3.05 | 111.9% |
| B_be_30s_2 | 59.8% | 270 | $9.49 / $31,555 / 16.6% | $31.06 / $102,775 / 16.9% | $24.75 / $24,300 / 17.5% | $20.54 | $157,310 | 1.17 | 51.6% | 62.9% | -3.04 | 184.5% |
| B_be_30s_3 | 56.6% | 298 | $19.69 / $65,500 / 18.8% | $47.69 / $157,815 / 19.0% | $47.65 / $46,790 / 20.3% | $35.09 | $268,785 | 1.29 | 45.2% | 61.4% | -3.04 | 109.7% |
| B_be_30s_5 | 48.4% | 362 | $31.19 / $103,725 / 22.2% | $54.45 / $180,175 / 22.3% | $51.68 / $50,745 / 23.1% | $43.62 | $334,115 | 1.32 | 35.8% | 54.0% | -3.09 | 90.0% |
| C_lock0_5s_5 | 39.2% | 391 | $-2.29 / $-7,600 / 22.0% | $11.57 / $38,270 / 22.4% | $-16.06 / $-15,770 / 23.4% | $1.65 | $12,610 | 1.01 | 35.8% | 39.7% | -3.31 | 2366.8% |
| C_lock25_5s_5 | 47.0% | 331 | $-0.77 / $-2,570 / 61.7% | $13.79 / $45,619 / 62.1% | $-8.97 / $-8,812 / 59.9% | $4.14 | $31,722 | 1.02 | 45.1% | 40.7% | -3.26 | 889.2% |
| C_lock50_5s_5 | 54.4% | 271 | $2.45 / $8,148 / 61.7% | $9.57 / $31,665 / 62.1% | $4.48 / $4,400 / 59.9% | $5.56 | $42,558 | 1.03 | 52.8% | 40.7% | -3.20 | 524.5% |
| C_lock0_5s_10 | 38.6% | 398 | $1.55 / $5,155 / 22.6% | $18.01 / $59,580 / 22.9% | $-12.11 / $-11,890 / 23.8% | $6.67 | $51,080 | 1.04 | 34.2% | 39.7% | -3.31 | 589.0% |
| C_lock25_5s_10 | 47.0% | 335 | $3.68 / $12,235 / 61.7% | $23.16 / $76,650 / 62.0% | $-3.44 / $-3,374 / 59.9% | $10.90 | $83,521 | 1.06 | 43.6% | 40.6% | -3.25 | 339.9% |
| C_lock50_5s_10 | 54.5% | 288 | $16.38 / $54,495 / 61.7% | $35.87 / $118,692 / 62.0% | $15.99 / $15,702 / 59.9% | $24.51 | $187,758 | 1.14 | 49.6% | 40.6% | -3.19 | 132.7% |
| C_lock0_5s_20 | 36.4% | 450 | $9.06 / $30,150 / 24.1% | $31.98 / $105,820 / 24.4% | $-4.15 / $-4,080 / 25.2% | $16.99 | $130,155 | 1.10 | 29.9% | 38.6% | -3.30 | 238.3% |
| C_lock25_5s_20 | 45.4% | 391 | $16.78 / $55,808 / 60.9% | $41.31 / $136,709 / 61.3% | $13.78 / $13,534 / 59.1% | $26.76 | $204,981 | 1.16 | 38.1% | 39.6% | -3.25 | 147.1% |
| C_lock50_5s_20 | 53.6% | 331 | $31.67 / $105,340 / 60.9% | $60.03 / $198,648 / 61.3% | $42.84 / $42,065 / 59.1% | $45.06 | $345,120 | 1.26 | 44.4% | 39.6% | -3.18 | 77.5% |
| C_lock0_30s_2 | 38.1% | 416 | $3.59 / $11,935 / 23.0% | $23.37 / $77,345 / 23.2% | $-6.56 / $-6,445 / 24.5% | $10.58 | $81,070 | 1.06 | 33.0% | 39.5% | -3.30 | 381.6% |
| C_lock25_30s_2 | 46.4% | 354 | $9.01 / $29,958 / 61.5% | $30.01 / $99,296 / 62.0% | $5.27 / $5,180 / 59.5% | $17.29 | $132,444 | 1.10 | 41.6% | 40.5% | -3.25 | 220.0% |
| C_lock50_30s_2 | 54.1% | 310 | $19.80 / $65,860 / 61.6% | $40.40 / $133,695 / 62.0% | $25.43 / $24,970 / 59.5% | $29.17 | $223,392 | 1.17 | 47.9% | 40.5% | -3.19 | 111.5% |
| C_lock0_30s_3 | 36.7% | 450 | $10.14 / $33,730 / 24.2% | $31.91 / $105,605 / 24.3% | $-1.52 / $-1,495 / 25.3% | $17.77 | $136,105 | 1.10 | 30.0% | 38.9% | -3.30 | 228.0% |
| C_lock25_30s_3 | 45.4% | 391 | $15.92 / $52,961 / 61.1% | $40.61 / $134,380 / 61.6% | $20.25 / $19,889 / 59.3% | $26.92 | $206,161 | 1.16 | 38.3% | 39.9% | -3.25 | 146.6% |
| C_lock50_30s_3 | 53.7% | 331 | $27.81 / $92,495 / 61.2% | $56.43 / $186,740 / 61.6% | $42.92 / $42,150 / 59.3% | $41.84 | $320,452 | 1.24 | 45.2% | 39.9% | -3.18 | 82.1% |
| C_lock0_30s_5 | 32.1% | 472 | $15.42 / $51,285 / 25.9% | $34.68 / $114,760 / 26.2% | $7.10 / $6,970 / 26.9% | $22.46 | $172,040 | 1.12 | 24.8% | 34.8% | -3.31 | 181.7% |
| C_lock25_30s_5 | 40.9% | 450 | $26.27 / $87,388 / 59.0% | $47.41 / $156,891 / 58.1% | $32.62 / $32,036 / 56.7% | $35.90 | $274,981 | 1.20 | 31.1% | 35.7% | -3.26 | 111.7% |
| C_lock50_30s_5 | 50.2% | 391 | $40.26 / $133,892 / 59.1% | $69.09 / $228,625 / 58.1% | $55.93 / $54,925 / 56.7% | $54.33 | $416,148 | 1.30 | 38.7% | 35.7% | -3.19 | 67.6% |

## Δ vs baseline regime exit

| Rule | Δ 2024 | Δ 2025 | Δ 2026 | Δ All mean | Δ All total |
|---|--:|--:|--:|--:|--:|
| REF_E_ltf_deterioration_T600 | $0.94 | $2.08 | $0.50 | $1.37 | $10,470 |
| A_stall_1s_5 | $-20.31 | $-24.54 | $9.27 | $-18.25 | $-139,810 |
| A_stall_1s_10 | $-20.38 | $-23.99 | $12.42 | $-17.66 | $-135,265 |
| A_stall_1s_20 | $-19.71 | $-20.60 | $8.33 | $-16.42 | $-125,790 |
| A_stall_1s_30 | $-21.76 | $-22.52 | $10.15 | $-17.92 | $-137,255 |
| A_stall_5s_5 | $-19.20 | $-22.57 | $11.86 | $-16.66 | $-127,610 |
| A_stall_5s_10 | $-18.93 | $-18.01 | $18.76 | $-13.68 | $-104,750 |
| A_stall_5s_20 | $-19.83 | $-20.61 | $25.08 | $-14.39 | $-110,225 |
| A_stall_5s_30 | $-15.92 | $-14.95 | $24.71 | $-10.32 | $-79,070 |
| A_stall_30s_5 | $-13.56 | $-15.30 | $25.95 | $-9.36 | $-71,665 |
| A_stall_30s_10 | $-13.18 | $-2.26 | $17.43 | $-4.43 | $-33,915 |
| A_stall_30s_20 | $-3.81 | $4.00 | $15.66 | $2.12 | $16,220 |
| A_stall_30s_30 | $-0.67 | $0.20 | $0.78 | $-0.11 | $-845.00 |
| B_be_5s_5 | $-11.92 | $-5.08 | $22.11 | $-4.64 | $-35,565 |
| B_be_5s_10 | $-2.45 | $6.14 | $29.04 | $5.33 | $40,795 |
| B_be_5s_20 | $11.67 | $30.43 | $63.94 | $26.43 | $202,395 |
| B_be_30s_2 | $1.98 | $13.39 | $43.48 | $12.23 | $93,705 |
| B_be_30s_3 | $12.19 | $30.02 | $66.38 | $26.79 | $205,180 |
| B_be_30s_5 | $23.68 | $36.78 | $70.41 | $35.32 | $270,510 |
| C_lock0_5s_5 | $-9.79 | $-6.10 | $2.68 | $-6.66 | $-50,995 |
| C_lock25_5s_5 | $-8.28 | $-3.88 | $9.76 | $-4.16 | $-31,882 |
| C_lock50_5s_5 | $-5.06 | $-8.10 | $23.22 | $-2.75 | $-21,048 |
| C_lock0_5s_10 | $-5.96 | $0.34 | $6.63 | $-1.64 | $-12,525 |
| C_lock25_5s_10 | $-3.83 | $5.50 | $15.30 | $2.60 | $19,916 |
| C_lock50_5s_10 | $8.88 | $18.20 | $34.73 | $16.21 | $124,152 |
| C_lock0_5s_20 | $1.56 | $14.31 | $14.58 | $8.69 | $66,550 |
| C_lock25_5s_20 | $9.27 | $23.65 | $32.52 | $18.46 | $141,376 |
| C_lock50_5s_20 | $24.17 | $42.36 | $61.57 | $36.76 | $281,515 |
| C_lock0_30s_2 | $-3.92 | $5.71 | $12.17 | $2.28 | $17,465 |
| C_lock25_30s_2 | $1.50 | $12.34 | $24.01 | $8.99 | $68,839 |
| C_lock50_30s_2 | $12.30 | $22.73 | $44.16 | $20.86 | $159,788 |
| C_lock0_30s_3 | $2.64 | $14.25 | $17.21 | $9.47 | $72,500 |
| C_lock25_30s_3 | $8.42 | $22.94 | $38.99 | $18.61 | $142,556 |
| C_lock50_30s_3 | $20.30 | $38.77 | $61.66 | $33.54 | $256,848 |
| C_lock0_30s_5 | $7.91 | $17.01 | $25.84 | $14.16 | $108,435 |
| C_lock25_30s_5 | $18.77 | $29.75 | $51.36 | $27.60 | $211,376 |
| C_lock50_30s_5 | $32.75 | $51.42 | $74.67 | $46.03 | $352,542 |

## Years positive per rule

| Rule | Yrs +mean | 2024 ✓? | 2025 ✓? | 2026 ✓? |
|---|--:|---|---|---|
| BASELINE_regime | 2/3 | ✅ | ✅ | ❌ |
| REF_E_ltf_deterioration_T600 | 2/3 | ✅ | ✅ | ❌ |
| A_stall_1s_5 | 0/3 | ❌ | ❌ | ❌ |
| A_stall_1s_10 | 0/3 | ❌ | ❌ | ❌ |
| A_stall_1s_20 | 0/3 | ❌ | ❌ | ❌ |
| A_stall_1s_30 | 0/3 | ❌ | ❌ | ❌ |
| A_stall_5s_5 | 0/3 | ❌ | ❌ | ❌ |
| A_stall_5s_10 | 1/3 | ❌ | ❌ | ✅ |
| A_stall_5s_20 | 1/3 | ❌ | ❌ | ✅ |
| A_stall_5s_30 | 2/3 | ❌ | ✅ | ✅ |
| A_stall_30s_5 | 2/3 | ❌ | ✅ | ✅ |
| A_stall_30s_10 | 1/3 | ❌ | ✅ | ❌ |
| A_stall_30s_20 | 2/3 | ✅ | ✅ | ❌ |
| A_stall_30s_30 | 2/3 | ✅ | ✅ | ❌ |
| B_be_5s_5 | 2/3 | ❌ | ✅ | ✅ |
| B_be_5s_10 | 3/3 | ✅ | ✅ | ✅ |
| B_be_5s_20 | 3/3 | ✅ | ✅ | ✅ |
| B_be_30s_2 | 3/3 | ✅ | ✅ | ✅ |
| B_be_30s_3 | 3/3 | ✅ | ✅ | ✅ |
| B_be_30s_5 | 3/3 | ✅ | ✅ | ✅ |
| C_lock0_5s_5 | 1/3 | ❌ | ✅ | ❌ |
| C_lock25_5s_5 | 1/3 | ❌ | ✅ | ❌ |
| C_lock50_5s_5 | 3/3 | ✅ | ✅ | ✅ |
| C_lock0_5s_10 | 2/3 | ✅ | ✅ | ❌ |
| C_lock25_5s_10 | 2/3 | ✅ | ✅ | ❌ |
| C_lock50_5s_10 | 3/3 | ✅ | ✅ | ✅ |
| C_lock0_5s_20 | 2/3 | ✅ | ✅ | ❌ |
| C_lock25_5s_20 | 3/3 | ✅ | ✅ | ✅ |
| C_lock50_5s_20 | 3/3 | ✅ | ✅ | ✅ |
| C_lock0_30s_2 | 2/3 | ✅ | ✅ | ❌ |
| C_lock25_30s_2 | 3/3 | ✅ | ✅ | ✅ |
| C_lock50_30s_2 | 3/3 | ✅ | ✅ | ✅ |
| C_lock0_30s_3 | 2/3 | ✅ | ✅ | ❌ |
| C_lock25_30s_3 | 3/3 | ✅ | ✅ | ✅ |
| C_lock50_30s_3 | 3/3 | ✅ | ✅ | ✅ |
| C_lock0_30s_5 | 3/3 | ✅ | ✅ | ✅ |
| C_lock25_30s_5 | 3/3 | ✅ | ✅ | ✅ |
| C_lock50_30s_5 | 3/3 | ✅ | ✅ | ✅ |

## Stall-distribution diagnostics — winners vs losers

| Granularity | Year | Cohort | n | Med max stall | p75 | p90 | Med final stall |
|---|--:|---|--:|--:|--:|--:|--:|
| 1s | 2024 | winner | 1,178 | 477 | 674 | 898 | 314 |
| 1s | 2024 | loser | 2,165 | 248 | 385 | 548 | 223 |
| 1s | 2025 | winner | 1,131 | 430 | 588 | 783 | 279 |
| 1s | 2025 | loser | 2,179 | 234 | 369 | 542 | 203 |
| 1s | 2026 | winner | 353 | 415 | 554 | 749 | 281 |
| 1s | 2026 | loser | 653 | 224 | 355 | 580 | 200 |
| 5s | 2024 | winner | 1,178 | 100 | 140 | 190 | 66 |
| 5s | 2024 | loser | 2,165 | 51 | 80 | 117 | 46 |
| 5s | 2025 | winner | 1,131 | 89 | 125 | 169 | 58 |
| 5s | 2025 | loser | 2,179 | 49 | 77 | 116 | 42 |
| 5s | 2026 | winner | 353 | 88 | 121 | 160 | 58 |
| 5s | 2026 | loser | 653 | 47 | 75 | 122 | 42 |
| 30s | 2024 | winner | 1,178 | 16 | 23 | 31 | 11 |
| 30s | 2024 | loser | 2,165 | 8 | 13 | 19 | 7 |
| 30s | 2025 | winner | 1,131 | 14 | 20 | 27 | 9 |
| 30s | 2025 | loser | 2,179 | 8 | 12 | 19 | 7 |
| 30s | 2026 | winner | 353 | 14 | 19 | 26 | 10 |
| 30s | 2026 | loser | 653 | 7 | 12 | 20 | 7 |

## Verdict — answer to the main question

**Yes — HH/LL progression contains substantial exit information. Multiple rules deliver true Pareto improvements (positive in all 3 years), far better than the prior conditioned-harvest study (which found only ONE rule with +$10K aggregate).**

### Structural validation from diagnostics

The stall-distribution data confirms the hypothesis: **winners stall longer than losers but eventually make new structure**:

| Granularity | Cohort | Median max stall | p90 max stall | Median final stall |
|---|---|--:|--:|--:|
| 30s buckets | Winner | 14-16 (≈420-480s) | 26-31 (≈780-930s) | 9-11 |
| 30s buckets | Loser | 7-8 (≈210-240s) | 19-20 (≈570-600s) | 7 |

Winner trades have **2x the median max stall** of losers and stay alive ~50% longer. This means: a trade that stalls without making new HH/LL for X bars is more likely to continue stalling and reverse, but only if the stall persists.

### What worked: Family B (move-to-BE) and Family C (lock partial MFE)

**Top 5 Pareto-improving rules (3/3 years positive)**:

| Rule | %fired | All Δ mean | Δ All total | 2024 Δ | 2025 Δ | 2026 Δ |
|---|--:|--:|--:|--:|--:|--:|
| **C_lock50_30s_5** | 50.2% | **+$46.03** | **+$352,542** | +$32.75 | +$51.42 | +$74.67 |
| **C_lock50_5s_20** | 53.6% | +$36.76 | +$281,515 | +$24.17 | +$42.36 | +$61.57 |
| **B_be_30s_5** | 48.4% | +$35.32 | +$270,510 | +$23.68 | +$36.78 | +$70.41 |
| **C_lock50_30s_3** | 53.7% | +$33.54 | +$256,848 | +$20.30 | +$38.77 | +$61.66 |
| **C_lock25_30s_5** | 40.9% | +$27.60 | +$211,376 | +$18.77 | +$29.75 | +$51.36 |

For comparison:
- BASELINE regime: $8.30/trade, $63,605 total
- REF E_ltf_deterioration_T600 (best from prior study): +$1.37/trade Δ, +$10,470
- **Best rule (C_lock50_30s_5)**: +$46.03/trade Δ, **+$352,542 (5.5x better baseline economics)**

### Why this works structurally

The Family A "exit on stall" rules (12 variants) almost all FAIL — most are net negative. This is informative: stall ALONE is not a sell signal. Many winners stall briefly then continue.

The Family B/C rules succeed because they **arm protection at the stall but only exit if price actually retraces**. This catches the "stall + reverse" trades while letting "stall + continue" trades run. The MFE capture pattern matches: top rules exit ~50% of trades at small protected wins, raising WR from 35% baseline to ~60%, while still allowing the runners that survive the protection level to reach regime exit.

### The C_lock50 family economics

Best rule (`C_lock50_30s_5`): after MFE ≥ 1.0 ATR AND 5 consecutive 30s buckets without a new favorable extreme, set protective exit at 50% of MFE-at-arm. Held to regime exit if not retraced.

| Metric | Baseline | C_lock50_30s_5 | Delta |
|---|--:|--:|--:|
| WR | 35% | 56-59% | +21-24 pts |
| Median hold | 631s | 391s | -38% (faster) |
| PF | 1.04 | 1.30 | +0.26 |
| Top-1% share | 506% | 67.6% | dramatically less outlier-dependent |
| 7yr total | $63,605 | $416,148 | **6.5×** |
| Years positive | 2/3 | 3/3 | covers 2026 |

The top-1% share dropping from 506% (i.e., baseline relies entirely on extreme outliers) to 68% is a major structural improvement — equity curve becomes smoother and less dependent on rare big wins.

### Caveats and required next steps

1. **Tested only on 2024-2026.** The user requested testing 2020-2023 next if promising. **This is now the critical follow-up** — these rules need OOS validation across different regimes (2020 COVID, 2021 grind, 2022 bear, 2023 chop). The fact that the best rule is positive in all 3 of 2024-26 is encouraging but not sufficient.
2. **Tape-replay vs NT runtime parity.** The intra-bar resolution (low for long, high for short) uses 1s-bar extremes from the tape. Should match NT bar_execution semantics, but should be validated with a NT runtime backtest of one rule before deploying.
3. **Threshold sensitivity.** C_lock50 vs C_lock25 vs C_lock0 (BE) are 3 distinct rule shapes; sweep across stall counts 2-10 in 30s granularity. Not done here per user instruction "do not optimize broadly".
4. **Cost model assumption.** The tick-data slippage validation showed $10/RT is realistic, so this is robust.
5. **Structural change to V_A.** This converts V_A from "trend rider with regime exit" to "trend rider with structural protection." Different risk profile. Drawdown patterns and per-day equity smoothness should be re-examined.

### Recommendation

This is the strongest exit-side finding in the series. Recommended next steps:
1. **Run the same 36 rules on 2020-2023** for OOS robustness — would take one quick batch with the existing tape infrastructure (need to capture tape for those years first, ~25 min)
2. **NT-validate `C_lock50_30s_5`** to confirm tape-replay parity holds in runtime
3. **If both pass, this becomes the deployable V_A overlay** — far stronger than the entry-side `flip2conf` filter, which the robustness battery exposed as fragile

## Files

- Per-rule per-trade results: `studies/v_a_exit_recon/results/trades_<rule>.parquet` (36 files)
- Summary: `studies/v_a_exit_recon/results/hhll_progression_summary.parquet`
- Stall distributions: `studies/v_a_exit_recon/results/stall_distributions.parquet`
- Replay code: `studies/v_a_exit_recon/hhll_progression.py`
