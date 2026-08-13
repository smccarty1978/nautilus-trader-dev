# Pre-Execution Causal Audit — Top-2.5% Stop and Regime Exit

**Date:** 2026-07-26  
**Pass:** 10  
**Auditor:** lookahead-auditor  
**Scope hash:** `da0e6a12d2ea56ce23c8d67eea504cf12b631a8a012a5386d341e2155e604e81`

## Scope

- `TOP2_5_FIRST_SIGNAL_STOP_1_25_REGIME_EXIT_SPEC.md`
- `config/top2_5_first_signal_stop_1_25_regime_exit.yaml`
- `analysis/analyze_top2_5_stop_and_regime_exit.py`
- `tests/test_top2_5_stop_and_regime_exit.py`
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

**FIXED.**

- The vectorized path now assigns `stop_fill_ns` from the next row's
  `timestamp_open_ns` while retaining that row's `open` as `stop_fill_price`
  (`analysis/analyze_top2_5_stop_and_regime_exit.py:131-135`).
- The independent replay uses the same next-row `timestamp_open_ns`
  (`analysis/analyze_top2_5_stop_and_regime_exit.py:74-83`).
- Confirmation/fallback competition therefore compares each boundary with the
  actual simulated fill time, not the fill bar's later close.

Passes 01 through 08 contained no causal findings and remain clean for their
respective scopes.

## New findings

None.

## Clean causal checks

- Stop detection uses the completed one-second bar's adverse high/low extreme,
  not its close.
- First stop touches are explicitly sorted by trade and path sequence.
- Stop fills use both the next path bar's open timestamp and open price.
- A stop touch on the same completed bar as confirmation or fallback is
  conservatively classified as ambiguous.
- A genuine fill-time/boundary collision is classified as ambiguous; a boundary
  at the later close of the fill bar is not.
- Final-bar touches without a next path row are censored.
- Future path values are confined to descriptive outcome construction and do
  not feed features, signals, labels, or model selection.
- No resampling, forward fill, session conversion, or re-entry simulation
  exists.

## Checklist matrix

| Rules | Status | Basis |
|---|---|---|
| A1–A5 | PASS/N/A | Completed one-second close timestamps identify path events; next-open time identifies fills |
| B1–B7, B9–B10 | N/A | No feature engineering |
| C1–C3 | PASS/N/A | Future path data is confined to outcomes; no model training or split |
| F1–F4 | N/A | No session or timezone classification |
| G1 | N/A | Immutable accepted inputs |
| G2 | PASS | No gap filling or stale-price propagation |
| G3–G4 | N/A | No resampling or indicators |
| H1 | PASS | Stop touch uses adverse intrabar high/low geometry |
| H2 | PASS | Simulation uses one-second canonical path rows |
| H3 | N/A | One fixed canonical entry per trade; no re-entry simulation |
| H4 | PASS | Stop exit uses actual next-row open time and price |

## Referred to contract-checker

None.

---

*Read-only pre-execution causal audit complete. The prior H4 defect is fixed and
the current scope is causally clean.*
