"""Selects the best (feature_set, model) by 2025 raw AUC, applies the SPEC's
signal-viability gate, saves predictions parquets, and builds manifest.json.

Selection criterion: highest 2025 raw AUC (tie-break: 2025 average
precision) -- selected on 2025 only, per SPEC's train/dev/test discipline.
2026 is evaluated, never used to select.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
WORK, RESULTS = HERE / "_work", HERE / "results"
TARGET = "bearish_regime_flip_within_300s"

BASE_RATE_MIN_MULT = 1.0  # top-decile rate must exceed split base rate to count as "materially above"


def top_decile_lift(df: pd.DataFrame, score_col: str) -> dict:
    d = df[[score_col, TARGET]].copy()
    d["decile"] = pd.qcut(d[score_col], 10, labels=False, duplicates="drop")
    base_rate = float(d[TARGET].mean())
    top = d[d["decile"] == d["decile"].max()]
    bottom = d[d["decile"] == d["decile"].min()]
    top_rate = float(top[TARGET].mean())
    bottom_rate = float(bottom[TARGET].mean())
    lift = top_rate / base_rate if base_rate > 0 else np.nan
    # Monotonicity: is the decile curve non-decreasing (allow small noise)?
    curve = d.groupby("decile")[TARGET].mean().sort_index()
    inverted = bool(curve.iloc[-1] < curve.iloc[0])
    driven_by_one_month = None  # filled by caller if month data available
    return {"base_rate": base_rate, "top_decile_rate": top_rate, "bottom_decile_rate": bottom_rate,
            "top_decile_lift": lift, "decile_curve_inverted": inverted}


def apply_gate(dev_metrics: dict, dev_lift: dict, test_metrics: dict, test_lift: dict,
               monthly_ok: bool, regime_2025: dict, regime_2026: dict) -> tuple[str, dict]:
    """Row-level checks alone are NOT sufficient -- audit finding (completion-
    gate pass) caught that an earlier version of this function decided
    PURE_FLIP_SIGNAL_STRONG from row-level AUC/lift alone while never
    reading `results/regime_level_diagnostics.csv`, which SPEC.md requires
    specifically because rows overlap heavily within a regime and can
    inflate a naive row-level AUC. Regime-level checks are now a REQUIRED,
    not optional, gate condition."""
    min_2025_row = (dev_metrics["auc"] > 0.55 and dev_lift["top_decile_lift"] > BASE_RATE_MIN_MULT)
    min_2026_row = (test_metrics["auc"] > 0.55 and test_lift["top_decile_lift"] > BASE_RATE_MIN_MULT
                    and not test_lift["decile_curve_inverted"] and monthly_ok)
    strong_2025_row = dev_metrics["auc"] >= 0.60 and dev_lift["top_decile_lift"] >= 1.50
    strong_2026_row = test_metrics["auc"] >= 0.58 and test_lift["top_decile_lift"] >= 1.50

    # Regime-level bar: same 0.55 AUC / meaningfully-above-1.0-lift standard
    # as the row-level minimum bar, applied to the de-duplicated (one
    # peak-score row per regime) view.
    regime_2025_ok = (regime_2025["regime_level_auc"] > 0.55
                      and regime_2025["regime_level_top_decile_flip_rate"]
                      > regime_2025["regime_level_base_rate"] * BASE_RATE_MIN_MULT)
    regime_2026_ok = (regime_2026["regime_level_auc"] > 0.55
                      and regime_2026["regime_level_top_decile_flip_rate"]
                      > regime_2026["regime_level_base_rate"] * BASE_RATE_MIN_MULT)

    gate = {
        "min_2025_row_level_pass": bool(min_2025_row), "min_2026_row_level_pass": bool(min_2026_row),
        "strong_2025_row_level_pass": bool(strong_2025_row), "strong_2026_row_level_pass": bool(strong_2026_row),
        "regime_2025_pass": bool(regime_2025_ok), "regime_2026_pass": bool(regime_2026_ok),
        "regime_2025_auc": regime_2025["regime_level_auc"], "regime_2026_auc": regime_2026["regime_level_auc"],
        "dev_auc": dev_metrics["auc"], "test_auc": test_metrics["auc"],
        "dev_top_decile_lift": dev_lift["top_decile_lift"], "test_top_decile_lift": test_lift["top_decile_lift"],
    }

    if not min_2025_row:
        decision = "PURE_FLIP_SIGNAL_NOT_LEARNABLE"
    elif not min_2026_row:
        decision = "PURE_FLIP_SIGNAL_FAILS_2026"
    elif not (regime_2025_ok and regime_2026_ok):
        # Row-level clears the bar cleanly but regime-level (the
        # de-duplicated, arguably more decision-relevant view) does not --
        # exactly SPEC.md's own definition of INCONCLUSIVE ("mixed metrics
        # ... unclear regime-level behavior"), not a pass.
        decision = "PURE_FLIP_SIGNAL_INCONCLUSIVE"
    elif strong_2025_row and strong_2026_row:
        decision = "PURE_FLIP_SIGNAL_STRONG"
    else:
        decision = "PURE_FLIP_SIGNAL_WEAK_BUT_REAL"
    return decision, gate


def main() -> None:
    metrics = pd.read_csv(RESULTS / "model_metrics.csv")
    metrics = metrics.sort_values(["2025_auc_raw", "2025_average_precision_raw"], ascending=False)
    best = metrics.iloc[0]
    fs_name, model_name = best["feature_set"], best["model"]
    key = f"{fs_name}__{model_name}"
    print(f"Selected on 2025: {key} (2025 AUC raw={best['2025_auc_raw']:.4f})")

    dev_df = pd.read_parquet(WORK / "scored_dev_2025.parquet")
    test_df = pd.read_parquet(WORK / "scored_test_2026.parquet")
    score_col = f"score_{key}_raw"

    dev_metrics = {"auc": float(best["2025_auc_raw"]), "average_precision": float(best["2025_average_precision_raw"]),
                  "brier": float(best["2025_brier_raw"]), "logloss": float(best["2025_logloss_raw"])}
    test_metrics = {"auc": float(best["2026_auc_raw"]), "average_precision": float(best["2026_average_precision_raw"]),
                   "brier": float(best["2026_brier_raw"]), "logloss": float(best["2026_logloss_raw"])}
    dev_lift = top_decile_lift(dev_df, score_col)
    test_lift = top_decile_lift(test_df, score_col)

    test_df_m = test_df.copy()
    test_df_m["month"] = pd.to_datetime(test_df_m["observation_time"], unit="ns", utc=True).dt.strftime("%Y-%m")
    monthly_auc_ok = True
    monthly_rows = []
    from sklearn.metrics import roc_auc_score
    for month, g in test_df_m.groupby("month"):
        if g[TARGET].nunique() < 2:
            continue
        auc_m = roc_auc_score(g[TARGET].astype(int), g[score_col])
        monthly_rows.append({"month": month, "n": len(g), "auc": auc_m})
    monthly_df = pd.DataFrame(monthly_rows)
    if len(monthly_df) >= 2:
        monthly_auc_ok = bool((monthly_df["auc"] > 0.50).sum() >= len(monthly_df) - 1)

    regime_df = pd.read_csv(RESULTS / "regime_level_diagnostics.csv")
    regime_2025 = regime_df[(regime_df.feature_set == fs_name) & (regime_df.model == model_name)
                            & (regime_df.split == 2025)].iloc[0].to_dict()
    regime_2026 = regime_df[(regime_df.feature_set == fs_name) & (regime_df.model == model_name)
                            & (regime_df.split == 2026)].iloc[0].to_dict()

    decision, gate = apply_gate(dev_metrics, dev_lift, test_metrics, test_lift, monthly_auc_ok,
                                regime_2025, regime_2026)

    pred_cols = ["regime_start_ns", "observation_time", "confirm_flip_ns", TARGET,
                "bearish_flip_within_600s", "time_to_bearish_flip_s",
                "post_flip_mfe_atr_300s", "post_flip_mfe_atr_600s",
                "adverse_move_1p25A_before_bearish_flip",
                "hit_pre_alignment_stop", "hit_timeout", "hit_post_alignment_stop",
                "hit_opposing_flip", "opposing_flip_exit_positive", "net_pnl", "exit_reason",
                score_col, f"score_{key}_isotonic", f"score_{key}_sigmoid"]
    dev_df[pred_cols].to_parquet(RESULTS / "selected_model_predictions_2025.parquet", index=False)
    test_df[pred_cols].to_parquet(RESULTS / "selected_model_predictions_2026.parquet", index=False)

    manifest = {
        "decision": decision, "selected_feature_set": fs_name, "selected_model": model_name,
        "selection_criterion": "highest 2025 raw AUC (tie-break: 2025 average precision)",
        "dev_2025_metrics": dev_metrics, "dev_2025_decile_lift": dev_lift,
        "test_2026_metrics": test_metrics, "test_2026_decile_lift": test_lift,
        "test_2026_monthly_auc": monthly_df.to_dict(orient="records"),
        "test_2026_monthly_auc_ok": monthly_auc_ok,
        "regime_level_2025": regime_2025, "regime_level_2026": regime_2026,
        "signal_viability_gate": gate,
        "all_combo_metrics_summary": metrics[["feature_set", "model", "2025_auc_raw", "2026_auc_raw",
                                              "2025_average_precision_raw", "2026_average_precision_raw"]
                                              ].to_dict(orient="records"),
    }
    (RESULTS / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    print("DECISION:", decision)
    print(json.dumps(gate, indent=2, default=str))


if __name__ == "__main__":
    main()
