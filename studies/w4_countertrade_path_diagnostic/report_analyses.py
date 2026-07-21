"""Reproduce the ad hoc analyses cited in results/final_report.md.

Committed for reproducibility per the completion audit. Everything here is a
descriptive or hindsight-counterfactual computation over the committed
diagnostic parquets — no thresholds are optimized and no policy is simulated.

Sections:
1. Threshold-free separation (AUC) and quartile tables at t+60s / t+120s,
   including FORWARD PnL (gross final minus gross mark at the checkpoint).
2. Pooled W4-warning-exit counterfactual (warned flip-reaching trades only).
3. Breakeven-at-flip envelope (SPECULATIVE: exact-at-entry fills assumed).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import rankdata

OUT = Path(__file__).resolve().parent / "results"
COST_RT = 10.0


def auc(x: pd.Series, y: pd.Series) -> float:
    x = np.asarray(x, float)
    y = np.asarray(y, bool)
    n1, n0 = int(y.sum()), int((~y).sum())
    if n1 == 0 or n0 == 0:
        return np.nan
    r = rankdata(x)
    return (r[y].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)


def early_window_analyses(cps: pd.DataFrame) -> None:
    for label in ("t+60s", "t+120s"):
        sub = cps[cps["checkpoint"] == label].copy()
        sub["eventual_stop"] = sub["outcome_group"].str.startswith("stop")
        sub["fwd_usd"] = sub["net_pnl_usd_final"] + COST_RT - sub["pnl_usd"]
        print(f"=== {label}: separation among alive trades ===")
        for yr, g in sub.groupby("year"):
            print(
                f"{yr}: n_alive={len(g)}"
                f" AUC(stop|-pnl)={auc(-g['pnl_atr'], g['eventual_stop']):.3f}"
                f" AUC(stop|mae)={auc(g['mae_atr'], g['eventual_stop']):.3f}"
            )
            g = g.copy()
            g["q"] = pd.qcut(g["pnl_atr"], 4,
                             labels=["Q1_worst", "Q2", "Q3", "Q4_best"])
            t = g.groupby("q", observed=True).agg(
                n=("fwd_usd", "size"),
                mean_final_net=("net_pnl_usd_final", "mean"),
                mean_fwd_gross=("fwd_usd", "mean"),
                pct_stop=("eventual_stop", "mean"),
            ).round(2)
            print(t.to_string())
        print()


def warning_exit_counterfactual(pfd: pd.DataFrame) -> None:
    print("=== pooled W4-warning-exit counterfactual (warned trades only) ===")
    warned = pfd[pfd["warned_before_exit"]].copy()
    warned["net_at_warn"] = warned["pnl_at_warn_usd"] - COST_RT
    t = warned.groupby("year").agg(
        n=("net_pnl_usd", "size"),
        total_actual=("net_pnl_usd", "sum"),
        total_at_warning=("net_at_warn", "sum"),
    ).round(0)
    print(t.to_string())
    print()


def be_at_flip_envelope(pfd: pd.DataFrame) -> None:
    """SPECULATIVE envelope: revisiting trades exit exactly at entry (-cost);
    non-revisiting trades keep their realized net. Ignores gap-through fills,
    intra-second sequencing, and re-entry effects. Not a simulation."""
    print("=== BE-at-flip envelope (speculative, generous fills) ===")
    env = np.where(pfd["post_flip_revisit_entry"], -COST_RT, pfd["net_pnl_usd"])
    t = pfd.assign(envelope=env).groupby("year").agg(
        n=("net_pnl_usd", "size"),
        actual_flip_reaching=("net_pnl_usd", "sum"),
        envelope=("envelope", "sum"),
    ).round(0)
    t["delta"] = t["envelope"] - t["actual_flip_reaching"]
    print(t.to_string())
    print("(delta applies to flip-reaching trades only; stop_before unchanged)")


def main() -> None:
    cps = pd.read_parquet(OUT / "path_checkpoints.parquet")
    pfd = pd.read_parquet(OUT / "post_flip_exit_diagnostic.parquet")
    pd.set_option("display.width", 200)
    early_window_analyses(cps)
    warning_exit_counterfactual(pfd)
    be_at_flip_envelope(pfd)


if __name__ == "__main__":
    main()
