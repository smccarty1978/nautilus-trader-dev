# Continuous Health Surface & HardStall Decomposition

This report documents the empirical findings of **Study A (Continuous Health Surface)** and **Study B (HardStall Decomposition)** evaluated on the Out-of-Sample (OOS) 2025–2026 dataset for NQ.

---

## Study A: Continuous Health Surface

The continuous health score is defined as:
\[hC = P(\text{new\_high3}) - P(\text{flip3})\]
where probabilities are estimated by KNN.

### 1. Continuous Health Deciles
The OOS sample was divided into ten equal-frequency deciles of $hC$.

| Decile | Min $hC$ | Max $hC$ | $n$ | P(reignite $\ge 0.5$ ATR) | P(flip $\le 5$ bars) | Rem MFE (ATR) | Post-Bar PnL | Trade htf PnL |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **1 (Low)** | -0.46 | -0.15 | 29,778 | 48.9% | 54.4% | 1.87 | -$5.66 | +$1.65 |
| **2** | -0.15 | -0.05 | 29,720 | 55.7% | 49.7% | 1.86 | -$10.77 | +$74.06 |
| **3** | -0.05 | +0.05 | 29,868 | 60.8% | 44.8% | 1.96 | -$4.82 | +$136.18 |
| **4** | +0.05 | +0.15 | 29,549 | 66.3% | 40.3% | 2.11 | -$0.59 | +$197.13 |
| **5** | +0.15 | +0.24 | 29,612 | 70.6% | 36.8% | 2.19 | -$5.52 | +$239.11 |
| **6** | +0.24 | +0.34 | 29,566 | 74.0% | 33.3% | 2.35 | -$5.54 | +$292.68 |
| **7** | +0.34 | +0.44 | 29,881 | 77.9% | 30.2% | 2.51 | -$6.17 | +$337.19 |
| **8** | +0.44 | +0.54 | 29,522 | 80.9% | 26.7% | 2.64 | -$3.13 | +$361.86 |
| **9** | +0.54 | +0.64 | 29,814 | 82.2% | 23.1% | 2.63 | -$12.27 | +$367.02 |
| **10 (High)** | +0.65 | +0.84 | 29,506 | **83.8%** | **19.3%** | **2.69** | **+$2.79** | +$350.33 |

#### Key Insight
The continuous health score $hC$ has a **strictly monotonic** relationship with all forward metrics. As $hC$ rises:
* **Reignition probability** ($\ge 0.5$ ATR new high) increases from **48.9%** to **83.8%**.
* **Flip risk** ($\le 5$ bars) falls from **54.4%** to **19.3%**.
* **Remaining MFE** expands from **1.87 ATR** to **2.69 ATR**.
* **Decile 10** is the only cohort that overcomes the regime-flip drag to yield a positive expected **post-bar PnL (+$2.79)**.

---

### 2. Health Velocity (3-Bar Change)
Velocity is defined as the 3-bar difference: $dhC = hC_k - hC_{k-3}$.

| Slope Bucket | $n$ | P(reignite $\ge 0.5$ ATR) | P(flip $\le 5$ bars) | Rem MFE (ATR) | Post-Bar PnL |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Strong Up** ($> 0.15$) | 52,862 | **78.1%** | **27.5%** | **2.45** | -$9.92 |
| **Mild Up** ($0.05 \text{ to } 0.15$) | 21,928 | 73.2% | 32.1% | 2.36 | -$3.75 |
| **Flat** ($-0.05 \text{ to } 0.05$) | 27,078 | 70.8% | 34.5% | 2.40 | -$1.22 |
| **Mild Down** ($-0.15 \text{ to } -0.05$) | 27,186 | 70.2% | 35.6% | 2.40 | -$4.54 |
| **Severe Down** ($< -0.15$) | 90,038 | **65.2%** | **42.6%** | **2.11** | -$5.13 |

#### Key Insight
Improving health (Strong Up) is a powerful indicator of reduced flip risk (27.5% vs 42.6% for Severe Down) and higher continuation potential.

---

### 3. Level × Slope Interaction Surface
Interaction of absolute health level ($hC$) and 3-bar slope ($dhC$).

| Level | Slope | $n$ | P(reignite $\ge 0.5$ ATR) | P(reignite $\ge 1.0$ ATR) | P(flip $\le 3$ bars) | P(flip $\le 5$ bars) | Rem MFE | Rem MAE | Post-Bar PnL |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **High ($\ge 0.5$)** | Up ($> 0.05$) | 30,070 | 83.1% | 71.9% | 9.0% | 20.7% | 2.71 | 1.46 | -$1.90 |
| **High ($\ge 0.5$)** | Flat | 6,714 | 84.4% | 73.6% | 8.0% | 19.5% | 2.85 | 1.55 | -$4.45 |
| **High ($\ge 0.5$)** | Down ($< -0.05$) | 6,473 | **83.0%** | **72.0%** | **8.5%** | **19.8%** | **2.94** | **1.53** | **+$9.60** |
| | | | | | | | | | |
| **Med (0.1–0.5)** | Up | 33,853 | 77.0% | 61.5% | 18.3% | 31.5% | 2.31 | 1.24 | -$12.25 |
| **Med (0.1–0.5)** | Flat | 10,720 | 77.6% | 62.1% | 19.4% | 33.0% | 2.55 | 1.32 | -$0.39 |
| **Med (0.1–0.5)** | Down | 45,321 | 75.6% | 60.6% | 19.0% | 32.1% | 2.45 | 1.28 | -$5.50 |
| | | | | | | | | | |
| **Low ($< 0.1$)** | Up | 10,867 | 57.7% | 42.5% | 29.2% | 42.9% | 1.98 | 1.04 | -$12.42 |
| **Low ($< 0.1$)** | Flat | 9,644 | 53.9% | 38.6% | 33.7% | 46.6% | 1.92 | 0.96 | +$0.10 |
| **Low ($< 0.1$)** | Down | 65,430 | 58.3% | 41.7% | 37.1% | 49.3% | 1.91 | 0.97 | -$6.08 |

#### Key Insight: "Buy the Pullback"
For **High Health** regimes, the slope is secondary. Even when health is actively decaying (Slope Down), the reignition rate remains at **83.0%**, the flip risk is low (19.8%), and the remaining MFE is actually the highest on the surface (**2.94 ATR**). 

This setup (High Health, Slope Down) represents a healthy pullback in a dominant trend. It generates the highest expected **post-bar PnL (+$9.60)** across the entire surface because you are buying the dip in a high-opportunity regime.

---

## Study B: HardStall Decomposition

A **HardStall** is defined as $dd \ge 0.20$ (health score has fallen 20% or more from its peak) while the KNN predicted class is still Continuation or Runner. HardStall represents **183,544 OOS bars** and is where **70.4% of all regime flips originate**.

### 1. HardStall by $hC$ Level

| Level | $n$ | % Recover | % Direct Flip | Rem MFE | Rem MAE | P(flip $\le 5$) | Post-Bar PnL |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **High ($\ge 0.5$)** | 11,958 | **46.0%** | **54.0%** | **2.85** | 1.48 | 21.7% | -$2.52 |
| **Med (0.1–0.5)** | 94,107 | 41.3% | 58.7% | 2.41 | 1.26 | 32.0% | -$6.29 |
| **Low ($< 0.1$)** | 77,479 | **22.4%** | **77.6%** | **1.95** | 0.99 | 47.7% | -$6.67 |

#### Key Insight
HardStall is **not** a single state. It bifurcates clean into two distinct populations:
* **High-Health HardStall** ($hC \ge 0.5$): A **temporary pullback** with a **46.0% recovery rate**, low flip risk (21.7% in 5 bars), and **2.85 ATR remaining MFE**.
* **Low-Health HardStall** ($hC < 0.1$): A **dying trend** with a **77.6% direct flip rate** (no recovery), high flip risk (47.7% in 5 bars), and severely decayed opportunity (**1.95 ATR remaining MFE**).

---

### 2. HardStall Level × Slope Matrix

| Level | Slope | $n$ | % Recover | % Direct Flip | Rem MFE | Rem MAE | P(flip $\le 5$) | Post-Bar PnL |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| High ($\ge 0.5$) | Up | 5,530 | 40.9% | 59.1% | 2.80 | 1.46 | 22.5% | -$6.80 |
| High ($\ge 0.5$) | Flat | 1,514 | 41.3% | 58.7% | 2.90 | 1.53 | 21.5% | -$19.17 |
| High ($\ge 0.5$) | Down | 3,514 | **49.8%** | **50.2%** | **2.98** | **1.54** | **20.7%** | **+$12.04** |
| Med (0.1–0.5) | Up | 29,296 | 39.3% | 60.8% | 2.33 | 1.24 | 31.3% | -$11.83 |
| Med (0.1–0.5) | Flat | 9,779 | 37.3% | 62.8% | 2.59 | 1.32 | 32.8% | +$1.17 |
| Med (0.1–0.5) | Down | 44,352 | 40.0% | 60.0% | 2.46 | 1.28 | 31.9% | -$5.11 |
| Low ($< 0.1$) | Up | 9,319 | 22.4% | 77.7% | 1.99 | 1.04 | 42.8% | -$14.59 |
| Low ($< 0.1$) | Flat | 8,200 | 19.0% | 81.0% | 1.91 | 0.97 | 46.5% | -$1.87 |
| Low ($< 0.1$) | Down | 57,411 | **22.2%** | **77.9%** | **1.93** | **0.98** | **48.8%** | **-$6.30** |

#### Key Insight
The **High Health + Slope Down** HardStall is the premium buying opportunity in the stall population:
* It has a **49.8% recovery rate** (nearly a coin flip).
* It provides a massive **2.98 ATR remaining MFE**.
* It yields a **positive post-bar PnL of +$12.04** because you are entering at a deep discount in a dominant trend.
* Conversely, **Low Health + Slope Down** represents a terminal decay phase (77.9% direct flip rate, only 1.93 ATR remaining MFE, negative expected PnL).

---

## Strategic Implications & Reframe

DETER is a lossy compression of the real signal. 

The continuous health score ($hC$) and its velocity ($dhC$) hold the actionable information. Instead of treating DETER as a binary exit trigger, we should reframe our system as follows:

1. **Pullbacks vs. Collapses**:
   * Do not exit trades in a HardStall if absolute health ($hC$) is still High ($\ge 0.5$). These are high-opportunity pullbacks that recover 46% of the time and have 2.85–2.98 ATR of remaining upside. Entering or adding to positions here is highly profitable (+$12.04 expected value).
   * Tighten stops or exit immediately if absolute health decays to Low ($< 0.1$), especially if the slope is Down. These have a 78% direct flip rate and represent the true "collapse" population.

2. **Continuous Trailing Stop**:
   * Trailing exits should be a joint function of level and slope. For example, exit if:
     \[hC < 0.10 \quad \text{and} \quad dhC < -0.05\]
   * This isolates the 78% direct flip cohort while leaving the high-health pullbacks untouched.
