# Specification: NQ Fair Pricing Theory — Anchor Reversion and Entry Confirmation

Derived from [`research_decision.yaml`](file:///C:/Users/Scott%20McCarty/Projects/Nautilus%20Trader-nq_fair_pricing_reversion/studies/nq_fair_pricing_reversion/research_decision.yaml).
**Study ID:** `nq_fair_pricing_reversion`  
**Dataset:** `NQ_1S_V2_GLOBEX` (XCME Globex equity calendar schedule)  

---

## 1. Research Question & Primary Hypotheses

**Question:** Does NQ exhibit a statistically meaningful tendency to revisit its regular-session opening price following intraday displacement, and do displacement-candle or confirmed BOS entries improve subsequent reversion outcomes?

* **H1 — Anchor Reversion (A0 Control):** The probability and timing of a return to the regular-session opening price vary systematically with displacement distance, elapsed session time, and intraday market conditions.
* **H2 — Displacement Confirmation (A1 Signal):** Opposite-direction displacement candle identification (opposite color, body expansion, wick break, toward anchor) improves subsequent reversion outcomes.
* **H3 — BOS Confirmation (A2 Signal):** 3-bar swing break confirmation (BOS break strictly after pivot confirmation, toward anchor) improves subsequent reversion outcomes.
* **H4 — Trend-Day Failure:** Persistent directional sessions exhibit materially lower anchor-return probabilities (evaluated strictly causally).

---

## 2. Anchor, Session & Observation Population

### 2.1 Anchor Definition & Availability
* **Anchor Price ($P_{\text{anchor}}$):** Opening price of the first completed RTH 1-minute bar at or after 09:30 America/New_York.
* **Timezone Authority:** Evaluated dynamically using `America/New_York` timezone rules against the CME Globex calendar.
* **Earliest Availability:** 09:31:00 America/New_York ($ts\_init$ of the first completed 1m bar).
* **Invariance:** Strictly immutable across the session.

### 2.2 Session Calendar & Observation Window
* **Session Standard Hours:** 08:30:00 to 15:15:00 America/Chicago (09:30:00 to 16:15:00 America/New_York).
* **Observation / Signal Decision Window:** Completed 1m bars from 09:31:00 through 11:00:00 America/New_York ($0 \le \text{elapsed\_seconds} \le 5400\text{s}$).
* **Executable Entry Cutoff:** 11:00:00 America/New_York. The executable entry fill occurs at `next_bar_open`. If the next actual executable print occurs after 11:00:00 ET, the entry is strictly rejected (`ENTRY_PAST_CUTOFF`).
* **Mandatory Flat Session Cutoff:** 11:30:00 America/New_York. Active trades/outcomes are forcefully flattened; outcomes reaching 11:30:00 ET resolve via `TIMEOUT` (or `SESSION_END` if shortened).

### 2.3 Arms & Signals
* **A0 (Observational Control):** All eligible 1-minute checkpoints within 09:31–11:00 ET with non-zero displacement toward anchor.
* **A1 (Displacement Candle):** Completed 1m displacement candle (opposite color, body expansion over prior body, close breaks prior wick extreme, direction toward anchor). Tracker: `tracker.candle.displacement_1m`.
* **A2 (Structure BOS):** 3-bar swing pivot confirmed at 3rd bar, BOS break strictly after confirmation bar, direction toward anchor. Tracker: `tracker.structure.bos_1m`.

### 2.4 Displacement & Recovery Direction
* **Displacement Calculation:** $\Delta_T = P_T - P_{\text{anchor}}$.
* **Displacement Direction:** $\text{sign}(\Delta_T) \in \{+1, -1\}$.
* **Recovery Direction:** $-\text{sign}(\Delta_T)$:
  - If $P_T > P_{\text{anchor}}$ ($\text{sign} = +1$): Recovery direction is $-1$ (short reversion).
  - If $P_T < P_{\text{anchor}}$ ($\text{sign} = -1$): Recovery direction is $+1$ (long reversion).
* **Zero-Displacement Eligibility:** Observations where $P_T == P_{\text{anchor}}$ ($\Delta_T = 0$) are **strictly ineligible**.
* **Regime Role:** `regime_1m.dir` is preserved strictly as causal context, never used as recovery direction.

---

## 3. Forward Outcomes & Barrier Arms

### 3.1 Outcome Setup & Cutoffs
* **Entry Reference:** `next_bar_open`.
* **Entry Cutoff:** `11:00:00 America/New_York`.
* **Session Cutoff:** `11:30:00 America/New_York`.
* **Max Tape Gap:** 60s.

### 3.2 Barrier Arms
1. **Milestone Recovery Arms:** 25%, 50%, 75%, 100% recovery toward anchor.
2. **Fixed Point Bracket Arm:** 38 points take profit / 25 points stop loss (`tp38_sl25`).
3. **Anchor Target Bracket Arm:** Target at anchor reference price / 25 points stop loss (`anchor_tp_sl25`). Checks for `ANCHOR_ALREADY_CROSSED` at entry fill.

---

## 4. Chronology & Governance

* **TRAIN Partitions:** `2021`, `2022`, `2023`.
* **DEV (OOS) Reserved:** `2024`.
* **Prohibited Reserved:** `2025`, `2026`.
* **Smoke Date:** `2023-10-02`.
