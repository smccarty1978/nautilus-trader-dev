# Structural Regime Geometry Within Maturity Buckets — Study Report

## Status

Terminal label: **ABORT_CONTRACT_OR_CAUSAL_FAILURE**. Promotion is governed by `results/promotion_gate.json`; no 2025/2026 data is permitted.

## Frozen scope

Separate prevailing-bullish→SHORT and prevailing-bearish→LONG HistGradientBoosting models; training 2021–2023, untouched 2024 OOS. Model A is the frozen Top25. Model B adds the collected structural geometry. The label is the inherited `(T, T+300s]` flip event; first crossings use TRAIN P90/P95/P97.5 thresholds and inherited Walk-A economics.

Collection validation: **PASS** — 48 monthly NT partitions, 4,551,280 base RTH checkpoints, 0 missing structural joins, and all completed-5m provenance timestamps at or before the checkpoint.

## 2024 row-level discrimination

| direction | maturity_bucket | n | base_auc | structural_auc | auc_delta |
|---|---|---|---|---|---|
| LONG | 300-600s | 31438 | 0.6187 | 0.6171 | -0.0016 |
| LONG | 600-900s | 39682 | 0.6277 | 0.6334 | 0.0057 |
| LONG | 900-1800s | 79116 | 0.6733 | 0.6720 | -0.0013 |
| LONG | >=1800s | 34639 | 0.6827 | 0.6777 | -0.0050 |
| SHORT | 300-600s | 35871 | 0.6183 | 0.6224 | 0.0040 |
| SHORT | 600-900s | 47015 | 0.6441 | 0.6449 | 0.0008 |
| SHORT | 900-1800s | 108083 | 0.6663 | 0.6645 | -0.0019 |
| SHORT | >=1800s | 64894 | 0.6822 | 0.6790 | -0.0032 |

Interpretation: B improves both sides in 300–600s and 600–900s (about +0.002 to +0.006 AUC), is essentially flat around 900–1800s, and degrades in the stale `>=1800s` band. This is evidence for a bounded maturity-specific follow-up, not a pooled replacement.

## P90 first crossings with accepted Walk-A labels

| model_set | direction | maturity_bucket | n | p_flip_le_300s | p_confirm_before_1atr | median_return_at_confirm_atr | median_eventual_opposite_mfe_atr |
|---|---|---|---|---|---|---|---|
| TOP25 | LONG | 300-600s | 35 | 0.4857 | 0.4000 | 1.6783 | 3.0152 |
| TOP25 | LONG | 600-900s | 143 | 0.4196 | 0.5524 | 0.9024 | 2.1189 |
| TOP25 | LONG | 900-1800s | 589 | 0.4584 | 0.4924 | 0.7770 | 2.4436 |
| TOP25 | LONG | >=1800s | 59 | 0.4915 | 0.5254 | 0.8752 | 1.7475 |
| TOP25 | SHORT | 300-600s | 54 | 0.3333 | 0.3704 | 1.2249 | 2.8519 |
| TOP25 | SHORT | 600-900s | 212 | 0.4057 | 0.4575 | 0.9217 | 2.5836 |
| TOP25 | SHORT | 900-1800s | 633 | 0.4202 | 0.4755 | 0.8261 | 2.5106 |
| TOP25 | SHORT | >=1800s | 111 | 0.5405 | 0.5856 | 0.8493 | 2.3002 |
| TOP25_PLUS_STRUCTURAL | LONG | 300-600s | 17 | 0.2941 | 0.3529 | 1.0466 | 1.9217 |
| TOP25_PLUS_STRUCTURAL | LONG | 600-900s | 138 | 0.4275 | 0.5145 | 0.9576 | 2.4447 |
| TOP25_PLUS_STRUCTURAL | LONG | 900-1800s | 587 | 0.4702 | 0.5043 | 0.7690 | 2.3432 |
| TOP25_PLUS_STRUCTURAL | LONG | >=1800s | 53 | 0.4717 | 0.5283 | 0.8992 | 1.8182 |
| TOP25_PLUS_STRUCTURAL | SHORT | 300-600s | 27 | 0.4444 | 0.4815 | 1.2850 | 2.4033 |
| TOP25_PLUS_STRUCTURAL | SHORT | 600-900s | 206 | 0.4126 | 0.4951 | 0.8383 | 2.6191 |
| TOP25_PLUS_STRUCTURAL | SHORT | 900-1800s | 652 | 0.4126 | 0.4755 | 0.8481 | 2.5056 |
| TOP25_PLUS_STRUCTURAL | SHORT | >=1800s | 112 | 0.5714 | 0.6161 | 0.8653 | 2.4301 |

The full P95/P97.5 tables remain in `results/oos_crossing_metrics.csv`; small cells are retained rather than extrapolated.

## Structural family group-permutation attribution

| direction | family | oos_auc_full | oos_auc_after_group_permutation | group_permutation_auc_drop | oos_auc_after_family_ablation | family_ablation_auc_drop |
|---|---|---|---|---|---|---|
| LONG | geometry_5m | 0.6712 | 0.6621 | 0.0090 | 0.6703 | 0.0009 |
| LONG | speed | 0.6712 | 0.6668 | 0.0043 | 0.6701 | 0.0011 |
| LONG | expansion | 0.6712 | 0.6701 | 0.0010 | 0.6707 | 0.0004 |
| LONG | retention_giveback | 0.6712 | 0.6708 | 0.0004 | 0.6713 | -0.0001 |
| LONG | prior_1m_geometry | 0.6712 | 0.6716 | -0.0004 | 0.6726 | -0.0014 |
| SHORT | speed | 0.6698 | 0.6671 | 0.0028 | 0.6691 | 0.0008 |
| SHORT | retention_giveback | 0.6698 | 0.6692 | 0.0007 | 0.6696 | 0.0003 |
| SHORT | geometry_5m | 0.6698 | 0.6693 | 0.0005 | 0.6706 | -0.0008 |
| SHORT | expansion | 0.6698 | 0.6695 | 0.0003 | 0.6706 | -0.0008 |
| SHORT | prior_1m_geometry | 0.6698 | 0.6704 | -0.0006 | 0.6712 | -0.0013 |

Attribution includes both fixed-seed grouped permutations and predeclared refit family ablations. It is diagnostic, not a causal claim about any individual feature.

## Decile and timing diagnostics

| model_set | direction | maturity_bucket | decile_1_flip_rate | decile_10_flip_rate | strictly_monotonic |
|---|---|---|---|---|---|
| TOP25 | LONG | >=1800s | 0.1349 | 0.5516 | True |
| TOP25_PLUS_STRUCTURAL | SHORT | 900-1800s | 0.0698 | 0.4533 | True |
| TOP25_PLUS_STRUCTURAL | LONG | >=1800s | 0.1195 | 0.5420 | False |
| TOP25 | SHORT | 300-600s | 0.0778 | 0.4402 | True |
| TOP25 | SHORT | >=1800s | 0.1017 | 0.5145 | True |
| TOP25 | LONG | 600-900s | 0.1072 | 0.4478 | True |
| TOP25_PLUS_STRUCTURAL | LONG | 300-600s | 0.0986 | 0.2561 | False |
| TOP25_PLUS_STRUCTURAL | SHORT | 600-900s | 0.0956 | 0.4874 | True |
| TOP25_PLUS_STRUCTURAL | SHORT | >=1800s | 0.0994 | 0.4956 | True |
| TOP25_PLUS_STRUCTURAL | LONG | 600-900s | 0.1022 | 0.3862 | True |
| TOP25_PLUS_STRUCTURAL | LONG | 900-1800s | 0.1034 | 0.5164 | True |
| TOP25 | LONG | 300-600s | 0.0850 | 0.4343 | True |
| TOP25 | SHORT | 900-1800s | 0.0683 | 0.4549 | True |
| TOP25 | SHORT | 600-900s | 0.1047 | 0.4595 | True |
| TOP25_PLUS_STRUCTURAL | SHORT | 300-600s | 0.0805 | 0.4286 | True |
| TOP25 | LONG | 900-1800s | 0.0944 | 0.5142 | True |

Classification deciles are exact across all OOS score rows. Walk-A decile economics use a fixed-seed, stratified diagnostic sample of 39,509 score rows / cap 250 per model-side-maturity-decile after the exhaustive 881,476-row run exceeded its 15-minute cap; see `results/oos_decile_economics_manifest.json`. Timing metrics are in `results/oos_timing_metrics.csv`.

## Terminal-label interpretation

- S1: structural information improves at least two primary buckets without worse P90 economics.
- S2: S1 is exclusively concentrated in 300-600s.
- S3: classification/timing improves but P90 confirmation or MFE does not consistently improve.
- S4: economic tail improves without material AUC improvement.
- S5: no material incremental information.
- ABORT: any seal, coverage, lint, or audit gate fails.

This run evaluates to **ABORT_CONTRACT_OR_CAUSAL_FAILURE** under the deterministic criteria in `results/summary.json`. Do not deploy Model B or alter the frozen Top25 entry architecture without a PASS promotion gate.

## Limitations

- The exhaustive Walk-A decile run exceeded its fixed 15-minute cap; economic decile columns are a fixed-seed stratified sample and are explicitly labelled as such.
- The 2024 result is one OOS year, not an independent deployment validation.
- Stale-regime (`>=1800s`) performance does not support use of the enriched model in that bucket.

## Artifact index

- `results/models_manifest.json` — feature lists, training/OOS counts, thresholds and deciles
- `results/oos_row_metrics.csv` — exact row-level AUC table
- `results/oos_first_crossings.parquet` / `oos_crossing_metrics.csv` — threshold events and Walk-A economics
- `results/oos_decile_classification.csv` / `oos_decile_economics.csv` — decile diagnostics
- `results/oos_family_permutation.csv` — group permutation attribution
- `results/validation_report.json` — collection, seal, join and completed-bar checks
