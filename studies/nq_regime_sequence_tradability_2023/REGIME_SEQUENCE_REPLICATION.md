# Replication across development blocks

Block A = 154 sessions (4,521 regimes), block B = 51 sessions (1,503 regimes). Quintile edges come from A only.
Sources: `artifacts/FEATURE_SPREADS.csv`, `CONTROLS_AND_PERSISTENCE.json`, `REGIME_SEQUENCE_ATLAS.parquet`.

## Base rates

| block | next gross | next net | next MFE | +1A | +2A | next-3 gross | next-3 eff |
|---|---|---|---|---|---|---|---|
| A | −0.044 | −0.134 | 2.17 | 58.8% | 37.0% | −0.25 | 0.557 |
| B | +0.021 | −0.060 | 2.16 | 57.8% | 36.3% | −0.04 | 0.554 |

## Top quintile minus bottom quintile, per feature

| feature | next gross A | next gross B | next-3 gross A | next-3 gross B | pooled next-3 95% CI |
|---|---|---|---|---|---|
| eff_3 | −0.02 | +0.04 | +0.14 | −0.43 | [−0.37, +0.43] |
| eff_5 | −0.17 | +0.08 | −0.64 | −0.05 | [−0.89, −0.06] (opposite to the hypothesis) |
| eff_clock_30m | −0.03 | +0.05 | +0.06 | −0.18 | [−0.33, +0.39] |
| flips_30m | −0.05 | +0.26 | −0.20 | +0.18 | [−0.46, +0.24] |
| dur_mean_3 | +0.09 | −0.47 | −0.09 | −0.26 | [−0.54, +0.35] |
| terr_ratio_5 | +0.11 | −0.16 | −0.21 | −0.01 | [−0.64, +0.27] |
| chan_width_5 | −0.02 | −0.14 | −0.17 | +0.09 | [−0.53, +0.32] |
| prog_same_last | +0.15 | −0.18 | +0.48 | +0.07 | [+0.15, +0.60] |
| prog_opp_last | +0.08 | −0.07 | −0.12 | −0.15 | [−0.36, +0.13] |
| frac_new_ext_4 | +0.39 | −0.17 | +0.24 | −0.57 | [−0.73, +0.94] |
| flip_disp_6 | +0.02 | +0.08 | −0.29 | −0.82 | [−0.94, +0.08] |
| n_near_0p5_6 (≥2 vs 0) | +0.08 | −0.22 | −0.16 | +0.35 | [−0.40, +0.33] |
| headroom_same | +0.14 | −0.21 | +0.51 | −0.13 | [−0.01, +0.71] |
| fails_at_level (≥1 vs 0) | −0.09 | −0.22 | −0.29 | −0.35 | [−0.57, −0.07] |
| rng_ratio_3v3 | +0.18 | −0.26 | +0.23 | +0.80 | [−0.10, +0.93] |
| rng_mean_3 | +0.29 | −0.20 | +0.44 | +0.25 | [−0.02, +0.80] |
| htf5_prog | −0.14 | −0.07 | −0.23 | −0.56 | [−0.73, +0.07] |
| htf15_prior_disp | −0.03 | −0.15 | +0.23 | −0.46 | [−0.43, +0.63] |

**Sign agreement between A and B:** next gross 5/18 (chance ≈ 9), next-3 gross 10/18, next-3 efficiency 12/18.
Next-regime gross replicates *less* often than coin-flipping would.

**Pooled next-3 CIs that exclude zero:** 3 of 18 (`eff_5`, `prog_same_last`, `fails_at_level`). About 1–2 are
expected by chance, and the next-3 sums of neighbouring flips overlap, which widens the true uncertainty.
`eff_5` points the wrong way for the hypothesis (more efficient history → worse future) and is −0.05 in B.
`prog_same_last` is +0.48 in A and +0.07 in B.

**The one same-sign residual is `fails_at_level ≥ 1`** ("the last same-direction stall level was hit before").
It covers about 25% of trades:

| block | next gross, 0 → ≥1 | top 1% removed | +2A reach | next-3 eff | per-block 95% CI of the next-gross gap |
|---|---|---|---|---|---|
| A | −0.043 → −0.13 | −0.167 → −0.22 | 35.8% → 36.4% | 0.551 → 0.568 | [−0.30, +0.10] |
| B | +0.069 → −0.16 | −0.069 → −0.27 | 36.2% → 36.9% | 0.566 → 0.525 | [−0.50, +0.05] |

It has no mechanism signature (reach and forward efficiency are unchanged), both per-block intervals include
zero, and its whole-population Spearman with next gross is −0.018. It is recorded as a lead for a pre-registered
single-contrast test, not as a finding.

## Positive controls (the null is not a plumbing failure)

| check | ρ |
|---|---|
| `flips_30m` ~ `dur_mean_3` | −0.872 |
| `eff_5` ~ `terr_ratio_5` | +0.627 |
| hindsight: next-3 efficiency ~ next-3 gross | +0.339 |
| hindsight: next-3 escape ~ next-3 gross | +0.684 |

The features measure what they claim, and the expansion/rotation distinction is real *in hindsight*: forward
sequences that escape the start area pay.

## Why nothing carries forward: ATR-normalised regime statistics have no memory

| lag (regimes) | duration | abs displacement / A | range / A | gross | range (points) | ATR |
|---|---|---|---|---|---|---|
| 1 | −0.001 | +0.030 | +0.036 | +0.022 | +0.373 | +0.913 |
| 2 | +0.016 | +0.014 | +0.014 | +0.009 | +0.340 | +0.849 |
| 3 | +0.004 | +0.002 | −0.021 | +0.001 | +0.300 | +0.787 |

Volatility clusters strongly in points. The V_A engine measures everything in ATR, and ATR tracks that clustering
(ρ 0.91), so what is left is memoryless. Regime duration has zero autocorrelation, which is consistent with the
flat ~8%/min terminal hazard found in `nq_t0_segment_path_atlas_2023`. Non-overlapping forward state is equally
memoryless: next-3 efficiency at i vs i+3 has ρ = −0.015 and next-3 flip rate has ρ = +0.019.
