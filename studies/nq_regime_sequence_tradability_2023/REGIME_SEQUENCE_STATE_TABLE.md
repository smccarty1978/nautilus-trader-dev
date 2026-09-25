# Regime-sequence state table

Source: `artifacts/STATE_TABLE.csv`, `GATE_ARITHMETIC.csv`, `STATE_PERSISTENCE.csv`, `ROBUSTNESS_DIR_MTF.csv`.
The state definition is in `REGIME_SEQUENCE_FEATURE_DEFINITIONS.md`: equal-weight composite of `eff_5`,
`terr_ratio_5`, `flips_30m`, `frac_new_ext_4` and `n_near_0p5_6`, cut at block-A P20/P80. Nothing was tuned.

## Forward economics by state

All values are means in ATR units. "ex1%" = gross with the top 1% of trades removed.

| block | state | n | next gross | ex1% | next net | next MFE | +1A | +2A | next dur (min) | next-3 gross | next-3 eff | next-3 flips/30m | next-3 rotational |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | EXPANSION | 674 | −0.049 | −0.195 | −0.142 | 2.10 | 56.4% | 34.0% | 13.0 | −0.19 | 0.545 | 2.96 | 27.0% |
| A | MIXED | 2018 | −0.042 | −0.164 | −0.135 | 2.12 | 58.8% | 36.5% | 13.7 | −0.36 | 0.552 | 2.99 | 27.8% |
| A | ROTATION | 674 | −0.146 | −0.237 | −0.238 | 2.01 | 57.4% | 36.5% | 12.7 | −0.33 | 0.577 | 3.13 | 26.3% |
| A | NO_HISTORY | 1155 | +0.015 | −0.128 | −0.067 | 2.41 | 61.0% | 40.1% | 13.2 | −0.07 | 0.560 | 2.97 | 24.9% |
| B | EXPANSION | 222 | +0.088 | −0.026 | +0.005 | 2.20 | 55.9% | 39.6% | 13.4 | −0.05 | 0.529 | 3.12 | 31.0% |
| B | MIXED | 675 | +0.021 | −0.114 | −0.063 | 2.07 | 56.4% | 36.7% | 13.5 | −0.03 | 0.572 | 3.01 | 24.3% |
| B | ROTATION | 209 | −0.087 | −0.229 | −0.168 | 1.99 | 54.1% | 31.6% | 13.5 | −0.19 | 0.537 | 2.91 | 28.6% |
| B | NO_HISTORY | 397 | +0.041 | −0.073 | −0.034 | 2.37 | 63.2% | 36.3% | 13.2 | +0.03 | 0.546 | 2.88 | 27.1% |

A ROTATION state does **not** produce a more rotational future. Next-3 efficiency, flip rate, escape distance
and the "still within 1A" share match the other states in both blocks. The only gap is the next-regime P&L of
about −0.12A, which is not distinguishable from zero:

| ROTATION − rest | A | B | pooled |
|---|---|---|---|
| next gross | −0.120 [−0.268, +0.030] | −0.126 [−0.415, +0.152] | −0.122 [−0.241, +0.038] |
| next gross, top 1% removed | −0.048 [−0.168, +0.087] | −0.093 [−0.375, +0.210] | −0.060 [−0.171, +0.055] |
| next +2A reach | −0.6 pp | −5.5 pp | −1.8 pp [−4.7, +1.4] |
| next-3 gross | −0.09 [−0.40, +0.24] | −0.17 [−0.90, +0.52] | −0.11 [−0.42, +0.21] |
| next-3 efficiency | +0.024 | −0.019 | +0.014 [−0.011, +0.037] |

Brackets are 95% session-bootstrap intervals.

## What the ROTATION bucket contains (descriptive, not a policy)

| block | trades | ROTATION share | excluded gross / net | retained gross / net | all gross / net | retained gross ex1% |
|---|---|---|---|---|---|---|
| A | 4,521 | 14.9% | −0.146 / −0.238 | −0.026 / −0.116 | −0.044 / −0.134 | −0.157 |
| B | 1,503 | 13.9% | −0.087 / −0.168 | +0.039 / −0.043 | +0.021 / −0.060 | −0.081 |
| pooled | 6,024 | 14.7% | −0.132 / −0.221 | −0.010 / −0.097 | −0.028 / −0.116 | −0.138 |

Removing ROTATION moves the retained population by about +0.02A gross. Retained net stays at −0.10A, well
below zero, in both blocks. Cost is about 0.09A/trade, which is roughly five times what this "gate" recovers.

## Persistence

| state | P(same state at next flip) A / B | P(same state 3 flips later) A / B | base rate |
|---|---|---|---|
| EXPANSION | 52.0% / 54.5% | 23.4% / 23.3% | ≈20% |
| ROTATION | 49.5% / 51.3% | 27.4% / 26.2% | ≈20% |

This persistence is mechanical. Consecutive flips share 4 of the 5 regimes in the composite's windows, and flips
three apart share 2 of 5. The outcomes the state is supposed to describe do not persist: across
non-overlapping windows, next-3 efficiency at i vs i+3 has ρ = −0.015, and next-3 rotational has ρ = −0.015.

## Direction and MTF (Phase 6)

Next-regime gross, EXPANSION vs ROTATION:

| group | A: EXP / ROT | B: EXP / ROT |
|---|---|---|
| short | −0.18 / −0.22 | +0.30 / −0.12 |
| long | +0.08 / −0.08 | −0.14 / −0.05 |
| ALL_ALIGNED | +0.13 / −0.13 (n 188/139) | −0.02 / −0.13 (n 60/25) |
| ALL_OPPOSED | −0.16 / −0.35 | −0.18 / −0.07 |
| AAO | −0.47 / +0.06 (n 74/46) | +0.19 / 0.00 (n 22/22) |
| MIXED | −0.05 / −0.13 | +0.45 / −0.23 |

The ordering is not consistent across direction or MTF groups, and block B cells are 22–110 trades. I stopped
subdividing here.
