# Corrected Pre-Execution Causal Audit — Post-Confirmation MFE and Model Exits

**Date:** 2026-07-27  
**Pass:** 22  
**Auditor:** lookahead-auditor  
**Scope hash:** `3ebcb7cac4db55c2e2da38d17987b24827d37e5f0b01736efeafd02b9b6c675e`

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

### Self-detected pre-execution defect — null competition suppressed valid candidates

**FIXED.**

The entire terminal-competition expression is now wrapped with
`.fill_null(False)`. An absent baseline `stop_touch_ns` can no longer turn
`same` and subsequently `wins` into null; a causally earlier candidate with an
observable next-open fill is permitted to win.

All outputs produced before this correction are explicitly rejected and are
not part of this audit scope.

### Pass 19 [H4] — simultaneous price and model triggers silently ordered

**FIXED — remains fixed.**

`candidate_collision` remains preserved and forces
`AMBIGUOUS EVENT ORDER` with null realized return.

### Pass 09 [H4] — next-bar-open fill timestamped at next-bar close

**FIXED — remains fixed.**

All candidate exits continue to use the next path row's open timestamp and
open price.

## New findings

None.

## Current causal review

- Dynamic floors use MFE from the prior completed bar; current-bar activation
  or peak cannot create a same-bar assumed exit.
- Price rules cannot execute before confirmation. Confirmation-bar floor
  competition remains ambiguous.
- Opposing score selection is bearish for SHORT and bullish for LONG.
- Persistence counts fresh score-source observations only, never carried
  one-second rows, and resets on domain exit.
- Already-active-at-confirmation state remains diagnostic; warnings require a
  new post-confirmation crossing.
- Model-triggered tightening applies only after both its warning and prior-bar
  price activation are known.
- Combined first-event rows preserve the winning dynamic exit label while equal
  price/model touches remain ambiguous.
- Candidate competition against initial stop, confirmation, and opposing flip
  treats null absence as false rather than unknown, without weakening genuine
  timestamp equalities.
- Transition and subgroup tables aggregate completed policy outcomes only and
  do not feed policy construction or selection state.
- Independent replay reconstructs P1 prior-MFE activation and Top-5 warning
  timestamps from sequential path rows.
- No fuzzy timestamp match, resampling, stale-price fill, random train/test
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
| G2 | PASS | No price-gap filling or carried-row persistence inflation |
| G3–G4 | N/A | No resampling or indicator computation |
| H1 | PASS | Price/stop touches use adverse one-second intrabar geometry |
| H2 | PASS | Policies replay one-second paths |
| H3 | N/A | Fixed one-entry population; no re-entry |
| H4 | PASS | Null-safe competition, simultaneous ambiguity, and next-open fills are causal |

## Referred to contract-checker

None.

---

*Read-only corrected pre-execution audit complete. The null-propagation defect
is fixed, prior H4 fixes remain intact, and the current scope is causally clean.*
