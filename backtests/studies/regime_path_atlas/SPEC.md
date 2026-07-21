# 1m Regime Path Atlas Study Specification

## Objective

Build a conditional expectancy database and analyzer for NQ 1m regimes to verify the martingale hypothesis across price-conditioned cells and evaluate whether any non-price or interaction pockets contain edge. 

Instead of hand-crafting entry and exit rules, the **Regime Path Atlas** catalog-tracks every closed 1m bar (checkpoint) inside active 1m regimes to map the historical outcomes of those states.

---

## Population & Session

*   **Period:** 2021–2026 (2021–2024 Discovery/IS, 2025–2026 Validation/OOS).
*   **Session:** RTH-only (Central Time `[08:30, 15:00)`).
*   **Timeframe:** 1-minute parent regimes, tracked on a bar-by-bar basis up to a maximum duration of 30 bars (or until the parent regime exits).

---

## Checkpoint Features (Known at Bar Close)

For every active 1m regime, at the close of bar $t \in [1, 30]$ (where $t=1$ is the close of the first bar after the flip bar close), we snapshot the following features:

1.  **Regime Context:**
    *   `regime_id`: unique identifier for the parent regime (`year * 100_000 + index`).
    *   `bar_index`: the number of closed 1m bars since the regime start ($t$).
    *   `direction`: 1m regime direction ($+1$ for bullish, $-1$ for bearish).
    *   `time_since_flip`: seconds since the 1m regime start timestamp ($t \times 60$).

2.  **Path Excursion Metrics:**
    *   `current_pnl_atr`: `(current_close - entry_price) * direction / atr_1m_entry`.
    *   `mfe_so_far_atr`: `(max_price_in_regime - entry_price) * direction / atr_1m_entry` (using 1s high/low path).
    *   `mae_so_far_atr`: `(entry_price - min_price_in_regime) * direction / atr_1m_entry` (using 1s high/low path).
    *   `pullback_from_peak_atr`: `mfe_so_far_atr - current_pnl_atr`.
    *   `last_bar_hh_ll`: $1$ if the closed bar made a new high (for bullish) or new low (for bearish) for the regime so far; $0$ otherwise.
    *   `bars_since_last_hh_ll`: number of 1m bars since a new HH/LL was established.

3.  **5s Sub-Regime Context:**
    *   `5s_flip_count`: number of 5s regime flips since the 1m regime start.
    *   `5s_current_alignment`: $1$ if the current 5s regime matches the 1m regime, $-1$ if opposed, $0$ if neutral.

4.  **Trend & Volume Indicators:**
    *   `ema9_slope`: 1m EMA9 slope, normalized by `atr_1m_entry`.
    *   `ema9_slope_change`: 1m EMA9 slope acceleration/deceleration.
    *   `distance_to_ema9`: `(current_close - ema9_value) * direction / atr_1m_entry`.
    *   `volume_state`: current 1m bar volume divided by the rolling 20-period average of 1m volume.

---

## Forward Labels (Future Outcomes)

For each checkpoint, we compute the following forward-only labels on the future 1s price path:

1.  **Next Bar High/Low:**
    *   `next_bar_hh`: $1$ if the next 1m bar makes a new HH (if bullish) or LL (if bearish) relative to the high/low of the regime up to the current bar; $0$ otherwise.

2.  **Bracket Outcomes (First-Passage):**
    For each bracket $PT \times SL \in \{0.5\times0.5, 1.0\times1.0, 2.0\times1.0\}$:
    *   `reach_PT_before_SL`: $1$ if price reaches the positive target ($PT \times \text{ATR}$) before it reaches the stop-loss ($SL \times \text{ATR}$). $0$ otherwise.
    *   *Exit Constraint:* If the parent 1m regime flips against the trade direction, or the maximum holding time is reached, the trade is forced out at the open of the first 1s bar of the new regime.
    *   `net_ev_dollars`: realized profit/loss in dollars, net of $5.00 round-trip commission and 0.5-tick slippage ($2.50) on SL/forced exits. limit PT hits experience zero slippage.

3.  **Forward Regime Path:**
    *   `forward_pnl_to_regime_exit`: the net PnL from the current close to the regime's exit price, normalized by `atr_1m_entry`.

---

## Verification & Validation Discipline

*   **In-Sample (IS):** 2021–2024.
*   **Out-of-Sample (OOS):** 2025–2026.
*   **Overfitting Safeguards:**
    *   Tertile bucketing edges are computed exclusively on IS data and applied unchanged to OOS.
    *   **All-Year Stability Gate:** A cell is considered "robust" only if its net EV is positive (or its probability is strictly above the base rate) across all 6 years (2021–2026) individually.
    *   **Cell Size Constraints:** Single feature buckets must pool $\ge 500$ observations; 2-way interactions $\ge 300$; 3-way interactions $\ge 150$.
