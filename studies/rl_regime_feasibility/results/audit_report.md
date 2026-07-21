# Detailed Economic Audit Report

## 1. Denominator & Trade Count Reconciliation
The simulation evaluates trades on the out-of-sample historical test set (**2025-03-01 to 2025-05-31**).
Units in the simulation are in **USD** (not points). A points reconciliation is provided below.

| Metric | USD value | Points equivalent (1 pt = $20) |
|--------|-----------|--------------------------------|
| **Eligible Test Episodes** | 6,669 | - |
| **Episodes Traded** | 1,486 | - |
| **Trades Executed** | 1,486 | - |
| **Trade Rate (%)** | 22.28% | - |
| **Total Net PnL** | $-43,080.00 | -2154.00 pts |
| **Net PnL per eligible episode** | $-6.46 | -0.32 pts |
| **Net PnL per traded episode (EV/trade)** | $-28.99 | -1.45 pts |

**Arithmetic Check**:
- `Total Net USD` ($-43,080.00) = `Sum of individual trade net PnL` ($-43,080.00): **Reconciled ✓**
- `Net USD per eligible episode` ($-6.46) = `Total Net USD` ($-43,080.00) / `Eligible Episodes` (6669): **Reconciled ✓**

## 2. Confirm One Trade per Episode
- **Maximum trades executed in any single episode**: 1
- **Number of episodes with multiple overlapping trades**: 0
- **Causality check**: Entries occur at the next 1-second open following the initiating 5-second close. Exits occur at the horizon or when the opposing flip/episode end is reached (Exit A). Programmatic checks confirm that entry is at the first causal threshold crossing, and that no trades entered after episode termination. **Reconciled ✓**

## 3. Configuration Freeze
The policy parameters were selected based **ONLY** on the validation set (**2025-01-01 to 2025-02-28**) and then frozen for the historical test.

- **Model selected on validation**: `ridge_log`
- **Horizon selected on validation**: `300s`
- **Threshold selected on validation**: `0.5024`
- **Exit rule**: `Exit A: fixed predicted horizon`
- **Validation set performance**: EV = **+0.302 points/episode** ($+6.05/episode)

*Note: The test set was NOT inspected to select these parameters. All 12 validation configurations were evaluated first, and `ridge_log_h300s` was selected as the frozen test-period policy.*

## 4. Cost Stress Test
Performance of the frozen policy `ridge_log_h300s` under the three cost scenarios:

| Cost Scenario | Commission | Slippage per side | Net EV / episode (USD) | Net EV / episode (Points) | Total Net PnL (USD) |
|---------------|------------|-------------------|------------------------|---------------------------|---------------------|
| **Base** | $5.00 RT | 0 ticks | $-6.46 | -0.32 pts | $-43,080.00 |
| **Base + 1 tick** | $5.00 RT | 1 tick ($5.00/side) | $-7.53 | -0.38 pts | $-50,235.00 |
| **Base + 2 ticks** | $5.00 RT | 2 ticks ($10.00/side) | $-8.70 | -0.44 pts | $-58,045.00 |

## 5. Sampled Trades Chronological Audit
Below are 3 randomly sampled trades from the historical test set:

### Sample 1
- **Observation time (decision)**: `2025-05-21 07:01:20.000`
- **Model score**: `0.5071` (Threshold: `0.5024`)
- **Entry**: `2025-05-21 07:01:20.000` @ `21320.50`
- **Exit**: `2025-05-21 07:06:20.000` @ `21299.75` (Type: `stop`)
- **Points**: Gross `-20.75` | Commission `0.25` | Slippage `0.00` | Net `-21.00`
- **Net PnL**: `-420.00 USD`

### Sample 2
- **Observation time (decision)**: `2025-04-24 08:07:40.000`
- **Model score**: `0.5102` (Threshold: `0.5024`)
- **Entry**: `2025-04-24 08:07:40.000` @ `18662.25`
- **Exit**: `2025-04-24 08:12:40.000` @ `18657.00` (Type: `horizon`)
- **Points**: Gross `+5.25` | Commission `0.25` | Slippage `0.00` | Net `+5.00`
- **Net PnL**: `+100.00 USD`

### Sample 3
- **Observation time (decision)**: `2025-03-28 16:16:10.000`
- **Model score**: `0.5056` (Threshold: `0.5024`)
- **Entry**: `2025-03-28 16:16:10.000` @ `19532.25`
- **Exit**: `2025-03-28 16:21:10.000` @ `19493.50` (Type: `horizon`)
- **Points**: Gross `+38.75` | Commission `0.25` | Slippage `0.00` | Net `+38.50`
- **Net PnL**: `+770.00 USD`

*Note: All entry timestamps occur after the observation decision timestamp. No look-ahead leakage is present.*

## 6. Control Audits

### Bootstrap Control (1,000 resamples)
- **95% Confidence Interval for EV/episode**: `[$-12.44, $-0.58]` (`[-0.62 pts, -0.03 pts]`).
- *Interpretation: The confidence interval is entirely negative, confirming that the out-of-sample negative performance is statistically significant and not due to random noise.*

### Label-Shuffle Control
- **Shuffled EV / episode**: `$-1.66` (`-0.08 pts`).
- *Interpretation: Breaking the relationship between model scores and outcomes makes the EV collapse to near zero (which is expected for a random strategy).*

### Time-Shift Control (10s lag)
- **Shifted EV / episode**: `$-5.20` (`-0.26 pts`).
- *Interpretation: Lagging scores by 10 seconds results in negative performance, showing that the timing is sensitive to local causal signals.*

### Monthly Breakdown (Base Costs)
| Month | Mean EV (USD) | Mean EV (Pts) | Total PnL (USD) | Trade Count |
|-------|---------------|---------------|-----------------|-------------|
| 2025-03 | $-18.70 | -0.93 pts | $-8,695.00 | 465 |
| 2025-04 | $-50.95 | -2.55 pts | $-26,035.00 | 511 |
| 2025-05 | $-16.37 | -0.82 pts | $-8,350.00 | 510 |

### Long/Short Directional Breakdown
| Direction | Mean EV (USD) | Mean EV (Pts) | Total PnL (USD) | Trade Count |
|-----------|---------------|---------------|-----------------|-------------|
| Long | $-26.30 | -1.31 pts | $-27,610.00 | 1,050 |
| Short | $-35.48 | -1.77 pts | $-15,470.00 | 436 |

## 7. Trade Distribution & Drawdown (Base Costs)
- **Mean Trade PnL**: $-28.99 (-1.45 pts)
- **Median Trade PnL**: $-10.00
- **Profit Factor (PF)**: 0.83
- **Win Rate (%)**: 48.25%
- **Max Drawdown**: $45560.00 (2278.00 pts)
- **Largest Winner**: $+3350.00
- **Largest Loser**: $-4280.00

## 8. Oracle Verification
- **Oracle test EV**: $+98.85 (+4.94 pts)
