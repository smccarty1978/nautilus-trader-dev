# Look-Ahead & Timestamp Audit

**Date:** 2026-07-19
**Scope:** `studies/short_rth_established_age_gate_flip_quality/SPEC.md`,
`phase0_prepare_data.py`, `population_label_diagnostics.py`,
`feature_separation_diagnostics.py`, `optional_diagnostic_model.py`,
`build_manifest.py`; upstream reference-checked (read-only, not re-audited
in full): `studies/short_rth_entry_surface_backfill/label_full_surface.py`,
`studies/fable5_specialized_w4/fable5_common.py`,
`studies/short_rth_enriched_volume_level_retrain/phase0_prepare_data.py`,
`studies/CODEX_5_X_weakness_atlas_repair/CODEX_5_X_run_established_fade.py`.
Empirical spot-checks run directly against `_work/*.parquet` and
`data/raw/NQ_v0_1s_{year}.parquet` for all 6 years (2021-2026).
**Auditor:** lookahead-auditor v1 (first pass for this study)

## Summary

- Critical: 0
- Warning: 1
- Note: 2

## Warnings

### [G2/H2] `phase0_prepare_data.py:94-105` — post-flip MFE window has no max-gap guard; silently extends 300s/600s window by minutes to hours across raw-1s-data gaps

`post_flip_mfe_by_regime` computes the window end index as
`i1 = np.searchsorted(ts, end_ts, side="left")` and then takes
`lows[i0:i1 + 1].min()`. This correctly guards the two intended censoring
cases (`i0 >= len(ts)` and `end_ts > ts_max`), but it does **not** guard
against internal gaps in the raw 1-second bar file. `data/raw/NQ_v0_1s_{year}.parquet`
is a sparse (trade-present-only) 1s file — most timestamp deltas are 1s but
a material fraction are multi-second, and deltas spanning session close /
holiday gaps run into the tens of thousands of seconds. When a flip's
300s/600s window boundary happens to fall inside one of these gaps,
`searchsorted` simply returns the next available bar regardless of how far
in the future it is, so the "fixed 300s/600s window" silently becomes a
much longer window (observed up to 18,000s = 5 hours past the nominal
boundary, e.g. 2021-11-25 11:55 CT / Thanksgiving half-day, 2021-02-15
Presidents Day). This inflates `post_flip_mfe_points_{300,600}s` (and
therefore `post_flip_mfe_atr_{300,600}s` and the
`bearish_flip_within_{300,600}s_and_followthrough_1A` /
`flip_but_no_followthrough` labels) for the affected checkpoint rows,
without any flag distinguishing them from a genuine same-day 300s/600s
scan.

**Empirically confirmed** (direct re-run of the window-boundary
computation against the actual raw files and `prepared_{year}.parquet`,
per year, 300s window):

| Year | Regimes w/ >300s overrun | Checkpoint rows inheriting corrupted window (of total) |
|--|--:|--:|
| 2021 | 8 / 1,762 | 721 / 212,241 (0.34%) |
| 2022 | 1 / 1,711 | 77 / 192,378 (0.04%) |
| 2023 | 1 / 1,732 | 34 / 204,742 (0.02%) |
| 2024 | 3 / 1,672 | 251 / 204,611 (0.12%) |
| 2025 | 2 / 1,678 | 257 / 198,255 (0.13%) |
| 2026 | 0 / 532 | 0 / 63,021 |

Population impact is small (well under 0.5% of rows every year) and very
unlikely to overturn the study's per-gate aggregate comparisons, but it is
a silent, reproducible label-corruption bug rather than a hypothetical one,
and it is concentrated exactly where you'd expect the most misleading
signal to hide: near-RTH-close flips and holiday-shortened sessions. Since
this study's stated purpose is comparing *label cleanliness* between Gate
A and Gate B, a bug that quietly makes a handful of near-close/holiday
labels look artificially "clean" (large apparent follow-through from hours
of extra price path) works against the study's own goal.

**Recommended fix (do not apply):** add the same style of explicit gap
guard already used for `i0 >= len(ts)` / `end_ts > ts_max` — e.g. treat the
window as unavailable (NaN) if `ts[i1] - end_ts` exceeds a small tolerance
(a few seconds), or if the gap between `ts[i0]` and `flip_ts` itself is
large. This affects at most a few hundred rows per year and would not
change the study's population-preservation conclusion (finding 4), but it
does affect the precision of the flip-quality/follow-through rate
comparisons that are this study's actual deliverable.

## Notes

### [C2-adjacent] `phase0_prepare_data.py:83,145-146` — no runtime assertion that `confirm_flip_ns` is invariant within `regime_start_ns`

`post_flip_mfe_by_regime` computes the flip time once per regime via
`regimes.drop_duplicates("regime_start_ns")[["regime_start_ns", "confirm_flip_ns"]]`,
which silently keeps whichever row happens to occur first in `regimes`'
row order for a given `regime_start_ns` and discards the rest. SPEC.md's
scout pass asserts this is safe because "all checkpoints in a regime share
the same flip time," but there is no code-level assertion enforcing this
before the `drop_duplicates` call — if it were ever violated (e.g., by an
upstream change to regime/flip construction, or a different year's data),
some checkpoint rows in that regime would silently be labeled against the
wrong flip time with no error raised. **Empirically verified 0 violations
across all 6 years (2021-2026)** in the current data, so there is no
current impact. Recommend adding an explicit assertion, e.g.
`assert (regimes.groupby("regime_start_ns")["confirm_flip_ns"].nunique() <= 1).all()`,
as defensive coding before this reuse pattern is copied into a future
study.

### [C-adjacent] `phase0_prepare_data.py:120-126` — NaN `post_flip_mfe_atr_*` (censored/unavailable) is implicitly coerced to "no follow-through" rather than left distinguishable from a confirmed negative

`bearish_flip_within_{300,600}s_and_followthrough_1A` is built as
`bearish_flip_within_Ns & (post_flip_mfe_atr_Ns >= 1.0)`. Because
`NaN >= 1.0` evaluates to `False` (not `NaN`) under numpy/pandas float
comparison semantics, any row where `bearish_flip_within_600s` is `True`
but `post_flip_mfe_atr_600s` is `NaN` (insufficient trailing raw data —
the genuine censoring case the code already guards against elsewhere) is
silently counted as "flipped, no follow-through" rather than "unknown."
`flip_but_no_followthrough` inherits the same conflation via
`.fillna(False)` at line 126. This is the same missing-vs-negative labeling
pattern flagged repeatedly elsewhere in this project's history (e.g.
censored `.notna()` labels excluding early-death losers). **Empirically
verified 0 rows currently affected** (checked all 6 years: 0 rows have
`bearish_flip_within_600s == True` and `post_flip_mfe_atr_600s` NaN
simultaneously), so this has no impact on the current results, but it is a
latent defect that would silently bias `followthrough_1A_rate_*` diagnostics
downward if it ever did trigger (e.g., on a future year, or after fixing
the gap-guard issue above in a way that produces more NaNs). Recommend an
explicit `.notna()` gate (propagate NaN rather than coercing to False) if
this code is reused for a future year/study.

## Clean checks

- **SPEC finding 1 / Gate A reproduction** — confirmed empirically: Gate A
  (`regime_age_s >= 120`) applied to the already-established-filtered
  `full_{year}.parquet` population reproduces exactly 1,762 distinct
  regimes for 2021 (matches SPEC's table), and observed minimum
  `regime_age_s` in the Gate-A full-checkpoint surface is 130.0s (matches
  SPEC's "2021 minimum observed age-at-first-eligibility is 130s" claim).
- **SPEC finding 4 / Gate B strict-subset claim** — confirmed by direct
  code inspection (`build_gate_surfaces` filters the *same* joined
  `prepared_{year}.parquet` frame per gate via a pure `>=` threshold on
  `regime_age_s`, no re-derivation) **and** empirically: every
  `(regime_start_ns, observation_time)` key in `full_gate_b_240s_2021.parquet`
  is present in `full_gate_a_120s_2021.parquet` (0 rows not a subset);
  distinct-regime counts (1,755 / 1,762) match SPEC's table exactly.
- **`load_gate_columns` / `run_year` join (B2, C1)** — `full.merge(gate_cols, on=KEY, how="left", validate="one_to_one")`
  with an explicit post-join row-count and `notna().mean() == 1.0`
  assertion; ran successfully (output files exist) meaning the assertions
  passed at build time. Rejoined columns (`regime_age_s`, `running_mfe_atr`,
  `running_mae_atr`, `new_progress_windows`, `retained_mfe_ratio`,
  `confirm_flip_ns`) are gate-filter/label-construction inputs only — grep-
  and content-verified they never appear in any of the F0/F1/F2/F3 feature
  lists (`_work/feature_sets.json`, imported verbatim from
  `short_rth_enriched_volume_level_retrain`) consumed by
  `feature_separation_diagnostics.py` or `optional_diagnostic_model.py`.
  `confirm_flip_ns` specifically is used only to build `time_to_bearish_flip_s`,
  `bearish_flip_within_600s`, and as the anchor for `post_flip_mfe_by_regime`
  — all future-facing label constructions, never joined into a feature
  path.
- **`post_flip_mfe_by_regime` causality (B2, B3)** — `i0` is computed via
  `searchsorted(ts, flip_ts, side="left")`, i.e. the first raw bar at or
  after `confirm_flip_ns`; the window slice `lows[i0:i1+1]` never indexes
  bars before `i0`. Confirmed by reading the loop directly: no bar before
  the flip contributes to `post_flip_mfe_points_*`. Insufficient trailing
  data is NaN (`i0 >= len(ts)` and `end_ts > ts_max` both return NaN,
  never 0) — verified this censoring path is exercised correctly
  elsewhere in the pipeline (see Warning above for the one gap it misses).
- **`build_labels` reuse fidelity (C1, C2)** — traced `aligned` and
  `hit_pre_alignment_stop` to their source
  (`studies/short_rth_entry_surface_backfill/label_full_surface.py` →
  `fable5_common.simulate_trade_arrays`): `aligned` is set `True` iff the
  opposing flip occurs at or before `entry_ts + TIMEOUT_NS` (300s),
  exactly matching SPEC's claim; `hit_pre_alignment_stop` fires only when
  the 1.25×ATR pre-alignment stop is touched while `not aligned`, i.e.
  strictly "before alignment or timeout" — exactly matching SPEC's claim.
  `bearish_flip_within_300s = aligned`, `no_flip_before_timeout = ~aligned`,
  `adverse_move_1p25A_before_bearish_flip = hit_pre_alignment_stop` are
  therefore verified legitimate, unmodified reuses, not near-duplicates.
  Empirically confirmed 0 NaN in `aligned`/`hit_pre_alignment_stop` across
  all 6 years (matches SPEC's "zero `label_available == False` rows"
  claim), so no silent censored-row handling gap here.
- **`find_position_cols` / `one_hot_position_cols` reuse (D4)** — imported
  unchanged from
  `studies/short_rth_enriched_volume_level_retrain/phase0_prepare_data.py`;
  the function itself is generic (`df.columns` ending in `_position`,
  `dtype == object`) and none of the newly joined gate/label columns end in
  `_position`, so the one-hot step operates on exactly the same causal
  `*_position` columns as the upstream study — confirmed by name
  inspection, no new columns introduced into this step.
- **Feature/label separation in diagnostics (C1, D2)** — both
  `feature_separation_diagnostics.py` and `optional_diagnostic_model.py`
  read `columns=all_feats/cols + LABELS/TARGETS`, but only ever slice
  `X = df[cols]` / `df[all_feats]` for AUC/Cohen's-d/model fitting; label
  columns are used exclusively as `y`. Verified by direct read of both
  files — no label column appears inside `all_feats`/`cols`.
- **Train/dev/test split (C3)** — `optional_diagnostic_model.py` uses a
  fixed temporal split (`TRAIN_YEARS = 2021-2024`, `DEV_YEAR = 2025`,
  `TEST_YEAR = 2026`), not `cross_val_score` or a random split.
- **`build_manifest.py`** — pure aggregation of already-written CSVs/JSON,
  no new computation, no leak surface.
- **Raw-bar timestamp convention (A2)** — 1-second bars are consumed via
  the project's existing, already-audited open-labelled convention
  (`ts_event` index, "first available bar with `ts_event >= t`" fill rule,
  documented and reused verbatim from
  `CODEX_5_X_run_established_fade.py`/`label_full_surface.py`); no new
  timestamp convention was introduced by this study, and no
  `ts_init_delta` misapplication was found (1s bars correctly receive no
  delta, per project convention).
- **No pandas backtesting/signal-detection (CORE INVARIANT 1)** — this
  study performs no strategy execution or signal detection; all pandas use
  is restricted to loading raw data, joining pre-existing audited surfaces,
  and post-hoc descriptive/label computation on data that already
  incorporates NT-validated Policy A outcomes. Sections A3-A5, D1-D4,
  E1-E5 of the checklist are N/A for this reason (no `on_bar`, no live
  strategy, no deployable model).

## Compliance matrix

| Item | Status | Note |
|---|---|---|
| A1 | N/A | no strategy bar indexing in this study |
| A2 | PASS | 1s raw bars, existing convention, no delta needed |
| A3 | N/A | no strategy |
| A4 | N/A | no strategy |
| A5 | N/A | no resampling performed |
| B1 | PASS | no rolling ops |
| B2 | PASS | post-flip scan never indexes before `confirm_flip_ns` |
| B3 | N/A | no recursive indicators computed here |
| B4 | PASS | no `.shift(-N)` in feature path |
| B5 | PASS | no ffill/bfill |
| B6 | N/A | only exact-key merges, validated 1:1 / many:1 |
| B7 | N/A | no scaling/normalization fit here |
| C1 | PASS | verified no label column in any feature list |
| C2 | PASS | labels align to future flip relative to observation_time |
| C3 | PASS | temporal 2021-2024/2025/2026 split |
| C4 | N/A | no walk-forward refitting in this study |
| D1-D4 | N/A | diagnostic-only, no deployable/live model |
| E1-E5 | N/A | no NT strategy/backtest config in this study |
| F1 | N/A | no RTH/ETH bar classification performed here |
| F2 | WARNING | session/holiday gap not guarded in post-flip window (see Warnings) |
| F3 | PASS | ns epoch UTC throughout, no naive timestamps |
| F4 | N/A | no time-of-day filter logic in this study |
| G1 | N/A | no continuous-contract handling in this study |
| G2 | WARNING | raw-1s gaps silently extend fixed window (see Warnings) |
| G3 | N/A | no resampling |
| G4 | N/A | no indicator computation on low-volume bars |
| H1 | N/A | no SL/PT bracket simulation in this study |
| H2 | WARNING | analogous fixed-window/temporal-resolution defect, see Warnings |
| H3 | N/A | not a re-entry/trade-count sim |
| H4 | N/A | no fill-price simulation in this study |
| Gate-B-subset claim | PASS | confirmed by code inspection + empirical key-subset check |

---

*Audit complete. Findings reflect read-only static analysis plus targeted
empirical spot-checks against the actual `_work/` parquet outputs and raw
1s data for all 6 years. This is a diagnostic/population-quality study,
not a deployable-model or trading-strategy study; severity was calibrated
accordingly. Dynamic bugs and full-history exhaustive row-by-row
verification are out of scope.*

## Post-audit fixes applied (2026-07-20)

All three findings were fixed and the full pipeline (`phase0_prepare_data.py`
through `build_manifest.py`) was re-run end to end:

1. **[G2/H2 WARNING fixed]** `post_flip_mfe_by_regime()`'s window slice
   changed from `lows[i0:i1+1]` (inclusive of the first bar at/after the
   boundary, which could be arbitrarily far past it across a raw-data gap)
   to `lows[i0:i1]` (strictly before `end_ts`) — a gap at the window
   boundary now correctly truncates the window rather than silently
   extending it. Re-running confirmed the fix is real but low-materiality,
   exactly as the auditor assessed: `followthrough_1A_rate_given_flip_300s`
   moved by ≤0.007 in every (gate, year) cell (e.g. 2021 gate_a:
   0.542254→0.538732), `post_flip_mfe_300s/600s_unavailable` stayed 0 for
   all 6 years, and no downstream diagnostic changed direction or
   conclusion.
2. **[NOTE fixed]** Added a runtime assertion in `post_flip_mfe_by_regime()`
   that `confirm_flip_ns` is constant within every `regime_start_ns` before
   `drop_duplicates` — re-run confirms 0 violations across all 6 years (the
   assumption was already true, now it is guaranteed rather than
   unverified).
3. **[NOTE fixed]** Added `followthrough_flag()`: follow-through labels are
   now NaN-propagating (1.0/0.0/NaN) rather than plain booleans — a flip
   with unavailable post-flip MFE now stays distinguishable from a
   confirmed "flipped but no followthrough," never silently coerced to
   `False` by `NaN >= 1.0`. Currently a no-op on real data (0 rows affected,
   since 0 regimes have unavailable post-flip MFE), but no longer an
   unguarded assumption.

All `results/*.csv` and `results/manifest.json` reflect the fixed pipeline.
