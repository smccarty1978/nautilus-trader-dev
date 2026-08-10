# Look-Ahead & Timestamp Audit

**Date:** 2026-08-10T12:31:00-05:00  
**Scope:** `SPEC.md`, `config/study.yaml`, `implementation/contracts.py`, `implementation/train_pre_2026.py`, and `tests/test_contracts.py`  
**Scope hash (SHA-256):** `f9e087b88cd81159f71e66b10c8688f29350c689e85d0e00063e3aaa47c58ee1`  
**Auditor:** lookahead-auditor v1  
**Audit type:** mandatory pre-execution causal gate; static read-only review

## Summary

- Critical: 2
- Warning: 1
- Note: 0
- Verdict: **BLOCKED**
- Pre-2026 training may proceed: **No**

## Critical findings

### [C1] `implementation/train_pre_2026.py:80-87` — label builder opens unsealed 2026 regimes

`next_flip_labels` scans and collects the entire `canonical_regimes_all.parquet` file without a pre-2026 predicate before any label is calculated. The sealed-gate contract in `SPEC.md:42-54` prohibits opening any 2026 path, feature, score, or label before the pre-2026 gate passes. If this canonical file contains 2026 regimes, every pre-2026 run reads them into `regimes`; rows near the seal can also obtain their next target from that unsealed portion before later evaluation masking removes them. This is a direct seal breach and invalidates the claim that the run never accessed 2026.

### [C2] `implementation/train_pre_2026.py:81-87` — `searchsorted` label alignment assumes an unverified ordering

`np.searchsorted(target, times, side="right")` is only correct when `target` is ascending. The Polars scan has neither an explicit `.sort("regime_start_decision_ns")` nor an assertion that the canonical read is monotonic. Parquet scan order is not a timestamp contract. A reordered row group or regenerated catalog can therefore select a non-next regime (or no regime), silently assigning the wrong future-window label to checkpoints. The model's quarterly AUC and all downstream gates would then be calculated against misaligned labels.

## Warnings

### [C1/C2] `implementation/train_pre_2026.py:80-87`, `implementation/train_pre_2026.py:90-125` — frozen confirmed-flip label semantics are not enforced

The frozen target is a **confirmed opposing flip** (`SPEC.md:16-27`), but the implementation derives `y` from the next global row having only `regime_direction == target_direction`. It neither reads an explicit confirmation milestone nor proves that every source checkpoint is in the required opposite regime before assigning the label. This may be correct only if `canonical_regimes_all.parquet.regime_start_decision_ns` is already the canonical confirmation time and each `{prefix}_in_domain` population guarantees the matching source regime. Neither invariant is checked in the audited code. If either differs, labels no longer match the frozen target at row `i`.

## Clean checks

- `implementation/contracts.py:39-46` excludes training timestamps whose 300-second label window reaches the next quarter; the boundary test at `tests/test_contracts.py:7-16` covers the exact-edge behavior.
- `implementation/train_pre_2026.py:160-175` fits each quarterly model only on `resolved_train_mask(...)` rows and calculates thresholds from that same historical training population.
- `implementation/train_pre_2026.py:97-111` rejects any selected score row at or after the UTC 2026 boundary. This row-level check is sound but does not remedy the unsealed full-file reads above.
- `config/study.yaml:2-4,24` uses the continuous symbol `NQ.v.0` and named `America/Chicago` timezone.

## Compliance matrix

| Rule | Status | Evidence / disposition |
|---|---|---|
| A1 | N/A | No NT `Bar` timestamps are handled in scope. |
| A2 | N/A | No catalog or `BarType` construction in scope. |
| A3 | N/A | No strategy current-price lookup in scope. |
| A4 | N/A | No timer/event callback in scope. |
| A5 | PASS | Quarterly boundaries are explicit UTC datetimes (`contracts.py:18-28`); no resampling. |
| B1 | PASS | No rolling, EWM, or expanding feature computation in scope. |
| B2 | N/A | Feature computation is delegated to the accepted upstream NT collector, outside this limited audit scope. |
| B3 | N/A | No recursive indicators are computed in scope. |
| B4 | PASS | No negative shift or negative lag occurs in the feature path. |
| B5 | PASS | No forward/backward fill occurs in scope. |
| B6 | N/A | No multi-frequency join or merge occurs in scope. |
| B7 | PASS | Quantiles are fit only on each model's resolved historical training scores (`train_pre_2026.py:170-175`). |
| B9 | N/A | No feature tracker is implemented in scope. |
| B10 | N/A | No multi-timeframe feature variant is implemented in scope. |
| C1 | CRITICAL | Unsealed global regime scan is used for label construction (`train_pre_2026.py:80-87`). |
| C2 | CRITICAL | Unsorted `searchsorted` target can misalign label timestamps (`train_pre_2026.py:81-87`). |
| C3 | PASS | Quarterly evaluation is temporal and expanding-window training is bounded by each quarter start (`contracts.py:35-46`, `train_pre_2026.py:160-165`). |
| F1 | N/A | No RTH/ETH classification code in scope. |
| F2 | N/A | No session-window tracker in scope. |
| F3 | PASS | The configured display zone is named and quarter boundaries are UTC-aware (`study.yaml:3`, `contracts.py:18-20`). |
| F4 | PASS | Named `America/Chicago`, rather than a fixed offset, is used (`study.yaml:3,24`). |
| G1 | PASS | Continuous `NQ.v.0` is specified (`study.yaml:2`). |
| G2 | N/A | Missing-bar handling belongs to the upstream canonical collector, outside scope. |
| G3 | N/A | No resampling is performed in scope. |
| G4 | N/A | No bar-derived indicator is computed in scope. |
| H1 | N/A | No offline bracket simulator is implemented in scope. |
| H2 | N/A | No offline bracket simulator is implemented in scope. |
| H3 | N/A | No offline bracket simulator is implemented in scope. |
| H4 | N/A | No offline bracket simulator is implemented in scope. |

## Referred to contract-checker

Train/serve feature parity, artifact/manifest integrity, advancement-gate completeness, and execution/fill semantics are D/E/C4 scope and were not adjudicated in this causal pass.

---

*Audit complete. Findings reflect static analysis only. No pipeline code was modified or executed.*
