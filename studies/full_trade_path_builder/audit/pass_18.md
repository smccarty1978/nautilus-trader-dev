# Causal Completion Audit — Top-2.5% 1.00 ATR Stop Repeat

**Date:** 2026-07-27  
**Pass:** 18  
**Auditor:** lookahead-auditor  
**Scope hash:** `00aec4a5a4827b6eaf670a72fdf95d38b5455735b40e630ab3a5fa9807d1e5d7`

## Scope

- `TOP2_5_FIRST_SIGNAL_STOP_1_00_REGIME_EXIT_SPEC.md`
- `config/top2_5_first_signal_stop_1_00_regime_exit.yaml`
- `analysis/analyze_top2_5_stop_and_regime_exit.py`
- `tests/test_top2_5_stop_and_regime_exit.py`
- `TOP2_5_FIRST_SIGNAL_STOP_1_25_REGIME_EXIT_SPEC.md` as the incorporated
  inherited contract
- `results/top2_5_stop_1_00_regime_exit_results.parquet`
- `results/top2_5_stop_1_00_regime_exit_summary.json`
- `results/top2_5_stop_1_00_run_status.json`
- `TOP2_5_STOP_1_00_REGIME_EXIT_REPORT.md`
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

**FIXED — remains fixed in the executed 1.00 ATR artifacts.**

Both classifier paths use the next row's open timestamp and price. Direct
result-to-path reconciliation found 3,358 resolved stops, 3,358 exact
next-open timestamp/price matches, and zero mismatches.

All other prior causal passes remain clean for their respective scopes.

## New findings

None.

## Completion evidence reviewed

- The bounded run completed with exit code 0.
- `stop_atr` is 1.00 in configuration, vectorized detection, independent
  replay, summary conventions, and report disclosure.
- All 5,836 entries have one mutually exclusive outcome.
- The result contains 14 ambiguous trades. All 14 have an exact stop
  touch/fill equality with a confirmation or fallback boundary, none encodes
  the former fill-bar-close defect, and all 14 have null realized return.
- Stop touches use completed one-second high/low geometry; resolved stop PnL
  uses the following path bar's open rather than the trigger price.
- Final-bar touches without an observable next open remain censored.
- Fixed-seed replay checked 100 trades with zero classification mismatches.
- Generated evidence reports 2,149 stops before confirmation, 1,209 stops after
  confirmation, 14 ambiguous trades, and 78 censored trades; these reconcile
  with the regime-flip outcomes to 5,836.
- Canonical inputs are not modified.

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
| H1 | PASS | Configured 1.00 ATR touch uses adverse intrabar high/low geometry |
| H2 | PASS | Stop monitoring uses one-second path rows |
| H3 | N/A | One fixed canonical entry per trade; no re-entry simulation |
| H4 | PASS | All executed resolved stops use actual next-row open timestamp and price |

## Referred to contract-checker

None.

---

*Read-only causal completion audit complete. The executed 1.00 ATR results
preserve the audited event ordering and are causally clean.*
