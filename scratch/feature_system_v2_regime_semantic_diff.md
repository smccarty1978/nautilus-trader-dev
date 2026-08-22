# Regime Geometry 1m vs 5m Semantic Diff

Date: 2026-08-22  
Scope: `StructuralRegimeGeometryTracker` as wired by the CleanFlip collector.

## Shared algorithmic components

| Dimension | Classification | Evidence |
|---|---|---|
| Regime state machine | IDENTICAL_ALGORITHM_DIFFERENT_INPUT_STREAM | Both source engines use EMA3/EMA9 of H/L, Wilder ATR(14), and sticky `close > both high EMAs` / `close < both low EMAs` state transitions. |
| Transition condition | IDENTICAL_ALGORITHM_DIFFERENT_INPUT_STREAM | `RegimeEngine.update` and `RegimeStateEngine.on_bar_closed` implement the same inequalities. |
| ATR | IDENTICAL_ALGORITHM_DIFFERENT_INPUT_STREAM | Both use TR and Wilder period 14; 1m consumes native completed 1m bars and 5m consumes completed aggregated 5m bars. |
| Completed prior metrics | IDENTICAL_ALGORITHM_DIFFERENT_INPUT_STREAM | `_completed` calculates duration, range, net move, MFE, speed, and efficiency for both states. |
| Efficiency | IDENTICAL_ALGORITHM_DIFFERENT_INPUT_STREAM | Both use `abs(net) / range`. |
| Duration | IDENTICAL_ALGORITHM_DIFFERENT_INPUT_STREAM | Both use `(end_ns - start_ns) / 60s`. |

## Substantive, output-affecting differences

| Dimension | Classification | 1m path | 5m path |
|---|---|---|---|
| MFE/range observation stream | GENUINE_SEMANTIC_DIFFERENCE | `CleanFlipCollector._on_1s` calls `StructuralRegimeGeometryTracker.on_1s`; `_one` extrema therefore use every completed 1s bar between 1m flips. | `_on_bucket_closed` calls `on_5m_bar`; `_five` extrema use completed 5m OHLC only. |
| Regime start/reset | PARAMETERIZABLE_DIFFERENCE | `_on_1m` calls `on_1m_flip` only at a 1m transition and anchors from the contemporaneous eligible 1s close. | `on_5m_bar` starts/replaces state when its own completed-5m state direction changes and anchors at the 5m bar open. |
| Availability | GENUINE_SEMANTIC_DIFFERENCE | Prior-1m geometry can change at a 5s checkpoint from newly completed 1s extrema after a prior 1m transition. | Current/prior-5m geometry changes only after a completed 5m bucket, and snapshot refuses forming/missing 5m provenance. |
| Gap/reset/null behavior | GENUINE_SEMANTIC_DIFFERENCE | Expected native 1m gaps hard-fail the collector. | Incomplete five-minute parent buckets call `on_5m_gap`, invalidate `_five`/`_prior_five`, and cause unavailable structural output. |
| Session reset | IDENTICAL_ALGORITHM_DIFFERENT_INPUT_STREAM | Neither tracker state resets solely at session boundary; input gap/session policy is owned by the collector. | Same, but incomplete five-minute aggregation has its own invalidation path. |

## Why `prior_3m_regime_efficiency` is not defined by the current evidence

Both of the following are causal and preserve different legacy precedents, but
they produce different values, availability timestamps, and null behavior:

1. **Direct-3m geometry:** compute a 3m regime from completed 3m bars and update
   extrema from each completed 3m OHLC bar, following the 5m implementation.
2. **3m-transition / 1s geometry:** compute transitions from completed 3m bars but
   update extrema from every completed 1s bar between those transitions, following
   the 1m implementation.

The existing `timeframe=3m` parameter does not choose either observation stream,
anchor policy, or gap policy. Selecting a default would change the formula the
canonical name promises. A valid generalization needs an explicit approved
parameter contract (for example, geometry observation stream and gap policy),
followed by feature-definition promotion and parity tests. No existing study or
registry authority selects a 3m default.
