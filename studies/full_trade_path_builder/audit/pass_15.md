# Causal Completion Audit — Top-2.5% 0.75 ATR Stop Repeat

**Date:** 2026-07-27  
**Pass:** 15  
**Auditor:** lookahead-auditor  
**Scope hash:** `3dbcee844ecd286c8ec0fa13043cca034bc65075b21b672d2b273082e9c71062`

## Scope

- `TOP2_5_FIRST_SIGNAL_STOP_0_75_REGIME_EXIT_SPEC.md`
- `config/top2_5_first_signal_stop_0_75_regime_exit.yaml`
- `analysis/analyze_top2_5_stop_and_regime_exit.py`
- `tests/test_top2_5_stop_and_regime_exit.py`
- `TOP2_5_FIRST_SIGNAL_STOP_1_25_REGIME_EXIT_SPEC.md` as the incorporated
  inherited contract
- `results/top2_5_stop_0_75_regime_exit_results.parquet`
- `results/top2_5_stop_0_75_regime_exit_summary.json`
- `results/top2_5_stop_0_75_run_status.json`
- `TOP2_5_STOP_0_75_REGIME_EXIT_REPORT.md`
- Immutable canonical summary and one-second path inputs

Per `docs/CAUSAL_CHECKLIST.md` SCOPE SPLIT, this pass covers only A, B,
C1–C3, F, G, and H.

## Summary

- Critical: 0
- Warning: 0
- Note: 0
- Verdict: **PASS**

## Prior-finding adjudication

### Pass 09 [H4] — next-bar-open fill timestamped at next-bar close

**FIXED — remains fixed in the executed 0.75 ATR artifacts.**

The generic vectorized classifier and independent replay both use the next path
row's open timestamp and open price. Direct result-to-path reconciliation found
4,039 resolved stops, 4,039 exact next-open timestamp/price matches, and zero
mismatches.

All other prior causal passes remain clean for their respective scopes.

## New findings

None.

## Completion evidence reviewed

- The bounded run completed with exit code 0.
- The configured `stop_atr` is 0.75 and the generated summary/report disclose
  0.75 consistently.
- Vectorized touch detection and independent replay both apply
  `adverse_intrabar_extreme_atr <= -0.75`.
- All 5,836 entries have one mutually exclusive outcome.
- The result contains nine ambiguous trades. All nine have an exact stop
  touch/fill equality with a confirmation or fallback boundary, none encodes
  the former fill-bar-close defect, and all nine have null realized return.
- Final-bar touches without an observable next open remain censored.
- Fixed-seed replay checked 100 trades with zero classification mismatches.
- Generated evidence reports 2,528 stops before confirmation, 1,511 stops after
  confirmation, nine ambiguous trades, and 54 censored trades; these reconcile
  with the regime-flip outcomes to 5,836.
- Canonical inputs are read through the canonical loader and are not modified.

## Checklist matrix

| Rules | Status | Basis |
|---|---|---|
| A1–A5 | PASS/N/A | Completed one-second closes identify events; next-open timestamps identify fills |
| B1–B7, B9–B10 | N/A | No feature engineering |
| C1–C3 | PASS/N/A | Future paths are used only for descriptive outcomes; no model training |
| F1–F4 | N/A | No session or timezone classification |
| G1 | N/A | Immutable accepted inputs |
| G2 | PASS | No gap filling or stale-price propagation |
| G3–G4 | N/A | No resampling or indicators |
| H1 | PASS | Configured 0.75 ATR touch uses adverse intrabar high/low geometry |
| H2 | PASS | Stop monitoring uses one-second path rows |
| H3 | N/A | One fixed canonical entry per trade; no re-entry simulation |
| H4 | PASS | All executed resolved stops use actual next-row open timestamp and price |

## Referred to contract-checker

None.

---

*Read-only causal completion audit complete. The executed 0.75 ATR results
preserve the audited event ordering and are causally clean.*
