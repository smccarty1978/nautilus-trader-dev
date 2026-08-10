# Look-Ahead & Timestamp Audit

**Date:** 2026-08-10T12:36:00-05:00  
**Scope:** `SPEC.md`, `config/study.yaml`, `implementation/contracts.py`, `implementation/train_pre_2026.py`, and `tests/test_contracts.py`  
**Scope hash (SHA-256):** `210cffadddb269d118a5e3bf1311ef473b4a451831ae666d51fbdd9579492fd5`  
**Auditor:** lookahead-auditor v1  
**Audit type:** mandatory pre-execution causal gate; static read-only review

## Prior-finding adjudication

| Pass-01 finding | Status | Evidence |
|---|---|---|
| C1 — unsealed regime scan | **FIXED** | The regime lazy scan predicates `regime_start_decision_ns < SEALED_END` before selection and collection (`implementation/train_pre_2026.py:88-94`). The resulting labels cannot contain a 2026 regime row. |
| C2 — unsorted `searchsorted` target | **FIXED** | Regimes are explicitly sorted by decision timestamp, and strictly increasing starts are asserted before target extraction (`implementation/train_pre_2026.py:92-101`). Filtering by direction preserves that order. |
| WARNING — confirmed opposing-flip semantics not enforced | **FIXED** | The label source is explicitly documented as confirmed-decision time (`implementation/train_pre_2026.py:81-87`); source rows must be confirmed and in the required opposite regime (`implementation/train_pre_2026.py:135-138`), while target directions must alternate at confirmed starts (`implementation/train_pre_2026.py:95-101`). |

## Summary

- Critical: 0
- Warning: 1
- Note: 0
- Verdict: **BLOCKED pending warning adjudication**
- Pre-2026 training may proceed: **No**

## Warnings

### [C2] `implementation/train_pre_2026.py:91-101` — confirmed-regime sequence continuity is not checked

The scan selects `regime_sequence_number` at line 91 but never validates it. Strictly increasing timestamps and alternating directions do not prove that every confirmed transition is present: removal of an even-sized block of rows preserves both invariants. In that failure path, `searchsorted` skips one or more true target flips and labels checkpoints against a later transition (or as negative), corrupting the frozen 300-second target. The existing population assertions do not detect a missing target-regime row. This remains a blocker unless remediated or explicitly adjudicated under the frozen contract.

## Clean checks

- `implementation/contracts.py:39-46` excludes every training timestamp whose 300-second label window reaches the next quarterly boundary; `tests/test_contracts.py:7-16` covers the exact boundary behavior.
- `implementation/train_pre_2026.py:88-106` derives labels only from chronological, pre-2026 confirmed-regime starts.
- `implementation/train_pre_2026.py:116-138` restricts the input population to pre-2026, feature-complete in-domain rows and rejects invalid timestamps, non-finite features, unconfirmed rows, and wrong source direction.
- `implementation/train_pre_2026.py:183-199` fits each quarterly model and calculates its thresholds exclusively from historical resolved-label rows.
- `config/study.yaml:2-4,24` uses `NQ.v.0` and the named `America/Chicago` timezone.

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
| C1 | PASS | Labels use only the explicit 300-second future target window and source data before the 2026 seal (`implementation/train_pre_2026.py:88-106`). |
| C2 | WARNING | Sequence continuity is not enforced despite an available sequence field (`implementation/train_pre_2026.py:91-101`). |
| C3 | PASS | Quarterly evaluation is temporal; expanding training ends before every evaluation-quarter start (`implementation/contracts.py:35-46`, `implementation/train_pre_2026.py:184-189`). |
| F1 | N/A | No RTH/ETH classification code in scope. |
| F2 | N/A | No session-window tracker in scope. |
| F3 | PASS | The display zone is named and quarter boundaries are UTC-aware (`config/study.yaml:3`, `implementation/contracts.py:18-20`). |
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
