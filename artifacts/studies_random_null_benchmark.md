# Random-Entry Null Benchmark Study

Generated at: 2026-06-07 03:05:58 (Study ID: `random_entry_null_study_1780819558`)

## Section 1: Executive Summary & Decision Adjudication

**Final Adjudication:** **Falsified (no positive entry alpha) — load-bearing**

> [!CAUTION]
> **Timing Edge Falsified:** Under the decisive, exposure-matched benchmark (Flavor B), the Stall-State strategy's mean ATR performance sits at the **24.4th percentile** of the random null distribution (one-sided p-value = **0.7562**).
> The aggregate year-level Fisher's combined test is also non-significant (p = **0.5661**). Entering at the regime-flip breakout timing carries **no positive alpha** once exposure and hold time are controlled.

### Mechanism Verdict:
> **Verdict: No continuation timing edge.** The breakout signal has no directional or timing advantage over random entry.

## Section 2: Aggregated Monte Carlo Benchmark Table

| Cohort | Total Trades | Win Rate (%) | Mean ATR | Mean Points | Gross PF | Net PF | Total Net PnL ($) | One-sided p-value | Percentile |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Stall-State Candidate** | 60,763 | 13.61% | 0.0028 | 0.05 | 1.01 | 0.80 | $-555,120.00 | - | - |
| **Flavor A Null (Median)** | 8,868 | 16.17% | 0.0040 | 0.02 | 1.02 | 0.74 | $-582,860.00 | 0.5934 | 40.7% |
| **Flavor B Null (Median)** | 8,607 | 49.15% | 0.0084 | 0.04 | 1.01 | 0.86 | $-558,807.50 | 0.7562 | 24.4% |

## Section 3: Year-by-Year Benchmarks & Significance

| Year | Candidate Trades | Candidate Mean ATR | Flavor B Median ATR | Flavor B Percentile | Flavor B p-value | Flavor A Median ATR | Flavor A Percentile | Flavor A p-value |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| 2020 | 9,001 | -0.0205 | 0.0119 | 5.0% | 0.9500 | 0.0033 | 1.7% | 0.9830 |
| 2021 | 9,686 | -0.0043 | 0.0109 | 14.7% | 0.8531 | 0.0061 | 14.3% | 0.8571 |
| 2022 | 9,648 | 0.0056 | -0.0078 | 79.5% | 0.2058 | 0.0040 | 56.7% | 0.4336 |
| 2023 | 9,685 | -0.0318 | 0.0149 | 0.2% | 0.9980 | -0.0119 | 2.7% | 0.9730 |
| 2024 | 9,724 | 0.0214 | 0.0185 | 56.2% | 0.4386 | 0.0166 | 65.2% | 0.3487 |
| 2025 | 9,824 | 0.0303 | 0.0070 | 91.0% | 0.0909 | 0.0162 | 87.6% | 0.1249 |
| 2026 | 3,195 | 0.0188 | 0.0005 | 71.0% | 0.2907 | -0.0050 | 87.3% | 0.1279 |

### Aggregate Year-Level Tests (Flavor B):
*   **Fisher's Combined p-value:** **0.5661** (X2 = 12.50)
*   **Binomial Sign Test (Stall beats median in 4/7 years):** **0.5000**

## Section 4: Entry Timing Mechanism Diagnostics

To understand why the timing edge collapsed, we decomposed the win/loss metrics side-by-side against both the Flavor A (exit-controlled) and Flavor B (exposure-controlled) controls:

| Diagnostic Metric | Stall-State Candidate | Flavor A Null (Exit Control) | Flavor B Null (Exposure Control) | Diagnostic Finding (vs Flavor A) |
| :--- | :---: | :---: | :---: | :--- |
| **Win Rate** | 13.61% | 16.17% | 49.15% | Candidate win rate is **-2.56pp** lower (No directional timing advantage) |
| **Avg Winner Size (ATR)** | 2.1541 ATR | 1.4088 ATR | 0.9406 ATR | Candidate winner size is **+52.9%** larger (Breakout entry selection effect) |
| **Avg Loser Size (ATR)** | 0.3360 ATR | 0.2662 ATR | 0.8936 ATR | Candidate loser size is **+26.2%** larger (Breakout entries suffer larger losses than random) |
| **Winner 90th Pct (ATR)** | 4.9743 ATR | 3.5103 ATR | 2.0546 ATR | Candidate right-tail is **+41.7%** larger (Selection retains tail upside) |
| **MFE Capture Ratio** | -1.0790 | -0.9440 | -1.6711 | Candidate MFE capture is **-14.3%** lower (Reflects higher stop-out rate and lower efficiency) |

### Diagnostic Discussion:
This diagnostic decomposition clarifies the timing characteristics:
1.  When compared against Flavor A (the same exit engine but with random entries), the candidate exhibits a lower win rate (**13.61%** vs **16.17%**). This shows that buying range-expansion flips is directionally *inferior* to entering at random moments and letting exits run.
2.  While the candidate has a larger average winner size (**2.1541 ATR** vs **1.4088 ATR**), it also suffers from larger average losses (**0.3360 ATR** vs **0.2662 ATR**). This demonstrates that range-expansion flips enter during high-volatility regimes where swings are wider, leading to both larger gains and larger losses, but with a net-negative outcome due to a lower win rate.
3.  Furthermore, the MFE capture ratio is lower (**-1.0790** vs **-0.9440**), indicating that breakout entries are less efficient at capturing favorable moves relative to their maximum excursions, likely due to execution lag (buying local extensions that immediately mean-revert).
4.  Therefore, range-expansion breakout entry timing carries **no positive entry alpha** compared to entering at random flat intervals. The strategy's entry edge is officially falsified.
