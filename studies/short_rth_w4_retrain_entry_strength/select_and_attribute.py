"""Selection gate + failure attribution + final decision.

Selects the best (model, retention band) using 2025 Layer-2 economics only
(never 2026), then evaluates that frozen selection on sealed 2026, checks
the selection gate criteria from SPEC.md, and computes failure attribution
against both the 100%-retention own-baseline (what the model's own filtering
changed) and the known external Baseline A/B/C numbers.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
WORK, RESULTS = HERE / "_work", HERE / "results"

BANDS = [1.00, 0.85, 0.70, 0.50, 0.35, 0.20]

BASELINE_A = {  # current original W4 candidate basis, from threshold ladder
    "2025": {"trades": 650, "net_pnl": 15366.0, "per_trade": 15366.0 / 650},
    "2026": {"trades": 222, "net_pnl": 6884.0, "per_trade": 6884.0 / 222},
    "combined": {"trades": 872, "net_pnl": 22250.0, "per_trade": 25.52,
                "profit_factor": 1.129, "max_dd": 18686.0},
}
BASELINE_B = {  # confirmed fixed-807 pocket
    "2025": {"trades": 604, "net_pnl": 20304.0, "per_trade": 20304.0 / 604},
    "2026": {"trades": 203, "net_pnl": 6709.0, "per_trade": 6709.0 / 203},
    "combined": {"trades": 807, "net_pnl": 27013.0, "per_trade": 33.47,
                "profit_factor": 1.174, "max_dd": 14331.0},
}
BASELINE_C = {  # NT Phase 1 schedule-driven benchmark
    "combined": {"trades": 807, "net_pnl": 23270.0, "per_trade": 28.84,
                "profit_factor": 1.149, "max_dd": 15000.0},
}


def select_best(econ: pd.DataFrame) -> dict:
    """Select using 2025 Layer-2 economics only. Primary criterion: highest
    per-trade PnL among combos with the highest profit factor tier; ties
    broken by profit factor, then lower max drawdown."""
    dev = econ[(econ.split == "2025") & (econ.layer == "layer2_one_per_regime")].copy()
    dev = dev[dev["trades"] > 0]
    dev = dev.sort_values(["per_trade", "profit_factor"], ascending=[False, False])
    best = dev.iloc[0]
    return {"model": best["model"], "retention_band": float(best["retention_band"]),
            "dev_per_trade": float(best["per_trade"]), "dev_net_pnl": float(best["net_pnl"]),
            "dev_profit_factor": float(best["profit_factor"]), "dev_trades": int(best["trades"]),
            "dev_max_dd": float(best["max_closed_trade_dd"])}


def attribution(model: str, band: float) -> dict:
    """Compare the selected model/band's schedule against that SAME model's
    own 100%-retention schedule (what filtering changed), per split."""
    out = {}
    for split in ("2025", "2026"):
        full = pd.read_parquet(WORK / f"schedule_{model}_{split}_1.0.parquet")
        sel = pd.read_parquet(WORK / f"schedule_{model}_{split}_{band}.parquet")
        full_regimes = set(full["regime_start_ns"])
        sel_regimes = set(sel["regime_start_ns"])
        removed_regimes = full_regimes - sel_regimes
        removed = full[full["regime_start_ns"].isin(removed_regimes)].copy()
        for col in ("hit_pre_alignment_stop", "hit_opposing_flip", "hit_timeout",
                    "hit_post_alignment_stop"):
            removed[col] = removed[col].astype(bool)

        stops_avoided = int(removed["hit_pre_alignment_stop"].sum())
        winners_removed = removed[removed["net_pnl"] > 0]
        losers_removed = removed[removed["net_pnl"] <= 0]
        opposing_winners_removed = removed[removed["hit_opposing_flip"] & (removed["net_pnl"] > 0)]

        month_full = full.copy()
        month_full["month"] = pd.to_datetime(month_full["entry_ts"], unit="ns", utc=True).dt.strftime("%Y-%m")
        month_sel = sel.copy()
        month_sel["month"] = pd.to_datetime(month_sel["entry_ts"], unit="ns", utc=True).dt.strftime("%Y-%m")
        pnl_by_month_full = month_full.groupby("month")["net_pnl"].sum()
        pnl_by_month_sel = month_sel.groupby("month")["net_pnl"].sum()

        out[split] = {
            "full_100pct_trades": len(full), "selected_trades": len(sel),
            "regimes_removed": len(removed_regimes),
            "pre_alignment_stops_avoided_by_removal": stops_avoided,
            # Positive = dollar value SAVED by avoiding these (losing) stop-outs.
            # These rows' own net_pnl is negative (they hit the stop); negate
            # the sum so the sign matches the field name.
            "net_pnl_saved_from_avoided_stops": float(
                -removed.loc[removed["hit_pre_alignment_stop"], "net_pnl"].sum()),
            "winners_removed_count": len(winners_removed),
            "net_pnl_lost_from_removed_winners": float(winners_removed["net_pnl"].sum()),
            "opposing_flip_winners_removed_count": len(opposing_winners_removed),
            "net_pnl_lost_from_removed_opposing_flip_winners": float(
                opposing_winners_removed["net_pnl"].sum()),
            "losers_removed_count": len(losers_removed),
            "net_pnl_saved_from_removed_losers": float(-losers_removed["net_pnl"].sum()),
            "timeout_rate_full": float(full["hit_timeout"].mean()) if len(full) else np.nan,
            "timeout_rate_selected": float(sel["hit_timeout"].mean()) if len(sel) else np.nan,
            "post_align_stop_rate_full": float(full["hit_post_alignment_stop"].mean()) if len(full) else np.nan,
            "post_align_stop_rate_selected": float(sel["hit_post_alignment_stop"].mean()) if len(sel) else np.nan,
            "monthly_pnl_full": pnl_by_month_full.to_dict(),
            "monthly_pnl_selected": pnl_by_month_sel.to_dict(),
            "monthly_concentration_selected_top1_share": (
                float(pnl_by_month_sel.abs().max() / pnl_by_month_sel.abs().sum())
                if len(pnl_by_month_sel) and pnl_by_month_sel.abs().sum() > 0 else np.nan
            ),
        }
    return out


def apply_gate(best: dict, dev_row: pd.Series, test_row: pd.Series) -> tuple[str, dict]:
    baseline_2025 = BASELINE_A["2025"]
    baseline_2026 = BASELINE_A["2026"]

    dev_improves = (dev_row["per_trade"] > baseline_2025["per_trade"]
                    or dev_row["profit_factor"] > 1.129)
    test_positive = test_row["net_pnl"] > 0
    test_not_materially_worse = (
        test_row["per_trade"] > 0.5 * baseline_2026["per_trade"] if test_positive else False)

    gate = {
        "dev_2025_improves_over_baseline_a": bool(dev_improves),
        "dev_2025_per_trade": float(dev_row["per_trade"]),
        "baseline_a_2025_per_trade": baseline_2025["per_trade"],
        "test_2026_positive": bool(test_positive),
        "test_2026_per_trade": float(test_row["per_trade"]),
        "baseline_a_2026_per_trade": baseline_2026["per_trade"],
        "test_2026_not_materially_worse_than_baseline": bool(test_not_materially_worse),
    }

    if not dev_improves:
        decision = "SHORT_RTH_BASELINE_STILL_BEST"
    elif dev_improves and not test_positive:
        decision = "SHORT_RTH_RETRAIN_OVERFITS_2025"
    elif dev_improves and test_positive and not test_not_materially_worse:
        decision = "SHORT_RTH_RETRAIN_OVERFITS_2025"
    else:
        decision = "SHORT_RTH_RETRAIN_PROMISING"
    return decision, gate


def main() -> None:
    econ = pd.read_csv(RESULTS / "economic_results.csv")
    best = select_best(econ)
    model, band = best["model"], best["retention_band"]
    print(f"Selected on 2025: model={model} band={band} "
          f"per_trade={best['dev_per_trade']:.2f} net={best['dev_net_pnl']:.0f} "
          f"PF={best['dev_profit_factor']:.3f}")

    dev_row = econ[(econ.model == model) & (econ.split == "2025")
                  & (econ.retention_band == band)
                  & (econ.layer == "layer2_one_per_regime")].iloc[0]
    test_row = econ[(econ.model == model) & (econ.split == "2026")
                    & (econ.retention_band == band)
                    & (econ.layer == "layer2_one_per_regime")].iloc[0]

    decision, gate = apply_gate(best, dev_row, test_row)
    attrib = attribution(model, band)

    dev_schedule = pd.read_parquet(WORK / f"schedule_{model}_2025_{band}.parquet")
    test_schedule = pd.read_parquet(WORK / f"schedule_{model}_2026_{band}.parquet")
    dev_schedule.to_parquet(RESULTS / "best_model_trade_schedule.parquet", index=False)
    test_schedule.to_parquet(RESULTS / "best_model_oos_2026_trades.parquet", index=False)

    layer3 = pd.read_csv(RESULTS / "layer3_fixed807_overlay.csv")
    layer3_best = layer3[(layer3.model == model) & (layer3.retention_band == band)]

    manifest = {
        "decision": decision,
        "selected_model": model, "selected_retention_band": band,
        "selection_criterion": "highest 2025 Layer-2 per-trade PnL (tie-break: profit factor)",
        "dev_2025_economics": dev_row.to_dict(),
        "test_2026_economics": test_row.to_dict(),
        "selection_gate": gate,
        "failure_attribution": attrib,
        "layer3_fixed807_overlay_for_selected": layer3_best.to_dict(orient="records"),
        "baselines": {"A_current_w4_candidate_basis": BASELINE_A,
                     "B_fixed_807_pocket": BASELINE_B,
                     "C_nt_phase1_benchmark": BASELINE_C},
    }
    (RESULTS / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    print("DECISION:", decision)
    print(json.dumps(gate, indent=2))


if __name__ == "__main__":
    main()
