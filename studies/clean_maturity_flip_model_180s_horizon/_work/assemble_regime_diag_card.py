import json
from pathlib import Path

V = Path(r"C:\Users\Scott McCarty\Projects\Nautilus Trader\studies\clean_maturity_flip_model_180s_horizon\validation_march2024")
r = json.loads((V / "REGIME_LEVEL_SCORE_DIAGNOSTIC.json").read_text())
p1, p2, p3, p4, p6 = (r["PART_1_checkpoint_reference"], r["PART_2_first_eligible_per_regime"],
                      r["PART_3_first_p90_fire"], r["PART_4_preflip_score_ramp"], r["PART_6_max_score_per_regime"])

CAVEAT = ("The 35,872 March checkpoints are NOT independent: LONG = 152 regimes, median 92 checkpoints/regime "
          "(max 315); SHORT = 154 regimes, median 106 (max 318). Regime-level effective sample size is ~150 per "
          "direction. The checkpoint ROC 0.70/0.67 is valid ONLY for its intended question -- 'at an arbitrary "
          "eligible checkpoint, does the score rank imminent flips?' -- and must not be read as 35,872 independent "
          "samples or as regime-selection skill. Parts 2, 3 and 6 answer the deployment question -- 'how much "
          "information exists when a regime first becomes actionable, and how does it evolve?' -- and those answers "
          "are separate and weaker.")

r["PART_7_decomposition"] = {
    "q1_discrimination_at_first_eligible_checkpoint":
        "Essentially none. First-checkpoint-per-regime ROC-AUC 0.495 (LONG) / 0.455 (SHORT); PR-AUC/base lift "
        "1.28 / 1.06; score deciles show flat, non-monotonic flip rates.",
    "q2_gain_from_repeated_within_regime_observation":
        "Large. Checkpoint-level ROC-AUC is 0.701 / 0.672 once every eligible 5s checkpoint is one observation. "
        "The full ~0.20 ROC gain over the first-checkpoint value is within-regime evolution as a regime ages toward its flip.",
    "q3_score_rises_as_true_flip_approaches":
        "YES, systematically, both directions. Median pre-flip score T-180s->T-30s: 0.161->0.245 (LONG), "
        "0.154->0.240 (SHORT); share >= frozen P90: 0.11->0.30 (LONG), 0.12->0.32 (SHORT). Part 5 shows this is "
        "flip-proximity-specific, not age-driven (age-controlled flip<=180s checkpoints score above non-imminent "
        "checkpoints of the same age at every bin). Effect real but modest: per-regime rise T-180s->T-60s median "
        "only +0.035, p25 negative (~1/4 of flipping regimes do not ramp).",
    "q4_first_P90_is_early_warning":
        "YES. First P90 fire in a flipping regime is a median ~115-148s before the flip; score keeps rising after "
        "(share >= P90 at T-30s ~0.30 vs ~0.11-0.15 earlier; median max pre-flip score ~0.31 > median first-fire ~0.30).",
    "q5_score_after_P90_adds_information":
        "WEAK. First-fire score quartiles give non-monotonic flip-within-180s rates (LONG 0.21/0.36/0.32/0.28; "
        "SHORT 0.10/0.29/0.33/0.29) and no timing trend. Only barely-above-threshold (SHORT Q1 0.10) is clearly worse. "
        "Within-tail ROC 0.54 / 0.62.",
    "q6_primary_source_of_the_checkpoint_roc": "WITHIN_REGIME_TIMING_SIGNAL",
    "q6_detail":
        "Between-regime axis is neutral-to-negative: first-eligible-checkpoint ROC ~0.49/0.46; retrospective max-score "
        "ROC vs ever-flip 0.43/0.44 with an INVERTED top quartile (LONG max-score Q4 eventual-flip 0.72 vs Q2 0.92) -- "
        "persistent regimes repeatedly enter 'about to flip' states without flipping. Minimal regime-quality axis.",
}
r["STATISTICAL_CAVEAT"] = CAVEAT
r["PRIMARY_VERDICT"] = "WITHIN_REGIME_TIMING_SIGNAL"
(V / "REGIME_LEVEL_SCORE_DIAGNOSTIC.json").write_text(json.dumps(r, indent=2, default=str), encoding="utf-8")


def rt(d, path, nd=3):
    x = r[path][d]
    return x


card = {
    "card": "MARCH_REGIME_LEVEL_SCORE_DIAGNOSTIC",
    "inputs_used": r["inputs_used"],
    "frozen_thresholds": r["frozen_thresholds"],
    "CHECKPOINT_REFERENCE": {d: {
        "rows": p1[d]["candidate_rows"], "regimes": p1[d]["unique_regimes"],
        "median_checkpoints_per_regime": p1[d]["checkpoints_per_regime"]["median"],
        "max_checkpoints_per_regime": p1[d]["checkpoints_per_regime"]["max"],
        "ROC_AUC": round(p1[d]["roc_auc"], 3), "PR_AUC": round(p1[d]["pr_auc"], 3),
        "base_rate": round(p1[d]["base_rate"], 3), "pr_auc_lift": round(p1[d]["pr_auc_over_base_rate"], 2),
        "every_eligible_5s_checkpoint_is_one_observation": True,
    } for d in ("LONG", "SHORT")},
    "FIRST_ELIGIBLE_PER_REGIME": {d: {
        "n": p2[d]["n_regimes"], "ROC_AUC": round(p2[d]["roc_auc"], 3), "PR_AUC": round(p2[d]["pr_auc"], 3),
        "base_rate": round(p2[d]["base_rate_180s"], 3), "lift": round(p2[d]["pr_auc_over_base_rate"], 2),
        "brier": round(p2[d]["brier"], 3),
        "distinguishes_near_term_flip_regimes_at_first_observation": "NO",
    } for d in ("LONG", "SHORT")},
    "FIRST_P90": {d: {
        "n": p3[d]["first_fire_n"], "flip_180_rate": round(p3[d]["flip_within_180s_rate"], 3),
        "lift_vs_first_checkpoint_base": round(p3[d]["precision_lift_vs_first_checkpoint_base"], 2),
        "median_seconds_to_flip_positives": p3[d]["median_seconds_to_flip_positives"],
        "ROC_AUC_within_tail": round(p3[d]["within_tail_roc_auc"], 3),
        "within_tail_interpretability_caveat": p3[d]["within_tail_interpretability_caveat"],
        "higher_score_predictive": "WEAK",
    } for d in ("LONG", "SHORT")},
    "PRE_FLIP_SCORE_RAMP": {d: {
        "median_score_T180": round(p4[d]["by_relative_time"]["T-180s"]["median_score"], 3),
        "median_score_T120": round(p4[d]["by_relative_time"]["T-120s"]["median_score"], 3),
        "median_score_T60": round(p4[d]["by_relative_time"]["T-60s"]["median_score"], 3),
        "median_score_T30": round(p4[d]["by_relative_time"]["T-30s"]["median_score"], 3),
        "pct_P90_T180": round(p4[d]["by_relative_time"]["T-180s"]["pct_ge_P90"], 3),
        "pct_P90_T120": round(p4[d]["by_relative_time"]["T-120s"]["pct_ge_P90"], 3),
        "pct_P90_T60": round(p4[d]["by_relative_time"]["T-60s"]["pct_ge_P90"], 3),
        "pct_P90_T30": round(p4[d]["by_relative_time"]["T-30s"]["pct_ge_P90"], 3),
        "first_P90_median_seconds_before_flip": p4[d]["first_P90_seconds_before_flip"]["median"],
        "per_regime_rise_T180_to_T60_median": p4[d]["score_rise_T180_to_T60_later_minus_earlier"]["median"],
        "per_regime_rise_T180_to_T60_p25": p4[d]["score_rise_T180_to_T60_later_minus_earlier"]["p25"],
        "systematic_ramp": p4[d]["systematic_ramp"],
    } for d in ("LONG", "SHORT")},
    "NONFLIPPING_CONTROL_PART5": {d: r["PART_5_nonflipping_control"][d]["by_regime_age_bin"] for d in ("LONG", "SHORT")},
    "MAX_SCORE_PER_REGIME": {"RETROSPECTIVE_ONLY": True, **{d: {
        "descriptive_ROC_vs_ever_flip": round(p6[d]["descriptive_roc_auc_vs_ever_flip"], 3),
        "descriptive_PR_vs_ever_flip": round(p6[d]["descriptive_pr_auc_vs_ever_flip"], 3),
        "bottom_quartile_eventual_flip_rate": round(p6[d]["eventual_flip_by_max_score_quartile"][0]["eventual_flip_rate"], 3),
        "top_quartile_eventual_flip_rate": round(p6[d]["eventual_flip_by_max_score_quartile"][-1]["eventual_flip_rate"], 3),
    } for d in ("LONG", "SHORT")}},
    "INTERPRETATION": {
        "between_regime_signal": "negligible-to-negative (first-eligible ROC ~0.49/0.46; max-score ROC 0.43/0.44, inverted top quartile)",
        "within_regime_timing_signal": "present and systematic both directions; carries the entire ~0.20 ROC gain over first-checkpoint",
        "first_P90_is_early_warning": "YES -- median ~115-148s before the flip; confidence keeps rising afterward",
        "score_after_P90_adds_information": "WEAK -- non-monotonic across first-fire score quartiles",
        "checkpoint_ROC_dependence_caveat": CAVEAT,
    },
    "PRIMARY_VERDICT": "WITHIN_REGIME_TIMING_SIGNAL",
    "MODEL_CHANGED": "NO", "THRESHOLD_CHANGED": "NO", "NT_RERUN": "NO",
    "NEW_OOS_ACCESSED": "NO", "2025_2026_ACCESSED": "NO",
}
(V / "artifacts" / "MARCH_REGIME_LEVEL_SCORE_DIAGNOSTIC_CARD.json").write_text(json.dumps(card, indent=2, default=str), encoding="utf-8")
print("WROTE MARCH_REGIME_LEVEL_SCORE_DIAGNOSTIC_CARD.json + PART_7 in REGIME_LEVEL_SCORE_DIAGNOSTIC.json")
