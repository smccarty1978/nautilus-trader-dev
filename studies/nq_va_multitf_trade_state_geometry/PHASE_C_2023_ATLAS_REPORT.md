# PHASE C — 2023 DESCRIPTIVE LIFECYCLE ATLAS
`nq_va_multitf_trade_state_geometry` · discovery year 2023 only · 2024 not opened · 2025/2026 untouched

**Frame:** the v4 2023 TRAIN partition `_work/controller/partitions/train/2023`.
- seal `ba69ad0b…1ec1` · plan `11fcaf24…e557` · closure `c9249f99…8356`
- observations sha256 `40ce405b…c589` · candidates sha256 `ef03d393…58ca`
- All hashes were verified against the partition manifest at every run.
- 7,489 T0 trades; **7,475 have a resolved terminal**. 14 are excluded: 12 terminal flips censored at SESSION_END, 2 exit fills unavailable.

**Code:** `analysis/phase_c_atlas_2023.py` builds the atlas. `analysis/replication_readout.py` holds the frozen claims; its 2023 self-test returns REPLICATED.
**Machine-readable tables:** `artifacts/phase_c_2023_*.json|parquet`. Every cell there carries N; cells with N < 100 are reported with N only.

### Coordinates used everywhere
| symbol | meaning |
|---|---|
| **A** | `atr_entry_1m`: the 1m Wilder ATR frozen at the confirmed flip. It is the outcome contract ATR. Median 8.55 pts (p5 5.0, p95 16.3). |
| **T0** | The first checkpoint, which is the **flip-bar close + 15 s**. The cadence does not emit a row at the close itself. |
| **E** | The executable entry: the next 1s open after T0. |
| **s** | Seconds since E. Checkpoint k sits at s = 15k (k = 0..19, so s = 0..285). |
| **pnl** | `terminal_gross_pnl_atr`: E to the open of the first bar after the next confirmed opposite 1m flip, in A. Gross; net is not available because no cost contract was declared. |
| HTF distances | Each timeframe (5m/15m/1h) is expressed in its **own frozen ATR** (`A5m`, `A15m`, `A1h`) and, separately, in **A** (`…_A1m`). The two are never mixed. |

### Frame semantics established here (read these before reusing the frame)
1. **The milestone arms run past the opposite flip, up to the trading-day close.** A rung therefore counts as reached *in the lifecycle* only if `resolution_seconds ≤ time from E to the flip`. Because the arms outlive the lifecycle, the in-lifecycle status of every rung is **fully observed for all 7,475 resolved trades**, with no censoring inside the lifecycle.
   - The 81% "milestone resolved" figure in the verification card includes post-flip passages. It is not a lifecycle statistic.
2. **The 1m excursion columns are anchored at the flip-bar OPEN, not at E.** `mfe_atr_1m`, `pnl_atr_1m`, `highest_high_1m` and `start_price_1m` all use that anchor. At T0, E is already +0.88A (median) from that anchor: `entry_ext_A`.
   - Path state after entry is therefore re-anchored to E in two ways: `last_close_1m`, and the entry-anchored milestone ladder.
3. **2,051 checkpoint rows fall exactly at the trade's own opposite flip.** The tracker has not yet processed the flip at that instant, so those rows carry the *next* terminal. They are excluded from every post-entry analysis.
4. **HTF tracker state is as of the last completed 1m bar.** This covers start, HH/LL and frozen ATR. E is a 1s price, so `loc_in_range` can slightly exceed [0, 1]. This is causal and verified to reconstruct `pnl_atr_<tf>` to within one 1m bar of drift.

---

## 1. EXECUTIVE SUMMARY
- **The untreated 1m V_A flip-to-flip trade is gross break-even in 2023.** Mean −0.031A (session-day-clustered SE 0.028); median −0.73A; 29% win (> +0.25A), 62% lose (< −0.25A).
  - The whole expectancy is the right tail. Outside the best 5% of trades the mean is −0.41A; the best 5% sum to +2,698A against a total of −230A.
- **The lifecycle is asymmetric by construction.** The favorable ladder continues at a nearly constant, slightly *rising* per-A rate: 0.63 → 0.68 per A from +1A to +5A. 11% of trades reach +5A.
  - The adverse ladder collapses past −1A (0.30, then 0.19 per A). Only 2.7% reach −3A, because the opposite flip is the stop.
  - For every trade that never reaches +2A, **the terminal equals the lifecycle adverse extreme**: Spearman(pnl, −MAE rung) = 0.90, and mean(pnl + MAE rung) = +0.01A.
- **T0 higher-timeframe geometry carries essentially no lifecycle information in 2023.** Across 52 features the strongest association is |Spearman| 0.021, and |AUC − 0.5| ≤ 0.025 for both rapid failure and runner formation. The features cover 5m/15m/1h direction tuple, regime age, bars, MFE/MAE, displacement, retained ratio, range, ATR ratio, current-regime location and distances, and prior-5m shape.
  - The 8 directional configurations differ by at most ±0.2A of mean gross, with SEs of 0.05–0.14.
  - Runners are born in the same HTF geometry as everything else.
- **The only T0 variable with structure is the 1m flip's own extension** (E versus the flip-bar open). It scales **both** tails: AUC 0.63 for reaching −2A and AUC 0.55 for reaching +3A. Its correlation with pnl is −0.04. It changes scale, not sign.
- **The lifecycle separates clearly by path, not by T0 state.** By s = 30–120, path state (MAE so far, 60s giveback) predicts eventual −1A with AUC 0.66–0.70, versus 0.55 at T0. P(future +3A) ranges 0.11–0.63 across states.
  - But **remaining gross expectancy from every observed state is ≈ 0.** Only 2 of 72 state cells have |z| > 2, which is below chance.
  - Path state predicts where the barriers are relative to E (spread), not the drift from here.
- **Four of the five candidate management problems do not appear as clean clusters.** There is no "quiet stagnation" at all (7 of 7,475 trades): a flip-to-flip lifecycle cannot stall.
  - "Giveback" is not a separate population. It is the exit mechanism: 33% of trades reach +1–3A and then give back to below half of it, while only 1.6% hold.
  - Rapid versus slow failure is a continuum: the log time to −0.5A is unimodal.
- **The data supports a two-stage decomposition:**
  1. an early-thesis-failure / loss-scale head that becomes observable after entry;
  2. a runner-preservation head (whether a +1–2A trade continues or is flipped out).

  No T0 "entry-quality" head is supported by HTF geometry. See §11.

## 2. WHAT A V_A FLIP ACTUALLY DOES AFTER ENTRY
`phase_c_2023_population_summary.json`, `phase_c_2023_milestone_atlas.json`

**Terminal gross (A), n = 7,475:**

| stat | p1 | p5 | p25 | p50 | p75 | p95 | p99 | max | mean |
|---|---|---|---|---|---|---|---|---|---|
| value | −3.33 | −2.25 | −1.39 | −0.73 | +0.61 | +4.47 | +8.45 | +37.8 | −0.031 |

- Long mean +0.043 (n 3,754); short mean −0.105 (n 3,721). 2023 was a strong NQ up-year, so this asymmetry is not treated as structural and no claim is made on it.
- Duration: p10 165 s, p50 585 s, p90 1,785 s, max 7,365 s. 2.8% exit after 15:15 CT.

**In-lifecycle milestone incidence** (P reached; median s to reach, given reached):

| rung | +0.25 | +0.5 | +0.75 | +1 | +1.5 | +2 | +3 | +4 | +5 |
|---|---|---|---|---|---|---|---|---|---|
| P | .860 | .753 | .663 | .588 | .465 | .368 | .240 | .163 | .110 |
| med s | 18 | 54 | 102 | 152 | 251 | 356 | 571 | 770 | 935 |

| rung | −0.25 | −0.5 | −0.75 | −1 | −1.5 | −2 | −3 |
|---|---|---|---|---|---|---|---|
| P | .903 | .801 | .689 | .571 | .312 | .135 | .027 |
| med s | 18 | 54 | 98 | 138 | 186 | 226 | 222 |

**Races** (P(+X before −Y), with P(−Y before +X) in parentheses):

| | −0.25A | −0.5A | −1A | −2A |
|---|---|---|---|---|
| +0.25A | .49 (.51) | .65 (.35) | .79 (.21) | .85 (.05) |
| +0.5A | .33 (.67) | .49 (.51) | .65 (.33) | .74 (.08) |
| +1A | .20 (.80) | .32 (.67) | .48 (.47) | .58 (.11) |
| +2A | .11 (.88) | .19 (.78) | .29 (.56) | .36 (.13) |

- The symmetric races are coin flips (±0.25: 49/51; ±0.5: 49/51; ±1: 48/47).
- The early path has no directional edge in its first half-ATR.

**Excursion before the opposite milestone** (ladder lower bounds, which are exact on the collected grid):
- **MFE before the first −0.25A:** 0 for 57% of the 6,750 trades that reach −0.25A; ≥ +1A for 11%.
- **MFE before the first −1A:** 0 for 36%; ≥ +1A for 17%.
- **MAE before the first +1A** (n 4,395): 0 for 33%; ≥ −1A for 18%.
- **MAE before the first +2A** (n 2,752): ≥ −1A for 21%. Runners routinely survive a −1A excursion first.
- These are the requested MFE/MAE-before quantities. They are recoverable only to the resolution of the ladder rungs, not to the tick.

**The exit mechanism.** In the joint MFE-rung × MAE-rung table (`joint_mfe_mae_rung_mean_pnl`), below MFE +2A the mean terminal sits within about 0.1A of −MAE rung in every row.
- The opposite flip fires at the adverse extreme, typically 1–1.5A adverse.
- A trade must reach roughly +2A for the flip exit to lock anything in. From +3A the median capture is 81% of the rung, and from +5A it is 85%.

## 3. MULTI-TIMEFRAME ORIENTATION
`phase_c_2023_mtf_direction_atlas.json|parquet`: 8 relative configurations × {pooled, long, short}, plus the 16 raw direction tuples.

| 5m/15m/1h vs 1m | n | share | mean A (SE) | median | P(+3A) | P(−2A) | early fail |
|---|---|---|---|---|---|---|---|
| A A A (all aligned) | 1,586 | .21 | +0.071 (.065) | −0.67 | .252 | .141 | .392 |
| A A O | 634 | .08 | **−0.222 (.084)** | −0.83 | .240 | .137 | .423 |
| A O A | 237 | .03 | +0.012 (.137) | −0.72 | .257 | .152 | .346 |
| A O O | 590 | .08 | −0.103 (.105) | −0.73 | .222 | .141 | .414 |
| O A A (1h+15m aligned, 5m opposed) | 909 | .12 | −0.062 (.069) | −0.75 | .220 | .149 | .385 |
| O A O | 356 | .05 | −0.031 (.116) | −0.68 | .261 | .121 | .402 |
| O O A (1h aligned, 15m+5m opposed) | 957 | .13 | +0.015 (.076) | −0.77 | .240 | .127 | .380 |
| O O O (all opposed) | 2,206 | .30 | −0.042 (.054) | −0.73 | .238 | .126 | .408 |

- The runner rate is 0.22–0.26 in every configuration, and the early-failure rate is 0.35–0.42.
- The "1h+15m aligned, 5m opposed" versus "all aligned" contrast the question asked about is −0.06 versus +0.07 (difference 0.13, SE ≈ 0.095).
- The one nominally distinct cell is **5m+15m aligned but 1h opposed** (−0.22, z ≈ −2.6 against 0). It is the most extreme of 8 cells. It is carried to 2024 as a *secondary, weak* claim (C11), not a finding.
- Counting aligned HTFs (0/1/2/3) gives −0.04 / −0.03 / −0.11 / +0.07: not monotone.

## 4. CURRENT HTF REGIME GEOMETRY
`phase_c_2023_htf_geometry_atlas.json|parquet`

**Method.** Each variable is cut into 2023 quintiles within {HTF aligned, HTF opposed}, per timeframe; edges are recorded. Maturity variables are age, bars, MFE, MAE, displacement, retained ratio, range and HTF/1m ATR ratio. Geometry variables are distance to the HTF favorable and adverse extremes, location in range, and distance to the extreme and to the start in A.

**Result: flat, at every timeframe.**
- Across 72 (variable × relation) series the Spearman correlation with pnl lies in [−0.036, +0.031].
- The quintile means wander by about ±0.2A with no monotone pattern and a per-bucket SE of ~0.1.
- P(+3A) stays in 0.20–0.29 and early failure in 0.35–0.45 in every bucket.

**Named contrast (1h aligned; terciles among 1h-aligned trades):**
- 1h MFE edges: 2.87 / 4.90 A1h. 1h location edges: 0.64 / 0.88.

| cell | n | mean A (SE) | P(+3A) | early fail |
|---|---|---|---|---|
| mature 1h, E at the 1h extreme | 605 | +0.09 (.12) | .235 | .365 |
| mature 1h, E near the 1h start (deep retrace) | 179 | +0.12 (.19) | .246 | .352 |
| young 1h, E at the extreme | 245 | +0.03 (.18) | .278 | .465 |
| young 1h, E near the start | 640 | +0.08 (.10) | .247 | .398 |

The states the question expected to differ ("a +5A mature 1h move at its extreme" versus "near the 1h start after a retracement") are **not distinguishable** in 1m lifecycle terms in 2023.

**Context worth recording:**
- The median 1m flip occurs at 1h location 0.77 in a 1h regime with MFE 3.97 A1h.
- The 1m flips are overwhelmingly generated inside, and near the top of, established HTF moves.

## 5. PRIOR HTF REGIME GEOMETRY
`phase_c_2023_prior_regime_geometry.json`

**Available:** prior-1m and prior-5m regime shape (efficiency, MFE, duration, net move, range), each in the prior regime's own ATR. All 10 have |Spearman| ≤ 0.023 with pnl; quintile tables are in the artifact.

**NOT RECOVERABLE from this frame (platform gap, not synthesized):**
- **Prior 15m and 1h regimes, anything.** There is no prior-context instance at 15m/1h: the feature family is capped at 5s/1m/5m (gap G3), and `regime.excursion` carries only the current regime.
- **Prior-regime price levels at any timeframe.** The prior regime's start, MFE extreme and MAE extreme *prices* and its frozen ATR are not carried. So the ATR distance from E to an inherited prior-1h extreme cannot be computed. Recomputing it from bars would be a bespoke collector, which is prohibited.
- **Gap name: `PRIOR_REGIME_LEVEL_SNAPSHOT`.** It would be a tracker-state snapshot of the prior regime's start_price / extreme prices / frozen_atr per timeframe, exposed as metadata the way the current-regime excursion state is.
- **§5's central hypothesis (inherited prior-1h levels) is therefore UNTESTED.** It is neither supported nor refuted.

## 6. CROSS-TF GEOMETRY (hierarchical)
`phase_c_2023_cross_tf_geometry.json`

- **Named cells, each split into terciles of 1h MFE, 1h location and 5m distance to its favorable extreme:** 45 sub-cells, n 210–739. None separates from its parent by more than ~2 SE.
  - The widest is "1h opposed, 5m+15m aligned" × 1h-MFE mid tercile: −0.52 (SE 0.12, n 211), next to −0.09 and −0.05 in the neighboring terciles. That pattern is not monotone, so it reads as noise.
- **Hierarchy config → 1h maturity tercile → 1h location tercile (N ≥ 150):** 17 of 70 cells are populated and 53 are suppressed. Means run from −0.46 to +0.32 with SEs of 0.10–0.23.
  - That spread is what 17 draws of noise produce, and the extreme cells are not coherent across neighbors.
  - There is no hierarchical interaction to report as a finding.

## 7. PATH ARCHETYPES
`phase_c_2023_path_archetypes.json|parquet`

**Definition method.** Classes use only the collected ladder rungs: MFE rung first, then the order of ±0.5A, then time to −0.5A against the 2023 median (34 s), then capture at 0.5 × rung. They are mutually exclusive. No threshold was chosen for economics.

| archetype | n | share | mean A | median | p5 / p95 | median dur | adverse-first | sum A |
|---|---|---|---|---|---|---|---|---|
| STAGNANT_QUIET (MFE<.5, never −.5) | 7 | 0.1% | — | — | — | — | — | — |
| FAILURE_RAPID (−.5 in ≤ 34 s, MFE<.5) | 933 | 12.5% | −1.76 | −1.64 | −2.99 / −0.98 | 225 s | 1.00 | −1,646 |
| FAILURE_SLOW (−.5 after 34 s, MFE<.5) | 905 | 12.1% | −1.46 | −1.41 | −2.34 / −0.74 | 225 s | 1.00 | −1,317 |
| SHALLOW_FADE (.5 ≤ MFE < 1, fav first) | 794 | 10.6% | −1.28 | −1.19 | −2.40 / −0.44 | 285 s | 0 | −1,014 |
| SHALLOW_RECOVERED (.5 ≤ MFE < 1, adv first) | 441 | 5.9% | −1.32 | −1.21 | −2.43 / −0.52 | 465 s | 1.00 | −580 |
| DEVELOPED_GIVEBACK (1 ≤ MFE < 3, pnl < .5·rung) | 2,485 | 33.2% | −0.51 | −0.47 | −1.83 / +0.70 | 645 s | .35 | −1,267 |
| DEVELOPED_HELD (1 ≤ MFE < 3, pnl ≥ .5·rung) | 118 | 1.6% | +1.30 | +1.25 | +0.74 / +1.97 | 1,425 s | .36 | +154 |
| RUNNER_3_5 | 971 | 13.0% | +1.45 | +1.59 | −0.40 / +3.07 | 1,245 s | .35 | +1,406 |
| RUNNER_5PLUS | 821 | 11.0% | +4.92 | +4.26 | +1.52 / +10.3 | 1,845 s | .35 | +4,036 |

**What the data says about the five hypothesized problems:**
1. **Rapid failure: real as an outcome, not as a separate population.** The log time to −0.5A is unimodal (histogram in the artifact), so rapid versus slow is a split of a continuum. Rapid failures do hit −0.25A in a median 7 s, against 24 s for slow ones, and lose 0.3A more.
2. **Recoverable adverse excursion: real and large.** The adverse-first share is 35% *inside every developed and runner class*: 35% of +5A runners first went to −0.5A. That is the same rate as in DEVELOPED_GIVEBACK, so an early adverse excursion says nothing about the later class.
3. **Slow grind / stagnation: does not exist** as a flip-to-flip lifecycle (0.1%; the LONG_QUIET flag is 0.25%). A lifecycle that neither progresses nor fails is terminated by the next flip or by the next adverse excursion.
4. **MFE then giveback: the modal outcome of the entire population (33%), and mechanical.** The opposite flip needs roughly a 1.5–2A retrace from the extreme, so a +1–3A trade almost never keeps half.
   - DEVELOPED_HELD is 1.6%, and 41% of it exits after 15:15 CT, where post-RTH ranges are small relative to the frozen RTH ATR.
5. **Runner: 24% reach +3A and 11% reach +5A.** They carry all of the positive gross (+5,442A from MFE ≥ +3A).

**Separability at T0.** The best one-vs-rest |AUC − 0.5| of any T0 feature is ≤ 0.061 for every archetype except DEVELOPED_HELD, where `ct_hour` gives AUC 0.70 (the post-15:15 effect above).
- The archetypes are separable only after entry, by definition of their path, and are **not** separable at T0.

## 8. STATE TRANSITIONS AFTER ENTRY
`phase_c_2023_state_transitions.json|parquet`

**State at s** = (T0-anchored MFE rung reached by s, MAE rung reached by s) and the current pnl from E.
**Outcomes:**
- `rem_pnl_A` is the gross from *that checkpoint's* own executable entry to the same flip;
- P(future rung) is conditional on the rung not yet being reached.

| state | s | n (share alive) | remaining mean A (SE) | P(future +3A) | P(future −1A) |
|---|---|---|---|---|---|
| −0.25A within 30 s | 30 | 4,070 (.56) | −0.03 (.04) | .21 | .66 |
| +0.25A within 30 s (reference) | 30 | 3,895 (.54) | +0.02 (.04) | .29 | .47 |
| +1A within 30 s | 30 | 361 (.05) | −0.01 (.18) | .48 | .34 |
| +1A within 60 s | 60 | 922 (.13) | +0.02 (.11) | .45 | .27 |
| +1A within 120 s | 120 | 1,792 (.27) | −0.01 (.07) | .42 | .23 |
| MFE ≥ .75 but back within ±.25 of E | 120 | 354 (.05) | −0.11 (.12) | .22 | .47 |
| MFE ≥ .75 but back within ±.25 of E | 285 | 494 (.10) | −0.06 (.09) | .18 | .35 |
| little progress (MFE < .5 & MAE < .5) | 120 | 398 (.06) | +0.01 (.11) | .19 | .48 |
| MFE ≥ 2A, no adverse | 285 | 476 (.09) | −0.13 (.11) | .54 | .05 |
| MFE 0, MAE ≥ .75 | 120 | 397 (.06) | −0.28 (.08) | .13 | .77 |

- **Of trades reaching +1A within 60 s:** 60% reach +2A, 45% +3A and 23% +5A. But 45% still end ≤ 0 and 72% end below half of their rung.
  - A fast +1A is the single strongest *runner-formation* state observed, and it is also a giveback state.
- **Current-pnl quintiles at s = 120:** P(future +3A) runs 0.11 → 0.48 and P(future −1A) runs 0.86 → 0.15 from worst to best. Remaining mean runs +0.02 / −0.15 / −0.07 / +0.01 / +0.06 (SE ≈ 0.05).
- **Martingale check:** at every s the mean remaining gross is within 0.026A of 0. Only 2 of 72 (s × state) cells with n ≥ 100 have |z| > 2, which is below the 5% chance rate. Spearman(current pnl, remaining pnl) is −0.04 to −0.08.
- **Interpretation.** Post-entry state carries **large information about the shape of the remaining distribution**: how far the barriers are and how likely a runner or a −1A excursion is. It carries **no information about its mean** under the untreated flip exit.
  - Any management value must come from *changing* the path (a stop or target alters the terminal), not from a state with a negative drift that the flip exit merely fails to cut.

## 9. RUNNER FORENSICS
`phase_c_2023_runner_forensics.json`

| population | n | freq | sum A | mean | median | P(pnl ≤ 0) | median s to rung | median dur | adverse −.5 first |
|---|---|---|---|---|---|---|---|---|---|
| MFE ≥ +1A | 4,395 | .588 | +4,329 | +0.99 | +0.25 | .44 | 152 | 945 | .35 |
| MFE ≥ +2A | 2,752 | .368 | +5,564 | +2.02 | +1.39 | .17 | 356 | 1,245 | .35 |
| MFE ≥ +3A | 1,792 | .240 | +5,442 | +3.04 | +2.42 | .05 | 571 | 1,485 | .35 |
| MFE ≥ +4A | 1,220 | .163 | +4,868 | +3.99 | +3.33 | .02 | 770 | 1,725 | .36 |
| MFE ≥ +5A | 821 | .110 | +4,036 | +4.92 | +4.26 | .015 | 935 | 1,845 | .35 |

**Contribution by lifecycle MFE rung (sum A):**

| MFE rung | 0 | .25 | .5 | .75 | 1 | 1.5 | 2 | 3 | 4 | 5+ |
|---|---|---|---|---|---|---|---|---|---|---|
| sum A | −1,774 | −1,191 | −909 | −685 | −855 | −380 | +122 | +574 | +832 | +4,036 |

Trades that never reach +2A (63%) cost −5,794A; trades reaching +5A (11%) return +4,036A.

**Tail concentration** (total −230A):

| best trades | top 10% | top 5% | top 2% | top 1% | top 0.5% |
|---|---|---|---|---|---|
| n | 748 | 374 | 150 | 75 | 37 |
| sum A | +4,022 | +2,698 | +1,486 | +919 | +563 |

Excluding the top 1% the mean is −0.155A; excluding the top 5% it is −0.41A.

**T0 profile of runners versus the population.** It is the same:

| | MFE ≥ +3A | all trades |
|---|---|---|
| median 1h location | 0.762 | 0.767 |
| all-aligned share | 22.3% | 21.2% |
| median 1h MFE | 3.88 A1h | 3.97 A1h |

- The MTF configuration mix and the 5m/15m location are identical within 0.01. The only shift is entry extension: 0.935A versus 0.882A.
- **Preceding adversity:** before reaching +3A, 28% had MAE 0, 22% −0.25, 17% −0.5, 12% −0.75, 14% −1A and 7% ≥ −1.5A.
- **What any management system must preserve:**
  - 35% of runners go adverse first, and 21% go to −1A first.
  - The median +3A takes 571 s and the median +5A takes 935 s.
  - Most runners are not yet visible by the end of the 300 s checkpoint window: P(+3A by 300 s) is .049, against .240 in the full lifecycle.

## 10. RAPID-FAILURE / LEFT-TAIL FORENSICS
`phase_c_2023_failure_forensics.json`

| population | n | freq | mean | median s to rung | MFE before = 0 | P(end > 0) | P(later +2A) |
|---|---|---|---|---|---|---|---|
| MAE ≥ −0.5A | 5,990 | .801 | −0.53 | 54 | 43% | .207 | .225 |
| MAE ≥ −1A | 4,271 | .571 | −1.02 | 138 | 36% | .114 | .133 |
| MAE ≥ −2A | 1,007 | .135 | −2.05 | 226 | 39% | .052 | .067 |
| MAE ≥ −3A | 204 | .027 | −3.07 | 222 | 29% | .064 | .088 |

**Their T0 MTF state and HTF geometry match the population** (all-aligned share, 1h location, 5m location and 1h MFE within 0.02). The exception is entry extension, which rises with depth: median 0.88 → 0.92 → 1.10 → 1.38A.

**Identifiability (target: lifecycle reaches −1A; −2A in parentheses):**

| stage | best signal | AUC | worst current-pnl decile: P(target) | share of all target events | share of future +3A runners |
|---|---|---|---|---|---|
| T0 | entry extension | 0.55 (0.63) | — | — | — |
| s = 15 | MAE so far / 60s giveback | 0.60–0.61 (0.62–0.64) | .79 (.27) | 14% (20%) | 7.0% (7.7%) |
| s = 30 | 60s giveback | 0.66 (0.68) | .84 (.32) | 15% (24%) | 6.2% |
| s = 60 | MAE so far | 0.68 (0.72) | .86 (.36) | 17% (28%) | 4.5% |
| s = 120 | MAE so far | 0.70 (0.76) | .84 (.39) | 20% (34%) | 4.0% |

**Answer to A / B / C.**
- **Not A.** Damaging losers are not identifiable at T0 from geometry. Entry extension gives a scale signal (AUC 0.63 for −2A), but it raises the runner rate as well.
- **Mostly B, with a sting.** They become identifiable at 15–60 s: the 10% worst path at 60 s contains 28% of eventual −2A trades and only 4.5% of eventual +3A runners.
  - By then that decile is already at ≤ −0.53A (s = 60). The **remaining** gross of the worst current-pnl *quintile* at s = 60 is ≈ 0 (−0.07, SE 0.05).
  - The early signal locates trades whose loss is largely sunk. It does not isolate trades with a negative drift from here.
- **Partly C.** Every early-cut rule would sacrifice the ~21% of runners that first go to −1A, and the flagged decile still holds 4–7% of all future +3A runners.

## 11. INFORMATION MAP
`phase_c_2023_information_map.json|parquet`. This is descriptive and is not a feature ranking for a model.

Max association per family:

| family | vs pnl (|Spearman|) | rapid fail (|AUC−.5|) | MAE ≥ 2A | runner ≥ 3A | giveback after +1A |
|---|---|---|---|---|---|
| 1m state/path (entry ext, flip-bar MFE, retained) | .049 | .027 | **.136** | .047 | .021 |
| pullback/velocity (rolling giveback) | .038 | .061 | .038 | .020 | .036 |
| prior 1m geometry | .023 | .007 | .068 | .021 | .020 |
| volatility/range | .024 | .009 | .027 | .019 | .018 |
| context/time (CT hour) | .002 | .004 | .039 | .040 | .009 |
| 5m features / maturity / geometry | ≤ .011 | ≤ .025 | ≤ .042 | ≤ .013 | ≤ .014 |
| 15m maturity / geometry | ≤ .017 | ≤ .014 | ≤ .024 | ≤ .014 | ≤ .016 |
| 1h maturity / geometry | ≤ .021 | ≤ .019 | ≤ .023 | ≤ .008 | ≤ .016 |
| cross-TF alignment | .013 | .014 | .016 | .005 | .009 |
| prior 5m geometry | .014 | .017 | .007 | .005 | .014 |

- **Redundant pairs (|ρ| ≥ 0.8):**
  - entry extension ≈ flip-bar MFE (0.91);
  - retained_1m ≈ −(60s giveback) (0.82);
  - 60s ≈ 300s giveback (0.96);
  - 1h range ≈ 1h displacement (0.83).
- **Stagnation has no target mass** (0.25%) and is not mapped.
- **Caveat:** `rolling_300s_giveback_atr` is null on 76% of T0 rows (warm-up), so its quintile spread (−0.54A) rests on about 1,800 trades.
- **The information that exists is 1m-local:** the flip's own extension, and after entry the path. Every HTF family is at noise level.

## 12. IMPLICATIONS FOR AN ENSEMBLE ARCHITECTURE
**Does the atlas support decomposing management into specialized stages? Yes, but into two stages, not five, and none of them sits at entry.**

| stage | justified? | problem it solves | observable | relevant information | optionality at risk | next target / label |
|---|---|---|---|---|---|---|
| **ENTRY QUALITY (HTF geometry)** | **No** | — | T0 | HTF families at noise (§3–6, §11) | — | none; do not model |
| **LOSS-SCALE / THESIS FAILURE** | **Yes** | Losses are bounded by the flip at 1–3A and scale with entry extension; 57% of trades reach −1A | T0 (scale only) and s = 15–120 (path) | entry_ext_A, MAE so far, 60s giveback, current pnl | 21% of runners go to −1A first; the worst-decile cut at 60 s holds 4.5% of runners; remaining mean ≈ 0, so the payoff is variance and tail, not mean | Conditional distribution of the **remaining** path from s (e.g. P(−X before +Y from the current price)); evaluate any stop as a *treated* path in a separate study |
| **RUNNER DEVELOPMENT / PRESERVATION** | **Yes** | +1–2A trades are flipped out and give back (33% of trades); the +5A tail is 11% and carries all expectancy | from +1A (median 152 s); fast +1A is the strongest runner state | time-to-+1A, MFE so far, 1m path; *not* T0 HTF geometry | Any giveback control that exits a +1–2A trade before the flip truncates the 45% (fast +1A) that go to +3A | P(reach +k A before giving back g A \| MFE so far, time) — a continuation/hazard label on the post-+1A path |
| **GIVEBACK / PROFIT PRESERVATION** | Merged into the runner stage | Giveback is the flip-exit mechanism itself, not a separate population | — | — | — | Same label as runner development |
| **STAGNATION / TIME DECAY** | **No** | The population does not exist in flip-to-flip lifecycles (0.1%) | — | — | — | none |

**The central tension any future model must resolve.**
- The adverse-first path is equally common among eventual runners (35%) and eventual failures.
- The fast-+1A path is simultaneously the best runner state and a 45% give-back-to-zero state.
- A management model is justified *only* as a policy that changes the path, with its own treated-path study and a matched placebo. This atlas cannot evaluate that, because it describes the untreated lifecycle.

## 13. WHAT IS NOT YET KNOWN
- **Prior 15m/1h regime geometry and inherited prior-regime price levels** at any timeframe: gap `PRIOR_REGIME_LEVEL_SNAPSHOT` (§5).
- **Entry-anchored exact MFE/MAE at the checkpoints.** The ladder gives lower bounds on rungs; the 1m excursion columns are flip-bar-open anchored.
- **The flip-bar-close entry (T0 − 15 s).** The frame's first executable entry is 15 s after confirmation, and prior work says delayed entry gives up favorable excursion. The 15 s cost is not measured here.
- **Anything net of costs.** No cost contract was declared.
- **Treated paths** (stops, targets, trails). Only the untreated flip-to-flip lifecycle is described.
- **Year dependence.** Long/short asymmetry and every number above are single-year until 2024 replicates.
- **Analysis harness gaps.** The registered `analysis_ops` cannot express:
  - lifecycle-bounded ladder races;
  - MFE-before-first-adverse on the ladder;
  - checkpoint-panel state transitions against a per-row remaining outcome;
  - top-q tail sums;
  - one-vs-rest AUC maps.

  The atlas is therefore a study-local descriptive reader, not a registered op pipeline (`ANALYSIS_HARNESS_GAP`, recorded in `research_decision.yaml`).

## 14. FROZEN 2024 REPLICATION PLAN
`artifacts/phase_c_2024_replication_contract.yaml`, executed by `analysis/replication_readout.py`.

- **Frozen constants:** RAPID_EDGE 34 s and LONG_QUIET p75 1,065 s. Both are carried, not recomputed.
- **Minimum sample:** ≥ 5,000 resolved 2024 trades, and ≥ 100 per cell.
- **Primary claims** C1–C10 and C12, each with its 2023 value, a PASS band and a PARTIAL band:
  - C1 break-even;
  - C2 ladder asymmetry;
  - **C3 exit-at-MAE** (core);
  - C4 tail dependence;
  - **C5 HTF null** (core);
  - C6 entry-extension scale;
  - **C7 post-entry martingale** (core);
  - C8 identifiability rises after entry;
  - C9 archetype prevalence;
  - C10 archetypes not T0-separable;
  - C12 runner T0 profile equals the population.
- **C11 (secondary, weak):** the 1h-opposed-with-LTF-aligned cell is below the population mean, and all-aligned is above.
- **Verdict:**
  - REPLICATED: every primary claim PASSES.
  - PARTIAL_REPLICATION: ≥ 9 of 11 PASS and no core claim FAILS.
  - Otherwise REPLICATION_FAILED.
- **2023 self-test:** REPLICATED, 11/11 plus C11 (`phase_c_2023_replication_selftest.json`).
- **Order of work:** commit (this change) → `replication_readout.py --year 2024`. The script refuses 2024 unless the contract and both scripts are committed and unmodified.
