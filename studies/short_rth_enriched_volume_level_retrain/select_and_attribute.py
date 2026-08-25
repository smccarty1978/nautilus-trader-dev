"""Selection gate + failure attribution + feature-family contribution +
final decision, for the enriched (feature-set x model) retrain.

Selects the best (feature_set, model, retention band) using 2025 Layer-2
economics only (never 2026), evaluates that frozen selection on sealed 2026,
checks the SPEC's selection-gate criteria, and computes:
  - stop-savings vs winner-clipping attribution (selected band vs that same
    model's own 100%-retention schedule);
  - feature-family contribution (existing / volume-delta / price-level) for
    the selected (feature_set, model) combo's fitted importances.

Baseline A's own per-trade/PF/max-DD are the only Baseline-A quantities
published as reusable constants in this project (no split-year
pre-alignment-stop-rate or opposing-flip-PnL constant for Baseline A exists
anywhere upstream) -- the "at least two of five" 2025 gate check is
therefore evaluated on the three criteria for which a real comparator
number exists (per_trade, profit_factor, max_dd), documented explicitly
rather than fabricating the other two.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
WORK, RESULTS = HERE / "_work", HERE / "results"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from features.registry import resolve_feature_request  # noqa: E402

BANDS = [1.00, 0.85, 0.70, 0.50, 0.35, 0.20]

BASELINE_A = {
    "2025": {"trades": 650, "net_pnl": 15366.0, "per_trade": 15366.0 / 650},
    "2026": {"trades": 222, "net_pnl": 6884.0, "per_trade": 6884.0 / 222},
    "combined": {"trades": 872, "net_pnl": 22250.0, "per_trade": 25.52,
                "profit_factor": 1.129, "max_dd": 18686.0},
}
BASELINE_B = {
    "2025": {"trades": 604, "net_pnl": 20304.0, "per_trade": 20304.0 / 604},
    "2026": {"trades": 203, "net_pnl": 6709.0, "per_trade": 6709.0 / 203},
    "combined": {"trades": 807, "net_pnl": 27013.0, "per_trade": 33.47,
                "profit_factor": 1.174, "max_dd": 14331.0},
}
BASELINE_C = {
    "combined": {"trades": 807, "net_pnl": 23270.0, "per_trade": 28.84,
                "profit_factor": 1.149, "max_dd": 15000.0},
}
BASELINE_D_PRIOR_RETRAIN = {
    "decision": "SHORT_RTH_BASELINE_STILL_BEST", "selected_model": "GBT", "retention": 0.35,
    "2025": {"per_trade": 4.75, "profit_factor": 1.029},
    "2026": {"per_trade": -32.36, "profit_factor": 0.825},
}


def select_best(econ: pd.DataFrame) -> pd.Series:
    dev = econ[(econ.split == "2025") & (econ.layer == "layer2_one_per_regime")].copy()
    dev = dev[dev["trades"] > 0]
    dev = dev.sort_values(["per_trade", "profit_factor"], ascending=[False, False])
    return dev.iloc[0]


def feature_family(feat: str, f0_feats: set[str]) -> str:
    if feat in f0_feats:
        return "existing"
    base = feat.split("__")[0] if "__" in feat else feat
    try:
        d = resolve_feature_request(feat if feat != base else base)
    except Exception:
        d = None
    if d is not None:
        return "volume_delta" if "ohlcv_est_delta" in str(d["family"]) else "price_level"
    raise RuntimeError(f"could not classify feature family for {feat!r}")


def attribution(key: str, band: float) -> dict:
    out = {}
    for split in ("2025", "2026"):
        full = pd.read_parquet(WORK / f"schedule_{key}_{split}_1.0.parquet")
        sel = pd.read_parquet(WORK / f"schedule_{key}_{split}_{band}.parquet")
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

        net_saved_from_stops = float(-removed.loc[removed["hit_pre_alignment_stop"], "net_pnl"].sum())
        net_lost_from_opp_winners = float(opposing_winners_removed["net_pnl"].sum())

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
            "net_pnl_saved_from_avoided_stops": net_saved_from_stops,
            "winners_removed_count": len(winners_removed),
            "net_pnl_lost_from_removed_winners": float(winners_removed["net_pnl"].sum()),
            "opposing_flip_winners_removed_count": len(opposing_winners_removed),
            "net_pnl_lost_from_removed_opposing_flip_winners": net_lost_from_opp_winners,
            "net_stop_savings_minus_winner_clipping": net_saved_from_stops - net_lost_from_opp_winners,
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


def apply_gate(dev_row: pd.Series, test_row: pd.Series, attrib: dict) -> tuple[str, dict]:
    b25, b26 = BASELINE_A["2025"], BASELINE_A["2026"]
    bc = BASELINE_A["combined"]

    criteria_2025 = {
        "per_trade_beats_baseline_a": bool(dev_row["per_trade"] > b25["per_trade"]),
        "profit_factor_beats_baseline_a": bool(dev_row["profit_factor"] > bc["profit_factor"]),
        "max_dd_better_than_baseline_a": bool(dev_row["max_closed_trade_dd"] < bc["max_dd"]),
    }
    dev_improves = sum(criteria_2025.values()) >= 2

    test_positive = bool(test_row["net_pnl"] > 0)
    test_pf_ok = bool(test_row["profit_factor"] > 0.5 * bc["profit_factor"]) if test_positive else False
    test_pt_ok = bool(test_row["per_trade"] > 0.5 * b26["per_trade"]) if test_positive else False
    test_not_materially_worse = test_pf_ok and test_pt_ok

    monthly_ok_2025 = (attrib["2025"]["monthly_concentration_selected_top1_share"] is None
                      or attrib["2025"]["monthly_concentration_selected_top1_share"] <= 0.60
                      or np.isnan(attrib["2025"]["monthly_concentration_selected_top1_share"]))
    monthly_ok_2026 = (attrib["2026"]["monthly_concentration_selected_top1_share"] is None
                      or attrib["2026"]["monthly_concentration_selected_top1_share"] <= 0.60
                      or np.isnan(attrib["2026"]["monthly_concentration_selected_top1_share"]))
    monthly_ok = bool(monthly_ok_2025 and monthly_ok_2026)

    clips_winners = (attrib["2025"]["net_stop_savings_minus_winner_clipping"] < 0
                     or attrib["2026"]["net_stop_savings_minus_winner_clipping"] < 0)

    gate = {
        "criteria_2025": criteria_2025, "dev_2025_improves_over_baseline_a": bool(dev_improves),
        "dev_2025_per_trade": float(dev_row["per_trade"]), "baseline_a_2025_per_trade": b25["per_trade"],
        "test_2026_positive": test_positive, "test_2026_per_trade": float(test_row["per_trade"]),
        "baseline_a_2026_per_trade": b26["per_trade"],
        "test_2026_not_materially_worse_than_baseline": test_not_materially_worse,
        "monthly_shape_ok": monthly_ok, "clips_winners": bool(clips_winners),
    }

    if not dev_improves:
        decision = "ENRICHED_RETRAIN_BASELINE_STILL_BEST"
    elif not test_positive or not test_not_materially_worse or not monthly_ok:
        decision = "ENRICHED_RETRAIN_OVERFITS_2025"
    elif clips_winners:
        decision = "ENRICHED_RETRAIN_CLIPS_WINNERS"
    else:
        decision = "ENRICHED_RETRAIN_PROMISING"
    return decision, gate


def build_feature_family_contribution(fs_name: str, model_name: str, f0_feats: set[str]) -> pd.DataFrame:
    imp = pd.read_csv(RESULTS / "feature_importance.csv")
    imp = imp[(imp.feature_set == fs_name) & (imp.model == model_name)].copy()
    imp["abs_importance"] = imp["coefficient"].abs()
    per_feature = imp.groupby("feature", as_index=False)["abs_importance"].sum()
    per_feature["family"] = per_feature["feature"].apply(lambda f: feature_family(f, f0_feats))
    agg = per_feature.groupby("family", as_index=False)["abs_importance"].sum()
    agg["share"] = agg["abs_importance"] / agg["abs_importance"].sum()
    agg["feature_set"], agg["model"] = fs_name, model_name
    return agg.sort_values("share", ascending=False)


def main() -> None:
    econ = pd.read_csv(RESULTS / "economic_results.csv")
    best = select_best(econ)
    fs_name, model_name, band = best["feature_set"], best["model"], float(best["retention_band"])
    key = f"{fs_name}__{model_name}"
    print(f"Selected on 2025: feature_set={fs_name} model={model_name} band={band} "
          f"per_trade={best['per_trade']:.2f} net={best['net_pnl']:.0f} PF={best['profit_factor']:.3f}")

    dev_row = econ[(econ.feature_set == fs_name) & (econ.model == model_name)
                  & (econ.split == "2025") & (econ.retention_band == band)
                  & (econ.layer == "layer2_one_per_regime")].iloc[0]
    test_row = econ[(econ.feature_set == fs_name) & (econ.model == model_name)
                    & (econ.split == "2026") & (econ.retention_band == band)
                    & (econ.layer == "layer2_one_per_regime")].iloc[0]

    attrib = attribution(key, band)
    decision, gate = apply_gate(dev_row, test_row, attrib)

    dev_schedule = pd.read_parquet(WORK / f"schedule_{key}_2025_{band}.parquet")
    test_schedule = pd.read_parquet(WORK / f"schedule_{key}_2026_{band}.parquet")
    dev_schedule.to_parquet(RESULTS / "selected_model_trade_schedule.parquet", index=False)
    test_schedule.to_parquet(RESULTS / "selected_model_oos_2026_trades.parquet", index=False)

    layer3 = pd.read_csv(RESULTS / "layer3_fixed807_overlay.csv")
    layer3_best = layer3[(layer3.feature_set == fs_name) & (layer3.model == model_name)
                         & (layer3.retention_band == band)]

    feature_sets = json.loads((WORK / "feature_sets.json").read_text(encoding="utf-8"))
    f0_feats = set(feature_sets["F0_existing_only"])
    all_family_rows = []
    for fs, cols in feature_sets.items():
        if fs == "F0_existing_only":
            continue
        for m in ("logreg", "gbt"):
            all_family_rows.append(build_feature_family_contribution(fs, m, f0_feats))
    pd.concat(all_family_rows, ignore_index=True).to_csv(
        RESULTS / "feature_family_contribution.csv", index=False)

    # Feature-set comparison table: best band per (feature_set, model) on 2025, its 2026 result.
    comparison_rows = []
    for fs in feature_sets:
        for m in ("logreg", "gbt"):
            sub = econ[(econ.feature_set == fs) & (econ.model == m) & (econ.split == "2025")
                      & (econ.layer == "layer2_one_per_regime") & (econ.trades > 0)]
            if len(sub) == 0:
                continue
            b = sub.sort_values(["per_trade", "profit_factor"], ascending=[False, False]).iloc[0]
            t = econ[(econ.feature_set == fs) & (econ.model == m) & (econ.split == "2026")
                    & (econ.layer == "layer2_one_per_regime") & (econ.retention_band == b["retention_band"])]
            t_row = t.iloc[0] if len(t) else None
            comparison_rows.append({
                "feature_set": fs, "model": m, "best_band_2025": b["retention_band"],
                "2025_trades": b["trades"], "2025_per_trade": b["per_trade"], "2025_pf": b["profit_factor"],
                "2026_trades": t_row["trades"] if t_row is not None else np.nan,
                "2026_per_trade": t_row["per_trade"] if t_row is not None else np.nan,
                "2026_pf": t_row["profit_factor"] if t_row is not None else np.nan,
            })

    manifest = {
        "decision": decision,
        "selected_feature_set": fs_name, "selected_model": model_name, "selected_retention_band": band,
        "selection_criterion": "highest 2025 Layer-2 per-trade PnL across all 48 (feature_set,model,band) combos (tie-break: profit factor)",
        "dev_2025_economics": dev_row.to_dict(), "test_2026_economics": test_row.to_dict(),
        "selection_gate": gate, "failure_attribution": attrib,
        "layer3_fixed807_overlay_for_selected": layer3_best.to_dict(orient="records"),
        "feature_set_comparison": comparison_rows,
        "baselines": {"A_current_w4_candidate_basis": BASELINE_A, "B_fixed_807_pocket": BASELINE_B,
                     "C_nt_phase1_benchmark": BASELINE_C, "D_prior_149_feature_retrain": BASELINE_D_PRIOR_RETRAIN},
        "note_on_2025_gate_scope": (
            "Baseline A publishes only per_trade/profit_factor/max_dd as reusable constants "
            "(no split-year pre_alignment_stop_rate or opposing_flip_pnl constant exists "
            "upstream for Baseline A itself) -- the 'at least two of five' 2025 check is "
            "therefore evaluated on these three criteria only. Pre-alignment-stop-rate and "
            "opposing-flip-PnL are reported as within-model before/after attribution instead "
            "(see failure_attribution), which is what the SPEC's separate stop-savings-vs-"
            "winner-clipping comparison actually asks for."
        ),
    }
    (RESULTS / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    pd.DataFrame(comparison_rows).to_csv(RESULTS / "feature_set_comparison.csv", index=False)
    print("DECISION:", decision)
    print(json.dumps(gate, indent=2, default=str))
    print(pd.DataFrame(comparison_rows).to_string(index=False))


if __name__ == "__main__":
    main()
