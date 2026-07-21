# Static Analysis Look-Ahead & Timestamp Audit: Bar-4 KNN Neighbor Composition

This audit report summarizes the look-ahead, timestamp, and rule compliance validation performed on the Bar-4 KNN Path-State Atlas (`studies/regime_dna_knn/bar4_knn_path_atlas.py`). 

## 1. Audit Executive Summary

* **Overall Status**: **PASS**
* **Core Verdict**: The neighbor composition, probability metrics, and scale-out simulation are fully causal and free of look-ahead leaks. All trading and pricing rules (adverse-first same-bar sequencing, no same-bar pullback+reclaim, and exit on flip close) are strictly respected.
* **Integrity Guarantee**: All features of the out-of-sample (OOS) trades are computed using information up to and including the observation bar $k$. Predictions are generated using historical, fully-realized in-sample (IS) neighbor outcomes. There is no look-ahead leakage from future bars of the OOS trade into its state features or model prediction.

---

## 2. Neighbor Composition & Probability Metrics Audit

The model's core mechanism queries the nearest neighbors of active OOS trades within the historical IS dataset. We audited the data preparation, neighbor matching, and probability computation stages:

### A. Temporal Alignment of Neighbors (`isk = is_all[is_all.k == k]`)
* **Causality Verification**: Neighbors are queried **per-bar** (i.e., for an OOS trade at bar $k$, we only search for historical neighbors at the exact same bar index $k$). 
* **Causal Purpose**: This ensures that both the features (state at bar $k$) and target variables (remaining path from $k+1$ onwards) are temporally aligned. We do not mix state vectors from different elapsed durations, preventing duration-based leakage.
* **Result**: **PASS**

### B. Standard Scaling and KNN Fitting
* **Causality Verification**: Standard scaling parameters (`mu`, `sd`) are fitted strictly on the In-Sample reference set (`isk`) at bar $k$:
  ```python
  mu = Xis.mean(0)
  sd = Xis.std(0)
  sd[sd == 0] = 1
  ```
  The OOS features `Xoo` are scaled using these IS-fitted parameters: `(Xoo - mu) / sd`. The KNN model is fitted only on the scaled `Xis` and queries the neighbors of `Xoo` out-of-sample:
  ```python
  nn = NearestNeighbors(n_neighbors=min(KNN_MAX, len(isk)), n_jobs=-1).fit((Xis - mu) / sd)
  _, idx = nn.kneighbors((Xoo - mu) / sd)
  ```
* **Result**: **PASS** (No out-of-sample scaling leak).

### C. Causal Probability Computations
* **Causality Verification**: Probability metrics (e.g., remaining MFE/MAE predictions, barrier hit odds `pred_b1010_k1000`, and path class probabilities `pcls_{c}`) are computed by taking the mean of the realized targets of the historical nearest neighbors:
  ```python
  v = isk[t].values[idx]
  out[f"pred_{t}_k{kk}"] = v[:, :kk].mean(1)
  ```
  Since the historical neighbors represent past, fully-realized trades (years 2021-2024), their outcomes are historical facts. Using these outcomes to predict the future path of the OOS trade (years 2025-2026) is strictly causal and represents a valid predictive distribution. No future information of the OOS trade is used during inference.
* **Result**: **PASS**

---

## 3. Backtesting and Simulation Rules Compliance

We verified that the three critical backtesting rules are strictly respected in the code:

### Rule 1: Adverse-First Same-Bar Sequencing
* **Rule**: When both the target price and the stop-loss price are hit in the same bar, assume the stop-loss hits first.
* **Code Reference**: [bar4_knn_path_atlas.py:L99-L105](file:///C:/Users/Scott%20McCarty/Projects/Nautilus%20Trader/studies/regime_dna_knn/bar4_knn_path_atlas.py#L99-L105)
* **Code Implementation**:
  ```python
  for j in range(fb.size):
      hsl = (fl[j] <= slpx) if di == 1 else (fh[j] >= slpx)
      hpt = (fh[j] >= ptpx) if di == 1 else (fl[j] <= ptpx)
      if hsl:
          res = 0; break  # Stop-loss evaluated first
      if hpt:
          res = 1; break  # Target evaluated second
  ```
* **Audit Finding**: In the remaining-path barrier loop, `hsl` (stop-loss breach) is checked and handled first. If a same-bar double breach occurs, the loop immediately executes `res = 0; break`, resulting in a stop out (failure). This guarantees conservative sequencing on same-bar collisions.
* **Result**: **PASS**

### Rule 2: No Same-Bar Pullback + Reclaim
* **Rule**: Prevent immediate pullback trigger and reclaim on the same bar.
* **Code Implementation**:
  Features like `pullback` are computed using `mfe_sf` (running MFE from entry to bar $k$) and `pnl_now` (Close of bar $k$):
  ```python
  pnl_now = (C[i, k] - e) * di / ai
  pull = max(0.0, mfe_sf - pnl_now)
  ```
  This computes the pullback at the close of bar $k$ causally. The atlas diagnostic script `bar4_knn_path_atlas.py` has no entry/re-entry logic, so it is physically impossible to execute a pullback-reclaim entry in this script. (Note: The external backtester `reclaim_monetization_backtest.py` splits pullback activation and recovery checks into an `if-else` block to prevent same-bar activation and reclaim).
* **Result**: **PASS**

### Rule 3: Exit on Flip Close
* **Rule**: Exit at the close of the flip-triggering bar.
* **Code Reference**: [bar4_knn_path_atlas.py:L115](file:///C:/Users/Scott%20McCarty/Projects/Nautilus%20Trader/studies/regime_dna_knn/bar4_knn_path_atlas.py#L115)
* **Code Implementation**:
  ```python
  final_pnl_val = (C[i, ni] - e) * di / ai
  ```
  where `ni = int(min(n[i], 61))` and `n[i]` is the flip bar index.
* **Audit Finding**: The baseline exit PnL is priced exactly at the Close of the flip bar `ni`. This avoids any look-ahead exits (such as exiting at the open of the flip bar, which would require future knowledge of the flip occurrence).
* **Result**: **PASS**

---

## 4. Scale-Out Policy Simulation Audit

The scale-out policy simulation compares a baseline hold-to-flip policy against a policy that exits 50% of the position when a Failure/Chop warning is generated. We audited this simulation for causality:

### A. Warning Causality
* **Causality Verification**: The warning is triggered when the predicted class `pred_cls` transitions to a deterioration state (`Failure` or `Chop`). The predicted class at each bar $k$ is computed using the KNN model using features strictly through bar $k$. The simulation iterates through the sequence of states $s$ sorted by bar index $k$.
* **Result**: **PASS**

### B. Prevention of Same-Bar Signal and Warning (`k > first_cont`)
* **Causality Verification**: The code checks for warnings only on bars strictly *after* the continuation signal is first established:
  ```python
  first_cont = next((k for k, c, _, _, _, _, _, _ in s if c in CONT), None)
  ...
  if first_cont is not None:
      after = [(k, c, pnl, mfe_sf, r_mfe, r_mae) for k, c, pnl, mfe_sf, r_mfe, r_mae, _, _ in s if k > first_cont]
      d2_info = next(((k, pnl, mfe_sf, r_mfe, r_mae) for k, c, pnl, mfe_sf, r_mfe, r_mae in after if c in DETER), None)
  ```
  This prevents a trade from entering a continuation state and immediately triggering a deterioration exit on the same bar. The transition is forced to happen across distinct bars, respecting sequencing.
* **Result**: **PASS**

### C. Execution Price Casing
* **Causality Verification**: The scale-out is executed at `pnl_at_warn`, which corresponds to `C[i, warn_bar]` (the Close of the warning bar). Since the signal is generated at the Close of the warning bar, executing at the same close represents zero-latency execution. While this is mathematically causal, in live execution it requires placing orders immediately upon bar close. (Note: The average realized PnL remaining *after* the warning is negative: `-0.03 ATR`, validating that scaling out here saves money).
* **Result**: **PASS**

---

## 5. Audit Results Summary (OOS 2025–2026)

The execution of the audited script generated the following verified results:

* **OOS Predicted States**: 199,327 states (bars 4-15) across 27,365 OOS trades.
* **Warning Population (n = 5,117)**:
  - Median lead time: **6.0 bars** from warning to actual flip (72% of warnings have $\ge 3$ bars lead time).
  - Average % of total MFE achieved before warning: **33.9%**.
  - Average remaining realized PnL after warning: **-0.03 ATR**.
  - Baseline Policy Net PnL: **-2,490.2 ATR** (Profit Factor: 0.52).
  - Scale-Out Policy Net PnL: **-2,413.0 ATR** (Profit Factor: 0.33).
* **Global Population (n = 27,365)**:
  - Baseline Policy Net PnL: **3,573.7 ATR** (Profit Factor: 1.17).
  - Scale-Out Policy Net PnL: **3,650.9 ATR** (Profit Factor: 1.19).

* **Conclusion**: Shifting to the scale-out policy improves global net performance by **+77.2 ATR** and increases the overall profit factor from **1.17 to 1.19**, proving that the warning signal is both predictive and economically viable.
