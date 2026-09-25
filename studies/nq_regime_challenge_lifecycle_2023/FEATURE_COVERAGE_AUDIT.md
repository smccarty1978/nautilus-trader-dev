# Feature coverage audit: what the chart shows vs what the library represents

## Sources

- **Library inventory:** a read-only `repo-scout` pass over `research_workflow/capabilities/registry.json`,
  `features/trackers/` and `features/definitions/`, with spot checks in this session:
  - `features/trackers/generic_episode_geometry.py` and the canonical `pullback_*` / `prior_deep_pullback_count`
    definitions exist;
  - no live feature exposes the dual-EMA high/low values or the distance to the flip threshold. The tracker keeps
    them internally (`features/trackers/regime_dual_ema.py`), and the collector only uses an EMA midpoint
    (`research_workflow/generic_collector.py:625`).
- **Chart side:** this study's lifecycle reconstruction and the five case charts (`artifacts/cases/*.png`).

Claims the scout could not verify are marked UNVERIFIED.

## A. Already represented well

| concept | library | notes |
|---|---|---|
| Running MFE / MAE / current location | `generic_structural_geometry` (`structural_max_expansion_atr`, `structural_giveback_atr`, `structural_retention_ratio`), `rolling_5m_productivity` | location is the dominant variable, and it is covered |
| A single pullback episode (depth, recovery, efficiency, elapsed) | `generic_episode_geometry` / `generic_pullback` (`pullback_max_depth_atr`, `pullback_current_depth_atr`, `pullback_recovery_from_extreme_atr`, `pullback_efficiency`, `pullback_elapsed_seconds`, `pullback_post_arm_seconds`) | one episode at a time |
| Prior-regime turning levels | `regime_prior_level_snapshot` (start/end/mfe/mae price, displacement), `generic_price_levels` (`distance_to_level` for prior swing / regime entry) | matches this study's `n_turns_*` (which carried nothing) |
| Raw point sizes and volatility | `generic_ohlcv_delta` (`price_change_points`, `range_points`), ATR in points | available; its apparent value here was drift |
| Session / time of day | `generic_context` (`session_elapsed`, `session_membership`) | scout reports a CT-based RTH window; UNVERIFIED against ET here |

## B. Represented but too compressed, or on the wrong timescale

| concept | what exists | what the chart shows | cost of the gap in this study |
|---|---|---|---|
| Challenge / recovery **sequence** | `prior_deep_pullback_count` (a count) | numbered challenges with per-challenge depth, recovery time, recovery-leg size, next-challenge response | built here (`CHALLENGE_EVENTS`): the sequence turned out to be memoryless (topology rows equal within about 3pp) |
| 1m candle morphology | per-1s bar fields, `consecutive_up/down`, `wick_imbalance` over fixed windows | candles of *the impulse* and *the pullback* | built here; at human-scale depth, wicky challenge candles give +5pp race odds, value-neutral |
| Impulse quality | whole-regime `regime_efficiency`, `arrival_velocity` | the leg that made the current extreme | built here; impulse length (bars) carries race information at 2.0A |
| Volume evolution | rolling windows, `volume_trend` | pullback volume vs impulse volume | built here (`ch_vol_ratio`, `vol_resp`): +3–4pp race |
| EMA slope | `ema_slope` of closes, `center_*` | slopes and separation of the EMAs of high and low | built here; small race effects at checkpoints |

## C. Missing

| concept | why it matters | recommendation |
|---|---|---|
| **Distance to the engine's flip threshold** (`close − min(EMA3_low, EMA9_low)`, mirrored for shorts), EMA3/EMA9 high/low, band width, penetration / recapture | the single strongest *location* variable for whether a challenge ends in a flip: P(new extreme) 65% → 91% across its deciles at 0.5A | expose the tracker's `ema_short/long_high/low` and `dist_flip_atr` as features (small, additive) |
| Challenge numbering and per-challenge history inside the regime | needed to ask any repeated-challenge question | promote `challenge.py`'s episode detector (armed / onset / new-extreme reset) as a generic tracker with a `threshold_atr` parameter |
| Level memory *inside* the regime (earlier challenge lows, marginal extremes) | the "tried and failed here" hypothesis | part of the challenge tracker; it carried nothing here, so low priority |
| HTF **changes** since the 1m regime started (flips since start, HTF age) | changing context carried more than static labels (15m flip −0.4 to −0.5A hold, though drift-contaminated) | UNVERIFIED as missing by the scout; confirmed absent from registry field names; add `{tf}_flips_since_parent_start` |
| Event-anchored observation points (first close through EMA3-low, 50% recovery, extreme retest) | the richest race information appeared at the first EMA3 close-through (10–15pp) | the collector observes on clock checkpoints; add event checkpoints |
| Pre-regime context on the chart (the regime starts inside a range vs out of a trend) | visible in the DETERIORATING case (a 30-min range before the flip) | derivable from `REGIME_LEDGER` + 1m; the sequence study found completed-regime context flat |

## Did the richer representation see what the human sees?

**Mostly yes.** The five case charts and their event tables (`artifacts/cases/`) line up: onsets, new extremes and
the final transition sit where a human would mark them.

The representation check (`cases.py`) found that the DETERIORATING regime's transition challenge has a near-twin
among *successful* challenges of CLEAN_TREND regimes. It is closer than 99.97% of all 1.0A challenges (standardised
distance 1.71 over 19 features):
- impulse 1.37 vs 1.32A;
- time since extreme 26 vs 34 s;
- EMA separation 0.80 vs 0.80A;
- band width 1.24 vs 1.10A;
- 15m/1h alignment identical;
- time of day 153 min after the open in both.

On the charts both moments are a flush to a fresh extreme followed by a bounce. **The representation does not merge
visually different situations; the situations genuinely look alike until after the fact.** The limiting factor is
not a missing chart concept.

What the human sees that this study did not encode: order flow / tape, cross-market context (ES, breadth), news
timing. None of these are in the chart being described, and none are in the data.
