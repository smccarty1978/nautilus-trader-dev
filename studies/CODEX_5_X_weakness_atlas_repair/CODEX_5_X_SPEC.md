# CODEX 5.X — Weakness Atlas Direction Repair

## Blocking defect

The legacy weakness-atlas builder multiplied bearish favorable/adverse
distances by `direction=-1` after those distances were already aligned. This
made almost all bearish `current_mfe` and `current_mae` values negative and
contaminated the frozen W4 model. Every prior W4-dependent policy result is
invalid until this repair completes.

## Isolation and naming

All new scripts, audits, models, atlases, and reports are stored under
`studies/CODEX_5_X_weakness_atlas_repair/` and use `CODEX_5_X_` names. The
only edit outside this folder is the minimal source correction in
`studies/regime_sequence_chop_context/build_weakness_atlas.py`.

## Excursion contract

For anchor `P0`, running high `H`, running low `L`, and positive ATR:

- bullish MFE = `max(0, H-P0)/ATR`;
- bullish MAE = `max(0, P0-L)/ATR`;
- bearish MFE = `max(0, P0-L)/ATR`;
- bearish MAE = `max(0, H-P0)/ATR`.

`current_mfe == running_mfe` and `current_mae == running_mae`. Both are
non-negative and monotonically non-decreasing within an exact regime key.
`current_pnl`, `current_mfe`, `current_mae`, `running_mfe`, and `running_mae`
are all normalized by the frozen `atr_at_entry`. The explicit
`atr_at_checkpoint` is the ATR from the last completed context bar. The
legacy-named `atr` column remains only as an exact compatibility alias for
`atr_at_checkpoint`. `current_mfe/current_mae` are running observed-so-far
excursions, not terminal full-regime outcomes.

## Atlas rebuild

- Raw source: `data/raw/NQ_v0_1s_{year}.parquet` (2026 uses `_ytd`).
- Regimes: fresh canonical sequential 1-minute RegimeEngine per year.
- Checkpoints: 30 seconds for 2021-2024; 5 seconds for 2025-2026; maximum age
  1,800 seconds.
- Databento 1-second `ts_event=t` is the open of `[t,t+1s)`. Entry is the
  first raw open at or after the completed flip decision. A checkpoint at
  `cp` uses bars in `[entry_ts, cp)`; labels scan `[cp, opposite_flip_ts)`;
  and every modeled checkpoint satisfies `cp < opposite_flip_ts`.
- The affected local path state, every label dependent on it, and every W4
  center/sequence input are rebuilt from raw 1-second bars. Center inputs are
  sampled only from the last feature bar with `ts_event < checkpoint`; sequence
  inputs use corrected completed regimes over `[start,end)`. The immutable
  legacy atlas is used only for full-key checkpoint identity parity, never as
  a source of repaired model inputs. Future path fields remain labels only.
- Legacy-only keys are accepted solely when they are either exactly at the
  opposing-flip endpoint or at/before the first available entry bar following
  a documented data gap. Both non-causal removal classes are counted; every
  other key mismatch fails the rebuild.
- Per-year repaired atlases are immutable inputs to modeling. 2026 is built
  only after the 2025 model structure and calibration are frozen.

## Chronology

- Model train: 2021-2024 only.
- Structure selection: 2025-01-01 through 2025-06-30.
- Calibration/threshold freeze: 2025-07-01 through 2025-12-31.
- Final untouched model test: 2026 only, opened after a frozen model manifest
  exists and passes the pre-test audit.

No 2026 feature, label, score, or metric may alter model structure,
calibration, thresholds, established-regime filter, stop, or exit.
Any regime spanning the July 1 boundary is purged from both H1 selection and
H2 calibration, and the two regime-key sets must be disjoint.

The 2026 seal requires a passing W4 gate, verified bundle/atlas/dependency
hashes, and a separate passing pre-2026 audit authorization tied to the frozen
manifest hash. Manifest existence alone never authorizes 2026 access.

## Model structures

Four fitted structures are compared without a parameter grid:

1. pooled repaired W4;
2. long-prevailing-only repaired W4;
3. short-prevailing-only repaired W4;
4. pooled repaired W4 plus `direction` and direction interactions with the
   five repaired local features (`regime_age`, `current_pnl`, `current_mfe`,
   `current_mae`, `giveback`).

The long/short models also form a direction-specific pair for pooled
evaluation. Selection uses 2025-H1 macro directional ROC-AUC. If candidates
are within 0.005 macro AUC, prefer the smaller directional AUC gap, then the
simpler pooled model. Calibration uses 2025-H2 only, separately by prevailing
direction, with isotonic calibration and direction-specific P90 thresholds.

## Pre-policy W4 gate

The repaired W4 passes only when all are true on pre-2026 data:

- unit tests pass;
- zero negative or within-regime monotonicity violations;
- finite-score rate >= 99% in each direction;
- 2025-H1 ROC-AUC > 0.50 in each direction for the selected structure;
- 2025-H2 strict-crossing regime rate is non-zero in each direction;
- ratio of larger to smaller directional regime crossing rate <= 2.0.

Failure stops the study before monetization.

## Tight policy rerun

Only after the repaired W4 gate and audits pass:

- reuse established filter unchanged: age >= 120 seconds, running MFE >= 1.0
  ATR, >= 2 progress windows, retained-MFE ratio >= 0.50;
- trigger on the selected repaired/calibrated W4 direction threshold;
- explicit next-available 1-second-open OHLC research entry;
- exactly 1.5 ATR fill-anchored stop, active on the entry bar;
- hold through the aligning flip and exit on the next flip against the trade;
- $10 round-trip cost;
- 2025 is the frozen development result and 2026 is the final test.

This remains a 1-second OHLC research simulation, not NT-native executable
validation and not deployable.
