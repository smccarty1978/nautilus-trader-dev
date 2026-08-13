# Pre-Execution Causal Audit — Post-Confirmation MFE and Model Exits

**Date:** 2026-07-27  
**Pass:** 20  
**Auditor:** lookahead-auditor  
**Scope hash:** `5db8493eeac0834021fe845813ca30b796719f65b24cf3fd2b887b78d46a5c7a`

## Scope

- `POST_CONFIRMATION_MFE_MODEL_EXIT_SPEC.md`
- `config/post_confirmation_mfe_model_exits.yaml`
- `analysis/analyze_post_confirmation_mfe_and_model_exits.py`
- `tests/test_post_confirmation_mfe_model_exits.py`
- `implementation/canonical_research_loader.py`
- `TOP2_5_FIRST_SIGNAL_STOP_1_25_REGIME_EXIT_SPEC.md` and accepted stop
  conventions inherited by the 0.75/1.00/1.25 baselines
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

### Pass 19 [H4] — simultaneous price and model triggers silently ordered

**FIXED.**

- The combined join now records `candidate_collision` when both original touch
  timestamps are non-null and equal
  (`analysis/analyze_post_confirmation_mfe_and_model_exits.py:646-650`).
- The collision flag is preserved through candidate selection
  (`analysis/analyze_post_confirmation_mfe_and_model_exits.py:663-666`).
- `apply_event` includes that flag in its `same` predicate and classifies the
  event `AMBIGUOUS EVENT ORDER` with null realized return
  (`analysis/analyze_post_confirmation_mfe_and_model_exits.py:187-223`).

### Pass 09 [H4] — next-bar-open fill timestamped at next-bar close

**FIXED — remains fixed.**

All price and model candidates continue to use the next path row's open
timestamp and open price.

## New findings

None.

## Clean causal checks

- Dynamic floors use prior completed-bar MFE; current-bar activation or peak
  cannot produce a same-bar assumed exit.
- Confirmation gating remains explicit. A pre-armed floor touched on the
  confirmation bar is ambiguous.
- Opposing score selection remains bearish for SHORT and bullish for LONG.
- Persistence counts only fresh score-source observations, not carried
  one-second rows; domain exit resets the run.
- Already-active-at-confirmation state is diagnostic. New warning exits require
  a post-confirmation crossing.
- Model-triggered tightening applies no earlier than the bar after its warning
  and uses prior-bar price activation state.
- Individual and combined events preserve same-bar ambiguity against price,
  model, initial-stop, confirmation, and opposing-flip signals.
- All simulated exits use the following path bar's open timestamp and price.
- No fuzzy timestamp matching, resampling, forward fill, random train/test
  split, or session conversion exists.

## Checklist matrix

| Rules | Status | Basis |
|---|---|---|
| A1–A5 | PASS/N/A | Completed close timestamps drive signals; next-open timestamps drive fills |
| B1 | PASS | No centered rolling computation |
| B2 | PASS | Dynamic floors use prior completed-bar MFE |
| B3–B7 | PASS/N/A | No recursive indicator, negative lag, fill, as-of join, or global normalization |
| B9–B10 | PASS/N/A | Score cadence/source semantics are explicit |
| C1–C3 | PASS/N/A | Future paths are outcome simulation only; no model fitting or split |
| F1–F4 | N/A | No session or timezone classification |
| G1 | N/A | Immutable accepted inputs |
| G2 | PASS | No price-gap filling; persistence counts available unique sources |
| G3–G4 | N/A | No resampling or indicator computation |
| H1 | PASS | Price/stop touches use adverse one-second intrabar geometry |
| H2 | PASS | Policies replay one-second paths |
| H3 | N/A | Fixed one-entry population; no re-entry |
| H4 | PASS | Next-open fills and all simultaneous terminal candidates are handled causally |

## Referred to contract-checker

None.

---

*Read-only pre-execution causal audit complete. The pass-19 collision defect is
fixed and the current scope is causally clean.*
