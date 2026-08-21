# Look-Ahead & Timestamp Audit — Pass 10

**Date:** 2026-08-14T12:24:23.0994741-05:00  
**Scope:** `run_study.py`, `implementation/validate.py`, `implementation/finalize_artifacts.py`, and seven narrowly required Top-25 provenance dependencies: the bullish and long artifact manifests, `phase_a_adapter.py`, `train_phase_a.py`, and the runtime-reduction importance-sample, importance-ranking, and candidate-construction scripts. `git diff -U20` was empty because the named study files are untracked, so the three named files were reviewed as the full changed surface against Pass 09.  
**Scope hash:** `1b1fd29c80b79300df0b2566fc182d23f8b8a7b03c301461f7b9ebd8c0dd23c5`  
**Lint:** 0 critical / 0 warning from `causal_lint.py`  
**Verdict:** BLOCKED

## Summary

- Critical: 1
- Warning: 0
- Note: 0

## Prior findings adjudicated

| # | Prior finding | Status | Evidence |
|---|---|---|---|
| 1 | [A1/A5] Equal-time 5m snapshots omitted the bucket that just completed | FIXED | Preserved from Pass 09: the named Pass-10 changes do not touch `implementation/collector.py:72-86` or `collectors/collector_v2/aggregator.py:117-135`. |
| 2 | [A1] 1s extrema were stamped with bar-open time | FIXED | Preserved from Pass 09: the named changes do not touch `implementation/collector.py:65-75`, which confines `ts_event` to aggregation and supplies `ts_init` to the tracker. |
| 3 | [G4] Volume-one bars fed structural extrema and completed-5m indicators | FIXED | Preserved from Pass 09: the named changes do not touch the `volume > 1` gate at `implementation/collector.py:68-76`. |
| 4 | [B9] Registry metadata omitted the load-bearing 1m-flip update | FIXED | Preserved from Pass 09: the named changes do not touch `features/registry.py:594-618`. |
| 5 | [G4] An excluded volume-one checkpoint supplied the snapshot price | FIXED | Preserved from Pass 09: the named changes do not touch eligible `_last_close` handling at `implementation/collector.py:77-86`. |
| 6 | [G2] Corrected collection output was disconnected from downstream consumers | FIXED | `run_study.py:15,45-46`, `implementation/validate.py:10-15,78-98`, and `implementation/finalize_artifacts.py:11,16,65-75` still consume the shared corrected `COLLECTION_ROOT`. |

## Critical findings

### [C3] `run_study.py:172-181` — Phase-0 source verification authenticates a future-label-selected feature list as valid for 2024 OOS

**Failure path:** The study fits on 2021-2023 and scores 2024 as OOS (`run_study.py:107-127`), but both baseline lists resolve to the same frozen Top-25 hash (`studies/full_trade_path_builder/artifacts/BULLISH_STRICT_top25_gbt_v2/model_manifest.json:7-33`; `studies/freeze_long_strict_models_v2/artifacts/LONG_STRICT_top25_gbt_v2/manifest.json:14-22`). That hash comes from `F3_top25_gbt_v1` (`studies/full_trade_path_builder/implementation/phase_a_adapter.py:16-20`), whose ranking sample loads labeled 2025 rows (`studies/runtime_constrained_f3_feature_reduction/implementation/build_importance_sample.py:1-6,23-24`), computes permutation importance against the 2025 target (`studies/runtime_constrained_f3_feature_reduction/implementation/phase3_feature_importance.py:41-45,57-60`), and selects the Top-25 from that ranking (`studies/runtime_constrained_f3_feature_reduction/implementation/phase4_build_candidates.py:25-30,41-69`). `source_contract()` checks only list hash and count, so `phase0_contract()` can PASS (`run_study.py:162-181`) even though the 2024 “OOS” feature set was selected using post-2024 outcome labels. The reported 2024 AUC is therefore post-selection, not an untouched temporal OOS estimate.

**Smallest fix:** Freeze the baseline Top-25 using data no later than 2023 and require `source_contract()` to verify selection provenance ending strictly before the 2024 OOS boundary before phase 0 can pass.

## Warnings

None.

## Notes

None.

## Referred to contract-checker

None.

## Clean checks

- The exact AUC grid adds 16 direction-specific cells plus 8 explicitly labeled pooled cells (`run_study.py:80-86,195-201`), while validation requires exactly that 24-cell key set and positive-class support (`implementation/validate.py:21-22,103-120`); this output expansion introduces no feature/label leakage.
- Pooled rows are excluded before all terminal discrimination and timing evidence: `terminal_summary()` filters AUC rows to `SHORT`/`LONG` at `implementation/finalize_artifacts.py:37-47`; pooled rows cannot change a terminal label.
- A1-A5, B1-B7, B9-B10, C1-C2, F1-F4, G1-G4, and H1-H4 remain clean on the changed surface. C3 is blocked by the finding above.
