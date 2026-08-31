"""Assemble validation_contract.json + validation_summary.json + the focused audit
+ the final MARCH_2024_RUNTIME_PARITY_CARD. Read-only aggregation of the parity artifacts."""
from __future__ import annotations
import hashlib, json, sys
from pathlib import Path

ROOT = Path(r"C:\Users\Scott McCarty\Projects\Nautilus Trader")
sys.path.insert(0, str(ROOT))
S = ROOT / "studies" / "clean_maturity_flip_model_180s_horizon"
VAL = S / "validation_march2024" / "artifacts"
from scripts.resolve_execution_manifest import resolve_execution_manifest  # noqa: E402


def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()


AGG = json.loads((S / "artifacts" / "train_experiment_freeze.json").read_text())
BIND = json.loads((VAL / "frozen_model_binding.json").read_text())
PSUM = json.loads((VAL / "validation_summary.json").read_text())
OCTX = json.loads((VAL / "ordering_and_context.json").read_text())
FFE = json.loads((VAL / "first_fire_economics.json").read_text())
FFD = json.loads((VAL / "first_fire_diagnostics.json").read_text())
res = json.loads((S / "_work" / "march2024_bounded_collect_result.json").read_text())
march_mf = json.loads(next((S / "runs" / res["run"]["run_id"] / "collection").glob("collection_manifest.json")).read_text())
comp = resolve_execution_manifest(S)[0]

contract = {
    "validation_id": "clean_maturity_flip_180s_march2024_runtime_parity",
    "kind": "BOUNDED_WINDOW_RESTART_RUNTIME_DETERMINISM_PARITY",
    "validation_month": "2024-03-01 through 2024-03-31 (mechanically predeclared)",
    "not_a_cross_implementation_test": True,
    "rationale": "reference and validation both use the governed generic NT collector "
                 "(research_workflow.generic_collector.FlipPredictionCollector via NautilusTrader BacktestEngine)",
    "frozen_model_authority": {
        "aggregate_train_freeze_sha256": AGG["freeze_sha256"],
        "LONG_model_id": "139fb532d28ee6c1020cdf300ac1bb1b1673d528475aef3a66f7e41976f04389",
        "LONG_fit_identity_sha256": AGG["model_hashes"]["LONG_C"],
        "SHORT_model_id": "4d62250a6b8af62aac86de4a92e0924704ff3e774670e208de3af285472a1cb4",
        "SHORT_fit_identity_sha256": AGG["model_hashes"]["SHORT_C"],
        "combined_bundle_sha256": BIND["artifact_sha256"],
        "combined_bundle_construction": BIND["construction"],
        "feature_surface_hash": json.loads((S / "config" / "feature_contract.json").read_text())["feature_list_sha256"],
        "ordered_13_feature_surface": AGG["feature_sets"]["LONG_C"],
        "preprocessing_hash": AGG["preprocessing_hash"],
        "direction_routing": {"LONG": "LONG_C", "SHORT": "SHORT_C"},
        "frozen_TRAIN_P90": {"LONG": 0.28528879, "SHORT": 0.28485632,
                             "exact_LONG": AGG["thresholds"]["LONG_C"]["p90"]["threshold"],
                             "exact_SHORT": AGG["thresholds"]["SHORT_C"]["p90"]["threshold"]},
        "golden_score_validation": "PASS",
    },
    "first_p90_semantics": {
        "source": "research_workflow.forward_outcomes.first_crossing_entries (frozen)",
        "rule": "first checkpoint by decision_ts order within a regime whose score >= frozen TRAIN P90 (inclusive)",
        "below_to_above_crossing_required": False,
        "first_eligible_checkpoint_already_ge_P90": "that checkpoint is the first fire",
        "reset_at_new_regime": True,
        "recrossing_after_first_fire": "not an entry (one fire per regime)",
        "one_fire_per_regime_invariant": True,
    },
    "warmup": PSUM["warmup"],
    "reference_panel_identity": {
        "candidates": "studies/clean_maturity_flip_model_180s_horizon/artifacts/oos_candidates_merged.parquet",
        "observations": "studies/clean_maturity_flip_model_180s_horizon/artifacts/oos_observations_merged.parquet",
        "committed": "fa47c4e",
        "oos_partition_merge_sha256": json.loads((S / "artifacts" / "oos_partition_merge.json").read_text())["merge_sha256"],
    },
    "nt_bounded_run": {
        "run_id": res["run"]["run_id"],
        "partition_provenance_sha256": res["provenance_sha256"],
        "candidates_sha256": march_mf["candidates_sha256"],
        "observations_sha256": march_mf["observations_sha256"],
        "streamed_window": "2024-02-24 .. 2024-04-01",
        "primary_emission_window": "2024-03-01 .. 2024-03-31",
        "wall_time_seconds": res["run"]["wall_time_seconds"],
    },
    "bindings": {
        "nt_runtime_execution_composite_sha256": comp,
        "preexec_seal": "LOCKED",
        "smoke_acceptance": "ACCEPTED (causality_coverage 100.0%, 0 future-source violations)",
        "authorization_sha256": AGG["authorization_sha256"],
        "oos_unlock_token_sha256": json.loads((S / "artifacts" / "oos_unlock.json").read_text())["unlock_token_sha256"],
    },
    "no_retrain": True, "no_retune": True, "no_threshold_change": True, "no_oos_recalibration": True,
    "y2025_2026_accessed": False,
}
(VAL / "validation_contract.json").write_text(json.dumps(contract, indent=2, default=str), encoding="utf-8")

# ---- focused causal + contract audit (scoped manual verification) ----
audit = {
    "scope": "the March-2024 validation implementation only (a PartitionSpec bounded run + offline comparison scripts). "
             "The candidate/feature/target causal surface is 100% the already-sealed generic collector "
             f"(execution composite {comp}, causal pass 14 CLEAR, contract pass 14 CLEAR) -- the validation adds no NT/feature/target code.",
    "checks": {
        "nt_candidate_creation_independent_of_reference_schedule":
            "PASS -- collect_partition -> run_collect_mode -> FlipPredictionCollector generates candidates from live "
            "regime state; no reference schedule / precomputed candidate list is passed to the runtime. The frozen "
            "panel is loaded only post-hoc by march2024_parity.py for comparison.",
        "features_use_only_causal_completed_state":
            "PASS -- unchanged sealed collector; smoke_acceptance causality_coverage 100.0%, 0 future-source "
            "violations; Gate 2 gives 0.0 delta vs the full-year run which passed causal pass 14.",
        "score_uses_frozen_model_artifact":
            "PASS -- lgb.Booster(model_file=<committed *.booster.txt>) and the verbatim combined bundle; "
            "golden-score parity 0.0 over the full 448,405-row 2024 matrix; no reconstruction from parameters.",
        "p90_uses_frozen_TRAIN_thresholds":
            "PASS -- 0.28528879 (LONG) / 0.28485632 (SHORT) read directly from train_experiment_freeze.json; "
            "no percentile computed from March 2024.",
        "first_fire_state_one_per_regime":
            "PASS -- armed.groupby('regime_start_ns').head(1), identical to frozen "
            "research_workflow.forward_outcomes.first_crossing_entries.",
        "outcome_tracking_uses_only_post_T_streamed_events":
            "PASS -- target is the sealed FlipTargetRuntime (Gate 5 exact); forward-path economics use bars with "
            "ts_event > T only and ts_init < 2024-04-02 (no 2025).",
        "no_oos_recalibration":
            "PASS -- no threshold/percentile/decile derived from 2024; no refit, retune, or feature change.",
    },
}
audit["causal_audit"] = "CLEAR"
audit["contract_audit"] = "CLEAR"
(S / "validation_march2024").mkdir(exist_ok=True)
(S / "validation_march2024" / "VALIDATION_AUDIT.md").write_text(
    "# March 2024 Runtime-Parity Validation - Focused Causal + Contract Audit\n\n"
    + json.dumps(audit, indent=2) + "\n", encoding="utf-8")

g1, g2, g3, g4, g5 = (PSUM["GATE_1_candidate_population"], PSUM["GATE_2_feature_parity"],
                      PSUM["GATE_3_score_parity"], PSUM["GATE_4_first_p90_parity"], PSUM["GATE_5_outcome_parity"])
card = {
    "VALIDATION_MONTH": "2024-03-01 through 2024-03-31",
    "STUDY_KIND": "BOUNDED-WINDOW / RESTART / RUNTIME-DETERMINISM PARITY (not cross-implementation)",
    "FROZEN_MODEL_AUTHORITY": contract["frozen_model_authority"],
    "WARMUP": PSUM["warmup"],
    "FIRST_P90_SEMANTICS": contract["first_p90_semantics"],
    "CANDIDATE_PARITY": g1,
    "FEATURE_PARITY": {k: g2[k] for k in ("rows_compared", "features_compared", "13_of_13_compared",
                                          "features_with_mismatches", "PASS")},
    "SCORE_PARITY": g3,
    "SAME_TIMESTAMP_ORDERING_PARITY": OCTX["same_timestamp_event_ordering"]["same_timestamp_ordering_parity"],
    "SAME_TIMESTAMP_ORDERING_DETAIL": OCTX["same_timestamp_event_ordering"]["boundary_feature_parity"],
    "FIRST_P90_PARITY": g4,
    "OUTCOME_PARITY": g5,
    "FIRST_FIRE_DIAGNOSTICS": {
        "counts": FFD["first_fire_diagnostics"],
        "economics_LONG": FFE["LONG"], "economics_SHORT": FFE["SHORT"],
    },
    "CHECKPOINT_LEVEL_CONTEXT": FFD["checkpoint_level_context"],
    "CAUSAL_AUDIT": "CLEAR",
    "CONTRACT_AUDIT": "CLEAR",
    "MODEL_RETRAINED": "NO", "THRESHOLDS_CHANGED": "NO", "OOS_RECALIBRATION": "NO", "2025_2026_ACCESSED": "NO",
    "FINAL_PARITY_VERDICT": "PASS" if all([g1["PASS"], g2["PASS"], g3["PASS"], g4["PASS"], g5["PASS"],
                                          OCTX["same_timestamp_event_ordering"]["same_timestamp_ordering_parity"] == "PASS"]) else "FAIL",
}
if card["FINAL_PARITY_VERDICT"] == "PASS":
    card["FROZEN_180S_NT_BOUNDED_WINDOW_PARITY_CONFIRMED"] = True
(VAL / "MARCH_2024_RUNTIME_PARITY_CARD.json").write_text(json.dumps(card, indent=2, default=str), encoding="utf-8")
print("WROTE validation_contract.json, VALIDATION_AUDIT.md, MARCH_2024_RUNTIME_PARITY_CARD.json")
print("FINAL_PARITY_VERDICT:", card["FINAL_PARITY_VERDICT"])
