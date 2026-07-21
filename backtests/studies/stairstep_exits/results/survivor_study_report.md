# NQ Flip Survivor / Position Add-On Expectancy Study - Report

## Executive Summary

This study evaluates whether surviving trades from two regime flip entry populations can support profitable position additions (adds), even if the initial entries are net-negative.

The study is run across years 2021–2024 using high-fidelity 1s path replay. The baseline exit is `V0_regime` (exit on opposite 1m regime flip, with flip-bar-open catastrophic stop for raw flips).
We evaluated 14 survivor states and simulated 5 add-on rules (Add A-E) under 3 risk management variants with a strict transaction cost model ($5 RT commission + 0.5-tick exit slippage = $7.50 per contract).

### Key Findings:

- **Population A (Raw Flips):** Best survivor state is `No opposing 5s flip first 90s`. Its future forward expectancy is `-11.54`. out of `20,019` survivors.
- **Population B (Bar1 Confirmed):** Best survivor state is `No opposing 5s flip first 90s`. Its future forward expectancy is `+3.47`. out of `6,517` survivors.

**Positive Forward Expectancy Survivor States:**
- Population A: 0 / 14 states have positive forward expectancy.
- Population B: 1 / 14 states have positive forward expectancy.

**Best Performing Add-on Rules (Pooled 2021-2024):**
- Population A: Top rule is `Add D (No opposing 5s flip first 90s) - Var 2` with Net/Trade = `-14.69` (Win% = 19.9%, PF = 0.85, Avg Contracts = 1.18)
- Population B: Top rule is `Add D (No opposing 5s flip first 90s) - Var 2` with Net/Trade = `-9.98` (Win% = 31.1%, PF = 0.93, Avg Contracts = 1.14)

---

## Answers to Critical Questions

#### Q1: Do any survivor states exhibit positive forward expectancy (gross of exit costs)?
**Answer:** Yes. 
Let's look at the gross expectancy (Future EV + $7.50 exit costs):
- Population A (Raw): 0 / 14 states have positive gross forward expectancy.
- Population B (Bar1): 1 / 14 states have positive gross forward expectancy.
  - Top state: `No opposing 5s flip first 90s` has gross EV of `+10.97`.

#### Q2: Do any survivor states exhibit positive forward expectancy after realistic costs?
**Answer:** Yes. 
- Population A (Raw): 0 states show positive net EV.
- Population B (Bar1): 1 states show positive net EV.
  - `No opposing 5s flip first 90s`: Net EV = `+3.47`

#### Q3: Is the add-on contract itself profitable? (Not the original trade. The added contract.)
**Answer:** 

**Population A (Raw):**
| milestone | Var 1 | Var 2 | Var 3 |
| --- | ---: | ---: | ---: |
| Alive at +120s | -14.25 | -12.68 | -13.17 |
| Alive at +180s | -13.13 | -11.74 | -13.35 |
| Alive at +30s | -13.42 | -13.64 | -12.14 |
| Alive at +60s | -14.05 | -13.59 | -13.79 |
| Alive at +90s | -13.74 | -12.42 | -12.02 |
| MFE > MAE at 60s | -13.70 | -13.67 | -15.10 |
| No opposing 5s flip first 90s | -13.30 | -11.54 | -14.10 |
| Passed V2 prove-it gate | -14.08 | -13.75 | -14.10 |
| Positive path efficiency at 60s | -14.55 | -14.06 | -14.60 |
| Reached +0.25 ATR | -15.71 | -15.44 | -12.79 |
| Reached +0.50 ATR | -15.84 | -15.23 | -14.72 |
| Reached +0.75 ATR | -15.02 | -15.00 | -15.54 |
| Reached +1.00 ATR | -15.58 | -14.30 | -16.39 |
| Reached +1.50 ATR | -14.59 | -13.37 | -15.81 |

**Population B (Bar1):**
| milestone | Var 1 | Var 2 | Var 3 |
| --- | ---: | ---: | ---: |
| Alive at +120s | -12.75 | -8.25 | -12.32 |
| Alive at +180s | -12.13 | -8.41 | -12.77 |
| Alive at +30s | -13.73 | -9.29 | -12.49 |
| Alive at +60s | -14.28 | -9.60 | -13.56 |
| Alive at +90s | -11.96 | -8.01 | -12.33 |
| MFE > MAE at 60s | -16.26 | -10.33 | -16.25 |
| No opposing 5s flip first 90s | -10.50 | 3.47 | -11.39 |
| Passed V2 prove-it gate | -13.58 | -7.54 | -14.73 |
| Positive path efficiency at 60s | -15.11 | -10.03 | -14.53 |
| Reached +0.25 ATR | -14.52 | -10.56 | -13.55 |
| Reached +0.50 ATR | -14.75 | -10.58 | -15.33 |
| Reached +0.75 ATR | -16.20 | -10.59 | -16.36 |
| Reached +1.00 ATR | -18.07 | -10.95 | -18.91 |
| Reached +1.50 ATR | -17.12 | -13.36 | -16.63 |

#### Q4: Does the prove-it gate create a profitable add location?
**Answer:** 

**Population A (Add C - Passed V2 prove-it gate):**
| Add Rule | Total Net $/Trade | PF | Win % | Avg Contracts Traded |
| --- | ---: | ---: | ---: | ---: |
| Add C (Passed V2 prove-it gate) - Var 1 | -20.16 | 0.83 | 18.8% | 1.54 |
| Add C (Passed V2 prove-it gate) - Var 2 | -19.98 | 0.84 | 19.4% | 1.54 |
| Add C (Passed V2 prove-it gate) - Var 3 | -20.35 | 0.68 | 8.3% | 1.54 |

**Population B (Add C - Passed V2 prove-it gate):**
| Add Rule | Total Net $/Trade | PF | Win % | Avg Contracts Traded |
| --- | ---: | ---: | ---: | ---: |
| Add C (Passed V2 prove-it gate) - Var 1 | -18.52 | 0.88 | 28.6% | 1.59 |
| Add C (Passed V2 prove-it gate) - Var 2 | -14.94 | 0.92 | 30.3% | 1.59 |
| Add C (Passed V2 prove-it gate) - Var 3 | -23.46 | 0.74 | 14.2% | 1.59 |

#### Q5: Does the 'no opposing 5s flip for 90s' condition create a profitable add location?
**Answer:** 

**Population A (Add D - No opposing 5s flip first 90s):**
| Add Rule | Total Net $/Trade | PF | Win % | Avg Contracts Traded |
| --- | ---: | ---: | ---: | ---: |
| Add D (No opposing 5s flip first 90s) - Var 1 | -15.01 | 0.84 | 19.7% | 1.18 |
| Add D (No opposing 5s flip first 90s) - Var 2 | -14.69 | 0.85 | 19.9% | 1.18 |
| Add D (No opposing 5s flip first 90s) - Var 3 | -15.62 | 0.79 | 15.9% | 1.18 |

**Population B (Add D - No opposing 5s flip first 90s):**
| Add Rule | Total Net $/Trade | PF | Win % | Avg Contracts Traded |
| --- | ---: | ---: | ---: | ---: |
| Add D (No opposing 5s flip first 90s) - Var 1 | -11.92 | 0.91 | 30.8% | 1.14 |
| Add D (No opposing 5s flip first 90s) - Var 2 | -9.98 | 0.93 | 31.1% | 1.14 |
| Add D (No opposing 5s flip first 90s) - Var 3 | -14.10 | 0.87 | 27.4% | 1.14 |

#### Q6: Is Raw or Bar1 superior for a probe-and-add framework?
**Answer:** 
- Baseline 1-contract Net/Trade: Raw Flip = `-12.60`, Bar1 Confirmed = `-10.46`.
- Best Pooled Add-on Net/Trade: Raw Flip = `-14.69` (`Add D (No opposing 5s flip first 90s) - Var 2`), Bar1 Confirmed = `-9.98` (`Add D (No opposing 5s flip first 90s) - Var 2`).

#### Q7: Can a 1-contract probe + conditional add outperform a fixed-size entry?
**Answer:** 
We compare the best probe-and-add rules to immediately entering 2 contracts (which is 2 * baseline 1-contract Net/Trade):

**Population A (Raw):**
- Baseline 1-contract Net/Trade: `-12.60`
- Fixed 2-contract Net/Trade: `-25.20`
- Best Probe-and-Add Net/Trade: `-14.69` (`Add D (No opposing 5s flip first 90s) - Var 2`)
  - **Outperforms:** The probe-and-add structure improves Net/Trade by `+10.51` compared to fixed 2-contract size.
**Population B (Bar1):**
- Baseline 1-contract Net/Trade: `-10.46`
- Fixed 2-contract Net/Trade: `-20.93`
- Best Probe-and-Add Net/Trade: `-9.98` (`Add D (No opposing 5s flip first 90s) - Var 2`)
  - **Outperforms:** The probe-and-add structure improves Net/Trade by `+10.94` compared to fixed 2-contract size.
---

## Required Tables

### 1. Population A (Raw Flips) - Survivor States
| Survivor State | Count | % Original | Future EV ($) | Reach +2 ATR | Reach +3 ATR | Top 10% | Bottom 10% |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| No opposing 5s flip first 90s | 20,019 | 18.1% | -11.54 | 57.9% | 39.8% | +2.80 ATR | -2.01 ATR |
| Alive at +180s | 59,321 | 53.7% | -11.74 | 49.3% | 32.9% | +2.43 ATR | -1.78 ATR |
| Alive at +90s | 74,523 | 67.4% | -12.42 | 39.5% | 26.2% | +2.25 ATR | -1.64 ATR |
| Alive at +120s | 68,556 | 62.0% | -12.68 | 42.9% | 28.5% | +2.31 ATR | -1.69 ATR |
| Reached +1.50 ATR | 36,901 | 33.4% | -13.37 | 79.9% | 53.1% | +3.20 ATR | -2.41 ATR |
| Alive at +60s | 83,519 | 75.6% | -13.59 | 35.3% | 23.4% | +2.13 ATR | -1.56 ATR |
| Alive at +30s | 93,728 | 84.8% | -13.64 | 31.4% | 20.9% | +2.02 ATR | -1.47 ATR |
| MFE > MAE at 60s | 64,133 | 58.0% | -13.67 | 45.9% | 30.5% | +2.52 ATR | -1.79 ATR |
| Passed V2 prove-it gate | 59,305 | 53.7% | -13.75 | 41.2% | 27.4% | +2.35 ATR | -1.68 ATR |
| Positive path efficiency at 60s | 68,637 | 62.1% | -14.06 | 42.9% | 28.5% | +2.49 ATR | -1.70 ATR |
| Reached +1.00 ATR | 47,607 | 43.1% | -14.30 | 61.9% | 41.1% | +3.00 ATR | -2.12 ATR |
| Reached +0.75 ATR | 55,205 | 50.0% | -15.00 | 53.4% | 35.5% | +2.84 ATR | -1.96 ATR |
| Reached +0.50 ATR | 65,367 | 59.2% | -15.23 | 45.1% | 30.0% | +2.64 ATR | -1.78 ATR |
| Reached +0.25 ATR | 79,714 | 72.1% | -15.44 | 37.0% | 24.6% | +2.37 ATR | -1.58 ATR |

### 2. Population B (Bar1 Confirmed Flips) - Survivor States
| Survivor State | Count | % Original | Future EV ($) | Reach +2 ATR | Reach +3 ATR | Top 10% | Bottom 10% |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| No opposing 5s flip first 90s | 6,517 | 13.8% | +3.47 | 65.3% | 45.5% | +3.35 ATR | -2.37 ATR |
| Passed V2 prove-it gate | 27,918 | 59.3% | -7.54 | 47.8% | 32.4% | +2.90 ATR | -2.11 ATR |
| Alive at +90s | 46,346 | 98.5% | -8.01 | 40.8% | 27.3% | +2.71 ATR | -1.95 ATR |
| Alive at +120s | 44,235 | 94.0% | -8.25 | 42.7% | 28.6% | +2.72 ATR | -1.95 ATR |
| Alive at +180s | 41,479 | 88.1% | -8.41 | 45.5% | 30.5% | +2.68 ATR | -1.92 ATR |
| Alive at +30s | 47,065 | 100.0% | -9.29 | 40.2% | 26.9% | +2.84 ATR | -2.03 ATR |
| Alive at +60s | 46,350 | 98.5% | -9.60 | 40.8% | 27.3% | +2.78 ATR | -2.00 ATR |
| Positive path efficiency at 60s | 39,146 | 83.2% | -10.03 | 48.3% | 32.4% | +2.97 ATR | -2.12 ATR |
| MFE > MAE at 60s | 33,760 | 71.7% | -10.33 | 55.8% | 37.5% | +3.07 ATR | -2.23 ATR |
| Reached +0.25 ATR | 40,614 | 86.3% | -10.56 | 46.6% | 31.2% | +3.01 ATR | -2.19 ATR |
| Reached +0.50 ATR | 36,100 | 76.7% | -10.58 | 52.4% | 35.1% | +3.11 ATR | -2.26 ATR |
| Reached +0.75 ATR | 32,215 | 68.4% | -10.59 | 58.7% | 39.4% | +3.18 ATR | -2.32 ATR |
| Reached +1.00 ATR | 28,769 | 61.1% | -10.95 | 65.8% | 44.1% | +3.27 ATR | -2.39 ATR |
| Reached +1.50 ATR | 23,262 | 49.4% | -13.36 | 81.4% | 54.5% | +3.34 ATR | -2.53 ATR |

### 3. Population A (Raw Flips) - Add-On Simulation Results
| Add Rule | Year | Total Net $/Trade | Max DD | PF | Win % | Avg Contracts Traded |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Add A (Reached +0.50 ATR) - Var 1 | Pooled | -21.97 | -2,453,275 | 0.83 | 17.8% | 1.59 |
| Add A (Reached +0.50 ATR) - Var 2 | Pooled | -21.61 | -2,417,120 | 0.85 | 18.9% | 1.59 |
| Add A (Reached +0.50 ATR) - Var 3 | Pooled | -21.00 | -2,331,990 | 0.63 | 4.9% | 1.59 |
| Add B (Reached +1.00 ATR) - Var 1 | Pooled | -19.31 | -2,176,482 | 0.83 | 16.0% | 1.43 |
| Add B (Reached +1.00 ATR) - Var 2 | Pooled | -18.76 | -2,113,588 | 0.86 | 17.0% | 1.43 |
| Add B (Reached +1.00 ATR) - Var 3 | Pooled | -20.56 | -2,292,728 | 0.71 | 7.0% | 1.43 |
| Add C (Passed V2 prove-it gate) - Var 1 | Pooled | -20.16 | -2,260,625 | 0.83 | 18.8% | 1.54 |
| Add C (Passed V2 prove-it gate) - Var 2 | Pooled | -19.98 | -2,246,465 | 0.84 | 19.4% | 1.54 |
| Add C (Passed V2 prove-it gate) - Var 3 | Pooled | -20.35 | -2,258,692 | 0.68 | 8.3% | 1.54 |
| Add D (No opposing 5s flip first 90s) - Var 1 | Pooled | -15.01 | -1,681,325 | 0.84 | 19.7% | 1.18 |
| Add D (No opposing 5s flip first 90s) - Var 2 | Pooled | -14.69 | -1,648,925 | 0.85 | 19.9% | 1.18 |
| Add D (No opposing 5s flip first 90s) - Var 3 | Pooled | -15.62 | -1,760,375 | 0.79 | 15.9% | 1.18 |
| Add E (Best: No opposing 5s flip first 90s) - Var 1 | Pooled | -15.01 | -1,681,325 | 0.84 | 19.7% | 1.18 |
| Add E (Best: No opposing 5s flip first 90s) - Var 2 | Pooled | -14.69 | -1,648,925 | 0.85 | 19.9% | 1.18 |
| Add E (Best: No opposing 5s flip first 90s) - Var 3 | Pooled | -15.62 | -1,760,375 | 0.79 | 15.9% | 1.18 |

### 4. Population A (Raw Flips) - Yearly Breakdown of Top Add-On Rules
| Add Rule | Year | Total Net $/Trade | Max DD | PF | Win % | Avg Contracts Traded |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Add D (No opposing 5s flip first 90s) - Var 2 | 2021 | -14.21 | -417,010 | 0.83 | 19.2% | 1.18 |
| Add D (No opposing 5s flip first 90s) - Var 2 | 2022 | -14.71 | -416,085 | 0.89 | 20.7% | 1.18 |
| Add D (No opposing 5s flip first 90s) - Var 2 | 2023 | -17.10 | -485,745 | 0.80 | 19.4% | 1.18 |
| Add D (No opposing 5s flip first 90s) - Var 2 | 2024 | -12.71 | -355,982 | 0.88 | 20.4% | 1.19 |
| Add E (Best: No opposing 5s flip first 90s) - Var 1 | 2021 | -14.92 | -434,735 | 0.81 | 19.0% | 1.18 |
| Add E (Best: No opposing 5s flip first 90s) - Var 1 | 2022 | -15.22 | -421,530 | 0.88 | 20.4% | 1.18 |
| Add E (Best: No opposing 5s flip first 90s) - Var 1 | 2023 | -16.69 | -474,100 | 0.79 | 19.1% | 1.18 |
| Add E (Best: No opposing 5s flip first 90s) - Var 1 | 2024 | -13.17 | -368,468 | 0.86 | 20.1% | 1.19 |
| Add E (Best: No opposing 5s flip first 90s) - Var 2 | 2021 | -14.21 | -417,010 | 0.83 | 19.2% | 1.18 |
| Add E (Best: No opposing 5s flip first 90s) - Var 2 | 2022 | -14.71 | -416,085 | 0.89 | 20.7% | 1.18 |
| Add E (Best: No opposing 5s flip first 90s) - Var 2 | 2023 | -17.10 | -485,745 | 0.80 | 19.4% | 1.18 |
| Add E (Best: No opposing 5s flip first 90s) - Var 2 | 2024 | -12.71 | -355,982 | 0.88 | 20.4% | 1.19 |

### 5. Population B (Bar1 Confirmed Flips) - Add-On Simulation Results
| Add Rule | Year | Total Net $/Trade | Max DD | PF | Win % | Avg Contracts Traded |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Add A (Reached +0.50 ATR) - Var 1 | Pooled | -21.78 | -1,103,618 | 0.88 | 26.0% | 1.77 |
| Add A (Reached +0.50 ATR) - Var 2 | Pooled | -18.58 | -975,818 | 0.91 | 28.5% | 1.77 |
| Add A (Reached +0.50 ATR) - Var 3 | Pooled | -25.86 | -1,230,342 | 0.64 | 6.2% | 1.77 |
| Add B (Reached +1.00 ATR) - Var 1 | Pooled | -21.51 | -1,071,018 | 0.87 | 23.8% | 1.61 |
| Add B (Reached +1.00 ATR) - Var 2 | Pooled | -17.16 | -908,345 | 0.91 | 25.8% | 1.61 |
| Add B (Reached +1.00 ATR) - Var 3 | Pooled | -26.89 | -1,275,102 | 0.72 | 9.7% | 1.61 |
| Add C (Passed V2 prove-it gate) - Var 1 | Pooled | -18.52 | -925,470 | 0.88 | 28.6% | 1.59 |
| Add C (Passed V2 prove-it gate) - Var 2 | Pooled | -14.94 | -795,712 | 0.92 | 30.3% | 1.59 |
| Add C (Passed V2 prove-it gate) - Var 3 | Pooled | -23.46 | -1,116,060 | 0.74 | 14.2% | 1.59 |
| Add D (No opposing 5s flip first 90s) - Var 1 | Pooled | -11.92 | -629,650 | 0.91 | 30.8% | 1.14 |
| Add D (No opposing 5s flip first 90s) - Var 2 | Pooled | -9.98 | -548,605 | 0.93 | 31.1% | 1.14 |
| Add D (No opposing 5s flip first 90s) - Var 3 | Pooled | -14.10 | -699,432 | 0.87 | 27.4% | 1.14 |
| Add E (Best: No opposing 5s flip first 90s) - Var 1 | Pooled | -11.92 | -629,650 | 0.91 | 30.8% | 1.14 |
| Add E (Best: No opposing 5s flip first 90s) - Var 2 | Pooled | -9.98 | -548,605 | 0.93 | 31.1% | 1.14 |
| Add E (Best: No opposing 5s flip first 90s) - Var 3 | Pooled | -14.10 | -699,432 | 0.87 | 27.4% | 1.14 |

### 6. Population B (Bar1 Confirmed Flips) - Yearly Breakdown of Top Add-On Rules
| Add Rule | Year | Total Net $/Trade | Max DD | PF | Win % | Avg Contracts Traded |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Add D (No opposing 5s flip first 90s) - Var 2 | 2021 | -11.56 | -187,332 | 0.90 | 30.5% | 1.14 |
| Add D (No opposing 5s flip first 90s) - Var 2 | 2022 | -10.81 | -148,875 | 0.94 | 31.9% | 1.13 |
| Add D (No opposing 5s flip first 90s) - Var 2 | 2023 | -14.70 | -180,405 | 0.87 | 30.8% | 1.14 |
| Add D (No opposing 5s flip first 90s) - Var 2 | 2024 | -2.91 | -96,388 | 0.98 | 31.3% | 1.14 |
| Add E (Best: No opposing 5s flip first 90s) - Var 1 | 2021 | -12.87 | -196,790 | 0.88 | 30.3% | 1.14 |
| Add E (Best: No opposing 5s flip first 90s) - Var 1 | 2022 | -13.09 | -172,342 | 0.92 | 31.7% | 1.13 |
| Add E (Best: No opposing 5s flip first 90s) - Var 1 | 2023 | -14.99 | -181,705 | 0.86 | 30.4% | 1.14 |
| Add E (Best: No opposing 5s flip first 90s) - Var 1 | 2024 | -6.75 | -123,480 | 0.95 | 30.8% | 1.14 |
| Add E (Best: No opposing 5s flip first 90s) - Var 2 | 2021 | -11.56 | -187,332 | 0.90 | 30.5% | 1.14 |
| Add E (Best: No opposing 5s flip first 90s) - Var 2 | 2022 | -10.81 | -148,875 | 0.94 | 31.9% | 1.13 |
| Add E (Best: No opposing 5s flip first 90s) - Var 2 | 2023 | -14.70 | -180,405 | 0.87 | 30.8% | 1.14 |
| Add E (Best: No opposing 5s flip first 90s) - Var 2 | 2024 | -2.91 | -96,388 | 0.98 | 31.3% | 1.14 |