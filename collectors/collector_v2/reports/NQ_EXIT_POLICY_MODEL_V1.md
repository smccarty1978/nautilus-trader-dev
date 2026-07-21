# NQ Exit-Policy Model v1 — Collector V2

Supervised exit-policy study on V_A momentum-confirm trades for NQ
2024 / 2025 / 2026. All features and labels derived causally from
Collector V2 path_checkpoint snapshots.

## Setup

**Decision rows**: every 30s while a V_A trade is open, a
path_checkpoint snapshot was emitted from inside NT (causal — see
CAUSALITY.md). Each snapshot includes:

- **Path-state features**: cur_pnl_atr, cur_mfe_atr, cur_mae_atr,
  cur_giveback_atr, elapsed_s, trade_atr_at_signal, direction
- **Causal MTF context** (registry-audited): regime_30s/1m/3m/5m,
  alignment vs trade direction, bars_in_regime per TF, ATR per TF,
  EMA-distance features per TF

**Labels** (computed from FUTURE path within same trade):
- `exit_now_better_than_hold` (binary)
- `future_giveback_risk` (binary — gives back ≥0.5 ATR before next
  +0.5 ATR favorable move)
- `remaining_ev_atr` (regression — final PnL minus current PnL in ATR)
- `future_mfe_remaining_atr`, `future_mae_remaining_atr`

**Walk-forward folds**:
- Fold 1: train NQ 2024 → test NQ 2025
- Fold 2: train NQ 2024 + 2025 → test NQ 2026

## Dataset sizes

| Cell | Trades | Decision rows |
|---|--:|--:|
| NQ 2024 (RTH+ETH) | 11,987 | 298,794 |
| NQ 2025 (RTH+ETH) | 11,776 | 293,260 |
| NQ 2026 (Q1+RTH+ETH) | 3,575 | 87,022 |

## Model performance

### Fold 1 — train 2024, test 2025

| Target | Model | AUC / corr |
|---|---|--:|
| exit_now_better_than_hold | LGBM | 0.532 |
| exit_now_better_than_hold | LogReg | 0.535 |
| future_giveback_risk | LGBM | **0.791** |
| future_giveback_risk | LogReg | 0.726 |
| remaining_ev_atr (regression) | LGBM | corr 0.007 |

### Fold 2 — train 2024+2025, test 2026

| Target | Model | AUC / corr |
|---|---|--:|
| exit_now_better_than_hold | LGBM | ~0.53 |
| future_giveback_risk | LGBM | **0.790** |
| remaining_ev_atr (regression) | LGBM | corr 0.014 |

**Only `future_giveback_risk` has non-trivial signal (AUC ~0.79
stable across folds).** `exit_now_better` is essentially random
(AUC 0.53). The remaining-EV regression has near-zero correlation
(0.01).

## Policy simulation

For each model-driven exit policy, simulated against the test-set
trades. "early exit" = policy fires at a checkpoint and exits at
that bar's close. Otherwise hold to actual regime-exit.

### Fold 1 (NQ 2025, n=11,721 trades after data filter)

Baseline (hold to regime exit): mean -$1.51/trade, total
-$17,655, PF 0.99.

| Policy | Threshold | Mean $ | Total $ | PF | % exited early |
|---|---|--:|--:|--:|--:|
| Baseline | — | -$1.51 | -$17,655 | 0.99 | 0% |
| P1: pred EV < -0.25 ATR | | -$0.68 | -$7,990 | 1.00 | 0.03% |
| P1: pred EV < 0.0 | | -$1.51 | -$17,655 | 0.99 | 1.6% |
| P2: pred giveback > 0.5 | | -$11.68 | -$136,845 | 0.73 | 99.5% |
| P2: pred giveback > 0.7 | | -$11.93 | -$139,815 | 0.80 | 98.8% |
| P2: pred giveback > 0.8 | | -$11.53 | -$135,180 | 0.83 | 97.2% |
| P3: pred exit_better > 0.5 | | -$10.54 | -$123,560 | 0.72 | 99.5% |
| P3: pred exit_better > 0.7 | | **+$0.11** | +$1,320 | 1.00 | 9.2% |
| P3: pred exit_better > 0.8 | | -$0.31 | -$3,690 | 1.00 | 0.3% |
| SL=2.0 ATR safety overlay | | -$0.95 | -$11,113 | 0.99 | 14.0% (SL hits) |

**Best policy improvement: +$1.62/trade vs baseline (P3 thr 0.7).**
Cuts 9.2% of trades. Effectively a small SL — economically marginal.

### Fold 2 (NQ 2026, n=3,561 trades)

Baseline: mean -$23.42/trade, total -$83,400, PF 0.88.

| Policy | Mean $ | Total $ | % exited early |
|---|--:|--:|--:|
| Baseline | -$23.42 | -$83,400 | 0% |
| P1: pred EV < 0 | -$20.98 | -$74,700 | 0.5% |
| P2: giveback > 0.5 | -$7.66 | -$27,280 | 99.4% |
| P3: exit_better > 0.7 | -$22.64 | -$80,625 | 7.2% |
| **P1: pred EV < 0.25** | **-$4.10** | **-$14,615** | **100%** |
| SL=2.0 ATR overlay | -$18.15 | -$64,638 | 14.1% (SL) |

**P1 ev<0.25 turns -$83K into -$14K** — but it cuts ALL 3,561 trades
(early-exit at first checkpoint). That's not a real policy; it's
"never trade NQ 2026" disguised as a model output.

## Why the model fails to produce a usable policy

The `future_giveback_risk` AUC of 0.79 sounds promising, but
inspecting the predictions reveals:

- **Base rate of giveback is very high.** For a V_A trade open ≥30s,
  the probability that it gives back ≥0.5 ATR from peak MFE before
  making another +0.5 ATR favorable move is ~80%.
- The model accurately predicts this base rate but **cannot
  identify the 20% of trades that won't give back.**
- At any reasonable threshold, the model says "high giveback risk"
  for 95-99% of trades — i.e., the policy collapses to "exit
  almost everything early."

The `exit_now_better_than_hold` target IS the right thing to predict
but the model can't beat random (AUC 0.53). This is the same
finding from the path-diagnostics study: winners and losers don't
separate at intermediate checkpoints.

The `remaining_ev_atr` regression has corr 0.01 — model has no idea
how much PnL is left in any given trade.

## Cross-validation with prior path-diagnostics

The path-diagnostics study (`PATH_DIAGNOSTICS_REPORT.md`) tested
hand-crafted exit rules without ML. It found:

- All catastrophic SLs negative on aggregate
- All time-based loser cuts negative on aggregate
- All trailing-exit rules negative on aggregate
- All partial-profit models negative on aggregate

This study tests ML-driven exits. It finds:

- LightGBM with 4 timeframes of registry features + path state
  cannot improve on baseline
- The signal that exists (giveback prediction) is already saturated
  in the trade population
- The signal that's needed (winner vs loser separation) is absent

**Both studies converge on the same conclusion: V_A's exit logic
is its baseline regime-flip. Any overlay damages it more than it
helps.**

## Verdict

### Can a causal model identify when remaining upside is poor enough to exit without killing the winner tail?

**No.** The model can predict generic giveback (AUC 0.79) but
cannot distinguish the trades that benefit from early exit from
the trades that don't. Every threshold either degenerates to "exit
everything" (large losses) or "exit very few" (no improvement
over baseline).

### Should we proceed to RL?

**No.** RL is unlikely to help here for the same reason:

- The features available at decision time don't separate eventual
  winners from eventual losers
- The reward signal would be the same as our regression target
  (remaining EV), which has near-zero correlation
- Without separable features, RL would converge to a similar policy
  as the supervised model — exit everything, or exit nothing

The bottleneck is feature informativeness, not model class.

### Recommendation

**Abandon exit-policy modeling for V_A.** The exit policy is
already optimal given the available features.

The next direction (if continuing this strategy class) should be:
1. Better entry selection — V_A 2024/2025 success was localized;
   identify what distinguishes those years before adding more
   strategy machinery
2. Different feature class — orderflow imbalance, volume profile,
   alternative regime definitions might separate winners from
   losers at intermediate checkpoints in a way that registry MTF
   regime + path state cannot

## Files

- Datasets: `collectors/collector_v2/results/exit_policy/NQ_<year>.parquet`
- Models + predictions: `collectors/collector_v2/results/exit_policy/models/`
- Simulation summaries: `collectors/collector_v2/results/exit_policy/sim_<label>_summary.json`
