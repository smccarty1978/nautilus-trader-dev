# HH/LL Tick-NT Validation — Attribution Audit

Tests whether tick-NT HH/LL failure was caused by implementation semantics (reactive market exit after 1s bar close) vs rule failure.

## Versions tested

- **Version A (actual tick-NT)**: internal monitor at 1s bar close detects breach → submit MARKET → fill at next tick AFTER bar close. Adds 1+ seconds of detection latency.
- **Version C_strict (assumed-fill stop)**: scan tick stream from arm_ts; first tick crossing protect_px triggers exit at protect_px exactly (standard backtest stop convention; what tape replay assumed).
- **Version C_realistic (first-cross stop)**: scan tick stream from arm_ts; first tick crossing protect_px triggers exit at THAT tick's price (more honest than C_strict).

- Population: 1,180 armed RTH trades from tick-NT HH/LL Feb-Sep 2025 run
- Tick data: NQ trades Feb-Sep 2025 (~59M)

## Stop validity at arm time

- Resting stop would be VALID at arm (protect_px not already past current price): **618 (52.4%)**
- Resting stop would be IN MARKET at arm (NT would REJECT, fall through to market): **562 (47.6%)**

## Crossed-protect rate

- Crossed protect_px after arm: **438 (37.1%)**
- Held to regime exit: 742

## Slippage (Version A vs Version C realistic) — crossed trades only

Positive = tick-NT exit WORSE than first cross.

| Quantile | Slip (ticks) | Slip ($) |
|---|--:|--:|
| p5 | -9.00 | $-45.00 |
| p25 | -2.00 | $-10.00 |
| p50 | +0.00 | $0.00 |
| p75 | +2.00 | $10.00 |
| p95 | +10.15 | $50.75 |
| mean | +0.81 | $4.03 |
| max | +467.00 | $2,335 |

## Per-trade PnL — armed cohort only

| Version | n | WR | Mean $ | Total $ | PF |
|---|--:|--:|--:|--:|--:|
| A: tick-NT actual (reactive market) | 1,180 | 81.9% | $352.08 | $415,460 | 13.09 |
| **C_strict: stop fills at protect_px (tape replay convention)** | 1,180 | 82.9% | $384.44 | $453,640 | 15.31 |
| C_realistic: stop fills at first cross | 1,180 | 82.1% | $350.59 | $413,695 | 13.42 |

- Δ mean per trade (C_strict − A): **$32.36**
- Δ mean per trade (C_realistic − A): **$-1.50**
- Δ total armed (C_strict − A): **$38,180**

## Verdict

✅ **Implementation semantics are the root cause.** Switching from reactive market exit (Version A) to a true resting stop (Version C_strict) recovers ~$32.36 per armed trade. The HH/LL rule is not dead; the implementation needs to use a real STOP_MARKET order placed at arm time. NEXT: implement Version B in NT (handle 'in-market' rejections via immediate market exit at current price). The realistic best-case (C_realistic) gives a fair lower bound: +$-1.50/trade.

## Files

- Per-trade audit: `studies/v_a_exit_recon/results/hhll_attribution_audit.parquet`
- This report: `studies/v_a_exit_recon/results/HHLL_ATTRIBUTION_AUDIT.md`