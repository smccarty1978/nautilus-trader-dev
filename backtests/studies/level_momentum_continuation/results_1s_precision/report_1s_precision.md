# 1s-Precision Validation: SL=30 + BE=2.5 + skip

## Method

Hybrid simulation: 1m Goldilocks triggers, 1s execution.

Per-bar checks at 1s precision:
1. Update running MFE from 1s bar's high/low
2. Arm BE if MFE >= 2.5 (intra-1s arming)
3. BE-stop check (if armed): low <= entry (long), high >= entry (short)
4. Cat-stop check (only if not yet BE-armed): low <= entry-30 (long)
5. Target check: high >= target (long)
6. EOD flat at 16:00 CT

Vectorized per-trade exit search via numpy argmax.

Skip-while-open at 1s precision: chain holds slot until 1s exit.

## Comparison vs prior 1m-bar simulation

| Year | 1m-bar (prior) | 1s-precision (this) | Δ |
|---|--:|--:|--:|
| 2024 | $385,000 | $-25,165 | $-410,165 |
| 2025 | $431,000 | $-81,310 | $-512,310 |

## 1s-precision detail per year

### 2024

- n trades: 24,629
- WR: 22.3%
- BE-stop rate: 70.0%
- Cat-loss rate: 7.3%
- EOD-flat rate: 0.3%
- Armed%: 98.0%
- Mean PnL net: -0.051
- Annual $: $-25,165

### 2025

- n trades: 32,717
- WR: 23.5%
- BE-stop rate: 68.4%
- Cat-loss rate: 7.9%
- EOD-flat rate: 0.2%
- Armed%: 98.6%
- Mean PnL net: -0.124
- Annual $: $-81,310
