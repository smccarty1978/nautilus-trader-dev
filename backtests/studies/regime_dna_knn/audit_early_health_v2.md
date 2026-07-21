# Audit Report: Regime DNA KNN Early Health Filter (V2)

An audit was conducted on [early_health_filter.py](file:///C:/Users/Scott%20McCarty/Projects/Nautilus%20Trader/studies/regime_dna_knn/early_health_filter.py) to verify causal consistency, sound baseline implementations, and the absence of look-ahead leakage. 

Below are the detailed findings for each audit item, including the diagnostic traceback encountered during execution and the corrective actions applied to achieve complete causal safety.

---

## 1. Version B Filter (`verB_mask`)
* **Status:** **Inconsistent in original, now corrected.**
* **Analysis:**
  * The mask successfully checked `flip_open_violation_b == 0` using post-flip bars 1 to 3, which is causal for the features evaluated at the open of Bar 4.
  * However, it required `n_post >= 3` (`survives3`) rather than `n_post >= 4` (`survives4`). 
  * Because Version B enters at the open of Bar 4, entering a trade requires the regime to be active at that moment. If `n_post == 3`, the regime flipped at the close of Bar 3 and is no longer active at the open of Bar 4. Requiring only `n_post >= 3` introduced a causal inconsistency, allowing entries on dead regimes and triggering an `IndexError` during simulation.

---

## 2. Entry Survival Checking in `sim_trade`
* **Status:** **Leaked / Unsound in original, now corrected.**
* **Analysis:**
  * The original survival check allowed entries when `n_post >= entry_bar - 1`:
    ```python
    if n_post < (entry_bar - 1):
        return None
    ```
  * For Version B (`entry_bar = 4`), this allowed entry when `n_post == 3`. But when `n_post == 3`, the list `post_o` only contains 3 elements (indices 0, 1, 2). Accessing `post_o[entry_bar - 1]` (`post_o[3]`) raised a traceback:
    ```tb
    File "studies/regime_dna_knn/early_health_filter.py", line 338, in sim_trade
      entry = post_o[entry_bar - 1]
    IndexError: list index out of range
    ```
  * **Correction:** The check was updated to `if n_post < entry_bar: return None`. This guarantees that the regime survives at least to the open of the entry bar (e.g., `n_post >= 4` for Bar 4), resolving the look-ahead leakage and preventing the crash.

---

## 3. Exit Pricing on Regime Flips
* **Status:** **Causal and Sound.**
* **Analysis:**
  * In `CapsuleReplay.on_bucket_closed`, the bar that triggers the regime flip is appended to the post-flip list of the active regime before finalization. Thus, index `n_post - 1` corresponds to the opposite flip-triggering bar.
  * In `sim_trade`, when exiting on a regime flip (`reason = "flip"`), the price is taken from `post_c[last_bar - 1]`. For `exit_model == 2` (Macro-OppFlip) where `last_bar = n_post`, this is `post_c[n_post - 1]`.
  * Since the flip can only be confirmed at the close of that bar, exiting at `post_c[n_post - 1]` is causal and correct.

---

## 4. Baseline Entries (`Base2` and `Base3`)
* **Status:** **Unsound in original, now corrected.**
* **Analysis:**
  * **Baseline 2 (`bar1_confirmed`):** Enters at `entry_bar = 2`. The original code checked `npost >= 1`. This allowed entry on regimes that flipped at the close of Bar 1 (where `n_post == 1`), resulting in look-ahead leakage and an `IndexError` when accessing `post_o[1]`. We corrected it to `npost >= 2`.
  * **Baseline 3 (`Base3 survive-4`):** Enters at `entry_bar = 4`. The original code checked `base3 = oos.n_post >= 3`. This allowed entry when `n_post == 3`, resulting in look-ahead leakage and an `IndexError` when accessing `post_o[3]`. We corrected it to `base3 = oos.n_post >= 4`.

---

## Final Performance & Verdict
With all look-ahead leakage and indexing bugs resolved, the script was re-run over the OOS years (2025–2026):
* **Falsification Gate Results:** **Passes = 0**. No configurations for Version A or Version B achieved net-positive results in both 2025 and 2026 with a Profit Factor (PF) $\ge 1.10$.
* **Conclusion:** The apparent profitability of these strategies in earlier iterations was a look-ahead leakage artifact (survival bias) caused by allowing entries on regimes that had already flipped. Under causal and sound conditions, the strategy is **permanently dead and non-deployable**.
