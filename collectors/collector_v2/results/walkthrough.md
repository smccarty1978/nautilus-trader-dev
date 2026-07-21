# Walkthrough: Next hC Research Sprint & NautilusTrader Validation

This walkthrough summarizes the implementation, execution, and key findings of the **Next hC Research Sprint** (Studies 1-4), **Study 7: hC State Machine Trading Policies**, and the subsequent **NautilusTrader Event-Driven Position Sizing Validation**.

---

## 1. Code Changes & Fixes

We executed the work in two distinct phases:

### Phase 1: State Machine & Offline Analysis
* **Sprint Script**: [decision_hc_sprint.py](file:///C:/Users/Scott%20McCarty/Projects/Nautilus%20Trader/studies/regime_dna_knn/decision_hc_sprint.py)
  * Resolved column dimension bound indexing errors and open price lookup bugs in the source dataframes.
* **State Machine Script**: [decision_hc_state_machine.py](file:///C:/Users/Scott%20McCarty/Projects/Nautilus%20Trader/studies/regime_dna_knn/decision_hc_state_machine.py)
  * Implemented the walk-forward KNN state scoring classifier and tested early exits, sizing modulation, and opportunity preservation rules.

### Phase 2: NautilusTrader Event-Driven Sizing Validation
* **Strategy & Sizing Class**: [hc_sizing_strategy.py](file:///C:/Users/Scott%20McCarty/Projects/Nautilus%20Trader/collectors/collector_v2/hc_sizing_strategy.py)
  * Created `HCSizingStrategy` to execute position sizing (Discrete, Conservative, and Continuous) at Bar 4 close inside the live NT event-loop.
* **Fixed Order Lifecycle Bug**:
  * Found that `TimeInForce.FOK` exit orders get cancelled or expired by the matching engine under fast market conditions in the simulated event loop.
  * When this occurred, `self._trade["exit_order_id"]` remained set, deadlocking the strategy from ever retrying exits or entering new trades.
  * We patched `on_order_canceled` and `on_order_expired` in the strategy to clear `exit_order_id` on cancellation/expiration, allowing the strategy to successfully retry exiting.
* **Backtest Runner**: [run_hc_sizing_backtests.py](file:///C:/Users/Scott%20McCarty/Projects/Nautilus%20Trader/collectors/collector_v2/run_hc_sizing_backtests.py)
  * Modified the runner to run all 20 matrix runs (4 policies × 5 years) in parallel and aggregate all trades.

---

## 2. Validation and Execution

All backtests were executed from a clean state using the volume-continuous catalog `NQ_v0_2020_2026`:
```powershell
# Run the full test suite matrix
python collectors/collector_v2/run_hc_sizing_backtests.py
```
* **Status**: Completed successfully.
* **Validation Reports Generated**:
  1. [hC_bucket_distribution.md](file:///C:/Users/Scott%20McCarty/.gemini/antigravity/brain/e605b5a7-30e3-408a-b749-ab24ceb8cf7e/hC_bucket_distribution.md)
  2. [hC_nt_sizing_validation.md](file:///C:/Users/Scott%20McCarty/.gemini/antigravity/brain/e605b5a7-30e3-408a-b749-ab24ceb8cf7e/hC_nt_sizing_validation.md)
  3. [hC_continuous_sizing.md](file:///C:/Users/Scott%20McCarty/.gemini/antigravity/brain/e605b5a7-30e3-408a-b749-ab24ceb8cf7e/hC_continuous_sizing.md)
  4. [hC_2026_oos_breakdown.md](file:///C:/Users/Scott%20McCarty/.gemini/antigravity/brain/e605b5a7-30e3-408a-b749-ab24ceb8cf7e/hC_2026_oos_breakdown.md)
  5. [hC_exposure_decomposition.md](file:///C:/Users/Scott%20McCarty/.gemini/antigravity/brain/e605b5a7-30e3-408a-b749-ab24ceb8cf7e/hC_exposure_decomposition.md)
  6. [audit_hC_nt_validation.md](file:///C:/Users/Scott%20McCarty/.gemini/antigravity/brain/e605b5a7-30e3-408a-b749-ab24ceb8cf7e/audit_hC_nt_validation.md)

---

## 3. Position-Sizing Performance Results (2022–2026)

| Sizing Policy | Net PnL (Pooled) | Expectancy / Trade | Win Rate | Max Drawdown |
| --- | --- | --- | --- | --- |
| **Baseline (1.0x)** | **-$77,960.00** | **-$5.98** | **36.0%** | **$187,780.00** |
| **Discrete Sizing** | **-$14,740.00** | **-$1.18** | **34.5%** | **$229,425.00** |
| **Conservative Sizing** | **-$70,500.00** | **-$5.48** | **35.1%** | **$252,150.00** |
| **Continuous Sizing** | **-$103,973.98** | **-$8.47** | **34.3%** | **$237,822.35** |

---

## 4. Key Findings & Deployability Analysis

### Deployability Decision: NO / NOT DEPLOYABLE

* **Why did Sizing fail? (Pre-Sizing PnL Dominance)**: 
  * The average pre-sizing move (from entry to Bar 4 close) is **+9.51 points** for High hC trades.
  * The average post-sizing move (from Bar 4 close to exit) is **only +0.78 points**.
  * Over **92% of the trade's positive move occurs in the first 4 minutes** before the sizing order is executed.
* **The Cost Trap**:
  * Sizing up to 4 contracts at Bar 4 close gains an average of **+$135,290.00** in gross PnL.
  * However, adding 2 contracts increases commissions and slippage (modeled as tick dollar friction) by **$30.00 per trade** ($10 entry commission + $10 entry slippage + $10 exit cost).
  * Across 4,580 High hC trades, the additional cost is **$137,400.00**, resulting in a net loss of **-$2,110.00** from sizing up.
* **Order Executions & Hold Time**:
  * FOK orders are frequently cancelled under fast market conditions. Because sizing up increases the size to 4 contracts, orders are cancelled more often, forcing retries and increasing the average hold time from **1493.1s** (Baseline) to **2186.5s** (Discrete).
  * This latency reduces capital efficiency and increases market exposure.
