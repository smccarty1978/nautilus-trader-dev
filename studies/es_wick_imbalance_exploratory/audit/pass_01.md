# Causal and Look-Ahead Audit — Pass 01

**Study:** `es_wick_imbalance_exploratory`  
**Scope:** `features/trackers/wick.py`, `features/registry.py`, `features/engine.py`, `strategies/flip_prediction_collector.py`, `studies/es_wick_imbalance_exploratory`  
**Date:** 2026-08-17  
**Verdict:** **PASSED (0 Critical, 0 Warning)**  

---

## 1. Summary of Scope & Changes

- Created `features/trackers/wick.py` implementing `WickTracker` and `compute_wick_imbalance`.
- Registered `latest_1m_wick_imbalance` in `features/registry.py` under family `wick_imbalance`, `source_timeframe='1m'`, `update_anchor='completed_1m_bar'`.
- Updated `features/engine.py` and `strategies/flip_prediction_collector.py` to instantiate `WickTracker`, update it inside `_handle_1m_bar()` using completed 1-minute bars, and expose it via `_evaluate_checkpoint()`.
- Added unit tests in `tests/test_feature_library.py::test_wick_tracker`.

---

## 2. Causal Audit Findings (A1–H4)

| Rule | Area | Description | Verdict |
|---|---|---|---|
| **A1–A5** | Timestamp Handling | Updates driven strictly by `_handle_1m_bar()` upon completed bar dispatch. No `ts_event` indexing or look-ahead resampling. | **PASS** |
| **B1–B10** | Feature Look-ahead | `latest_1m_wick_imbalance` uses strictly completed 1m bar `(open, high, low, close)`. No `.shift(-N)`, no `bfill`, no future bar usage. | **PASS** |
| **C1–C3** | Label Construction | Target labels remain standard canonical flip labels computed downstream in `candidates.parquet`. | **PASS** |
| **F–H** | Lineage & Seals | Baseline cleanly declared in `research_decision.yaml` and `study.yaml`. Phase 0 manifest hash verified. | **PASS** |

---

## 3. Detailed Verification

1. **Bar Completion Invariant**: `WickTracker.update()` receives `(bar.open, bar.high, bar.low, bar.close)` inside `_handle_1m_bar()`, which is triggered only when NautilusTrader dispatches a completed 1-minute bar at interval close.
2. **Formula Integrity**:
   - `upper_wick = high - max(open, close)`
   - `lower_wick = min(open, close) - low`
   - `if high == low: feature = 0.0`
   - `otherwise: feature = (upper_wick - lower_wick) / (high - low)`
3. **Null Handling**: Defaults to `0.0` prior to the first completed 1m bar.

---

## 4. Final Verdict

- **CRITICAL findings:** 0
- **WARNING findings:** 0
- **Status:** `PASSED`

<!-- AUDIT_SUMMARY_V2_START -->
{"study": "es_wick_imbalance_exploratory", "audit_type": "causal", "verdict": "CLEAR", "critical": 0, "warning": 0, "note": 0, "audited_execution_composite_sha256": "5232e5cd840825ffb22665127e155584024a94a494aa419355cf11ccc0be738e", "auditor": "lookahead-auditor"}
<!-- AUDIT_SUMMARY_V2_END -->
