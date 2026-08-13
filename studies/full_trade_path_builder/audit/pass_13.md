# Pre-Execution Causal Audit — Top-2.5% 0.75 ATR Stop Repeat

**Date:** 2026-07-26  
**Pass:** 13  
**Auditor:** lookahead-auditor  
**Scope hash:** `98d68dd4452a918f3a68f02b1238af599171a28ced9c40358c839d35b35d304f`

## Scope

- `TOP2_5_FIRST_SIGNAL_STOP_0_75_REGIME_EXIT_SPEC.md`
- `config/top2_5_first_signal_stop_0_75_regime_exit.yaml`
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

The genericized vectorized path continues to assign `stop_fill_ns` from the
next row's `timestamp_open_ns` and `stop_fill_price` from its `open`. The
independent replay uses the same next-row open timestamp. No fill-bar close is
used as a fill time.

All other prior causal passes remain clean for their respective scopes.

## New findings

None.

## Amendment review

- The stop distance is read once from `config["stop_atr"]` as `0.75`.
- The same value drives vectorized first-touch detection
  (`adverse_intrabar_extreme_atr <= -stop_atr`), independent replay, summary
  conventions, and generated report wording.
- Touch detection remains based on completed one-second high/low geometry.
- Same-touch-bar boundary events and genuine next-open/boundary collisions
  remain ambiguous.
- Final-bar touches without an observable next path open remain censored.
- Stop PnL remains based on the next path bar's open, never the threshold
  trigger price.
- The threshold change does not alter entry selection, timestamps, features,
  labels, session handling, or immutable canonical inputs.

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
| H4 | PASS | Stop fills use actual next-row open timestamp and price |

## Referred to contract-checker

None.

---

*Read-only pre-execution causal audit complete. The 0.75 ATR repeat preserves
the audited stop mechanics and is causally clean.*
