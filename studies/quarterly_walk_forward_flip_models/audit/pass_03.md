# Look-Ahead & Timestamp Audit

**Date:** 2026-08-10T12:40:00-05:00  
**Scope:** `SPEC.md`, `config/study.yaml`, `implementation/contracts.py`, `implementation/train_pre_2026.py`, and `tests/test_contracts.py`  
**Scope hash (SHA-256):** `bc2ccec1217a5d454e500b5bb733f3ba12c9881cd2d77a43013e623da7507fa8`  
**Auditor:** lookahead-auditor v1  
**Audit type:** mandatory pre-execution causal gate; static read-only review

## Prior-finding adjudication

| Prior finding | Status | Evidence |
|---|---|---|
| C1 — unsealed regime scan | **FIXED** | The regime lazy scan predicates `regime_start_decision_ns < SEALED_END` before selection and collection (`implementation/train_pre_2026.py:88-94`). |
| C2 — unsorted `searchsorted` target | **FIXED** | The source is sorted by decision timestamp and strictly increasing starts are asserted before target extraction (`implementation/train_pre_2026.py:92-104`). |
| C1/C2 — confirmed opposing-flip semantic proof | **FIXED** | Confirmed-decision semantics are documented at the source, and population rows must be confirmed and in the required opposite regime (`implementation/train_pre_2026.py:81-87, 138-141`). |
| C2 — confirmed-regime sequence continuity not checked | **FIXED** | The sequence is loaded after chronological sorting and every adjacent delta must equal one; missing or duplicate regimes reject the run (`implementation/train_pre_2026.py:95-103`). |

## Summary

- Critical: 0
- Warning: 0
- Note: 0
- Verdict: **PASS**
- Pre-2026 training may proceed: **Yes**

## Clean checks

- `implementation/contracts.py:39-46` excludes all training rows whose 300-second label window reaches the following quarter; `tests/test_contracts.py:7-16` covers the exact boundary condition.
- `implementation/train_pre_2026.py:88-109` builds labels solely from pre-2026, chronological, sequence-continuous, alternating confirmed-regime decisions.
- `implementation/train_pre_2026.py:120-141` restricts selected source rows to pre-2026, feature-complete, in-domain records and rejects invalid timestamps, incomplete features, unconfirmed rows, and incorrect source regime direction.
- `implementation/train_pre_2026.py:184-199` fits every quarterly model and determines its quantile thresholds only from resolved historical training observations.
- `config/study.yaml:2-4,24` identifies `NQ.v.0` and uses named `America/Chicago` time handling.

## Compliance matrix

| Rule | Status | Evidence / disposition |
|---|---|---|
| A1 | N/A | No NT `Bar` timestamps are handled in scope. |
| A2 | N/A | No catalog or `BarType` construction in scope. |
| A3 | N/A | No strategy current-price lookup in scope. |
| A4 | N/A | No timer/event callback in scope. |
| A5 | PASS | Quarterly boundaries are explicit UTC datetimes (`implementation/contracts.py:18-28`); no resampling. |
| B1 | PASS | No rolling, EWM, or expanding feature computation occurs in scope. |
| B2 | N/A | Feature computation is delegated to the accepted upstream NT collector, outside this limited audit scope. |
| B3 | N/A | No recursive indicators are computed in scope. |
| B4 | PASS | No negative shift or negative lag occurs in the feature path. |
| B5 | PASS | No forward/backward fill occurs in scope. |
| B6 | N/A | No multi-frequency join or merge occurs in scope. |
| B7 | PASS | Quantiles use each model's resolved historical training scores only (`implementation/train_pre_2026.py:194-199`). |
| B9 | N/A | No feature tracker is implemented in scope. |
| B10 | N/A | No multi-timeframe feature variant is implemented in scope. |
| C1 | PASS | Labels use the explicit 300-second future target window, with target starts filtered before the 2026 seal (`implementation/train_pre_2026.py:88-109`). |
| C2 | PASS | Target regime chronology, contiguous sequence, alternating direction, and source-population direction are enforced (`implementation/train_pre_2026.py:95-109, 138-141`). |
| C3 | PASS | Quarterly evaluation is temporal; expanding training ends before every evaluation-quarter start (`implementation/contracts.py:35-46`, `implementation/train_pre_2026.py:184-189`). |
| F1 | N/A | No RTH/ETH classification code in scope. |
| F2 | N/A | No session-window tracker in scope. |
| F3 | PASS | The display zone is named and quarterly boundaries are UTC-aware (`config/study.yaml:3`, `implementation/contracts.py:18-20`). |
| F4 | PASS | Named `America/Chicago`, rather than a fixed offset, is used (`config/study.yaml:3,24`). |
| G1 | PASS | Continuous `NQ.v.0` is specified (`config/study.yaml:2`). |
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
