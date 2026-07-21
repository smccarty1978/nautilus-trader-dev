# Reproduce

All commands run from the repo root
(`C:\Users\Scott McCarty\Projects\Nautilus Trader`) with the project's
Python environment active, from `studies/runtime_constrained_f3_feature_reduction/implementation/`
unless noted (each script adds `implementation/` to `sys.path` via `common.py`).

## Phase 0 -- baseline verification and promotion

Already verified and promoted this session (`results/baseline_manifest_verified.json`,
`artifacts/models/F3_695_baseline/`). To re-verify from scratch:

```bash
python -c "from implementation import common; import joblib; \
m = joblib.load(common.ARTIFACTS / 'F3_695_baseline' / 'model.joblib'); print(m.classes_)"
```

## Phase 1 -- existing importance inventory + F0 parity side-check

```bash
python -m studies.runtime_constrained_f3_feature_reduction.implementation.f0_tracker_parity_check
```

Writes `results/f0_tracker_parity_check.json`. Expect `parity_verdict: INCONCLUSIVE_HARNESS_LIMITED`
(see `honest_interpretation` in that file for why a clean MATCHES/DIVERGES call isn't supported by
this bounded check's own known approximations).

## Phase 2 -- family ablations A-G

```bash
cd studies/runtime_constrained_f3_feature_reduction/implementation
python build_feature_inventory_and_family_sets.py
python phase2_family_ablations.py
```

Writes `results/family_ablation_summary.csv` and 6 new model artifacts under `artifacts/models/`.

## Phase 3 -- feature importance

```bash
python build_importance_sample.py
python phase3_feature_importance.py
```

Writes `config/importance_sample.json`, `results/top_100_raw_feature_columns.csv`,
`results/full_raw_feature_ranking_695.csv`, `results/top_canonical_runtime_sources.csv`,
`results/feature_correlation_groups.json`, `results/phase3_importance_summary.json`.

## Phase 4 -- candidate construction

```bash
python phase4_build_candidates.py
```

Writes `results/candidate_feature_sets.json`.

## Phase 5 -- retrain all candidates

```bash
python phase5_train_candidates.py
```

Trains and persists 8 raw-count candidate models under `artifacts/models/`.

## Phase 6 -- full 2025 population evaluation

```bash
python phase6_evaluate_population.py
```

Writes `results/candidate_model_metrics.csv`, `results/candidate_population_overlap.csv`.

## Phase 7 -- selection gate

```bash
python phase7_selection_gate.py
```

Writes `results/phase7_gate_results.csv`, `results/selection_gate_decision.json`.

## Phase 8 -- freeze + catalog

```bash
python phase8_freeze_and_catalog.py
```

Writes `artifacts/models/FROZEN_RUNTIME_MODEL/`, `results/model_catalog.json`, `results/final_decision.json`.

## Tests

```bash
python -m pytest studies/runtime_constrained_f3_feature_reduction/tests/ -v
```

## Audits

Two `lookahead-auditor` passes recorded in `audit/audit.md`: pre-execution (before Phase 3, 0
CRITICAL / 5 Warning / 2 Note) and completion-gate (after Phase 8).
