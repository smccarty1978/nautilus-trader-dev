# Pre-Execution Causal Audit — Post-Confirmation MFE and Model Exits

**Date:** 2026-07-27  
**Pass:** 21  
**Auditor:** lookahead-auditor  
**Scope hash:** `169af2df969fd3532c61a9672010a2fb66ec325617b47ca4db506e0baded318c`

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

**FIXED — remains fixed.**

`candidate_collision` remains preserved through combined event selection and
forces `AMBIGUOUS EVENT ORDER` with null realized return.

### Pass 09 [H4] — next-bar-open fill timestamped at next-bar close

**FIXED — remains fixed.**

All price and model candidates continue to use the next path row's open
timestamp and open price.

## New findings

None.

## Scope-refresh review

- Baseline input selection now uses the explicit mapping
  `0.75 -> baseline_0_75`, `1.00 -> baseline_1_00`, and
  `1.25 -> baseline_1_25`.
- The mapping changes only which configured accepted artifact is opened. It
  does not change timestamps, stop geometry, score state, MFE state,
  confirmation gating, event competition, or fill mechanics.
- Each selected baseline still fails closed unless all 5,836 rows and exact
  frozen outcome counts reconcile.
- Dynamic floors still use prior completed-bar MFE.
- Persistence still counts fresh unique score observations and resets on domain
  exit.
- Model-triggered tightening remains delayed until after both warning and price
  activation are known.
- Combined same-bar candidate collisions remain explicitly ambiguous.

## Checklist matrix

| Rules | Status | Basis |
|---|---|---|
| A1–A5 | PASS/N/A | Completed close timestamps drive signals; next-open timestamps drive fills |
| B1–B7, B9–B10 | PASS/N/A | Prior-bar MFE and fresh score sources remain causal |
| C1–C3 | PASS/N/A | Future paths are outcome simulation only; no model fitting or split |
| F1–F4 | N/A | No session or timezone classification |
| G1 | N/A | Immutable accepted inputs |
| G2 | PASS | No price-gap filling or persistence inflation |
| G3–G4 | N/A | No resampling or indicator computation |
| H1 | PASS | Price/stop touches use adverse one-second intrabar geometry |
| H2 | PASS | Policies replay one-second paths |
| H3 | N/A | Fixed one-entry population; no re-entry |
| H4 | PASS | Next-open fills and simultaneous terminal candidates remain causal |

## Referred to contract-checker

None.

---

*Read-only pre-execution causal audit complete. The baseline-key setup fix does
not alter causal policy logic, and the current scope remains clean.*
