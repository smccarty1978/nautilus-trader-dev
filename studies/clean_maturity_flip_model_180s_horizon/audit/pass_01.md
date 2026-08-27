# Look-Ahead & Timestamp Audit — Pass 01

**Date** 2026-08-26 · **Scope** `study.yaml`, `compiled_study.json`, `config/{population,target,feature,timestamp,execution,model_selection,lineage}_contract.json`, `SPEC.md`, `audit/{preflight,readiness,lint,frozen_execution_manifest}.json`, cross-referenced against parent study `clean_maturity_flip_model_rolling_productivity` (same paths) and `research_workflow/generic_collector.py` (`_track_pending`/`_emit_observation`/`_sweep_elapsed_horizons`), `research/engines/target_engine.py::compile_target_contract` · **Scope hash (frozen execution composite)** `8b953ad2b30b4818abf880564d5a22e015d2363457d1cecb07847b787db3eae8` · **Lint** 0 critical / 0 warning (`audit/lint.json`, 98/98 files, 100% coverage — preflight-owned, not re-derived) · **Verdict** `CLEAR`

## Summary
Critical: 0 · Warning: 0 · Note: 1

## Prior findings adjudicated
N/A — pass 01 for this study (a new study directory; the parent's 16-pass history belongs to `clean_maturity_flip_model_rolling_productivity` and is not re-litigated here).

## Machine sub-checks (independently re-derived, not merely re-run)
```json
{
  "checks": [
    {"name": "preflight", "passed": true, "detail": "status=CLEAR, execution_composite_sha256 matches frozen manifest and this report's scope hash"},
    {"name": "readiness", "passed": true, "detail": "overall_status=PASS; R2 (1m/1s/5m timestamp deltas) and R4 (213431-event callback order) proven per readiness.json, not re-derived"},
    {"name": "real_output_parity", "passed": true, "detail": "r10: 13/13 emitted features == resolved collection universe, unexpected_columns=[]"},
    {"name": "canonical_instances", "passed": true, "detail": "all 13 instances declare feature+parameters"},
    {"name": "legacy_runtime_excluded", "passed": true},
    {"name": "derived_input_availability_causal", "passed": true, "detail": "features.derived_inputs=[] — nothing to check"},
    {"name": "composite_target_label_only", "passed": true, "detail": "target.required_forward_outcomes=null — no composite-target excursion columns generated"},
    {"name": "causal_lint", "passed": true, "critical_findings": 0}
  ]
}
```

## Critical findings
None.

## Warnings
None.

## Notes
### [NOTE] `study.yaml:29` — `horizon_seconds: 180` correctly bounds only the forward label-resolution window, not decision time
**Verification, not a defect:** `research/engines/target_engine.py::compile_target_contract` sets `censoring_policy.max_horizon_seconds = target_spec.horizon_seconds` and leaves `decision_reference` untouched. In `research_workflow/generic_collector.py::_track_pending` (line ~547), `horizon_end_ts = T + int(self.cfg.horizon_seconds) * NS` is computed *from* the already-emitted candidate's `observation_ts`/T and used only in `_sweep_elapsed_horizons`/`_emit_observation` to resolve the terminal disposition (`target_flip_within_horizon`, `censored`). No feature, qualification gate, or candidate-emission logic reads `horizon_seconds`; `config/population_contract.json` and `config/feature_contract.json`'s `feature_list_sha256` (`4e46c0b3...df33`) are byte-identical to the parent. Shortening 300s→180s narrows the label's forward window (legitimately, per C1) and cannot move T later or require any window to read past T. This directly answers required check #1.

## Referred to contract-checker
- `model.family` changed `HistGradientBoostingClassifier` (parent) → `lightgbm` (this study), with a new `model.params`/`model.selection` hyperparameter set — this delta is not listed in `lineage.intended_changes` (which names only `target.horizon_seconds`) or in `lineage.frozen`. Not a causal question; a lineage-fidelity / model-integrity-declaration gap for contract-checker to adjudicate (does the SPEC's stated "same model family" claim match the manifest).

## Clean checks
- **A1–A5** — timestamp_contract.json byte-identical to parent; `ts_init`/`ts_event` deltas empirically re-measured (1000/60000/300000 ms×10^6) and proven in `audit/readiness.json` R2, not re-derived.
- **B1–B7, B9, B10** — feature instances (13, all timeframes/windows/lookbacks) unchanged from parent; `feature_list_sha256` matches parent exactly; no rolling/EWM `center=True`, no `.shift(-N)`, no `bfill` in the touched surface (unchanged code path — `generic_rolling_productivity.py`, `generic_structural_geometry.py`, `generic_arrival.py`, `generic_context.py` are not in this study's diff).
- **C1** — `horizon_seconds`/`censoring_policy.max_horizon_seconds` are label-only fields (`_track_pending`/`_emit_observation`); never read as a feature. Confirmed no new outcome/forward-outcome columns declared (`required_forward_outcomes=null`).
- **C2** — `target_flip_within_horizon` is written once per candidate at terminal disposition, keyed to the same `observation_ts`/`checkpoint_index` the features were snapped at (`_emit_observation`).
- **C3** — `chronology` (train 2021–2023 / dev 2024 / prohibited 2025–2026) byte-identical to parent; `model.selection.tuning_years=[2021,2022]` and `final_train_validation_years=[2023]` are both strict subsets of `chronology.train`; neither reaches `dev` or `prohibited`. The selection block governs a later modeling-stage split only — `generic_collector.py` (the only code that runs before/at TRAIN COLLECT) contains no reference to `model_selection`/`tuning_years`. Directly answers required check #5.
- **F1–F4** — `population_contract.json` (`session: RTH`, qualification gates) byte-identical to parent; session handling untouched.
- **G1–G4** — dataset (`NQ_v0_2020_2026`), catalog path, and R9 (zero alternate catalog openers) unchanged; not touched by this study's diff.
- **H1–H4** — no bracket/SL/PT sim in this study (collector-only, `flip_prediction` type produces `candidates.parquet`/`observations.parquet`, no backtest mode authorized per `deliverables_contract.json`); not applicable.

**Population-asymmetry check (repository-specific pattern):** confirmed the horizon shortening does **not** touch `population_contract.json`'s qualification gates (`age_gate_seconds`, `running_mfe_atr_gte`, `new_progress_windows_gte`, `retained_mfe_ratio_gte`, `cadence_seconds`) — identical to parent byte-for-byte. Candidate emission is therefore identical between the two studies; only the terminal-disposition resolution window differs. No cross-event elapsed-time look-ahead was introduced at the earlier (decision) event.

<!-- AUDIT_SUMMARY_V2_START -->
{"audit_type": "causal", "auditor": "lookahead-auditor", "study": "clean_maturity_flip_model_180s_horizon", "verdict": "CLEAR", "critical": 0, "warning": 0, "note": 1, "audited_execution_composite_sha256": "8b953ad2b30b4818abf880564d5a22e015d2363457d1cecb07847b787db3eae8"}
<!-- AUDIT_SUMMARY_V2_END -->
