"""Gate 2: the sensitivity / runner-damage trade-off at fixed landmarks.

`events.py` established a hard negative that shapes this module: **path-threshold
escalation events are useless here.** Over a trade carrying 41-179 dispatches the
stream-B score is near-certain to rise 0.03-0.10 off its running minimum at some
point, so every such event fires on ~100% of trades, touches 100% of winners, and
has precision exactly equal to the base failure rate (0.481). Nothing is learned
from "did the score ever escalate"; the answer is always yes.

The Gate 1 signal lives in the score **level at a fixed elapsed time**, which is
also the only form a runtime manager could act on. This module therefore sweeps
the operating point at each landmark and reports the whole trade-off curve.

Sweeping the cutoff is **characterisation, not optimisation** -- the brief asks
explicitly for the trade-off rather than a chosen threshold, and no cutoff is
selected or carried forward. Cutoffs are expressed as quantiles of the *alive
cross-section at that landmark*, which is distribution-free and avoids inventing
a second threshold contract (SPEC 1.3).
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
QUANTILES = (0.50, 0.60, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95)
YEARS = (2021, 2022, 2023, 2024, 2025)


def snapshot(panel: pl.DataFrame, horizon: int) -> pl.DataFrame:
    """Per-trade state as of `horizon`, among trades still open then."""
    alive = panel.filter(pl.col("hold_s") > horizon)
    upto = alive.filter(pl.col("elapsed_s") <= horizon)
    if upto.height == 0:
        return upto
    return (
        upto.sort("checkpoint_decision_ns")
        .group_by("regime_id")
        .agg(
            terminal_label=pl.col("terminal_label").first(),
            is_failure=pl.col("is_failure").first(),
            side=pl.col("side").first(),
            entry_year=pl.col("entry_year").first(),
            full_mfe_atr=pl.col("full_mfe_atr").first(),
            hold_s=pl.col("hold_s").first(),
            score_b=pl.col("score_b").last(),
            open_pnl_atr=pl.col("open_pnl_atr_conf").last(),
            mfe_atr=pl.col("run_mfe_atr").last(),
            giveback_atr=pl.col("giveback_atr").last(),
            n_obs=pl.len(),
        )
        .filter(pl.col("terminal_label").is_in(list(FAIL) + [WINNER]))
    )


def remaining_after(panel: pl.DataFrame, horizon: int) -> pl.DataFrame:
    """MFE still available strictly after the landmark, per trade."""
    return (
        panel.filter(pl.col("elapsed_s") > horizon)
        .group_by("regime_id")
        .agg(max_pnl_after=pl.col("open_pnl_atr_conf").max(),
             final_pnl_after=pl.col("open_pnl_atr_conf").last())
    )


def curve(snap: pl.DataFrame, horizon: int) -> dict:
    tot_fail = int(snap["is_failure"].sum())
    winners = snap.filter(pl.col("terminal_label") == WINNER)
    tot_win = winners.height
    big = {
        t: winners.filter(pl.col("full_mfe_atr") >= t).height for t in (2.0, 2.5, 3.0)
    }

    points = []
    vals = snap["score_b"].to_numpy()
    for q in QUANTILES:
        cutoff = float(np.quantile(vals, q))
        flagged = snap.filter(pl.col("score_b") >= cutoff)
        f_fail = flagged.filter(pl.col("is_failure"))
        f_win = flagged.filter(pl.col("terminal_label") == WINNER)
        pt = {
            "quantile": q,
            "score_cutoff": round(cutoff, 4),
            "n_flagged": flagged.height,
            "failures_caught": f_fail.height,
            "sensitivity": round(f_fail.height / tot_fail, 4) if tot_fail else None,
            "winner_touch_rate": round(f_win.height / tot_win, 4) if tot_win else None,
            "precision": round(f_fail.height / flagged.height, 4) if flagged.height else None,
            "median_open_pnl_atr_at_flag": (
                round(float(flagged["open_pnl_atr"].median()), 4) if flagged.height else None
            ),
            "median_open_pnl_atr_failures": (
                round(float(f_fail["open_pnl_atr"].median()), 4) if f_fail.height else None
            ),
            "median_open_pnl_atr_winners": (
                round(float(f_win["open_pnl_atr"].median()), 4) if f_win.height else None
            ),
            "median_remaining_mfe_winners_touched": (
                round(float(f_win["remaining_mfe_atr"].median()), 4)
                if f_win.height and "remaining_mfe_atr" in f_win.columns else None
            ),
        }
        for t in (2.0, 2.5, 3.0):
            tag = format(t, "g").replace(".", "_")
            hit = f_win.filter(pl.col("full_mfe_atr") >= t).height
            pt[f"touch_rate_ge_{tag}atr"] = round(hit / big[t], 4) if big[t] else None
        points.append(pt)

    return {
        "horizon_s": horizon,
        "n_alive": snap.height,
        "n_failures_alive": tot_fail,
        "n_winners_alive": tot_win,
        "base_failure_rate": round(tot_fail / snap.height, 4) if snap.height else None,
        "n_runners_ge_2atr": big[2.0],
        "n_runners_ge_2_5atr": big[2.5],
        "n_runners_ge_3atr": big[3.0],
        "median_open_pnl_atr_alive": round(float(snap["open_pnl_atr"].median()), 4),
        "median_open_pnl_failures": round(
            float(snap.filter(pl.col("is_failure"))["open_pnl_atr"].median()), 4
        ) if tot_fail else None,
        "median_open_pnl_winners": round(
            float(winners["open_pnl_atr"].median()), 4
        ) if tot_win else None,
        "operating_points": points,
    }


def main() -> None:
    panel = pl.read_parquet(PANEL)
    report = {
        "design": (
            "At each landmark, among trades still open, flag those whose stream-B "
            "score is at or above a quantile of the alive cross-section. The "
            "quantile sweep is a trade-off curve, not a tuned threshold: no "
            "operating point is selected or carried forward."
        ),
        "why_not_path_events": (
            "Path-threshold escalation events fire on ~100% of trades (precision "
            "== base rate 0.481, winner touch 1.00) because over 41-179 dispatches "
            "the score is near-certain to rise 0.03-0.10 off its running minimum "
            "at some point. See deterioration_event_table.json."
        ),
        "horizons": [],
    }
    for h in HORIZONS:
        snap = snapshot(panel, h)
        if snap.height == 0:
            continue
        rem = remaining_after(panel, h)
        snap = snap.join(rem, on="regime_id", how="left").with_columns(
            remaining_mfe_atr=(
                pl.col("max_pnl_after").fill_null(pl.col("open_pnl_atr"))
                - pl.col("open_pnl_atr")
            )
        )
        c = curve(snap, h)
        report["horizons"].append(c)
        print(f"\n=== t={h}s  alive={c['n_alive']:,} "
              f"(fail {c['n_failures_alive']:,} / win {c['n_winners_alive']:,}, "
              f"base {c['base_failure_rate']})  "
              f"runners>=2.5ATR={c['n_runners_ge_2_5atr']}")
        print(f"    median open PnL ATR: failures {c['median_open_pnl_failures']} "
              f"| winners {c['median_open_pnl_winners']}")
        print(f"    {'q':>5} {'cut':>7} {'sens':>7} {'touch':>7} {'prec':>7} "
              f"{'t>=2.5':>7} {'pnl@flag':>9} {'remMFE_w':>9}")
        for p in c["operating_points"]:
            print(f"    {p['quantile']:>5} {p['score_cutoff']:>7} "
                  f"{p['sensitivity']:>7} {p['winner_touch_rate']:>7} "
                  f"{p['precision']:>7} {p['touch_rate_ge_2_5atr']:>7} "
                  f"{p['median_open_pnl_atr_at_flag']:>9} "
                  f"{p['median_remaining_mfe_winners_touched']:>9}")

    (OUT / "landmark_tradeoff.json").write_text(json.dumps(report, indent=2, default=str))
    print("\nwrote landmark_tradeoff.json")


if __name__ == "__main__":
    main()
