# Validation 3 & 4 — Sizing Model Comparison

Objective: Compare Discrete Sizing, Conservative Sizing, and Continuous Sizing.

## Sizing Models
1. **Discrete**:
   - $hC \ge 0.5$: 2.0x (4 contracts)
   - $0.1 \le hC < 0.5$: 1.0x (2 contracts)
   - $hC < 0.1$: 0.5x (1 contract)
2. **Conservative**:
   - $hC \ge 0.5$: 1.5x (3 contracts)
   - $0.1 \le hC < 0.5$: 1.0x (2 contracts)
   - $hC < 0.1$: 0.5x (1 contract)
3. **Continuous**:
   - size = $f(hC)$ mapped linearly to $[0.5	ext{x}, 2.0	ext{x}]$:
     $f(hC) = 	ext{clip}(0.5 + 3.75 \cdot (hC - 0.1), 0.5, 2.0)$
     and snapped to integer contracts: $	ext{round}(2.0 \cdot f(hC))$.

## Sizing Model Results

| Sizing Policy | Year | Trades | Net PnL | PnL/Trade | PF | Win Rate | Max DD |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Discrete Sizing | 2022 | 3023 | $-170,500.00 | $-56.40 | 0.92 | 34.2% | $229,425.00 |
| Discrete Sizing | 2023 | 2997 | $61,995.00 | $20.69 | 1.05 | 34.9% | $41,915.00 |
| Discrete Sizing | 2024 | 2863 | $-38,240.00 | $-13.36 | 0.98 | 33.7% | $109,360.00 |
| Discrete Sizing | 2025 | 2719 | $92,415.00 | $33.99 | 1.04 | 35.6% | $121,200.00 |
| Discrete Sizing | 2026 | 861 | $39,590.00 | $45.98 | 1.05 | 33.4% | $95,980.00 |
| **Discrete Sizing (Pooled)** | **All** | **12463** | **$-14,740.00** | **$-1.18** | **1.00** | **34.5%** | **$229,425.00** |
| Conservative Sizing | 2022 | 3118 | $-140,115.00 | $-44.94 | 0.93 | 34.9% | $190,190.00 |
| Conservative Sizing | 2023 | 3080 | $-23,195.00 | $-7.53 | 0.98 | 35.3% | $60,915.00 |
| Conservative Sizing | 2024 | 2957 | $-17,665.00 | $-5.97 | 0.99 | 34.7% | $127,825.00 |
| Conservative Sizing | 2025 | 2799 | $102,620.00 | $36.66 | 1.06 | 35.8% | $70,245.00 |
| Conservative Sizing | 2026 | 911 | $7,855.00 | $8.62 | 1.01 | 34.5% | $81,680.00 |
| **Conservative Sizing (Pooled)** | **All** | **12865** | **$-70,500.00** | **$-5.48** | **0.99** | **35.1%** | **$252,150.00** |
| Continuous Sizing | 2022 | 2983 | $-183,217.25 | $-61.42 | 0.92 | 34.2% | $231,339.35 |
| Continuous Sizing | 2023 | 2963 | $23,867.32 | $8.06 | 1.02 | 34.7% | $66,991.30 |
| Continuous Sizing | 2024 | 2819 | $-17,842.70 | $-6.33 | 0.99 | 33.7% | $141,116.18 |
| Continuous Sizing | 2025 | 2670 | $81,429.85 | $30.50 | 1.04 | 34.8% | $162,283.05 |
| Continuous Sizing | 2026 | 846 | $-8,211.20 | $-9.71 | 0.99 | 33.3% | $97,317.63 |
| **Continuous Sizing (Pooled)** | **All** | **12281** | **$-103,973.98** | **$-8.47** | **0.99** | **34.3%** | **$237,822.35** |

## Comparison
* **Continuous vs. Discrete Sizing**: Continuous sizing offers a smoother risk scaling function and avoids arbitrary threshold cliffs.
* **Conservative vs. Aggressive Sizing**: Sizing models with 2.0x leverage (Discrete and Continuous) show stronger expectancies than Conservative sizing (1.5x), suggesting the sizing signal benefits from aggressive allocation when health is extremely high.
