# Specification: NQ Fair Pricing Theory — Anchor Reversion and Entry Confirmation

Derived from [`research_decision.yaml`](file:///C:/Users/Scott%20McCarty/Projects/Nautilus%20Trader-nq_fair_pricing_reversion/studies/nq_fair_pricing_reversion/research_decision.yaml).
**Study ID:** `nq_fair_pricing_reversion`  
**Dataset:** `NQ_1S_V2_GLOBEX` (XCME Globex equity calendar schedule)  

---

## 1. Research Question & Primary Hypotheses

**Question:** Does NQ exhibit a statistically meaningful tendency to revisit its regular-session opening price following intraday displacement, and do displacement-candle or confirmed BOS entries improve subsequent reversion outcomes?

* **H1 — Anchor Reversion:** The probability and timing of a return to the regular-session opening price vary systematically with displacement distance, elapsed session time, and intraday market conditions.
* **H2 — Displacement Confirmation:** A qualifying opposite-direction displacement candle identifies subsequent favorable reversion behavior beyond that observed for comparable displaced-price checkpoints without the signal.
* **H3 — BOS Confirmation:** A confirmed 3-bar swing break provides incremental predictive information relative to displacement-candle entries.
* **H4 — Trend-Day Failure:** Persistent directional sessions exhibit materially lower anchor-return probabilities and greater adverse excursions than balanced sessions (evaluated strictly via causal state known at observation time, never retrospective trend labels).

---

## 2. Anchor, Window & Observation Population

### 2.1 Anchor Definition & Timezone Legality
* **Anchor Price ($P_{\text{anchor}}$):** The opening price of the 09:30 America/New_York 1-minute bar.
* **Timezone Authority:** Evaluated dynamically using `America/New_York` timezone rules against the CME Globex calendar. EST is never hardcoded as UTC−5 across daylight saving transitions.
* **Invariance:** Once established at 09:30 bar open, the anchor remains constant throughout the session window.

### 2.2 Observation Window
* **Admissible Range:** 09:30:00 to 11:00:00 America/New_York (minutes 1 through 90 of RTH).
* **Early Closures & Halts:** Truncated if a scheduled early holiday closure occurs before 11:00 ET.
* **Cadence:** Completed 1-minute bars ($t$).

### 2.3 Observable State at Decision Time ($T$)
For each observation epoch $T$:
1. `observation_ts`: Nanosecond epoch of completed 1m bar close ($ts\_init$).
2. `rth_open`: The 09:30 ET opening price.
3. `close_px`: The close of bar $t$.
4. `displacement_points`: $P_t - P_{\text{anchor}}$.
5. `displacement_atr`: $(P_t - P_{\text{anchor}}) / \text{ATR}_{14}(1\text{m})$.
6. `elapsed_seconds`: Seconds since 09:30 open ($T - T_{\text{open}}$).
7. `running_session_high` / `running_session_low`: Causal extremes established since 09:30.
8. `displacement_direction`: $+1$ if $P_t > P_{\text{anchor}}$, $-1$ if $P_t < P_{\text{anchor}}$, $0$ if equal.
9. `candle_body_points`: $|\text{close}_t - \text{open}_t|$.
10. `causal_volatility_state`: 1m ATR(14) and 5m regime volatility.

---

## 3. Signal Families (A0, A1, A2)

### 3.1 A0 — Displacement Baseline
* Price is displaced by at least $D$ points (e.g. 20, 40, 60, 80 pts) or $K$ ATR (e.g. 1.0, 1.5, 2.0 ATR) away from $P_{\text{anchor}}$.
* Evaluated without requiring candle or swing confirmation.

### 3.2 A1 — Displacement Candle
* **Bearish Displacement Candle (Short Reversion when $P_t > P_{\text{anchor}}$):**
  - $\text{close}_t < \text{open}_t$ (bearish real body)
  - $|\text{close}_t - \text{open}_t| > |\text{close}_{t-1} - \text{open}_{t-1}|$ (body expansion)
  - $\text{close}_t < \text{low}_{t-1}$ (prior wick penetration)
* **Bullish Displacement Candle (Long Reversion when $P_t < P_{\text{anchor}}$):**
  - $\text{close}_t > \text{open}_t$ (bullish real body)
  - $|\text{close}_t - \text{open}_t| > |\text{close}_{t-1} - \text{open}_{t-1}|$ (body expansion)
  - $\text{close}_t > \text{high}_{t-1}$ (prior wick penetration)
* **Execution Reference:** First executable entry is strictly `next_bar_open` ($t+1$ open), never decision close.

### 3.3 A2 — Confirmed 3-Bar BOS (Break of Structure)
* **Fractal Swing Definition:**
  - Swing Low at $t-1$: $\text{low}_{t-1} < \text{low}_{t-2} \land \text{low}_{t-1} < \text{low}_t$. Confirmed only when bar $t$ completes.
  - Swing High at $t-1$: $\text{high}_{t-1} > \text{high}_{t-2} \land \text{high}_{t-1} > \text{high}_t$. Confirmed only when bar $t$ completes.
* **Swing Replacement & Expiration:**
  - The most recently confirmed swing high/low remains the active reference until replaced by a new confirmed swing high/low in that direction.
  - Active swings expire at the session boundary.
* **Structure Break Rule:**
  - Break must occur on a subsequent bar $t+k$ ($k \ge 1$) strictly after the confirmation bar $t$.
  - Short BOS: Completed 1m close $< \text{active\_swing\_low}$.
  - Long BOS: Completed 1m close $> \text{active\_swing\_high}$.
  - Break confirming bar is not permitted to be the swing-forming bar.

---

## 4. Forward Outcomes & Partial-Recovery Measurements

### 4.1 Descriptive Recovery Labels (Not Fill Economics)
For each observation at $T$ with displacement $D_T = |P_T - P_{\text{anchor}}|$:
1. **Full Anchor Return (100% Recovery):**
   - Touched when $\text{low} \le P_{\text{anchor}}$ (for short reversion) or $\text{high} \ge P_{\text{anchor}}$ (for long reversion).
2. **Partial Recoveries:**
   - 25% Recovery: Price retraces $0.25 \times D_T$ toward $P_{\text{anchor}}$.
   - 50% Recovery: Price retraces $0.50 \times D_T$ toward $P_{\text{anchor}}$.
   - 75% Recovery: Price retraces $0.75 \times D_T$ toward $P_{\text{anchor}}$.
3. **Time to Revisit:** Seconds from $T$ to the first bar touching the recovery level.
4. **MFE / MAE:** Maximum favorable and adverse excursion measured in points and ATR over the forward trajectory.
5. **Censoring:**
   - Observations reaching 11:00 ET without hitting target are recorded as `WINDOW_END_UNRESOLVED`.
   - Observations reaching session close (16:00/16:15 CT) without hitting target are recorded as `SESSION_END_CENSORED`.
   - Data gaps $> 60\text{s}$ are censored as `GAP`.

### 4.2 Separation of Market Touch vs. Executable Fills
* Exact market touch/crossing is an observational path property.
* Executable fills (Phase C backtesting) require NautilusTrader limit/stop simulation with bid/ask spreads, slippage, and queue ordering.

---

## 5. Chronology & Leakage Controls

* **TRAIN Partitions:** `2021`, `2022`, `2023`.
* **DEV (OOS) Reserved:** `2024` (declared in `chronology.dev`, untouched until freeze).
* **Prohibited Reserved:** `2025`, `2026` (never opened).
* **Smoke Date:** `2023-10-02` (single Globex session inside TRAIN).
