# Challenge feature definitions

All features are measured at challenge onset `tc` unless marked *checkpoint*. They are causal:
- 1s bars with `ts_init ≤ tc`;
- 1m bars (and their EMA state) with `ts_init ≤ tc`, i.e. the last completed engine update;
- HTF state from the last bucket closed at or before `tc`;
- ledger regimes ended at or before S.

Coordinates are favourable (see REGIME_LIFECYCLE_DEFINITION.md §3). A = audited entry ATR. **Raw point measures are
kept alongside ATR measures** (`*_pts`). Code: `challenge.py`.

**Terms used below:**
- **impulse:** the leg that made the onset extreme `M_c`. It runs from the lowest point since the previous
  episode's deepest point (or since regime start) to the time `M_c` was first made (`iM`).
- **challenge window:** `iM → tc`.
- **candles:** completed 1m bars. Body = close − open (favourable).
- **overlap:** mean of `overlap(consecutive ranges) / min(range)`.
- **wick fraction:** mean of `1 − |body|/range`.

## A. Regime maturity

| feature | definition |
|---|---|
| `t_onset_s` | regime age at onset (s) |
| `n`, `n_prior` | challenge number / prior challenges at this threshold |
| `mfe_A`, `mfe_pts` | `M_c − P0` |
| `mae_A` | worst adverse excursion from P0 so far |
| `loc_close_A`, `loc_touch_A` | current close / touch level vs P0 |
| `since_ext_s` | time since the favourable extreme (= challenge duration) |
| `deepest_prior_A`, `prev_max_depth_A` | deepest prior challenge / depth of the previous one |
| `since_prev_onset_s`, `prev_rec_time_s` | time since the previous onset / how long the previous challenge took to make a new extreme |
| `frac_time_below_0p25` | share of regime seconds with drawdown ≥ 0.25A |
| `prog_last_A` | `(M_c − M_c of the previous episode)/A`: size of the last successful recovery leg ("declining favourable progress") |

## B. Impulse quality

- **Size and pace:**
  - `imp_A`, `imp_pts`, `imp_dur_s`;
  - `imp_eff`: net move / Σ|Δ 1s close|;
  - `imp_speed_A_min`.
- **Volume:**
  - `imp_vol_rate`: contracts/s;
  - `imp_vol_accel`: second-half vs first-half rate.
- **Candles in the impulse:**
  - `imp_bars`, `imp_body_mean_pts`, `imp_body_med_pts`;
  - `imp_dir_frac`: favourable-close share;
  - `imp_big_frac`: |body| ≥ 0.5A share;
  - `imp_max_consec_dir`, `imp_overlap`, `imp_wick_frac`, `imp_range_mean_pts`.

## C. Challenge morphology

- **Size and pace:**
  - `depth_pts` (= k·A);
  - `retrace_frac` (k·A / impulse);
  - `ch_dur_s`;
  - `ch_vel_A_min`;
  - `ch_eff`: net adverse / Σ|Δ 1s close| over the window.
- **Volume:**
  - `ch_vol_rate`;
  - `ch_vol_ratio`: challenge rate / impulse rate.
- **Returns and volatility:**
  - `ret15/30/60/120_A`: close change over the last 15/30/60/120 s;
  - `rv120_pts`: √Σ(Δ 1s close)² over 120 s.
- **Candles in the window:**
  - `ch_bars`;
  - `ch_adv_bars`: adverse closes;
  - `consec_adv_bars`: trailing run of adverse candles;
  - `max_adv_bar_A`, `ch_body_mean_pts`, `ch_overlap`, `ch_wick_frac`, `ch_range_mean_pts`.

## D. EMA / band interaction (last completed 1m bar)

- **Distance to the flip:**
  - `dist_flip_A`: close − min(EMA3_low, EMA9_low), the distance a close must still fall to flip;
  - `dist_flip_touch_A`: the same from the touch level.
- **Penetration:**
  - `pen_ema3`, `pen_ema9`: close below EMA3-low / EMA9-low;
  - `closes_thru_ema3_last3`: last 3 candles closing below EMA3-low without a flip.
- **Band:**
  - `band_w_A`: EMA9_high − EMA9_low;
  - `band_w_chg5`: band width now / 5 bars ago;
  - `band_pos`: close position between EMA9 low and high.
- **Slopes and separation:**
  - `slope3_A`, `slope9_A`: 3-bar change of the EMA mid;
  - `slope9_chg_A`: slope change;
  - `ema_sep_A`: EMA3 mid − EMA9 mid.

## E. Level memory

- **Prior regimes:** turning points = favourable extremes and flip closes of the last 6 ledger regimes (overnight
  included).
  - `n_turns_0p25/0p5/1p0`: turning points within 0.25/0.5/1A of the touch level.
  - `ext_vs_prev_same_regime_A`: `M_c` vs the previous same-direction regime's extreme.
  - `stalled_at_prior_regime_ext`: within ±0.25A of it.
- **Inside the regime:**
  - `touch_vs_prev_deep_A`: touch level vs the previous challenge's deepest point (≤ 0 = a lower low).
  - `n_prior_deeps_near_touch_0p25/0p5`: earlier challenge lows near this touch (repeated test of the same support).
  - `n_marginal_ext`: earlier recovery legs that added < 0.25A ("tried and barely made it").

## F. Higher-timeframe evolution (5m / 15m / 1h)

- `{tf}_aligned`: HTF direction == regime direction now.
- `{tf}_aligned_at_start`: the same at S.
- `{tf}_flips_since_start`: HTF regime changes since S.
- `{tf}_age_min`: minutes since the HTF regime began.
- `5m_dist_flip_A`: distance to the 5m flip threshold in 1m ATR.

## G. Session / market context

- **Time of day:**
  - `min_since_open`, `min_to_close` (ET, 09:30–16:00);
  - `opening_drive` (< 30 min).
- **Volatility and volume:**
  - `rv30_pts`: std of 1m close changes over the last 30 min;
  - `vol30_per_min`;
  - `atr_pts`.

## Checkpoint (response) features, 0.5A and 1.0A episodes

| feature | definition |
|---|---|
| `depth_now_A`, `max_depth_so_far_A` | current / deepest drawdown from `M_c` |
| `rec_frac` | (close − running low)/(M_c − running low) |
| `dist_flip_A`, `above_ema3`, `recaptured_ema3` | EMA state at the last completed bar |
| `n_touch_crosses` | re-crossings of the touch level (re-tests) |
| `new_lows_0p1` | ≥ 0.1A extensions of the running low |
| `vol_resp` | volume rate since onset / impulse volume rate |
| `cp_adv_bars`, `cp_adv_bar_frac`, `cp_consec_adv` | candles since the extreme: adverse count / share / trailing run |
| `cp_closes_below_ema3`, `cp_ema3_recaptured` | candles closing below EMA3-low; closed below then back above |
| `cp_max_adv_body_A`, `cp_overlap` | largest adverse body; candle overlap |
| `cp_band_w_chg`, `cp_slope9_A`, `cp_ema_sep_A` | band-width change since onset; EMA9 slope; EMA separation |

**Degenerate at shallow depths** (a finding, not a bug): at 0.5A `pen_ema3` is true in 0.4% of onsets, `pen_ema9`
in 0.1%, and `ch_bars = 0` in 83%. A sub-minute challenge has no completed candle yet. These features only become
informative at ≥ 1.0A or at checkpoints.
