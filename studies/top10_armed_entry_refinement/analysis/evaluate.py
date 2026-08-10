"""Phases 4-6 — tradeoff table, frontier, stability. Writes the deliverables."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl

from ..implementation.candidates import (
    ALL_RULES, BASELINES, CANDIDATES, evaluate, first_firings, with_reexpansion,
)

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "studies/top10_armed_entry_refinement/results"
STREAM = OUT / "armed_score_path_diagnostics.parquet"
YEARS = (2021, 2022, 2023, 2024, 2025)
BASE = "A_IMMEDIATE_TOP10"


def _q(s, p):
    s = s.drop_nulls()
    return round(float(s.quantile(p)), 4) if s.len() else None


def _med(s):
    return _q(s, 0.5)


def summarise(t: pl.DataFrame, n_arms: int, base_rate: float | None,
              base_return: float | None) -> dict:
    if t.height == 0:
        return {"n": 0}
    conf = t.filter(pl.col("confirmed"))
    p_conf = float(t["confirmed"].mean())
    entered = t.height / n_arms
    sac = t["price_move_arm_to_entry_atr"]
    wait = t["seconds_arm_to_entry"]
    d_p = (p_conf - base_rate) if base_rate is not None else None
    med_sac = _med(sac) or 0.0
    med_wait = _med(wait) or 0.0
    out = {
        "n": t.height,
        "pct_arms_entered": round(100 * entered, 2),
        "p_confirm_given_entered": round(p_conf, 4),
        "confirmed_per_100_arms": round(100 * entered * p_conf, 2),
        "lift_vs_top10": round(d_p, 4) if d_p is not None else None,
        "pct_stopped_before_confirm": round(float(t["stopped_before_confirm"].mean()), 4),
        "pct_session_unresolved": round(float(t["session_unresolved"].mean()), 4),
        "median_seconds_arm_to_entry": med_wait,
        "mean_seconds_arm_to_entry": round(float(wait.mean()), 2) if wait.len() else None,
        "median_price_move_arm_to_entry_atr": med_sac,
        "p25_price_move": _q(sac, 0.25), "p75_price_move": _q(sac, 0.75),
        "p90_price_move": _q(sac, 0.90),
        "pct_entries_after_arm_1atr_adverse": round(
            100 * float(t["entered_after_arm_1atr_adverse"].fill_null(False).mean()), 2),
        "ambiguous": int(t["ambiguous"].fill_null(False).sum()),
    }
    if conf.height:
        r = conf["return_at_confirm_atr"]
        out.update({
            "median_return_at_confirm_atr": _med(r),
            "mean_return_at_confirm_atr": round(float(r.mean()), 4),
            "median_mfe_to_confirm_atr": _med(conf["mfe_to_confirm_atr"]),
            "median_mae_to_confirm_atr": _med(conf["mae_to_confirm_atr"]),
            "median_seconds_entry_to_confirm": _med(conf["seconds_entry_to_confirm"]),
            "pct_positive_at_confirm": round(100 * float((r > 0).mean()), 2),
            "pct_ge_0_25": round(100 * float((r >= 0.25).mean()), 2),
            "pct_ge_0_50": round(100 * float((r >= 0.50).mean()), 2),
            "pct_ge_0_75": round(100 * float((r >= 0.75).mean()), 2),
            "pct_ge_1_00": round(100 * float((r >= 1.00).mean()), 2),
            "median_net_return_at_confirm_atr": _med(conf["net_return_at_confirm_atr"]),
        })
        if base_return is not None:
            out["return_delta_vs_top10"] = round(
                (out["median_return_at_confirm_atr"] or 0) - base_return, 4)
    # Descriptive efficiency. Never a single composite selection metric.
    if d_p is not None and abs(med_sac) > 1e-9:
        out["lift_per_atr_sacrificed"] = round(d_p / med_sac, 4)
    if d_p is not None and med_wait > 0:
        out["lift_per_100s_waited"] = round(d_p / (med_wait / 100.0), 4)
    return out


def main() -> None:
    stream = pl.read_parquet(STREAM)
    stream = with_reexpansion(with_reexpansion(stream, 0.05), 0.03)
    stream = stream.with_columns(
        side=pl.when(pl.col("direction") > 0).then(pl.lit("LONG")).otherwise(pl.lit("SHORT")))
    n_arms = stream["regime_id"].n_unique()
    print(f"armed regimes: {n_arms:,}", flush=True)

    all_entries, all_trades = [], []
    for name, cond in ALL_RULES.items():
        e = first_firings(stream, name, cond)
        t = evaluate(e)
        all_entries.append(e)
        all_trades.append(t)
        print(f"  {name:30s} entries={e.height:>5,} trades={t.height:>5,}", flush=True)

    entries = pl.concat(all_entries, how="diagonal_relaxed")
    trades = pl.concat(all_trades, how="diagonal_relaxed")
    entries.write_parquet(OUT / "candidate_entries.parquet")
    trades.write_parquet(OUT / "candidate_trade_metrics.parquet")

    b = trades.filter(pl.col("rule") == BASE)
    base_rate = float(b["confirmed"].mean())
    base_ret = _med(b.filter(pl.col("confirmed"))["return_at_confirm_atr"])

    rows = []
    for name in ALL_RULES:
        t = trades.filter(pl.col("rule") == name)
        s = summarise(t, n_arms, base_rate, base_ret)
        rows.append({"rule": name,
                     "family": "BASELINE" if name in BASELINES else "CANDIDATE", **s})
    table = pl.DataFrame(rows, infer_schema_length=None)
    table.write_parquet(OUT / "confirmation_move_frontier.parquet")
    table.write_csv(OUT / "confirmation_move_frontier.csv")

    # --- Pareto frontier on (P(confirm|entered), median return at confirm)
    pts = table.filter(pl.col("n") > 0).select(
        "rule", "family", "n", "p_confirm_given_entered",
        "median_return_at_confirm_atr", "confirmed_per_100_arms").to_dicts()
    # Two frontiers. The conditional one is what the brief defines; on it almost
    # everything survives, because confirmation and remaining move trade off
    # nearly one-for-one, so few rules are beaten on BOTH axes. The throughput
    # frontier is the one that bites: it replaces remaining move with confirmed
    # trades per 100 arms, and a rule that enters selectively cannot hide there.
    def mark(points, second_axis: str, key: str):
        for p in points:
            p[f"dominated_by_{key}"] = [
                q["rule"] for q in points
                if q["rule"] != p["rule"]
                and q["p_confirm_given_entered"] >= p["p_confirm_given_entered"]
                and (q[second_axis] or -9) >= (p[second_axis] or -9)
                and (q["p_confirm_given_entered"] > p["p_confirm_given_entered"]
                     or (q[second_axis] or -9) > (p[second_axis] or -9))
            ]
            p[f"non_dominated_{key}"] = len(p[f"dominated_by_{key}"]) == 0

    mark(pts, "median_return_at_confirm_atr", "conditional")
    mark(pts, "confirmed_per_100_arms", "throughput")
    (OUT / "frontier_points.json").write_text(json.dumps(pts, indent=2, default=str))

    # --- Phase 6 stability
    srows = []
    for name in ALL_RULES:
        t = trades.filter(pl.col("rule") == name)
        for key, sub in ([("pooled", t)]
                         + [(f"side:{s}", t.filter(pl.col("side") == s)) for s in ("LONG", "SHORT")]
                         + [(f"year:{y}", t.filter(pl.col("entry_year") == y)) for y in YEARS]):
            if sub.height == 0:
                srows.append({"rule": name, "slice": key, "n": 0})
                continue
            c = sub.filter(pl.col("confirmed"))
            srows.append({
                "rule": name, "slice": key, "n": sub.height,
                "p_confirm": round(float(sub["confirmed"].mean()), 4),
                "median_return_at_confirm_atr": _med(c["return_at_confirm_atr"]),
                "median_mae_to_confirm_atr": _med(c["mae_to_confirm_atr"]),
            })
    stab = pl.DataFrame(srows, infer_schema_length=None)
    stab.write_parquet(OUT / "year_direction_stability.parquet")
    stab.write_csv(OUT / "year_direction_stability.csv")

    print("\n=== PRIMARY TRADEOFF TABLE")
    print(f"{'rule':30s}{'n':>6s}{'%arm':>7s}{'pConf':>7s}{'lift':>8s}{'/100arm':>9s}"
          f"{'wait_s':>8s}{'sacATR':>8s}{'retConf':>9s}{'dRet':>8s}{'mfe':>7s}{'mae':>7s}{'%2ndLife':>9s}")
    for r in rows:
        if not r.get("n"):
            continue
        f = lambda k, d=0.0: r.get(k) if r.get(k) is not None else d  # noqa: E731
        print(f"{r['rule']:30s}{r['n']:>6,}{f('pct_arms_entered'):>7.1f}"
              f"{f('p_confirm_given_entered'):>7.3f}{f('lift_vs_top10'):>+8.3f}"
              f"{f('confirmed_per_100_arms'):>9.1f}{f('median_seconds_arm_to_entry'):>8.0f}"
              f"{f('median_price_move_arm_to_entry_atr'):>+8.3f}"
              f"{f('median_return_at_confirm_atr'):>9.3f}{f('return_delta_vs_top10'):>+8.3f}"
              f"{f('median_mfe_to_confirm_atr'):>7.3f}{f('median_mae_to_confirm_atr'):>7.3f}"
              f"{f('pct_entries_after_arm_1atr_adverse'):>9.1f}")
    print("\nnon-dominated (conditional  P(confirm) x return):",
          [p["rule"] for p in pts if p["non_dominated_conditional"]])
    print("non-dominated (throughput   P(confirm) x confirmed/100 arms):",
          [p["rule"] for p in pts if p["non_dominated_throughput"]])
    print("\nexpected ATR per 100 arms (confirmed/100 x median return at confirm):")
    for p in sorted(pts, key=lambda q: -(q["confirmed_per_100_arms"]
                                         * (q["median_return_at_confirm_atr"] or 0))):
        print(f"  {p['rule']:30s} {p['confirmed_per_100_arms']:>5.1f} x "
              f"{p['median_return_at_confirm_atr']:.3f} = "
              f"{p['confirmed_per_100_arms'] * p['median_return_at_confirm_atr']:>5.1f}")


if __name__ == "__main__":
    main()
