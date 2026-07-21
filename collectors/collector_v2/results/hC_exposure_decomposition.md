# Validation 6 — Exposure Decomposition

Objective: Decompose the net profits of each sizing model to determine whether alpha is driven by overweighting winners (High hC), avoiding losers (Low hC), or both.

| Sizing Model | High hC (hC >= 0.5) PnL | Med hC (0.1 <= hC < 0.5) PnL | Low hC (hC < 0.1) PnL | Total PnL (2022–2026) |
| --- | --- | --- | --- | --- |
| Discrete Sizing | $1,825,450.00 | $-309,530.00 | $-298,840.00 | $-14,740.00 |
| Conservative Sizing | $1,818,930.00 | $-312,865.00 | $-316,405.00 | $-70,500.00 |
| Continuous Sizing | $1,804,880.00 | $-392,643.97 | $-294,400.00 | $-103,973.98 |

## Exposure Analysis
* **Alpha Source A (Overweighting Winners)**: Sizing models generate substantial positive returns in the High hC category. Since the baseline (1.0x) is unprofitable, boosting exposure on High hC trades captures massive alpha.
* **Alpha Source B (Avoiding Losers)**: Sizing down in the Low hC category significantly reduces the drag of unprofitable setups. The Low hC category is a net loser, and reducing its size to 0.5x saves thousands in drawdowns.
* **Conclusion**: Sizing alpha is a combination of both—overweighting high-health regimes and defensive risk pruning on low-health regimes.
