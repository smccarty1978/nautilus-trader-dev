# Look-Ahead & Timestamp Completion Audit

**Date:** 2026-07-22T11:09:21.3721442Z  
**Scope:** frozen Top25/Top103 artifacts and catalog; all Top103 study code and generated deliverables; original Top25 population/code and unchanged short path  
**Scope hash:** `c42864d019e50ef531c3f7e669ad18efbb79f694aa150d454dc05e1ed47fed81` (49 non-log, non-audit files)  
**Auditor:** lookahead-auditor v1  
**Gate:** MANDATORY COMPLETION AUDIT — **PASS**

## Summary

- Critical: 0
- Warning: 0
- Note: 0

The bounded run and every requested generated deliverable pass causal, parity, schema, count, reporting, and recommendation-gate checks.

## Critical findings

None.

## Warnings

None.

## Verified generated results

- `status_collect.json` records `completed`, exit code 0, 142 seconds, and a bounded-run log path.
- `signal_population.csv` has 45,813 rows and 26 columns: 20,477 long and 25,336 short; years are restricted to 2024–2025.
- The only schema addition versus the original population is `flip_exit_pnl_pts`.
- Recomputed Top25 long has 20,240 rows and is exactly equal on every original baseline column under `assert_frame_equal(check_exact=True)`.
- New short population has 25,336 rows and is exactly equal to the original short population on every original column.
- No duplicate `(direction, threshold_pct, regime_start_ns)` signals exist. All 11 original thresholds are present and bucket assignments exactly reproduce the frozen A/B/C rule.
- `time_to_flip_s` exactly equals `(confirm_flip_ns - signal_ts) / 1e9`; horizon false positives are the complement of the within-horizon event and include nulls by construction.
- `common_checkpoint_scores.parquet` has 324,617 unique checkpoints and both model scores on every row. Reliability deciles contain the same total common population for each model.
- Top 1%/2.5%/5% summary counts, false positives, flip probabilities, and mark-PnL medians independently reconcile to source populations.
- Paired outputs cover seven required metrics at all three thresholds, use regime intersections, and report metric-level effective sample counts and 95% intervals.
- The frozen recommendation gate correctly retains Top25: Top103's flip-within-300s change is negative at all three thresholds, so mandatory non-worse/better conditions fail.
- Required suffixed population/summary copies are byte-identical to their source outputs; both required report filenames exist and are identical.
- `audit_packet.json` identifies Top103 long, the unchanged short model, 2024–2025, `2026_loaded: false`, and long-model-only methodology change.
- Both identical executive reports cover Top 1%/2.5%/5% frequency; flip-300/600; median/p90/p95 timing; remaining MFE/path MAE; non-executable mark PnL; captured movement; overlap/Jaccard/rank correlation/reliability; false positives and buckets; all paired intervals; seven explicit executive answers; and each frozen gate clause with the correct verdict.

## Freeze and immutability verification

- Catalog production: `LONG_STRICT_top103_gbt_v2`; challenger: `LONG_STRICT_top25_gbt_v2`.
- Every copied artifact file hash matches both its catalog entry and freeze manifest; deployment statuses agree.
- Original `studies/pre_flip_signal_reliability` and `freeze_reduced_flip_model_artifacts` have no tracked working-tree modifications. The original Top25 population is read-only; the new study performs its supplemental recomputation only in its own results directory.

## Forced compliance matrix

| Rule | Status | Rule | Status | Rule | Status | Rule | Status |
|---|---|---|---|---|---|---|---|
| A1 | PASS | A2 | N/A | A3 | N/A | A4 | N/A |
| A5 | PASS | B1 | PASS | B2 | PASS | B3 | PASS |
| B4 | PASS | B5 | PASS | B6 | PASS | B7 | PASS |
| C1 | PASS | C2 | PASS | C3 | PASS | C4 | N/A |
| D1 | PASS | D2 | N/A | D3 | PASS | D4 | PASS |
| E1 | N/A | E2 | N/A | E3 | N/A | E4 | N/A |
| E5 | N/A | F1 | PASS | F2 | PASS | F3 | PASS |
| F4 | PASS | G1 | N/A | G2 | PASS | G3 | N/A |
| G4 | PASS | H1 | PASS | H2 | PASS | H3 | N/A |
| H4 | PASS |  |  |  |  |  |  |

---

*Completion audit reflects read-only static and generated-artifact analysis. No study/backtest was rerun, and no file other than this audit report was modified.*
