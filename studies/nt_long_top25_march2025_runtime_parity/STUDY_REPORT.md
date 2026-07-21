# Long TOP25 NT Runtime Parity — March 2025 — INTERIM STATUS

## Adjudication

**NONE ASSIGNED — the study is incomplete.** Phase 2 (feature parity) does not
pass, so no `LONG_MARCH_2025_RUNTIME_PARITY_*` label is claimed and Phases 4–5
were deliberately never run with a threshold.

| Layer | Status |
|---|---|
| MODEL PARITY STATUS | **PARTIAL** — 12/25 features exact; scoring itself proven exact |
| TRIGGER-HARNESS STATUS | **NOT RUN** (Layer B correctly gated behind Phase 3) |
| PRODUCTION-THRESHOLD STATUS | **NOT_SELECTED** (unchanged) |

## What is built and proven

- 7 harness modules; **11/11 tests pass**, including the live `RegimeEngine`
  reproducing the offline 1m regime series **exactly**.
- Frozen-artifact contract gate (model/coefficients/intercept/feature-order
  SHAs) is blocking and passes.
- **Scoring is exact and pre-validated.** Over all 15,234 offline March rows:
  joblib-vs-frozen `5.55e-17`, explicit-formula-vs-frozen `3.89e-16`,
  explicit-vs-joblib `3.89e-16`. Any score divergence in the live run is
  therefore attributable purely to feature divergence — a clean separation.
- Full March Layer A run executed in a real `BacktestEngine`
  (1,542,903 1s + 42,952 1m bars, Feb-15 warmup → Apr-1, 1,400 s).

## Phase 1 — population (strong)

| metric | value |
|---|---:|
| offline eligible | 15,234 |
| live eligible | 15,576 (+2.25%) |
| exact key matches | **15,131 (99.32% of offline)** |
| offline-only / live-only rows | 103 / 445 |
| offline / live / shared regimes | 146 / 148 / 146 |
| regimes with exact checkpoint-index sets | 71 / 146 |

Displacement of symmetric-difference rows: `>30s` 267, `no counterpart` 124,
`±2–5s` 112, `±6–30s` 45. Not yet fully attributed.

## Phase 2 — features (FAILS: 12/25 exact)

Three defects were found and fixed during this session; two classes remain.

**Fixed (evidence-backed):**

1. **One-bar look-ahead.** `_features.update_1s()` ran *before* the tracker
   emitted checkpoints for `T <= ts`, so feature state absorbed a bar at/after
   the observation instant. Offline snaps at
   `searchsorted(ts, obs, 'left') - 1` and snapshots while processing *that*
   bar. Fixed by emitting checkpoints first. **4 → 12 features exact.**
2. **Wrong timestamp to the price snapshot.** Offline passes `bar_ts` (the snap
   bar) to `price_tracker.calculate`; the live code passed the observation
   instant. Signature: `rth_elapsed_seconds` had **0** exact matches with max
   diff exactly 12.0 s (the snap→observation gap). Now exact on 1083/1084.
3. **Wrong ATR for the center family.** The atlas built
   `aligned_price_minus_center_*` with the **running per-bar 1m ATR**, not the
   frozen regime-entry ATR. Proof: with the frozen ATR the *ATR-free* ratio
   `aligned_5m/aligned_15m` matched offline at **3.55e-15 on 100% of rows**
   while the values diverged, and implied `live_atr/offline_atr` ran 0.48–1.09
   (median 0.83) — the price/median arithmetic was already exact, only the
   denominator was wrong. Fixed by passing two ATRs. Center features went
   **0–8 → 996/1084 exact (91.9%)**, max diff 5.31 → 0.95.

**Remaining (not yet fixed):**

| class | features | exact | leading hypothesis |
|---|---|---|---|
| RTH accumulator | `rth_vol_cum` | 22/1084 | minute-boundary flush / `reset_rth` timing differs from the offline `minute_buffer` loop |
| price-level | 5× `rolling_*_signed_distance_atr`, `full_level_envelope_width_atr`, `opening_range_30m_low_*`, `pct_levels_behind_trade` | 894–1078 / 1084 | `update_1m` inputs: offline passes **1s-aggregated** minute OHLC + `prev_close`; live passes the **catalog 1m bar's** OHLC |
| center residual | 3× `aligned_price_minus_center_*` | 996/1084 (91.9%) | residual ATR *timing* (which 1m ATR is current at the observation instant) |

All three `seq_*` features are **exact (0.0)**, consistent with the standalone
pre-flight verification.

## Phase 3 — score

Live-vs-offline probability max abs diff **3.16e-02** (mean 1.32e-03) — i.e.
**FAIL** against the 1e-10 tolerance, but this is entirely inherited from the
Phase 2 feature gaps: `explicit_vs_joblib` is `4.44e-16` (PASS), confirming the
scoring path itself is sound.

## Methodological limitations

This is a **one-month March 2025 smoke test**. It establishes nothing about
annual behaviour and nothing about 2026, which was never touched. No economics,
no PnL claim, no threshold selection. The remaining feature gaps mean the live
scores are **not yet trustworthy** for any downstream use.

## Decision-relevant next step (exactly one)

**Fix an identified parity defect** — specifically the price-level `update_1m`
input mismatch, which accounts for 8 of the 13 remaining failing features. Feed
the live `PriceLevelTracker` the **1s-aggregated** minute OHLC and `prev_close`
(exactly as `attach_features_long.py:157` does) instead of the catalog 1m bar's
own OHLC, then re-run the March window and re-reconcile.

Do **not** broaden to a second month or to Layer B until Phase 2 passes.
