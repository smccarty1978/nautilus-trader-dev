# Look-Ahead & Timestamp Audit — Mandatory Completion Gate

**Date:** 2026-07-21T23:47:36-05:00  
**Scope:** final code; 2021-2025 monthly datasets/checkpoints/manifests; both candidate model directories; 2025 metrics/comparison/decision; reproduction evidence  
**Scope hash:** `659230628b1d02976cf5165a7f03261686ff8e402be2d5c8a31000670f0c9f42`  
**Auditor:** lookahead-auditor v1  
**Final verdict:** `STRICT_LONG_CONTRACT_VERIFIED` / `LONG_STRICT_TOP103_SELECTED`

## Summary

- Critical: 0
- Warning: 0
- Note: 1

## Notes

### [Persistence hygiene] `implementation/pipeline.py:292-335` — failed writes are not atomic

The two required candidate directories are complete and verified. A separate directory, `artifacts/models/LONG_STRICT_top25_gbt_v2_failed_attempt_1`, contains only `model.joblib`, a fixture, and fixture scores from an earlier failed attempt. Its explicit name prevents confusion with the two model IDs, so it does not invalidate either candidate. The write sequence creates and populates the final directory incrementally, however, so a future mid-persistence exception can again leave an incomplete artifact namespace.

## Completion evidence

### Population, chronology, and completed-bar timing

- Exactly 60 monthly parquet files and 60 month manifests exist: 12 months for each of 2021-2025. Every year checkpoint lists the exact same complete month set.
- Recomputed totals match checkpoints: 846,349 rows; training 682,952 rows / 6,401 regimes; development 163,397 rows / 1,578 regimes.
- Year populations and prevalence match their checkpoint evidence: 2021 `164,940 / 1,626 / 0.294174`; 2022 `189,071 / 1,672 / 0.252090`; 2023 `167,721 / 1,583 / 0.271659`; 2024 `161,220 / 1,520 / 0.265749`; 2025 `163,397 / 1,578 / 0.262936`.
- Every month output hash matches its manifest. Source, script, mapping, and feature-list hashes match the current frozen causal contract.
- Population direction remains `-1`, trade/predicted direction `+1`, RTH-only, with the strict `ts_event < observation_time` contract and zero-censor upstream provenance.
- Training data are exclusively 2021-2024; all model evaluation and selection evidence is 2025.
- `final_decision.json` records `"2026_status": "NOT_SCORED"`; no generated file in this study references or contains 2026 scoring.

### Model configuration and persistence

- Both persisted objects are `HistGradientBoostingClassifier` with exactly `max_depth=3`, `learning_rate=0.05`, `max_iter=200`, and `random_state=42` as the explicitly supplied configuration.
- Persisted classes are exactly `[0, 1]`; positive-class index is 1. Feature counts and `n_features_in_` are exactly 25 and 103.
- Both required directories contain exactly: `model.joblib`, `feature_list.json`, `feature_mapping.json`, `manifest.json`, `metrics_2025.json`, `validation_fixture.parquet`, `validation_fixture_scores.npy`, and `README.md`.
- Both manifests contain every required field: identity/class/config, target/directions/timing, train/dev years, feature count and ordered hash, mapping/builder/attachment/data/model/score hashes, sklearn/numpy versions, seed, fit timestamp/runtime, and `CANDIDATE` status.
- Model, mapping, and saved-score file hashes match the manifests. Ordered feature hashes match the frozen source candidate contracts.
- Existing v1 long artifacts were not modified by this study.

### Required 2025 evidence and selection

- Both metrics files contain all required global and monthly predictive metrics, score distribution, top-5%/top-2.5% thresholds and row/regime counts, fit/score runtime, canonical runtime calculation count, and artifact size.
- L25: ROC-AUC `0.650265`, AP `0.400343`, Brier `0.183012`.
- L103: ROC-AUC `0.655289`, AP `0.410026`, Brier `0.181866`.
- L25 versus L103 deltas are AUC `-0.005024` and AP `-0.009683`; worst same-month AUC deficit is `0.022001` (2025-06). These fail the frozen close-enough limits (`-0.003`, `-0.005`, and `0.020`), so `LONG_STRICT_TOP103_SELECTED` follows the implemented 2025-only decision rule.
- Comparison evidence includes Pearson/Spearman score correlation, both regime-overlap thresholds, L25-only/L103-only regimes, and first-qualifying-checkpoint differences.
- Regime-level ROC-AUC is reported for maximum, p90, first, and mean aggregation for both candidates. Values remain near chance as required for disclosure; they were not used to redefine the model or target.

### Reproduction

- Reloaded-model recomputation independently confirms `max_abs_diff=0.0` and `mean_abs_diff=0.0` for both candidates.
- Saved feature order is exact for both candidates.
- `reproduction_report.json` confirms exact scores, `[0,1]` classes, and positive-class index 1 for both candidates.

## Compliance matrix

- A1, A5: PASS
- A2-A4: N/A
- B1-B7: PASS/N/A
- C1-C4: PASS
- D1-D4: PASS
- E1-E5: N/A
- F1-F4: PASS
- G1-G4: PASS/N/A
- H1-H4: N/A

---

*Mandatory completion audit complete. Findings reflect read-only static and artifact analysis; no backtest or 2026 scoring was run.*
