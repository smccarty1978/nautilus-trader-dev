# 2025 Ensemble Baseline (failure + winner v3)

Standard entry timing: signal_time + 30s fill.
Cost: $5 commission + 1-tick adverse entry + 1-tick exit slip on losses. Unresolved scored at -0.7 ATR.

## Comparison matrix

| Slice | n | Mean $ | Median | Trim 5% | PF | Win% | PT% | Reg% | L/S% | Total $ |
|---|--:|--:|--:|--:|--:|--:|--:|--:|---|--:|
| ALL (no filter, no selection) | 80,035 | $-12.11 | $-108.21 | $-14.20 | 0.92 | 47.6% | 47.6% | 12.4% | 51/49 | $-969,129 |
| Winner only (score >= val p90) | 9,816 | $-22.02 | $-126.25 | $-25.59 | 0.86 | 44.3% | 44.3% | 26.9% | 56/44 | $-216,185 |
| Failure-filter only excl worst 2% | 78,434 | $-11.13 | $-106.43 | $-13.15 | 0.93 | 47.9% | 47.9% | 11.8% | 52/48 | $-873,186 |
| Failure-filter only excl worst 5% | 76,033 | $-10.44 | $-104.50 | $-12.36 | 0.93 | 48.1% | 48.1% | 11.0% | 52/48 | $-793,763 |
| Failure-filter only excl worst 10% | 72,031 | $-10.28 | $-103.50 | $-11.99 | 0.93 | 48.3% | 48.3% | 10.0% | 52/48 | $-740,416 |
| Combined: excl worst 2% + winner top-10% | 7,847 | $-15.73 | $-120.75 | $-18.79 | 0.90 | 45.2% | 45.2% | 25.0% | 58/42 | $-123,431 |
| Combined: excl worst 5% + winner top-10% | 7,694 | $-12.06 | $-113.21 | $-14.83 | 0.92 | 46.4% | 46.4% | 22.1% | 58/42 | $-92,758 |
| Combined: excl worst 10% + winner top-10% | 7,206 | $-14.10 | $-115.73 | $-17.18 | 0.91 | 46.6% | 46.6% | 20.3% | 56/44 | $-101,572 |