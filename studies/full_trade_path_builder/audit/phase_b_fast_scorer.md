# Phase B Fast-Scorer Targeted Audit

**Date:** 2026-07-24  
**Scope:** Phase B adapter, scorer call, runtime identity, and contract tests  
**Scope hash:** `f7a3b5ce8353c77bd4e6bf0821180ec18719772928095c715c249f3a4b0cfb29`  
**Auditor:** lookahead-auditor v1  
**Verdict:** **PASS — safe to restart the March parity run**

## Summary

- Critical: 0
- Warning: 0
- Note: 0

## Clean checks

- Binary HGB structure is enforced with one tree per boosting iteration.
- The scorer uses the frozen baseline margin and every stored leaf value.
- Numeric thresholds, equality, and missing-value routing match sklearn.
- Categorical splits fail loudly.
- Final probability is the sigmoid of the identical accumulated margin.
- Bearish fixture and deterministic Bullish probabilities are bit-exact.
- Scoring remains synchronous inside the checkpoint callback.
- No batching, delay, carried score, async queue, or future-row access exists.
- Adapter timing, event ordering, domains, and checkpoint population are unchanged.
- Wrapper source and model/dependency hashes are recorded.
- NautilusTrader, NumPy, SciPy, scikit-learn, and Numba versions are recorded.

---

*Read-only targeted audit. Approval applies to this exact source state and recorded runtime environment.*
