# Regime Flip Truth — Summary Report

Descriptive only. No ML, no optimization, no parameter search. All metrics are 1s-precision path outcomes from entry to the next opposite 1m regime flip. Features are causal entry snapshots.

**Universe:** NQ `NQ.v.0`, 2021–2024, 24h Globex (events tagged `rth_flag`). Catalog `NQ_v0_2020_2026` (safe `closed='left'` build).

## 1. Population sizes

| pop | n_total | n_warmed | rth_share |
| --- | --- | --- | --- |
| A (raw flip) | 110,507 | 110,507 | 27% |
| B (bar1-confirmed) | 47,068 | 47,068 | 29% |


Warmup-gated (`warmed_up`) events are used for all rate/feature stats below. Total raw events across years: 157,575.

Per-year warmed counts:

| year | A | B |
| --- | --- | --- |
| 2021 | 27825 | 11625 |
| 2022 | 27138 | 11825 |
| 2023 | 28029 | 11788 |
| 2024 | 27515 | 11830 |


## 2. Outcome distribution — milestone reach rates

Share of events whose MFE reached each ATR multiple before the regime ended.

| population | n | 0.5 ATR | 1.0 ATR | 2.0 ATR | 3.0 ATR |
| --- | --- | --- | --- | --- | --- |
| A | 110,507 | 75.2% | 59.2% | 38.3% | 25.7% |
| B | 47,068 | 76.4% | 60.9% | 40.1% | 26.9% |


By session (Population A):

| session | n | 0.5 ATR | 1.0 ATR | 2.0 ATR | 3.0 ATR |
| --- | --- | --- | --- | --- | --- |
| RTH | 29,434 | 77.3% | 60.8% | 39.2% | 25.8% |
| Overnight | 81,073 | 74.4% | 58.6% | 38.0% | 25.6% |


## 3. Path-quality distribution

Clean Trend A: MFE≥2 & MAE≤0.75 ATR. Clean Trend B: MFE≥3 & MAE≤1. Persistent: duration≥15 bars. Elite: persistent & MFE≥2 & MAE≤0.75.

| population | n | clean_trend_a | clean_trend_b | persistent_trend | elite_trend | median_dur_bars | mean_term_pnl_atr |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A | 110,507 | 22.4% | 19.3% | 32.2% | 15.4% | 9 | -0.05 |
| B | 47,068 | 22.3% | 19.5% | 35.3% | 16.0% | 10 | -0.03 |


Per-year Elite rate (Population A / B):

| year | A | B |
| --- | --- | --- |
| 2021 | 14.8% | 15.2% |
| 2022 | 16.1% | 16.7% |
| 2023 | 14.9% | 16.0% |
| 2024 | 15.6% | 16.1% |


## 4. Feature separation — Elite vs non-Elite

Cohen's d on causal ENTRY features (positive d ⇒ higher in Elite). `decile_lo/hi` = Elite rate in the bottom/top feature decile; `monotonic` = |corr(decile, rate)| ≥ 0.8. Pooled Population A+B warmed.

| feature | cohens_d | pos_mean | neg_mean | decile_lo | decile_hi | decile_spread | monotonic |
| --- | --- | --- | --- | --- | --- | --- | --- |
| atr_1m | +0.091 | +6.448 | +6.012 | 12.8% | 17.9% | +5.1% | yes |
| rv_recent_20m | +0.080 | +0.000 | +0.000 | 13.0% | 17.7% | +4.7% | yes |
| rv_30m | +0.076 | +0.000 | +0.000 | 13.0% | 17.6% | +4.6% | yes |
| rv_5m | +0.073 | +0.000 | +0.000 | 13.7% | 17.6% | +4.0% | yes |
| bb_bandwidth | +0.072 | +0.002 | +0.002 | 13.1% | 17.5% | +4.3% | yes |
| vol_30m | +0.072 | +13027.125 | +11826.172 | 13.2% | 17.3% | +4.2% | yes |
| vol_5m | +0.065 | +2134.625 | +1939.515 | 12.8% | 17.6% | +4.8% | yes |
| atr_pctile | +0.064 | +0.534 | +0.513 | 13.8% | 16.4% | +2.6% | yes |
| vol_1m | +0.061 | +527.218 | +478.365 | 13.0% | 17.3% | +4.3% | yes |
| vol_pctile | +0.057 | +0.596 | +0.578 | 14.3% | 16.0% | +1.7% | yes |
| bb_position | +0.055 | +0.512 | +0.495 | 14.1% | 16.7% | +2.7% | yes |
| price_velocity | +0.055 | +0.091 | +0.085 | 14.6% | 17.5% | +2.9% | yes |
| keltner_dist_upper_atr | -0.055 | +1.461 | +1.517 | 16.4% | 14.0% | -2.4% | yes |
| bb_dist_lower_atr | +0.053 | +1.926 | +1.860 | 14.1% | 16.7% | +2.6% | yes |
| keltner_position | +0.051 | +0.515 | +0.498 | 14.0% | 16.4% | +2.4% | yes |
| keltner_dist_lower_atr | +0.049 | +1.555 | +1.506 | 14.1% | 16.3% | +2.2% | yes |
| sma9_slope | -0.039 | -0.285 | -0.253 | 17.5% | 16.4% | -1.2% | no |
| alignnum_5m | -0.037 | -0.203 | -0.167 | — | — | — | no |
| keltner_width_atr | -0.036 | +3.017 | +3.023 | 16.0% | 14.1% | -1.9% | yes |
| bb_dist_upper_atr | -0.036 | +1.851 | +1.896 | 16.8% | 15.3% | -1.5% | yes |
| sma13_slope | -0.033 | -0.312 | -0.286 | 17.4% | 16.1% | -1.2% | no |
| ret_30s_atr | -0.028 | +0.389 | +0.402 | 15.9% | 14.6% | -1.3% | no |
| ema50_dist_atr | -0.026 | +0.506 | +0.544 | 15.9% | 14.7% | -1.3% | no |
| vol_acceleration | +0.024 | +121.103 | +110.029 | 16.8% | 16.7% | -0.1% | no |
| ema21_slope | -0.021 | -0.149 | -0.138 | 17.3% | 16.5% | -0.8% | no |


Max |Cohen's d| = 0.091. As a yardstick: |d|<0.2 negligible, 0.2–0.5 small, 0.5–0.8 medium, >0.8 large.

Top-10 separators for **Clean Trend A**:

| feature | cohens_d | decile_lo | decile_hi | monotonic |
| --- | --- | --- | --- | --- |
| vol_pctile | +0.038 | 20.7% | 22.1% | no |
| atr_1m | +0.037 | 21.2% | 23.8% | yes |
| atr_pctile | +0.035 | 21.1% | 22.6% | no |
| sma13_dist_atr | -0.032 | 22.6% | 21.0% | no |
| sma9_slope | -0.031 | 24.1% | 22.2% | no |
| rv_5m | +0.030 | 21.6% | 23.6% | yes |
| rv_recent_20m | +0.027 | 21.2% | 23.5% | yes |
| alignnum_5m | -0.025 | — | — | no |
| sma9_dist_atr | -0.025 | 22.7% | 21.2% | no |
| ema13_dist_atr | -0.025 | 21.7% | 21.1% | no |


Top-10 separators for **Persistent Trend**:

| feature | cohens_d | decile_lo | decile_hi | monotonic |
| --- | --- | --- | --- | --- |
| ema9_dist_atr | +0.171 | 28.7% | 41.1% | yes |
| sma9_dist_atr | +0.164 | 29.4% | 41.1% | yes |
| ema13_dist_atr | +0.161 | 29.5% | 41.2% | yes |
| sma13_dist_atr | +0.155 | 29.8% | 41.0% | yes |
| ret_120s_atr | +0.145 | 29.6% | 40.1% | yes |
| ema21_dist_atr | +0.127 | 30.8% | 40.1% | yes |
| sma21_dist_atr | +0.126 | 30.9% | 40.1% | yes |
| ret_300s_atr | +0.126 | 30.9% | 40.1% | yes |
| price_velocity | +0.115 | 29.2% | 38.3% | yes |
| rv_5m | +0.111 | 28.0% | 37.9% | yes |


## 5. Can we recognize Elite EARLY?

Cohen's d at each checkpoint for `cur_mfe_atr`, `cur_pnl_atr`, `path_efficiency` between events that EVENTUALLY become Elite vs not. Larger |d| earlier ⇒ recognizable sooner. (Warmed Population A+B.)

| checkpoint | n | cur_mfe_atr | cur_pnl_atr | path_efficiency |
| --- | --- | --- | --- | --- |
| entry | 157,575 | — | — | — |
| +30s | 157,575 | +0.24 | +0.36 | +0.64 |
| +60s | 157,575 | +0.36 | +0.51 | +0.83 |
| +90s | 157,575 | +0.47 | +0.65 | +0.95 |
| +120s | 157,575 | +0.54 | +0.73 | +1.01 |
| +180s | 157,575 | +0.66 | +0.87 | +1.06 |
| Bar2 | 157,575 | +0.54 | +0.73 | +1.01 |
| Bar3 | 157,575 | +0.66 | +0.87 | +1.06 |
| Bar5 | 157,575 | +0.86 | +1.08 | +1.10 |


## 6. Caveats

- This is a TRUTH dataset, not a strategy. Terminal PnL is measured to the next opposite 1m flip at that bar's close — not an executable exit (no spread, slippage, or fill mechanics). Do not read PnL columns as tradeable edge.

- Labels (Elite etc.) use the FULL forward path; they are outcomes, not signals. Section 4 quantifies whether ENTRY features separate them; Section 5 whether EARLY-path state separates them.

- `mfe_atr`/`mae_atr` are signed: a negative MAE means the trade never traded against entry (rare, short regimes); negative MFE means it never traded favorably. Both are real, ~2% of events.

- No ML was used. Cohen's d / deciles are univariate; they do not capture interactions. A small univariate |d| does not preclude a multivariate signal — but a large univariate separation is the cheapest evidence of a real, early-recognizable distinction.


## 7. Time-to-reach +2 ATR and the drawdown trade-off

Exact `t_reach_2_0_atr_s` (61,214 reachers = 38.8% of warmed events).

**Time to first touch +2 ATR (from entry):** median **5.5 min** (330s), mean 13.2 min.
p10 1.4m · p25 2.9m · p75 9.5m · p90 14.2m · p95 18.1m. It is a slow grind:
only 5% reach +2 ATR within 1 min, 16% within 2 min, 45% within 5 min, 77%
within 10 min, 23% take >10 min.

**Drawdown scales with hold time (Spearman +0.53).** The longer a trade takes to
reach +2 ATR, the more heat it eats getting there:

| time-to-+2ATR | share | median DD before +2 | p90 DD |
|---|---|---|---|
| <=30s | 2% | 0.05 ATR | 0.42 |
| 30-60s | 3% | 0.11 | 0.51 |
| 1-2m | 10% | 0.18 | 0.68 |
| 2-3m | 10% | 0.28 | 0.85 |
| 3-5m | 19% | 0.41 | 1.07 |
| 5-10m | 32% | 0.65 | 1.41 |
| >10m | 23% | 0.93 | 1.82 |

The cheap, fast reaches (~0.4 ATR stop room) are a small minority (5% under 1 min).
The bulk (5-10 min) and slow (>10 min) reaches need 1.4-1.8 ATR of room at p90.
Since entry features cannot predict which bucket a trade lands in (Section 4,
|d|<=0.09), a stop sized to capture most +2 ATR reaches must budget ~1.5 ATR.

**Milestone ladder (median time / population reached):** 0.5 ATR 52s (76%) ->
1.0 ATR 2.3m (60%) -> 2.0 ATR 5.5m (39%) -> 3.0 ATR 8.6m (26%). Each additional
ATR of favorable excursion roughly doubles the wait and sheds ~15-20pp of events.
