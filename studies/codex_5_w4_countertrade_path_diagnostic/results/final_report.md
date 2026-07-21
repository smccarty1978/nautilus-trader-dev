# codex_5 W4 Countertrade Path Diagnostic

## Final decision

`BOTH_EARLY_AND_POST_FLIP_MANAGEMENT_PROMISING`

This is an exploratory path diagnostic, not a new policy test. No thresholds
were optimized, no entry/stop/exit rule was changed, and no 2026 result was used
for selection.

## Executive summary

The frozen study contains 4,383 trades and 1,320,819 path checkpoints whose
price and W4 values are causal as of their stored mark/observation times: 1,476
stops before the aligning flip, 375 stops after it, 1,360 planned-exit winners,
and 1,172 planned-exit losers.

Outcome groups and selection of the named holding-peak row are retrospective
descriptive labels; neither would be available to a live policy at that time.

The main evidence is price-path separation rather than a standalone W4 exit:

1. **A 60-120 second probation window is informative.** At +60s, planned-exit
   winners have median +0.255 ATR PnL versus -0.103 for later post-flip stops
   and -0.439 for pre-flip stops. By +120s those medians are +0.541, -0.133,
   and -0.748 ATR. MAE separates even more strongly.
2. **Most pre-flip stops are weak entries, but a meaningful minority first
   offers tradable excursion.** Median conservative MFE before stop is only
   0.317 ATR, although 33.7% reach 0.50 ATR and 18.2% reach 0.75 ATR.
3. **Post-flip giveback is large and plausibly manageable.** Planned-exit
   losers are positive at the aligning flip (median +0.581 ATR), reach median
   1.378 ATR post-flip MFE, then exit at -0.585 ATR: median giveback is 1.951
   ATR. Post-flip stop-outs show the same shape.
4. **W4 alone is generally too late for failed trades.** The first aligned-
   regime W4 warning arrives with median PnL -0.262 ATR for planned losers and
   -0.742 ATR for post-flip stops. Only 30.4% and 12.5%, respectively, are still
   profitable at that warning. W4 progression may still help when conditioned
   on retained gains, but a bare W4 exit is not supported.

## Contract and limitations

- All price excursions use `atr_at_checkpoint`, matching the frozen 1.5 ATR
  stop denominator.
- A checkpoint at `t` uses completed 1-second ranges in `[entry,t)` and a
  backward-only W4 score no more than five seconds stale.
- At an aligning flip or planned exit, the known explicit next available open
  is included as a reached discrete price.
- For stop exits, primary pre-stop MFE excludes the stop bar because favorable
  and adverse ordering within that 1-second OHLC bar is unknown. The machine
  diagnostic retains a stop-bar upper bound separately.
- Before the aligning flip, W4 belongs to the original regime. After the flip,
  it resets to the new aligned regime; it is never carried through the regime
  boundary. Cross-regime changes are labeled as such in the path file.
- Fixed +60/+120 rows remain present after an early exit and are explicitly
  marked counterfactual, preventing survivor-only early-window summaries.
- OHLC peaks are localized to their open-labelled bar but become available and
  receive their named checkpoint at `ts_event+1s`. Not-applicable summary cells
  (for example, post-flip metrics for pre-flip stops) are stored as null.

## 1. Stop before aligning flip

Primary MFE is conservative and excludes the unknown stop-bar range.

| Metric | Result |
|---|---:|
| Trades | 1,476 |
| Median MFE before stop | 0.317 ATR |
| Reached +0.25 ATR | 56.6% |
| Reached +0.50 ATR | 33.7% |
| Reached +0.75 ATR | 18.2% |
| Reached +1.00 ATR | 9.8% |
| Median time to peak MFE availability | 17s |
| Median peak-availability-to-stop time | 140s |
| W4 still above threshold before stop | 1.6% |
| Median W4 change, entry to pre-stop | -0.435 |
| Old prevailing regime set a new favorable extreme | 11.5% |

**Evidence:** W4 usually collapses back below its trigger, and the old regime
usually does not extend to a fresh favorable extreme. Most of these trades do
not contain enough favorable excursion to solve with simple profit protection.
However, one third reach 0.50 ATR and nearly one fifth reach 0.75 ATR, so a
smaller pullback-like subset may be manageable.

The pattern is stable: median MFE is 0.330 ATR in 2025 and 0.254 in 2026;
0.322 for long fades and 0.310 for short fades; 0.293 in ETH and 0.351 in RTH.

## 2. Stop after aligning flip

| Metric | Result |
|---|---:|
| Trades | 375 |
| Median PnL at aligning flip | +0.325 ATR |
| Median post-flip peak MFE | 0.827 ATR |
| Median giveback, post-flip peak to stop | 2.352 ATR |
| Reached at least 0.50 ATR post-flip | 69.6% |
| Reached at least 1.00 ATR post-flip | 41.3% |
| Aligned W4 warning before stop | 76.5% |
| Median warning time after flip | 160s |
| Median PnL at warning | -0.742 ATR |
| Still profitable at warning | 12.5% |
| Warning occurred before peak | 7.0% |

**Evidence:** these trades often become meaningfully profitable after the flip,
then surrender more than the full 1.5 ATR stop distance from their peak. Faster
price-based management could plausibly protect gains. The frozen W4 warning,
used alone, usually arrives after the profit has already disappeared.

## 3. Planned-exit winners versus losers

| Metric (median unless noted) | Winners | Losers |
|---|---:|---:|
| Trades | 1,360 | 1,172 |
| PnL at aligning flip | +0.833 ATR | +0.581 ATR |
| Post-flip peak MFE | 3.846 ATR | 1.378 ATR |
| Time from flip to peak availability | 639s | 75s |
| Realized PnL | +1.602 ATR | -0.585 ATR |
| Realized capture ratio | 0.412 | -0.408 |
| Peak-to-exit giveback | 2.150 ATR | 1.951 ATR |
| First aligned-W4 warning after flip | 520s | 235s |
| PnL at first warning | +1.359 ATR | -0.262 ATR |
| Warning before exit | 89.3% | 84.7% |
| Profitable at warning | 88.8% | 30.4% |
| Warning occurred before peak | 39.0% | 7.2% |

**Evidence:** planned losers are not simply trades that never work. 91.9% are
positive at the aligning flip, 91.7% reach at least 0.50 ATR post-flip, and
71.6% reach 1.00 ATR. Their peaks arrive quickly and are then surrendered over
a median 238 seconds before exit. This is strong evidence that the natural
opposing-flip exit is too slow for a large losing subset.

Winners also give back heavily, but their trends persist much longer and reach
far larger MFE. W4 warning timing distinguishes the economic state more than
warning incidence: warnings are common in both groups, but usually occur while
winners retain gains and after losers have lost them.

The post-flip structure is consistent in both years. Planned-loser median
giveback is 1.936 ATR in 2025 and 1.990 in 2026; winner peak MFE is 3.860 and
3.806. Long/short and RTH/ETH splits preserve the same ordering.

## 4. Early probation window

These fixed-horizon values include counterfactual marks after early exits and
therefore do not condition on survival.

| Outcome | +60s PnL | +60s MFE | +60s MAE | +60s W4 Δ | +120s PnL | +120s MFE | +120s MAE |
|---|---:|---:|---:|---:|---:|---:|---:|
| Planned winner | +0.255 | 0.606 | 0.280 | -0.058 | +0.541 | 0.997 | 0.370 |
| Planned loser | +0.145 | 0.528 | 0.321 | -0.148 | +0.197 | 0.762 | 0.448 |
| Stop after flip | -0.103 | 0.409 | 0.414 | -0.260 | -0.133 | 0.574 | 0.663 |
| Stop before flip | -0.439 | 0.236 | 0.751 | -0.131 | -0.748 | 0.281 | 1.161 |

At +60s, W4 remains above the active threshold for 45.7% of future winners,
34.0% of planned losers, 22.3% of post-flip stops, and 26.4% of pre-flip stops.
By +120s those rates compress to 28.6%, 21.5%, 20.2%, and 20.9%.

The 2025/2026 medians are directionally consistent. At +120s, winner PnL is
+0.547/+0.518 ATR, while pre-flip-stop PnL is -0.747/-0.759 and MAE is
1.162/1.137 ATR. Thus +60s offers earlier, weaker separation; +120s offers
stronger separation but many pre-flip stops have already failed or are close
to the 1.5 ATR stop.

## Strongest path differences

1. Early PnL and MAE distinguish future winners from both stop groups by +60s
   and widen materially by +120s.
2. Planned losers peak early after the aligning flip (75s median) while winners
   continue for 639s; this persistence gap is larger than the difference in PnL
   at the flip.
3. Old-regime continuation is not the main cause of pre-flip stops: only 11.5%
   set a new old-regime favorable extreme.
4. W4 trigger persistence has some early separation, but W4 changes fall across
   all groups and are not sufficient alone.
5. First post-flip W4 warnings are common but usually too late for failed trades.

## Evidence versus speculation

**Supported by this diagnostic:** early price-path separation exists; a minority
of pre-flip stops has monetizable MFE; post-flip stops and planned losers show
large preventable-looking giveback; unconditioned aligned-W4 warnings are late.

**Not established:** that any probation exit, break-even rule, trailing stop, or
W4-conditioned exit improves net expectancy. This study did not simulate those
rules, did not model additional fills, and did not select thresholds.

## Recommended next policy hypotheses

Limited to three candidates for a later, separately frozen test:

1. **One early probation rule:** use 2021-2024/2025 only to freeze a single
   +60s or +120s failure definition based on countertrade PnL/MFE/MAE, then test
   it unchanged on 2026. Do not grid both windows and many cutoffs.
2. **One post-flip retention rule:** after the aligning flip and a causal profit
   milestone, protect a fixed portion of achieved MFE instead of waiting for the
   next opposing flip. This directly targets the 1.95-2.35 ATR median giveback.
3. **W4 plus retained-profit confirmation:** test the first aligned-regime W4
   warning only when price still retains a predefined positive fraction of MFE.
   Do not test W4 warning alone; the diagnostic shows it is usually too late for
   failed trades and could truncate long-running winners.

## Deliverables

- `path_checkpoints.parquet`: full 5-second and exact event-aligned paths.
- `outcome_group_summary.parquet`: compact overall/year/direction/session
  summaries.
- `early_window_summary.parquet`: +60s/+120s probation summaries.
- `post_flip_exit_diagnostic.parquet`: trade-level post-flip and W4-warning
  diagnostics.
- `run_manifest.json`: output counts and SHA-256 hashes.

No new policy backtest was run.
