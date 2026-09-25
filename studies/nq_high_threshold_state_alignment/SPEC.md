# nq_high_threshold_state_alignment

Derived from `research_decision.yaml`. Question: As Model-C score moves from P90 -> P95 -> P97.5 -> P99, does the threshold crossing become systematically closer—in both price and time—to the broad reversal-entry zones identified by Project 3B?

## Population
All 6,559 P90-armed NQ regimes across 2023, 2024, and 2025 Q1 evaluated on the frozen 5-second candidate lattice from `studies/nq_p90_reversal_entry_quality` and `studies/nq_p90_reversal_economic_surface`.

## Target
Threshold crossing behavior, immediate reversal economics (+1.00/-0.75 ATR), temporal and price alignment with broad winning zones (>=30s contiguous winning runs), state persistence at higher thresholds (P95, P97.5, P99), and monotonicity across the deterioration severity ladder.

## Features
Frozen Model-C scores, exact authenticated TRAIN quantiles (P90, P95, P97.5, P99), regime geometry (`regime_mfe_atr_at_T`, `regime_giveback_atr`), and barrier outcomes.

## Chronology
- TRAIN: 2023, 2024
- DEV/OOS: 2025 Q1

## Deliverables Manifest
- analysis/threshold_crossing_behavior.json
- analysis/immediate_reversal_economics.json
- analysis/winning_zone_alignment.json
- analysis/state_persistence_higher_thresholds.json
- analysis/monotonicity_matrix.json
- analysis/probability_vs_timing.json
- analysis/threshold_metrics_table.parquet
- analysis/threshold_metrics_table.json
- analysis/project3d_summary.json
- analysis/project3d_verdict.json
- analysis/PROJECT_3D_HIGH_THRESHOLD_STATE_ALIGNMENT_REPORT.md

