# Mirrored Long-Side Pure-Flip Surface Build + Top-100 Training

## Status

**SPEC frozen. Feasibility established as BUILDABLE** (contrary to the POC's
pessimism). Surface → label → features → gate → train, all executed. A
completion-gate `lookahead-auditor` pass ran on the full pipeline and returned
**1 CRITICAL + 2 WARNING** (see `audit/audit.md`); all were remediated and the
attach + train stages re-run on corrected data before finalizing. See
"Causal convention (post-audit remediation)" below.

## Causal convention (post-audit remediation)

Raw 1s bars are **open-labelled**: `ts_event=t` covers `[t, t+1s)`
(`CODEX_5_X_run_established_fade.py:3-4`). The correct "last completed bar at
`observation_time`" therefore has `ts_event < observation_time` (strictly), and
the atlas enforces exactly this (`build_weakness_atlas.py:96`
`searchsorted(..., side='left')-1`; W4 merge asserts `feature_bar_ts_event <
observation_time`). The 44 atlas-sourced center features were always on this
strict convention.

The audit found the feature-attach step inherited `searchsorted(..., side='right')-1`
from the upstream short-side `attach_features.py`, which is **inclusive** of a
bar at `ts_event == observation_time` (a still-forming bar) — a 1-second
look-ahead on the 56 ohlcv+price features, affecting ~96–98% of rows. Fixed in
`attach_features_long.py` (change 3: strict `side='left'`), and the provenance
invariant tightened to strict (`latest_source_ts_used < observation_time`), so
all 100 features now share one causal convention. This bug is **inherited,
unchanged, by the deployed short-side benchmark model** — so the short-side
AUC/flip benchmarks this study compares against are themselves ~1s-optimistic;
disclosed in `STUDY_REPORT.md` rather than assumed away.

## Primary decision

Build the missing mirrored long-side pure-flip training surface
(`direction == -1`, prevailing-bearish RTH regimes), then train the long-side
top-100 pure-flip model **iff** the surface passes data, causality, and
feature-parity gates. Core question: given a qualified bearish RTH regime, can
the reduced top-100 feature set predict a bullish regime flip within 300 s?

This study exists because `long_rth_pure_flip_top100_training` correctly stopped
with `LONG_TOP100_STUDY_REMEDIATION_REQUIRED` — no long-side checkpoint surface
existed. The feature list was never the blocker.

## Key feasibility finding (verified this session, de-risks the POC's fear)

The prior POC (`nt_pure_flip_trigger_poc_and_mirrored_long_model`) concluded the
mirror needed "three prior full studies' pipelines mirrored" because it searched
for a materialized bearish **surface**. But the direction-agnostic **5s atlas**
substrate already contains `direction == -1` regimes with *correct
bearish-favorable excursions* and the full W4 context, for **all six years**:

| Years | Atlas file | Cadence | Directions | 44 center feats | Keys |
|---|---|---|---|---|---|
| 2021–2024 | `short_rth_entry_surface_backfill/_work/atlas_5s_backfill_{y}.parquet` | 5s | both (~50/50) | present | present |
| 2025, 2026 | `CODEX_5_X_weakness_atlas_repair/_work/CODEX_5_X_repaired_years/CODEX_5_X_weakness_atlas_repaired_{y}.parquet` | 5s | both (~50/50) | present | present |

Atlas excursions are direction-correct because each regime's checkpoints are
built via `build_weakness_checkpoints_for_regime(direction=direction, ...)`
(`build_5s_atlas_smoke.py:96`), and the intrinsic causal audit validates
non-negative monotone `running_mfe/mae` across **all** regimes (both
directions). **No atlas rebuild is required.**

## Frozen feature list (Phase 0 — reused, verified identical to prior study)

- `feature_source_file`:
  `studies/runtime_constrained_f3_feature_reduction/results/top_100_raw_feature_columns.csv`
- `feature_source_sha256`:
  `6c6ceba7d3520e91b0feaed00cd6ab320230e8404e840894190b1cc7e70bc619`
- `ordered_feature_list_sha256`:
  `f2a6db0b6453433ccc1970255808c940133d1530ff4aa907339966c8c4f37992`
- `n_features` = 100 raw. Families: 44 center/slope/alignment, 29 ohlcv-delta,
  27 price-level. 97 verified / 3 timing-unverified.
- **Encoding expansion**: the 4 `rolling_5m_high_position__*` one-hot siblings
  are the only categorical group in the top-100 raw list; if any position
  categorical is present it expands deterministically to its complete dummy set,
  train-fit only (fit on train, applied to dev/test — no leakage). All other 96
  are numeric. (The short-side *trained* `F3_top100_gbt_v1` reached 103 columns
  the same way; here we freeze the raw 100 and expand deterministically.)

Stop if the source SHA does not reproduce exactly.

## Directionality contract (Phase 0/3 — the highest-risk step, resolved with code proof)

Full per-feature table: `results/directionality_audit.csv`. Summary:

| Source | Treatment | Count | Mirror action | Code evidence |
|---|---|---:|---|---|
| Atlas W4 context | regime-direction-relative | 44 | use as-is (bearish population ⇒ bearish-oriented) | `build_5s_atlas_smoke.py:96` passes regime `direction`; short side used these same regime-relative feats on its `direction==+1` regimes |
| `OHLCVDeltaTracker` | absolute (no direction param) | 29 | use as-is | `attach_features.py:259` `ohlcv_tracker.calculate(atr=atr)` — no direction arg on either side |
| `PriceLevelTracker` | absolute signed-distance/position | 26 | use as-is | `price_levels.py:192-200` signed distances independent of `direction` |
| `PriceLevelTracker` | direction-normalized | 1 | call `direction=+1` | `price_levels.py:392-427` `_direction_normalized`; only `pct_levels_behind_trade` is in the top-100 |

**The only sign-flip in the entire top-100 is the price tracker's `direction`
argument (short used `-1`, mirror uses `+1`), which affects exactly one selected
feature (`pct_levels_behind_trade`).** No delta feature is sign-flipped (proof:
the short side fed them absolute). No new feature is implemented. This is a
faithful mirror, not a re-interpretation.

## Population (Phase 1)

- Instrument NQ; RTH only; `direction == -1` (prevailing-bearish) regimes;
  long counter-regime setup (`entry_direction = +1`).
- Years 2021–2026. 2026 built **only** for sealed test evaluation; never used in
  selection.
- Checkpoint cadence 5s (atlas). Qualified-regime gates = the *same*
  established+RTH filter used for the short side
  (`CODEX_5_X_established_fade_policy.json` filter + `is_rth`), applied to the
  mirrored excursion.

`build_surface_long` is a fork of
`short_rth_entry_surface_backfill/entry_surface.py:build_surface` with exactly
these changes, everything else identical:
- keep `direction == -1` (instead of `== 1`);
- `favorable = anchor - lows[a:b]` (bearish-favorable = price below entry),
  instead of `highs[a:b] - anchor`;
- `entry_direction = +1`, `prevailing_direction = -1`.
The established filter still reads `cp.current_mfe` (already bearish-favorable in
the atlas), `cp.regime_age`, `progress[k]`, `retained_mfe_ratio` unchanged.

**Self-validation (mandatory, `RuntimeError` on failure):** the re-derived
bearish-favorable `running[k]` must equal the atlas `cp.current_mfe` to 1e-9 —
this is an independent proof that the atlas excursion is bearish-oriented for
`direction==-1` regimes. If it diverges, directionality is wrong → STOP with
`LONG_SURFACE_DIRECTIONALITY_FAILED`.

## Target (Phase 2)

`bullish_regime_flip_within_300s = (confirm_flip_ns - observation_time)/1e9 <= 300`,
where `confirm_flip_ns = regime_end` (the bearish→bullish flip that ends the
prevailing-bearish regime). Pure arithmetic, mirror of the short-side
`bearish_regime_flip_within_300s` (`short_rth_pure_flip_prediction_enriched/
phase0_prepare_data.py:99-100`). Independent of stop/PnL/timeout/entry/exit.

Censoring: `confirm_flip_ns` is always defined for a completed regime (atlas uses
`build_completed_regimes`), so the 300 s horizon is always observable →
0 primary-label censored rows expected. Any row with unobservable horizon (e.g.
a truncated final regime at data end) is censored and excluded; reported per year.

## Feature attachment (Phase 3)

- **44 center/slope/alignment**: joined directly from the atlas on
  `(regime_start_ns, observation_time)` — already present, regime-relative.
- **56 ohlcv+price**: `attach_features_long` = fork of
  `ohlcv_volume_delta_price_level_features/attach_features.py` with the single
  change `price_tracker.calculate(..., direction=+1)` (was `-1`), replaying the
  **long** surface's checkpoints. OHLCV tracker call unchanged.

Output `_work/prepared_long_{year}.parquet` = top-100 features + label + keys
(`regime_start_ns, observation_time, regime_start_time, direction=-1, session,
confirm_flip_ns, atr_at_entry, checkpoint age`).

## Split discipline

Train 2021–2024 · dev/select 2025 · sealed test 2026. 2026 never used for
feature/model/hyperparameter/threshold selection or calibration refit.

## Models (Phase 5)

Regularized logistic regression (standardized) + `HistGradientBoostingClassifier(
max_depth=3, learning_rate=0.05, max_iter=200, random_state=42)`. No zoo,
no deep learning. Selection on 2025 only.

## Benchmark

Short-side full-F3 GBT: 2025 AUC ≈ 0.671, 2026 ≈ 0.670, top-decile flip ≈ 50.5%,
lift ≈ 2×. Minimum-viable and strong-parity gates exactly as briefed.

## Files this study may create

Only under `studies/long_rth_mirrored_surface_top100_training/`. All prior
studies, `features/`, and both atlas sources are **read-only inputs**. No file
outside this directory is modified.

## Stop conditions

- top-100 SHA mismatch → `LONG_SURFACE_TOP100_STUDY_REMEDIATION_REQUIRED`.
- `direction==-1` population cannot be built / re-derived MFE ≠ atlas current_mfe
  → `LONG_SURFACE_DIRECTIONALITY_FAILED`.
- any top-100 feature absent after attach → `LONG_SURFACE_BUILD_FAILED`.
- any script reads 2026 during selection → halt (contract violation).
- feature requires new implementation / list change → halt.
- Phase 4 gate fails → write Phase 0–4 artifacts + remediation decision, no train.

## Decision vocabulary

`LONG_SURFACE_TOP100_SIGNAL_STRONG_PARITY` | `LONG_SURFACE_TOP100_SIGNAL_WEAK_BUT_REAL` |
`LONG_SURFACE_TOP100_SIGNAL_FAILS_2026` | `LONG_SURFACE_TOP100_SIGNAL_NOT_LEARNABLE` |
`LONG_SURFACE_BUILD_FAILED` | `LONG_SURFACE_DIRECTIONALITY_FAILED` |
`LONG_SURFACE_TOP100_STUDY_REMEDIATION_REQUIRED`
