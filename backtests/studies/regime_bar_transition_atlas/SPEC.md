# NQ 1m Regime Bar-Transition Probability Atlas Specification

## Objective

Build a granular **bar-transition probability atlas** for NQ 1m parent regimes to map historical probabilities of trend continuation, pullback recovery, and first-passage races from every closed bar checkpoint.

---

## Population & Session

*   **Period:** 2021–2026 (2021–2024 Discovery/IS, 2025–2026 Validation/OOS).
*   **Session:** RTH-only (Central Time `[08:30, 15:00)`).
*   **Timeframe:** 1-minute parent regimes, tracked on a bar-by-bar basis up to a maximum duration of 30 bars (or until the parent regime exits).

---

## Checkpoint Identity

For each closed 1m bar $t \in [1, 30]$ inside an active regime, snapshot:
*   `regime_id`: unique identifier (`year * 100_000 + index`).
*   `year`: calendar year.
*   `date`: calendar date (`YYYY-MM-DD`).
*   `session`: `"RTH"`.
*   `direction`: regime direction ($+1$ for bullish, $-1$ for bearish).
*   `regime_start_ts`: start timestamp of the 1m regime.
*   `bar_ts`: close timestamp of the current 1m bar.
*   `bar_index_in_regime`: the number of closed bars since regime start ($t$).
*   `bars_remaining_until_regime_exit`: number of 1m bars from the current close to the regime exit close (label-only).

---

## Causal Features at Bar Close

All metrics are direction-normalized relative to the regime direction ($d \in \{+1, -1\}$). Let $P_{\text{ref}}$ be the close of the regime-flip bar (the entry reference price), and $ATR_{\text{ref}}$ be the 1m ATR at regime start.

### A. Bar Anatomy (Current Closed Bar)
*   `bar_return_atr`: $(Close_t - Open_t) \times d / ATR_{\text{ref}}$.
*   `bar_range_atr`: $(High_t - Low_t) / ATR_{\text{ref}}$.
*   `bar_body_atr`: $|Close_t - Open_t| / ATR_{\text{ref}}$.
*   `bar_body_pct`: $|Close_t - Open_t| / (High_t - Low_t)$ (if range $> 0$, else $0$).
*   `bar_close_location`: location of close within the range in trend direction:
    *   If $d = 1$: $(Close_t - Low_t) / (High_t - Low_t)$.
    *   If $d = -1$: $(High_t - Close_t) / (High_t - Low_t)$.
*   `bar_upper_wick_pct`: wick in the trend direction:
    *   If $d = 1$: $(High_t - \max(Open_t, Close_t)) / (High_t - Low_t)$.
    *   If $d = -1$: $(\min(Open_t, Close_t) - Low_t) / (High_t - Low_t)$.
*   `bar_lower_wick_pct`: wick opposed to the trend direction:
    *   If $d = 1$: $(\min(Open_t, Close_t) - Low_t) / (High_t - Low_t)$.
    *   If $d = -1$: $(High_t - \max(Open_t, Close_t)) / (High_t - Low_t)$.
*   `bar_direction_aligned`: $+1$ if $(Close_t - Open_t) \times d > 0$, $-1$ if $< 0$, $0$ if $== 0$.

### B. Continuation / HH-LL State
*   `made_continuation_this_bar`: $1$ if $(High_t > High_{\text{prior\_max}})$ for bulls, or $(Low_t < Low_{\text{prior\_min}})$ for bears. Where the prior high/low is the best achieved in the regime up to bar $t-1$ (with reference price $P_{\text{ref}}$ as the initial prior max/min).
*   `failed_continuation_this_bar`: $1 - \text{made\_continuation\_this\_bar}$.
*   `bars_since_last_continuation`: count of bars since the last continuation.
*   `consecutive_no_continuation_bars`: count of consecutive bars up to $t$ where continuation failed.
*   `continuation_count_so_far`: cumulative count of continuation bars in the regime up to $t$.
*   `prior_bar_made_continuation`: `made_continuation` of bar $t-1$ (0 for $t=1$).
*   `prior_bar_failed_continuation`: `failed_continuation` of bar $t-1$ (0 for $t=1$).

### C. Pullback / Recovery State
*   `current_pnl_atr`: $(Close_t - P_{\text{ref}}) \times d / ATR_{\text{ref}}$.
*   `mfe_so_far_atr`: $(High_{\text{max\_so\_far}} - P_{\text{ref}}) \times d / ATR_{\text{ref}}$.
*   `mae_so_far_atr`: $(P_{\text{ref}} - Low_{\text{min\_so\_far}}) \times d / ATR_{\text{ref}}$.
*   `pullback_from_peak_atr`: $\text{mfe\_so\_far\_atr} - \text{current\_pnl\_atr}$.
*   `pullback_depth_current_bar_atr`: current bar pullback relative to prior peak MFE:
    *   For bulls: $\max(0, High_{\text{prior\_max}} - Low_t) / ATR_{\text{ref}}$.
    *   For bears: $\max(0, High_t - Low_{\text{prior\_min}}) / ATR_{\text{ref}}$.
*   `max_pullback_depth_so_far_atr`: max of `pullback_from_peak_atr` at bar closes up to $t$.
*   `recovered_prior_peak_this_bar`: $1$ if the current bar high/low touched or exceeded prior MFE peak after a pullback was established on the prior bar.
*   `recovered_above_prior_bar_midpoint`: $1$ if current close is above the prior bar midpoint in trend direction:
    *   For bulls: $Close_t > (High_{t-1} + Low_{t-1}) / 2$.
    *   For bears: $Close_t < (High_{t-1} + Low_{t-1}) / 2$.
*   `recovered_above_prior_bar_close`: $1$ if current close is above the prior bar close in trend direction:
    *   For bulls: $Close_t > Close_{t-1}$.
    *   For bears: $Close_t < Close_{t-1}$.

### D. Sequence Pattern Features
*   **Symbolic Alphabet mapping for any bar $i$:**
    *   `C` (Continuation): if `made_continuation_this_bar == 1`.
    *   `F` (Failure): if `made_continuation_this_bar == 0` and PnL is negative (`current_pnl_atr < 0`).
    *   `R` (Recovery): if `made_continuation_this_bar == 0` and it closed positive vs. prior close and prior bar close had a pullback (`(Close_i - Close_{i-1}) * d > 0` and `pullback_from_peak_atr_{i-1} > 0`).
    *   `P` (Pullback): if none of the above (no continuation, positive PnL vs entry, no recovery close).
*   `last_1_bar_pattern`: symbol of bar $t$.
*   `last_2_bar_pattern`: symbol of bar $t-1$ + symbol of bar $t$.
*   `last_3_bar_pattern`: symbol of bar $t-2$ + symbol of bar $t-1$ + symbol of bar $t$.
*   *Booleans:* `bar1_pulled_back`, `bar1_deep_pullback_gt_0p25`, `bar1_deep_pullback_gt_0p50`, `bar1_no_continuation`, `first_two_bars_no_continuation`, `first_three_bars_no_continuation`.

### E. 5s Context at 1m Bar Close
*   `regime_5s_aligned`: $1$ if current 5s regime direction matches $d$, else $0$.
*   `regime_5s_direction`: current 5s regime direction ($+1$, $-1$, $0$).
*   `5s_flip_count_since_1m_start`: count of 5s regime flips since 1m start.
*   `5s_opposed_flip_count_since_1m_start`: count of 5s flips opposed to 1m direction.
*   `5s_current_aligned_duration_s`: seconds aligned if currently aligned.
*   `5s_flips_last_60s`: flips count in last 60s.
*   `5s_flips_last_120s`: flips count in last 120s.

### F. EMA / Slope Context
*   `distance_to_emaX_atr` ($X \in \{3, 9, 13, 21\}$): $(Close_t - EMA\_X_t) \times d / ATR_{\text{ref}}$.
*   `emaX_slope_atr`: slope of EMA normalized by $ATR_{\text{ref}}$.
*   `emaX_slope_change`: acceleration of slope.
*   `ema3_ema9_spread_atr`: $(EMA\_3_t - EMA\_9_t) \times d / ATR_{\text{ref}}$.
*   `ema9_ema21_spread_atr`: $(EMA\_9_t - EMA\_21_t) \times d / ATR_{\text{ref}}$.

### G. Volume State
*   `bar_volume`: volume of the 1m bar.
*   `bar_volume_vs_20avg`: $Volume_t / Volume_{\text{rolling\_20\_avg}}$.
*   `volume_percentile_20`: volume percentile over the last 20 bars.
*   `signed_volume_proxy`: $Volume_t \times \text{sign}(Close_t - Open_t) \times d$.
*   `cum_signed_volume_since_regime_start`: cumulative sum of signed volume.
*   `aligned_volume_since_regime_start`: sum of volume where $(Close_i - Open_i) \times d > 0$.
*   `opposed_volume_since_regime_start`: sum of volume where $(Close_i - Open_i) \times d < 0$.
*   `aligned_opposed_volume_ratio`: ratio of aligned to opposed volume.

---

## Forward Labels

### A. Next-Bar Labels
*   `next_bar_makes_continuation`: $1$ if bar $t+1$ makes a continuation.
*   `next_bar_close_positive`: $1$ if $(Close_{t+1} - Close_t) \times d > 0$.
*   `next_bar_return_atr`: $(Close_{t+1} - Close_t) \times d / ATR_{\text{ref}}$.
*   `next_bar_range_atr`: $(High_{t+1} - Low_{t+1}) / ATR_{\text{ref}}$.

### B. Next-N-Bar Labels ($N \in \{2, 3, 5\}$)
*   `next_N_bars_make_continuation`: $1$ if any bar in $t+1$ to $t+N$ has `made_continuation_this_bar == 1`.
*   `next_N_bars_recover_prior_peak`: $1$ if any bar in $t+1$ to $t+N$ touches or exceeds the MFE peak at bar $t$.
*   `next_N_bars_net_positive`: $1$ if $(Close_{t+N} - Close_t) \times d > 0$.
*   `next_N_bars_max_favorable_atr`: max favorable excursion from $Close_t$ normalized by $ATR_{\text{ref}}$.
*   `next_N_bars_max_adverse_atr`: max adverse excursion from $Close_t$ normalized by $ATR_{\text{ref}}$.

### C. First-Passage Labels
Swept on the future 1s path starting from $Close_t$:
*   `pt025_before_sl025`, `pt050_before_sl050`, `pt100_before_sl100`, `pt200_before_sl100`.
*   *Exit Rules:* If parent 1m regime flips against the direction ($regime_{1m} == -d$), the trade is closed at the open of the first 1s bar of the new regime.
*   *Friction:* $5.00 round-trip commission. Market exits (stops, regime flips, forced exit) incur 0.5-tick slippage ($2.50). Limit profit targets (PT) incur zero slippage.
*   `race_resolution_time_s`: seconds from $Close_t$ to exit.
*   `race_resolution_reason`: `"pt"`, `"sl"`, `"opposite_1m_regime"`, `"end_of_data"`.

### D. Regime-End Labels
*   `forward_pnl_to_regime_exit_atr`: $(ExitPrice - Close_t) \times d / ATR_{\text{ref}}$.
*   `forward_pnl_to_regime_exit_dollars`: `forward_pnl_to_regime_exit_atr` $\times ATR_{\text{ref}} \times 20.0$.
*   `future_mfe_from_here_atr`: max excursion in trend direction from $Close_t$ to exit.
*   `future_mae_from_here_atr`: max excursion opposed to trend direction from $Close_t$ to exit.
*   `regime_exit_in_next_1_bar`: $1$ if `bars_remaining_until_regime_exit == 1`.
*   `regime_exit_in_next_2_bars`: $1$ if `bars_remaining_until_regime_exit <= 2`.
*   `regime_exit_in_next_3_bars`: $1$ if `bars_remaining_until_regime_exit <= 3`.
