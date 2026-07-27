# Pre-Execution Causal Audit — Top-2.5% Stop and Regime Exit

**Date:** 2026-07-26  
**Pass:** 09  
**Auditor:** lookahead-auditor  
**Scope hash:** `1fc9300875a2ce2ec68014268d5ee66793447b54e05afce76a77b5c2d6c6cfb9`

## Scope

- `TOP2_5_FIRST_SIGNAL_STOP_1_25_REGIME_EXIT_SPEC.md`
- `config/top2_5_first_signal_stop_1_25_regime_exit.yaml`
- `analysis/analyze_top2_5_stop_and_regime_exit.py`
- `tests/test_top2_5_stop_and_regime_exit.py`
- Immutable canonical summary and one-second path inputs

Per `docs/CAUSAL_CHECKLIST.md` SCOPE SPLIT, this pass covers only A, B,
C1–C3, F, G, and H.

## Summary

- Critical: 1
- Warning: 0
- Note: 0
- Verdict: **FAIL**

## Prior-finding adjudication

Passes 01 through 08 contained no causal findings. Those clean verdicts remain
valid for their respective scopes. Pass 09 audits new stop/exit simulation code.

## Critical findings

### [H4] `analysis/analyze_top2_5_stop_and_regime_exit.py:131-135,157-163` — next-bar-open fill is timestamped at next-bar close

The stop fill price correctly comes from the next path bar's `open`, but
`stop_fill_ns` is assigned from that bar's `timestamp_close_ns`. The ambiguity
test then compares this close timestamp with `confirm_flip_ns` and
`fallback_exit_flip_ns`.

This contradicts the frozen ordering contract at
`TOP2_5_FIRST_SIGNAL_STOP_1_25_REGIME_EXIT_SPEC.md:49-57`: the simulated market
exit fills at the next bar **open**. A boundary at that next bar's close occurs
after the fill and is not simultaneous with it.

Concrete failure path: for a stop touched on bar N, if bar N+1 closes at a
confirmation or opposing-flip boundary, lines 161-163 classify the trade as
`AMBIGUOUS EVENT ORDER` even though the stop already filled at bar N+1's open.
A read-only evaluation of the immutable inputs found 11 such false ambiguity
classifications at the frozen 1.25 ATR threshold; comparison using
`timestamp_open_ns` found zero competing fills.

**Recommended fix (do not apply):** assign the next row's
`timestamp_open_ns` to `stop_fill_ns` while retaining its `open` as the fill
price, and make the independent replay use that same open timestamp.

## Clean causal checks

- Stop detection uses the completed one-second bar's adverse high/low extreme,
  not its close.
- First stop touches are explicitly ordered by trade and path sequence.
- Stop PnL uses the next path bar's open price, not the trigger level.
- Stop touches on the same completed bar as confirmation or fallback are
  conservatively marked ambiguous.
- Final-bar touches without a next path row are censored.
- No feature engineering, model fitting, random train/test split, resampling,
  forward fill, or session conversion exists.

## Checklist matrix

| Rules | Status | Basis |
|---|---|---|
| A1–A5 | PASS/N/A | Completed one-second close timestamps are used for path events; no NT construction or resampling |
| B1–B7, B9–B10 | N/A | No feature engineering |
| C1–C3 | PASS/N/A | Future path data is confined to outcome construction; no model training |
| F1–F4 | N/A | No session or timezone classification |
| G1 | N/A | Immutable accepted inputs |
| G2 | PASS | No gap filling or stale-price propagation |
| G3–G4 | N/A | No resampling or indicators |
| H1 | PASS | Stop touch uses adverse intrabar high/low geometry |
| H2 | PASS | Simulation uses one-second canonical path rows |
| H3 | N/A | One fixed canonical entry per trade; no re-entry simulation |
| H4 | CRITICAL | Fill price is next-bar open, but fill timestamp incorrectly uses next-bar close |

## Referred to contract-checker

None.

---

*Read-only pre-execution causal audit complete. The H4 timestamp defect blocks
first execution.*
