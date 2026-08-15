# Look-Ahead & Timestamp Audit — Pass 11

**Date:** 2026-08-14T12:46:35.4048998-05:00  
**Scope:** `SPEC.md`, `config/study.yaml`; the new `implementation/freeze_train_only_baselines.py`; amended `run_study.py`; the narrowly required collector, registry, collection-lineage, and finalization dependencies; the three upstream F3 ranking/candidate-construction scripts and candidate-set JSON; and schema/year-bound inspection of the canonical score and regime parquet sources. `git diff -U20` exposed only the tracked SPEC amendment because the study implementation is untracked, so the two amended study-owned Python files were reviewed in full.  
**Scope hash:** `e2eaa853aa816c4225ba28a935aae7917dae0a62437602c07274b89b5242ccd1`  
**Lint:** 0 critical / 0 warning from `causal_lint.py` (26 files scanned)  
**Verdict:** BLOCKED

## Summary

- Critical: 1
- Warning: 0
- Note: 0

## Prior findings adjudicated

| # | Prior finding | Status | Evidence |
|---|---|---|---|
| 1 | [A1/A5] Equal-time 5m snapshots omitted the bucket that just completed | FIXED | Unchanged: `implementation/collector.py:77-86` finalizes through `ts_init` before provenance audit and snapshot. |
| 2 | [A1] 1s extrema were stamped with bar-open time | FIXED | Unchanged: `implementation/collector.py:65-75` uses `ts_init` for the geometry tracker and confines `ts_event` to completed-source aggregation. |
| 3 | [G4] Volume-one bars fed structural extrema and completed-5m indicators | FIXED | Unchanged: `implementation/collector.py:68-76` requires `volume > 1` before either update. |
| 4 | [B9] Registry metadata omitted the load-bearing 1m-flip update | FIXED | Unchanged: `features/registry.py:594-618` declares the combined timeframe, completed-bar/flip anchor, window unit, and reset policy. |
| 5 | [G4] An excluded volume-one checkpoint supplied the snapshot price | FIXED | Unchanged: `implementation/collector.py:71-86` updates `_last_close` only inside the eligible-volume branch. |
| 6 | [G2] Corrected collection output was disconnected from downstream consumers | FIXED | Unchanged: `implementation/paths.py:1-8`, `run_study.py:15,49-50`, and `implementation/finalize_artifacts.py:11,16,65-75` share `COLLECTION_ROOT`. |
| 7 | [C3] Phase-0 authenticated a feature list selected with post-2024 labels | NOT FIXED | The new freezer's entire candidate universe comes from the score-table schema (`implementation/freeze_train_only_baselines.py:27-33`). Independent schema inspection found exactly 25 candidates per direction, identical to the old `F3_top25_gbt_v1`; that set was ranked against 2025 labels (`build_importance_sample.py:1-6,22-24`; `phase3_feature_importance.py:36-45,50-60`) and frozen as Top-25 (`phase4_build_candidates.py:24-31,40-69`). Selecting 25 of those same 25 does not remove the future selection. |

## Critical findings

### [C3] `implementation/freeze_train_only_baselines.py:27-52` — the “train-only” freezer re-ranks an already 2025-selected 25-feature universe

**Failure path:** `candidates()` discovers only prefixed columns already materialized in `canonical_regime_scores_all.parquet`. The current parquet schema contains exactly 25 bullish and 25 bearish candidate columns, and each side is exactly the old `F3_top25_gbt_v1` list. That upstream list was selected by permutation importance against the 2025 target (`build_importance_sample.py:1-6,22-24`; `phase3_feature_importance.py:41-45,50-60`; `phase4_build_candidates.py:24-31,40-69`). Although the new freezer correctly filters ranking rows to 2021-2023 and regime ends to before 2024 (`freeze_train_only_baselines.py:34-45`), it ranks 25 candidates and retains all 25 (`freeze_train_only_baselines.py:46-54`). `run_study.py:29-33,111-124,190-196` then loads that reordered future-selected set into both the 2021-2023 fit and 2024 scoring. The reported 2024 AUC therefore remains post-selection rather than untouched temporal OOS.

The recorded score/regime hashes (`freeze_train_only_baselines.py:58-65`) authenticate the contaminated source bytes, not a train-only candidate-universe construction; `source_contract()` also does not recompute those two source hashes before fitting (`run_study.py:176-187`).

**Smallest fix:** Construct and rank the eligible candidate universe from a pre-2024 feature source that was not itself narrowed using 2024+ outcomes, then freeze its Top-25 and verify its score/regime source hashes before any fit begins.

## Warnings

None.

## Notes

None.

## Referred to contract-checker

- `run_study.py:29-46` defines `STRUCTURAL`, `FAMILIES`, and `BUCKETS` as locals of `require_frozen_baselines()`, while later module functions reference them as globals.
- `freeze_train_only_baselines.py:23-24` and `run_study.py:182-187` hash the feature list with incompatible JSON serialization, and phase 0 is materialized only after fit outputs at `run_study.py:190-217`.

## Clean checks

- The new freezer's row/label path itself is bounded to 2021-2023: score rows are filtered by year and RTH, strict eligibility uses `>120`, `>=1`, `>=2`, `>=0.5`, and exact 5s cadence, regime ends are restricted to `< 2024-01-01`, and only then is the `(T,T+300s]` label formed (`implementation/freeze_train_only_baselines.py:34-45`).
- Direction wiring is consistent: bullish freezes `SHORT`, bearish freezes `LONG` (`implementation/freeze_train_only_baselines.py:69-71`); the runner resolves and fits the same mapping (`run_study.py:23-33,78-81,111-124,176-187,195-196`).
- A1-A5, B1-B7, B9-B10, C1-C2, F1-F4, G1-G4, and H1-H4 verified clean on the changed causal surface. C3 remains blocked by the finding above.
