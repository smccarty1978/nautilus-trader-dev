# Long-Side Top-50 / Top-25 Pure-Flip Reduced-Feature Training

## Primary decision

Can the mirrored long-side bullish-flip signal preserve most of the top-100
signal using only the top 50 or top 25 ranked raw features? The goal is **not**
to beat top-100 — it is to find the **lightest** model that preserves enough
signal to be worth carrying toward NT live-scoring parity.

Lightweight offline reduced-feature training only. **No NautilusTrader, no
MBP-1, no surface rebuild, no trade economics, no entry/stop/exit/threshold
optimization.**

## Inputs (all read-only)

| Input | Path | Verification |
|---|---|---|
| Frozen ranking | `studies/runtime_constrained_f3_feature_reduction/results/top_100_raw_feature_columns.csv` | `sha256 = 6c6ceba7…` reproduced ✅ |
| Ordered top-100 list | derived, ascending `rank` | `sha256 = f2a6db0b…` reproduced ✅ |
| Strict-causal prepared data | `studies/long_rth_mirrored_surface_top100_training/_work/prepared_long_{year}.parquet` | row counts + per-year SHA + strict-causality re-verified ✅ |

**No rebuild was required.** All six prepared years exist, row counts match the
brief exactly (train 682,952 / dev 163,397 / test 52,488), and the corrected
bar-snap convention `latest_source_ts_used < observation_time` was independently
re-verified from the attached parquet: **min gap exactly 1,000,000,000 ns, zero
rows at-or-after `observation_time`, all six years.**

### List-hash recipe (recorded to remove ambiguity)

`ordered_*_feature_list_sha256 = sha256("\n".join(names) + "\n")`. This recipe is
fixed by the prior top-100 study; it is *proved* correct here by reproducing
`f2a6db0b…` from the source CSV **before** any reduced list is hashed, so the
TOP50/TOP25 hashes are commensurable with the frozen one.

## Feature sets (Phase 0 — frozen)

Constructed as **exact prefixes** of the frozen ranked top-100. No re-ranking, no
long-side importance used, no 2025/2026 signal consulted.

| Set | n | ordered list sha256 | exact prefix |
|---|---:|---|---|
| TOP100 | 100 | `f2a6db0b6453433ccc1970255808c940133d1530ff4aa907339966c8c4f37992` | — (frozen source) |
| TOP50 | 50 | `5a2b1a70ebaff75ef70cccfd5337059b840b882eb6bb996635d9d5c1b4ac9978` | ✅ |
| TOP25 | 25 | `d601abe692c78c0471088b41cae1fe80bbb918bbe7e7af067ddb45e7b0ce45bf` | ✅ |

TOP25 is additionally verified to be an exact prefix of TOP50.

### Family composition — the ranking is not family-ordered

| Set | center/slope/alignment | ohlcv-delta | price-level | timing-unverified |
|---|---:|---:|---:|---:|
| TOP100 | 44 | 29 | 27 | 3 |
| TOP50 | 17 | 17 | 16 | 1 |
| TOP25 | 6 | 9 | 10 | **0** |

Two consequences worth stating up front:

1. **Truncation is not family-neutral.** In TOP100 the center/slope family
   carried the largest aggregate importance, yet it is the *least* represented
   family in TOP25 (6 of 25). The reduced sets are therefore a genuine test, not
   a relabelling — TOP25 keeps the highest-ranked center features
   (`aligned_price_minus_center_{15m,30m,5m}`) but drops 38 of 44.
2. **TOP25 is the cleanest set on provenance.** All three inherited
   `TIMING_UNVERIFIED` features (`regime_first_half_vol`,
   `regime_abs_delta_per_atr_moved`, `regime_price_change_atr`) rank outside the
   top 25; only one survives into TOP50. If TOP25 holds up, it removes a
   disclosed residual rather than carrying it forward.

### Directionality contract still applies

`pct_levels_behind_trade` — the single genuinely direction-normalized feature in
the entire top-100 — ranks **25**, so it is present in all three sets. The
mirrored `direction=+1` treatment established and code-proved by the top-100
study (10,253,579 excursion checks, 0 failures) is therefore fully inherited and
unchanged; this study introduces no new directional surface area.

## Target

`bullish_regime_flip_within_300s` — unchanged, reused as built. `1` = the current
bearish RTH regime flips bullish within 300 s after `observation_time`. No stop,
timeout, PnL, or trade-outcome label is constructed or consulted.

## Split discipline

Train 2021–2024 · dev/select 2025 · sealed test 2026. 2026 is used for evaluation
and decision labelling **only** — never for feature selection, model selection,
hyperparameters, thresholds, calibration refit, or target design. Calibration
(`isotonic`, `sigmoid`) is fit on 2025 exclusively via
`CalibratedClassifierCV(FrozenEstimator(...))`.

## Models

Per feature set: regularized logistic regression (median-impute → standardize →
L2 `C=1.0`) and `HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05,
max_iter=200, random_state=42)`. `fit_logistic` / `fit_gbt` are imported
**verbatim** from `short_rth_enriched_volume_level_retrain/train_and_evaluate.py`
with `assert RANDOM_STATE == 42` before any fit — the identical functions the
top-100 study used. No model zoo, no deep learning, no expanded search.

Selection: **2025 AUC only**, 2025 average precision as tie-break.

TOP100 is **re-fit inside this same harness** rather than transcribed, so the
comparison is like-for-like; it must reproduce the prior study's 0.6682 / 0.6512.

## Gates

**Minimum viable:** 2025 AUC ≥ 0.63 · 2026 AUC ≥ 0.62 · 2025 lift ≥ 1.70× ·
2026 lift ≥ 1.70× · 2026 decile curve not inverted · every 2026 monthly AUC > 0.58.

**Strong preservation vs top-100:** 2025 AUC within 0.015 · 2026 AUC within
0.020 · 2025 top-decile flip within 5 pp · 2026 top-decile flip within 5 pp ·
every 2026 monthly AUC > 0.60.

**Preference order:** TOP25 strong → TOP50 strong → (TOP25 viable but TOP50
materially better) → TOP50 → TOP100. Never selected on 2026.

## Benchmarks

- TOP100 long (prior, strict-causal): 2025 AUC 0.6682 / 2026 0.6512; top-decile
  flip 51.1% / 53.7%; lift 1.94× / 1.91×.
- Short-side bearish-flip, **context only**: ≈0.671 / 0.670, flip ≈50.5%, lift ≈2×.
  This benchmark still carries the inherited 1 s optimistic bar-snap that the
  long side fixed, so it is mildly optimistic — not to be over-interpreted.

## Stop conditions

top-100 source SHA mismatch · TOP50/TOP25 not exact prefixes · strict-causal
prepared data missing or irreproducible · target column missing · any required
feature missing · 2026 touched in selection · bar-snap convention ambiguous ·
model code needing new features or target changes → **STOP** and report with
`LONG_REDUCED_FEATURE_STUDY_REMEDIATION_REQUIRED`.

## Files this study may create

Only under `studies/long_rth_pure_flip_top50_top25_training/`. The prior study,
`features/`, and the reduction study are read-only inputs. **No file outside this
directory is modified.**

## Decision vocabulary

`LONG_TOP25_SIGNAL_STRONG_PRESERVATION` | `LONG_TOP50_SIGNAL_STRONG_PRESERVATION` |
`LONG_TOP25_SIGNAL_WEAK_BUT_USABLE` | `LONG_TOP50_SIGNAL_WEAK_BUT_USABLE` |
`LONG_TOP100_STILL_REQUIRED` | `LONG_REDUCED_FEATURE_FAILS_2026` |
`LONG_REDUCED_FEATURE_STUDY_REMEDIATION_REQUIRED`
