# Look-Ahead & Timestamp Audit — health_transition_atlas.py

**Date:** 2026-06-18T00:00:00Z
**Auditor:** lookahead-auditor v1
**Scope:** health_transition_atlas.py (causality, survivor-bias, population checks)

---

## Summary

- **Critical:** 0
- **Warning:** 0
- **Note:** 3

**Overall: ALL PASS**

---

## 1. Feature Causal Isolation (Check B2/B3)

### Analysis
* **Mechanism**: $hC$ at bar $k$ is computed as `pNH3 - pFL3`.
* **Features**: The KNN search queries OOS features `A.FEATS` (defined in `bar4_knn_path_atlas.py` line 34) which consist of:
  `["bar_idx", "mfe_sofar", "mae_sofar", "pnl_now", "pullback", "progress_count", "consec_noncont", "dist_flip_open", "health_ratio", "close_loc", "range_exp", "vol_exp"]`.
* **Causality**:
  * `mfe_sofar` and `mae_sofar` use `H[i, 4:k+1]` and `L[i, 4:k+1]`, which are strictly backward-looking.
  * `pnl_now` uses `C[i, k]`.
  * `hC_pk` uses `g.hC.cummax()`. Since the group is sorted by `(rid, k)` chronologically, this only uses values up to bar $k$.
  * `dd = 1 - hC / hC_pk` is therefore strictly causal.
* **Verdict**: **No Leakage**. All inputs into the state classification at bar $k$ are fully known at the close of bar $k$.

---

## 2. Outcome Label Causality & Verification (Check C1)

### Analysis
* **Mechanism**: All labels used to study transitions and opportunity (Study 1, 2, 3) are forward-looking outcomes.
* **Transition Target ($\Delta hC$)**: Uses `hC_{k+H}` or registers a `Flip` if `k + H >= n`. Since the target bar is in the future, it is a valid forward outcome.
* **Reignition Target**: Checks if the maximum price between $k+1$ and $k+H$ exceeds `peak_px` (the peak price seen up to $k$) by at least $X$ ATR. This is a valid forward outcome.
* **Flip Target**: Checks if `rem_bars <= H` (where `rem_bars = n - k` is the number of bars to the terminal flip). This is a valid forward outcome.
* **Verdict**: **No Leakage**. All outcomes are evaluated strictly on future bars relative to $k$.

---

## 3. Survivor Filter & Population Audits (Check E5/C3)

### Analysis
* **Survivor Filter**: The population at bar $k$ includes all active regimes where $n > k$. No future survival requirements are imposed.
* **Study 1 & 2 Horizon Handling**: If a regime flips before the horizon $H$ is reached:
  * In Study 1, it is registered as "Deteriorated/Flipped" (not dropped).
  * In Study 2, it is registered as having "0" new high and "1" flip (not dropped).
  This handles early flippers correctly without discarding them, preventing survivor bias.
* **Temporal Split**: Discovery/training set is strictly `year < 2025` (2021–2024), and OOS validation set is strictly `year >= 2025` (2025–2026).
* **Verdict**: **No Bias**. The population is complete and free of selection/survivor bias.
