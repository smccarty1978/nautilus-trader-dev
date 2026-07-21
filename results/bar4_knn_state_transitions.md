# Bar-4 KNN State Transitions & Lead Time

Does KNN predict deterioration BEFORE the opposite 1m flip, or coincident (observation)?

## Predicted-class transitions (consecutive bars, counts)
| from → to | count |
| --- | --- |
| Runner → Runner | 57,416 |
| Continuation → Continuation | 53,609 |
| Continuation → Runner | 13,783 |
| Failure → Failure | 12,738 |
| Runner → Continuation | 12,384 |
| Failure → Continuation | 4,963 |
| Chop → Continuation | 3,753 |
| Continuation → Chop | 3,072 |
| Chop → Chop | 2,365 |
| Failure → Runner | 2,179 |
| Failure → Chop | 1,330 |
| Continuation → Failure | 1,199 |

## Lead time — first predicted Failure/Chop → actual flip (bars)

> [!WARNING]
> RAW lead is INFLATED by born-failed trades (KNN says Failure from bar 4 because mfe_so_far is low the whole time — observation, not prediction). The honest metric is GENUINE deterioration: trades KNN first called Continuation/Runner, that LATER flipped to Failure/Chop.

- **RAW** (any Failure/Chop call): n=15,359, median **6.0 bars**, % ≤1 bar (observation) = 15%
- **GENUINE** (Continuation/Runner→deterioration): n=5,117 (18.7% of OOS trades), median lead **6.0 bars**, % ≤1 bar = 17%, % ≥3 bars = 72%

## Warning State Metrics

- **Average % of total MFE achieved before warning**: 33.9%
- **Average remaining MFE after warning**: 1.50 ATR
- **Average remaining MAE after warning**: 0.55 ATR
- **Average remaining realized PnL after warning**: -0.03 ATR

## Scale-Out Policy Simulation

We compare a baseline hold-to-flip policy against a 50% scale-out policy that exits half the position when the Failure/Chop warning fires.

### Warning Population (warned trades only, n=5,117)
| Policy | Net PnL (ATR) | Win % | Avg Payoff (ATR) | Profit Factor |
| :--- | :---: | :---: | :---: | :---: |
| **Baseline** | -2490.2 | 22.3% | -0.49 | 0.52 |
| **Scale-Out** | -2413.0 | 18.7% | -0.47 | 0.33 |

### Global Population (all OOS trades, n=27,365)
| Policy | Net PnL (ATR) | Win % | Avg Payoff (ATR) | Profit Factor |
| :--- | :---: | :---: | :---: | :---: |
| **Baseline** | 3573.7 | 35.2% | 0.13 | 1.17 |
| **Scale-Out** | 3650.9 | 34.5% | 0.13 | 1.19 |