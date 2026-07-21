"""Selects the best trigger variant on 2025 MAR-like score, applies the
signal-to-policy viability gate, saves selected trades + monthly/exit-reason
breakdowns.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
WORK, RESULTS = HERE / "_work", HERE / "results"

BASELINE_A = {
    "2025": {"trades": 650, "net_pnl": 15366.0, "per_trade": 15366.0 / 650},
    "2026": {"trades": 222, "net_pnl": 6884.0, "per_trade": 6884.0 / 222},
    "combined": {"trades": 872, "net_pnl": 22250.0, "per_trade": 25.52,
                "profit_factor": 1.129, "max_dd": 18686.0},
}
BASELINE_B = {"combined": {"trades": 807, "net_pnl": 27013.0, "per_trade": 33.47,
                          "profit_factor": 1.174, "max_dd": 14331.0}}
MATERIALLY_WORSE_MULT = 0.5


def monthly(schedule: pd.DataFrame) -> pd.DataFrame:
    if len(schedule) == 0:
        return pd.DataFrame(columns=["month", "trades", "net_pnl"])
    g = schedule.copy()
    g["month"] = pd.to_datetime(g["entry_ts"], unit="ns", utc=True).dt.strftime("%Y-%m")
    return g.groupby("month").agg(trades=("net_pnl", "size"), net_pnl=("net_pnl", "sum")).reset_index()


def exit_attribution(schedule: pd.DataFrame) -> pd.DataFrame:
    if len(schedule) == 0:
        return pd.DataFrame(columns=["exit_reason", "count", "pct", "net_pnl"])
    counts = schedule["exit_reason"].value_counts()
    pnl = schedule.groupby("exit_reason")["net_pnl"].sum()
    return pd.DataFrame({
        "exit_reason": counts.index, "count": counts.values,
        "pct": (counts / len(schedule) * 100).values,
        "net_pnl": [float(pnl.get(r, 0.0)) for r in counts.index],
    })


def select_best(grid: pd.DataFrame) -> pd.Series:
    dev = grid[(grid.split == 2025) & (grid.trades > 0)].copy()
    dev = dev.sort_values(
        ["mar_like_score", "per_trade", "profit_factor", "pre_alignment_stop_rate", "trades"],
        ascending=[False, False, False, True, True])
    return dev.iloc[0]


def apply_gate(dev_row: pd.Series, test_row: pd.Series, monthly_ok: bool, clip_ok: bool) -> tuple[str, dict]:
    b25, b26, bc = BASELINE_A["2025"], BASELINE_A["2026"], BASELINE_A["combined"]

    dev_pass = (
        dev_row["net_pnl"] > 0
        and (dev_row["profit_factor"] > bc["profit_factor"] or dev_row["profit_factor"] > 1.10)
        and dev_row["max_closed_trade_dd"] <= bc["max_dd"]
        and dev_row["per_trade"] >= b25["per_trade"]
    )
    test_positive = test_row["net_pnl"] > 0
    test_pt_ok = test_row["per_trade"] > MATERIALLY_WORSE_MULT * b26["per_trade"] if test_positive else False
    test_pass = (
        test_positive and test_row["profit_factor"] > 1.05 and test_pt_ok
        and monthly_ok and clip_ok
    )

    gate = {
        "dev_2025_pass": bool(dev_pass), "test_2026_pass": bool(test_pass),
        "dev_net_pnl": float(dev_row["net_pnl"]), "dev_pf": float(dev_row["profit_factor"]),
        "dev_max_dd": float(dev_row["max_closed_trade_dd"]), "dev_per_trade": float(dev_row["per_trade"]),
        "test_net_pnl": float(test_row["net_pnl"]), "test_pf": float(test_row["profit_factor"]),
        "test_per_trade": float(test_row["per_trade"]), "test_pt_ok_0.5x_baseline": bool(test_pt_ok),
        "baseline_a_2026_per_trade": b26["per_trade"], "monthly_ok": bool(monthly_ok), "clip_ok": bool(clip_ok),
    }

    beats_baseline_2025 = dev_row["per_trade"] > b25["per_trade"] and dev_row["profit_factor"] > bc["profit_factor"]
    if not dev_pass:
        decision = "FLIP_SCORE_SIGNAL_NOT_MONETIZED"
    elif not test_positive:
        decision = "FLIP_SCORE_POLICY_OVERFITS_2025"
    elif not test_pass:
        decision = ("FLIP_SCORE_POLICY_WEAK_BUT_USEFUL" if test_row["profit_factor"] > 1.0
                    else "FLIP_SCORE_POLICY_OVERFITS_2025")
    elif beats_baseline_2025 and test_row["per_trade"] >= b26["per_trade"]:
        decision = "FLIP_SCORE_POLICY_PROMISING"
    else:
        decision = "FLIP_SCORE_POLICY_WEAK_BUT_USEFUL"
    return decision, gate


def main() -> None:
    grid = pd.read_csv(RESULTS / "trigger_grid_results.csv")
    best = select_best(grid)
    trig = best["trigger"]
    print(f"Selected on 2025: {trig} (MAR={best['mar_like_score']:.4f}, "
          f"per_trade={best['per_trade']:.2f}, PF={best['profit_factor']:.3f})")

    dev_row = grid[(grid.trigger == trig) & (grid.split == 2025)].iloc[0]
    test_row = grid[(grid.trigger == trig) & (grid.split == 2026)].iloc[0]

    dev_sched = pd.read_parquet(WORK / f"schedule_{trig}_2025.parquet")
    test_sched = pd.read_parquet(WORK / f"schedule_{trig}_2026.parquet")
    dev_sched.to_parquet(RESULTS / "selected_trades_2025.parquet", index=False)
    test_sched.to_parquet(RESULTS / "selected_trades_2026.parquet", index=False)

    monthly_rows = []
    for split_name, sched in (("2025", dev_sched), ("2026", test_sched)):
        m = monthly(sched)
        for _, r in m.iterrows():
            monthly_rows.append({"split": split_name, **r.to_dict()})
    monthly_df = pd.DataFrame(monthly_rows)
    monthly_df.to_csv(RESULTS / "monthly_results.csv", index=False)

    test_monthly = monthly_df[monthly_df.split == "2026"]
    monthly_ok = True
    if len(test_monthly) >= 2 and test_monthly["net_pnl"].abs().sum() > 0:
        top1_share = test_monthly["net_pnl"].abs().max() / test_monthly["net_pnl"].abs().sum()
        monthly_ok = bool(top1_share <= 0.70)
    dominated_by_one_month = not monthly_ok

    exit_rows = []
    for split_name, sched in (("2025", dev_sched), ("2026", test_sched)):
        ea = exit_attribution(sched)
        for _, r in ea.iterrows():
            exit_rows.append({"split": split_name, **r.to_dict()})
    pd.DataFrame(exit_rows).to_csv(RESULTS / "exit_reason_attribution.csv", index=False)

    # Winner-clipping vs. this SAME trigger family's least-selective variant
    # (top20, same family letter) as the "before filtering" reference --
    # clip_ok = stop savings not outweighed by removed opposing-flip winners.
    family_prefix = trig.rsplit("_", 1)[0]
    least_selective = f"{family_prefix}_top20"
    if least_selective == trig:
        clip_ok = True  # trig IS the least-selective variant; nothing was filtered
    else:
        # No silent pass-on-missing-file: the reference schedule is a
        # required same-family output of trigger_grid.py and must exist by
        # construction. A missing file means the pipeline ran out of order
        # or produced an incomplete grid -- fail loudly (audit finding W2).
        full_sched = pd.read_parquet(WORK / f"schedule_{least_selective}_2026.parquet")
        removed = full_sched[~full_sched["regime_start_ns"].isin(test_sched["regime_start_ns"])]
        stops_saved = float(-removed.loc[removed["hit_pre_alignment_stop"], "net_pnl"].sum())
        opp_winners_lost = float(
            removed.loc[removed["hit_opposing_flip"] & (removed["net_pnl"] > 0), "net_pnl"].sum())
        clip_ok = (stops_saved - opp_winners_lost) >= 0

    decision, gate = apply_gate(dev_row, test_row, monthly_ok, clip_ok)

    summary = {
        "decision": decision, "selected_trigger": trig,
        "selection_criterion": "highest 2025 MAR-like score (net_pnl/max_closed_trade_dd), "
                              "tie-break: per_trade, PF, pre_alignment_stop_rate, fewer trades",
        "dev_2025": dev_row.to_dict(), "test_2026": test_row.to_dict(),
        "signal_to_policy_gate": gate, "monthly_dominated_by_one_month": dominated_by_one_month,
        "winner_clipping_ok": clip_ok,
        "best_by_per_trade_2025": grid[(grid.split == 2025) & (grid.trades > 0)]
            .sort_values("per_trade", ascending=False).iloc[0][["trigger", "per_trade"]].to_dict(),
        "best_by_pf_2025": grid[(grid.split == 2025) & (grid.trades > 0)]
            .sort_values("profit_factor", ascending=False).iloc[0][["trigger", "profit_factor"]].to_dict(),
    }
    (RESULTS / "selected_trigger_summary.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print("DECISION:", decision)
    print(json.dumps(gate, indent=2, default=str))


if __name__ == "__main__":
    main()
