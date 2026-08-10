"""Gate 2, decisive: the ATR ledger of acting on the flag.

The trade-off curve shows the signal discriminates. That is not the question.
The question the brief poses is economic:

    ATR of loss/giveback avoided on the failures we save
        versus
    remaining MFE destroyed in the winners we eject

This module computes the true counterfactual rather than a proxy. For every
flagged trade, acting on the flag replaces the realized outcome with the open PnL
at the flag, so the delta is

    open_pnl_at_flag  -  final_realized_pnl        (confirmation-anchored ATR)

summed separately over failures (where it should be positive) and winners (where
it will be negative). Both legs are charged the same round turn, so cost cancels
in the delta and is not double-counted.

Confirmation-anchored terminal PnL is reconstructed from the predecessor's
arm-anchored gross:

    exit_price = arm_price + full_gross_atr * arm_atr * direction
    final_conf = (exit_price - confirm_price) * direction / atr_at_confirmation

The predecessor applies a 0.125-point flat band before normalising, so a
reconstructed |gross| of exactly 0 is ambiguous between "flat" and "0.125 points
either way". That affects at most a fraction of a tick per trade and is recorded
in the artifact rather than silently absorbed.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "studies/post_confirmation_score_deterioration/results"
PANEL = OUT / "post_confirm_paths.parquet"

FAIL = ("CONFIRMED_THEN_STOPPED", "FINAL_FLIP_EXIT_LOSER")
WINNER = "FINAL_FLIP_EXIT_WINNER"
HORIZONS = (60, 120, 180, 300, 600)
QUANTILES = (0.50, 0.70, 0.85, 0.90, 0.95)


PRIOR = ROOT / "studies/armed_fade_score_path_progression/results/armed_regime_score_paths.parquet"


def attach_terminal_gross(panel: pl.DataFrame) -> pl.DataFrame:
    """`full_gross_atr` is not in the panel; join it from the predecessor table.

    Cheaper than rebuilding the 658k-row panel for one column, and the join key
    (`arm_regime_id`) is the predecessor's primary key, so it is exact.
    """
    if "full_gross_atr" in panel.columns:
        return panel
    prior = pl.read_parquet(PRIOR).select(
        arm_regime_id="regime_id", full_gross_atr="full_gross_atr"
    )
    return panel.join(prior, on="arm_regime_id", how="left")


def snapshot(panel: pl.DataFrame, horizon: int) -> pl.DataFrame:
    alive = panel.filter(pl.col("hold_s") > horizon)
    upto = alive.filter(pl.col("elapsed_s") <= horizon)
    if upto.height == 0:
        return upto
    snap = (
        upto.sort("checkpoint_decision_ns")
        .group_by("regime_id")
        .agg(
            terminal_label=pl.col("terminal_label").first(),
            is_failure=pl.col("is_failure").first(),
            side=pl.col("side").first(),
            entry_year=pl.col("entry_year").first(),
            full_mfe_atr=pl.col("full_mfe_atr").first(),
            full_gross_atr=pl.col("full_gross_atr").first(),
            arm_price=pl.col("arm_price").first(),
            arm_atr=pl.col("arm_atr").first(),
            confirm_price=pl.col("confirm_price").first(),
            atr_conf=pl.col("atr_at_confirmation").first(),
            direction=pl.col("direction").first(),
            score_b=pl.col("score_b").last(),
            open_pnl_atr=pl.col("open_pnl_atr_conf").last(),
        )
        .filter(pl.col("terminal_label").is_in(list(FAIL) + [WINNER]))
    )
    return snap.with_columns(
        exit_price=(pl.col("arm_price")
                    + pl.col("full_gross_atr") * pl.col("arm_atr") * pl.col("direction"))
    ).with_columns(
        final_pnl_atr=((pl.col("exit_price") - pl.col("confirm_price"))
                       * pl.col("direction") / pl.col("atr_conf"))
    )


def ledger(snap: pl.DataFrame, horizon: int) -> dict:
    vals = snap["score_b"].to_numpy()
    n_fail = int(snap["is_failure"].sum())
    winners_all = snap.filter(pl.col("terminal_label") == WINNER)

    points = []
    for q in QUANTILES:
        cutoff = float(np.quantile(vals, q))
        flagged = snap.filter(pl.col("score_b") >= cutoff).with_columns(
            delta_atr=(pl.col("open_pnl_atr") - pl.col("final_pnl_atr"))
        )
        f = flagged.filter(pl.col("is_failure"))
        w = flagged.filter(pl.col("terminal_label") == WINNER)
        saved = float(f["delta_atr"].sum()) if f.height else 0.0
        destroyed = float(w["delta_atr"].sum()) if w.height else 0.0
        big = w.filter(pl.col("full_mfe_atr") >= 2.5)
        points.append({
            "quantile": q,
            "score_cutoff": round(cutoff, 4),
            "n_flagged": flagged.height,
            "failures_flagged": f.height,
            "winners_flagged": w.height,
            "atr_saved_on_failures": round(saved, 2),
            "atr_lost_on_winners": round(destroyed, 2),
            "net_atr": round(saved + destroyed, 2),
            "net_atr_per_flagged_trade": (
                round((saved + destroyed) / flagged.height, 4) if flagged.height else None
            ),
            "mean_atr_saved_per_failure": round(saved / f.height, 4) if f.height else None,
            "mean_atr_lost_per_winner": round(destroyed / w.height, 4) if w.height else None,
            "winners_ge_2_5atr_flagged": big.height,
            "atr_lost_on_ge_2_5atr_winners": (
                round(float(big["delta_atr"].sum()), 2) if big.height else 0.0
            ),
        })

    return {
        "horizon_s": horizon,
        "n_alive": snap.height,
        "n_failures_alive": n_fail,
        "n_winners_alive": winners_all.height,
        "operating_points": points,
    }


def main() -> None:
    panel = attach_terminal_gross(pl.read_parquet(PANEL))
    report = {
        "method": (
            "Counterfactual delta per flagged trade = open PnL at the flag minus "
            "the realized confirmation-anchored terminal PnL. Positive on a "
            "failure means the flag saved ATR; negative on a winner means it "
            "destroyed ATR. Both legs pay the same round turn, so cost cancels."
        ),
        "caveat": (
            "Terminal price reconstructed from the predecessor's arm-anchored "
            "gross, which applies a 0.125-point flat band before normalising. "
            "Sub-tick imprecision only; it cannot move a result of this magnitude."
        ),
        "horizons": [],
    }
    for h in HORIZONS:
        snap = snapshot(panel, h)
        if snap.height == 0:
            continue
        led = ledger(snap, h)
        report["horizons"].append(led)
        print(f"\n=== t={h}s  alive={led['n_alive']:,} "
              f"(fail {led['n_failures_alive']:,} / win {led['n_winners_alive']:,})")
        print(f"    {'q':>5} {'flag':>6} {'fail':>6} {'win':>6} "
              f"{'ATRsaved':>10} {'ATRlost':>10} {'NET':>10} {'net/trade':>10}")
        for p in led["operating_points"]:
            print(f"    {p['quantile']:>5} {p['n_flagged']:>6} "
                  f"{p['failures_flagged']:>6} {p['winners_flagged']:>6} "
                  f"{p['atr_saved_on_failures']:>10} {p['atr_lost_on_winners']:>10} "
                  f"{p['net_atr']:>10} {p['net_atr_per_flagged_trade']:>10}")

    (OUT / "gate2_ledger.json").write_text(json.dumps(report, indent=2, default=str))
    print("\nwrote gate2_ledger.json")


if __name__ == "__main__":
    main()
