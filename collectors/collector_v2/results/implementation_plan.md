# Bar-4 hC Position-Sizing NautilusTrader Validation Plan

This plan details the implementation and execution of a full NautilusTrader event-driven validation of the Bar-4 $hC$ position-sizing policies. The objective is to determine if $hC$ provides deployable sizing alpha under realistic event-driven backtesting conditions, including execution delay, transaction costs, and actual trade execution at Bar 4 close.

## Proposed Changes

### Component 1: hC Mapping Precomputation

To run backtests efficiently and ensure bit-exact parity with the walk-forward KNN model from Study 7, we will precompute the $hC$ scores for all regimes at Bar 4 close.

#### [NEW] [extract_hc_mapping.py](file:///c:/Users/Scott%20McCarty/Projects/Nautilus%20Trader/collectors/collector_v2/extract_hc_mapping.py)
* Loads `studies/regime_dna_knn/results/early_health_capsule.parquet` and builds features.
* Runs the identical walk-forward KNN logic as Study 7 (`decision_hc_state_machine.py`) for years 2022–2026 at `k=4` (Bar 4 close).
* Generates a mapping from `regime_start_ts` (in nanoseconds) to `hC`.
* Saves this mapping to `collectors/collector_v2/results/hc_bar4_mapping.parquet`.

---

### Component 2: NautilusTrader Strategy and Config

We will implement a specialized strategy class to handle position sizing at Bar 4 close without modifying the core `CollectorV2Strategy` code.

#### [NEW] [hc_sizing_strategy.py](file:///c:/Users/Scott%20McCarty/Projects/Nautilus%20Trader/collectors/collector_v2/hc_sizing_strategy.py)
* Defines `HCSizingConfig` (inheriting from `CollectorV2Config`) adding:
  - `sizing_policy`: str (`baseline`, `discrete`, `conservative`, `continuous`)
  - `mapping_file_path`: str (path to the precomputed Parquet mapping)
  - `base_position_size`: int = 2 (base size is 2 contracts)
* Defines `HCSizingStrategy` (inheriting from `CollectorV2Strategy`):
  - In `on_start()`, loads `hc_bar4_mapping.parquet` into a dictionary `self._hc_map`.
  - Overrides `_submit_entry()` to submit the initial entry order with `self._cfg.base_position_size` (2 contracts).
  - Stores the `regime_start_ts` in `self._trade` at entry time.
  - In `_on_1m_bucket_closed()`, checks if `s_1m.bars_in_regime == 5` (Bar 4 close) and `self._trade` is open and not yet sized:
    - Looks up the precomputed $hC$ for the current regime's `regime_start_ts`.
    - Computes the target position size based on the policy:
      - **Baseline**: 2 contracts (1.0x)
      - **Discrete**:
        - $hC \ge 0.5$: 4 contracts (2.0x)
        - $0.1 \le hC < 0.5$: 2 contracts (1.0x)
        - $hC < 0.1$: 1 contract (0.5x)
      - **Conservative**:
        - $hC \ge 0.5$: 3 contracts (1.5x)
        - $0.1 \le hC < 0.5$: 2 contracts (1.0x)
        - $hC < 0.1$: 1 contract (0.5x)
      - **Continuous**:
        - $f(hC) = \text{clip}(0.5 + 3.75 \cdot (hC - 0.1), 0.5, 2.0)$
        - Target contracts = $\text{round}(2.0 \cdot f(hC))$ (snaps to 1, 2, 3, or 4 contracts)
    - If `target_contracts != self._trade["size"]`, submits a secondary market order for the difference.
    - Records the client order ID of the sizing order.
  - Overrides `on_order_filled()` to handle sizing order fills:
    - If the sizing order fills, updates `self._trade["size"]` to `target_contracts`.
    - Computes PNL using a cash flow tracking method:
      - `cash_flow = -d * size * price` at each execution.
      - At exit: `cash_flow += d * final_size * exit_price`.
      - `gross_pnl = cash_flow * multiplier`.
    - Scales the transaction cost (commission + tick dollar) by `sizing_factor = final_size / base_size` to match Study 7's cost assumptions.
  - Overrides `_submit_exit()` to submit the exit order with quantity equal to the *actual* current position size.

---

### Component 3: Backtest Runner and Reporting

#### [NEW] [run_hc_sizing_backtests.py](file:///c:/Users/Scott%20McCarty/Projects/Nautilus%20Trader/collectors/collector_v2/run_hc_sizing_backtests.py)
* Script to run backtests for years 2022 to 2026 for all four sizing policies.
* Uses the continuous volume-continuous catalog `data/catalog/NQ_v0_2020_2026`.
* Saves trade logs for each run to `collectors/collector_v2/results/sizing_<policy>_<year>/`.
* After runs complete, aggregates and processes all trade logs to produce the required validation reports.
* Generates the 6 required markdown deliverables:
  1. `hC_bucket_distribution.md`
  2. `hC_nt_sizing_validation.md`
  3. `hC_continuous_sizing.md`
  4. `hC_2026_oos_breakdown.md`
  5. `hC_exposure_decomposition.md`
  6. `audit_hC_nt_validation.md`

## Verification Plan

### Automated Verification
* Compare baseline backtest trades from `run_hc_sizing_backtests.py` with the existing `v_a_v0_<year>` results to verify that adding the sizing hooks does not alter entry/exit timing and prices.
* Verify that the secondary order fills occur exactly 3 minutes (3 bars) after the initial entry fill.
* Check that all $hC$ values retrieved in the strategy match the walk-forward KNN outputs.
* Enforce $5 RT commission + slippage.

### Deliverables Check
* Confirm all 6 reports are generated in the artifacts directory.
* Answer the final YES/NO/INCONCLUSIVE deployability question.
