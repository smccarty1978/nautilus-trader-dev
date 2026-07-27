# Causal Completion Audit — Post-Confirmation MFE and Model Exits

**Date:** 2026-07-27  
**Pass:** 23  
**Auditor:** lookahead-auditor  
**Scope hash:** `d870bbfd2a30880b9776eae438b4ed9ece51433c43684aa211c3add0a5f1fa39`

## Scope

- `POST_CONFIRMATION_MFE_MODEL_EXIT_SPEC.md`
- `config/post_confirmation_mfe_model_exits.yaml`
- `analysis/analyze_post_confirmation_mfe_and_model_exits.py`
- `tests/test_post_confirmation_mfe_model_exits.py`
- `implementation/canonical_research_loader.py`
- `TOP2_5_FIRST_SIGNAL_STOP_1_25_REGIME_EXIT_SPEC.md` and accepted baseline
  stop conventions
- `POST_CONFIRMATION_MFE_AND_MODEL_EXIT_REPORT.md`
- `results/post_confirmation_mfe_model_exit_summary.json`
- `results/post_confirmation_mfe_model_exit_trade_policy_results.parquet`
- `results/post_confirmation_model_warning_events.parquet`
- `results/post_confirmation_policy_cross_stop_comparison.parquet`
- `results/post_confirmation_mfe_model_exit_run_status.json`
- Immutable canonical observations, summaries, paths, and accepted baseline
  artifacts

Per `docs/CAUSAL_CHECKLIST.md` SCOPE SPLIT, this pass covers only A, B,
C1–C3, F, G, and H.

## Summary

- Critical: 0
- Warning: 0
- Note: 0
- Verdict: **PASS**

## Prior-finding adjudication

### Self-detected null competition suppression

**FIXED — remains fixed in executed outputs.**

Supported candidates are no longer suppressed by an absent baseline stop. The
executed artifact contains 245,143 supported winning trade-policy rows; none
has a null return or an exit timestamp different from its candidate fill.

### Pass 19 [H4] — simultaneous price and model triggers silently ordered

**FIXED — remains fixed in executed outputs.**

Combined collisions propagate to `candidate_ambiguity`,
`AMBIGUOUS EVENT ORDER`, and null realized return. Across supported policy
rows, all 15,931 ambiguity flags have that exact terminal/null treatment.

### Pass 09 [H4] — next-bar-open fill timestamped at next-bar close

**FIXED — remains fixed in executed outputs.**

The 245,143 supported winning policy rows reduce to 35,016 distinct
trade/fill/return combinations. Every fill timestamp matches an actual
canonical next-path-row open, and every realized return exactly matches that
open price; zero fills or returns mismatch.

## New findings

None.

## Completion evidence reviewed

- The bounded run completed with exit code 0.
- The trade-policy artifact contains 1,067,988 rows and 1,067,988 unique
  `trade_id + initial_stop_atr + policy_id` keys.
- All three accepted baselines reconcile exactly to 5,836 trades and their
  frozen outcome counts.
- Dynamic floors use prior completed-bar MFE. Current-bar activation and peak
  values do not arm or raise a same-bar floor.
- Warnings use the directionally correct opposing model, fresh score-source
  rows only, post-confirmation crossings, and domain-reset persistence.
  Executed warning diagnostics contain no warning at or before confirmation;
  persistence-2 and persistence-3 timestamps are strictly later than their
  predecessor.
- Model-triggered tightening contains no candidate touch at or before its
  persistence-1 warning.
- Combined first-event labels retain whether price or model produced the
  earlier candidate, while exact ties remain ambiguous.
- The independent validation covers 300 trade-stop cases and reports zero
  mismatches for baseline outcome, timestamp order, monotonic MFE, P1 touch,
  and Top-5 warning timing.
- Landmark diagnostics are descriptive only. Each recorded opposing score
  source is at or before its landmark close timestamp; zero landmarks use a
  future score source. Peak/final/remaining-MFE fields are outcome diagnostics
  and do not feed policy state or ranking inputs.
- Warning-usefulness, subgroup, transition, and cross-stop tables aggregate
  completed outcomes only and do not alter the simulated event stream.

## Checklist matrix

| Rules | Status | Basis |
|---|---|---|
| A1–A5 | PASS/N/A | Completed close timestamps drive signals/landmarks; next-open timestamps drive fills |
| B1 | PASS | No centered rolling computation |
| B2 | PASS | Dynamic floors use prior completed-bar MFE |
| B3–B7 | PASS/N/A | No recursive indicator, negative lag, fill, as-of join, or global normalization |
| B9–B10 | PASS/N/A | Score cadence/source semantics are explicit and executed persistence uses fresh sources |
| C1–C3 | PASS/N/A | Future path extrema are descriptive outcomes only; no model fitting or split |
| F1–F4 | N/A | No session or timezone classification |
| G1 | N/A | Immutable accepted inputs |
| G2 | PASS | No price-gap filling or carried-row persistence inflation |
| G3–G4 | N/A | No resampling or indicator computation |
| H1 | PASS | Price/stop touches use adverse one-second intrabar geometry |
| H2 | PASS | Policies replay one-second paths |
| H3 | N/A | Fixed one-entry population; no re-entry |
| H4 | PASS | Executed competition, ambiguity, and next-open fills reconcile exactly |

## Referred to contract-checker

None.

---

*Read-only causal completion audit complete. The executed broad study preserves
all corrected event-ordering contracts and is causally clean.*
