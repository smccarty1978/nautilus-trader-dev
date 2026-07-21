# Look-Ahead & Timestamp Audit

**Date:** 2026-07-19
**Scope:**
- `features/trackers/ohlcv_delta.py` (339 lines, new)
- `features/trackers/price_levels.py` (424 lines, new)
- `studies/ohlcv_volume_delta_price_level_features/attach_features.py` (245 lines, new)
- `features/engine.py` (224 lines, modified)
- `features/registry.py` (436 lines, modified)
- `studies/ohlcv_volume_delta_price_level_features/tests/test_ohlcv_delta.py`, `test_price_levels.py` (read for coverage cross-check)
- `studies/ohlcv_volume_delta_price_level_features/SPEC.md` (read for contract/requirements)
- Cross-referenced (read-only, not in scope for editing): `studies/CODEX_5_X_weakness_atlas_repair/CODEX_5_X_run_established_fade.py` (`is_rth`, `canonical_regime_timeline`), `features/collector.py`, `features/trackers/velocity.py`, `features/trackers/volume.py`, `features/trackers/pullback.py`

**Auditor:** lookahead-auditor v1
**Scope hash (files reviewed, sha256 of path list):** `ohlcv_delta.py+price_levels.py+attach_features.py+engine.py+registry.py @ 2026-07-19`

## Summary

- Critical: 4
- Warning: 3
- Note: 3

**Overall: FAIL — 0 CRITICAL required for acceptance, 4 found.** Do not promote `ohlcv_est_delta`/`price_level_context` features from `status='provisional'` to `'verified'`, and do not treat the current `attached_{year}.parquet` Part-B (price-level) output as reliable, until CRIT-1 and CRIT-3 are fixed and the historical attachment is re-run.

## Critical findings

### [CRIT-1] `attach_features.py:161-174` — 1s→1m bucket construction is off by one second; every synthesized 1-minute bar fed to `PriceLevelTracker` has wrong content

```python
161  minute_key = bar_ts // (60 * NS)
162  if current_minute is None:
163      current_minute = minute_key
164      minute_o, minute_h, minute_l = opens[i], highs[i], lows[i]
165  elif minute_key != current_minute:
166      m_close_ts = int((current_minute + 1) * 60 * NS)
167      price_tracker.update_1m(m_close_ts, minute_o, minute_h, minute_l,
168                              prev_close, is_rth(m_close_ts))
169      current_minute = minute_key
170      minute_o, minute_h, minute_l = opens[i], highs[i], lows[i]
171  else:
172      minute_h = max(minute_h, highs[i])
173      minute_l = min(minute_l, lows[i])
174  prev_close = closes[i]
```

Raw 1s bars are close-labeled, each covering `(ts-1s, ts]` (this is the explicit, tested convention in `ohlcv_delta.py`'s own docstring and rolling-window logic). `bar_ts // 60s` on a close-labeled series buckets bars `{ts=60k, 60k+1, ..., 60k+59}` together — i.e. the bar closing **exactly on** a minute boundary (`ts=60k`, which covers `(60k-1, 60k]`, the true *last* second of clock-minute `[60k-60, 60k)`) gets grouped with the *following* 59 seconds, not the preceding ones.

Concretely, for true clock-minute `[0s, 60s)`: the bars that should compose it are those closing in `(0, 60]`, i.e. `ts = 1, 2, ..., 60`. But this loop's bucket 0 actually accumulates `ts = 0, 1, ..., 59` — it is **missing the bar at `ts=60`** (the true final second of that minute) and instead **includes the bar at `ts=0`**, which really belongs to the *previous* minute.

Effect on the finalized bar reported to `price_tracker.update_1m()`:
- `minute_h`/`minute_l` are computed from only 59 of the 60 true constituent seconds (missing the true last second) — high/low can be understated if that missing second set a new extreme.
- The close passed (`prev_close`) is the close of the second **before** the true minute-close, not the true minute's own close.
- The bar that *should* belong to this minute (the one whose `ts` triggers the `elif` branch) is instead used to seed `minute_o` for the **next** bucket — i.e. `rth_open`, `rolling_Xm_open`, and every subsequent-day's opening bar can be sourced from a second that actually belongs to the prior minute.
- `m_close_ts` itself (the label, `(current_minute+1)*60s`) is numerically the correct clock boundary, so `is_rth(m_close_ts)`/`trading_day_key` classification is *not* mislabeled — only the OHLC **content** is wrong. This makes the bug silent: provenance fields look fine, the underlying values are quietly off.

This corrupts `prior_day_open/high/low/close`, `overnight_high/low_developing/final`, `rth_open`, `opening_range_30m_*`, and `rolling_5/15/30/60m_*` — i.e. essentially all of Part B — for every single synthesized minute in the historical attachment. It is **not exercised by the existing unit tests**: `tests/test_price_levels.py` calls `PriceLevelTracker.update_1m()` directly with hand-built, already-correct 1-minute OHLC (bypassing this exact aggregation code entirely), so the test suite currently gives zero coverage of this bug.

**Not a look-ahead leak** (no future data is used — the label timestamp is still correct and causal), but it is a systematic, deterministic, silent data-integrity defect matching "Critical findings corrupt results silently" in the operating principles.

**Recommended fix (do not apply):** bucket 1s bars by `(bar_ts - 1) // (60*NS)` (equivalently, treat the bucket as closed on `(bucket*60, bucket*60+60]`) so the bar whose `ts` is an exact multiple of 60 is recognized as completing the *current* bucket, not starting the next one. Add a unit test that feeds `attach_features.py`'s own bucket-construction function (not just `PriceLevelTracker.update_1m` directly) across an exact minute boundary and asserts the resulting 1-minute OHLC matches a hand-computed reference.

### [CRIT-2] `features/engine.py:64-120` — OHLCVDeltaTracker regime/RTH resets are gated at 1-minute granularity while `update()` is fed every 1-second bar; NT's documented 1s-before-1m dispatch order causes a full transitioning minute to be misattributed

```python
64   def update_1s(self, bar) -> None:
...
74       self._ohlcv_delta_tracker.update(int(bar.ts_init), open_px, high_px, low_px, close_px, volume_val)
...
84   def update_1m(self, bar, regime) -> None:
86       if regime.regime_id != self.last_regime_id:
...
92           self._ohlcv_delta_tracker.reset_regime(int(bar.ts_init), float(bar.close))
...
111      is_rth_now = _is_rth(int(bar.ts_init))
112      if is_rth_now and not self._was_rth:
113          self._ohlcv_delta_tracker.reset_rth(int(bar.ts_init))
114      elif not is_rth_now and self._was_rth:
115          self._ohlcv_delta_tracker.end_rth()
```

`OHLCVDeltaTracker.update()` (A1-A5 accumulation) is driven exclusively from `update_1s()`, called once per completed 1-second bar. The regime-change/RTH-transition detection that resets that same tracker's cumulative state is driven exclusively from `update_1m()`, called once per completed 1-minute bar. Per this repo's own documented event order (CLAUDE.md invariant 4, "MFE/MAE Blind Spot": *"1s bars process before their parent 1m bar in NT... you MUST buffer recent 1s bars and replay them retroactively"*), **all 60 of a transitioning minute's 1-second `update_1s()` calls happen before the corresponding `update_1m()` call that would reset the tracker.** Consequences:

- **Regime transition:** every 1-second bar in the minute where a regime flip is confirmed gets accumulated into the *old* regime's `regime_vol_sum`/`regime_est_delta_sum`/`regime_high`/`regime_low` before `reset_regime()` finally fires at that minute's `update_1m()` — the new regime silently starts one minute "late" relative to what its own `regime_start_ns`/`bar.ts_init` implies.
- **RTH transition:** at RTH open, the tracker's `_rth_active` flag is still `False` throughout all 60 `update_1s()` calls of the RTH-open minute (it only flips inside `update_1m()`, after those calls already ran) — the entire first minute of RTH volume/delta is silently **dropped from `rth_vol_cum`/`rth_est_delta_cum`**, never counted anywhere.

This is exactly the class of bug CLAUDE.md's own invariant #4 exists to prevent, applied here to `OHLCVDeltaTracker`'s regime/RTH state rather than MFE/MAE — but no buffering/retroactive-replay was implemented for it. It also constitutes a **train/serve skew (D1)**: `attach_features.py`'s own replay (a 1-second-granularity loop, see lines 148-157) resets `OHLCVDeltaTracker` at the correct 1-second boundary and does **not** have this bug — so the historical Part-D attachment and any future live/`FeatureCollector`-driven computation of the same nominal features will disagree systematically at every regime/RTH transition. `features/collector.py`'s `FeatureCollector` is a thin pass-through wrapper with the identical calling contract ("call `update_1s` on each 1s bar... call `update_1m` ... AFTER regime.update()"), so any other study that uses the "single source of truth" `FeatureEngine`/`FeatureCollector` path for offline historical feature generation (the design intent stated in `FEATURE_REGISTRY_CONTRACT.md`, per SPEC's scout note #1) inherits this bug too — it is not confined to future live trading.

**Recommended fix (do not apply):** buffer the current minute's 1-second bars in `FeatureEngine` and, on `update_1m()`, detect the regime/RTH transition *before* replaying that minute's buffered 1-second bars into the (freshly reset) tracker — mirroring the existing MFE/MAE 1s-buffer-and-retroactive-replay pattern already mandated by CLAUDE.md invariant #4.

### [CRIT-3] `features/trackers/price_levels.py:115-120` — 30-minute opening range is off by one bar (31 minutes wide, not 30)

```python
115  elapsed = (ts_event - self._rth_open_ts) / NS
116  if elapsed <= OPENING_RANGE_SECONDS:
117      self._opening_range_high = high if self._opening_range_high is None else max(self._opening_range_high, high)
118      self._opening_range_low = low if self._opening_range_low is None else min(self._opening_range_low, low)
119  elif self._opening_range_final is None and self._opening_range_high is not None:
120      self._opening_range_final = {"high": self._opening_range_high, "low": self._opening_range_low}
```

`_rth_open_ts` is the **close** timestamp of the first RTH 1-minute bar (i.e. that bar already represents one full minute of the session). `elapsed` for the RTH-open bar itself is `0`; for the bar closing 30 minutes later it is `1800`. Using `elapsed <= 1800` (rather than `< 1800`, equivalently `<= 1740`) includes **31** one-minute bars (`elapsed = 0, 60, ..., 1800`) in the developing/final range instead of 30 — the bar covering minutes 30-31 of the session leaks into what should be a strictly-30-minute opening range. This is the same *class* of close-time-labeling boundary bug as the rolling-window off-by-one you already found and fixed in `ohlcv_delta.py` (a `+1 bar-width` correction is needed, but here it needs to be subtracted, not added, because this window accumulates forward from a start anchor rather than backward from an end anchor).

Not caught by `tests/test_price_levels.py::test_opening_range_leak_prevention` — that test only checks bars at `8:30`, `8:45`, and `9:01` (elapsed 0, 900, 1860s), never the exact `elapsed=1800` boundary bar, so it cannot detect this off-by-one.

Impact: `opening_range_30m_high/low_final` (and `_developing`) are silently ~3% too wide on every single trading day, for the entire historical attachment and any future live use. `opening_range_30m_is_final` also flips true one bar later than the 30-minute mark actually completes.

**Recommended fix (do not apply):** change `elapsed <= OPENING_RANGE_SECONDS` to `elapsed < OPENING_RANGE_SECONDS`; add a test asserting the exact bar at `elapsed=1800` is excluded from `developing` and triggers `is_final`.

### [CRIT-4] `studies/ohlcv_volume_delta_price_level_features/attach_features.py:70-92, 148-150` — 5-day validation-smoke padding does not guarantee correct regime-relative (A4) warmup if a regime's true duration exceeds 5 days

```python
70   # Regime timeline must be built from the FULL raw year (regime detection
...
76   timeline = canonical_regime_timeline(year, raw)
77   regime_starts = timeline["regime_start_ns"].to_numpy(np.int64)
...
89   replay_start = (pd.Timestamp(start, tz="UTC") - pd.Timedelta(days=5)
...
148  while reg_idx + 1 < len(regime_starts) and bar_ts >= regime_starts[reg_idx + 1]:
149      reg_idx += 1
150      ohlcv_tracker.reset_regime(int(regime_starts[reg_idx]), float(opens[i]))
```

`regime_starts` is derived from the *full year* (correct), so `regime_elapsed_seconds` (`= (obs_ts - self._regime_start_ts)/NS`, using the true historical `regime_start_ts`) will be correct even when the replay window is truncated. But `reset_regime()`'s **other** side effects — `_regime_vol_sum`, `_regime_delta_sum`, `_regime_high`/`_regime_low`, `_regime_bar_log` (used for the first-half/second-half split), and the **anchor price** (`opens[i]`, taken from whatever bar happens to be at the truncated replay's own starting index, not the true historical regime-start bar) — only begin accumulating from `replay_start` (5 days before the smoke window's `--start`). If the regime that is *actually active* at `--start` began **more than 5 days earlier** (plausible given this project's own memory notes that regime durations are highly variable and can span many days), every regime-relative feature except `regime_elapsed_seconds` will be silently computed from a truncated, wrong starting point — while `regime_elapsed_seconds` itself will still report the full (correct, long) duration. That inconsistent combination (correct elapsed time, wrong everything-else) is not detected or flagged anywhere in the code (no comparison against the true regime start, no warning emitted).

This affects **only** the `--start`/`--end` (5-day runtime-validation smoke) path — the full 6-year Part D production run (no `--start`/`--end`) replays from the true start of each year's raw file and is not affected. But since the SPEC's own "Runtime validation" section is exactly where worked examples for "regime reset" are meant to be produced and checked (`validation/feature_validation.md`), this risks the validation artifact itself being silently wrong for any checkpoint whose regime predates the 5-day pad — undermining the audit trail the SPEC relies on to certify correctness before promoting these features out of `provisional`.

**Recommended fix (do not apply):** either (a) extend `replay_start` back to the true start of the regime active at the surface's own `--start` filter (look up `regime_starts` directly rather than using a fixed 5-day heuristic), or (b) explicitly detect and flag/skip any checkpoint whose active regime's true start precedes `replay_start`, so the smoke validation cannot silently certify wrong numbers.

## Warnings

### [WARN-1] `features/trackers/ohlcv_delta.py:163-182` and `features/trackers/price_levels.py:151-164` — window/rolling "available" checks assume gapless bars; a genuine 1s/1m data gap can silently produce an incomplete window marked as complete

`ohlcv_delta.py`'s `full_available = bool(ts[0] <= cutoff + NS)` only checks the *oldest buffered bar's* timestamp, not that every intervening second is actually present; if the underlying 1s feed has a gap inside the window (this project's own memory explicitly flags "Missing bars (gaps in 1m data during low-liquidity overnight)" as a real, recurring characteristic — see `validate_raw_bars()` in `CODEX_5_X_run_established_fade.py`, which checks OHLC geometry and monotonic/unique index but does **not** enforce 1-second contiguity), the window will be marked `window_available_<W>s = True` while actually covering fewer than `W` seconds of history, with no distinguishing signal. `price_levels.py`'s `rolling_<W>m_*` levels have the analogous issue: availability is gated on **bar count** (`n >= W`), not on verified elapsed calendar time, so a gap makes a "rolling 30-minute" window silently span more than 30 real minutes.

**Recommended fix (do not apply):** additionally assert `cnt == W` (ohlcv_delta) / check that the oldest window member's timestamp is within `W` minutes of the newest (price_levels) before marking a window available; if not, mark unavailable rather than silently accepting a gapped window.

### [WARN-2] `attach_features.py:176-188` — ATR-normalized OHLCV features are computed once per raw bar and reused across all surface rows that gap-snap to the same bar, using only the first row's ATR

```python
176  hits = obs_lookup.get(bar_ts)
177  if hits:
178      f_ohlcv = ohlcv_tracker.calculate(atr=hits[0][2])
179      for regime_start_ns, obs_time, atr in hits:
180          f_price = price_tracker.calculate(bar_ts, closes[i], atr, direction=-1)
...
186          rec.update(f_ohlcv)
187          rec.update(f_price)
```

When multiple surface rows' `observation_time`s gap-snap to the identical underlying raw bar (a real, reported occurrence — see `gap_snapped_checkpoints` in the manifest), `f_ohlcv` is computed **once**, using only `hits[0][2]` (the first row's `atr_at_entry`), and that single result is applied to every row sharing that `bar_ts` — even though each row's own `atr_at_entry` can differ. `price_price`/`f_price` correctly uses each row's own `atr` (inside the loop), so only the OHLCV-tracker's ATR-normalized fields (`price_change_atr_<W>`, `range_atr_<W>`, `volume_per_atr_moved_<W>`, `regime_price_change_atr`, `regime_range_atr`, `regime_volume_per_atr_moved`, `regime_abs_delta_per_atr_moved`, etc.) are affected. Not a look-ahead leak (the ATR used is still a causally-valid value, just from the wrong row), but a correctness/cross-row-contamination bug.

**Recommended fix (do not apply):** compute `f_ohlcv` per-row inside the `for` loop using that row's own `atr`, not `hits[0][2]`.

### [WARN-3] `attach_features.py:150` vs `features/engine.py:92` — regime-reset anchor price basis differs between offline replay and live wiring (train/serve skew, D1)

Offline: `ohlcv_tracker.reset_regime(int(regime_starts[reg_idx]), float(opens[i]))` — anchor price = the triggering **1-second** bar's **open**.
Live: `self._ohlcv_delta_tracker.reset_regime(int(bar.ts_init), float(bar.close))` — anchor price = the triggering **1-minute** bar's **close**.

Both use the correct/consistent transition *timestamp* (confirmed aligned), but the anchor **price** basis differs, which feeds directly into `regime_price_change_atr`, `regime_volume_per_atr_moved`, and `regime_abs_delta_per_atr_moved`. Magnitude is typically small (last-second-open vs. minute-close are usually close), but it is a genuine, unremediated definitional mismatch between the two paths meant to be "the same" per the registry contract's single-source-of-truth intent.

**Recommended fix (do not apply):** pick one canonical anchor-price definition (e.g. always the transitioning 1-minute bar's close) and use it in both call sites.

## Notes

### [NOTE-1] `features/engine.py:17-19` — `_is_rth()` duplicates rather than reuses the canonical `is_rth()`

`engine.py` defines its own local `_is_rth(ts_init_ns)` (hour/minute check, `8:30 <= t < 15:00` CT) instead of importing `CODEX_5_X_run_established_fade.is_rth()` (used by `attach_features.py`, `146-149` of that file: `8*60+30 <= minute < 15*60`). The two are currently **numerically identical** given the same input timestamp, so there is no current train/serve skew from this — but it is a duplicate implementation of exactly the boundary logic the SPEC's own guardrails say must not be duplicated ("No parallel session/timestamp/RTH logic — reuse the existing fill-time-remediated `is_rth()`"), and the two copies can silently diverge in the future if either is edited independently.

### [NOTE-2] `features/trackers/price_levels.py:166-174` — `opening_range_state()` contains dead/vestigial code

```python
166  def opening_range_state(self) -> Dict[str, object]:
167      elapsed = None
168      if self._rth_open_ts is not None:
169          # caller supplies "now" via calculate(); exposed separately for clarity
170          pass
```

The `elapsed`/`if` block computes nothing and is unused (the method only returns the two `is_developing`/`is_final` flags). Harmless, but confusing to a future reader auditing this exact class of boundary logic.

### [NOTE-3] `attach_features.py:184-185` — `latest_1m_bar_close_ts_used` provenance field is wrong for the very first bar of any replay window

```python
184  "latest_1m_bar_close_ts_used": (int((current_minute) * 60 * NS)
185                                  if current_minute is not None else None)
```

At loop index `i=0`, the `if current_minute is None` branch (line 162-164) sets `current_minute` to the *first, still-forming* minute's bucket **without** any `price_tracker.update_1m()` call having happened yet — so this field would report a nonzero close-timestamp for a 1-minute bar that was never actually finalized/passed to the tracker. Given the 5-day warmup padding on both the smoke-validation and full-year runs, no real surface checkpoint's `observation_time` should ever land in the very first raw bar of the replay window, so this is not expected to manifest in practice — but it is a latent provenance-field bug that a future reader could use to (falsely) certify causality if the replay window were ever shortened.

## Clean checks

- Label leakage (#4 in the request): `net_pnl`, `exit_reason`, `mfe_atr`, `mae_atr`, `hit_pre_alignment_stop`, `label_available` are not read as inputs anywhere in `ohlcv_delta.py`, `price_levels.py`, or the feature-computation path of `attach_features.py`; the only reference (`attach_features.py:100`) is in the row/label-preservation *check*, correctly guarding against, not using, those columns.
- `_coerce()` change in `engine.py` (#5): confirmed the pre-existing ~55 registered features (`velocity.py`, `volume.py`, `pullback.py`, and `_get_context_features`) never return `None` or `bool` — every one is already an explicit `float(...)`. `_coerce(val)` therefore reduces to `float(val)` for all of them, identical to the presumed prior blind cast; only the *new* string-enum (`<level>_position`, `nearest_level_*_name`) and `None`-unavailable features are affected by the new branch.
- `attach_features.py` gap-snap logic (`np.searchsorted(ts, obs_times, side="right") - 1`): verified causal — always resolves to the last actual raw bar with `ts <= observation_time`, never a bar after it.
- `PriceLevelTracker._on_new_trading_day` / `prior_day_ohlc` freeze: only computed from the just-completed day's own accumulated bars at the moment the *next* day's first bar arrives; never updated from the day it's reported for.
- `overnight_final` freeze: computed from `_overnight_high/low` as of immediately before the first RTH bar is processed; does not include that first RTH bar's own high/low.
- `trading_day_key()` (17:00 CT rollover) is the only session/day-boundary implementation in this study and is applied consistently (only place that computes trading-day identity).
- Direction normalization (B7): hardcoded `direction=-1` at both call sites (`engine.py` receives it from caller context; `attach_features.py:180` fixed at `-1`), matching the SPEC's stated fixed-short surface — never inferred from outcome.
- Cluster determinism (B6): sort key `(price, name)` gives a fully deterministic, stable tie-break; no randomness or learned weights.
- No pandas `.rolling(center=True)`, `.shift(-N)`, or `.bfill()` anywhere in the two new tracker files — both are pure `deque`/list-based causal accumulators.
- Row-count/label preservation harness in `attach_features.py` (`merge(..., how="left", validate="one_to_one")`, pre/post row-count comparison, pre/post label-column hash comparison) is present and structurally sound for catching accidental row duplication or label mutation.
- No microstructure/order-book/bid-ask fields referenced anywhere; strictly OHLCV-derived, consistent with the SPEC's guardrail.
- `OHLCVDeltaTracker.update()`/`PriceLevelTracker.update_1m()` themselves have no internal code path that could accept a "forming" bar — both are pure accumulate-on-call, so correctness of "completed bars only" depends entirely on the caller (verified causal in `attach_features.py`'s replay loop for regime/RTH boundaries beyond the granularity issue in CRIT-2, which is a caller/wiring defect in `engine.py`, not in the tracker classes).

---

*Audit complete. Findings reflect read-only static analysis of the five files listed in Scope, cross-referenced against their direct imports. Dynamic/runtime behavior (actual gap frequency in the raw 1s files, actual regime-duration distribution, live NT event-ordering under real load) was not executed and is out of scope; where an assumption materially drives severity (CRIT-4's dependence on regime duration, WARN-1's dependence on gap frequency), that dependency is stated explicitly in the finding.*

---

# RE-AUDIT — Fix Verification Pass (2026-07-19)

**Scope:** same five files, re-read in full at their current state, plus new/changed test files
(`studies/ohlcv_volume_delta_price_level_features/tests/test_attach_features.py`,
`tests/test_feature_library.py::test_ohlcv_delta_regime_transition_buffers_and_replays_correctly`),
plus `studies/regime_sequence_chop_context/reproduce_regimes.py` (read-only, upstream regime-timeline
builder, consulted to resolve exact `regime_start_ns` boundary semantics) and
`studies/ohlcv_volume_delta_price_level_features/validation/feature_validation.md` (claims cross-checked
against code, not taken at face value). Full test suite executed
(`python -m pytest tests/test_feature_library.py studies/ohlcv_volume_delta_price_level_features/tests/ -q`
→ **40 passed**). Gap statistics in the raw feed independently verified by direct inspection of
`data/raw/NQ_v0_1s_2025.parquet` (12,083,801 rows; 1,366,165 single-second gaps ≈ 11.3% of all
consecutive-bar intervals; 532 gaps ≥ 60s; max gap ≈ 73 hours).

## Summary (re-audit)

- Critical: **1** (newly found; all 4 originally-reported CRITICALs verified fixed on their own narrow terms)
- Warning: **1** (WARN-3 not fully resolved as claimed)
- Note: **2** (new)

**Overall: FAIL — 0 CRITICAL required for acceptance, 1 found (CRIT-5).** CRIT-1, CRIT-3, and CRIT-4 are
confirmed correctly fixed and may be considered closed. CRIT-2's live-side fix is itself correct and
well-tested in isolation, but re-deriving its interaction with `attach_features.py`'s (unchanged) offline
replay at 1-second granularity surfaces a new, unaddressed offline/live disagreement at every regime and
RTH transition (CRIT-5). `validation/feature_validation.md`'s claim that "`attach_features.py`'s own replay
was already correct... and needed no change" is not supported by the evidence below — it was never actually
cross-checked against the fixed live engine at the transition boundary.

## Fix verification detail

### CRIT-1 — VERIFIED FIXED

`minute_bucket_key(bar_ts) = (bar_ts - 1) // (60*NS)` (`attach_features.py:58-66`) is correct: for a
close-labeled bar covering `(bar_ts-1s, bar_ts]`, this maps `ts ∈ {60k+1, ..., 60k+60}` to bucket `k`, so the
bar at the exact minute boundary (`ts=60k+60`) correctly completes bucket `k` rather than starting bucket
`k+1`. Confirmed algebraically and by direct execution of the two new tests in
`tests/test_attach_features.py` (`test_minute_bucket_key_exact_boundary_bar_completes_current_minute`,
`test_minute_bucket_key_hand_computed_ohlc_reference`) — both pass, and both would fail against the
pre-fix `bar_ts // (60*NS)` formula (verified by substitution). The function is actually called from the
replay loop (`attach_features.py:197`), not merely defined and unused. Part B (price-level) content is now
built from the correct 60 constituent 1s bars per minute.

### CRIT-2 — Live-side fix VERIFIED CORRECT in isolation; see CRIT-5 for a new residual issue it exposes

`OHLCVDeltaTracker.update()` (`ohlcv_delta.py:88-120`) now only appends to the rolling-window deques;
regime/RTH accumulation is split into a separate `accumulate_regime_rth()` (`ohlcv_delta.py:122-137`).
`FeatureEngine.update_1s()` (`engine.py:83-104`) buffers each 1s bar's `(ts, high, low, volume, est_delta)`
into `self._minute_1s_buffer` instead of accumulating immediately. `FeatureEngine.update_1m()`
(`engine.py:109-158`) performs the regime-id-change reset (`engine.py:111-123`) and RTH-transition reset
(`engine.py:142-147`) **before** replaying the buffered minute's bars via `accumulate_regime_rth()`
(`engine.py:149-154`), and clears the buffer immediately after (`engine.py:154`). This ordering is correct —
replay strictly follows both reset decisions, not before.

`tests/test_feature_library.py::test_ohlcv_delta_regime_transition_buffers_and_replays_correctly` does
exercise the transitioning-minute scenario (feeds a full minute of 1s bars under the old regime's buffer,
then calls `update_1m()` with a changed `regime_id`, asserting the new regime's `_regime_vol_sum` reflects
the full just-fed minute, not zero and not the old regime's carried-over total). Traced by hand against the
pre-fix code (inline accumulation in `update()`): the pre-fix tracker would have accumulated the transitioning
minute's 60 bars into the *old* regime's sum before `reset_regime()` wiped it, yielding `regime_vol_sum=0.0`
for the new regime immediately after the reset — this test's assertion of `1500.0` would have failed. Confirmed
a valid, non-tautological regression test.

`attach_features.py`'s replay loop calls `ohlcv_tracker.update(...)` then immediately
`ohlcv_tracker.accumulate_regime_rth(...)` for the same bar in the same iteration (`attach_features.py:194-195`),
after the `reg_idx`/`was_rth` bookkeeping for that same bar has already run (`attach_features.py:177-186`) — no
double-counting or dropped bars for the offline path considered in isolation. **However**, see CRIT-5: this
loop's per-1-second-granularity regime/RTH bookkeeping produces a *different* transition-minute attribution
than the now-corrected `FeatureEngine`, not merely "the same, just already correct" as the codebase's own
validation doc asserts.

### CRIT-3 — VERIFIED FIXED

`price_levels.py:116`: `if elapsed < OPENING_RANGE_SECONDS:` (was `<=`). Independently re-derived by feeding a
synthetic 31-bar sequence (one bar per minute, RTH open at 8:30 through 9:00 inclusive) through the live
`PriceLevelTracker` class: the developing/final high stops accruing at the minute-29 bar (`elapsed=1740`,
`high=129.5`), and the minute-30 bar (`elapsed=1800`, `high=130.5`) is excluded — `opening_range_30m_is_final`
flips `True` at exactly that bar without absorbing its own range. Confirms an exact 30-bar (not 29, not 31)
range. No change needed.

### CRIT-4 — Logic VERIFIED CORRECT; test-coverage claim not accurate (NOTE, see below)

`attach_features.py:100-117`: `regime_starts` is built from the full-year `raw` frame before any
`--start`/`--end` truncation (confirmed: the truncation branch begins at line 92, strictly after the
`canonical_regime_timeline` call at line 87), so it always reflects the true, complete regime history for
that single year — no cross-year contamination is possible since `year` is fixed per `run_year()` call and
`regime_starts` is derived solely from that year's own raw file. `prior_regime_starts =
regime_starts[regime_starts <= start_ns]`; `true_active_start = max(prior_regime_starts)` correctly identifies
the most recent (direction-agnostic, correctly so) regime start at or before the smoke window's `--start`;
`replay_start = min(padded_start, true_active_start)` can only extend the warmup earlier, never truncate it —
safe in the look-ahead direction regardless of outcome. The empty-`prior_regime_starts` edge case (no regime
confirmed yet before `--start`, e.g. very early in a year) correctly falls back to the fixed 5-day pad, which
is consistent with `regime_available=False` being reported for that period rather than a wrong value.

**Note:** despite `tests/test_attach_features.py`'s own module docstring claiming "Covers CRIT-1... and CRIT-4
(regime-relative warmup for the validation-smoke padding)," the file contains **only** the two
`minute_bucket_key` tests — no test exercises the `replay_start`/`prior_regime_starts` logic at all. The fix
was verified here by independent code tracing, not by an actual regression test. See NOTE-4 below.

### WARN-2 — VERIFIED FIXED

`attach_features.py:213-220`: `f_ohlcv = ohlcv_tracker.calculate(atr=atr)` is now computed inside the
`for regime_start_ns, obs_time, atr in hits:` loop, using each row's own `atr`, matching `f_price`'s existing
per-row pattern. Confirmed by direct reading — no remaining hoisted, shared-ATR computation.

### WARN-3 — PARTIALLY FIXED, not fully reconciled (remains open, downgraded in nature)

`engine.py:117-123`'s comment and code now use `float(bar.open)` (was `float(bar.close)`), matching
`attach_features.py:179`'s convention of using an "open" price rather than a "close" price. However, tracing
the *specific* bar each side uses shows they are still not the same value:

- Offline (`attach_features.py:177-179`): the `while` loop increments `reg_idx` and calls `reset_regime(...,
  float(opens[i]))` at the **first 1-second bar** whose `bar_ts >= regime_starts[reg_idx+1]` — since
  `regime_starts` values are exact 60s-multiples (see CRIT-5), this is the 1-second bar covering
  `(boundary-1s, boundary]`, i.e. the **last second of the transitioning minute**. `opens[i]` is that
  bar's own open (a price near the *end* of the transitioning minute).
- Live (`engine.py:123`): `float(bar.open)` is the 1-minute bar's own open — a price at the *start* of the
  transitioning minute.

These are two different ticks. Verified numerically with a synthetic drifting-price minute (open at first
second = 100.00, open at last second = 100.59): the two conventions differ by the full magnitude of
intra-minute drift, not a rounding-level difference. The fix reduced the *class* of mismatch (both sides now
use "an open," not open-vs-close) but did not make the two paths use the *same* open. This still feeds
`regime_price_change_atr`, `regime_volume_per_atr_moved`, and `regime_abs_delta_per_atr_moved` differently
between offline and live. Magnitude is typically small relative to ATR-scaled features but is not zero and is
not addressed by the fix as implemented, despite the docstring/manifest describing it as reconciled.

**Recommended fix (do not apply):** pick one bar unambiguously (e.g. always the 1-minute bar's own open, by
having the offline loop use the finalized minute-bar's open captured at bucket-finalization time, not
whichever 1s bar happens to trigger the regime-index crossing) and use it in both call sites.

### WARN-1 — independent opinion requested; response below

**Opinion: the reasoning for `ohlcv_delta.py` is sound and independently corroborated; the `price_levels.py`
fix is correct and is exercised by genuine data characteristics; one residual nuance is flagged as NOTE-3
(re-numbered from the original audit's NOTE slots) below.**

Independently re-derived the raw-feed gap statistics rather than trusting the stated figures: direct
inspection of `data/raw/NQ_v0_1s_2025.parquet` (12,083,801 rows) shows **1,366,165 single-second gaps**
(≈11.3% of all consecutive-bar intervals — i.e. roughly 1 in 9 seconds has no print), and **532 gaps ≥60s**
(genuine multi-minute-or-longer discontinuities, up to ≈73 hours, consistent with weekends/holidays/maintenance
breaks). This corroborates both halves of the stated reasoning:

1. Single-second gaps are common enough (11.3%) that an exact-count (`cnt == W`) requirement on `ohlcv_delta.py`'s
   5s-1800s windows would indeed mark the overwhelming majority of long windows unavailable, for a reason
   (a quiet second correctly contributing zero) that does not compromise the correctness of a **sum**-based
   aggregate (`vol_sum`, `est_delta_sum`, `est_abs_delta_sum`, `upbar_vol_sum`, `downbar_vol_sum`, etc.) — a
   missing zero-volume bar and an explicit zero-volume bar contribute identically to a sum. Reverting to the
   time-span-only check for these fields is reasonable and correctly documented in-code.
2. Genuine gaps ≥60s do occur (532 instances, confirming the reasoning's premise that these are a "different,
   coarser, more meaningful signal" than a quiet second) — so `price_levels.py`'s stricter exact-span check on
   its 1-minute rolling windows (`window[-1][0] - window[0][0] == (W-1)*60*NS`, `price_levels.py:157-158`) is
   not a no-op; it will actually fire on real data. This check's correctness also depends on both call sites
   (`FeatureEngine.update_1m` and `attach_features.py`'s replay loop) invoking `PriceLevelTracker.update_1m()`
   only once per genuinely-completed 1-minute bar, spaced 60s apart with a *skip* (not a zero-fill) across a gap
   rather than a synthetic placeholder bar — confirmed true for `attach_features.py`'s bucket-finalization logic
   (an entirely-empty minute bucket is never synthesized; the loop simply jumps `current_minute` to the next
   non-empty bucket) and consistent with `FeatureEngine.update_1m()` only being invoked when NT actually
   dispatches a completed 1-minute bar.

One nuance the stated reasoning does not address: `ohlcv_delta.py`'s **`vol_mean_1s_<W>s`** field is a mean,
not a sum, and *is* affected by silently-dropped gaps — `vol_mean_1s = sum(vols_present) / count(vols_present)`,
whereas the "true" mean-per-calendar-second would divide by the true elapsed-second count (including the
implicit-zero seconds). Given the true feed's ~11% per-second gap rate, for wide windows (900s, 1800s) this
field is very likely almost always computed over a materially smaller denominator than the window's nominal
width, systematically **overstating** `vol_mean_1s` (a sum unaffected by omitted zeros, divided by an
undercount of seconds, is biased high). This is a minor, non-blocking nuance (does not affect the sum-type
fields the reasoning was defending, and is much smaller in relative terms than the CRIT-1/CRIT-3/CRIT-5 issues)
but the blanket "a sum is legitimately unaffected" framing was applied to the whole revert, including one field
that is not a sum. See NOTE-3.

## New findings from this pass

### [CRIT-5] `attach_features.py:177-186` vs `features/engine.py:111-154` — offline replay and live `FeatureEngine` now disagree, systematically, on which 1-second bars belong to the "old" vs. "new" regime/RTH state at every transition — CRIT-2's fix corrected live's 100%-wrong attribution but left a new, different offline/live mismatch unaddressed

**This directly contradicts `validation/feature_validation.md`'s claim ("attach_features.py's own replay was
already correct... and needed no change here") — that claim was never actually cross-checked against the
now-fixed live engine at the transition boundary, and is not true as stated.**

`studies/regime_sequence_chop_context/reproduce_regimes.py:96-109` (`aggregate_and_run_regimes`, the function
`canonical_regime_timeline` uses to build `regime_starts`) buckets 1s bars into 1-minute bars for regime
detection and sets `close_ts = (bucket_id + 1) * bucket_size` — every `regime_start_ns` value is therefore an
exact multiple of `60 * NS` (a genuine 1-minute-bar close boundary). Given that:

- **Offline** (`attach_features.py:177-179`):
  ```python
  while reg_idx + 1 < len(regime_starts) and bar_ts >= regime_starts[reg_idx + 1]:
      reg_idx += 1
      ohlcv_tracker.reset_regime(int(regime_starts[reg_idx]), float(opens[i]))
  ```
  advances `reg_idx` (and calls `reset_regime`) only when a 1-second bar's own `bar_ts` reaches the exact
  boundary value. Since `regime_starts[k]` is a multiple of 60s, the **first** 1-second bar satisfying
  `bar_ts >= regime_starts[k]` is the bar whose `ts` **equals** that boundary — i.e. the single last second of
  the transitioning minute. The other 59 seconds of that same minute (which, per `reproduce_regimes.py`'s own
  definition, is the new regime's *first* 1-minute bar) get accumulated into the **old** regime's state before
  the reset fires.
- **Live** (`engine.py:111-123, 149-154`, post-CRIT-2-fix): the regime-id change is only detectable at
  `update_1m()`, which fires once for the whole minute. `reset_regime()` fires first, then **all 60** of that
  minute's buffered 1-second bars are replayed into the freshly-reset **new** regime's state.

Net effect: for the single 1-minute bar that is the *first* bar of every new regime (and, identically, the
first bar of every new RTH session, via the exact same `accumulate_regime_rth()` gating mechanism and the same
minute-aligned boundary argument), offline attributes 59/60 seconds of it to the **old** regime/session and
1/60 second to the **new** one; live (correctly, per its own now-fixed logic) attributes all 60/60 seconds to
the **new** regime/session. These are two different, mutually inconsistent answers — not "close enough," and
not merely a first-checkpoint artifact: because the surface's `observation_time` grid is `arange` **from
`regime_start_ns` itself** (confirmed at `attach_features.py:141-147`'s own comment), the very first checkpoint
of literally every regime episode in the surface (`observation_time == regime_start_ns`, i.e. the
`regime_elapsed_seconds == 0` row — the single most commonly referenced checkpoint type in this project's own
prior work, per memory notes on "bar0"/"flip2conf"/immediately-post-flip features) lands exactly on this
transition bar.

Verified by direct execution (not just derivation) using the actual `OHLCVDeltaTracker` class, replaying a
synthetic 5-minute-old regime followed by a transition at `ts=300s` with constant per-bar volume=10:

```
OFFLINE regime_vol_sum at checkpoint ts=300 (t=0 of new regime): 10.0   (bars in log: 1)
LIVE    regime_vol_sum at checkpoint ts=300 (t=0 of new regime): 600.0  (bars in log: 60)
```

A **60x** discrepancy at the exact checkpoint most studies in this project key off of. The same mechanism
(`accumulate_regime_rth`'s `if self._rth_active:` gate, reset via `reset_rth()`/`end_rth()`) applies identically
to `rth_vol_cum`, `rth_est_delta_cum`, `rth_abs_delta_cum`, and `rth_est_delta_ratio_cum` at every RTH open —
the first RTH minute is undercounted by 59/60 offline and correctly counted 60/60 live. Beyond the first
checkpoint, this is not a decaying artifact either: it is a **permanent absolute deficit** carried in the
offline `regime_vol_sum`/`regime_est_delta_sum`/`regime_high`/`regime_low`/`_regime_bar_log` (and hence
`regime_first_half_*`/`regime_second_half_*`) for the *entire life of that regime* relative to what live
computes — for short-lived regimes (this project's own memory notes describe regime duration as "everything,
unpredictable," including very short episodes) the missing 59 seconds can be a large fraction of the regime's
total accumulated activity, not a negligible rounding effect.

Not caught by the existing test suite: `test_ohlcv_delta_regime_transition_buffers_and_replays_correctly`
(added for CRIT-2) validates `FeatureEngine`'s own internal buffer-and-replay behavior in isolation and would
correctly pass regardless of this issue — it never runs `attach_features.py`'s replay loop side-by-side with
`FeatureEngine` to check the two agree at a transition boundary. No such offline-vs-live parity test exists in
this study for the A4/A5 feature families.

**Recommended fix (do not apply):** bucket 1-second bars into 1-minute buckets first (e.g. reuse
`minute_bucket_key()`) when deciding regime/RTH transitions in the offline replay, so the *entire* minute whose
close matches `regime_starts[k]` is attributed to the new regime/session in one step — matching what `live`
can (only) know at 1-minute granularity — rather than crossing the boundary per-1-second-tick. Add a dedicated
regression test that runs both `attach_features.py`'s replay logic and `FeatureEngine`'s buffer-and-replay logic
over the *same* synthetic 1s bar sequence spanning a regime/RTH transition and asserts they produce identical
`regime_vol_sum`/`rth_vol_cum` (and related) values at every checkpoint, not just internally-consistent ones.

## New notes

### [NOTE-3] `ohlcv_delta.py`'s `vol_mean_1s_<W>s` is a mean, not a sum, and is not protected by WARN-1's stated reasoning

See the WARN-1 discussion above. `vol_mean_1s = sum(vols_present)/count(vols_present)`, silently biased high
by the ~11.3% per-second gap rate for wide windows, since dropped bars remove seconds from the denominator
without removing (zero) volume from the numerator. Minor relative to other findings in this pass; flagged for
completeness since the revert's blanket justification technically overreaches for this one field.

**Recommended fix (do not apply):** either compute `vol_mean_1s` as `sum / (elapsed window seconds)` using the
time span rather than the raw bar count, or add a distinct, weaker availability flag for mean-type fields only.

### [NOTE-4] `tests/test_attach_features.py`'s module docstring overstates its own CRIT-4 coverage

The docstring states the file "Covers CRIT-1 ... and CRIT-4 (regime-relative warmup for the validation-smoke
padding)," but the file contains only two `minute_bucket_key` tests (CRIT-1) and no test at all exercising the
`prior_regime_starts`/`replay_start` extension logic added for CRIT-4. The CRIT-4 fix was verified correct in
this pass by independent code tracing (see above), not by an actual regression test — the claimed test
coverage does not exist. Recommend adding a test that constructs a synthetic multi-year-spanning regime,
truncates the replay window to fall inside it with `--start` more than 5 days after the regime's true start,
and asserts `replay_start` (or an equivalent observable side effect, e.g. `_regime_bar_log`'s earliest entry)
reflects the true regime start, not the fixed 5-day pad.

---

*Re-audit complete. All claims in this section were independently re-derived from the current state of the
code (not assumed from the fix descriptions provided) and, where practical, corroborated by direct script
execution against the actual raw data file and the actual tracker classes (not merely inferred from reading).
CRIT-1, CRIT-3, and CRIT-4 are closed. CRIT-2's live-side defect is closed, but its interaction with the
unchanged offline replay produces a new CRITICAL (CRIT-5) that must be fixed, with a cross-pipeline parity
test added, before this study's features may be promoted out of `provisional`.*

---

# THIRD PASS — CRIT-5 Fix Verification (2026-07-19)

**Scope:** `studies/ohlcv_volume_delta_price_level_features/attach_features.py` (314 lines, re-read in full
at current state), `features/engine.py` (263 lines, re-read in full), `features/trackers/ohlcv_delta.py`
(380 lines, re-read in full), `studies/ohlcv_volume_delta_price_level_features/tests/test_attach_features.py`
(177 lines, new test added), `studies/regime_sequence_chop_context/reproduce_regimes.py` and
`studies/CODEX_5_X_weakness_atlas_repair/CODEX_5_X_run_established_fade.py` (read-only, to re-confirm
`regime_start_ns` == minute-close-timestamp semantics), `validation/feature_validation.md` (claims
cross-checked against code and against direct execution, not taken at face value). Full test suite executed
(`python -m pytest tests/test_feature_library.py studies/ohlcv_volume_delta_price_level_features/tests/ -q`
→ **41 passed**, matches expectation). `results/smoke5day_manifest.json`, `_work/smoke5day_2025.parquet`,
and `validation/sample_features.parquet` independently loaded and inspected (not just the manifest's
self-reported summary) — confirmed the two parquet files are row-for-row, value-for-value identical
(spot-checked `regime_vol_sum`, `rth_vol_cum`, `bar_est_delta`, max abs diff `0.0` across all 2,248 rows).
Also independently re-derived `canonical_regime_timeline`'s regime-start semantics by direct execution
against the real `NQ_v0_1s_2025.parquet` raw file (12,083,801 rows) rather than assuming the prior pass's
characterization still holds.

## Summary (third pass)

- Critical: **0**
- Warning: **2** (new: WARN-4, WARN-5)
- Note: **1** (new: NOTE-5)

**Overall: PASS — 0 CRITICAL required for acceptance, 0 found.** CRIT-5's core defect (offline/live
disagreement on regime_vol_sum/rth_vol_cum at every transitioning minute) is verified fixed, both by
re-derivation and by direct execution of the actual `OHLCVDeltaTracker`/`FeatureEngine`/`attach_features.py`
code (not merely re-reading the diff). The 5-day smoke artifact currently sitting in `_work/` and
`validation/` is confirmed structurally sound (`row_count_unchanged=True`, `labels_unchanged=True`,
`provenance_violations=0`) and, independently, is **not** corrupted by either of the two new residual
issues found below (both confirmed dormant for this specific run by direct data inspection). Two new
WARNING-level defects were found in code paths adjacent to the CRIT-5 fix — neither reaches CRITICAL
severity because both are confirmed, by direct execution against the real data and the real generated
artifact, to be currently inert (not corrupting the smoke output or the full 6-year production path), but
both are genuine, reproducible bugs that should be fixed and covered by a real test before being relied
upon in a future run that does exercise the conditions that trigger them.

## Fix verification detail

### CRIT-5 core mechanism — VERIFIED FIXED

Confirmed the restructuring described (`attach_features.py:200-241`) matches the stated design: each
forming minute's 1s bars are buffered in `minute_buffer` (initialized/reset at `attach_features.py:210-211,
235-236`), and only at that minute's completion (`elif minute_key != current_minute:`, `attach_features.py:212`)
does the code resolve `m_close_ts` (`:215`), advance `reg_idx`/call `reset_regime()` using `minute_o` as the
anchor (`:217-219`), resolve the RTH transition (`:221-226`), and only *then* replay the buffered bars via
`accumulate_regime_rth()` (`:228-229`) — matching `FeatureEngine.update_1m()`'s own reset-then-replay order
(`features/engine.py:111-123` regime reset, `:142-147` RTH reset, `:149-154` buffer replay). Reproduced the
`test_offline_and_live_regime_transition_attribution_match` scenario by hand-tracing what the **pre-CRIT-5**
offline code (1-second-granularity `while ... bar_ts >= regime_starts[reg_idx+1]`, immediate
`accumulate_regime_rth` per bar) would have produced for the same synthetic sequence: `regime_vol_sum` at
the checkpoint immediately after the transition would have been `10.0` (only the single boundary-second bar),
not `600.0` (the whole confirming minute) — confirming the test is a genuine, non-tautological regression
guard for the specific defect CRIT-5 describes, and that the fix as implemented resolves it. **CRIT-5 is
correctly closed for its stated defect.**

### Question 2 — Pre-loop initialization: regime index is correct; **anchor price is wrong** (new finding, WARN-4)

Traced `attach_features.py:179-190`:
```python
reg_idx = -1
if len(regime_starts) and int(regime_starts[0]) <= int(ts[0]):
    reg_idx = int(np.searchsorted(regime_starts, ts[0], side="right")) - 1
    start_i = int(np.searchsorted(ts, regime_starts[reg_idx], side="left"))
    if start_i < len(ts) and int(ts[start_i]) == int(regime_starts[reg_idx]):
        ohlcv_tracker.reset_regime(int(regime_starts[reg_idx]), float(opens[start_i]))
```
The `reg_idx` selection (`searchsorted(regime_starts, ts[0], side="right") - 1`) is **correct**: since
`regime_starts` is guaranteed strictly increasing and duplicate-free (enforced by
`canonical_regime_timeline`'s own `RuntimeError` guards), this always resolves to the index of the most
recent regime confirmed at or before the window's first loaded bar — verified by direct construction of a
multi-regime synthetic array and by confirming the "not found" fallback path (`ts[start_i] != regime_starts[reg_idx]`,
e.g. a genuine gap at that exact second) leaves `_regime_start_ts = None` (so `regime_available=False` and
every derived field reports `None`, never a wrong number) while `reg_idx` itself remains correctly advanced —
the next in-window transition (main-loop `while` at `:217-219`) picks up from the right place with no
desync. **The fallback is confirmed safe, as claimed.**

However, when the anchor bar **is** found (`ts[start_i] == regime_starts[reg_idx]`), the price used is
**wrong**. `regime_starts[reg_idx]` is, by construction (`reproduce_regimes.py:108-109`,
`aggregate_and_run_regimes`'s `close_ts = (bucket_id + 1) * bucket_size`), always an exact multiple of 60s —
i.e. the **close** timestamp of the confirming minute. Given `minute_bucket_key`'s own (correct, CRIT-1-fixed)
convention that a bar whose `ts` is an exact multiple of 60s is the bar covering `(ts-1s, ts]`, i.e. the
**last** second of that minute — `opens[start_i]` is the open of the single last-second bar of the
confirming minute, **not** the minute's own true open (which would require the bar at
`regime_starts[reg_idx] - 59s`, the *first* second of that minute — exactly what `minute_o` represents in
the main loop's own, now-corrected convention at `:219`).

Verified by direct execution (not just derivation): fed a synthetic scenario reproducing the realistic case
where `raw.loc[replay_start:replay_end]`'s truncation (per CRIT-4's `replay_start = min(padded_start,
true_active_start)`, `:112-117`) causes the loaded window's very first bar to land exactly on
`regime_starts[reg_idx]` itself (the common/expected outcome whenever CRIT-4's extended-pad branch is
actually taken, since `true_active_start` **is** `regime_starts[reg_idx]` verbatim):

```
start_i: 0   ts at start_i (s): 6000
PRE-LOOP INIT anchor price (opens[start_i]): 100.59
TRUE minute_o (first second of that minute) would have been: 100.0
Mismatch magnitude: 0.59
```

This is not a rounding-level difference — it is the full magnitude of intra-minute drift, the same class of
issue previously flagged as WARN-3 (there: live-vs-offline; here: an internal inconsistency between the
pre-loop-init anchor and the main loop's own `minute_o` convention, within the offline path alone). It feeds
`regime_price_change_atr`, `regime_volume_per_atr_moved`, and `regime_abs_delta_per_atr_moved` for the
**entire remaining life, within the loaded window,** of whatever regime was already active when a windowed
(`--start`/`--end`) replay begins.

**Confirmed dormant for the currently-generated artifacts, by direct execution against the real data:** for
`smoke5day_2025.parquet` (`--start 2025-01-06 --end 2025-01-11`), independently reran the regime-timeline
and padding computation against `data/raw/NQ_v0_1s_2025.parquet` and found `raw.index.min() ==
2025-01-01 23:00:00 UTC`, `padded_start == 2025-01-01 00:00:00 UTC` (so no clipping occurs — `ts[0]` is raw's
own natural first bar, `23:00:00`), and the year's **first-ever** confirmed regime start is
`2025-01-01 23:19:00 UTC` — i.e. `regime_starts[0] > ts[0]`, so the pre-loop-init `if` condition is **false**
for this run and the buggy branch never executes. This also means the bug is **structurally unreachable** in
the full unwindowed 6-year production path (`--start`/`--end` both `None`): there, `ts[0]` is always the raw
year file's own absolute first bar, which by definition precedes any regime confirmation computed from that
same file, so `regime_starts[0] <= ts[0]` can never hold. **The bug is real, reproducible, and would corrupt
output the moment someone runs a windowed replay whose `--start` falls inside a regime that is genuinely
>5 days old at that point** (exactly the scenario CRIT-4 was written to protect against) — but it does not
corrupt the artifacts currently being certified in this pass.

**Recommended fix (do not apply):** in the pre-loop init, instead of anchoring on `opens[start_i]` (the bar
at the exact `regime_starts[reg_idx]` timestamp), search for the bar at `regime_starts[reg_idx] - 59s` (the
minute's true first second) — or, more robustly, buffer/replay that partial first minute the same way the
main loop's `minute_buffer` mechanism does, rather than special-casing a single anchor bar.

### Question 3 — `minute_buffer` scoping — VERIFIED CORRECT for its intended scope; trailing minute never flushed (new finding, WARN-5)

Traced the exact ordering within the `elif minute_key != current_minute:` branch (`attach_features.py:212-236`):
the just-completed minute is finalized and replayed using the *pre-reassignment* `minute_buffer` (`:228-229`,
executed before line 236 reassigns it), and the triggering bar `i` (the first bar of the **new** minute) is
correctly **excluded** from that replay and correctly becomes the sole seed of the **next** `minute_buffer`
(`:236`). No leakage in either direction for interior minutes — confirmed by hand-tracing index boundaries
and cross-checked against the passing `test_offline_and_live_regime_transition_attribution_match`.

**However:** there is no flush step after the main `for i in range(n):` loop ends (`:200-241`) before
`feat_df = pd.DataFrame(records)` is built (`:259`). This means the **trailing, still-forming minute** at the
end of every replay window — whether the full unwindowed year or a `--start`/`--end` window — is buffered
into `minute_buffer` but **never** passed to `accumulate_regime_rth()` or `price_tracker.update_1m()`. This
is a **genuine regression introduced specifically by the CRIT-5 restructuring**: the pre-CRIT-5 offline code
accumulated `regime_vol_sum`/`rth_vol_cum` immediately per 1-second bar (no buffering), so every loaded bar —
including the very last one — was always counted; the new minute-buffered design defers that accounting to
minute-completion, which the last (necessarily incomplete, from the loop's point of view) minute of any
window never reaches. (`price_tracker.update_1m()`'s own trailing-minute gap is not new — it always operated
at 1-minute granularity and always had this property — so this is specific to the newly-buffered
`OHLCVDeltaTracker` regime/RTH path.)

**Confirmed dormant for the currently-generated smoke artifact, by direct inspection:** loaded
`smoke5day_2025.parquet` and found `observation_time` ranges from `2025-01-06 14:37:40 UTC` to
`2025-01-10 20:59:30 UTC`, more than 3 hours before the loaded raw window's own trailing boundary
(`--end 2025-01-11`, i.e. `2025-01-11 00:00:00 UTC`) — zero surface rows fall anywhere near the final minute
of the loaded window. The same is true, by construction, of every trading day's own established-regime/RTH
filtering in this study's surface, making it very unlikely (though not structurally impossible, unlike
WARN-4) to matter for the full 6-year production run either. Also verified (per the request) that a
**simultaneous** regime-and-RTH transition confirmed on the same minute close is handled correctly: both the
regime `while` loop (`:217-219`) and the RTH check (`:221-226`) run to completion, in that order, **before**
the shared `minute_buffer` replay (`:228-229`) — so a minute that both changes regime and opens/closes RTH
correctly attributes its bars under both new states at once, with no ordering hazard, matching the identical
ordering in `features/engine.py:111-154`.

**Recommended fix (do not apply):** after the main loop ends, flush any non-empty trailing `minute_buffer`
the same way the `elif` branch does (using `ts[-1]`-derived `m_close_ts`, `reg_idx` catch-up, RTH check, and
`accumulate_regime_rth()` replay) before constructing `feat_df`.

### Question 4 — Regression test coverage — core assertion valid; pre-loop-init path and anchor-tick granularity **not** covered (NOTE-5)

`test_offline_and_live_regime_transition_attribution_match`'s `regime_vol_sum` assertion is a genuine,
non-tautological regression test for CRIT-5's core defect (see above — traced by hand that it would have
failed against the pre-fix code, giving `10.0` instead of `600.0`). The test's own internal bucket-alignment
arithmetic is correct and not accidentally testing the wrong thing: `ts0` is deliberately constructed as
`((base_s // 60) * 60 + 1) * NS` (the true first second of a minute), and `close_a/b/c` are derived via
`minute_close_ts()`, itself built from the *same* `minute_bucket_key()` function under test — not
independently hand-computed offsets — so the test cannot silently drift from what the code under test
actually does. Verified this arithmetic by direct substitution.

**However, two coverage gaps, both bearing directly on the findings above:**

1. `_offline_style_regime_replay()` (the test's "Minimal replica" of the offline path, `:71-103`) does
   **not** include any equivalent of `attach_features.py`'s actual pre-loop-init block (lines 179-190) — it
   starts cold (`reg_idx = -1`) and relies on the *ordinary* main-loop transition-catch mechanism to
   establish the "already active" old regime (since `regime_starts[0] == ts0` triggers the normal `elif`
   path at minute 0's completion, using the correct `minute_o`). The test's own comment ("Old regime already
   active at ts0 (matches the pre-loop init path)") **overstates** what is actually exercised — the real
   pre-loop-init code in `attach_features.py` is never invoked by this test, so it provides **zero**
   coverage of WARN-4's defect. This is the same class of overstatement already flagged in the prior pass's
   NOTE-4 (CRIT-4's own `replay_start`/`prior_regime_starts` logic), now recurring for the CRIT-5 test.
2. Independent of (1): even if the test *did* call the real pre-loop-init code, its synthetic fixture uses a
   **constant open price throughout each minute** (`100.0` for minutes 0-1, `105.0` for minute 2) — so the
   anchor-price assertion (`== pytest.approx(105.0)`) would pass identically whether the *first*-second's
   open or the *last*-second's open were used, since they're the same value in this fixture. A test built to
   actually catch WARN-4 needs a fixture with a **drifting** price within the transitioning minute (as used
   in this pass's own ad hoc verification script), not a flat one.

**Recommended fix (do not apply):** add a dedicated test that (a) calls `attach_features.py`'s actual
pre-loop-init code path (not a hand-rolled replica) with a synthetic regime whose start predates the loaded
window by construction, and (b) uses a drifting (non-constant) open price across the confirming minute, then
asserts the resulting anchor price equals the minute's true first-second open, not the boundary second's.

## New findings from this pass

### [WARN-4] `attach_features.py:184` — pre-loop-init anchor price uses the confirming minute's *last*-second open, not its own true (first-second) open, inconsistent with the main loop's `minute_o` convention

See "Question 2" above for full detail, execution trace (`0.59`-point synthetic discrepancy), and confirmed
dormancy for the current smoke/production artifacts. **Severity note:** rated WARNING, not CRITICAL,
consistent with this project's own precedent for WARN-3 (an anchor-tick/price granularity mismatch of the
same general character, non-look-ahead, deterministic, and — per direct execution — currently inert for
every artifact this pass was asked to certify). Should be fixed and given a real regression test (see NOTE-5)
before any future windowed replay is run against a regime that is genuinely older than 5 days at its
`--start` boundary.

### [WARN-5] `attach_features.py:200-259` — trailing/still-forming minute at the end of any replay window is buffered but never flushed into `OHLCVDeltaTracker`'s regime/RTH cumulative state

See "Question 3" above for full detail and confirmed dormancy (`smoke5day_2025.parquet`'s last
`observation_time` is >3 hours before the loaded window's own trailing edge). A genuine regression
introduced by the CRIT-5 restructuring (the pre-CRIT-5 code had no such gap, since it accumulated per-bar
immediately). Should be fixed with a post-loop flush and covered by a test asserting a checkpoint in the
literal last minute of a replay window still receives correct `regime_vol_sum`/`rth_vol_cum` credit.

## New notes

### [NOTE-5] `test_offline_and_live_regime_transition_attribution_match` does not exercise the pre-loop-init code path or distinguish anchor-tick granularity — overstated coverage, recurrence of the prior pass's NOTE-4 pattern

See "Question 4" above. The test's `_offline_style_regime_replay()` helper is a simplified stand-in that
happens to sidestep both WARN-4 (by using the ordinary transition-catch instead of the real pre-loop-init
code) and would not detect it even if wired up (flat per-minute OHLC fixture cannot distinguish first-second
open from last-second open). Recommend the fix described under WARN-4/Question 4 above.

## Independent confirmation of items 6 and 7 (as requested)

- **Item 6:** `python -m pytest tests/test_feature_library.py studies/ohlcv_volume_delta_price_level_features/tests/ -q`
  → **41 passed**, 0 failed, 0 errors. Matches the expected count exactly.
- **Item 7:** `results/smoke5day_manifest.json` (2025 entry): `row_count_unchanged=true`,
  `labels_unchanged="True"`, `provenance_violations=0`, `duplicate_rows=0`. Independently re-loaded
  `_work/smoke5day_2025.parquet` (2,248 rows x 652 columns) and `validation/sample_features.parquet`
  (2,248 rows x 652 columns) directly (not trusting the manifest's self-report) and confirmed the two files
  are identical row-for-row on the join key (`regime_start_ns`, `observation_time`) and value-for-value on
  spot-checked columns (`regime_vol_sum`, `rth_vol_cum`, `bar_est_delta` — max absolute difference `0.0`
  across all 2,248 rows). Both claims independently corroborated, not merely re-stated.

---

*Third pass complete. CRIT-5 is verified fixed by direct execution, not merely by re-reading the diff. Two
new WARNING-level findings (WARN-4, WARN-5) were discovered in code paths immediately adjacent to the fix —
both confirmed real and reproducible by direct execution against synthetic data, and both confirmed currently
dormant (do not corrupt the smoke artifact or the full production path) by direct execution against the real
raw data and the real generated parquet outputs. 0 CRITICAL findings remain open. Recommend fixing WARN-4 and
WARN-5 (and closing NOTE-5's test-coverage gap) before this study is exercised with any windowed replay whose
`--start` lands inside a regime older than 5 days, or before relying on features at the literal trailing edge
of any replay window — neither condition is present in the currently-certified 5-day smoke or (per the
structural argument above) the full 6-year production run, so this does not block promotion out of
`provisional` on its own, but should not be deferred indefinitely.*
