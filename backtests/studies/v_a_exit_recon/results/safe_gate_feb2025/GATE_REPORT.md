# HH/LL Safe Replay Gate — Feb 2025 RTH

Run: 2026-04-29T02:21:51.918416+00:00

## Configuration

- Rule: `C_lock50_30s_5` (stall_bars=5, lock_pct=0.50, min_mfe_atr=1.0, granularity=30s buckets)
- Framework: `utils/safe_replay`
- fill_model: `conservative_ohlc`
- ohlc_convention: `at_or_worse_close`
- invalid_stop_policy: `market_exit_now`

## Gate Result

- **Audit (impossible fills): PASS** (0 impossible fills)
- **Median diff vs tick-NT: PASS** ($-5.00/trade, threshold ±$5.00)
- WARN: |mean diff| > $5.00 (actual $-14.58)

### **Overall: PASS**

## Audit detail

## Replay Fill Audit

- Total trades audited: 215
- **Impossible fills detected: 0** (PnL contribution: $0.00)

| Flag | Description | Count | PnL contribution |
|---|---|--:|--:|
| exit_outside_bar_ohlc | exit_price is outside [bar.low, bar.high] at exit_ts — phantom fill, not tradable | 0 | $0.00 |
| exit_before_arm | exit_ts < arm_ts — caused by stale arm_ts or bad ordering | 0 | $0.00 |
| stop_invalid_filled_at_stop | stop was invalid at arm (in market) but fill_px == stop_px anyway | 0 | $0.00 |
| exit_reason_overwritten | exit_reason inconsistent with fill mechanics | 0 | $0.00 |
| direction_sign_inconsistent | direction not in {-1, +1} or implied PnL has wrong sign vs (exit_price - fill_price) | 0 | $0.00 |
| protect_not_on_tick_grid | stop_px / protect_px is not a multiple of tick_size | 0 | $0.00 |
| exit_after_max_hold | exit timestamp implausibly far after entry | 0 | $0.00 |

PASS — no impossible fills detected.

## Replay vs tick-NT diff stats

- Matched trades: **215**
- Sum diff (safe - tick): **$-3,135**
- Median diff: **$-5.00/trade**
- Mean diff: **$-14.58/trade**
- Std: $145.40

| Quantile | $/trade |
|---|--:|
| p5 | $-35.00 |
| p25 | $-5.00 |
| p50 | $-5.00 |
| p75 | $-5.00 |
| p95 | $11.50 |

### Stop-invalid-at-arm cases: 56

- mean diff in this subset: $-10.98/trade
- sum: $-615.00

## Per-rule headline economics

- n=215, sum $-6,365, mean $-29.60/trade, median $-25.00/trade, WR 45.6%
- vs baseline (regime exit): sum $7,420, delta $-13,785
