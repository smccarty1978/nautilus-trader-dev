# Causal Completion Audit — Top-2.5% Stop and Regime Exit

**Date:** 2026-07-26  
**Pass:** 12  
**Auditor:** lookahead-auditor  
**Scope hash:** `b96281d576cc7f17917f787054fd10baadcfae312f91e6c233b2f842070c0d32`

## Scope

- `TOP2_5_FIRST_SIGNAL_STOP_1_25_REGIME_EXIT_SPEC.md`
- `config/top2_5_first_signal_stop_1_25_regime_exit.yaml`
- `analysis/analyze_top2_5_stop_and_regime_exit.py`
- `tests/test_top2_5_stop_and_regime_exit.py`
- `implementation/canonical_research_loader.py`
- `results/top2_5_stop_1_25_regime_exit_results.parquet`
- `results/top2_5_stop_1_25_regime_exit_summary.json`
- `results/top2_5_stop_1_25_run_status.json`
- `TOP2_5_STOP_1_25_REGIME_EXIT_REPORT.md`
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

**FIXED — remains fixed in the executed artifacts.**

- Both vectorized classification and independent replay use the next path row's
  `timestamp_open_ns` and `open` for stop fills.
- The executed result contains 14 ambiguous trades. All 14 have a genuine
  equality between stop touch/fill time and a confirmation/fallback boundary;
  none is ambiguous merely because the fill bar later closes at a boundary.
- All 14 ambiguous trades have null realized return, so no favorable fill order
  is imposed.

Passes 01 through 08 contained no causal findings and remain clean for their
respective scopes.

## New findings

None.

## Completion evidence reviewed

- The bounded process completed with exit code 0.
- All 5,836 canonical summaries map to one mutually exclusive outcome.
- Stop detection uses completed one-second high/low geometry through
  `adverse_intrabar_extreme_atr <= -1.25`.
- The executed results contain 2,716 resolved stops, each valued from the next
  path bar's open rather than the trigger price.
- Same-touch-bar regime events and genuine fill-time boundary collisions remain
  ambiguous; final-bar touches without an observable next open remain censored.
- Fixed-seed replay checked 100 trades with zero classification mismatches.
- Generated evidence reports 1,855 stops before confirmation, 861 stops after
  confirmation, 14 ambiguous trades, and 98 censored trades; counts reconcile
  to the full population with the regime-flip outcome classes.
- Canonical data is accessed through the lazy canonical loader and is not
  modified.

## Checklist matrix

| Rules | Status | Basis |
|---|---|---|
| A1–A5 | PASS/N/A | Completed one-second closes identify events; next-open timestamps identify fills |
| B1–B7, B9–B10 | N/A | No feature engineering |
| C1–C3 | PASS/N/A | Future paths are used only to construct descriptive outcomes; no model training |
| F1–F4 | N/A | No session or timezone classification |
| G1 | N/A | Immutable accepted continuous-contract inputs |
| G2 | PASS | No gap filling or stale-price propagation |
| G3–G4 | N/A | No resampling or indicators |
| H1 | PASS | Stop touch uses adverse intrabar high/low geometry |
| H2 | PASS | Stop monitoring uses one-second path rows |
| H3 | N/A | One fixed canonical entry per trade; no re-entry simulation |
| H4 | PASS | Executed stop fills use the actual next-row open timestamp and price |

## Referred to contract-checker

None.

---

*Read-only causal completion audit complete. Executed classification preserves
the corrected event ordering and is causally clean.*
