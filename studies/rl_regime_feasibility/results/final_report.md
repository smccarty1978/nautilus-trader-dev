# RL Regime Feasibility Study — Final Report

## Study Design
- **Signal**: 1m regime flip (EMA3/EMA9 on NQ.v.0 1s bars)
- **Observation**: every 5 seconds from flip through episode end
- **Features**: 28 features across 5 families (path, volatility/volume, momentum, multi-TF regime, structural)
- **Horizons**: 5s, 15s, 30s, 60s, 120s, 300s
- **Catastrophic stop**: 1.50 × ATR (from flip close)
- **Episode max duration**: 30 minutes
- **Cost**: $5 RT base commission

## Data Splits
| Period | Dates | Role |
|--------|-------|------|
| Train | 2024-01-01 to 2024-12-31 | Model fitting |
| Validation | 2025-01-01 to 2025-02-28 | Threshold selection |
| Historical test | 2025-03-01 to 2025-05-31 | Gate 2 evaluation |

## Gate 1: Conditional Predictability
**Criterion**: val_AUC >= 0.54 on at least 2 horizons (preliminary screen only)

| Model | Passing horizons (val_AUC >= 0.54) | Best val AUC |
|-------|-----------------------------------|-------------|
| ridge_log | 3/6 (5s=0.5513, 15s=0.5404, 300s=0.5507) | 0.5513 |
| GBM | 6/6 | 0.5634 |

**Verdict**: PASS ✓ (AUC screen) — statistically detectable signal exists at the observation level.

**Note**: AUC > 0.54 is a necessary but not sufficient condition. The economic viability test is Gate 2.

## Gate 2: Causal Policy vs Oracle (Canonical Fixed-Horizon Policy)

**Canonical policy specification:**
- Entry: first observation in episode where `ridge_log_h300_prob >= 0.5024` (threshold frozen on validation)
- Fill: `base__pnl_300s` label at entry row (next 1s open fill)
- Exit: exactly 300s after fill
- Early exits: stop, opposing flip, or episode end only
- Dynamic score exit: prohibited
- Denominator: all 6,669 eligible test episodes (includes flat episodes as 0)

**Oracle test EV**: +167.36/episode (n=6,672 test episodes; clairvoyant ceiling)

**Canonical policy result**:
| Metric | Value |
|--------|-------|
| Eligible test episodes | 6,669 |
| Traded episodes | 1,486 (22.3% trade rate) |
| Total net PnL | -$43,080 |
| **EV / eligible episode** | **-$6.46** |
| EV / traded episode | -$28.99 |
| Win rate | 48.3% |
| Profit factor | 0.83 |
| Max drawdown | $45,560 |

**Gate 2 pass criterion**: best policy EV >= 50% of oracle EV (>= +$83.68/ep)

**Verdict**: FAIL ✗ — best canonical policy EV = -$6.46/ep (-3.9% of oracle)

### Cost Stress
| Scenario | EV/episode |
|----------|-----------|
| Base ($5 RT) | -$6.46 |
| Base + 1 tick | -$7.53 |
| Base + 2 ticks | -$8.70 |

### Monthly Stability (Base Cost)
| Month | EV/trade | Total PnL | Trades |
|-------|----------|-----------|--------|
| 2025-03 | -$18.70 | -$8,695 | 465 |
| 2025-04 | -$50.95 | -$26,035 | 511 |
| 2025-05 | -$16.37 | -$8,350 | 510 |

### Bootstrap 95% CI
(-$12.44, -$0.58) — entirely negative; result is statistically significant.

### Control Audits
| Control | EV/episode |
|---------|-----------|
| Label-shuffle | -$1.66 (near-zero as expected) |
| 10s time-shift | -$5.20 |

## Policy Comparison (Two Code Paths)

A separate simulation (`causal_policy.py`) that used a **dynamic probability exit** produced +$23.97/ep. This is not the canonical result:

| Dimension | `causal_policy.py` | Canonical (`run_reconstruction.py`) |
|---|---|---|
| Entry | Step 0 only, Youden J thr=0.420 | First crossing, val-optimized thr=0.5024 |
| Exit | Dynamic: exits when prob drops below 0.420 | Fixed 300s; stop/flip/ep_end only |
| Dynamic score exit | YES | NO (prohibited) |
| Result | +$23.97/ep | -$6.46/ep |

The $30/ep gap is from the dynamic exit acting as an ML-driven stop: when model confidence drops in the first 30-60s, the trade exits early. This exploits the model's ongoing predictions rather than isolating the entry signal, and was not the policy under evaluation.

## RL Recommendation

**DO NOT PROCEED** with RL/PPO/DQN on this OHLCV state space.

- Observation-level predictability exists (AUC 0.54-0.56 range), but it is not actionable with a fixed-horizon entry policy
- Canonical policy loses -$6.46/episode on test — every cost scenario is negative
- Monthly stability: every month negative, April severely so
- Bootstrap CI entirely negative: not noise, it's signal in the wrong direction
- The oracle ceiling (+$167/ep) confirms the market does move favorably after many flips; the problem is the OHLCV features cannot identify which ones

**Next step**: order flow / footprint data as additional feature families, or orderbook microstructure features, before revisiting RL feasibility.

## Key Caveats
- Models trained on OHLCV-derived features only; no order flow
- Bar execution mode (1s bar open fills) may overstate slightly vs tick execution
- Regime-capped labels assume exact flip-time exit; real exit has 5s delay
- Canonical policy uses `forward_labels.parquet` 300s label which includes stop/ep_end early exit in the label itself
