# Regime exit — engine-null residual capture (2023 development sessions)

**Verdict by the frozen contract: `INCONCLUSIVE`.**

## What decides the verdict

1. **No lag state qualified.** A qualifying lag state needed a meaningful excess-giveback or excess-continuation
   residual at two adjacent anchors in discovery, not contradicted in replication. None met that.
2. **The per-tercile final-P&L precision cannot reach the 0.10A economic bar.** The discovery-block minimum
   detectable effect (MDE) is 0.20–0.42A at the primary anchors, because terminal P&L has a heavy right tail.
   That triggers the frozen INCONCLUSIVE clause instead of MECHANICALLY_NEUTRAL.

## What is resolved, and what is not

- **Resolved:** at every anchor, the *overall* expectancy of the existing exit equals the anchor location
  (the martingale value), and so does the engine null. The pooled residual is bounded to about ±0.1A.
- **Resolved:** the lag → giveback relationship is mechanical. The engine null reproduces it, and more
  strongly than the real data do.
- **Resolved:** where real paths depart from the null by lag, giveback and additional MFE depart *together*,
  in the same direction and by roughly the same amount. That pattern replicates. Any net expectancy effect
  does not: its sign flips between blocks.
- **Unresolved:** whether some lag tercile carries an expectancy residual in the ±0.1–0.3A range. The data
  cannot see effects that size per tercile.

**Answer to Q10: there is no evidence that changing this exit would improve expectancy.** As the prompt
requires, I stop here and propose no exit-optimisation study.

**Scope and freeze.**
- The contract was frozen at `d15fb461`, and the build and power table were committed at `531f0f9e`, both
  before any residual comparison was read.
- The final 20% of 2023 was never loaded, and 2024–2026 were not touched.
- No model was trained and no policy was simulated.

## Required answers

**1. What are the MDEs for the primary continuous residual quantities?**
Discovery / replication MDE, 80% power, session-clustered, for a single tercile:

| quantity | discovery | replication |
|---|---|---|
| final P&L | 0.20–0.42A | 0.32–0.77A |
| giveback | 0.08–0.18A | 0.11–0.28A |
| additional MFE | 0.21–0.41A | 0.30–0.74A |
| exit-below-entry | 4–5pp | 3–8pp |

For an anchor's overall mean, divide by about 1.7. Pooled overall final-P&L CIs are about ±0.07–0.15A.

**2. Does raw trigger lag predict giveback?**
**Yes, strongly, and mechanically.** Spearman ρ of MFE-to-trigger distance against giveback is 0.26 / 0.30 /
0.34 / 0.41 / 0.49 (real) at +0.5A / +1A / +1.5A / +2A / +3A. **The driftless engine null gives 0.34 / 0.40 /
0.47 / 0.54 / 0.71**, which is *stronger* than real. The raw relationship is what the exit does to any noisy
path.

**3. Does the real-minus-null residual show excess giveback that lag predicts?**
Residual giveback does rise with lag. The large-lag tercile gives back more than the null: +0.16 to +0.56A
pooled, and positive in both blocks at every anchor. The small-lag tercile gives back less: −0.15 to −0.31A.

**4. Does large lag produce excess additional MFE beyond the engine null?**
**Yes, and by about the same amount.** For the large-lag tercile, residual additional MFE is +0.17 / +0.17 /
+0.22 / +0.31 / +0.62A (pooled, +0.5A → +3A), positive in both blocks. The excess giveback and the excess
continuation are one phenomenon. Real paths in fast, large-lag states are **more volatile** than the null's
causal preceding-hour volatility assumes, so they range further both ways.

**5. Is expected final P&L, conditional on lag, different from the engine null?**
**No sign-stable difference.** Every tercile residual across all 4 lag measures and 5 anchors lies between
−0.10 and +0.16A pooled, and every CI contains 0. In the large-lag tercile it is −0.07 to −0.17A in discovery
but +0.07 to +0.82A in replication.

Overall, real mean final P&L equals the anchor location:

| anchor | real | engine null |
|---|---|---|
| +0.5A | 0.50A | 0.50A |
| +1A | 1.00A | 0.99A |
| +1.5A | 1.51A | 1.50A |
| +2A | 2.03A | 1.99A |
| +3A | 3.05A | 3.00A |

This is optional stopping, observed directly.

**6. Does the earlier speed → giveback effect survive in residual space?**
- **Giveback:** yes. Slow minus fast residual is −0.14 / −0.24 / −0.33 / −0.45 / −0.61A, with CIs excluding 0.
- **Additional MFE:** the same happens: −0.13 / −0.27 / −0.19 / −0.28 / −0.46A.
- **Final P&L:** slow minus fast is +0.01 / −0.03 / +0.14 / +0.18 / +0.15A, and every CI spans 0.

Fast trades are more volatile after the anchor than the null predicts. They are not worse in expectancy.
"Fast trades give back more" is true, but it comes with "fast trades run further". It is not a quality defect.

**7. How much P&L is lost between the flip decision and the next-1s-open fill?**
**Essentially none.** The mean fill gap is +0.005A in the trade's favour (engine null +0.002A), about 0.05 NQ
points. The surrender is the boundary lag, not the execution.

**8. How much of the low MFE capture remains after subtracting the engine-null capture?**
**None.** Across all trades:
- **Real:** mean final MFE 2.17A, mean final P&L −0.03A, so the capture ratio of means is −1.3%.
- **Engine null:** MFE 2.26A, P&L −0.01A, so −0.4%.
- **Residual final P&L:** −0.02A [−0.08, +0.04].

Low capture is the mathematical consequence of this exit on a driftless path, not anomalous market behaviour.

The outcome-defined top-MFE quintile shows 57% capture. That is selected on the outcome and has no
like-for-like null, so it is not evidence of anything.

**9. Which residual effects reproduce in the 51-session block, and which fall below its detection limit?**
- **Reproduced in direction:** the paired pattern, i.e. high-lag excess giveback together with high-lag excess
  additional MFE, and the low-lag mirror image. It appears at every anchor in both blocks. The same holds in
  speed residual space.
- **Not reproduced:** the sign of any lag-conditional expectancy residual. It flips between blocks.
- **Detection limit:** the replication block's per-tercile final-P&L MDE is 0.32–0.77A, so it cannot confirm
  or refute effects of 0.1–0.3A.

**10. Is there evidence that changing this exit could improve expectancy, rather than only reshape the
distribution?**
**No.** The existing exit's expectancy equals the location value at every anchor. The same exit on driftless
paths gives the same answer. Where real paths differ from the null, they differ in *variance*, symmetrically,
not in expectancy.

Tightening would trade the additional-MFE tail for retention, one for one in expectancy, before costs.
Changing the exit on this entry cannot be justified on expectancy grounds from these data. **Stopping as
instructed.**

## Protection facts (descriptive)

Where the causal pre-bar flip bound sits relative to entry, at each first touch:

| MFE reached | median trigger vs entry | trigger still below entry | median share of MFE protected |
|---|---|---|---|
| +0.5A | −1.19A | 100% | 0 |
| +1A | −0.93A | 99.7% | 0 |
| +1.5A | −0.69A | 94.8% | 0 |
| +2A | −0.36A | 73.7% | 0 |
| +3A | +0.42A | 32.2% | 13.5% |

The exit protects almost nothing until about +3A. Even so, real exit-below-entry rates by trigger bin match
the engine null closely. One exception is the +3A worst-trigger bin: 25.7% real against 11.1% null, but only
N = 101, so it is not interpretable.

## Trigger semantics (Phase 1)

**Flip rule** (`features/trackers/regime_dual_ema.py`, completed 1m bars only). A long flips when
close < ½·low + ½·EMA3_low_prev AND close < ⅕·low + ⅘·EMA9_low_prev, both strict. Shorts mirror this with highs.

The timeline records two kinds of trigger:
- **pre-bar bound** `min(EMA3_low, EMA9_low)`: the only anchor-time explanatory variable, and the loosest
  close that could flip;
- **realized threshold**: it absorbs that bar's own low. It is outcome-side and always at least as tight as
  the bound.

**Parity.** On all 80,353 in-trade minutes, "close beyond realized threshold" equals the engine's flip exactly.
Every trade has exactly one flip, at its audited terminal.

## Parity and lineage

- `mechanical_null.py` was extended in place behind an opt-in `econ` flag, with no extra random draws. The
  extended build reproduces all 25,333 original null rows bit-for-bit.
- Real exit price, gross P&L and flip-bar close match the audited values on 6,024 / 6,024 trades.
- T0, +3A and previously "decided" events use a separate random stream.
- 99.9% of simulated paths flip before the session close, so the terminal conditioning matches the real
  population.

## Files (`residual_capture/`)

- `CONTRACT.json` (frozen) and `RESIDUAL_CAPTURE_VERDICT.json`.
- `artifacts/`:
  - `EVENT_ECON` — one row per trade × anchor with real, null and residual values; reproduces every aggregate;
  - `TRIGGER_TIMELINE` — per in-trade minute: both boundary EMAs, pre-bar bound, realized threshold,
    distances, 1-bar movement, P&L;
  - `POWER`, `OVERALL_REAL_NULL_RESIDUAL`, `RESIDUAL_CURVES`, `LAG_RANK_CORRELATIONS`, `SPEED_RESIDUAL`,
    `SPEED_LAG_LINK`, `PROTECTION_MAP`, `LAG_BY_ADD_MFE_MAP`, `CAPTURE`;
  - `ECON_BUILD_AUDIT.json`, `RESIDUAL_RESULTS.json`.

```
INCONCLUSIVE
```
