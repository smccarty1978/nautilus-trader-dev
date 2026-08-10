# Contract Audit — Pass 02

**Date:** 2026-08-10
**Scope:** SPEC §6 Deliverables Manifest, terminal-label reachability, §7 domain/completeness, C4/D/E, §9 gates 1–14 (gate 15 excluded — self-referential).
**Prior pass:** 1 blocking finding (stale `results/summary.json`, Manifest #13).

## Adjudication of pass-1 finding

| Finding | Verdict | Evidence |
|---|---|---|
| `results/summary.json` unconditionally overwrote `phase12_ran` / missing 14-answer block on any `phases.py` re-run | **FIXED** | `analysis/phases.py` L487–492, L519, L521–523 now reads prior `summary.json` and preserves `phase12_ran` / `phase12` / `report_answers` / `final_classification`. New `analysis/close_out.py` populates `report_answers` (q1–q14) and `final_classification` by reading back every value from the parquet artifacts (`confirm_speed_cohorts`, `confirmation_geometry`, `post_confirm_opportunity`, `giveback_geometry`, `stall_geometry`, `single_variable_discrimination`, `model_context`, `policy_results`, `policy_stability`). `classify()` executes the SPEC §6 decision table, including the exact label-D standard (net-positive/original entry AND ≥50% ≥3 ATR preserved AND beats placebo AND ≥4/5 years), rather than asserting an outcome. Verified on disk: `summary.json` shows `phase12_ran: true`, populated `phase12`, `report_answers` q1–q14, `final_classification.code = "C"`. Spot-checked q1/q5/q10 against pass-1-verified CSVs — exact match. `README.md` documents `close_out.py` in layout and reproduce order. `audit/lint.json`: 11 files, 0 critical. |

## New findings (max 3 per bounded re-audit rule)

1. **WARNING (non-blocking).** `close_out.py::classify()` has no explicit branch for
   SPEC label **E**; it falls through to C/F by exclusion. Independently confirmed
   this does not affect the current routing — `model_context.parquet` shows the
   Phase-10 score's AUC lift (0.253 at +120 s) does not exceed the best price
   variable (0.256), and 25 price variables clear the gate, so E's precondition
   ("every price variable fails") is false regardless of the missing branch.
   Remediation (smallest, non-blocking): add an explicit `E` check to `classify()`
   for defensive correctness in future re-runs; not required to close this study.

No other new findings. No causal findings — none referred to lookahead-auditor.

## Verdict

**CLEAR.** 0 blocking. Manifest complete, terminal label C correctly routed and
reproducibly derived from artifact data, §7 domain contract intact, §9 gates 1–14
pass. Remaining step (operational, not a compliance gap): overwrite
`audit/contract_status.json` with this pass-2 verdict and re-run
`implementation/validate.py` so gate 15 / `all_passed` reflects it.

## Post-audit remediation (recorded by the study author)

The WARNING was fixed rather than carried: `close_out.py` now has
`score_only_separation()` and an explicit `E` branch in `classify()`. The
precondition evaluates **false** in this run (25 price variables clear the gate),
so the routing to **C** is unchanged and the fix cannot have altered the verdict.
`final_classification.label_E_precondition_score_only_separation` records it.
