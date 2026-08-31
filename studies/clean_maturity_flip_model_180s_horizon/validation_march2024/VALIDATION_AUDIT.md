# March 2024 Runtime-Parity Validation - Focused Causal + Contract Audit

{
  "scope": "the March-2024 validation implementation only (a PartitionSpec bounded run + offline comparison scripts). The candidate/feature/target causal surface is 100% the already-sealed generic collector (execution composite bd2e9cf145a7408cff84613fec65149a94c296eeafad6194b42d427df4203e0e, causal pass 14 CLEAR, contract pass 14 CLEAR) -- the validation adds no NT/feature/target code.",
  "checks": {
    "nt_candidate_creation_independent_of_reference_schedule": "PASS -- collect_partition -> run_collect_mode -> FlipPredictionCollector generates candidates from live regime state; no reference schedule / precomputed candidate list is passed to the runtime. The frozen panel is loaded only post-hoc by march2024_parity.py for comparison.",
    "features_use_only_causal_completed_state": "PASS -- unchanged sealed collector; smoke_acceptance causality_coverage 100.0%, 0 future-source violations; Gate 2 gives 0.0 delta vs the full-year run which passed causal pass 14.",
    "score_uses_frozen_model_artifact": "PASS -- lgb.Booster(model_file=<committed *.booster.txt>) and the verbatim combined bundle; golden-score parity 0.0 over the full 448,405-row 2024 matrix; no reconstruction from parameters.",
    "p90_uses_frozen_TRAIN_thresholds": "PASS -- 0.28528879 (LONG) / 0.28485632 (SHORT) read directly from train_experiment_freeze.json; no percentile computed from March 2024.",
    "first_fire_state_one_per_regime": "PASS -- armed.groupby('regime_start_ns').head(1), identical to frozen research_workflow.forward_outcomes.first_crossing_entries.",
    "outcome_tracking_uses_only_post_T_streamed_events": "PASS -- target is the sealed FlipTargetRuntime (Gate 5 exact); forward-path economics use bars with ts_event > T only and ts_init < 2024-04-02 (no 2025).",
    "no_oos_recalibration": "PASS -- no threshold/percentile/decile derived from 2024; no refit, retune, or feature change."
  },
  "causal_audit": "CLEAR",
  "contract_audit": "CLEAR"
}
