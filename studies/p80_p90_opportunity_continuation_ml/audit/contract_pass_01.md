# Contract Compliance — Pass 01

Study: `p80_p90_opportunity_continuation_ml`
Scope: C4, D, E, Deliverables Manifest (SPEC §11), Terminal Labels (SPEC §11), Domain/Completeness (SPEC §12).
Causality (A, B, C1–C3, F, G, H) is `lookahead-auditor`'s scope — see `pass_01.md`, 0 CRITICAL.

**VERDICT: PASS — 0 CRITICAL, 3 WARNING, 2 INFO, 1 NOT VERIFIED. All six remediated (see end).**

## Deliverables Manifest (SPEC §11)

| # | Path | Verdict | Evidence |
|---|---|---|---|
| 1 | `results/provenance.json` | PASS | thresholds, availability status, train-years, waiver path, feature-family decision + rejected Top-100 coverage numbers |
| 2 | `results/population_reconciliation.json` | PASS | P90 reproduction exact (1771/1771), P80/P90 overlap, Model-B rung counts exact |
| 3 | `results/model_a_candidates.parquet` | PASS | present |
| 4 | `results/model_a_forward_labels.parquet` | PASS | present |
| 5 | `results/model_a_baselines.csv` | PASS | present; `summary.json` `baselines_300s` cross-checks |
| 6 | `results/model_a_oos_predictions.parquet` | PASS | present, read by `analysis/gates.py` |
| 7 | `results/model_a_bucket_performance.csv` | PASS | 8 buckets × POOLED/FOLD_1/FOLD_2/LONG/SHORT × 2 primes |
| 8 | `results/model_a_fold_performance.csv` | PASS | present |
| 9–14 | `model_b_{observations,forward_labels}.parquet`, `model_b_{baselines,bucket_performance,fold_performance}.csv`, `model_b_oos_predictions.parquet` | PASS | all present |
| 15 | `results/feature_family_ablation.csv` | PASS | always emitted (gate input, not a bonus) |
| 16 | `results/feature_importance.csv` | PASS | Model-B rows only (B-1/B-4 passed individually); Model-A rows correctly absent, disclosed in REPORT Q18 |
| 17 | `results/validation_report.json` | PASS | `all_passed: true`; V1–V12 + V14 |
| 18 | `results/summary.json` | PASS | Q-answer data + three terminal labels |
| 19 | `SPEC.md` · `README.md` · `REPORT.md` | PASS (was W1) | REPORT answers Q1–Q20; labels now also close the document |
| 20 | `audit/lint.json` · `audit/status.json` · `audit/contract_status.json` | PASS | lint 0 CRITICAL; lookahead-auditor 0 CRITICAL; this file |

## Seal (SPEC §1 / V1)

| Requirement | Verdict | Evidence |
|---|---|---|
| Every loader filters `entry_year == 2024` at source scan | PASS | `common.py::load_scores_2024`; `load_market(years=(2024,))` |
| Timestamps re-asserted, not just the partition column | PASS | `assert_2024_only` checks America/Chicago year on every produced frame |
| No path references 2021/2022/2023/2025/2026 | PASS | only `YEAR = 2024` and the never-read `SEALED_YEARS` tuple appear |
| Regime index intentionally NOT year-filtered | PASS | documented rationale (a late-December flip must stay resolvable); windows are session-clamped so no sealed-year bar can enter |
| Asserted before any fit | PASS | `validation_report.json` `V1_2024_seal.passed: true` |

## Terminal label reachability (SPEC §11)

| Label set | Verdict | Evidence |
|---|---|---|
| A1/A2/A3/A4 | PASS — all reachable | `gates.py::terminal_labels`; A4 via the `invalid` flag (surviving CRITICAL or V2 failure) |
| B1/B2/B3/B4 | PASS — all reachable | same routing, single Model-B gate set (Model B has no primes) |
| P1/P2/P3/P4 | PASS — all reachable | exact SPEC §11 routing table |
| Emitted labels follow the frozen routing | PASS | neither prime passes A-1 or A-2 → **A3**; B-1 passes but not all → **B2**; neither A1 nor B1 → **P4** |

## C4 — walk-forward, selection seals, promotion gates

| Requirement | Verdict | Evidence |
|---|---|---|
| No refit on evaluation-overlapping data | PASS | `V5_fold_causality`: max(train_ns) < min(eval_ns), both folds, both models, integer ns |
| Selection seal authenticates its own result | PASS | V2/V3 reproduce accepted lineage exactly before any fit; stage order enforces baselines-before-fit |
| Promotion gates implement every frozen check | PASS (was W3) | A-7's OR-clause now implemented and reported as a named sub-condition |

## D — train/serve skew

| Requirement | Verdict | Evidence |
|---|---|---|
| D1 offline/live parity | N/A | offline feasibility study; no live `on_bar` path exists |
| D2 filter cascade | PASS | 0 candidates dropped; count tracked in `population_reconciliation.json` |
| D4 deterministic encoding/imputation/ordering | PASS | GBT native NaN handling, nulls never imputed; column sets sorted |
| Decision-time identity binding | PASS (was informal) | `entry_atr` asserted bit-identical across the Model-B feature and label frames by gate V4 |

## E — label construction / execution configuration

| Requirement | Verdict | Evidence |
|---|---|---|
| Warmup / age gate respected | PASS | `AGE_GATE_S = 600` per SPEC §4.1 |
| Reference-price model disclosed | PASS | `checkpoint_reference_price` inherited; `REF_NEXT_OPEN` sensitivity emitted per candidate |
| Session / warmup clamping | PASS | `V9_session_containment`: 3,834 windows, 0 leaving session |

## Domain & completeness (SPEC §12)

| Requirement | Verdict | Evidence |
|---|---|---|
| 16 Model-A + 48 Model-B partitions, empty cells retained with a flag | PASS (was NV1) | `results/partition_completeness.csv`: **64 enumerated, 0 empty**; min cell n = 189 (A) / 19 (B) |
| Bucket completeness | PASS | 8 buckets × 5 scopes × 2 primes (A); 8 × 14 scopes (B) |
| Label completeness, hard assertion | PASS (was I2) | `assert_label_completeness`: **23,004 / 23,004 cells**, 0 null-or-invalid, 3,834 label rows = 3,834 candidates |
| Nulls never imputed for the GBT, never forward-filled | PASS | native NaN handling; an empty score window yields null |
| Boundary convention (CT, RTH, session clamp) | PASS | consistent; V9 passes |

## Numbers cross-check (REPORT.md vs results/*)

| Claim | Verdict |
|---|---|
| P90 reproduction 1,771 / 975 SHORT / 796 LONG | PASS — matches V2 and `population_reconciliation.json` |
| Model-B 2,991 obs / 781 trades / per-rung counts | PASS — matches V3 exactly |
| Bucket WIN% table (Q5) | PASS — matches `model_a_bucket_performance.csv` |
| Headline pooled AUC | PASS (was W2) — now 0.540 (P80) / 0.539 (P90) |
| B-1 +17.0pp, B-4 CI [−1.303, −0.180] | PASS — matches `summary.json` |

## Findings and remediation

All six items were remediated in the same session. Every verdict, label and gate
outcome is unchanged by the remediation.

| ID | Severity | Finding | Remediation |
|---|---|---|---|
| W1 | warning | REPORT labels appeared only at the top; SPEC §15 says the REPORT *ends* with three labels | Labels now also close `REPORT.md` |
| W2 | warning | Headline said AUC 0.539 (P80); actual 0.5400, contradicted by the REPORT's own Q10 answer | Headline corrected to 0.540 |
| W3 | warning | A-7's OR-clause ("one family alone already satisfies A-1..A-6") was never implemented — latent defect, unpassable for a model whose single family suffices | Both clauses implemented and reported separately; did not change this run |
| I1 | info | SPEC prose gave P80 SHORT as `0.3437437...`; the true frozen value is `0.34374423771129053`. The implementation never hardcoded it, so V12 was unaffected | SPEC prose now carries the exact frozen values |
| I2 | info | SPEC §12's label-completeness assertion was structural, not literal | `assert_label_completeness()` runs in Stage 1; result recorded in `population_reconciliation.json` |
| NV1 | not verified | The 16 + 48 partition cross-product was not enumerable as a single artifact | `results/partition_completeness.csv` enumerates all 64 with `is_empty` flags |

**Blocking: none.** This is a SIGNAL-FEASIBILITY study returning A3/B2/P4; no
deployment gate is being requested.
