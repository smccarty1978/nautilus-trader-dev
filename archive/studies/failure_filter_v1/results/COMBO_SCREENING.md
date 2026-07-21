# Combo Screening — Failure Filter + Winner Model

Post-processing test on existing OOS predictions. No live NT run, no single-position gate. Pure formulaic bracket PnL.

Cost: $5 commission + 1-tick adverse entry + 1-tick adverse exit on losses. Unresolved rows scored as -0.7 ATR proxy (matches prior regime-exit-rows behavior).

## 2024 OOS

| Slice | n | Mean $ | Median $ | Trim 5% | PF | Win% | PT% | Reg% | L/S% | Total $ |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|--:|
| ALL (no filter, no selection) | 77,647 | $-14.96 | $-104.29 | $-15.14 | 0.87 | 47.9% | 47.9% | 11.8% | 52/48 | $-1,161,959 |
| Winner only (top-10%) | 7,782 | $-11.09 | $67.86 | $-8.51 | 0.91 | 50.4% | 50.4% | 6.1% | 59/41 | $-86,324 |
| Failure-filter only: excl worst 2% | 76,094 | $-14.18 | $-102.00 | $-14.31 | 0.88 | 48.2% | 48.2% | 11.1% | 52/48 | $-1,079,042 |
| Failure-filter only: excl worst 5% | 73,764 | $-13.35 | $-100.71 | $-13.42 | 0.89 | 48.4% | 48.4% | 10.3% | 53/47 | $-984,644 |
| Failure-filter only: excl worst 10% | 69,882 | $-12.15 | $-96.43 | $-12.14 | 0.90 | 48.8% | 48.8% | 9.3% | 53/47 | $-849,303 |
| Combined: excl worst 2% + winner top-10% | 7,618 | $-11.38 | $67.86 | $-8.83 | 0.91 | 50.4% | 50.4% | 6.1% | 59/41 | $-86,697 |
| Combined: excl worst 5% + winner top-10% | 7,389 | $-12.93 | $-47.86 | $-10.50 | 0.89 | 49.9% | 49.9% | 6.2% | 59/41 | $-95,540 |
| Combined: excl worst 10% + winner top-10% | 6,997 | $-15.03 | $-91.00 | $-12.62 | 0.88 | 49.5% | 49.5% | 6.1% | 58/42 | $-105,157 |

## 2026 OOS

| Slice | n | Mean $ | Median $ | Trim 5% | PF | Win% | PT% | Reg% | L/S% | Total $ |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|--:|
| ALL (no filter, no selection) | 22,135 | $-23.84 | $-131.07 | $-26.22 | 0.87 | 47.1% | 47.1% | 11.7% | 50/50 | $-527,684 |
| Winner only (top-10%) | 2,215 | $9.45 | $108.57 | $5.61 | 1.06 | 51.2% | 51.2% | 5.0% | 66/34 | $20,937 |
| Failure-filter only: excl worst 2% | 21,692 | $-22.10 | $-126.75 | $-24.33 | 0.88 | 47.4% | 47.4% | 11.1% | 50/50 | $-479,338 |
| Failure-filter only: excl worst 5% | 21,028 | $-21.56 | $-124.29 | $-23.61 | 0.88 | 47.6% | 47.6% | 10.3% | 50/50 | $-453,284 |
| Failure-filter only: excl worst 10% | 19,921 | $-18.73 | $-121.25 | $-20.47 | 0.90 | 48.1% | 48.1% | 9.2% | 51/49 | $-373,094 |
| Combined: excl worst 2% + winner top-10% | 2,171 | $8.55 | $108.57 | $4.61 | 1.05 | 51.2% | 51.2% | 4.9% | 67/33 | $18,554 |
| Combined: excl worst 5% + winner top-10% | 2,104 | $8.80 | $108.57 | $4.80 | 1.05 | 51.1% | 51.1% | 5.0% | 67/33 | $18,517 |
| Combined: excl worst 10% + winner top-10% | 1,993 | $12.94 | $108.57 | $8.90 | 1.08 | 51.5% | 51.5% | 4.8% | 68/32 | $25,784 |
