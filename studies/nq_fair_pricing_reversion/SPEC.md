# Specification: NQ Fair Pricing Theory — Anchor Reversion and Entry Confirmation

Derived from [`research_decision.yaml`](file:///C:/Users/Scott%20McCarty/Projects/Nautilus%20Trader-nq_fair_pricing_reversion/studies/nq_fair_pricing_reversion/research_decision.yaml).
**Study ID:** `nq_fair_pricing_reversion`  
**Dataset:** `NQ_1S_V2_GLOBEX` (XCME Globex equity calendar schedule)  

---

## 1. Research Question & Primary Hypotheses

**Question:** Does NQ exhibit a statistically meaningful tendency to revisit its regular-session opening price following intraday displacement, and do displacement-candle or confirmed BOS entries improve subsequent reversion outcomes?

* **H1 — Anchor Reversion:** The probability and timing of a return to the regular-session opening price vary systematically with displacement distance, elapsed session time, and intraday market conditions.
* **H2 — Displacement Confirmation (A1 - Deferred):** Opposite-direction displacement candle identification.
* **H3 — BOS Confirmation (A2 - Deferred):** 3-bar swing break confirmation.
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
* **Observation Window:** 09:31:00 through 11:00:00 America/New_York.
* **Boundary Inclusion:** The 1-minute bar closing exactly at 11:00:00 ET is **INCLUDED**. No candidate is emitted with $ts\_init > 11:00:00\text{ ET}$.
* **Elapsed Seconds:** $0 \le \text{elapsed\_seconds} \le 5400\text{s}$.

### 2.3 Displacement & Recovery Direction
* **Displacement Calculation:** $\Delta_T = P_T - P_{\text{anchor}}$.
* **Displacement Direction:** $\text{sign}(\Delta_T) \in \{+1, -1\}$.
* **Recovery Direction:** $-\text{sign}(\Delta_T)$:
  - If $P_T > P_{\text{anchor}}$ ($\text{sign} = +1$): Recovery direction is $-1$ (short reversion).
  - If $P_T < P_{\text{anchor}}$ ($\text{sign} = -1$): Recovery direction is $+1$ (long reversion).
* **Zero-Displacement Eligibility:** Observations where $P_T == P_{\text{anchor}}$ ($\Delta_T = 0$) are **strictly ineligible**.
* **Regime Role:** `regime_1m.dir` is preserved strictly as causal context, never used as recovery direction.

### 2.4 Population Strata
* **Reporting Strata:** 20.0, 40.0, 60.0, 80.0 NQ points and 1.0, 1.5, 2.0 ATR(14) units. These are predetermined descriptive strata, not optimized gates.

---

## 3. Forward Outcomes & Recovery Milestones

### 3.1 Frozen Decision-Time State
At candidate instant $T$, freeze:
* $P_{\text{anchor}}$
* $P_T$ (close of bar $T$)
* $\text{displacement\_direction}$
* $|\Delta_T| = |P_T - P_{\text{anchor}}|$
* Recovery price thresholds:
  - $P_{25} = P_T - \text{sign}(\Delta_T) \times (0.25 \times |\Delta_T|)$
  - $P_{50} = P_T - \text{sign}(\Delta_T) \times (0.50 \times |\Delta_T|)$
  - $P_{75} = P_T - \text{sign}(\Delta_T) \times (0.75 \times |\Delta_T|)$
  - $P_{100} = P_{\text{anchor}}$

### 3.2 Denominator Invariance & Touch Definition
* The denominator $|\Delta_T|$ remains immutable; future price extrema never redefine it.
* **Touch Definition:** Exact market-price touch or crossing of completed bar high/low:
  - Short recovery: $\text{low}_t \le P_{\text{target}}$.
  - Long recovery: $\text{high}_t \ge P_{\text{target}}$.
* Evaluated at 0.25 tick precision without artificial tolerance.

### 3.3 Horizon & Censoring
* **Forward Observation Span:** The earlier of declared horizon or actual RTH calendar close (15:15 CT / 16:15 ET or scheduled early close).
* Candidate emission ends at 11:00 ET; forward tracking continues through RTH close.
* **Independent Milestone Resolution:** Each milestone (25%, 50%, 75%, 100%) resolves independently.
* **Censoring Semantics:** An unresolved milestone at session close is stamped `SESSION_END_CENSORED`, never recorded as failure.
* **Gap Censoring:** Tape gap $> 60\text{s}$ censors as `GAP`.

---

## 4. Chronology & Governance

* **TRAIN Partitions:** `2021`, `2022`, `2023`.
* **DEV (OOS) Reserved:** `2024`.
* **Prohibited Reserved:** `2025`, `2026`.
* **Smoke Date:** `2023-10-02`.
