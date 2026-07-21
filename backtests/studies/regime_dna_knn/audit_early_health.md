# Static Analysis & Timestamp Audit Report: `early_health_filter.py`

This audit evaluates `studies/regime_dna_knn/early_health_filter.py` for potential look-ahead bias, future leakage, and chronological inconsistencies in the data replay, feature calculations, baseline entries, and backtest simulation.

---

## 1. Future Leakage in Replay (`CapsuleReplay`)

### Analysis
* **Mechanism**: The replay processes 1-second bars sequentially via `on_1s`, which are aggregated into 1-minute bars via `TimeframeAggregator`.
* **State Updates**: When a 1-minute bar closes, `on_bucket_closed` updates the `RegimeStateEngine` and checks for a regime flip using only the completed bar's state.
* **Capsule Creation**: When a flip is detected, a new capsule is initialized, capturing the completed flip bar's open, high, low, close, and pre-flip buffer features.
* **Histories & Buffer**: The histories and pre-flip buffer are advanced at the very end of `on_bucket_closed`, ensuring the flip bar is not included in the pre-flip features.

> [!NOTE]
> **Verdict**: **No Leakage**. The replay itself is strictly sequential and causal. It operates purely on completed historical bars.

---

## 2. Future Leakage in Feature Calculations

### Pre-flip Features (`pre5_*`)
* **Features**: `pre5_efficiency`, `pre5_compression`, `pre5_velocity_ratio`, `pre5_volume_acceleration`, `pre5_hh_ll_count`.
* **Causality**: These features use only the pre-flip buffer `self._buf` (which holds the 5 bars strictly prior to the flip bar) and `atr_20` (which is computed prior to the current bar's true range entry).
* **Version A Entry**: Version A enters at the **open of Bar 1** (the first bar after the flip bar). Since the flip bar has just closed, the pre-flip features are fully historical and known.

> [!NOTE]
> **Verdict**: **No Leakage** for Version A's feature block.

### Early Post-flip Features (`early_*`)
* **Features**: `early_mfe_expansion` (`mfe3`), `early_mae_peak` (`mae3`), `early_health_ratio`, `progress_count_3`, `close_progression_ratio`, `current_pullback_from_peak`.
* **Causality**: These features are defined using columns 0, 1, 2, and 3 of the `all` arrays (the flip bar plus post-flip bars 1, 2, and 3). Since Version B enters at the **open of Bar 4** (the close of Bar 3), all of these bars have completed.

> [!NOTE]
> **Verdict**: **No Leakage** in the `early_*` features themselves.

### Critical Leakage in Version B's Entry Filter (`verB_mask`)
Despite the individual features being causal, the mask used to filter Version B entries (`verB_mask`) contains two severe future leaks:

```python
verB_mask = ((oos.survives4 == 1) & ... & (oos.flip_open_violation == 0) & ...)
```

1. **`survives4 == 1` (`n_post >= 4`)**:
   * **Leak**: At the open of Bar 4, we do not know if the regime will flip on Bar 4. Requiring `n_post >= 4` at entry looks ahead to ensure the regime survives Bar 4.
2. **`flip_open_violation == 0`**:
   * **Definition**: Uses `L_all[:, 1:6]` (columns 1 to 5, corresponding to Bars 1, 2, 3, 4, 5).
   * **Leak**: At the open of Bar 4, Bars 4 and 5 have not yet closed. Filtering entries based on violations in future bars is a direct look-ahead leak.

> [!WARNING]
> **Verdict**: **Critical Future Leakage**. Version B's entry mask cannot be evaluated in real-time.

---

## 3. Baseline Causal Entries (Baseline 2)

### Analysis
* **Definition**:
  ```python
  bar1_confirmed = np.where(d == 1, C_all[:, 1] > O_all[:, 1], C_all[:, 1] < O_all[:, 1])
  df["bar1_confirmed"] = (bar1_confirmed & (npost >= 1)).astype(int)
  ```
* **Entry point**: In `main()`, `Base2 bar1-conf` uses `entry_bar = 2`.
* **Causality**: At the open of Bar 2, Bar 1's close is fully known.
* **Leakage via `sim_trade`**: Although the baseline mask is causal, the simulation wrapper introduces survival leakage:
  ```python
  if n_post < entry_bar: # 2
      return None
  ```
  This means if a regime flips on Bar 1 or Bar 2 (making `n_post` 0 or 1), the trade is rejected, which is a future look-ahead.

> [!WARNING]
> **Verdict**: **Minor Survival Leakage** introduced by the simulation wrapper, not the baseline definition itself.

---

## 4. Backtest Simulation (`sim_trade`)

The backtest simulation contains two structural look-ahead biases:

### A. Survival Leakage at Entry
```python
if n_post < entry_bar:
    return None
```
* **Leak**: If a trade enters at `entry_bar`, it should be allowed to enter even if the regime flips on that exact bar or earlier. By filtering out these trades, the backtest avoids immediate losses that would be realized in live trading.

### B. Exit Leakage (Regime Flip Exit)
```python
if exit_px is None:
    bc = post_c[-1]
    exit_px = bc - d * EXIT_SLIP_T * TICK
    reason = "flip"
```
* **Leak**: If a trade survives without hitting a stop-loss or time-stop, it is exited at the close of `n_post` (`post_c[-1]`).
* **Chronological Flow**:
  * Suppose the regime flips on Bar `F`.
  * The flip is only detected when Bar `F` closes.
  * In a causal system, the exit must be executed at the close of Bar `F`.
  * In `sim_trade`, `n_post` is recorded as `F - 1`. The simulation exits at the close of Bar `F - 1` (which is the open of Bar `F`).
  * This means the simulation exits **one bar early** using future knowledge that the next bar will trigger a flip, completely avoiding the adverse price action of the flip bar.

```mermaid
graph TD
    subgraph Real-Time Execution (Causal)
        A[Flip Bar Closes] --> B[Enter trade at Bar 1 Open]
        B --> C[Bar 1 Closes]
        C --> D[Bar 2 Closes]
        D --> E[Bar 3 Closes (Regime Flip occurs)]
        E --> F[Exit trade at Bar 3 Close]
    end
    subgraph Simulation (Look-Ahead Leakage)
        G[Flip Bar Closes] --> H[Check if n_post >= 2]
        H -- No --> I[Do not enter trade]
        H -- Yes --> J[Enter trade at Bar 1 Open]
        J --> K[Exit at Bar 2 Close - 1 bar before Flip!]
    end
```

> [!CAUTION]
> **Verdict**: **Severe Structural Leakage**. Both the entry filter and the flip exit engine suffer from look-ahead bias, artificially inflating backtest performance.

---

## Recommendations for Remediation

To make the backtest and features 100% causal:

1. **Remove `n_post < entry_bar` check**:
   Allow the simulation to enter trades. If `n_post` is less than `entry_bar`, look up the actual price of the flip bar (or exit at the open of the next regime).
2. **Correct the Flip Exit**:
   Exits on regime flips should occur at the close of the flip bar (which is the first bar of the next regime), not the close of the last post-flip bar of the current regime.
3. **Correct `verB_mask`**:
   * Remove `survives4 == 1`.
   * Redefine `flip_open_violation` for Version B to only check columns 1 to 3 (`L_all[:, 1:4]` / `H_all[:, 1:4]`) at the time of entry.
