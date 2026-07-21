# Long TOP25 NautilusTrader Runtime Parity — March 2025 Smoke

## Status

**IN PROGRESS.** Phase 0 (offline reference) is complete and **all three**
blocking feasibility unknowns are resolved with evidence — including exact
offline-vs-live equivalence for every one of the 25 features. Phases 1–5 (live
NT run and reconciliation) are **not yet executed** — no parity claim is made
and no adjudication label is assigned.

## Objective

Determine whether the live NT event loop causally reproduces the frozen offline
long-model pipeline for `long_bullish_flip_top25` over March 2025 only:
candidate population → features → vector → score → trigger → orders → fills →
trades. Runtime parity, **not** economics.

## Frozen model contract (verified)

| Item | Value |
|---|---|
| `model_id` | `long_bullish_flip_top25` (FINAL, logistic regression) |
| target | `bullish_regime_flip_within_300s` |
| `model.joblib` sha256 | `ccad9a9b4441a5891ea61bd263ceaedfead42dcd2d5fb2149cdbf2da9e1cc789` |
| `feature_order` sha256 | `d601abe692c78c0471088b41cae1fe80bbb918bbe7e7af067ddb45e7b0ce45bf` |
| `coefficients.csv` sha256 | `5d128d4f1e59ecceb4e8aa8f8166a6e2cd5979546809fa46078c7b3ff3d71778` |
| threshold status | **NOT_SELECTED** |

Not retrained, not refit, not reordered. Layer A (threshold-free score parity)
precedes any Layer B trigger harness, whose threshold must be labelled
`PROVISIONAL_PARITY_HARNESS_ONLY`.

## Phase 0 — offline reference (COMPLETE)

`_work/offline_reference_march_2025.parquet` + `results/offline_reference_manifest.json`.

- **15,234 candidate rows / 146 bearish regimes**, all RTH, all
  `prevailing_direction == -1`, `entry_direction == +1`.
- Sliced on **America/Chicago** boundaries (2025-03-01 00:00 CST →
  2025-04-01 00:00 CDT = 2025-03-01 06:00 UTC → 2025-04-01 05:00 UTC), never UTC
  calendar days. Both windows recorded in the manifest.
- Rows/regime: min 1, median 88.5, max 321. Positive rate 0.2382.
- Frozen scores joined 1:1 from the artifact's own `score_reference_2025.parquet`;
  range 0.00060–0.72531, mean 0.23824. Zero rows lack a score.
- Only 3 features carry nulls (12 rows each): `rth_elapsed_seconds`,
  `opening_range_30m_low_developing_signed_distance_points`, `rth_vol_cum`.

Recorded honestly: the prepared artifact stores **only surviving rows**, so the
upstream waterfall stages (raw → established → decision_rth → fill_rth →
valid_fill) are **not recoverable offline**. The live run must emit all stages;
offline supplies the terminal `eligible` count only. Phase 1 reconciliation is
therefore terminal-count + per-regime + checkpoint-index-set based.

## Resolved feasibility findings (the two things that could have killed this)

### 1. All 25 features are live-computable — but not by the short-side engine

Long TOP25 shares only **19/25** features with short TOP25. The 6 long-only
features are all regime-center/sequence family:
`aligned_price_minus_center_{5m,15m,30m}`, `seq_8r_mean_retracement`,
`seq_12r_mean_retracement`, `seq_5r_max_overlap`.

The short smoke's `ReducedFeatureEngine` instantiates only `OHLCVDeltaTracker` +
`PriceLevelTracker` and implements **none** of these. However
`features/trackers/median_center.py::MedianCenterTracker` does emit all six —
the `seq_*` names are built by f-string (`prefix = f"seq_{K}r_"`, line 457),
which is why a literal grep finds nothing. The long engine therefore needs
**three** trackers, with `PriceLevelTracker(direction=+1)` (the single
direction-flipping feature, `pct_levels_behind_trade`, is rank 25 and present).

`MedianCenterTracker.calculate()` computes
`aligned_* = current_regime * (close − median)/atr`, so passing the prevailing
regime direction (−1) makes the center features auto-orient bearish — consistent
with the directionality contract proved in the top-100 study.

### 2. Registry-vs-reality: two implementations of the same 6 features

`features/registry.py` declares all six as
`implementation = features.trackers.median_center.MedianCenterTracker`. **But the
frozen model was trained on values produced by a different code path** — the
offline atlas used `build_median_centers.build_median_centers_df` (pandas
`rolling`) and `build_regime_sequence.compute_sequence_features`, not the
tracker. The registry entry is an equivalence *claim* that had never been tested.

**Tested this session, and it holds for the median-center definition.**
Reconstructing the centers directly from catalog 1s bars
(`close.rolling(N, min_periods=1).median()`, snapped at
`searchsorted(ts, obs, side="left") − 1`) and comparing the ATR-free ratio
`aligned_5m / aligned_15m` against the frozen offline values over
2025-03-03 → 2025-03-07:

```
rows compared        3,116
max abs ratio diff   7.105e-15      (machine precision)
median abs diff      0.000e+00
fraction < 1e-9      1.0000
```

This simultaneously confirms (a) the offline center definition, (b) that
`MedianCenterTracker`'s `np.median(prices_1s[-N:])` is the same definition, and
(c) that the offline reference itself snaps **strictly causally** (`side="left"`),
matching the contract this study must enforce.

### 3. `seq_*r_*` equivalence — tested and **PASS (exact)**

`implementation/verify_seq_features.py` streams the **real** `MedianCenterTracker`
over the same raw 1s parquet the atlas used (`data/raw/NQ_v0_1s_2025.parquet`,
not the NT catalog, which differs on roll days), driven by the offline 1m regime
series, and compares to the frozen values at every March observation:

| feature | live vs frozen | offline vs frozen | live vs offline |
|---|---|---|---|
| `seq_8r_mean_retracement` | **0.0** | 0.0 | 0.0 |
| `seq_12r_mean_retracement` | **0.0** | 0.0 | 0.0 |
| `seq_5r_max_overlap` | **0.0** | 0.0 | 0.0 |

4,141 rows, 684,027 bars, 1,348 offline regimes. `max_abs_diff = 0.0` exactly on
all nine comparisons. The `offline_vs_frozen == 0.0` column is the control: it
proves the offline reproduction is bit-exact to what produced the training data,
so the live column is a real result and not a self-comparison.

**All 25 long TOP25 features are therefore proven live-computable.**

### The costly detail this uncovered (two causal conventions, easily conflated)

The first run **FAILED** on all three features (100% of rows, mean abs diff
~1.24). The defect was in the *test driver*, not the tracker. Mapping the 1m
regime series onto 1s bars must use `searchsorted(close_ts, t, side='right') - 1`
— the regime of the last 1m bar with `close_ts <= t`. The `<=` is **not**
look-ahead: a 1m bar with `close_ts == T` covers `[T-60s, T)` and is complete at
`T`, while the 1s bar at `ts_event == T` covers `[T, T+1s)`. It also matches the
offline slicer, which puts the bar at `ts == start` in the NEW regime.

Using the strict **feature-snap** rule (`ts_event < observation_time`,
`side='left' - 1`) for the *regime mapping* shifts every regime window one bar
late — median `end_time` offset exactly 1.000 s — which changes `start_price`,
hence `MFE`/`MAE`/`net_aligned_move`, which the retracement ratios amplify.
Diagnostic signature: **direction matches 100% and regimes align 1:1, but
boundaries are offset ~1 s**. The NT strategy must keep these two conventions
distinct.

Incidental: `MedianCenterTracker.completed_regimes` is `deque(maxlen=300)`, so a
live-vs-offline regime *count* gap (300 vs 1,348) is expected and harmless —
300 is far more than `seq_12r` needs.

## Causality contract

1s bars before coincident 1m bars via `add_bars_causal_order()`. At every
observation `latest_source_ts_used < observation_time` — equality disallowed.
`searchsorted(..., side="right") − 1` is forbidden; `side="left") − 1` is the
contract (independently reconfirmed above against the frozen reference).

## Population mirror

Fork `nt_reduced_f3_top25_population_parity_smoke/candidate_tracker.py`
(read-only source; it is being actively modified by concurrent work, so it is
**forked, not imported**, with its source SHA recorded) with exactly these
changes, matching `build_surface_long.py`:

- open a candidate stream when `new_direction == -1` (not `+1`);
- `current_mfe = (flip_close − lowest_low) / atr` (bearish-favorable);
- `current_mae = (highest_high − flip_close) / atr`;
- `current_pnl = −1 × (price − flip_close) / atr`.

Established filter thresholds unchanged (age ≥ 120 s, MFE ≥ 1.0 ATR,
≥ 2 progress windows, retained ratio ≥ 0.5, 5 s grid, 1800 s timeout).

## Warmup

March candidates require prior state (`seq_12r` needs 12 completed regimes;
`rolling_60m`, `prior_day_*`, 1800 s windows). Bars will be loaded from
**2025-02-01** with candidate emission gated to the March Chicago window; the
exact loaded range goes in `run_manifest.json`.

## Remaining phases (not executed)

1. Candidate-population parity (live ledger + reconciliation, displacement buckets).
2. Feature parity (per-feature summary; `seq_*` highest risk).
3. Logistic score parity — joblib vs explicit `intercept + Σ(coef·x)`, tol 1e-10.
4. Provisional trigger parity (`PROVISIONAL_PARITY_HARNESS_ONLY`).
5. Order/fill/trade parity — fixed 1.25×ATR stop frozen at entry, never trailed;
   exit on stop or opposing flip only.

Then: focused tests, `lookahead-auditor` to **0 CRITICAL / 0 WARNING**.

## Adjudication

`LONG_MARCH_2025_RUNTIME_PARITY_PASS` | `..._PARTIAL` | `..._FAIL` — **none
assigned yet.** Production-threshold status remains **NOT_SELECTED**.
