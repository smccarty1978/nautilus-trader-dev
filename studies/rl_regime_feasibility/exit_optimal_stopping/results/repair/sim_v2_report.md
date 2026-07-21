# Exit Optimal Stopping v2 — Repaired Simulation

**Warning:** VAL PERIOD ONLY (Jan–Feb 2025). Test period pending full retrain.

## Ghost Row Removal

- Original post-stop checkpoints removed: 268,573
- Episodes with stop hit before regime end: 7,249
- Truncated checkpoint pool (train+val): 2,744,180

## Policy Results (val period, base cost)

| Policy | EV/trade | vs E0 |
|--------|---------|------|
| E0_regime | $8.60 | +0.00 |
| E1_fixed_300s | $-2.54 | -11.14 |
| E4_hazard | $1.05 | -7.55 |
| E5_fitted_q | $10.13 | +1.52 |
| E5_fitted_q_h2 | $7.72 | -0.88 |

## Feature Baseline Comparison (val period, E5 only)

| Model | Features | E5 EV/trade |
|-------|---------|------------|
| MINIMAL | 5 | $2.97 |
| MINIMAL_PLUS | 10 | $8.26 |
| FULL | 57 | $10.13 |

## Controls (val period, base E5 as reference)

| Control | EV/trade | vs E5 | Verdict |
|---------|---------|-------|---------|
| C1_label_shuffle | $-1.03 | -11.15 | PASS (causal) |
| C2_seq_shuffle | $-25.34 | -35.47 | OK |
| C3_lag_5s | $10.32 | +0.19 | OK |
| C4_future_lead | $14.06 | +3.93 | PASS (oracle improves) |
| C5_post_stop_signals | 0 violations | — | PASS |
| C6_pullback_shuffle | $10.03 | -0.10 | OK |

## Verdict

INCONCLUSIVE: E5 EV = $10.13/trade on val period.

> Next: expand to full train/val/test; then NT live-style validation.