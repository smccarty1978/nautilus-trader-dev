# Feature stationarity audit (target-blind, recorded before any fit)

**Starting point:** the constrained study's `stationary_full` surface (56 features). The 22 absolute-price
coordinates were already removed there and are not restored here.

**Rows used:** development train (2023-01-03 → 08-07, 4,521 rows) against development validation
(08-08 → 10-17, 1,503 rows). **Only feature values are read.** No label and no final-20% row is used.

| screen | rule (frozen in `DEVELOPMENT_CONTRACT.json`) | flagged |
|---|---|---|
| A — extrapolation | ≥ 25% of validation rows fall outside the development-train [min, max] | `prior_rotation_seq_{5m,15m,1h}` (100%) |
| B — within-year time proxy | \|Spearman(feature, observation_ts)\| ≥ 0.50 inside development train | `prior_rotation_seq_{5m,15m,1h}` (ρ = 1.000) |
| C — constant | a single value in development train | `checkpoint_seconds_since_flip`, `bars_1m` |
| D — named counters | `prior_rotation_seq_*` | the same three |

**Result:** 5 columns excluded, **51 kept** in `stationary_full`. `stationary_geometry_no_direction` has **44**:
it is `stationary_full` ∩ the audited geometry arm.

Nothing else comes close to a flag:
- **Extrapolation (A):** every kept feature has ≤ 2.3% of validation rows outside the training range.
- **Time proxy (B):** the largest |ρ| with time among kept features is 0.33 (`frozen_atr_1h`). The point-scale
  ATR columns show mild negative drift of −0.13 to −0.33, because volatility fell during 2023. They are below
  the frozen threshold and were kept.

**Leak guard:** every arm was also checked for columns prefixed `fp_`, `terminal_`, `f5_`, `fav`, `adv`,
`target`, `executable_` or `flip_`. None was present.

Full table: `artifacts/STATIONARITY_AUDIT.csv`.
