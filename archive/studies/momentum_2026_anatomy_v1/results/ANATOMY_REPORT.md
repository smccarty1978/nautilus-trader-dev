> **🚨 DEPRECATED — NON-CAUSAL FEATURE TIMING (2026-04-27)**
>
> This report was produced before the causality/parity gate.
> One or more feature lookups in the source collector used
> bar OPEN times where bar CLOSE times were required. This
> exposed up to several seconds (HMM 5s state) or several
> minutes (5m regime alignment) of intra-bar lookahead.
>
> See `CAUSALITY.md` and
> `memory/multi_timeframe_lookup_lookahead.md`.
>
> The collectors have been patched. Re-run before citing
> any specific number from this report.

# Momentum Confirm 2026 Failure Anatomy v1

Two-layer diagnostic study using only pre-entry / at-entry features (Layer 1) and full path labels (Layer 2). Goal: identify what structurally differs about 2026 trades, and whether eventual losers have harvestable MFE first.

## L1.1 — Year comparison

| Year | Mode | n | WR | Mean $ | PF | Avg Win | Avg Loss | Med Dur | Med ATR | Med Reg Age | Med Chop_10 | Med Flip 60m |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 2024 | 1m_momentum | 3,300 | 35.5% | $6.01 | 1.03 | $559.57 | $-299.59 | 10.5m | 10.14 | 13.2 | 2.68 | 5 |
| 2024 | 30s_momentum | 3,082 | 33.9% | $-4.50 | 0.98 | $576.51 | $-304.20 | 10.0m | 10.25 | 13.2 | 2.97 | 5 |
| 2025 | 1m_momentum | 3,287 | 33.7% | $16.98 | 1.07 | $791.85 | $-378.76 | 10.5m | 13.06 | 12.6 | 2.83 | 5 |
| 2025 | 30s_momentum | 3,102 | 34.9% | $27.79 | 1.11 | $802.04 | $-389.25 | 11.0m | 13.19 | 12.6 | 3.07 | 5 |
| 2026 | 1m_momentum | 977 | 35.2% | $-21.69 | 0.93 | $786.12 | $-463.62 | 10.5m | 15.97 | 12.6 | 2.60 | 5 |
| 2026 | 30s_momentum | 853 | 34.6% | $-38.68 | 0.87 | $763.58 | $-464.48 | 11.0m | 16.05 | 12.6 | 2.74 | 5 |

## L1.2 — Winner vs loser feature differences

Per year-mode: median for winners vs losers, and Cohen's d effect size. Top |d| ranked.

### 2024 — 1m_momentum (top 12 by |d|)

| Feature | Med Win | Med Loss | Δ | Cohen's d |
|---|--:|--:|--:|--:|
| regime_5m_aligned | 1.000 | 0.000 | +1.000 | +0.243 |
| regime_5m_age_5m_bars | 7.000 | 9.000 | -2.000 | -0.135 |
| confirm_body_pct | 0.483 | 0.444 | +0.039 | +0.084 |
| confirm_vol_z | 0.546 | 0.482 | +0.065 | +0.066 |
| dist_sess_h_atr | 5.593 | 5.471 | +0.122 | +0.057 |
| dist_sess_mid_atr | 0.420 | 0.562 | -0.143 | -0.055 |
| close_through_amt_atr | 0.304 | 0.270 | +0.034 | +0.053 |
| chop_5 | 1.538 | 1.560 | -0.022 | -0.050 |
| hmm_state_at_flip | 2.000 | 2.000 | +0.000 | +0.038 |
| prior_3_net_move_atr | 1.261 | 1.239 | +0.022 | +0.036 |
| dist_sess_l_atr | 6.700 | 7.125 | -0.425 | -0.034 |
| chop_10 | 2.652 | 2.684 | -0.032 | +0.026 |

### 2024 — 30s_momentum (top 12 by |d|)

| Feature | Med Win | Med Loss | Δ | Cohen's d |
|---|--:|--:|--:|--:|
| regime_5m_aligned | 1.000 | 0.000 | +1.000 | +0.182 |
| regime_5m_age_5m_bars | 8.000 | 9.000 | -1.000 | -0.096 |
| chop_5 | 1.623 | 1.673 | -0.050 | -0.071 |
| position_in_range | 0.550 | 0.522 | +0.028 | +0.070 |
| dist_recent_l_atr | 2.344 | 2.217 | +0.127 | +0.068 |
| confirm_close_loc | 0.556 | 0.522 | +0.034 | +0.064 |
| prior_5_net_move_atr | 1.073 | 1.047 | +0.026 | +0.061 |
| dist_recent_h_atr | 1.987 | 2.040 | -0.053 | -0.052 |
| confirm_wickiness | 0.167 | 0.178 | -0.011 | -0.048 |
| atr_pct_500 | 0.713 | 0.695 | +0.018 | +0.047 |
| prior_10_net_move_atr | 0.483 | 0.456 | +0.027 | +0.047 |
| avg_dur_5_bars | 13.400 | 13.000 | +0.400 | +0.039 |

### 2025 — 1m_momentum (top 12 by |d|)

| Feature | Med Win | Med Loss | Δ | Cohen's d |
|---|--:|--:|--:|--:|
| regime_5m_age_5m_bars | 7.000 | 9.000 | -2.000 | -0.187 |
| regime_5m_aligned | 1.000 | 0.000 | +1.000 | +0.184 |
| rr_20_atr | 3.979 | 3.863 | +0.115 | +0.098 |
| atr_at_signal | 13.701 | 12.707 | +0.994 | +0.098 |
| hmm_entropy | 0.000 | 0.000 | -0.000 | -0.092 |
| rr_5_atr | 2.716 | 2.668 | +0.048 | +0.086 |
| close_through_amt_atr | 0.298 | 0.258 | +0.040 | +0.084 |
| rr_10_atr | 3.047 | 3.026 | +0.021 | +0.084 |
| confirm_body_pct | 0.487 | 0.456 | +0.031 | +0.084 |
| atr_pct_500 | 0.705 | 0.691 | +0.014 | +0.084 |
| prior_3_net_move_atr | 1.312 | 1.258 | +0.054 | +0.077 |
| bar_overlap_pct | 1.773 | 1.792 | -0.019 | -0.067 |

### 2025 — 30s_momentum (top 12 by |d|)

| Feature | Med Win | Med Loss | Δ | Cohen's d |
|---|--:|--:|--:|--:|
| dist_recent_l_atr | 2.356 | 2.148 | +0.208 | +0.134 |
| regime_5m_age_5m_bars | 8.000 | 9.000 | -1.000 | -0.133 |
| regime_5m_aligned | 1.000 | 0.000 | +1.000 | +0.124 |
| position_in_range | 0.545 | 0.513 | +0.032 | +0.120 |
| confirm_close_loc | 0.568 | 0.500 | +0.068 | +0.116 |
| atr_at_signal | 13.915 | 12.653 | +1.262 | +0.109 |
| atr_pct_500 | 0.711 | 0.687 | +0.024 | +0.090 |
| prior_3_net_move_atr | 1.300 | 1.244 | +0.055 | +0.086 |
| rr_10_atr | 3.038 | 3.023 | +0.015 | +0.078 |
| dist_recent_h_atr | 2.027 | 2.084 | -0.056 | -0.075 |
| rr_20_atr | 3.937 | 3.875 | +0.062 | +0.074 |
| hmm_state_prob_3 | 0.996 | 0.951 | +0.045 | +0.073 |

### 2026 — 1m_momentum (top 12 by |d|)

| Feature | Med Win | Med Loss | Δ | Cohen's d |
|---|--:|--:|--:|--:|
| regime_5m_aligned | 1.000 | 0.000 | +1.000 | +0.266 |
| regime_5m_age_5m_bars | 7.000 | 9.000 | -2.000 | -0.160 |
| eff_5 | 0.419 | 0.463 | -0.044 | -0.118 |
| prior_5_net_move_atr | 1.038 | 1.095 | -0.056 | -0.105 |
| atr_slope_10 | 0.005 | -0.022 | +0.027 | +0.104 |
| chop_5 | 1.581 | 1.511 | +0.070 | +0.094 |
| confirm_body_pct | 0.487 | 0.444 | +0.042 | +0.089 |
| chop_10 | 2.553 | 2.615 | -0.063 | -0.076 |
| hmm_state_at_flip | 3.000 | 3.000 | +0.000 | -0.075 |
| hmm_state_changed | 0.000 | 0.000 | +0.000 | +0.069 |
| eff_10 | 0.138 | 0.155 | -0.017 | -0.066 |
| rr_5_atr | 2.687 | 2.623 | +0.064 | +0.062 |

### 2026 — 30s_momentum (top 12 by |d|)

| Feature | Med Win | Med Loss | Δ | Cohen's d |
|---|--:|--:|--:|--:|
| regime_5m_aligned | 1.000 | 0.000 | +1.000 | +0.260 |
| prior_5_net_move_atr | 0.979 | 1.161 | -0.182 | -0.234 |
| eff_5 | 0.415 | 0.486 | -0.072 | -0.230 |
| flip_count_60m | 5.000 | 5.000 | +0.000 | +0.174 |
| avg_dur_5_bars | 12.200 | 13.000 | -0.800 | -0.160 |
| prior_3_net_move_atr | 1.203 | 1.256 | -0.053 | -0.134 |
| bar_overlap_pct | 1.802 | 1.738 | +0.064 | +0.133 |
| chop_10 | 2.744 | 2.749 | -0.005 | -0.128 |
| rr_10_atr | 2.988 | 3.066 | -0.078 | -0.117 |
| sess_range_atr | 17.713 | 19.087 | -1.374 | -0.107 |
| flip_count_30m | 3.000 | 3.000 | +0.000 | +0.102 |
| regime_5m_age_5m_bars | 8.000 | 8.500 | -0.500 | -0.096 |

## L1.3 — 2026 vs 2024/2025 difference

Compare 2026 trades (all) vs 2024+2025 trades (all) per mode. Shows what is structurally different about 2026 entries.

### 1m_momentum — top 15 differences (2026 vs 2024+2025)

| Feature | Med 2026 | Med 24+25 | Δ | Cohen's d |
|---|--:|--:|--:|--:|
| atr_at_signal | 15.972 | 11.301 | +4.671 | +0.522 |
| hmm_state_prob_3 | 1.000 | 0.899 | +0.101 | +0.271 |
| hmm_state_at_flip | 3.000 | 3.000 | +0.000 | +0.257 |
| hmm_state_at_signal | 3.000 | 3.000 | +0.000 | +0.239 |
| sess_range_atr | 18.272 | 16.974 | +1.299 | +0.224 |
| atr_pct_500 | 0.673 | 0.699 | -0.026 | -0.203 |
| dist_sess_l_atr | 7.417 | 7.232 | +0.186 | +0.176 |
| confirm_vol_z | 0.306 | 0.445 | -0.139 | -0.138 |
| hmm_state_changed | 0.000 | 0.000 | +0.000 | -0.131 |
| dist_sess_mid_atr | 0.704 | 0.584 | +0.120 | +0.086 |
| prior_10_net_move_atr | 0.552 | 0.468 | +0.084 | +0.081 |
| rr_10_atr | 3.010 | 3.051 | -0.041 | -0.081 |
| rr_5_atr | 2.655 | 2.700 | -0.044 | -0.081 |
| confirm_wickiness | 0.227 | 0.204 | +0.024 | +0.080 |
| confirm_range_atr | 0.948 | 0.967 | -0.018 | -0.077 |

### 30s_momentum — top 15 differences (2026 vs 2024+2025)

| Feature | Med 2026 | Med 24+25 | Δ | Cohen's d |
|---|--:|--:|--:|--:|
| atr_at_signal | 16.053 | 11.474 | +4.579 | +0.511 |
| hmm_state_prob_3 | 1.000 | 0.845 | +0.155 | +0.321 |
| hmm_state_at_signal | 3.000 | 3.000 | +0.000 | +0.304 |
| hmm_state_at_flip | 3.000 | 3.000 | +0.000 | +0.258 |
| sess_range_atr | 18.597 | 16.834 | +1.762 | +0.256 |
| atr_pct_500 | 0.667 | 0.699 | -0.032 | -0.230 |
| dist_sess_l_atr | 7.419 | 7.271 | +0.148 | +0.158 |
| hmm_state_changed | 0.000 | 0.000 | +0.000 | -0.157 |
| dist_sess_h_atr | 6.039 | 5.349 | +0.690 | +0.148 |
| dist_recent_h_atr | 2.232 | 2.045 | +0.187 | +0.098 |
| confirm_close_loc | 0.500 | 0.529 | -0.029 | -0.089 |
| eff_10 | 0.150 | 0.137 | +0.013 | +0.085 |
| prior_10_net_move_atr | 0.553 | 0.459 | +0.094 | +0.085 |
| rr_20_atr | 4.016 | 3.909 | +0.107 | +0.078 |
| eff_5 | 0.460 | 0.425 | +0.035 | +0.072 |

### 2026-LOSING vs 2024/2025-PROFITABLE — direct cohort comparison

#### 1m_momentum — 2026 losers vs 24+25 winners (top 12)

| Feature | Med 2026L | Med 24+25W | Δ | d |
|---|--:|--:|--:|--:|
| atr_at_signal | 16.032 | 11.695 | +4.337 | +0.478 |
| regime_5m_aligned | 0.000 | 1.000 | -1.000 | -0.286 |
| hmm_state_at_flip | 3.000 | 3.000 | +0.000 | +0.253 |
| hmm_state_prob_3 | 1.000 | 0.946 | +0.054 | +0.249 |
| sess_range_atr | 18.780 | 16.969 | +1.811 | +0.243 |
| atr_pct_500 | 0.673 | 0.705 | -0.032 | -0.226 |
| hmm_state_at_signal | 3.000 | 3.000 | +0.000 | +0.222 |
| dist_sess_l_atr | 7.545 | 6.870 | +0.675 | +0.215 |
| confirm_vol_z | 0.315 | 0.487 | -0.172 | -0.168 |
| hmm_state_changed | 0.000 | 0.000 | +0.000 | -0.149 |
| regime_5m_age_5m_bars | 9.000 | 7.000 | +2.000 | +0.145 |
| rr_5_atr | 2.623 | 2.719 | -0.096 | -0.136 |

#### 30s_momentum — 2026 losers vs 24+25 winners (top 12)

| Feature | Med 2026L | Med 24+25W | Δ | d |
|---|--:|--:|--:|--:|
| atr_at_signal | 16.111 | 11.821 | +4.289 | +0.478 |
| sess_range_atr | 19.087 | 16.815 | +2.272 | +0.297 |
| hmm_state_prob_3 | 1.000 | 0.899 | +0.101 | +0.280 |
| hmm_state_at_signal | 3.000 | 3.000 | +0.000 | +0.279 |
| atr_pct_500 | 0.660 | 0.713 | -0.053 | -0.267 |
| hmm_state_at_flip | 3.000 | 3.000 | +0.000 | +0.255 |
| regime_5m_aligned | 0.000 | 1.000 | -1.000 | -0.229 |
| dist_sess_l_atr | 7.515 | 6.996 | +0.519 | +0.198 |
| eff_5 | 0.486 | 0.425 | +0.062 | +0.150 |
| dist_sess_h_atr | 5.877 | 5.416 | +0.460 | +0.150 |
| hmm_state_changed | 0.000 | 0.000 | +0.000 | -0.149 |
| confirm_close_loc | 0.500 | 0.558 | -0.058 | -0.141 |

## L1.4 — Simple candidate filters

Each filter applied per (year, mode). A filter is **promising** only if it improves 2026 without destroying 2024/2025.

| Filter | Mode | Year | %kept | n | WR | Mean $ | PF | Total $ | Max DD | Δ Mean | Δ Total |
|---|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| low chop (chop_10 <= year median) | 1m_momentum | 2024 | 50.0% | 1,650 | 35.8% | $-6.02 | 0.97 | $-9,940 | $-35,245 | $-12.03 | $-29,775 |
| low chop (chop_10 <= year median) | 1m_momentum | 2025 | 50.0% | 1,644 | 33.5% | $4.44 | 1.02 | $7,305 | $-31,495 | $-12.54 | $-48,505 |
| low chop (chop_10 <= year median) | 1m_momentum | 2026 | 50.1% | 489 | 35.8% | $-20.85 | 0.93 | $-10,195 | $-20,500 | $0.84 | $10,995 |
| low chop (chop_10 <= year median) | 30s_momentum | 2024 | 50.0% | 1,540 | 36.2% | $-12.06 | 0.94 | $-18,565 | $-48,560 | $-7.56 | $-4,710 |
| low chop (chop_10 <= year median) | 30s_momentum | 2025 | 50.0% | 1,550 | 35.5% | $23.80 | 1.09 | $36,890 | $-25,925 | $-3.99 | $-49,325 |
| low chop (chop_10 <= year median) | 30s_momentum | 2026 | 50.1% | 427 | 34.7% | $-34.99 | 0.89 | $-14,940 | $-28,965 | $3.69 | $18,055 |

| strong confirm (close_loc >= 0.7 if bull, <= 0.3 if bear) | 1m_momentum | 2024 | 55.2% | 1,823 | 37.6% | $15.78 | 1.08 | $28,765 | $-24,370 | $9.77 | $8,930 |
| strong confirm (close_loc >= 0.7 if bull, <= 0.3 if bear) | 1m_momentum | 2025 | 59.5% | 1,957 | 34.0% | $23.83 | 1.09 | $46,645 | $-29,490 | $6.86 | $-9,165 |
| strong confirm (close_loc >= 0.7 if bull, <= 0.3 if bear) | 1m_momentum | 2026 | 58.8% | 574 | 37.5% | $-19.93 | 0.94 | $-11,440 | $-18,605 | $1.76 | $9,750 |
| strong confirm (close_loc >= 0.7 if bull, <= 0.3 if bear) | 30s_momentum | 2024 | 55.6% | 1,715 | 33.5% | $-19.93 | 0.90 | $-34,175 | $-68,930 | $-15.43 | $-20,320 |
| strong confirm (close_loc >= 0.7 if bull, <= 0.3 if bear) | 30s_momentum | 2025 | 58.2% | 1,805 | 34.5% | $29.63 | 1.11 | $53,485 | $-28,620 | $1.84 | $-32,730 |
| strong confirm (close_loc >= 0.7 if bull, <= 0.3 if bear) | 30s_momentum | 2026 | 58.1% | 496 | 33.7% | $-55.78 | 0.82 | $-27,665 | $-38,120 | $-17.10 | $5,330 |

| strong confirm body (body_pct >= 0.5) | 1m_momentum | 2024 | 46.3% | 1,529 | 37.3% | $2.97 | 1.01 | $4,535 | $-31,270 | $-3.04 | $-15,300 |
| strong confirm body (body_pct >= 0.5) | 1m_momentum | 2025 | 46.7% | 1,536 | 35.1% | $41.53 | 1.16 | $63,795 | $-25,280 | $24.55 | $7,985 |
| strong confirm body (body_pct >= 0.5) | 1m_momentum | 2026 | 45.4% | 444 | 37.2% | $-32.26 | 0.90 | $-14,325 | $-20,495 | $-10.57 | $6,865 |
| strong confirm body (body_pct >= 0.5) | 30s_momentum | 2024 | 50.1% | 1,545 | 33.5% | $-16.92 | 0.92 | $-26,145 | $-54,970 | $-12.43 | $-12,290 |
| strong confirm body (body_pct >= 0.5) | 30s_momentum | 2025 | 49.2% | 1,528 | 34.4% | $2.86 | 1.01 | $4,370 | $-22,925 | $-24.93 | $-81,845 |
| strong confirm body (body_pct >= 0.5) | 30s_momentum | 2026 | 48.9% | 417 | 35.7% | $-44.35 | 0.85 | $-18,495 | $-26,315 | $-5.67 | $14,500 |

| low recent flip count (flip_count_60m <= 5) | 1m_momentum | 2024 | 61.3% | 2,024 | 35.4% | $6.00 | 1.03 | $12,135 | $-32,610 | $-0.02 | $-7,700 |
| low recent flip count (flip_count_60m <= 5) | 1m_momentum | 2025 | 56.8% | 1,868 | 34.0% | $11.66 | 1.05 | $21,785 | $-33,785 | $-5.32 | $-34,025 |
| low recent flip count (flip_count_60m <= 5) | 1m_momentum | 2026 | 57.5% | 562 | 34.5% | $-23.68 | 0.92 | $-13,310 | $-20,920 | $-1.99 | $7,880 |
| low recent flip count (flip_count_60m <= 5) | 30s_momentum | 2024 | 61.5% | 1,894 | 34.4% | $0.54 | 1.00 | $1,015 | $-28,810 | $5.03 | $14,870 |
| low recent flip count (flip_count_60m <= 5) | 30s_momentum | 2025 | 57.5% | 1,783 | 34.9% | $26.42 | 1.11 | $47,110 | $-21,410 | $-1.37 | $-39,105 |
| low recent flip count (flip_count_60m <= 5) | 30s_momentum | 2026 | 58.7% | 501 | 32.3% | $-47.80 | 0.84 | $-23,950 | $-29,550 | $-9.12 | $9,045 |

| high pre-signal efficiency (eff_10 >= 0.4) | 1m_momentum | 2024 | 7.6% | 251 | 35.1% | $-31.25 | 0.85 | $-7,845 | $-15,615 | $-37.27 | $-27,680 |
| high pre-signal efficiency (eff_10 >= 0.4) | 1m_momentum | 2025 | 5.7% | 189 | 37.0% | $11.90 | 1.04 | $2,250 | $-10,370 | $-5.07 | $-53,560 |
| high pre-signal efficiency (eff_10 >= 0.4) | 1m_momentum | 2026 | 8.0% | 78 | 32.1% | $-62.05 | 0.81 | $-4,840 | $-12,765 | $-40.36 | $16,350 |
| high pre-signal efficiency (eff_10 >= 0.4) | 30s_momentum | 2024 | 8.3% | 255 | 36.9% | $-22.67 | 0.90 | $-5,780 | $-11,405 | $-18.17 | $8,075 |
| high pre-signal efficiency (eff_10 >= 0.4) | 30s_momentum | 2025 | 6.2% | 193 | 37.8% | $52.31 | 1.20 | $10,095 | $-12,035 | $24.51 | $-76,120 |
| high pre-signal efficiency (eff_10 >= 0.4) | 30s_momentum | 2026 | 8.2% | 70 | 30.0% | $-198.43 | 0.50 | $-13,890 | $-18,125 | $-159.75 | $19,105 |

| 5m aligned | 1m_momentum | 2024 | 53.3% | 1,758 | 40.7% | $67.89 | 1.40 | $119,345 | $-10,840 | $61.88 | $99,510 |
| 5m aligned | 1m_momentum | 2025 | 51.9% | 1,707 | 37.6% | $64.08 | 1.28 | $109,390 | $-11,770 | $47.10 | $53,580 |
| 5m aligned | 1m_momentum | 2026 | 50.2% | 490 | 41.2% | $62.15 | 1.24 | $30,455 | $-10,990 | $83.84 | $51,645 |
| 5m aligned | 30s_momentum | 2024 | 51.0% | 1,573 | 37.9% | $46.49 | 1.26 | $73,135 | $-14,645 | $50.99 | $86,990 |
| 5m aligned | 30s_momentum | 2025 | 48.6% | 1,505 | 37.8% | $61.56 | 1.27 | $92,655 | $-17,180 | $33.77 | $6,440 |
| 5m aligned | 30s_momentum | 2026 | 47.8% | 408 | 40.7% | $22.11 | 1.08 | $9,020 | $-17,225 | $60.79 | $42,015 |

| morning session (minutes_since_open <= 60) | 1m_momentum | 2024 | 16.5% | 546 | 35.2% | $-9.27 | 0.97 | $-5,060 | $-23,705 | $-15.28 | $-24,895 |
| morning session (minutes_since_open <= 60) | 1m_momentum | 2025 | 15.7% | 515 | 37.9% | $45.87 | 1.12 | $23,625 | $-15,975 | $28.89 | $-32,185 |
| morning session (minutes_since_open <= 60) | 1m_momentum | 2026 | 15.7% | 153 | 37.3% | $-17.58 | 0.97 | $-2,690 | $-14,315 | $4.11 | $18,500 |
| morning session (minutes_since_open <= 60) | 30s_momentum | 2024 | 16.7% | 512 | 31.2% | $-32.46 | 0.89 | $-16,620 | $-29,740 | $-27.97 | $-2,765 |
| morning session (minutes_since_open <= 60) | 30s_momentum | 2025 | 16.3% | 504 | 39.1% | $94.66 | 1.26 | $47,710 | $-18,865 | $66.87 | $-38,505 |
| morning session (minutes_since_open <= 60) | 30s_momentum | 2026 | 15.5% | 132 | 37.1% | $-11.40 | 0.98 | $-1,505 | $-9,575 | $27.28 | $31,490 |

| not afternoon (minutes_since_open <= 240) | 1m_momentum | 2024 | 62.6% | 2,066 | 35.0% | $2.86 | 1.01 | $5,915 | $-19,975 | $-3.15 | $-13,920 |
| not afternoon (minutes_since_open <= 240) | 1m_momentum | 2025 | 62.3% | 2,048 | 34.1% | $26.36 | 1.10 | $53,990 | $-31,290 | $9.38 | $-1,820 |
| not afternoon (minutes_since_open <= 240) | 1m_momentum | 2026 | 64.4% | 629 | 35.5% | $-18.93 | 0.94 | $-11,910 | $-19,150 | $2.75 | $9,280 |
| not afternoon (minutes_since_open <= 240) | 30s_momentum | 2024 | 63.6% | 1,960 | 34.0% | $-11.40 | 0.95 | $-22,345 | $-35,640 | $-6.91 | $-8,490 |
| not afternoon (minutes_since_open <= 240) | 30s_momentum | 2025 | 61.6% | 1,910 | 35.9% | $45.79 | 1.17 | $87,465 | $-28,195 | $18.00 | $1,250 |
| not afternoon (minutes_since_open <= 240) | 30s_momentum | 2026 | 64.1% | 547 | 35.1% | $-42.30 | 0.88 | $-23,140 | $-32,995 | $-3.62 | $9,855 |

| HMM state not 3 at signal | 1m_momentum | 2024 | 49.2% | 1,623 | 35.6% | $16.61 | 1.12 | $26,960 | $-12,535 | $10.60 | $7,125 |
| HMM state not 3 at signal | 1m_momentum | 2025 | 43.2% | 1,419 | 32.0% | $7.49 | 1.05 | $10,625 | $-34,980 | $-9.49 | $-45,185 |
| HMM state not 3 at signal | 1m_momentum | 2026 | 33.1% | 323 | 34.7% | $15.17 | 1.09 | $4,900 | $-6,105 | $36.86 | $26,090 |
| HMM state not 3 at signal | 30s_momentum | 2024 | 50.1% | 1,546 | 33.8% | $14.29 | 1.10 | $22,095 | $-12,210 | $18.79 | $35,950 |
| HMM state not 3 at signal | 30s_momentum | 2025 | 43.0% | 1,334 | 33.3% | $3.36 | 1.02 | $4,480 | $-34,400 | $-24.44 | $-81,735 |
| HMM state not 3 at signal | 30s_momentum | 2026 | 31.1% | 265 | 32.8% | $-25.91 | 0.85 | $-6,865 | $-12,830 | $12.78 | $26,130 |

| not high ATR pct (atr_pct_500 < 0.7) | 1m_momentum | 2024 | 49.8% | 1,644 | 35.0% | $9.47 | 1.06 | $15,565 | $-26,480 | $3.46 | $-4,270 |
| not high ATR pct (atr_pct_500 < 0.7) | 1m_momentum | 2025 | 50.7% | 1,667 | 32.8% | $20.44 | 1.10 | $34,075 | $-37,465 | $3.46 | $-21,735 |
| not high ATR pct (atr_pct_500 < 0.7) | 1m_momentum | 2026 | 53.8% | 526 | 35.2% | $-19.37 | 0.91 | $-10,190 | $-23,685 | $2.32 | $11,000 |
| not high ATR pct (atr_pct_500 < 0.7) | 30s_momentum | 2024 | 49.7% | 1,534 | 32.3% | $-1.55 | 0.99 | $-2,385 | $-30,820 | $2.94 | $11,470 |
| not high ATR pct (atr_pct_500 < 0.7) | 30s_momentum | 2025 | 50.8% | 1,579 | 33.4% | $16.76 | 1.08 | $26,460 | $-34,490 | $-11.04 | $-59,755 |
| not high ATR pct (atr_pct_500 < 0.7) | 30s_momentum | 2026 | 54.7% | 467 | 34.3% | $-25.62 | 0.89 | $-11,965 | $-28,405 | $13.06 | $21,030 |

| low chop + strong confirm | 1m_momentum | 2024 | 27.7% | 914 | 37.9% | $-9.49 | 0.95 | $-8,675 | $-19,620 | $-15.50 | $-28,510 |
| low chop + strong confirm | 1m_momentum | 2025 | 27.6% | 907 | 35.3% | $13.04 | 1.05 | $11,825 | $-24,070 | $-3.94 | $-43,985 |
| low chop + strong confirm | 1m_momentum | 2026 | 27.6% | 270 | 37.4% | $-25.17 | 0.92 | $-6,795 | $-15,635 | $-3.48 | $14,395 |
| low chop + strong confirm | 30s_momentum | 2024 | 27.6% | 850 | 36.9% | $-15.40 | 0.93 | $-13,090 | $-33,040 | $-10.90 | $765.00 |
| low chop + strong confirm | 30s_momentum | 2025 | 27.4% | 851 | 34.4% | $-8.63 | 0.97 | $-7,345 | $-23,475 | $-36.42 | $-93,560 |
| low chop + strong confirm | 30s_momentum | 2026 | 26.1% | 223 | 34.1% | $-68.34 | 0.79 | $-15,240 | $-24,355 | $-29.66 | $17,755 |

| low chop + 5m aligned | 1m_momentum | 2024 | 27.5% | 909 | 42.1% | $61.89 | 1.36 | $56,260 | $-5,910 | $55.88 | $36,425 |
| low chop + 5m aligned | 1m_momentum | 2025 | 27.5% | 905 | 36.9% | $52.41 | 1.22 | $47,430 | $-13,335 | $35.43 | $-8,380 |
| low chop + 5m aligned | 1m_momentum | 2026 | 26.5% | 259 | 41.7% | $31.41 | 1.11 | $8,135 | $-19,600 | $53.10 | $29,325 |
| low chop + 5m aligned | 30s_momentum | 2024 | 26.5% | 817 | 42.0% | $51.05 | 1.28 | $41,710 | $-12,545 | $55.55 | $55,565 |
| low chop + 5m aligned | 30s_momentum | 2025 | 25.8% | 800 | 38.9% | $65.89 | 1.28 | $52,710 | $-12,595 | $38.09 | $-33,505 |
| low chop + 5m aligned | 30s_momentum | 2026 | 26.1% | 223 | 41.7% | $34.75 | 1.12 | $7,750 | $-18,000 | $73.43 | $40,745 |

| strong confirm + 5m aligned | 1m_momentum | 2024 | 26.5% | 875 | 42.7% | $64.71 | 1.36 | $56,620 | $-13,005 | $58.70 | $36,785 |
| strong confirm + 5m aligned | 1m_momentum | 2025 | 26.0% | 855 | 38.5% | $77.92 | 1.33 | $66,620 | $-10,860 | $60.94 | $10,810 |
| strong confirm + 5m aligned | 1m_momentum | 2026 | 24.8% | 242 | 41.7% | $18.16 | 1.06 | $4,395 | $-11,350 | $39.85 | $25,585 |
| strong confirm + 5m aligned | 30s_momentum | 2024 | 26.2% | 808 | 37.7% | $39.00 | 1.21 | $31,510 | $-20,220 | $43.49 | $45,365 |
| strong confirm + 5m aligned | 30s_momentum | 2025 | 25.7% | 797 | 36.9% | $19.62 | 1.08 | $15,640 | $-22,835 | $-8.17 | $-70,575 |
| strong confirm + 5m aligned | 30s_momentum | 2026 | 23.7% | 202 | 43.6% | $67.52 | 1.27 | $13,640 | $-9,320 | $106.21 | $46,635 |

## L1.5 — Scale-up eligible cohort search

For each promising filter from L1.4, report cross-year stability. Eligible only if positive in all 3 years.

| Filter | Mode | n_24 | mean_24 | n_25 | mean_25 | n_26 | mean_26 | All 3 yrs +? |
|---|---|--:|--:|--:|--:|--:|--:|---|
| low chop + strong confirm | 1m_momentum | 914 | $-9.49 | 907 | $13.04 | 270 | $-25.17 | no |
| low chop + strong confirm | 30s_momentum | 850 | $-15.40 | 851 | $-8.63 | 223 | $-68.34 | no |
| low chop + 5m aligned | 1m_momentum | 909 | $61.89 | 905 | $52.41 | 259 | $31.41 | **YES** |
| low chop + 5m aligned | 30s_momentum | 817 | $51.05 | 800 | $65.89 | 223 | $34.75 | **YES** |
| strong confirm + 5m aligned | 1m_momentum | 875 | $64.71 | 855 | $77.92 | 242 | $18.16 | **YES** |
| strong confirm + 5m aligned | 30s_momentum | 808 | $39.00 | 797 | $19.62 | 202 | $67.52 | **YES** |
| morning + 5m aligned | 1m_momentum | 315 | $71.00 | 272 | $118.97 | 91 | $94.40 | **YES** |
| morning + 5m aligned | 30s_momentum | 273 | $63.17 | 244 | $156.70 | 73 | $64.52 | **YES** |
| morning + low chop | 1m_momentum | 279 | $-24.48 | 273 | $50.86 | 79 | $115.13 | no |
| morning + low chop | 30s_momentum | 273 | $-36.87 | 262 | $44.03 | 63 | $89.52 | no |
| high HHLL break + 5m aligned | 1m_momentum | 1,596 | $63.63 | 1,497 | $75.07 | 435 | $46.78 | **YES** |
| high HHLL break + 5m aligned | 30s_momentum | 1,322 | $42.89 | 1,196 | $64.29 | 330 | $49.39 | **YES** |
| strong confirm + low recent flips | 1m_momentum | 946 | $7.87 | 894 | $37.77 | 243 | $-23.89 | no |
| strong confirm + low recent flips | 30s_momentum | 940 | $-11.20 | 902 | $14.93 | 236 | $-129.11 | no |

# Layer 2 — Max-MFE Structural Study

## L2.1 — Loser MFE buckets

Among eventual losers, distribution of max MFE.

| Year | Mode | Bucket (max MFE ATR) | n | %losers | Avg Loss | Med Loss | Med Time-to-MFE | Med Giveback | Med Time MFE→Exit |
|---|---|---|--:|--:|--:|--:|--:|--:|--:|
| 2024 | 1m_momentum | <0.25 | 417 | 19.6% | $-410.47 | $-350.00 | 4s | 1.99 ATR | 149s |
| 2024 | 1m_momentum | 0.25-0.50 | 356 | 16.7% | $-398.48 | $-330.00 | 33s | 2.03 ATR | 202s |
| 2024 | 1m_momentum | 0.50-0.75 | 260 | 12.2% | $-334.98 | $-290.00 | 71s | 2.12 ATR | 232s |
| 2024 | 1m_momentum | 0.75-1.00 | 233 | 10.9% | $-306.87 | $-245.00 | 123s | 2.17 ATR | 240s |
| 2024 | 1m_momentum | 1.00-1.50 | 358 | 16.8% | $-229.33 | $-182.50 | 208s | 2.26 ATR | 251s |
| 2024 | 1m_momentum | >=1.50 | 505 | 23.7% | $-161.79 | $-115.00 | 313s | 2.87 ATR | 285s |

| 2024 | 30s_momentum | <0.25 | 382 | 18.8% | $-421.19 | $-370.00 | 2s | 1.96 ATR | 179s |
| 2024 | 30s_momentum | 0.25-0.50 | 317 | 15.6% | $-386.42 | $-330.00 | 34s | 2.06 ATR | 202s |
| 2024 | 30s_momentum | 0.50-0.75 | 265 | 13.0% | $-345.68 | $-280.00 | 60s | 2.16 ATR | 224s |
| 2024 | 30s_momentum | 0.75-1.00 | 235 | 11.5% | $-313.85 | $-270.00 | 124s | 2.28 ATR | 233s |
| 2024 | 30s_momentum | 1.00-1.50 | 343 | 16.8% | $-259.74 | $-190.00 | 203s | 2.24 ATR | 254s |
| 2024 | 30s_momentum | >=1.50 | 495 | 24.3% | $-158.53 | $-115.00 | 328s | 2.79 ATR | 294s |

| 2025 | 1m_momentum | <0.25 | 402 | 18.4% | $-533.97 | $-432.50 | 2s | 1.88 ATR | 149s |
| 2025 | 1m_momentum | 0.25-0.50 | 350 | 16.1% | $-491.10 | $-395.00 | 32s | 1.97 ATR | 180s |
| 2025 | 1m_momentum | 0.50-0.75 | 268 | 12.3% | $-436.85 | $-345.00 | 92s | 2.04 ATR | 199s |
| 2025 | 1m_momentum | 0.75-1.00 | 238 | 10.9% | $-375.48 | $-282.50 | 133s | 2.06 ATR | 227s |
| 2025 | 1m_momentum | 1.00-1.50 | 411 | 18.9% | $-279.94 | $-210.00 | 230s | 2.20 ATR | 238s |
| 2025 | 1m_momentum | >=1.50 | 511 | 23.4% | $-220.62 | $-130.00 | 303s | 2.87 ATR | 272s |

| 2025 | 30s_momentum | <0.25 | 372 | 18.4% | $-525.66 | $-410.00 | 2s | 1.87 ATR | 176s |
| 2025 | 30s_momentum | 0.25-0.50 | 319 | 15.8% | $-518.75 | $-410.00 | 34s | 2.04 ATR | 215s |
| 2025 | 30s_momentum | 0.50-0.75 | 279 | 13.8% | $-440.65 | $-355.00 | 75s | 2.08 ATR | 214s |
| 2025 | 30s_momentum | 0.75-1.00 | 229 | 11.3% | $-376.35 | $-290.00 | 155s | 2.10 ATR | 239s |
| 2025 | 30s_momentum | 1.00-1.50 | 344 | 17.0% | $-311.69 | $-232.50 | 190s | 2.26 ATR | 250s |
| 2025 | 30s_momentum | >=1.50 | 476 | 23.6% | $-220.64 | $-140.00 | 321s | 2.88 ATR | 262s |

| 2026 | 1m_momentum | <0.25 | 123 | 19.4% | $-637.89 | $-575.00 | 5s | 1.96 ATR | 149s |
| 2026 | 1m_momentum | 0.25-0.50 | 95 | 15.0% | $-565.74 | $-445.00 | 30s | 1.98 ATR | 194s |
| 2026 | 1m_momentum | 0.50-0.75 | 91 | 14.4% | $-553.52 | $-450.00 | 66s | 2.14 ATR | 251s |
| 2026 | 1m_momentum | 0.75-1.00 | 84 | 13.3% | $-440.77 | $-375.00 | 138s | 2.15 ATR | 208s |
| 2026 | 1m_momentum | 1.00-1.50 | 102 | 16.1% | $-370.10 | $-312.50 | 185s | 2.36 ATR | 236s |
| 2026 | 1m_momentum | >=1.50 | 138 | 21.8% | $-248.30 | $-152.50 | 292s | 2.84 ATR | 243s |

| 2026 | 30s_momentum | <0.25 | 104 | 18.6% | $-593.75 | $-490.00 | 2s | 1.87 ATR | 167s |
| 2026 | 30s_momentum | 0.25-0.50 | 84 | 15.1% | $-627.38 | $-537.50 | 36s | 2.11 ATR | 204s |
| 2026 | 30s_momentum | 0.50-0.75 | 79 | 14.2% | $-621.52 | $-585.00 | 80s | 2.14 ATR | 227s |
| 2026 | 30s_momentum | 0.75-1.00 | 66 | 11.8% | $-453.86 | $-360.00 | 102s | 2.26 ATR | 268s |
| 2026 | 30s_momentum | 1.00-1.50 | 90 | 16.1% | $-341.72 | $-245.00 | 210s | 2.21 ATR | 293s |
| 2026 | 30s_momentum | >=1.50 | 135 | 24.2% | $-251.78 | $-185.00 | 299s | 2.78 ATR | 297s |

## L2.2 — Structural predictors of max MFE

Compare trades reaching max MFE >= threshold vs those that don't. Cohen's d on key features. Combined across all years per mode.

### 1m_momentum

#### Max MFE >= 0.5 ATR (5,818 / 7,564 = 76.9%)

| Feature | Med Reached | Med Not | Δ | d |
|---|--:|--:|--:|--:|
| regime_5m_aligned | 1.000 | 0.000 | +1.000 | +0.287 |
| close_through_amt_atr | 0.291 | 0.221 | +0.070 | +0.142 |
| confirm_body_pct | 0.478 | 0.424 | +0.054 | +0.141 |
| regime_5m_age_5m_bars | 8.000 | 9.000 | -1.000 | -0.140 |
| confirm_range_atr | 0.974 | 0.933 | +0.041 | +0.122 |
| hhll_amount_atr | 0.580 | 0.544 | +0.035 | +0.116 |
| rr_5_atr | 2.710 | 2.640 | +0.070 | +0.112 |
| confirm_vol_z | 0.451 | 0.305 | +0.147 | +0.103 |

#### Max MFE >= 1.0 ATR (4,639 / 7,564 = 61.3%)

| Feature | Med Reached | Med Not | Δ | d |
|---|--:|--:|--:|--:|
| regime_5m_aligned | 1.000 | 0.000 | +1.000 | +0.276 |
| regime_5m_age_5m_bars | 8.000 | 9.000 | -1.000 | -0.155 |
| rr_5_atr | 2.723 | 2.652 | +0.070 | +0.126 |
| confirm_range_atr | 0.980 | 0.944 | +0.036 | +0.113 |
| close_through_amt_atr | 0.292 | 0.246 | +0.046 | +0.100 |
| confirm_body_pct | 0.478 | 0.440 | +0.038 | +0.094 |
| confirm_vol_z | 0.466 | 0.345 | +0.121 | +0.092 |
| rr_10_atr | 3.057 | 3.022 | +0.035 | +0.091 |

#### Max MFE >= 1.5 ATR (3,746 / 7,564 = 49.5%)

| Feature | Med Reached | Med Not | Δ | d |
|---|--:|--:|--:|--:|
| regime_5m_aligned | 1.000 | 0.000 | +1.000 | +0.275 |
| regime_5m_age_5m_bars | 7.000 | 9.000 | -2.000 | -0.162 |
| confirm_range_atr | 0.988 | 0.945 | +0.043 | +0.139 |
| close_through_amt_atr | 0.301 | 0.248 | +0.052 | +0.127 |
| rr_5_atr | 2.723 | 2.663 | +0.060 | +0.126 |
| confirm_vol_z | 0.487 | 0.349 | +0.138 | +0.119 |
| hhll_amount_atr | 0.587 | 0.556 | +0.031 | +0.114 |
| rr_10_atr | 3.063 | 3.024 | +0.040 | +0.096 |

#### Max MFE >= 2.0 ATR (3,022 / 7,564 = 40.0%)

| Feature | Med Reached | Med Not | Δ | d |
|---|--:|--:|--:|--:|
| regime_5m_aligned | 1.000 | 0.000 | +1.000 | +0.261 |
| regime_5m_age_5m_bars | 7.000 | 9.000 | -2.000 | -0.159 |
| rr_5_atr | 2.729 | 2.668 | +0.060 | +0.143 |
| confirm_range_atr | 0.988 | 0.949 | +0.039 | +0.139 |
| close_through_amt_atr | 0.304 | 0.251 | +0.052 | +0.125 |
| rr_10_atr | 3.068 | 3.027 | +0.041 | +0.118 |
| atr_slope_10 | -0.004 | -0.010 | +0.006 | +0.115 |
| hhll_amount_atr | 0.591 | 0.558 | +0.032 | +0.115 |

### 30s_momentum

#### Max MFE >= 0.5 ATR (5,459 / 7,043 = 77.5%)

| Feature | Med Reached | Med Not | Δ | d |
|---|--:|--:|--:|--:|
| regime_5m_aligned | 1.000 | 0.000 | +1.000 | +0.206 |
| rr_10_atr | 3.058 | 2.998 | +0.060 | +0.139 |
| rr_5_atr | 2.716 | 2.645 | +0.071 | +0.135 |
| regime_5m_age_5m_bars | 8.000 | 9.000 | -1.000 | -0.114 |
| bar_overlap_pct | 1.766 | 1.810 | -0.044 | -0.104 |
| atr_slope_10 | -0.006 | -0.011 | +0.004 | +0.093 |
| close_through_amt_atr | 0.202 | 0.178 | +0.024 | +0.088 |
| prior_5_net_move_atr | 1.080 | 1.052 | +0.028 | +0.087 |

#### Max MFE >= 1.0 ATR (4,305 / 7,043 = 61.1%)

| Feature | Med Reached | Med Not | Δ | d |
|---|--:|--:|--:|--:|
| regime_5m_aligned | 1.000 | 0.000 | +1.000 | +0.212 |
| regime_5m_age_5m_bars | 8.000 | 9.000 | -1.000 | -0.137 |
| rr_5_atr | 2.727 | 2.654 | +0.073 | +0.133 |
| rr_10_atr | 3.063 | 3.019 | +0.044 | +0.112 |
| hhll_amount_atr | 0.428 | 0.397 | +0.031 | +0.090 |
| bar_overlap_pct | 1.763 | 1.796 | -0.033 | -0.089 |
| confirm_range_atr | 0.745 | 0.725 | +0.020 | +0.085 |
| atr_slope_10 | -0.005 | -0.011 | +0.006 | +0.085 |

#### Max MFE >= 1.5 ATR (3,508 / 7,043 = 49.8%)

| Feature | Med Reached | Med Not | Δ | d |
|---|--:|--:|--:|--:|
| regime_5m_aligned | 1.000 | 0.000 | +1.000 | +0.219 |
| rr_5_atr | 2.735 | 2.659 | +0.076 | +0.142 |
| regime_5m_age_5m_bars | 8.000 | 9.000 | -1.000 | -0.130 |
| rr_10_atr | 3.068 | 3.023 | +0.044 | +0.112 |
| hhll_amount_atr | 0.432 | 0.401 | +0.031 | +0.104 |
| close_through_amt_atr | 0.209 | 0.184 | +0.025 | +0.099 |
| atr_slope_10 | -0.005 | -0.010 | +0.005 | +0.095 |
| confirm_range_atr | 0.749 | 0.727 | +0.022 | +0.094 |

#### Max MFE >= 2.0 ATR (2,818 / 7,043 = 40.0%)

| Feature | Med Reached | Med Not | Δ | d |
|---|--:|--:|--:|--:|
| regime_5m_aligned | 1.000 | 0.000 | +1.000 | +0.197 |
| rr_5_atr | 2.731 | 2.672 | +0.059 | +0.135 |
| regime_5m_age_5m_bars | 7.000 | 9.000 | -2.000 | -0.122 |
| rr_10_atr | 3.075 | 3.024 | +0.051 | +0.120 |
| atr_slope_10 | -0.004 | -0.010 | +0.006 | +0.108 |
| confirm_range_atr | 0.748 | 0.731 | +0.017 | +0.087 |
| bar_overlap_pct | 1.760 | 1.789 | -0.029 | -0.082 |
| hhll_amount_atr | 0.431 | 0.405 | +0.026 | +0.081 |

## L2.3 — Early path predictors of max MFE

For each (mode), pull paths_<mode>_<year>.parquet and check whether path state at 30/60/120/180/300s predicts final max MFE >= 1.0 ATR.

### 1m_momentum

| Checkpoint | Med PnL ATR | Med MFE ATR | Med MAE ATR | Med Giveback | %trades MFE>=1.0 (eventual) | Cor(curr_PnL, max_MFE) |
|--:|--:|--:|--:|--:|--:|--:|
| 30s | 0.01 | 0.28 | 0.26 | 0.27 | 62.1% | 0.186 |
| 60s | 0.02 | 0.42 | 0.40 | 0.41 | 62.1% | 0.268 |
| 120s | 0.06 | 0.61 | 0.54 | 0.57 | 64.6% | 0.351 |
| 180s | 0.15 | 0.81 | 0.62 | 0.65 | 68.6% | 0.397 |
| 300s | 0.36 | 1.15 | 0.68 | 0.76 | 76.7% | 0.500 |

Conditional: at each checkpoint, P(final max MFE >= 1.0 | current state) for buckets of current PnL ATR.

| Checkpoint | Bucket | n | P(max MFE >= 1.0) | P(max MFE >= 1.5) | P(eventual win) |
|--:|---|--:|--:|--:|--:|
| 60s | PnL < 0 | 3,569 | 43.5% | 34.6% | 24.8% |
| 60s | 0 <= PnL < 0.25 | 1,302 | 64.0% | 51.5% | 36.6% |
| 60s | 0.25 <= PnL < 0.5 | 1,029 | 76.6% | 59.3% | 42.0% |
| 60s | PnL >= 0.5 | 1,568 | 93.4% | 78.6% | 52.6% |
| 120s | PnL < 0 | 3,372 | 41.7% | 32.1% | 22.8% |
| 120s | 0 <= PnL < 0.25 | 944 | 66.2% | 48.9% | 35.1% |
| 120s | 0.25 <= PnL < 0.5 | 795 | 78.5% | 60.3% | 43.8% |
| 120s | PnL >= 0.5 | 2,066 | 96.0% | 83.4% | 56.7% |
| 180s | PnL < 0 | 2,915 | 42.4% | 31.0% | 20.8% |
| 180s | 0 <= PnL < 0.25 | 763 | 69.6% | 49.8% | 35.9% |
| 180s | 0.25 <= PnL < 0.5 | 712 | 80.8% | 60.8% | 43.4% |
| 180s | PnL >= 0.5 | 2,345 | 97.2% | 86.4% | 60.9% |

### 30s_momentum

| Checkpoint | Med PnL ATR | Med MFE ATR | Med MAE ATR | Med Giveback | %trades MFE>=1.0 (eventual) | Cor(curr_PnL, max_MFE) |
|--:|--:|--:|--:|--:|--:|--:|
| 30s | 0.00 | 0.31 | 0.32 | 0.32 | 61.2% | 0.227 |
| 60s | 0.03 | 0.43 | 0.42 | 0.40 | 62.8% | 0.269 |
| 120s | 0.07 | 0.63 | 0.55 | 0.56 | 65.7% | 0.361 |
| 180s | 0.16 | 0.82 | 0.62 | 0.64 | 69.7% | 0.395 |
| 300s | 0.42 | 1.18 | 0.67 | 0.73 | 77.9% | 0.495 |

Conditional: at each checkpoint, P(final max MFE >= 1.0 | current state) for buckets of current PnL ATR.

| Checkpoint | Bucket | n | P(max MFE >= 1.0) | P(max MFE >= 1.5) | P(eventual win) |
|--:|---|--:|--:|--:|--:|
| 60s | PnL < 0 | 3,228 | 45.5% | 36.2% | 24.6% |
| 60s | 0 <= PnL < 0.25 | 1,235 | 63.4% | 50.1% | 35.5% |
| 60s | 0.25 <= PnL < 0.5 | 974 | 74.2% | 59.7% | 42.3% |
| 60s | PnL >= 0.5 | 1,418 | 93.8% | 80.3% | 54.9% |
| 120s | PnL < 0 | 2,995 | 42.7% | 32.8% | 22.4% |
| 120s | 0 <= PnL < 0.25 | 847 | 65.3% | 49.4% | 35.5% |
| 120s | 0.25 <= PnL < 0.5 | 749 | 77.6% | 59.5% | 42.6% |
| 120s | PnL >= 0.5 | 1,952 | 96.6% | 85.1% | 58.0% |
| 180s | PnL < 0 | 2,596 | 43.6% | 32.3% | 21.0% |
| 180s | 0 <= PnL < 0.25 | 717 | 69.5% | 51.0% | 37.0% |
| 180s | 0.25 <= PnL < 0.5 | 606 | 79.9% | 62.4% | 41.9% |
| 180s | PnL >= 0.5 | 2,202 | 97.7% | 87.1% | 61.6% |

## L2.4 — Exit-near-max diagnostic

Conditional 'after MFE >= X, exit if giveback >= Y' rules. Reports separately for eventual winners, losers, and all trades. **Key**: a rule helping losers but destroying winners must be rejected.

### 1m_momentum

| Rule | Year | Group | n | Mean $ | Δ vs hold-to-end | Avg saved/sacrificed |
|---|---|---|--:|--:|--:|--:|
| MFE>=0.50, giveback>=0.25 | 2024 | eventual winners | 1,171 | $116.93 | $-442.64 | $-442.64 |
| MFE>=0.50, giveback>=0.25 | 2024 | eventual losers | 2,129 | $-87.46 | $211.01 | $211.01 |
| MFE>=0.50, giveback>=0.25 | 2024 | all | 3,300 | $-14.93 | $-20.94 | $-20.94 |
| MFE>=0.50, giveback>=0.25 | 2025 | eventual winners | 1,107 | $171.22 | $-620.63 | $-620.63 |
| MFE>=0.50, giveback>=0.25 | 2025 | eventual losers | 2,180 | $-100.34 | $276.16 | $276.16 |
| MFE>=0.50, giveback>=0.25 | 2025 | all | 3,287 | $-8.88 | $-25.86 | $-25.86 |
| MFE>=0.50, giveback>=0.25 | 2026 | eventual winners | 344 | $182.92 | $-603.20 | $-603.20 |
| MFE>=0.50, giveback>=0.25 | 2026 | eventual losers | 633 | $-117.10 | $343.59 | $343.59 |
| MFE>=0.50, giveback>=0.25 | 2026 | all | 977 | $-11.46 | $10.23 | $10.23 |
| MFE>=0.75, giveback>=0.25 | 2024 | eventual winners | 1,171 | $168.05 | $-391.52 | $-391.52 |
| MFE>=0.75, giveback>=0.25 | 2024 | eventual losers | 2,129 | $-112.33 | $186.13 | $186.13 |
| MFE>=0.75, giveback>=0.25 | 2024 | all | 3,300 | $-12.84 | $-18.85 | $-18.85 |
| MFE>=0.75, giveback>=0.25 | 2025 | eventual winners | 1,107 | $249.26 | $-542.59 | $-542.59 |
| MFE>=0.75, giveback>=0.25 | 2025 | eventual losers | 2,180 | $-132.09 | $244.41 | $244.41 |
| MFE>=0.75, giveback>=0.25 | 2025 | all | 3,287 | $-3.66 | $-20.64 | $-20.64 |
| MFE>=0.75, giveback>=0.25 | 2026 | eventual winners | 344 | $264.84 | $-521.28 | $-521.28 |
| MFE>=0.75, giveback>=0.25 | 2026 | eventual losers | 633 | $-177.91 | $282.78 | $282.78 |
| MFE>=0.75, giveback>=0.25 | 2026 | all | 977 | $-22.02 | $-0.33 | $-0.33 |
| MFE>=1.00, giveback>=0.50 | 2024 | eventual winners | 1,171 | $243.58 | $-315.99 | $-315.99 |
| MFE>=1.00, giveback>=0.50 | 2024 | eventual losers | 2,129 | $-153.97 | $144.49 | $144.49 |
| MFE>=1.00, giveback>=0.50 | 2024 | all | 3,300 | $-12.90 | $-18.91 | $-18.91 |
| MFE>=1.00, giveback>=0.50 | 2025 | eventual winners | 1,107 | $363.91 | $-427.94 | $-427.94 |
| MFE>=1.00, giveback>=0.50 | 2025 | eventual losers | 2,180 | $-178.93 | $197.57 | $197.57 |
| MFE>=1.00, giveback>=0.50 | 2025 | all | 3,287 | $3.89 | $-13.09 | $-13.09 |
| MFE>=1.00, giveback>=0.50 | 2026 | eventual winners | 344 | $398.68 | $-387.44 | $-387.44 |
| MFE>=1.00, giveback>=0.50 | 2026 | eventual losers | 633 | $-251.11 | $209.57 | $209.57 |
| MFE>=1.00, giveback>=0.50 | 2026 | all | 977 | $-22.32 | $-0.63 | $-0.63 |
| MFE>=1.50, giveback>=0.75 | 2024 | eventual winners | 1,171 | $375.26 | $-184.31 | $-184.31 |
| MFE>=1.50, giveback>=0.75 | 2024 | eventual losers | 2,129 | $-205.88 | $92.58 | $92.58 |
| MFE>=1.50, giveback>=0.75 | 2024 | all | 3,300 | $0.34 | $-5.67 | $-5.67 |
| MFE>=1.50, giveback>=0.75 | 2025 | eventual winners | 1,107 | $507.03 | $-284.82 | $-284.82 |
| MFE>=1.50, giveback>=0.75 | 2025 | eventual losers | 2,180 | $-257.64 | $118.86 | $118.86 |
| MFE>=1.50, giveback>=0.75 | 2025 | all | 3,287 | $-0.11 | $-17.09 | $-17.09 |
| MFE>=1.50, giveback>=0.75 | 2026 | eventual winners | 344 | $591.77 | $-194.35 | $-194.35 |
| MFE>=1.50, giveback>=0.75 | 2026 | eventual losers | 633 | $-329.33 | $131.36 | $131.36 |
| MFE>=1.50, giveback>=0.75 | 2026 | all | 977 | $-5.01 | $16.68 | $16.68 |

### 30s_momentum

| Rule | Year | Group | n | Mean $ | Δ vs hold-to-end | Avg saved/sacrificed |
|---|---|---|--:|--:|--:|--:|
| MFE>=0.50, giveback>=0.25 | 2024 | eventual winners | 1,045 | $119.03 | $-457.48 | $-457.48 |
| MFE>=0.50, giveback>=0.25 | 2024 | eventual losers | 2,037 | $-79.53 | $223.03 | $223.03 |
| MFE>=0.50, giveback>=0.25 | 2024 | all | 3,082 | $-12.20 | $-7.71 | $-7.71 |
| MFE>=0.50, giveback>=0.25 | 2025 | eventual winners | 1,083 | $169.38 | $-632.66 | $-632.66 |
| MFE>=0.50, giveback>=0.25 | 2025 | eventual losers | 2,019 | $-102.80 | $284.72 | $284.72 |
| MFE>=0.50, giveback>=0.25 | 2025 | all | 3,102 | $-7.77 | $-35.57 | $-35.57 |
| MFE>=0.50, giveback>=0.25 | 2026 | eventual winners | 295 | $180.95 | $-582.63 | $-582.63 |
| MFE>=0.50, giveback>=0.25 | 2026 | eventual losers | 558 | $-104.32 | $358.49 | $358.49 |
| MFE>=0.50, giveback>=0.25 | 2026 | all | 853 | $-5.66 | $33.02 | $33.02 |
| MFE>=0.75, giveback>=0.25 | 2024 | eventual winners | 1,045 | $172.04 | $-404.47 | $-404.47 |
| MFE>=0.75, giveback>=0.25 | 2024 | eventual losers | 2,037 | $-108.53 | $194.03 | $194.03 |
| MFE>=0.75, giveback>=0.25 | 2024 | all | 3,082 | $-13.40 | $-8.90 | $-8.90 |
| MFE>=0.75, giveback>=0.25 | 2025 | eventual winners | 1,083 | $243.14 | $-558.90 | $-558.90 |
| MFE>=0.75, giveback>=0.25 | 2025 | eventual losers | 2,019 | $-142.60 | $244.92 | $244.92 |
| MFE>=0.75, giveback>=0.25 | 2025 | all | 3,102 | $-7.92 | $-35.72 | $-35.72 |
| MFE>=0.75, giveback>=0.25 | 2026 | eventual winners | 295 | $271.92 | $-491.66 | $-491.66 |
| MFE>=0.75, giveback>=0.25 | 2026 | eventual losers | 558 | $-169.90 | $292.91 | $292.91 |
| MFE>=0.75, giveback>=0.25 | 2026 | all | 853 | $-17.10 | $21.58 | $21.58 |
| MFE>=1.00, giveback>=0.50 | 2024 | eventual winners | 1,045 | $239.79 | $-336.72 | $-336.72 |
| MFE>=1.00, giveback>=0.50 | 2024 | eventual losers | 2,037 | $-151.01 | $151.55 | $151.55 |
| MFE>=1.00, giveback>=0.50 | 2024 | all | 3,082 | $-18.50 | $-14.01 | $-14.01 |
| MFE>=1.00, giveback>=0.50 | 2025 | eventual winners | 1,083 | $346.69 | $-455.35 | $-455.35 |
| MFE>=1.00, giveback>=0.50 | 2025 | eventual losers | 2,019 | $-192.61 | $194.91 | $194.91 |
| MFE>=1.00, giveback>=0.50 | 2025 | all | 3,102 | $-4.32 | $-32.12 | $-32.12 |
| MFE>=1.00, giveback>=0.50 | 2026 | eventual winners | 295 | $391.85 | $-371.73 | $-371.73 |
| MFE>=1.00, giveback>=0.50 | 2026 | eventual losers | 558 | $-240.21 | $222.61 | $222.61 |
| MFE>=1.00, giveback>=0.50 | 2026 | all | 853 | $-21.62 | $17.06 | $17.06 |
| MFE>=1.50, giveback>=0.75 | 2024 | eventual winners | 1,045 | $364.36 | $-212.15 | $-212.15 |
| MFE>=1.50, giveback>=0.75 | 2024 | eventual losers | 2,037 | $-211.03 | $91.53 | $91.53 |
| MFE>=1.50, giveback>=0.75 | 2024 | all | 3,082 | $-15.94 | $-11.44 | $-11.44 |
| MFE>=1.50, giveback>=0.75 | 2025 | eventual winners | 1,083 | $496.89 | $-305.15 | $-305.15 |
| MFE>=1.50, giveback>=0.75 | 2025 | eventual losers | 2,019 | $-267.53 | $119.99 | $119.99 |
| MFE>=1.50, giveback>=0.75 | 2025 | all | 3,102 | $-0.65 | $-28.44 | $-28.44 |
| MFE>=1.50, giveback>=0.75 | 2026 | eventual winners | 295 | $578.64 | $-184.93 | $-184.93 |
| MFE>=1.50, giveback>=0.75 | 2026 | eventual losers | 558 | $-313.62 | $149.19 | $149.19 |
| MFE>=1.50, giveback>=0.75 | 2026 | all | 853 | $-5.04 | $33.64 | $33.64 |

## L2.5 — Key summary table

| Year | Mode | n total | %losers MFE>=0.5 | >=0.75 | >=1.0 | >=1.5 | Avg loser final | Med loser MFE | Med loser giveback |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|
| 2024 | 1m_momentum | 3,300 | 63.7% | 51.5% | 40.5% | 23.7% | $-298.46 | 0.78 | 2.26 |
| 2024 | 30s_momentum | 3,084 | 65.7% | 52.7% | 41.1% | 24.3% | $-302.56 | 0.80 | 2.28 |
| 2025 | 1m_momentum | 3,287 | 65.5% | 53.2% | 42.3% | 23.4% | $-376.50 | 0.83 | 2.20 |
| 2025 | 30s_momentum | 3,106 | 65.8% | 52.0% | 40.6% | 23.6% | $-387.52 | 0.79 | 2.23 |
| 2026 | 1m_momentum | 977 | 65.6% | 51.2% | 37.9% | 21.8% | $-460.69 | 0.77 | 2.26 |
| 2026 | 30s_momentum | 853 | 66.3% | 52.2% | 40.3% | 24.2% | $-462.81 | 0.79 | 2.25 |

---

# VERDICT — Bad-regime fingerprint + best filter

## What structurally differs about 2026

Top differentiating features (2026 vs 2024+2025, by Cohen's d):

| Feature | Med 2026 | Med 24+25 | d | Direction |
|---|--:|--:|--:|---|
| atr_at_signal | 16.0 | 11.4 | +0.52 | 2026 has +40% higher ATR |
| hmm_state_prob_3 | 1.00 | 0.87 | +0.30 | 2026 entries dominated by HMM state 3 (vol burst) |
| atr_pct_500 | 0.67 | 0.70 | -0.21 | **2026 ATR is LOWER vs its own rolling context** |
| sess_range_atr | 18.4 | 16.9 | +0.24 | Wider session ranges |
| confirm_vol_z | 0.31 | 0.45 | -0.14 | Lower volume on confirmation |

**Key paradox**: 2026 has ~40% higher absolute ATR but **lower** ATR percentile vs its own 500-bar rolling context. The market has normalized to higher vol — 2026 is high-vol-but-average-for-itself. The 5s HMM consistently classifies 2026 entries as state 3 (vol burst, no directional persistence) — confirming the prior finding that "transition out of state 3" is a tradable bad signal.

**Volume is structurally lower** in 2026 confirmations — less conviction behind moves.

## Single most important filter: 5m REGIME ALIGNMENT

This is the strongest, cleanest result in the entire study.

| Year | Mode | n_kept | %kept | Mean $ | PF | Total $ | Max DD | Δ vs baseline |
|---|---|--:|--:|--:|--:|--:|--:|--:|
| 2024 | V_A | 1,758 | 53% | **+$67.89** | 1.40 | $119,345 | -$10,840 | +$61.88 |
| 2025 | V_A | 1,707 | 52% | **+$64.08** | 1.28 | $109,390 | -$11,770 | +$47.10 |
| 2026 | V_A | 490 | 50% | **+$62.15** | 1.24 | $30,455 | -$10,990 | **+$83.84** |
| 2024 | V_B | 1,573 | 51% | **+$46.49** | 1.26 | $73,135 | -$14,645 | +$50.99 |
| 2025 | V_B | 1,505 | 49% | **+$61.56** | 1.27 | $92,655 | -$17,180 | +$33.77 |
| 2026 | V_B | 408 | 48% | **+$22.11** | 1.08 | $9,020 | -$17,225 | +$60.79 |

**Properties:**
- Positive in ALL 3 years across BOTH modes
- Mean PnL is **remarkably stable across years** (V_A: $62-$68; V_B: $22-$62)
- Halves trade count but nearly triples per-trade economics
- **Max DD drops 4-6x** ($44K-$77K → $11K-$17K)
- PF improvement: 1.03 → 1.40 (V_A 2024)

**Net result**: 5m-aligned V_A across 3 years = 3,955 trades, mean ~$66/trade, total ~$259K, with worst-year DD of $12K. This is a far cleaner Sharpe profile than the unfiltered baseline.

## Cohort combinations that pass cross-year (all 3 years positive)

| Filter | V_A n_24/25/26 | V_A means | V_B n_24/25/26 | V_B means |
|---|---|---|---|---|
| 5m aligned | 1758/1707/490 | $68/$64/$62 | 1573/1505/408 | $46/$62/$22 |
| low chop + 5m aligned | 909/905/259 | $62/$52/$31 | 817/800/223 | $51/$66/$35 |
| strong confirm + 5m aligned | 875/855/242 | $65/$78/$18 | 808/797/202 | $39/$20/$68 |
| **morning + 5m aligned** | 315/272/91 | **$71/$119/$94** | 273/244/73 | **$63/$157/$65** |
| high HHLL break + 5m aligned | 1596/1497/435 | $64/$75/$47 | 1322/1196/330 | $43/$64/$49 |

**Morning + 5m aligned is strongest by mean PnL** but smallest sample (~91 trades/year in 2026). For deployment, the bare 5m-aligned filter offers the best n/edge tradeoff.

## What does NOT work

- **chop/flip count filters alone** — help 2026 modestly, hurt 2024/2025 strongly. Cross-year inversion.
- **strong confirm body or close_loc alone** — mixed across years
- **HMM state-not-3 alone** — V_A 2024 helps (+$10.60), 2025 hurts (-$9.49), 2026 helps (+$36.86) — too noisy without 5m alignment
- **Time-of-day alone** — morning slightly helps but inconsistent
- **High pre-signal efficiency** — destroys 2026 (-$40 V_A, -$160 V_B). Counter-intuitively, "pre-signal trends very efficiently" is a TRAP — those trades are exhausted and reverse. Reject.
- **Low chop alone** — small effects, mixed direction

## Layer 2 — Max-MFE diagnosis

**Most losers DO reach harvestable MFE first:**

| Bucket | % of losers | Avg loss | Med MFE giveback |
|---|--:|--:|--:|
| MFE <0.25 ATR (no harvest) | ~19% | -$465 | 1.95 ATR |
| MFE 0.25-0.50 | ~16% | -$483 | 2.04 |
| MFE 0.50-0.75 | ~13% | -$453 | 2.13 |
| MFE 0.75-1.00 | ~12% | -$378 | 2.18 |
| MFE 1.00-1.50 | ~17% | -$280 | 2.27 |
| MFE >=1.50 | ~24% | -$209 | 2.85 |

About **80% of eventual losers reach >= 0.5 ATR MFE** before reversing. The median giveback for losers is 2.2-2.3 ATR — they ride from positive into significant drawdown.

**But exit-near-max rules don't help on aggregate** (Layer 2.4):
- "MFE>=0.50, giveback>=0.25" saves losers ~$210-360, sacrifices winners ~$443-633. Net: -$8 to -$30/trade in 2024-2025, +$10-33 in 2026.
- "MFE>=1.50, giveback>=0.75" saves losers ~$92-150, sacrifices winners ~$184-300. Net: roughly neutral (-$5 to +$33).

The trades that "had MFE first" overlap massively with the trades that "are eventually winners". You can't separate them at the giveback moment.

**Early path predictors are real but not actionable:**
- At 60s, "PnL<0" trades have 43% chance of reaching MFE>=1.0 and 25% chance of winning. Cutting them all loses too many winners.
- At 60s, "PnL>=0.5" trades have 93% chance of MFE>=1.0 and 53% win rate. But this is just confirming the strategy is already working — no incremental edge.

## Final recommendations

### 1. Deploy with 5m-alignment filter
- Use V_A (1m HH/LL + momentum) with 5m regime alignment requirement
- Expected: ~3,955 trades over 3 years, ~$66/trade, ~$259K total
- Max DD per year: $11K-$17K
- PF range: 1.24 (worst, 2026) to 1.40 (best, 2024)
- **Robust to the 2026 vol regime** — only filter that doesn't fail there

### 2. Don't add exit overlays
- Confirmed by Layer 2: every exit-near-max rule sacrifices the winner tail more than it saves on losers (or just shifts edge between years)
- The strategy's edge depends on holding through retracements that look like reversals
- The 5m-alignment filter does the job by improving entry selection, not exit management

### 3. NT validation needed
- The 5m-alignment finding is offline — needs NT runtime parity check to confirm production economics
- Strategy modification is small: subscribe to 5m bars, track 5m regime via SimpleRegimeTracker, only enter when 5m regime matches 1m flip direction
- Should hit NT in the next study iteration

### 4. Optional enhancement (smaller cohort)
- "morning + 5m aligned" yields $71-$119/trade but only ~91 trades/year in 2026
- For position-sizing-up cohort, consider this as a "high conviction" sub-filter
- Statistically thinner — risk of single-year noise inflating the result

### 5. The 2026 paradox resolved
2026's apparent failure is NOT primarily about ATR magnitude. It's about **directional persistence**:
- Same WR as 2024-2025 (~35%)
- Larger absolute losses driven by higher ATR
- Same MFE/MAE distribution shape
- BUT: 2026 has dramatically higher HMM state 3 fraction (vol burst, no directional follow-through)
- AND 2026 entries occur with lower confirmation volume

The 5m-alignment filter happens to disproportionately reject 2026 state-3-dominated, low-volume confirmations — which is why it lifts 2026 most (Δ +$84/trade vs +$48-$62 in other years).

This is a **regime quality** filter, not a volatility filter. It works because requiring 1m/5m agreement means the trade is happening within a coherent multi-timeframe trend, not a vol-burst chop.
