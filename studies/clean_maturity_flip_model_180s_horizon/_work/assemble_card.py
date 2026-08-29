import json
from pathlib import Path

S = Path(r"C:\Users\Scott McCarty\Projects\Nautilus Trader\studies\clean_maturity_flip_model_180s_horizon\artifacts")
cl = json.loads((S / "diag_classification_180s_vs_300s.json").read_text())
ep = json.loads((S / "diag_economic_path_180s_vs_300s.json").read_text())
tps = json.loads((S / "two_phase_selection_dispatch_summary.json").read_text())
ftz = json.loads((S / "final_train_freeze_dispatch_summary.json").read_text())


def r(x, n=4):
    return round(x, n) if isinstance(x, (int, float)) else x


card = {
    "study": "clean_maturity_flip_model_180s_horizon",
    "stop_point": "TRAIN freeze + TRAIN-only comparison card",
    "OOS_ACCESSED": "NO",
    "2025_2026_ACCESSED": "NO",
    "framework_reconciliation": {
        "current_workflow_used": True,
        "old_artifacts_stale": True,
        "parameterized_feature_identity_reconciled": "YES - prior_1m_* / prior_5m_* now distinct; feature_list_sha256 4e46c0b3 -> 38c0201f; semantic surface unchanged",
        "execution_closure_valid": True,
        "sealed_composite": "bd2e9cf145a7408cff84613fec65149a94c296eeafad6194b42d427df4203e0e",
        "feature_list_sha256": "38c0201fe2b0fec3070b7a226353d7782778aa82bace3b6070de8844d9d04d32",
        "spec_sha256": "e363badf226991c99ebef50892f468d79d04be59f5abd7ffb5cac5a702fad1e0",
        "causal_audit": "CLEAR pass 14 (lookahead-auditor) 0 critical / 0 warning / 2 notes (deferred to parity gate)",
        "contract_audit": "CLEAR pass 14 (contract-checker) 0 blocking / 0 warning",
        "seal": "LOCKED",
    },
    "parent_300s": {
        "authoritative_study": "clean_maturity_flip_model_rolling_productivity",
        "frozen_execution_composite": "7b0994145ce702fedbf3b589a98fa869b09ef57253a17722b8de25931cbb96c8",
        "benchmark_artifact": "artifacts/train_experiment_freeze_repaired.json",
        "model_family": "lightgbm 4.6.0 LGBMClassifier (established by joblib deserialization)",
        "feature_surfaces": "A=3 / B=9 / C=13; identical canonical identities + parameters to the child",
        "model_hashes": {"LONG_C": "a341ae262496ac30338f861535bf2dae45c301dff2d8753a8c4ce0821f555d38",
                          "SHORT_C": "5aa9f0c897e9b60bb83ab7d7c6b1f20411d261264dae4e5bfd753f6ed0bda0cf"},
        "OOS_2024": "already scored in the parent study - NOT touched here",
    },
    "parent_300s_runtime_parity": {
        "verdict": "EXACT_SEMANTIC_PARITY",
        "action": "HOLD_FROZEN_PARENT",
        "evidence": ("shared authorized date 2023-10-02: 1704/1704 candidates identical on join key; "
                     "224/224 flips observable within both horizons match exactly on disposition + flip_ts + label + time_to_flip; "
                     "all 137 disposition differences explained by a flip in (180s,300s]; 0 from censoring; 0 unexplained. "
                     "Combined with causal pass 14 (new flip labeling = behaviour-preserving refactor of the legacy inline path) "
                     "and contract pass 14 (population/session/censoring/timestamp inherited identical). "
                     "Parent used unchanged for the 180s-vs-300s comparison; no parent re-collection or re-score."),
        "artifact": "artifacts/target_runtime_parity.json",
    },
    "target_runtime_parity": {
        "verdict": "CLEAR",
        "exact_horizon_boundary_convention": ("INCLUSIVE upper bound: a prevailing-1m-regime flip whose completed-1m-bar "
                                              "confirmation lands at exactly T + 180s is POSITIVE / within horizon; strictly after is NEGATIVE. "
                                              "Verified identical across (a) the collector live inline path (_sweep_elapsed_horizons one-tick hold), "
                                              "(b) FlipTargetRuntime._terminal_legacy / _terminal_pending (ts <= end), "
                                              "(c) the replay-oracle flip child _replay_flip_condition (T < ts <= end). "
                                              "3 assertions in _work/verify_horizon_boundary_convention.py pass. "
                                              "No independent replay oracle exists for a bare flip_within_horizon primitive; parity is covered by "
                                              "READINESS R10 + PREFLIGHT RUNTIME_CONTRACT_BINDING + causal pass 14 field-by-field verification."),
    },
    "target_180s": {
        "exact_event": "prevailing_1m_regime_transition, direction both",
        "horizon": "180s",
        "confirmation": "completed_1m_bar x1 (the regime engine has no separate raw/confirmed flip event; the flip IS the confirmation)",
        "population": ("1,387,411 candidates (identical to parent); 1,379,092 labeled "
                       "(LABELED_POSITIVE 226,315 / LABELED_NEGATIVE 1,152,777 / CENSORED 8,319 - fewer than parent's 13,894, "
                       "the expected mechanical consequence of the shorter horizon near the RTH close)"),
        "chronology": "TRAIN [2021, 2022, 2023]; 2024 sealed; 2025/2026 prohibited",
    },
}

for D, sign in (("LONG", -1), ("SHORT", 1)):
    b = cl[D]; t = tps[D]; fz = ftz[D]; p90 = ep["p90"][D]; p95 = ep["p95"][D]
    card[D] = {
        "base_rate_180s": r(b["base_rate_180s"]), "base_rate_300s": r(b["base_rate_300s"]),
        "n_labeled_180s": b["n_180s"], "n_labeled_300s": b["n_300s"],
        "A": {"pr_auc_val2022": r(b_pr := t["per_arm_pr_auc"]["A"]), "brier_val2022": r(t["per_arm_brier"]["A"])},
        "B": {"pr_auc_val2022": r(t["per_arm_pr_auc"]["B"]), "brier_val2022": r(t["per_arm_brier"]["B"])},
        "C": {"pr_auc_val2022": r(t["per_arm_pr_auc"]["C"]), "brier_val2022": r(t["per_arm_brier"]["C"])},
        "selected_architecture": t["winning_arm"],
        "selected_using": "PR-AUC (maximize) on fit=2021/val=2022; tie tol 0.005; brier then n_features then arm-name tie-break; 2023 never loaded in Phase 1",
        "tie_break_applied": t["tie_break_applied"],
        "tuned_hyperparameters": t["tuned_hyperparameters"],
        "tuning": "random search, 24 unique trials, seed 42, arm C only, fit=2021/val=2022",
        "inner_validation_pr_auc_2021_to_2022": r(t["inner_validation_score"]),
        "2023_reject_only": {
            "PR_AUC": r(t["final_validation_metrics"].get("pr_auc")),
            "brier": r(t["final_validation_metrics"].get("brier")),
            "gate": "max_degradation_vs_inner_validation <= 0.15 AND brier <= 0.30",
            "status": t["final_validation_status"],
        },
        "train_freeze": {
            "arm": fz["arm"], "n_rows": fz["n_rows"],
            "model_artifact_sha256": fz["model_artifacts"][0]["artifact_sha256"],
            "model_id": fz["model_artifacts"][0]["model_id"],
            "golden_fixture_sha256": fz["model_artifacts"][0]["golden_fixture_sha256"],
            "thresholds_TRAIN_ONLY": {k: r(v["threshold"]) for k, v in fz["thresholds"]["C"].items()},
            "stage_scoped_lineage": fz["stage_scoped_lineage"],
        },
        "vs_300s_classification_full_train": {
            "roc_auc_180s": r(b["classification_180s_full_train"]["roc_auc"]),
            "roc_auc_300s": r(b["classification_300s_full_train"]["roc_auc"]),
            "roc_auc_delta": r(b["delta_180s_minus_300s"]["roc_auc"]),
            "pr_auc_180s": r(b["classification_180s_full_train"]["pr_auc"]),
            "pr_auc_300s": r(b["classification_300s_full_train"]["pr_auc"]),
            "pr_auc_delta": r(b["delta_180s_minus_300s"]["pr_auc"]),
            "pr_auc_over_base_rate_180s": r(b["classification_180s_full_train"]["pr_auc"] / b["base_rate_180s"], 3),
            "pr_auc_over_base_rate_300s": r(b["classification_300s_full_train"]["pr_auc"] / b["base_rate_300s"], 3),
            "brier_180s": r(b["classification_180s_full_train"]["brier"]),
            "brier_300s": r(b["classification_300s_full_train"]["brier"]),
            "flip_rate_delta_at_base": r(b["base_rate_180s"] - b["base_rate_300s"]),
        },
        "high_score_precision_and_timing": {
            "p90": {"180s": {"flip_rate": r(b["crossing_180s"]["p90"]["flip_rate"], 3),
                              "precision_lift": r(b["crossing_180s"]["p90"]["precision_lift"], 2),
                              "median_sec_to_flip": b["crossing_180s"]["p90"]["median_seconds_to_flip"]},
                    "300s": {"flip_rate": r(b["crossing_300s"]["p90"]["flip_rate"], 3),
                              "precision_lift": r(b["crossing_300s"]["p90"]["precision_lift"], 2),
                              "median_sec_to_flip": b["crossing_300s"]["p90"]["median_seconds_to_flip"]}},
            "p97_5": {"180s": {"flip_rate": r(b["crossing_180s"]["p97_5"]["flip_rate"], 3),
                                "precision_lift": r(b["crossing_180s"]["p97_5"]["precision_lift"], 2),
                                "median_sec_to_flip": b["crossing_180s"]["p97_5"]["median_seconds_to_flip"]},
                      "300s": {"flip_rate": r(b["crossing_300s"]["p97_5"]["flip_rate"], 3),
                                "precision_lift": r(b["crossing_300s"]["p97_5"]["precision_lift"], 2),
                                "median_sec_to_flip": b["crossing_300s"]["p97_5"]["median_seconds_to_flip"]}},
        },
        "economic_path_first_crossing": {
            "note": "one entry per regime at the frozen threshold; forward path on 1s bars; Wilder ATR(14) 1m diagnostic",
            "p90": {"n_180s": p90["n_first_crossings_180s"], "n_300s": p90["n_first_crossings_300s"],
                    "median_sec_to_flip": {"180s": p90["summary_180s"]["median_ttf_s"], "300s": p90["summary_300s"]["median_ttf_s"]},
                    "MFE_at_300s_ATR_median": {"180s": r(p90["summary_180s"]["mfe_atr_300s_median"], 3), "300s": r(p90["summary_300s"]["mfe_atr_300s_median"], 3)},
                    "MAE_at_180s_ATR_median": {"180s": r(p90["summary_180s"]["mae_atr_180s_median"], 3), "300s": r(p90["summary_300s"]["mae_atr_180s_median"], 3)},
                    "eventual_max_MFE_ATR_median": {"180s": r(p90["summary_180s"]["eventual_max_mfe_atr_median"], 3), "300s": r(p90["summary_300s"]["eventual_max_mfe_atr_median"], 3)},
                    "eventual_max_MAE_ATR_median": {"180s": r(p90["summary_180s"]["eventual_max_mae_atr_median"], 3), "300s": r(p90["summary_300s"]["eventual_max_mae_atr_median"], 3)},
                    "P_MFE_ge_1_ATR": {"180s": r(p90["summary_180s"]["p_mfe_ge_1_atr"], 3), "300s": r(p90["summary_300s"]["p_mfe_ge_1_atr"], 3)},
                    "P_MFE_ge_2_ATR": {"180s": r(p90["summary_180s"]["p_mfe_ge_2_atr"], 3), "300s": r(p90["summary_300s"]["p_mfe_ge_2_atr"], 3)},
                    "P_MFE_ge_3_ATR": {"180s": r(p90["summary_180s"]["p_mfe_ge_3_atr"], 3), "300s": r(p90["summary_300s"]["p_mfe_ge_3_atr"], 3)},
                    "one_to_one_tradeability_success_within_300s": {"180s": r(p90["summary_180s"]["one_to_one_success_rate"], 3), "300s": r(p90["summary_300s"]["one_to_one_success_rate"], 3)},
                    "favorable_before_adverse_1ATR": {"180s": r(p90["summary_180s"]["favorable_before_adverse_1atr_rate"], 3), "300s": r(p90["summary_300s"]["favorable_before_adverse_1atr_rate"], 3)}},
            "p95": {"n_180s": p95["n_first_crossings_180s"],
                    "MFE_at_300s_ATR_median": {"180s": r(p95["summary_180s"]["mfe_atr_300s_median"], 3), "300s": r(p95["summary_300s"]["mfe_atr_300s_median"], 3)},
                    "eventual_max_MFE_ATR_median": {"180s": r(p95["summary_180s"]["eventual_max_mfe_atr_median"], 3), "300s": r(p95["summary_300s"]["eventual_max_mfe_atr_median"], 3)},
                    "one_to_one_tradeability_success_within_300s": {"180s": r(p95["summary_180s"]["one_to_one_success_rate"], 3), "300s": r(p95["summary_300s"]["one_to_one_success_rate"], 3)}},
        },
        "vs_300s_deltas": {
            "PR_AUC_delta": r(b["delta_180s_minus_300s"]["pr_auc"]),
            "ROC_AUC_delta": r(b["delta_180s_minus_300s"]["roc_auc"]),
            "calibration_delta_brier": r(b["classification_180s_full_train"]["brier"] - b["classification_300s_full_train"]["brier"]),
            "flip_rate_delta": r(b["base_rate_180s"] - b["base_rate_300s"]),
            "median_seconds_to_flip_delta_p90_crossing": (p90["summary_180s"]["median_ttf_s"] - p90["summary_300s"]["median_ttf_s"]),
            "remaining_MFE_delta_at_300s_ATR": r(p90["summary_180s"]["mfe_atr_300s_median"] - p90["summary_300s"]["mfe_atr_300s_median"], 3),
            "MAE_delta_at_180s_ATR": r(p90["summary_180s"]["mae_atr_180s_median"] - p90["summary_300s"]["mae_atr_180s_median"], 3),
            "one_to_one_tradeability_delta": r(p90["summary_180s"]["one_to_one_success_rate"] - p90["summary_300s"]["one_to_one_success_rate"], 3),
        },
    }

card["ECONOMIC_PRESERVATION"] = {
    "does_180s_leave_meaningful_post_signal_excursion": "YES",
    "does_accuracy_improvement_come_at_cost_of_MFE": "NO - MFE, MAE, eventual excursion, P(MFE>=k ATR) and 1:1 tradeability are all within ~1-5% of the 300s benchmark at matched frozen first-crossing thresholds, both directions, p90 and p95",
    "evidence": ("At the p90 first-crossing population the 180s signal fires ~55s closer to the flip (median 130s vs 185s to flip) "
                 "yet the subsequent path is essentially unchanged: MFE at 300s post-signal ~0.91-0.93 ATR (180s) vs ~0.94-0.95 (300s); "
                 "eventual max MFE ~1.30 ATR vs ~1.35; MAE identical; 1:1 favorable-before-adverse within 300s ~0.43 for BOTH horizons; "
                 "P(MFE>=1 ATR) ~0.60 vs ~0.62. The tighter horizon removes weak predictions faster than it removes reversal opportunity."),
}

card["TRAIN_FREEZE"] = {
    "status": "FROZEN (both directions)",
    "merge_sha256": "f60de141642554208472d76ef75d0937ac655f8064d2111adc6af0b9d3087666",
    "merged_train_rows": 1387411,
    "authorization_sha256": "19534de9bec8932da8b5b690c892bb4ea4324741865cae208c0270c8c0dd30fb",
    "LONG_freeze_sha256": "3b0b4799d0ef3b391c40ae3ab837fe0941bc5739c2d1f3e660a4bf8221bbe64b",
    "SHORT_freeze_sha256": "558830668efe11c569688e985e256a3af73e94f04893aa74c11a2a8efa2959d1",
    "LONG_model_hash": "25737fcd6830a60f8b5cb4a97293ceef8cabcf0efdc1910792a71c7127a9ae60",
    "SHORT_model_hash": "3c480affc677f64b712540f8e55df67d7f14fe9921ad9baa293b96bf70cdaa6f",
    "feature_order": ["arrival_velocity", "arrival_acceleration", "ema_slope",
                      "prior_1m_regime_efficiency", "prior_1m_regime_mfe_atr", "prior_1m_regime_range_atr",
                      "prior_5m_regime_efficiency", "prior_5m_regime_mfe_atr", "prior_5m_regime_range_atr",
                      "rolling_300s_retention_ratio", "rolling_300s_current_progress_atr",
                      "rolling_300s_max_progress_atr", "rolling_300s_giveback_atr"],
    "preprocessing_hash": "96ebac895c3526f56bcdc1f7c635ccc4df52108142e14901c3c4d7dc144c6ee8 (calibration none, raw feature surface)",
    "library_versions": {"python": "3.13.7", "numpy": "2.3.3", "pandas": "2.3.3", "sklearn": "1.7.2", "lightgbm": "4.6.0"},
    "reproducibility": ("deterministic - seed 42 throughout; Phase 1/2/3 rerun produced byte-identical selection; "
                        "immutable per-model golden-score fixtures persisted in studies/model_registry/; "
                        "stage-scoped lineage binds COLLECTION_PRODUCER bd2e9cf1 / TARGET_RUNTIME 54dc9897 / MODELING_EXECUTION ed5de9b1"),
}

card["INTERPRETATION"] = {
    "verdict": "CLASSIFICATION_BETTER_AND_TIMING_BETTER_WITH_ECONOMIC_MOVE_PRESERVED",
    "better_flip_classifier": ("YES - ROC-AUC rises +0.028/+0.028 (LONG/SHORT) and base-rate-relative PR-AUC lift rises "
                               "(1.95x vs 1.59x at the full surface; ~3.0x vs ~2.4x precision lift at the p97.5 crossing). "
                               "Raw PR-AUC and Brier fall, but only because the 180s base rate is ~half the 300s base rate."),
    "better_timing_signal": "YES - at matched frozen thresholds the 180s first-crossing fires ~50-55s closer to the flip (median 130s vs 185s at p90; 105s vs 155s at p95).",
    "economic_move_preserved": ("YES - MFE, MAE, eventual excursion, P(MFE>=k ATR) and 1:1 tradeability are all within a few percent of the "
                                "300s benchmark. The shorter horizon does not trivialize the prediction."),
    "direction_specific_findings": "LONG and SHORT behave near-identically on every axis; no directional divergence.",
    "one_to_one_tradeability_readout": ("~43% of high-confidence first-crossings reach +1 ATR favorable before -1 ATR adverse within 300s "
                                        "(50% over a full 600s race) - real but roughly coin-flip, at BOTH horizons. This is descriptive "
                                        "evidence for the next research question (a model predicting flip + favorable MFE/MAE geometry), not a tradeable edge on its own."),
    "recommended_next_step": ("Open 2024 OOS on the frozen 180s winner vs the frozen 300s parent to confirm the TRAIN picture holds out of sample, "
                              "then scope the flip + MFE/MAE-geometry model on the 180s horizon."),
}

card["READY_FOR_RESEARCHER_OOS_DECISION"] = True

(S / "180S_HORIZON_TRAIN_CARD.json").write_text(json.dumps(card, indent=2, default=str), encoding="utf-8")
print("wrote 180S_HORIZON_TRAIN_CARD.json", len(json.dumps(card)), "bytes")
