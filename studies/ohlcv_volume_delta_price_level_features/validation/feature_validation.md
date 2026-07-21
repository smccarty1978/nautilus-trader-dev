# Runtime Validation — 5 Consecutive Trading Days

**Window:** 2025-01-06 through 2025-01-10 (Mon-Fri), NQ, no holidays. Replay
warmup padded 5 calendar days earlier (2025-01-01) so tracker state (prior-
day, overnight, regime-relative, RTH-cumulative) is not cold-started inside
the reported window. Source: `attach_features.py --years 2025 --start
2025-01-06 --end 2025-01-11`, output `sample_features.parquet` (2,248 rows,
matching the existing surface's row count for this window exactly).

## Coverage confirmed

- Overnight session: present (bars before 08:30 CT each day).
- RTH open: present (08:30 CT each day).
- First 30 minutes of RTH: present (`opening_range_30m_is_developing` rows
  observed).
- Opening-range finalization: **3 transitions observed** (2025-01-06,
  01-07, 01-08).
- Rolling 5/15/30/60-minute availability: confirmed available throughout
  (post-warmup).
- Trading-day transitions: **5** (one per day boundary in the padded+reported
  range).

## Run statistics

- Runtime: 12.3s for 2,248 checkpoint snapshots (plus ~5 days of 1s/1m
  replay warmup).
- Row count unchanged: **True** (2,248 in, 2,248 out).
- Labels unchanged: **True**.
- Provenance violations (`latest_source_ts_used > observation_ts`): **0**.
- Gap-snapped checkpoints: **29** — the atlas's `observation_time` is a
  theoretical fixed-5s-interval timestamp that occasionally does not land on
  an actual traded second (a pre-existing raw-feed characteristic, not
  introduced by this study). These 29 rows are snapped to the last actual
  bar at or before `observation_time` (fully compliant with the observation
  contract) rather than silently dropped. Example:
  `observation_time=2025-01-06 20:14:15 UTC` had no raw bar (gap between
  20:14:14 and 20:14:16); `latest_source_ts_used=2025-01-06 20:14:14 UTC`
  was used, `bar_est_delta=-4.0` computed from that bar.
- Unmatched (checkpoint before any raw data existed): **0**.

## Worked examples

### 1. Estimated delta calculation

Row at `2025-01-06 14:46:00 UTC`: `bar_volume=74.0`,
`bar_est_bull_volume=50.45`, `bar_est_bear_volume=23.55`,
`bar_est_delta=26.91`, `bar_est_delta_ratio=0.364`. Consistent with
`estimated_delta = volume * (2*close - high - low) / range` — a close
biased toward the bar's high produces a positive delta close to, but less
than, full volume.

### 2. Rolling delta window update

Same timestamp: `vol_sum_5s=153.0`, `vol_sum_60s=2375.0`,
`vol_sum_1800s=58321.0` — monotonically increasing with window size, as
expected (each wider window is a superset of the narrower one's bars).

### 3. Regime volume/delta reset

Regime transition observed at index boundary
`2025-01-06 15:44:00 UTC` (regime `1736176440000000000`,
`regime_vol_sum=39576.0`, accumulated across that regime's life) →
`2025-01-06 19:48:55 UTC` (new regime `1736192700000000000`,
`regime_vol_sum=2631.0`) — cumulative volume resets to a small value at the
start of the new regime rather than carrying over the prior regime's total.
23 regime transitions observed in the 5-day window.

### 4. RTH cumulative volume reset

Earliest available RTH-cumulative row in the window:
`rth_elapsed_seconds=315.0`, `rth_vol_cum=16438.0`, rising to
`rth_vol_cum=17052.0` at `rth_elapsed_seconds=330.0` ten seconds later —
consistent with genuine accumulation since RTH open (the established-filter
gate means the earliest surface checkpoint each day is somewhat into the
session, not at `elapsed=0`, but the monotonic growth from a small base
confirms the reset-then-accumulate behavior; the reset-to-zero-at-session-
start mechanism itself is unit-tested directly in
`tests/test_ohlcv_delta.py::test_rth_cumulative_reset_on_new_session`).

### 5. Prior-day levels freezing

`prior_day_open_price` is constant across every checkpoint within a given
trading day (verified: exactly 1 unique value per day for 2025-01-06,
01-07, 01-08, 01-10 in this window) — e.g. `2025-01-06 14:37:40 UTC`:
`prior_day_open_price=21186.75`; the LAST checkpoint of a later day
(`2025-01-10 20:59:30 UTC`) shows a different, also-constant-for-that-day
value (`21334.75`), confirming the freeze updates once per day boundary and
does not drift within a day.

### 6. Overnight levels finalizing

The transition itself (developing → final) happens at the first RTH bar of
each day, before the established-regime filter admits any surface
checkpoint that day — so no surface row straddles it directly. Directly
instrumented with a standalone `PriceLevelTracker` (same class, same code
path): feeding overnight bars up to `07:00`/`08:00 CT` gives
`overnight_high_final_available=False`,
`overnight_high_developing_price=102`; feeding the `08:30 CT` RTH-open bar
immediately flips `overnight_high_final_available=True`,
`overnight_high_final_price=102` (frozen at the developing value observed
through 08:00, not contaminated by the 08:30 RTH bar's own higher range).
This exact scenario is covered by
`tests/test_price_levels.py::test_overnight_developing_vs_final`.

### 7. Opening range becoming final

Transition at `2025-01-06 14:56:00 UTC`
(`opening_range_30m_is_final=False`,
`opening_range_30m_high_developing_price=21848.75`) →
`2025-01-06 15:18:25 UTC` (`opening_range_30m_is_final=True`,
`opening_range_30m_high_final_price=21848.75`,
`opening_range_30m_low_final_price=21723.5`) — the final high matches the
last developing value observed before finalization, confirming no
post-finalization bar leaked into the frozen range. A second instance
confirmed at `2025-01-07 14:53:45→16:28:40 UTC`. 3 such transitions total in
the 5-day window.

### 8. Nearest level above/below

Row at `2025-01-06 20:17:40 UTC`: `nearest_level_above_name=rolling_5m_high`
(price `21701.5`, `0.196 ATR` away), `nearest_level_below_name=rolling_5m_close`
(price `21693.5`, `0.501 ATR` away) — both sides populated, distances in
ATR terms, names identify which raw level was selected.

### 9. Clustered level example

Row at `2025-01-06 14:46:00 UTC`: 27 raw levels available, collapsed to 16
clusters (`n_level_clusters_available=16`) — confirming the clustering
step meaningfully reduces duplicate nearby levels. `nearest_cluster_above`
price `21826.75` with strength 5 (5 raw levels merged), `nearest_cluster_below`
price `21814.25` with strength 4, `max_cluster_strength=5`.

## Addendum: raw above/below count semantics confirmed and corrected

A user addendum requested explicit confirmation and tests for the raw
level-count/proximity features (`n_levels_above/below`, `pct_levels_*`,
`level_balance`, nearest-level/cluster features, direction-normalized
ahead/behind). Re-deriving the addendum's own worked example (8 levels,
price above 5 / below 3 → `n_levels_below=5`, `n_levels_above=3`,
`level_balance=0.25`) against the actual code found that
`PriceLevelTracker._aggregate_counts` had `n_levels_above`/`n_levels_below`
**swapped** (and `level_balance`'s sign consequently flipped) relative to
every other level-position helper in the same file
(`_nearest_geometry`, `_density_envelope`, `_cluster_features`,
`_direction_normalized` were all already correct — only the raw
aggregate-count function had the inversion). Fixed in
`features/trackers/price_levels.py`; a dedicated regression test
(`test_raw_above_below_touch_counts_addendum_example`) now pins the exact
addendum example, plus separate tests for percent features, level balance,
clustered above/below counts, nearest-cluster above/below, short-vs-long
direction transformation, unavailable-denominator handling, and
no-zero-fill-for-unavailable (all in `tests/test_price_levels.py`). The
5-day smoke was re-run after the fix: still row-count/label-preserving with
0 provenance violations; spot-checked output now shows internally
consistent values (e.g. `n_levels_available=29, n_levels_above=13,
n_levels_below=16, level_balance=(16-13)/29=0.1034`).

**This means the full 6-year attachment (Part D) had not yet been run with
correct above/below semantics when this was caught** — it was stopped
before completion specifically because of this finding, fixed, and is
being re-run from scratch on the corrected code.

## Post-audit fixes and one refinement of the auditor's own suggestion

An independent lookahead audit (`audit/audit.md`) found **4 CRITICAL, 3
WARNING, 3 NOTE** findings against the code that produced the numbers
above. All were fixed:

- **CRIT-1**: `attach_features.py`'s 1s→1m bucket construction was off by
  one second (a bar whose ts is an exact multiple of 60s was grouped with
  the *following* 59 seconds instead of completing the current minute),
  silently corrupting essentially all of Part B for the historical
  attachment. Fixed; extracted into a testable `minute_bucket_key()`
  function with dedicated regression tests.
- **CRIT-2**: `OHLCVDeltaTracker`'s regime/RTH resets were gated at
  1-minute granularity in `features/engine.py` while fed every 1-second bar
  — the same class of bug as CLAUDE.md's documented MFE/MAE blind spot
  (NT dispatches a whole minute's 1s bars before its parent 1m bar). Fixed
  by buffering each minute's 1s bars in `FeatureEngine` and replaying them
  into the tracker only after the 1m-confirmed regime/RTH transition,
  mirroring the established MFE/MAE buffered-retroactive-replay pattern.
  `attach_features.py`'s own replay was already correct (1-second-
  granularity resets) and needed no change here.
- **CRIT-3**: the 30-minute opening range was 31 minutes wide
  (`elapsed <= 1800s` instead of `< 1800s`). Fixed.
- **CRIT-4**: the 5-day smoke's fixed padding could under-warm
  regime-relative features if a regime's true duration exceeded 5 days.
  Fixed by extending the padding back to the true active regime's start
  when needed (does not affect the full 6-year Part D run, which always
  replays from each year's true start).
- **WARN-2**: ATR was reused across multiple surface rows gap-snapping to
  the same underlying bar. Fixed — computed per-row.
- **WARN-3**: the regime-reset anchor price basis disagreed between the
  offline replay (bar open) and the live engine (bar close). Standardized
  on bar open, matching this project's established "entry_open" convention.
- **NOTE-1/2**: documented the intentional `is_rth` duplication rationale;
  removed dead code in `opening_range_state()`.

**WARN-1 was fixed, then partially reverted after empirical investigation.**
The auditor's literal suggested fix (require `cnt == W`, i.e. an exact bar
count, before marking any rolling window available) was implemented for
both trackers first. Re-running the 5-day smoke on that version showed
`window_available_5s` false for ~5% of rows and `window_available_1800s`
false for ~99% — investigating why found that this raw feed has routine
single-second gaps even during RTH (a genuinely quiet second with zero
prints, e.g. `2025-01-06 14:14:15 UTC` — verified by direct inspection of
the raw file), which is normal market microstructure, not a data-integrity
problem: a volume/delta **sum** is legitimately unaffected by a quiet
second's correct zero contribution. Requiring an exact count would have
made `ohlcv_delta.py`'s rolling-window features nearly unusable for a
reason that isn't actually a correctness issue. Reverted `ohlcv_delta.py`
to the original time-span-only availability check (`ts[0] <= cutoff+1s`)
with this reasoning documented in the code. `price_levels.py`'s rolling
1-minute windows keep the stricter exact-contiguity check, since a genuine
multi-minute gap (e.g. the daily maintenance break) there DOES invalidate
the intended "last W minutes of trading" semantic for an OHLC level in a
way that a quiet second does not for a volume sum.

Post-fix availability on the same 5-day window:
`window_available_5s`/`window_available_1800s`/`rolling_60m_open_available`
all 100% true (2,248/2,248); `opening_range_30m_is_final` 2,005/2,248 true
(the 243 false rows are, correctly, checkpoints within the first 30 minutes
of RTH each day, before the range can finalize).

## Second audit pass found one more CRITICAL (CRIT-5) — cross-pipeline disagreement

A follow-up audit re-verifying the fixes above found a new CRITICAL: CRIT-2's
live-side fix (buffer-and-replay in `features/engine.py`) was correct in
isolation, but it now **disagreed with the unchanged offline replay**
(`attach_features.py`) at every regime/RTH transition. Offline's original
per-1-second regime detection only attributed the *exact boundary second* of
a transitioning minute to the new regime (59/60 seconds of that minute
stayed with the old regime); live now correctly attributed the *whole*
confirming minute. Since the surface's checkpoints start at
`regime_elapsed_seconds==0` (the most common entry point), this was a
material, silent disagreement between the two paths this project's registry
contract requires to be a single source of truth (`regime_vol_sum=10` from
offline vs. `600` from live in the auditor's own reproduction).

Fixed by restructuring `attach_features.py`'s replay loop to resolve
regime/RTH context at **minute-completion granularity**, matching what
`FeatureEngine` can actually know (every `regime_start_ns` is itself some
minute's close timestamp, so a transition can never be confirmed any sooner
than that). The anchor price for both paths is now the confirming minute's
own open, computed identically. A cross-pipeline parity test
(`test_offline_and_live_regime_transition_attribution_match` in
`tests/test_attach_features.py`) feeds the identical synthetic bar sequence
through both paths and asserts `regime_vol_sum` and the anchor price agree
exactly across a live regime transition — it initially failed on a genuine
test-construction bug of its own (an unaligned synthetic timestamp base,
unrelated to the fix), which was found and corrected before the test could
be trusted as a real regression guard.

Re-ran the 5-day smoke after this fix: still row-count/label-preserving,
0 provenance violations (11.5s runtime). 41 tests pass in total.

## Third audit pass: PASS, 0 CRITICAL — two WARNINGs fixed anyway

A third audit pass specifically re-verifying the CRIT-5 fix came back
**PASS, 0 CRITICAL** (2 WARNING, 1 NOTE). Both warnings were confirmed
*dormant* for both the 5-day smoke and the full 6-year production run (do
not affect any already-produced output), so they did not block acceptance
— but both were fixed anyway since they were cheap and well-understood:

- **WARN-4**: the pre-loop initialization (for whatever regime is already
  active at the start of a `--start`/`--end`-windowed replay) used the
  wrong tick as anchor price — the confirming minute's *last* second's
  open (per `minute_bucket_key`'s convention) instead of that minute's own
  *first* bar's open, inconsistent with the main loop's convention. Fixed
  by scanning backward from the located bar to the true start of its
  minute bucket.
- **WARN-5**: the trailing, still-forming minute at the very end of any
  replay window was buffered but never committed to regime/RTH cumulative
  state. Fixed with a post-loop flush. No already-recorded checkpoint is
  retroactively affected by this (any checkpoint inside that trailing
  minute was already computed using the last-finalized state, a bounded
  and causally-valid lag, not a look-ahead issue) — the flush only
  completes the tracker's own final state if it's ever inspected afterward.

**Self-identified, broader, non-blocking limitation (not raised by any
audit pass):** while re-deriving WARN-5 by hand, a related but distinct
pattern became apparent: because regime/RTH-cumulative bars are only
committed once their minute completes, a checkpoint that falls *mid-minute*
within an already-established (non-transitioning) regime sees
`regime_vol_sum`/`rth_vol_cum` reflecting cumulative volume only through
the *previous* completed minute boundary, not through its own exact
timestamp — a bounded lag of up to ~59 seconds on a running total that can
span minutes to hours. This is **not** a look-ahead violation (every bar
used still satisfies `latest_source_ts_used <= observation_ts`; the data is
simply slightly conservative/stale within a bounded window, never using
future information), and does not affect the bar-level/rolling-window (A1-A3)
families, which update unconditionally every second. Closing this fully
would require a "peek without commit" mechanism (temporarily including the
current minute's buffered bars in a snapshot calculation without mutating
persistent state, since regime high/low tracking isn't cleanly reversible)
— judged out of scope for this pass given it is bounded, non-causality-
violating, and confined to two feature families; flagged here explicitly as
a candidate for a future refinement pass rather than left undocumented.

## Not covered by this 5-day window

No trading-day gap/holiday transition (by design — SPEC requires a *normal*
5-day period); that path is exercised separately by the full 6-year
attachment's gap gap-gap-scan-equivalent (row-count/label preservation
checks across all 813,972+198,255+63,021 rows, `results/feature_join_summary.csv`).
