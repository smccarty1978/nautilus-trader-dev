# Development model results — +2A before the terminal flip (60% → 20%)

**Target:** +2A reach before the terminal flip (entry-ATR, audited exactly). **Arm:** `stationary_full`, 51 features.

**Setup:** development train is 154 sessions / 4,521 rows; validation is 51 sessions / 1,503 rows. The
+2A rate is 36.33% in validation. The ladder is the frozen one reused from the constrained study (100
rounds, min_data_in_leaf 200, L2 10, feature_fraction 0.7, bagging 0.7 / freq 1, seed 42); only tree depth
varies.

**Canary:** Target A shuffled once, seed 20260923, on development train only.

**Uncertainty:** session-blocked bootstrap, 2,000 reps. Controls are exact-cell empirical +2A rates.

| config | leaves | shuffled train AUC | real train AUC | **validation AUC** [95% CI] | Δ vs `direction_only` [CI] | Δ vs `mtf_state_only` [CI] |
|---|---|---|---|---|---|---|
| L1_stumps | 200 | 0.577 | 0.581 | **0.513** [0.478, 0.545] | +0.001 [−0.046, +0.045] | +0.011 [−0.043, +0.061] |
| L2_depth2 | 367 | 0.636 | 0.630 | **0.505** [0.474, 0.537] | −0.007 [−0.050, +0.035] | +0.003 [−0.047, +0.051] |
| L3_depth3 | 595 | 0.676 | 0.677 | **0.512** [0.482, 0.542] | −0.000 [−0.040, +0.039] | +0.010 [−0.040, +0.058] |
| control `direction_only` | — | — | 0.510 | **0.512** [0.484, 0.541] | | |
| control `mtf_state_only` | — | — | 0.534 | **0.502** [0.469, 0.537] | | |

**Bagging:** active in every configuration. Predictions differ from a `subsample_freq=0` refit by up to
0.059 / 0.070 / 0.106.

## Gate (frozen before fitting) — no configuration passes

| config | G1 canary ≤ 0.70 | G2 AUC CI > 0.50 | G3 beats both controls by ≥ 0.02, CI > 0 | G4 monotone +2A & Q5 ≥ pooled + 5 pp | G5 support | G6 not variance |
|---|---|---|---|---|---|---|
| L1_stumps | pass | **fail** | **fail** | **fail** (ρ −0.1; Q5 −2.3 pp) | pass | **fail** |
| L2_depth2 | pass | **fail** | **fail** | **fail** (ρ −0.1; Q5 −2.8 pp) | pass | **fail** |
| L3_depth3 | pass | **fail** | **fail** | **fail** (ρ 1.0 but Q5 only +1.0 pp) | pass | **fail** |

**The canary passes, but it proves nothing about signal.** The real-label training fit is the same as the
shuffled-label fit, within ±0.006. In L2 the real-label value is actually lower. Whatever the trees fit
in-sample is capacity, not +2A structure.

G6 (not variance) fails in every configuration. From Q1 to Q5, −1A reach rises by +5.4 / +6.4 / +6.1 pp,
while +2A reach changes by −0.3 / −2.6 / +3.3 pp. What little ordering exists runs toward **more adverse
excursion**, not better development.

Selection: none. **`NO_T0_DEVELOPMENT_SIGNAL`**. The final 20% was not opened.

Machine-readable: `artifacts/DEVELOPMENT_MODEL_RESULTS.{csv,parquet}` and `artifacts/DEVELOPMENT_GATE.json`.
