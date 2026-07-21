# Static Analysis & Timestamp Audit Report: Bar 4 KNN Path-State Atlas

This report summarizes the static code analysis, look-ahead logic, and timestamp audit performed on [bar4_knn_path_atlas.py](file:///c:/Users/Scott%20McCarty/Projects/Nautilus%20Trader/studies/regime_dna_knn/bar4_knn_path_atlas.py).

## Audit Summary
- **Overall Status**: **PASS** (after applying critical bug fixes).
- **Core Findings**: The path classification and KNN state transition modeling are mathematically sound and strictly causal. Exits and targets are evaluated correctly, same-bar collisions are handled conservatively (adverse-first), and no future look-ahead leaks are present in the features.
- **Critical Fixes Applied**: Three bugs were identified and fixed to allow the script to execute successfully and generate the study reports.

---

## 1. Detailed Audit Items

### Item 1: Entry-Bar Exits Checking
* **Requirement**: Verify exits start on the entry bar.
* **Findings**: **PASS**
* **Code Reference**: [bar4_knn_path_atlas.py:L105-115](file:///c:/Users/Scott%20McCarty/Projects/Nautilus%20Trader/studies/regime_dna_knn/bar4_knn_path_atlas.py#L105-L115)
* **Details**: In the path classification loop, the entry price `f_val` is set at the Open of `ENTRY_BAR` (Bar 4). The loop evaluating MFE and MAE runs `for j in range(ENTRY_BAR, last_bar + 1):`, which includes `j = 4` (the entry bar itself). Thus, potential exits are evaluated immediately from the entry fill onward.
* **State Transition Targets**: For state vectors defined at the Close of bar `j`, targets are checked using `check_hit(pt, sl)` which starts at `j + 1` (the very next bar). This is also correct, as the trade has already survived to the Close of bar `j`.

### Item 2: Adverse-First Same-Bar Sequencing
* **Requirement**: When high and low both hit a target/stop level on the same bar, assume the stop hits first (or verify causality if tick data is used).
* **Findings**: **PASS**
* **Code Reference**: [bar4_knn_path_atlas.py:L218-L228](file:///c:/Users/Scott%20McCarty/Projects/Nautilus%20Trader/studies/regime_dna_knn/bar4_knn_path_atlas.py#L218-L228)
* **Details**: Inside `check_hit(pt, sl)`:
  ```python
  if fav_t >= pt and adv_t >= sl: # double hit resolved adverse-first
      return 0
  ```
  If both target and stop levels are hit on the same future bar `t`, it returns `0` (indicating failure/stop hit). This guarantees conservative and causal sequencing on same-bar collisions.

### Item 3: Pullback/Reclaim Logic
* **Requirement**: Prevent same-bar triggers (e.g. evaluating pullback relative to peak prior to current bar).
* **Findings**: **PASS**
* **Code Reference**: [bar4_knn_path_atlas.py:L179-L182](file:///c:/Users/Scott%20McCarty/Projects/Nautilus%20Trader/studies/regime_dna_knn/bar4_knn_path_atlas.py#L179-L182)
* **Details**: Pullback is calculated as `max(0.0, mfe_so_far - current_pnl)`, where `mfe_so_far` is the maximum favorable excursion up to the current bar `j` (inclusive) and `current_pnl` is the Close of bar `j`. Since features are computed at the *Close* of bar `j` and the model runs at that Close, this does not constitute a look-ahead leak.
* **Causal Safeguards in Backtest**: In [reclaim_monetization_backtest.py](file:///c:/Users/Scott%20McCarty/Projects/Nautilus%20Trader/studies/regime_dna_knn/reclaim_monetization_backtest.py#L135-L147), the pullback activation and recovery checks are split in an `if-else` block:
  ```python
  if not pb_active:
      if running_peak_mfe - pb_mfe_j >= 0.50:
          pb_active = True
  else:
      if mfe_j >= pb_start_peak_mfe:
          recovered = True
  ```
  This guarantees that a trade cannot be activated and reclaimed on the same bar. Recovery can only trigger on a bar *after* the bar on which the pullback was activated.

### Item 4: Exit on Actual Flip Close
* **Requirement**: Check if flip exits are priced at the close of the flip-triggering bar.
* **Findings**: **PASS**
* **Code Reference**: [bar4_knn_path_atlas.py:L125](file:///c:/Users/Scott%20McCarty/Projects/Nautilus%20Trader/studies/regime_dna_knn/bar4_knn_path_atlas.py#L125), [early_health_filter.py:L376-380](file:///c:/Users/Scott%20McCarty/Projects/Nautilus%20Trader/studies/regime_dna_knn/early_health_filter.py#L376-L380)
* **Details**: The PnL calculation is based on `C[idx, last_bar]`, where `last_bar = min(n_val, BMAX)` and `n_val` is the number of post-flip bars (which includes the opposite flip bar as the last bar). Therefore, the exit is priced at the Close of the flip-triggering bar. This matches `early_health_filter.py`, where `exit_px` for flip exits is based on `post_c[last_bar - 1]`.

### Item 5: Feature Lookahead Leaks
* **Requirement**: Verify no future labels or future path data are used in features.
* **Findings**: **PASS**
* **Code Reference**: [bar4_knn_path_atlas.py:L58-L83](file:///c:/Users/Scott%20McCarty/Projects/Nautilus%20Trader/studies/regime_dna_knn/bar4_knn_path_atlas.py#L58-L83)
* **Details**:
  - The model uses `health[idx]` as a key state feature.
  - On In-Sample (IS) data (`yr < 2025`), `health` is generated using 5-fold cross-validation Out-of-Fold (OOF) predictions, preventing label leakage.
  - On Out-of-Sample (OOS) data (`yr >= 2025`), `health` is predicted using a classifier trained strictly on IS data.
  - The features used to predict `health` are through bar 3 (`feats_through(df, M, 3)`), which is in the past relative to the state rows evaluated from Bar 4 onwards.
  - All state vector features are constructed up to bar `j` (inclusive) and do not contain future bars.

---

## 2. Bugs Identified & Fixed

During the audit, three major issues were found that prevented the script from running or caused incorrect index lookups:

1. **MODEL_B Feature Name mismatch (KeyError)**:
   - *Problem*: The `MODEL_B` feature list was defined using columns from the raw capsule (`early_mfe_expansion`, `early_mae_peak`, etc.), but the model was fitted on `XB` which is returned by `P.feats_through(df, M, 3)`. The columns in `XB` are named `mfe`, `mae`, `health`, and `pullback`. This caused a `KeyError` during training.
   - *Fix*: Replaced the column names in `MODEL_B` with the correct feature names in `XB`:
     `MODEL_B = ["pre5_efficiency", "pre5_compression", "pre5_velocity_ratio", "pre5_volume_acceleration", "pre5_hh_ll_count", "mfe", "mae", "health", "pullback", "close_loc"]`.

2. **AttributeError on `df.volume_base`**:
   - *Problem*: Line 148 referenced `vol_base = df.volume_base.values[idx]`, but the `volume_base` column does not exist in `early_health_capsule.parquet`, nor was `vol_base` ever used in the script.
   - *Fix*: Removed the unused reference line.

3. **Index Lookup Bug in Warning Lead Time (IndexError)**:
   - *Problem*: Line 518 used `actual_flip_bar = n[gi[t_idx]]` to calculate the warning lead time. Since `t_idx` is already the absolute index of the trade in `df`, indexing `gi` (which is a sliced list of OOS indices) with `t_idx` would cause an `IndexError` or return the wrong index.
   - *Fix*: Corrected to `actual_flip_bar = n[t_idx]`.

---

## 3. Results Summary (OOS 2025–2026)

Following the fixes, the script was run successfully. The generated reports yield the following key findings:

### 1. Overall Performance across K Sweeps
The KNN model shows high consistency across different values of $K$ (number of nearest neighbors) for predicting remaining MFE and MAE, with the primary $K=500$ achieving:
* **Average Predicted MFE**: 2.19 ATR (vs. 2.27 ATR actual)
* **Average Predicted MAE**: 1.16 ATR (vs. 1.20 ATR actual)
* **P(+1 before -1) AUC**: 0.531 (improving with higher $K$)

### 2. Path Class Accuracy
Multi-class path classification achieves high accuracy and AUC, especially as the trade progresses:
- **Bar 4 Multi-class Accuracy**: 45.7% (Baseline: ~28%)
- **Bar 8 Multi-class Accuracy**: 65.2%
- **Bar 12 Multi-class Accuracy**: 77.0%
- **Clean Continuation Precision (Top 10%)**:
  - **Bar 4**: 66.1% (Prevalence: 28.9%)
  - **Bar 5**: 82.1% (Prevalence: 31.5%)
  - **Bar 8**: 95.9% (Prevalence: 40.1%)
  - **Bar 12**: 98.5% (Prevalence: 49.9%)

### 3. Transition Analysis & Early Warnings
- **Deterioration warning rate**: The KNN model successfully predicts Failure or Exhaustion before the actual flip occurs in **86.1%** of failing trades (5,610 out of 6,513 total).
- **Warning Lead Time**:
  - **Average Lead Time**: 3.5 bars before the flip.
  - **Median Lead Time**: 2.0 bars before the flip.
- **State Stability**: Once a trade enters "Clean Continuation", it has a **93.3%** probability of remaining in that state on the next bar.
