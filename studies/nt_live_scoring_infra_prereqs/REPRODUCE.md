# Reproduce

All commands run from the repo root
(`C:\Users\Scott McCarty\Projects\Nautilus Trader`) with the project's
Python environment active.

## Phase 0 — reconstruct and persist the frozen bearish-flip model

```bash
python -m studies.nt_live_scoring_infra_prereqs.phase0_reconstruct_model
```

Refits the model on ~814K rows / 695 features (~80s). Writes
`_work/F3_volume_delta_plus_price_levels__gbt_reconstructed.joblib` and
`results/phase0_manifest.json`. Expect `reproduction_ok: true`,
`max_abs_diff_vs_stored_reference: 0.0`.

## Phase 1 — F3 feature inventory

```bash
python -m studies.nt_live_scoring_infra_prereqs.phase1_feature_inventory
```

Writes `results/f3_feature_inventory.csv` and
`results/f3_feature_inventory_summary.json`. Expect `n_in_registry: 546`,
`n_timing_unverified: 17`.

## Phase 2 — registry schema extension

No standalone script — the changes are directly in `features/registry.py`
(`FeatureDefinition`'s new `window`/`window_unit`/`reset_policy` fields,
`_add()`'s new keyword params, `bind_snapshot_anchor()`/
`effective_snapshot_anchor()`). Verify via:

```bash
python -m pytest studies/nt_live_scoring_infra_prereqs/tests/test_registry_schema_extension.py studies/nt_live_scoring_infra_prereqs/tests/test_snapshot_anchor_binding.py -v
python -m pytest tests/test_feature_library.py -v   # pre-existing suite, confirms no regression
```

## Phase 3 — feature-timing causal spec

No standalone script — the deliverable is
`results/feature_timing_causal_spec.md`, hand-extracted and verified
against source. Its empirical claims are pytest-checked:

```bash
python -m pytest studies/nt_live_scoring_infra_prereqs/tests/test_feature_timing_causal_contract.py -v
```

## Phase 4 — coincident 1s/1m callback-ordering proof

```bash
python -m pytest studies/nt_live_scoring_infra_prereqs/tests/test_coincident_bar_ordering.py -v
```

Two tests: one confirms correct 1s-before-1m order under
`add_bars_causal_order()`; the other proves this is a calling-convention
artifact, not an NT-native guarantee, by reversing the `add_data()` call
order and confirming the arrival order flips. **Any future NT study
loading both 1s and 1m data must use `add_bars_causal_order()` from this
file (or replicate its exact call order).**

## Phase 0 model-artifact regression test

```bash
python -m pytest studies/nt_live_scoring_infra_prereqs/tests/test_phase0_model_artifact.py -v
```

Independently loads the persisted `.joblib` and re-confirms it still
scores within tolerance — catches silent artifact/upstream drift that
`phase0_reconstruct_model.py`'s own one-shot assertion wouldn't.

## Full test suite

```bash
python -m pytest studies/nt_live_scoring_infra_prereqs/tests/ -v
```

Expect 30/30 passed.

## Audits

Two audit passes recorded in `audit/audit.md`:
1. Completion-gate audit of all 4 phases — found 1 CRITICAL (coincident-
   ordering false claim) + 5 Warnings + 4 Notes.
2. Follow-up fix-verification pass — confirmed all fixed, 0 CRITICAL, 0
   Warning remaining (2 Notes left open by design).

Re-running requires re-invoking the `lookahead-auditor` subagent against
current code, not a script.
