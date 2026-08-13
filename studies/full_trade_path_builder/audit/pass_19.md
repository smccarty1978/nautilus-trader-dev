# Pre-Execution Causal Audit — Post-Confirmation MFE and Model Exits

**Date:** 2026-07-27  
**Pass:** 19  
**Auditor:** lookahead-auditor  
**Scope hash:** `8b07fb2b26d811a4a6d24fd414f4de9f10cd4efe1d6425cf245ff28c22db15dd`

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

- Critical: 1
- Warning: 0
- Note: 0
- Verdict: **FAIL**

## Prior-finding adjudication

### Pass 09 [H4] — next-bar-open fill timestamped at next-bar close

**FIXED — remains fixed.**

All newly simulated price and model candidates inherit
`candidate_fill_ns = next_row.timestamp_open_ns` and
`candidate_fill_price = next_row.open`. No trigger price or fill-bar close is
credited as an execution.

## Critical findings

### [H4] `analysis/analyze_post_confirmation_mfe_and_model_exits.py:621-663` — simultaneous price and model triggers are silently ordered

The combined first-event branch joins the first price-management touch and the
persistence-1 model warning, then selects the price event only when
`p_touch < m_touch`. When both events occur on the same completed bar,
lines 640-651 silently select the model event through the `otherwise` branch.
The original two timestamps are then discarded at lines 652-656, so
`apply_event` cannot recognize their collision and mark it ambiguous.

This violates the frozen rule that a model warning coincident with another
terminal signal is `AMBIGUOUS EVENT ORDER`. It also imposes an unsupported
within-bar ordering on one-second OHLC/checkpoint data.

A read-only evaluation of the immutable paths found eight simultaneous
price/model candidate pairs across the representative first-event policies.
At least two occur in universally supported Top-5 or Top-2.5 policies
(`P1_top_5` and `P1_top_2_5`), independent of the unsupported bearish Top-10
branch. Those candidates will be treated as an ordinary chosen event whenever
they precede the applicable baseline terminal event rather than being
conservatively ambiguous.

**Recommended fix (do not apply):** retain an explicit
`price_model_same_touch` flag when `p_touch == m_touch`, propagate it into the
candidate event, and make `apply_event` classify that collision as
`AMBIGUOUS EVENT ORDER` with null realized return.

## Clean causal checks

- Dynamic price floors use `prior_mfe_atr`, shifted within each sorted trade,
  so current-bar MFE cannot arm or raise a floor on the same bar.
- Price management is confirmation-gated. A pre-armed floor violated on the
  confirmation bar is classified ambiguous.
- Opposing-model selection is bearish for SHORT and bullish for LONG.
- Warning persistence filters carried rows and counts fresh score-source
  observations only; domain exit resets the run.
- Already-active-at-confirmation state is diagnostic and does not trigger an
  exit. New warnings require a post-confirmation below-to-above crossing.
- Model-triggered tightening first applies on a bar strictly after the warning,
  and price activation is based on prior completed-bar MFE.
- Individual price/model candidates, initial stops, and regime boundaries use
  next-open fills and conservative boundary competition.
- No fuzzy time join, resampling, forward fill, random train/test split, or
  session conversion exists.

## Checklist matrix

| Rules | Status | Basis |
|---|---|---|
| A1–A5 | PASS/N/A | Completed close timestamps drive signals; next-open timestamps drive fills |
| B1 | PASS | No centered rolling computation |
| B2 | PASS | Dynamic floors use prior completed-bar MFE |
| B3–B7 | PASS/N/A | No recursive indicator, negative lag, fill, as-of join, or global normalization |
| B9–B10 | PASS/N/A | Score cadence/source semantics are explicit; no new tracker variant |
| C1–C3 | PASS/N/A | Future paths are outcome simulation only; no model fitting or split |
| F1–F4 | N/A | No session or timezone classification |
| G1 | N/A | Immutable accepted inputs |
| G2 | PASS | No price-gap filling; score persistence counts available unique sources |
| G3–G4 | N/A | No resampling or indicator computation |
| H1 | PASS | Price/stop touches use adverse one-second intrabar geometry |
| H2 | PASS | Policies replay one-second paths |
| H3 | N/A | Fixed one-entry population; no re-entry |
| H4 | CRITICAL | Individual fills are correct, but combined same-bar events are silently ordered |

## Referred to contract-checker

None.

---

*Read-only pre-execution causal audit complete. Combined-event ambiguity must be
fixed before first execution.*
