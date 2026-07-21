# DETER State Dynamics & Reignition Analysis

This report evaluates the behavior of the **DETER** (Deteriorated) state in the NQ Regime DNA KNN study. It resolves the inconsistency between how the state was historically described ("imminent regime flip") and how it empirically behaves in our Out-of-Sample (OOS) 2025–2026 data.

---

## Executive Summary: The Inconsistency Resolved

DETER is **not** an imminent death signal. 

The data shows that DETER is a **temporary, low-opportunity congestion state** that represents a highly volatile decision point. When a trade enters DETER:
* It has a **51.2% chance of experiencing a full recovery** back to a Healthy or Soft Stall state before the regime flips.
* Even under a strict definition of "reignite" (requiring a new high by at least **0.50 ATR**), **51.3%** of DETER bars still achieve it.
* Only **24.3% of regimes actually flip (die) from the DETER state**; the vast majority (**70.4%**) flip directly from **HardStall**.

This explains why naive scale-out policies on DETER warnings show poor performance: they cut profits on the 64% of cases that recover (averaging **+$104.85** from the warning bar to the end of the trade) while still taking large losses on the 36% that collapse straight to the flip (averaging **-$188.92**).

---

## 1. What Exactly is "Reignite"?
The table below breaks down the probability of a trade making a new favorable high after being in a given state, at various epsilon thresholds (expressed in ATR).

### Reignition Rate by Epsilon (OOS 2025–2026)
| State | n | $\ge 0.00$ ATR (1 tick) | $\ge 0.05$ ATR (current) | $\ge 0.10$ ATR | $\ge 0.25$ ATR | $\ge 0.50$ ATR | $\ge 1.00$ ATR |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Healthy** | 55,443 | 93.7% | 93.1% | 91.9% | 88.4% | 82.0% | 68.5% |
| **SoftStall** | 15,757 | 92.4% | 91.9% | 90.8% | 87.8% | 82.8% | 70.5% |
| **HardStall** | 183,544 | 78.0% | 77.6% | 76.8% | 74.3% | 69.7% | 54.1% |
| **DETER** | 42,072 | **73.5%** | **72.2%** | **69.6%** | **62.6%** | **51.3%** | **35.9%** |

### Key Takeaway
Even when requiring a material breakout of **0.50 ATR** above the prior high, **51.3% of DETER bars still reignite**. At **1.00 ATR**, more than **1-in-3 (35.9%)** reignite. 

DETER is indeed less explosive than Healthy (which has an 82% chance of a 0.50 ATR breakout), but it is a coin flip for a material continuation, not a dead trend.

---

## 2. DETER Flip Horizons
When a trade is in a DETER state, what percentage of the time does it flip within $N$ bars?

* **Flip within 1 bar**: **16.3%**
* **Flip within 3 bars**: **34.9%**
* **Flip within 5 bars**: **47.3%**
* **Flip within 10 bars**: **67.2%**

### Key Takeaway
DETER does not represent immediate danger. There is an **83.7% chance** that the regime survives the next bar, and a **52.7% chance** it survives the next 5 bars.

---

## 3. State Path: Recovery vs. Direct Flip
Of all DETER bars:
* **Recover back to Healthy or SoftStall**: **51.2%**
* **Stay in HardStall/DETER until flip**: **48.8%**

This is almost a perfect 50/50 split. A trade in DETER is just as likely to return to a fully healthy, productive state as it is to remain bogged down until the regime flips.

---

## 4. DETER Episode Frequency & Lifetime
* **Total OOS Regimes**: 28,191
* **Regimes hitting DETER**: 17,349 (**61.5%**)

### Among regimes that ever hit DETER:
* **Average DETER bars**: 2.43 (Median: 2.0)
* **Average DETER episodes**: 1.18 (Median: 1.0)

### Episode Distribution:
* **1 episode**: **83.8%**
* **2 episodes**: **14.5%**
* **3 episodes**: **1.7%**
* **4 episodes**: **0.1%**

### Key Takeaway
DETER is overwhelmingly a **one-time transition phase** (83.8% of cases) rather than a state that the trade repeatedly enters and exits. The typical DETER phase lasts about 2 to 3 bars.

---

## 5. Terminal State at the Flip
What state is the regime in on the **very last bar** before the opposite flip?

* **HardStall**: **19,834 trades (70.4%)**
* **DETER**: **6,838 trades (24.3%)**
* **Healthy**: **1,184 trades (4.2%)**
* **SoftStall**: **335 trades (1.2%)**

### Key Takeaway
This is a major finding. **70.4% of trades die in HardStall**, not DETER. 

In these cases, the KNN model continues to predict a Continuation or Runner (so the state does not register as DETER), but because the trade has stalled or pulled back, the health indicator `hC` is in a deep drawdown. Only **24.3%** of trades actually flip directly from DETER.

---

## 6. Realized PnL & Price Change from DETER Bars

### Expected Value of Holding from DETER Bar:
* **To Terminal Flip**: Avg Price Change **-0.02 ATR** (Avg PnL **-$1.84**, Median **-$70.00**)
* **To Next State Transition**: Avg Price Change **-0.01 ATR** (Avg PnL **-$0.65**, Median **+$20.00**)

### Breakdown by Transition Outcome:
* **Transitioned to another state** (64.1% of DETER bars, $n=26,963$):
  * **Avg Price Change to end**: **+0.58 ATR**
  * **Avg PnL Change to end**: **+$104.85** (Median **+$70.00**)
* **Went straight to Flip** (35.9% of DETER bars, $n=15,109$):
  * **Avg Price Change to end**: **-1.06 ATR**
  * **Avg PnL Change to end**: **-$188.92** (Median **-$130.00**)

### Key Takeaway
DETER is a high-volatility branching point. If the trade manages to transition to another state, it captures a highly profitable continuation (+0.58 ATR). If it fails to transition and goes straight to the flip, it suffers a major drop (-1.06 ATR). 

Because the expected value is nearly flat (average PnL change of -$1.84), exiting immediately on DETER is not a clear win—it converts a high-volatility, positive-expectation recovery path into a certain exit, sacrificing the runners.

---

## Strategic Implications: Scenario A vs. Scenario B

The data heavily supports **Scenario B**:
```
Healthy ↔ Stall ↔ DETER ↔ Reignite / Flip
```
Where DETER is a temporary congestion phase from which the trade has a 51.2% chance of recovering back to a healthy state. 

### Why this changes our approach:
1. **DETER is not an exit signal.** Treating it as a hard exit or scale-out signal degrades the profit factor because you cut the legs off trades that are simply pausing before a major continuation (+0.58 ATR on average).
2. **KNN is an opportunity-state monitor.** KNN excels at telling us where we are in the trend lifecycle. 
3. **Operational Use**: Instead of exiting on DETER, we can use it to **adjust our expectations and risk controls**:
   * **Trailing Stops**: We can tighten or activate break-even stops *during* DETER to protect against the 36% of cases that drop -1.06 ATR.
   * **Re-entries**: If the trade transitions from DETER back to Healthy, it confirms a genuine trend restart, which may offer a high-quality re-entry or add-on point.
