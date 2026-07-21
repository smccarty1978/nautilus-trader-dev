# Look-Ahead & Timestamp Audit

**Date:** 2026-07-20
**Scope:** `studies/long_rth_mirrored_surface_top100_training/{SPEC.md, implementation/build_surface_long.py, implementation/attach_features_long.py, implementation/assemble_and_label.py, implementation/data_readiness_gate.py, implementation/train_and_evaluate_long.py, results/*.csv, results/*.json}` plus read-only boundary inspection of `studies/short_rth_entry_surface_backfill/entry_surface.py`, `studies/ohlcv_volume_delta_price_level_features/attach_features.py` + `SPEC.md`, `studies/short_rth_enriched_volume_level_retrain/train_and_evaluate.py`, `studies/regime_sequence_chop_context/build_weakness_atlas.py`, `studies/CODEX_5_X_weakness_atlas_repair/CODEX_5_X_build_repaired_atlas.py`, `studies/CODEX_5_X_weakness_atlas_repair/CODEX_5_X_run_established_fade.py`, `features/trackers/ohlcv_delta.py`, `features/trackers/price_levels.py`.
**Auditor:** lookahead-auditor v1
**Scope hash (files inspected, sha256 of path list):** `long_rth_mirrored_surface_top100_training+5upstream+2trackers-20260720`

This study performs no NautilusTrader execution and computes no trade economics
(no fills, no PnL, no brackets). Sections E and H of the standard checklist are
**N/A** by design and are not scored below. The audit judges look-ahead bias,
target leakage, directionality correctness, and train/dev/test discipline only,
per the brief.

## Summary

- Critical: 1
- Warning: 2
- Note: 3

**Blocking verdict: DOES NOT PASS (1 CRITICAL outstanding).**

## Critical findings

### [B2 / A1(analog) / D1] `attach_features_long.py:83,119-121,152-156` — inclusive bar-snap feeds the still-forming raw bar into ~97.5% of checkpoints, leaking up to 1s of future OHLC into 56 of the 100 frozen features

**Mechanism.** The checkpoint snap is:

```
82:    obs_times = surface["observation_time"].to_numpy(np.int64)
83:    snap_idx = np.searchsorted(ts, obs_times, side="right") - 1
```

`side="right" - 1` returns the *last index with `ts <= obs_time`*, i.e. it
**includes** an exact match `ts[idx] == obs_time` when one exists. The main
replay loop then does, unconditionally, for every raw bar `i`:

```
119:    for i in range(n):
120:        bar_ts = int(ts[i])
121:        b_est = ohlcv_tracker.update(bar_ts, opens[i], highs[i], lows[i], closes[i], vols[i])
...
152:        hits = obs_lookup.get(bar_ts)
153:        if hits:
154:            for regime_start_ns, obs_time, atr in hits:
155:                f_ohlcv = ohlcv_tracker.calculate(atr=atr)
156:                f_price = price_tracker.calculate(bar_ts, closes[i], atr, direction=LONG_DIRECTION)
```

When `bar_ts == obs_time` (the common case), bar `i`'s own `high/low/close/
volume` are pushed into `ohlcv_tracker.update()` and `closes[i]` is used
directly as `reference_price` in `price_tracker.calculate()` **before** the
checkpoint's own features are computed — i.e. the checkpoint at
`observation_time = T` is scored using a bar whose full range is `T`'s own bar,
not a bar that closed before `T`.

**Why this is a real bar boundary violation, not a naming quibble.** This
project's own authoritative timestamp convention is that raw 1s bars are
**open-labelled**:

- `CLAUDE.md` core invariant #3: "Databento timestamps at OPEN... 1s bars need
  no adjustment" (i.e. the raw index *is* open time, not close time).
- User memory: "1s ts_init = ts_event + 1s → 1s bars arrive BEFORE parent 1m
  bar" (close time is `ts_event + 1s`, one second later than the index).
- `studies/CODEX_5_X_weakness_atlas_repair/CODEX_5_X_run_established_fade.py:4`:
  *"1-second bars are open-labelled: the range at ts_event=t describes
  [t, t+1s)."*

Under that (correct, project-wide) convention, a bar with `ts_event == T` has
**not yet closed** at instant `T` — its high/low/close are not knowable until
`T+1s`. Using it to compute a feature snapshotted "at" `T` is a one-bar
look-ahead.

This is corroborated by three independent pieces of evidence inside the very
code being audited:

1. **The atlas's own checkpoint-feature builder uses the opposite (strict)
   convention**, `studies/regime_sequence_chop_context/build_weakness_atlas.py:96-98`:
   ```
   # Last completed bar at cp_ts has ts_event strictly before cp_ts.
   idx_cp = np.searchsorted(ts_arr, cp_ts, side='left') - 1
   ```
   This deliberately **excludes** the bar with `ts_event == cp_ts`. The 44
   atlas-sourced center/slope/alignment features joined by
   `assemble_and_label.py` inherit this correct, strict convention (further
   enforced by a hard `RuntimeError` assertion in
   `CODEX_5_X_build_repaired_atlas.py:82`: `feature_bar_ts_event <
   observation_time`, strict). Those 44 features are **not** affected by this
   finding (see Clean checks).
2. **`OHLCVDeltaTracker`'s own docstring mandates completed bars only**
   (`features/trackers/ohlcv_delta.py:14-17,90`: *"the caller must call
   update() only with COMPLETED bars, never a still-forming bar"*), which the
   replay loop violates whenever `bar_ts == obs_time`.
3. **The feature system's own written contract says the same thing and is
   violated**: `studies/ohlcv_volume_delta_price_level_features/SPEC.md:157,
   162-166,193-194`: *"latest_source_ts_used <= observation_ts... features
   describe what is knowable at the decision"* and *"computed from completed
   1s bars only (current forming bar excluded)"*. The snap as coded treats
   equality as compliant (`attach_features_long.py:171`:
   `dq_violations = (merged["latest_source_ts_used"] > merged["observation_time"]).sum()`
   — only strict `>` is flagged, `==` is silently accepted), which is the
   opposite of "current forming bar excluded."

Note a compounding internal inconsistency that helped produce this bug: the
tracker's own rolling-window code comments the raw bar as **close-labelled**
(`features/trackers/ohlcv_delta.py:193`: *"Each bar's ts is its CLOSE time and
covers (ts-1s, ts]"*), which directly contradicts the open-labelled convention
stated in `CLAUDE.md`, user memory, and `CODEX_5_X_run_established_fade.py:4`.
Whichever module is "right" in isolation, the two conventions cannot both be
true of the same `RAW_1S` data, and the attach script inherited the tracker's
(incorrect, per project convention) assumption.

**Scope of impact.** `results/phase3_attach_manifest.json` reports
`gap_snapped_checkpoints` (the *exception* case, where no exact match exists)
at roughly 2.2-3.5% of rows per year (e.g. 2023: 4,129 / 167,721 = 2.5%;
2025: 5,643 / 163,397 = 3.5%). The complement — **~96.5-97.8% of all rows,
every year, 2021-2026** — hits the exact-match branch and is affected. This
touches the 29 `ohlcv_est_delta` + 27 `price_level_context` families = **56 of
the 100 frozen model features** (the 44 `regime_median_center_slope_alignment`
features are unaffected, see above).

**This is inherited unchanged, not introduced by the mirror.** The identical
logic (`side="right"-1` snap, unconditional `update()` before `calculate()`)
exists verbatim in the upstream, ostensibly "already audited"
`studies/ohlcv_volume_delta_price_level_features/attach_features.py:149,
210-215,253-267`, which is also what the already-deployed short-side
production model (`short_rth_w4_retrain_entry_strength` /
`short_rth_enriched_volume_level_retrain`) was trained on. This audit's brief
is this study, so it is reported here as CRITICAL for
`long_rth_mirrored_surface_top100_training`; it is very likely present
identically in every prior study built on this attach script and should be
independently triaged there.

**Impact if deployed.** Because `OHLCVDeltaTracker`/`PriceLevelTracker` are the
canonical, registry-listed trackers intended for eventual live NT use
(`features/registry.py:290-293`), and the tracker's own docstring states a live
caller must never call `update()` with a still-forming bar, a live
`FeatureEngine` replaying the same instant would **not** reproduce these
training features for ~97% of rows (it would use the bar that closed one
second *before* `observation_time`, not the one that opens *at*
`observation_time`). This is simultaneously a look-ahead bug (Section B2) and
a latent train/serve skew (Section D1) for any future deployment of this
feature set.

**Recommended fix (do not apply — reporting only):** change the snap to the
atlas's own strict convention, `np.searchsorted(ts, obs_times, side="left") - 1`
(bar strictly before `obs_time`), and audit `dq_violations` to flag `>=`
rather than `>`.

## Warnings

### [B6/data-integrity] `assemble_and_label.py:55` — silent `drop_duplicates` ahead of the causal join

```
54:    atlas = pd.read_parquet(ATLAS_PATHS[year], columns=KEY + CENTER_FEATS)
55:    atlas = atlas.drop_duplicates(KEY)
56:    merged = attached.merge(atlas, on=KEY, how="left", validate="one_to_one")
```

`drop_duplicates(KEY)` silently keeps an arbitrary first row and discards any
other rows sharing `(regime_start_ns, observation_time)` **before** the
`validate="one_to_one"` check runs, so a genuine duplicate-key data-quality
problem on the atlas side (two rows, same key, different center-feature
values) would never raise — it would be silently resolved to whichever row
pandas kept, and the row-count check (`len(merged) != n0`) would not catch it
either, since `attached` (the left frame) already has one row per key. Spot
check of `atlas_5s_backfill_2023.parquet` found **0 duplicate keys** today, so
this is not currently firing, but it is a silent-failure-mode gap rather than
a defended invariant. Recommend asserting `atlas[KEY].duplicated().sum() == 0`
before the `drop_duplicates` call (fail loud) rather than deduplicating
silently.

### [B9] `results/top100_feature_manifest.json` — 3 frozen features remain `TIMING_UNVERIFIED`

`regime_first_half_vol`, `regime_abs_delta_per_atr_moved`,
`regime_price_change_atr` (all `ohlcv_est_delta` family, `source_timeframe=1m`,
per `results/top100_feature_list.csv`) carry `timing_status=TIMING_UNVERIFIED`
in the frozen list this study trains on. `data_readiness_gate.py` does not
check `timing_status` at all (it checks presence, dtype, forbidden-columns,
direction, and label sanity only — see `data_readiness_gate.py:28-55`), so
these 3 unverified-timing features silently pass the Phase 4 gate and enter
training. Given the CRITICAL finding above shows this exact feature family
(`ohlcv_est_delta`) already has a demonstrated boundary-timing defect, these 3
features specifically warrant independent re-verification before any
deployment decision is made on this model.

## Notes

### [process] No automated Phase-0 SHA re-verification script in `implementation/`

`SPEC.md` states "Stop if the source SHA does not reproduce exactly" for the
frozen top-100 feature list, but none of the 5 scripts in `implementation/`
re-hashes `studies/runtime_constrained_f3_feature_reduction/results/
top_100_raw_feature_columns.csv` and compares it to the recorded
`feature_source_sha256`. The match is only asserted as a static field in
`results/top100_feature_manifest.json`, not programmatically re-checked by
this study's own pipeline. Recommend adding an explicit hash-reverification
step (even a one-line assert) to `data_readiness_gate.py` so the frozen-list
contract is enforced by code, not by manifest claim alone.

### [style] `train_and_evaluate_long.py:190-193` — redundant conditional in regime diagnostics call

```
190:        for sp, dfr in (("2025", dev_df), ("2026", test_df)):
191:            rd = regime_diagnostics(dfr, yb[sp], proba["2025" if sp == "2025" else "2026"])
```

`proba["2025" if sp == "2025" else "2026"]` is functionally identical to
`proba[sp]` for this loop's two values of `sp`. Not a bug today, but an
unnecessarily convoluted expression in exactly the kind of place
(split-selection logic) where a careless future edit could introduce a
genuine 2025/2026 split-selection bug without being noticed. No action
required beyond awareness.

### [data-integrity] Zero-volume / single-tick bar handling not independently re-verified for this study

`OHLCVDeltaTracker.bar_estimates()` sets `bar_zero_range=True` and neutral
50/50 splits when `high == low`, but this audit did not independently trace
whether zero-volume/zero-range bars are excluded from the rolling-window ATR
denominators consumed by the 56 replayed features. No evidence of a problem
found; flagged for completeness (G4) since it was not exhaustively verified
within the time budget of this pass.

## Clean checks

- Target arithmetic (C1/C2): `bullish_regime_flip_within_300s =
  (confirm_flip_ns - observation_time)/1e9 <= 300` is pure arithmetic,
  computed once in `assemble_and_label.py:62-67`, and the label/diagnostic
  columns (`confirm_flip_ns`, `time_to_bullish_flip_s`,
  `bullish_flip_within_600s`, `fill_ts`, `fill_px`, the label itself) are
  explicitly excluded from the model matrix and enforced by
  `data_readiness_gate.py:19-20,30,53` (`FORBIDDEN_IN_MATRIX`,
  `n_forbidden_in_matrix` check) — confirmed 0 across all 6 years in
  `results/data_readiness.csv`.
- Feature matrix construction (`train_and_evaluate_long.py:144`,
  `Xb = {"train": train_df[TOP100], ...}`) selects **exactly** the frozen
  100-column list; no metadata/label columns leak in.
- 44 atlas-sourced center/slope/alignment features are causal by construction
  and by hard runtime assertion: `build_weakness_atlas.py:96-98` (strict
  `ts_event < cp_ts`) and `CODEX_5_X_build_repaired_atlas.py:82`
  (`feature_bar_ts_event < observation_time`, `RuntimeError` on violation).
  Not affected by the CRITICAL finding above.
- Directionality (Section 3 of brief): population is `direction == -1` only,
  enforced by `build_surface_long.py:94-95` and re-verified post-hoc by
  `data_readiness_gate.py:31` (`dir_ok`, confirmed `True` all 6 years in
  `results/data_readiness.csv`). Bearish-favorable excursion is
  `anchor - lows[a:b]` (`build_surface_long.py:111`), correctly the mirror of
  the short side's `highs[a:b] - anchor` (`entry_surface.py:86`).
  `price_tracker.calculate(..., direction=LONG_DIRECTION=+1)`
  (`attach_features_long.py:56,156`) correctly flips the `ahead`/`behind`
  branch in `price_levels.py:396-401,414-419` relative to the short side's
  `direction=-1`. The self-validation guard
  (`build_surface_long.py:120-125`, re-derived running MFE vs atlas
  `current_mfe` to 1e-9) is a genuine independent recomputation from raw
  1s bars inside this script, not delegated to the atlas-building code being
  checked, so it is not a tautology.
- Split discipline (Section 4 of brief): train = concatenation of
  2021-2024 only (`train_and_evaluate_long.py:131-132`); calibration fits
  exclusively on 2025 (`CalibratedClassifierCV(FrozenEstimator(est),
  method).fit(Xb["2025"], yb["2025"])`, line 182); model selection is by
  `2025_auc` only (`sel_model = max(selected, key=lambda m:
  selected[m]["2025_auc"])`, line 206); 2026 (`test_df`) is read only for
  final reporting metrics (`base_metrics`, `decile_metrics`, `monthly_auc`,
  `regime_diagnostics`), never for fit/select/calibrate. `fit_gbt`/
  `fit_logistic` (reused from `short_rth_enriched_volume_level_retrain/
  train_and_evaluate.py:56-77`) fit imputer/scaler/model on the train split
  only.
- Encoding (Section 5 of brief): `data_readiness_gate.py:29,53`
  (`n_object_dtype_features`) and `train_and_evaluate_long.py:137-139`
  (raises `RuntimeError` on any object-dtype top-100 column) both confirm 0
  categorical columns in the frozen 100 across all 6 years — no silent
  one-hot expansion occurred, consistent with `SPEC.md`'s documented
  contingency.
- No `.shift(-N)`, `.ffill()`, `.bfill()`, `center=True` rolling, or
  `cross_val_score` found anywhere in the 5 audited implementation scripts.
- RTH/timezone handling (`is_rth()`,
  `CODEX_5_X_run_established_fade.py:146-149`) is tz-aware
  (`pd.Timestamp(..., tz="UTC").tz_convert("America/Chicago")`), DST-safe by
  construction (no manual UTC-offset arithmetic), and applied on fill time per
  the project's documented remediation.
- Data source is `NQ_v0_1s_*.parquet` (`CODEX_5_X_common.py:36-41`), matching
  the project's mandated volume-continuous-only data rule.
- 1-minute bar finalization (`price_tracker.update_1m`,
  `attach_features_long.py:141`) is explicitly called with a computed
  close timestamp (`m_close_ts`), correctly distinct from the raw-bar
  index — this part of the replay loop does *not* exhibit the CRITICAL
  finding's boundary error.

---

*Audit complete. Findings reflect read-only static analysis. This study
performs no NT execution and no trade economics, so Sections E and H of the
standard checklist are out of scope by design, not overlooked. Dynamic bugs
(e.g. race conditions in a future live deployment) are out of scope.*

---

# CONFIRMATORY RE-AUDIT (remediation verification)

**Date:** 2026-07-20
**Scope (this pass):** `implementation/attach_features_long.py`,
`implementation/assemble_and_label.py`, `implementation/data_readiness_gate.py`
(the 3 changed files), plus independent re-derivation from
`_work/attached_long_{2021..2026}.parquet`, `_work/reattach_corrected.log`,
`results/phase3_attach_manifest.json`, `results/phase2_3_assemble_manifest.json`,
`results/phase4_gate_verdict.json`, `results/data_readiness.csv`,
`results/label_quality_by_year.csv`, `results/phase1_surface_manifest.json`,
`implementation/train_and_evaluate_long.py`, `implementation/build_surface_long.py`
(re-confirmation only, unchanged files).
**Auditor:** lookahead-auditor v1 (confirmatory pass)
**Scope hash:** `long_rth_mirrored_surface_top100_training-remediation-verify-20260720`

## Confirmatory summary

- Critical: 0 (prior CRITICAL **RESOLVED**, verified both statically and empirically)
- Warning: 0 (both prior warnings **RESOLVED**)
- Note: 3 (unchanged/carried forward — process and style items, no severity change)

**Blocking verdict: PASSES at 0 CRITICAL / 0 WARNING outstanding.**

## Fix 1 — CRITICAL [B2/A1(analog)/D1] `attach_features_long.py` — RESOLVED

Verified against all four sub-questions in the brief:

**(a) Snap is now strict.** Line 97:
```
97:    snap_idx = np.searchsorted(ts, obs_times, side="left") - 1
```
`searchsorted(..., side="left")` returns the first index with `ts >= obs_time`;
`- 1` gives the last index with `ts < obs_time` — strictly before, matching
`build_weakness_atlas.py:96`'s own convention exactly. On the 1s grid used
throughout (`NS = 1_000_000_000`), `ts[idx] < obs_time` implies
`ts[idx] <= obs_time - NS`, so the bar's true close (`ts[idx] + NS`, per the
open-labelled convention) is `<= obs_time` — genuinely completed by the
observation instant, not merely relabeled.

**(b) Checkpoint features are still drawn from tracker state as of the
strictly-before bar.** The replay loop is otherwise unchanged: `obs_lookup` is
now keyed by `snapped_ts` values that are all strictly `< obs_time` by
construction (line 110, built from `snap_idx`), so `hits = obs_lookup.get(bar_ts)`
(line 168) can only fire when `bar_ts` is itself one of those strictly-before
snapped timestamps. `ohlcv_tracker.calculate()` / `price_tracker.calculate()`
(lines 171-172) run immediately after that bar's own `update()` — i.e. the
tracker state used for the checkpoint is "as of the last completed bar
strictly before `observation_time`," exactly as intended.

**(c) Merge key is still the true `observation_time`, not the snapped
timestamp.** Line 110: `obs_lookup.setdefault(snap_ts, []).append((...,
int(row.observation_time), ...))` — the dict is keyed by `snap_ts` but the
tuple carries the original `row.observation_time`, which is what gets written
into `rec["observation_time"]` (line 173) and used as the merge key at line
185 (`merged = surface.merge(feat_df, on=["regime_start_ns",
"observation_time"], ...)`). Confirmed no substitution of the snapped
timestamp for the true observation instant anywhere downstream.

**(d) No remaining coincident-bar path.** Because `obs_lookup` only ever
contains keys drawn from `snap_idx` (all strictly `< obs_time`), a bar with
`bar_ts == observation_time` can never be a dict key that matches its own
checkpoint — the only way `bar_ts == obs_time` could produce a "hit" would be
if that same instant were *also* the strictly-before snap for a **different,
later** checkpoint, which is by definition still strictly before that other
checkpoint's own `obs_time` and is not a look-ahead for it. No path found
where a bar feeds a coincident checkpoint's features before that checkpoint's
own snap is computed.

**Provenance check tightened as described.** Line 189:
`dq_violations = int((merged["latest_source_ts_used"] >=
merged["observation_time"]).sum())` — now flags `>=` (was `>`), consistent
with "current forming bar excluded" rather than merely "no reordering."

**Independent empirical re-derivation (not trusting the self-reported log).**
Re-computed directly from the 6 `_work/attached_long_{year}.parquet` outputs,
independently of `reattach_corrected.log`:

| year | rows | min(obs_time − latest_source_ts_used) | max gap | rows with gap ≤ 0 | rows with gap < 0 | null latest_source_ts_used |
|---|---|---|---|---|---|---|
| 2021 | 164,940 | 1,000,000,000 ns (1.000s) | 23.0s | 0 | 0 | 0 |
| 2022 | 189,071 | 1,000,000,000 ns (1.000s) | 15.0s | 0 | 0 | 0 |
| 2023 | 167,721 | 1,000,000,000 ns (1.000s) | 33.0s | 0 | 0 | 0 |
| 2024 | 161,220 | 1,000,000,000 ns (1.000s) | 19.0s | 0 | 0 | 0 |
| 2025 | 163,397 | 1,000,000,000 ns (1.000s) | 34.0s | 0 | 0 | 0 |
| 2026 | 52,488 | 1,000,000,000 ns (1.000s) | 16.0s | 0 | 0 | 0 |

This exactly matches the claim in the brief (min gap = 1s, 0 rows with
equality, 0 negative) and independently corroborates `phase3_attach_manifest.json`'s
self-reported `provenance_violations: 0` for all 6 years — this audit did not
merely re-read the manifest, it recomputed the gap distribution directly from
the parquet files.

**Row-count / label invariance confirmed.** `phase3_attach_manifest.json`
`surface_rows` (164,940 / 189,071 / 167,721 / 161,220 / 163,397 / 52,488)
match `phase1_surface_manifest.json` `surface_rows` for the same years exactly
(re-checked 2022/2023 directly), and match `phase2_3_assemble_manifest.json`
`rows` and `data_readiness.csv` `rows` downstream — confirming the fix altered
only the 56 attach-feature **values**, not row identity, censoring, or the
label. `label_quality_by_year.csv` positive rates (0.294 / 0.252 / 0.272 /
0.266 / 0.263 / 0.280 for 2021-2026) are pure functions of
`confirm_flip_ns`/`observation_time` (untouched by this fix) and are
unaffected, as expected.

**Verdict: [B2/A1(analog)/D1] RESOLVED.** No residual look-ahead in the
attach-feature snap. The train/serve-skew concern (D1) also resolves as a
side effect: a live `FeatureEngine` replaying the same instant under the
"never call `update()` on a still-forming bar" contract
(`features/trackers/ohlcv_delta.py:14-17`) would now reproduce the same
strictly-before-`observation_time` tracker state used in training.

**Residual note (not a new finding, restating the prior audit's own
caveat):** the internal doc inconsistency previously flagged — the tracker's
own rolling-window comment at `features/trackers/ohlcv_delta.py:193`
still describes the raw bar as close-labelled ("Each bar's ts is its CLOSE
time"), which contradicts the project's open-labelled convention — is
untouched by this fix (out of scope; the fix operated on the snap index, not
the tracker docstring). This remains a documentation hazard for future
readers of that file but does not affect the correctness of the fix verified
here, since the snap's own strict-inequality arithmetic does not depend on
that comment being correct.

## Fix 2 — WARNING [B6] `assemble_and_label.py:55-58` — RESOLVED

Prior code (`atlas.drop_duplicates(KEY)` before the `validate="one_to_one"`
merge) is gone. Current code:
```
55:    ndup = int(atlas.duplicated(KEY).sum())
56:    if ndup:
57:        raise RuntimeError(f"{year}: atlas has {ndup} duplicate (regime_start_ns, observation_time) keys")
58:    merged = attached.merge(atlas, on=KEY, how="left", validate="one_to_one")
```
This now fails loud (`RuntimeError`) on any duplicate key rather than silently
resolving to an arbitrary first row. Independently re-checked all 6 atlas
files (`atlas_5s_backfill_{year}.parquet`, ~1.3M-4.0M rows each) directly via
`duplicated(KEY).sum()`: **0 duplicate keys in all 6 years**, confirming the
guard does not currently fire but is genuinely present as live, executed code
(not a comment or dead branch) — it sits directly ahead of the merge at
line 59 and there is no `drop_duplicates` call anywhere else in the file.
**Verdict: RESOLVED.**

## Fix 3 — WARNING [B9] `data_readiness_gate.py` — RESOLVED (disclosed, correctly non-blocking)

`phase4_gate_verdict.json` now contains:
```json
"timing_unverified_features_disclosed": [
  "regime_first_half_vol",
  "regime_abs_delta_per_atr_moved",
  "regime_price_change_atr"
],
"timing_unverified_note": "Inherited disclosed residual from the runtime_constrained_f3_feature_reduction study ..."
```
matching `data_readiness_gate.py:62-72`. This is exactly the 3 features named
in the prior audit's B9 finding, so the disclosure targets the correct
residual rather than a superset/subset. The disclosure is intentionally
non-blocking (`verdict` computation at line 53-55 does not reference
`timing_status`) — that is the requested remediation (disclose, don't
silently pass unnoticed) rather than a re-verification of the 3 features'
actual timing correctness. **The underlying timing-unverified status of these
3 features is still not independently re-verified** (this was true before the
fix and remains true after it) — the remediation converts an undisclosed
residual into a disclosed one, which resolves the WARNING as scoped
(disclosure), but does not itself constitute proof those 3 features are
causally clean. This is restated as a **Note** below, not re-raised as a
WARNING, since the requested fix was disclosure and disclosure is confirmed
present and correctly scoped.

## Re-confirmed previously-clean invariants (no regression found)

- **Directionality:** `build_surface_long.py` unchanged; `direction != -1: continue`
  filter (line 94), self-validation guard re-deriving running MFE vs atlas
  `current_mfe` to 1e-9 (lines 120-125), and `prevailing_direction`/
  `entry_direction` assignment (line 161) all present verbatim. `data_readiness.csv`
  confirms `direction_minus1_only=True` for all 6 years post-fix.
- **Split discipline:** `train_and_evaluate_long.py:131-134` — train is still
  exactly the concatenation of 2021-2024 `prepared_long_{year}.parquet`
  outputs; 2025 used only for calibration fit + model selection
  (`2025_auc`, line 206); 2026 read only for final reporting. No fit/select/
  calibrate call references `test_df`/`yb["2026"]` anywhere in the file.
- **Target-leakage exclusion:** `FORBIDDEN_IN_MATRIX` in
  `data_readiness_gate.py:19-20` unchanged (`confirm_flip_ns`,
  `time_to_bullish_flip_s`, `bullish_flip_within_600s`, `TARGET`, `fill_ts`,
  `fill_px`, `regime_end_ns`); `n_forbidden_in_matrix` is 0 for all 6 years in
  the post-fix `data_readiness.csv`.
- **No object-dtype/one-hot leakage:** `n_object_dtype_features` is 0 for all
  6 years in `data_readiness.csv`; `train_and_evaluate_long.py:137-139`'s
  `RuntimeError` guard on object-dtype top-100 columns is unchanged.

## Updated clean checks (confirmatory pass)

- `attach_features_long.py` — strict causal snap (`side="left"-1`), `>=`
  provenance check, `obs_lookup` keyed by strictly-before timestamps only,
  merge key unaffected — independently re-derived from parquet outputs, not
  just re-read from the manifest.
- `assemble_and_label.py` — fail-loud duplicate-key guard ahead of
  `validate="one_to_one"` merge; 0 duplicates currently present in all 6
  atlas years (independently re-checked, not just accepted from the log).
- `data_readiness_gate.py` — timing-unverified disclosure present, correctly
  scoped to the same 3 features flagged previously, correctly non-blocking.
- Row counts, censoring (0 rows in all 6 years), positive rates, and
  `center_join_rate` (1.0 in all 6 years) are unchanged pre-/post-fix,
  confirming the remediation altered only the 56 attach-feature values as
  claimed and did not silently change population size or label definition.

## Updated notes (carried forward, unchanged severity)

- [process] No automated Phase-0 SHA re-verification script — unchanged,
  still a Note, not re-scored.
- [style] `train_and_evaluate_long.py:190-193` redundant conditional —
  unchanged, still a Note.
- [data-integrity] Zero-volume/single-tick bar handling not independently
  re-verified — unchanged, still a Note.
- **[new, Note] [B9 residual]** The 3 `TIMING_UNVERIFIED` features
  (`regime_first_half_vol`, `regime_abs_delta_per_atr_moved`,
  `regime_price_change_atr`) are now disclosed but their timing correctness
  is still unverified. Given this study's own CRITICAL finding demonstrated a
  real boundary-timing defect in the same `ohlcv_est_delta` family, these 3
  features remain a candidate for independent re-verification before any
  deployment decision, notwithstanding that the disclosure remediation itself
  is complete and correctly scoped.

## Final blocking verdict

**PASSES at 0 CRITICAL.** All 3 remediations (1 CRITICAL, 2 WARNING) verified
correct by direct code reading and independently re-derived from the
underlying parquet/JSON artifacts (not merely accepted from the implementer's
self-reported log). No regression found in directionality, split discipline,
target-leakage exclusion, or encoding invariants. The study is clear to
proceed past the look-ahead/timestamp audit gate; the 3 remaining Notes
(process/style/data-integrity) and the restated B9 residual are non-blocking
and carried forward for awareness, not as gating conditions.

---

*Confirmatory re-audit complete. Read-only static analysis plus independent
recomputation from output artifacts. No file other than this audit report was
modified.*
