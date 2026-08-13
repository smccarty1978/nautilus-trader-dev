# Contract Audit — post_confirmation_score_deterioration — RECONCILIATION — Pass 02

**Date:** 2026-08-10
**Scope:** bounded to the `reconciliation/` deliverable, plus adjudication of pass 1.
Deliverables, seals, terminal-label reachability, C4/D/E only. Causality is out of
scope — `lookahead-auditor` pass 2: PASS, 0 critical, 1 warning (since fixed).
**Verdict: CLEAR.**

> Authored by the `contract-checker` agent and persisted by the main session,
> which has the Write tool the agent lacks. The table is verbatim; the closing
> correction was added afterwards.

## Adjudication of pass 1 (study proper)

All three findings **RESOLVED**, verified against the pass-1 `contract_status.json`
resolution fields and the artifacts themselves: `analysis/escalation_recovery.py`
written and its finding added to REPORT.md §5.3; `landmark_features.json` and
`divergence.json` present under their manifest names; `build_panel.py` hash glob
extended to `analysis/*.py`. No re-raise.

## Compliance table

| Requirement | Verdict | Evidence | Remediation |
|---|---|---|---|
| Five artifacts exist and are populated | PASS | all present in `reconciliation/`, read in full; `reconcile.py main()` writes all five in one run | — |
| Report opens with EXECUTIVE VERDICT and answers all six questions | PASS | `SCORE_STREAM_RECONCILIATION_REPORT.md` — verdict block then six numbered Q&A sections, each with figures cross-checked against the JSON artifacts | — |
| Phase 2 sample strata (≥50 trades, all four labels, both sides, zero-observation, both-accept, short-lived failures, long-lived winners) | PASS | verified against `reconcile.py:346-355` sampling logic rather than report prose: 8/label × 4, 6/side × 2, 12 zero-strict, 10 both-valid, 8 hold ≤ 120s failures, 8 hold ≥ 1200s. 76 trades / 242 rows | — |
| Phase 2 per-row fields | PASS | `reconcile.py:370-429` carries identity, canonical `bullish/bearish_probability`, both `*_in_domain` flags, true dispatch timestamp, `score_observation_id`, expected model, contract flags, and `code_path_score_selection` citing exact file:line | — |
| Exactly one terminal classification, not softened, defensible vs A/C/D/E | PASS | B is the sole label; supported by Phase 3 exact Codex match and Phase 4 in-domain counts 0 / 0 / 61 / 525. Correctly scoped as provenance — B's economic basis is the pre-existing placebo null, untouched here | — |
| "Do not re-optimize / rerun / change thresholds / alter collector" honoured | PASS | the single `phase0_gate1.py` re-run is a verified bit-identical cosmetic rename (lookahead-auditor pass 2), AUCs 0.6843 / 0.7353 / 0.7527 / 0.7801 before and after. A documentation-accuracy fix, not a re-optimization | — |
| REPORT.md / README.md updated consistently | PASS | both now carry the 0% / 0% / 1.6% / 16.4% contract-validity figures and label the AUC "exploratory out-of-domain evidence, not deployable evidence" | — |
| Phase 3/4 independence from the study's own panel | PASS | `post_confirm_rows()` reads only `canonical_regime_scores_all.parquet`; `results/post_confirm_paths.parquet` is never opened in `reconcile.py`. The Codex reproduction is therefore not circular | — |
| Sample parquet `score_is_new` flag for SHORT trades | WARNING → see correction | `reconcile.py:417-421` read as an unconditional bullish read | branch on direction |
| lint / audit trio | PASS | `lint.json` 0 critical / 0 warning over 15 files; `pass_02.md` PASS | — |

## Referred to lookahead-auditor

None — the one open item had already been raised and dispositioned there.

## Blocking verdict

**CLEAR.** All five reconciliation artifacts exist with the required content. The
executive-verdict and six-question structure are present and answered with figures
traceable to the supporting artifacts, independently recomputed from the canonical
store rather than from the study's own panel. The Phase 2 sample meets its
stratification requirements by inspection of the sampling code. Terminal label B is
the sole classification and remains defensible. The `phase0_gate1.py` touch does not
violate the no-rerun constraint.

---

## Correction applied after this pass (main session, 2026-08-10)

The `score_is_new` warning was **already fixed before this pass ran**, and the
finding is withdrawn rather than carried.

`lookahead-auditor` pass 2 raised it; the fix landed at `reconcile.py:417-421`,
which now reads
`bullish_score_is_new if direction == 1 else bearish_score_is_new`, and
`reconcile.py` was re-run so the parquet was regenerated from the corrected code.
The contract-checker cited the correct line range but read it as still
unconditional. Verified after the fact: the direction branch is present, and all
242 sampled rows carry `score_is_new = true`. Warning count moved 1 → 0 in
`contract_status.json` accordingly.
