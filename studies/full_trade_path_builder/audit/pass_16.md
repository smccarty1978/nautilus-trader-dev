# Pre-Execution Causal Audit — Top-2.5% 1.00 ATR Stop Repeat

**Date:** 2026-07-27  
**Pass:** 16  
**Auditor:** lookahead-auditor  
**Scope hash:** `a747a802f41891cf50687f308e04229f6b05e222116e4f2a4cee941c40d5470e`

## Scope

- `TOP2_5_FIRST_SIGNAL_STOP_1_00_REGIME_EXIT_SPEC.md`
- `config/top2_5_first_signal_stop_1_00_regime_exit.yaml`
- `analysis/analyze_top2_5_stop_and_regime_exit.py`
- `tests/test_top2_5_stop_and_regime_exit.py`
- `TOP2_5_FIRST_SIGNAL_STOP_1_25_REGIME_EXIT_SPEC.md` as the incorporated
  inherited contract
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

**FIXED — remains fixed.**

The generic vectorized classifier assigns `stop_fill_ns` from the next path
row's `timestamp_open_ns` and `stop_fill_price` from its `open`. Independent
replay uses the same next-row open timestamp. The 1.00 ATR configuration does
not alter these mechanics.

All other prior causal passes remain clean for their respective scopes.

## New findings

None.

## Amendment review

- `stop_atr: 1.00` is loaded from the new configuration.
- That value drives vectorized first-touch detection
  (`adverse_intrabar_extreme_atr <= -stop_atr`) and the independent replay's
  identical comparison.
- The same value is persisted in summary conventions and formats as `1.00` in
  the generated report title and touch-method disclosure.
- Stop detection remains based on completed one-second high/low geometry.
- Same-touch-bar regime boundaries and genuine next-open/boundary collisions
  remain ambiguous.
- Final-bar touches without an observable next path open remain censored.
- Stop PnL remains based on the next path bar's open, never the threshold
  trigger price.
- No entry selection, timestamp, feature, label, session, or canonical input is
  changed.

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
| H4 | PASS | Stop fills use actual next-row open timestamp and price |

## Referred to contract-checker

None.

---

*Read-only pre-execution causal audit complete. The 1.00 ATR repeat preserves
the audited stop mechanics and is causally clean.*
