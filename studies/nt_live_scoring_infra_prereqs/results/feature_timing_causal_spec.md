# F3 Feature-Timing Causal Contract (authoritative, extracted Phase 3)

This is the single authoritative statement of the causal timing contract
the offline F3 feature-attachment pipeline actually implements, extracted
from the real code (not assumed) across the chain
`entry_surface.py` → `attach_features.py` →
`ohlcv_volume_delta_price_level_features` (registered families
`ohlcv_est_delta`, `price_level_context`). Any future live NT
implementation must match this contract bar-for-bar; any divergence
found later must be reconciled against THIS document, not against
memory or assumption. Extracted via a dedicated read-only research pass;
every claim below carries a file:line citation to the source it was
verified against.

## Core rule (verbatim, `ohlcv_volume_delta_price_level_features/SPEC.md:152-158`)

> "Every emitted feature row must satisfy: `latest_source_ts_used <=
> observation_ts`"

with `observation_ts` defined as "the established-checkpoint decision
time" (`SPEC.md:162-166`) — features describe only what is knowable at
the decision instant, never anything after it.

## 1s-timeframe features (`ohlcv_est_delta` family: bar-level, rolling
windows, cross-window, regime-relative, RTH-cumulative)

- `OHLCVDeltaTracker.update(...)` is called for **every** 1s bar in
  ascending time order, unconditionally, as the main loop advances
  (`attach_features.py:210,215`) — this feeds A1 (bar-level) and A2/A3
  (rolling/cross-window) state.
- `.calculate()` is invoked **once per checkpoint, inline, in the same
  forward pass** — not by feeding all bars first and indexing back into
  history afterward (`attach_features.py:259-260`, confirmed by the
  explicit per-row-ATR comment at `attach_features.py:256-258`). At the
  instant `.calculate()` runs for checkpoint `T`, the tracker has seen
  every 1s bar with `ts_event <= T` and nothing after.
- **Regime-relative state (A4)** resets only on a completed minute's own
  close crossing a precomputed regime boundary:
  `attach_features.py:227-229` (`while ... m_close_ts >=
  regime_starts[reg_idx+1]: reset_regime(regime_starts[reg_idx],
  minute_o)`), using only that minute's own open as the reset anchor —
  no forward-looking information. `reset_regime` itself only zeroes
  internal state (`ohlcv_delta.py:139-148`).
- **RTH-cumulative state (A5)** accumulates only through completed
  minutes, gated by the current RTH-session flag, never using a future
  session boundary to backfill.

## 1m-timeframe features (`price_level_context` family: all level/session/
aggregate/geometry/density/cluster/direction-normalized features)

- Fed exclusively via `price_tracker.update_1m(m_close_ts, minute_o,
  minute_h, minute_l, prev_close, now_rth)` (`attach_features.py:241`),
  called only when the main loop's bar `i` crosses into a **new** minute
  (`attach_features.py:222-246`), using the just-finalized **previous**
  minute's OHLC captured before being overwritten
  (`attach_features.py:245`). The in-progress minute containing `T` is
  never passed to `update_1m` before it closes — confirmed causal.

## Checkpoint declaration and alignment

- Checkpoints are NOT declared from raw 1s bars in `entry_surface.py`
  itself — they arrive already-defined via `load_atlas_stream`
  (`entry_surface.py:28-38`); `entry_surface.py` only filters
  (established/RTH/valid-fill gates, `entry_surface.py:90-145`).
- The actual checkpoint grid originates in
  `regime_sequence_chop_context/build_weakness_atlas.py:73-80`
  (`np.arange(flip_ts + step_s*1e9, timeout_ts+1, step_s*1e9)` — a fixed
  5s-interval theoretical grid from regime start), matched to real data
  via `searchsorted(ts_arr, cp_ts, 'left') - 1` with rejection if the
  found bar's timestamp `>= cp_ts` (`build_weakness_atlas.py:96-99`) —
  i.e. **strictly `<`**, always a closed bar.
- `attach_features.py:141-151` re-snaps `observation_time` to the actual
  1s grid via `searchsorted(ts, obs_times, side="right") - 1` — i.e.
  **`<=`** (an exact-timestamp match counts).

**Known, previously-undocumented discrepancy (flagged by this Phase 3
pass, not previously written down anywhere)**: the atlas builder's
checkpoint-to-bar matching uses strict `<`, while `attach_features.py`'s
own re-snap uses `<=`. Both individually satisfy the core rule
(`latest_source_ts_used <= observation_ts`), so neither is a look-ahead
bug, but they are not the identical rule, and a live NT implementation
must pick one deliberately (recommend `<=`, matching
`attach_features.py`'s own re-snap, since that is the rule that actually
touches the feature values) rather than assume they're interchangeable.

## Warmup / null-availability (actual code, not just the registry's
`null_policy` field)

| Feature group | Gate | Citation |
|---|---|---|
| Rolling windows (A2) | `full_available` requires `ts[0] <= cutoff` for the window; else 18 keys `None`, `window_available_{W}s=False` | `ohlcv_delta.py:210-222` |
| Regime-relative (A4) | `regime_available=False`, all keys `None` if no regime start seen yet | `ohlcv_delta.py:306-307` |
| Regime first/second-half split | Forced `None` unless `len(log)>=4 and elapsed_s>=4` | `ohlcv_delta.py:331-337` |
| RTH-cumulative (A5) | `rth_available=False`, keys `None` outside RTH | `ohlcv_delta.py:368-369` |
| `prior_day_*` levels | `None` until `_on_new_trading_day` populates `prior_day_ohlc` (no value on the very first day) | `price_levels.py:131-133` |
| `overnight_*_final` / `opening_range_30m_*_final` | `None` until RTH open / 30 min elapsed | `price_levels.py:113-114,119-120` |
| Rolling `{5,15,30,60}m` OHLC | Requires a gapless full window (`len(window)==W`, contiguous); else `None` | `price_levels.py:157-165` |
| Generic per-level distance | `available=(price is not None)`; unavailable → distance fields `None`, `_position="UNAVAILABLE"` | `price_levels.py:188-196` |

## Open item not independently verified in this pass

`regime_starts`' own construction (`canonical_regime_timeline` →
`CODEX_5_X_run_established_fade.py:314-345`, `aggregate_and_run_regimes`/
`timeline_from_flips` in `regime_sequence_chop_context/reproduce_regimes.py`)
was NOT traced to the same depth as the feature trackers in this pass —
confirmed at the surface that each regime boundary is a completed
minute's `close_ts` (`CODEX_5_X_run_established_fade.py:323-328`), taken
on the strength of that module's own docstring ("fresh complete causal
flip timeline") and this repo's standing `RegimeEngine`-based NT
precedent (already live-proven in
`nt_pure_flip_trigger_poc_and_mirrored_long_model`), not re-audited from
scratch here. A future live-scoring study should not re-derive this --
reuse `RegimeEngine` directly (as the completed NT POC already does),
rather than reimplementing `timeline_from_flips`.

## F0's 149 features (regime/median-center slope/alignment) — explicitly
out of scope for this contract

F0 is not covered above: Phase 1 (`results/f3_feature_inventory.csv`)
found these trace to
`regime_sequence_chop_context/build_median_centers.py`
(`build_median_centers_df`/`compute_rolling_slopes`), a fully separate,
vectorized-pandas-only computation with no live tracker anywhere. A
future live-scoring study needing F0 must extract and verify ITS causal
contract separately — not assumed covered by this document.
