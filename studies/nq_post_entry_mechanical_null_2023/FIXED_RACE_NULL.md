# Fixed-price race vs the location-only null

## Definitions

**Outcome:** starting from the first 1s bar that touches +x·A (strictly before the terminal flip), does +2A
(from the original entry) come before −1A?
- The anchor bar itself is eligible.
- Trades that had already touched −1A at or before the anchor are excluded (418–670 per anchor).
- A same-bar double touch is ambiguous, and a race still open at the session close is censored. Together
  these exclude 19–61 per anchor.

**Nulls:**
- **N1 = (x + 1) / 3:** a driftless continuous path between fixed barriers.
- **N1c = (cur + 1) / 3:** the same, but started at the anchor bar's close, which accounts for overshoot.
- **N2:** 64 driftless paths per event. They are built from 30 s blocks of the preceding 3,600 s of real 1s
  bars (relative OHLC), sign-symmetrised per block, and scored with the same touch rules. N2 keeps discrete
  bars, tick size and local volatility.

## Pooled (discovery + replication)

| x | N | actual | N1 | N1c | N2 | actual − N1 [CI] | actual − N2 [CI] |
|---|---|---|---|---|---|---|---|
| 0.25 | 4,683 | 0.410 | 0.417 | 0.422 | 0.422 | −0.007 [−0.019, +0.008] | −0.012 [−0.025, +0.002] |
| 0.50 | 3,858 | 0.497 | 0.500 | 0.505 | 0.504 | −0.003 [−0.018, +0.014] | −0.007 [−0.022, +0.010] |
| 0.75 | 3,258 | 0.586 | 0.583 | 0.588 | 0.586 | +0.002 [−0.015, +0.019] | −0.001 [−0.017, +0.016] |
| 1.00 | 2,833 | 0.669 | 0.667 | 0.672 | 0.673 | +0.002 [−0.015, +0.019] | −0.004 [−0.022, +0.013] |
| 1.25 | 2,498 | 0.750 | 0.750 | 0.755 | 0.757 | 0.000 [−0.017, +0.017] | −0.007 [−0.025, +0.010] |
| 1.50 | 2,217 | 0.834 | 0.833 | 0.836 | 0.837 | 0.000 [−0.016, +0.015] | −0.003 [−0.019, +0.011] |

**Replication alone:** residuals are −0.6 to −1.5pp, and every CI contains zero.

**Corrections** (N1c − N1 and N2 − N1) are +0.1 to +0.8pp. The median overshoot at the anchor bar is
0.00–0.01A.

## Reading

This is about as clean a match to the analytic line as real data allows. At an exact location, the real NQ
path's chance of reaching +2A before −1A is **the location-only probability**. There is no momentum and no
mean reversion above about 2pp. The earlier conditional-continuation progression (49% → 63% → 80% for +2A
before the terminal flip) is almost entirely the geometry of being closer to the target.

Machine-readable: `artifacts/LEVEL_RESIDUALS.*` and `artifacts/EVENT_LEVEL.*` (columns `fixed_outcome`,
`N1`, `N1c`, `null_p_fixed`).
