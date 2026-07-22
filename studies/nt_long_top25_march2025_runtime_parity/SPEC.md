# Long TOP25 NautilusTrader Runtime Parity — March 2025 Smoke

## Status

**LAYER A CLOSED — `LONG_MARCH_2025_RUNTIME_PARITY_PARTIAL`.** Phases 0–3 are
executed over full March 2025 in a real `BacktestEngine`
(`results/reconciliation_layerA_v2.json`): Phase 2 **25/25 features exact
(0.0)** and Phase 3 **score exact (2.22e-16)** on 15,131 matched rows. Phase 1
population parity is **99.32%, not exact**, and Phases 4–5 (Layer B) have not
run — hence PARTIAL, not PASS. Production-threshold status remains
**NOT_SELECTED**. See `STUDY_REPORT.md`; the conventions that had to be
reproduced to get here are findings 4 and 5 below.

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

### 4. The offline replay's minute bar is NOT the minute (root cause, measured)

`attach_features_long.py` imports `attach_features.minute_bucket_key` verbatim
— deliberately, "so the CRIT-1 minute-bucketing fix cannot silently drift":

```python
def minute_bucket_key(bar_ts: int) -> int:
    return (bar_ts - 1) // (60 * NS)      # written for CLOSE-labelled bars
```

That rule is correct for bars covering `(ts-1s, ts]`. But the same file's own
header states the raw 1s bars are **OPEN-labelled** (`ts` covers `[ts, ts+1s)`)
— that is the entire justification for its change 3. Applied to open-labelled
bars the bucket becomes `(m-60s, m]`: the synthesized "minute closing at `m`"
holds the bars at `m-59s … m`, **shifted +1 second** from the true minute
`[m-60s, m)`, and its rollover fires at the bar `ts == m+1s`, not `ts == m`.

Consequences the live engine must reproduce:

| | offline | naive live |
|---|---|---|
| minute closing at `m` contains | bars `(m-60s, m]` | bars `[m-60s, m)` |
| rollover fires at bar | `m + 1s` | `m` |
| price levels / RTH accumulators driven by | re-aggregated 1s bars | catalog 1m bar |

**Measured proof** (2025-03-03, first two RTH checkpoints). The offline
reference's `rth_vol_cum` is 1180 at 08:30:05 and 5253 at 08:31:05. Summing raw
1s volume over `(08:29:00, 08:30:00]` gives **1180** and over
`(08:29:00, 08:31:00]` gives **5253** — exact. The true-minute reading gives 706
and 5226, which is precisely what the live run produced.

This is **not** a look-ahead. The newest bar folded in (`ts == m`) covers
`[m, m+1s)`; a snapshot that can see it is taken at a snap bar `S >= m` for an
observation `O > S`, so `m + 1s <= O`. It is a labelling quirk, and it is
causally implementable live.

It also explains the 12 offline-null rows in `rth_elapsed_seconds`,
`rth_vol_cum` and `opening_range_30m_low_developing_*`: at an observation of
exactly 08:30:00 the offline rollover (due at 08:30:01) has not run, so RTH has
not opened yet.

The earlier hypothesis — that the gap was the *values* passed to `update_1m`
(1s-aggregated OHLC vs the catalog 1m bar's) — was **tested and refuted**: over
2025-02-25 → 2025-03-04 the two agree on 7,259 of 7,260 minutes, and catalog 1s
is byte-identical to the raw 1s file. The gap was never the values; it was the
bucket boundary and the rollover position.

### 5. Two RTH rules, deliberately

The offline attach imports `is_rth` from
`CODEX_5_X_run_established_fade.py:146`, which ends RTH at **15:00** Chicago.
The study's decision/fill rule is **15:15**. Both are live now:
`common.is_rth_feature_minute` (features) vs `common.is_rth_minute_of_day`
(population). Collapsing them leaves `rth_vol_cum` populated for 15 minutes
after the offline reference has gone null.

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

## Live engine ownership (the contract that had to change)

| concern | owner | driven by |
|---|---|---|
| regime series (`close_ts <= t`) | `RegimeEngine`, `strategy._on_1m` | the **1m** feed |
| median-center / `seq_*` | `MedianCenterTracker` | 1s bars + the immediate regime int |
| minute buckets, price levels, RTH + regime accumulators | `LongFeatureEngine` | the **1s** stream, `minute_bucket_key` |
| running 1m ATR for center features | `strategy._center_atr_at_snap` | pinned to the snap bar |

`LongFeatureEngine` exposes **no 1m update path at all** — that is enforced by a
test. The 1m feed reaching the price/RTH trackers is the defect this study
found, and removing the entry point is what stops it recurring.

## Phase results

| phase | status | evidence |
|---|---|---|
| 0 offline reference | COMPLETE | 15,234 rows / 146 regimes, `offline_reference_manifest.json` |
| 1 candidate population | **PARTIAL — 99.32%** | 15,131 matched; 103 offline-only / 445 live-only |
| 2 feature parity | **PASS — 25/25 exact (0.0)** | `feature_parity_summary.csv`, 15,131 rows, null masks agree |
| 3 score parity | **PASS — 2.22e-16** | all four comparisons, tol 1e-10 |
| 4 trigger parity | **NOT RUN** | gated behind Phase 3 + the H4/E4 warning below |
| 5 order/fill/trade parity | **NOT RUN** | ditto |

Run of record: `results/run_manifest_layerA_v2.json` /
`reconciliation_layerA_v2.json` (2,023,875 1s + 56,751 1m bars, 831 s).
Tests: **16/16**, including 5 convention tests that were mutation-checked —
reverting `minute_bucket_key` to `ts // 60s` fails three of them.

### Phase 1 — what the gap actually is

Live and offline agree **exactly on where every candidate stream starts** and
diverge on where it **ends**; live always runs longer:

| regime | offline cp_idx | live cp_idx | live-only |
|---|---|---|---|
| 1741722660 | 57..106 | 57..**250** | 107..250 |
| 1742240100 | 186..298 | 186..**358** | 299..358 |
| 1742413740 | 72..130 | 72..**199** | 131..199 |

Five regimes supply 382 of the 445 live-only rows; the 124 `no counterpart`
rows are exactly the 2 live-only regimes. So this is **not** an
established-gate reproduction problem — the gate is exact. It is a
stream-*termination* difference, and that is the whole remaining question.

### Waterfall caveat

`population_waterfall_live_layerA_v2.csv` was **regenerated from the ledger**
after the run: the run's own counters were not emit-window gated (audit
WARNING 1, now fixed in `strategy.py`). Corrected March-only stages: raw
161,549 → established 54,851 → decision_rth 15,576 → eligible 15,576.

Two of the six stages are **non-informative by construction** and must not be
read as evidence: `valid_fill` is hardcoded `True`
(`candidate_tracker_long.py:136`) and `fill_rth` is assigned `= decision_rth`
(:199). Only raw → established → decision_rth/eligible actually filter.

## Audit gate

`lookahead-auditor`, post-rewire: **0 CRITICAL / 2 WARNING / 3 NOTE**
(`audit/audit.md`). The `S >= m` non-look-ahead argument for the shifted minute
bucket was re-derived independently against the code across the no-gap case,
stream gaps, the first bucket after warmup, a missing first-second-of-minute,
and session edges — and **survived**, including one constructed counter-example
(observation coinciding with the rollover trigger bar) that resolved correctly.
The auditor found the live guarantee is `S >= m + 1s`, strictly stronger than
claimed.

The original bar was 0 CRITICAL / 0 WARNING. That bar is **met for Layer A** and
**not yet met for Layer B**:

- WARNING 1 (waterfall scope) — **FIXED**, artifact regenerated.
- WARNING 2 (H4/E4: `_enter`/`_check_stop` book the snap price and the exact
  stop level, not NT-realized fills) — **OPEN, and blocking Phase 4**. Inert
  today: every run is `trigger_threshold=-1.0`, 0 triggers, 0 trades, so it
  cannot have touched any Layer A number. It must be closed before Layer B runs.
- NOTE 2 — a checkpoint due exactly at a regime-flip instant is dropped, not
  mis-evaluated. Undercount, not causality; a candidate contributor to Phase 1.

## Adjudication

**`LONG_MARCH_2025_RUNTIME_PARITY_PARTIAL`.**

PASS was not claimed: Phase 1 is 99.32%, not exact, and Phases 4–5 never ran.
What *is* established is narrow and strong — on the 15,131 rows both pipelines
agree exist, the live NT event loop reproduces the frozen offline pipeline
exactly (features `0.0`, probability `2.22e-16`).

Production-threshold status remains **NOT_SELECTED**. No economics, no PnL, no
2026 data. One month.

### Next step (exactly one)

Attribute the **stream-termination** difference behind Phase 1 — why offline
candidate streams end earlier than live ones in the five regimes that dominate
the gap. Do not open Layer B until that is closed or explicitly accepted, and
not before WARNING 2 is fixed.
