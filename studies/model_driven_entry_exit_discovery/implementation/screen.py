"""Stage 1 family screening.

Purpose is to find which entry and exit families contain signal, not to locate an
optimum. Entry screening holds the exit fixed at the accepted baseline; exit
screening holds the entry fixed. Cross-products are deferred to Stage 3.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import polars as pl

from .candidates import FAMILIES, load_scored
from .engine import (
    COST_POINTS,
    ExitPolicy,
    load_market,
    load_regimes,
    simulate,
)

ROOT = Path(__file__).resolve().parents[3]
RESULTS = ROOT / "studies/model_driven_entry_exit_discovery/results"

DISCOVERY_YEARS = (2021, 2022, 2023)
SELECTION_YEAR = (2024,)
HOLDOUT_YEAR = (2025,)

BASELINE_EXIT = ExitPolicy(stop_atr=1.00, name="baseline_stop1.0_opposing")
CT = ZoneInfo("America/Chicago")


def run_policy(market, regimes, entries: pl.DataFrame, policy: ExitPolicy) -> dict:
    trades = []
    for row in entries.iter_rows(named=True):
        trades.append(
            simulate(
                market, regimes,
                entry_ns=row["checkpoint_decision_ns"],
                direction=row["direction"],
                entry_price=row["checkpoint_reference_price"],
                atr=row["atr_at_checkpoint"],
                policy=policy,
            )
        )
    return summarize(trades, entries)


def _month_key(entry_ns: int) -> int:
    """Calendar month in America/Chicago, as year*12 + month."""
    local = datetime.fromtimestamp(entry_ns / 1e9, tz=timezone.utc).astimezone(CT)
    return local.year * 12 + local.month


def summarize(trades, entries: pl.DataFrame) -> dict:
    gross = np.array([t.gross_atr for t in trades], dtype=float)
    net = np.array([t.net_atr for t in trades], dtype=float)
    resolved = ~np.isnan(gross)
    n = int(resolved.sum())
    if n == 0:
        return {"trades": 0, "resolved": 0}

    g, w = gross[resolved], net[resolved]
    wins = w > 0
    years = np.array([t.year for t in trades])[resolved]
    dirs = np.array([t.direction for t in trades])[resolved]
    mfe = np.array([t.mfe_atr for t in trades])[resolved]
    mae = np.array([t.mae_atr for t in trades])[resolved]

    equity = np.cumsum(w)
    peak = np.maximum.accumulate(equity)
    drawdown = float((peak - equity).max()) if equity.size else 0.0

    top1pct = max(1, int(0.01 * w.size))
    largest = np.sort(w)[-top1pct:].sum()

    # SPEC 9 requires concentration by calendar month, not only by trade. A
    # policy whose expectancy comes from one month is not an edge.
    months = np.array([_month_key(t.entry_ns) for t in trades])[resolved]
    month_totals = {int(m): float(w[months == m].sum()) for m in set(months.tolist())}
    best_month = max(month_totals.values()) if month_totals else 0.0

    return {
        "trades": int(len(trades)),
        "resolved": n,
        "censored": int((~resolved).sum()),
        "ambiguous": int(sum(t.ambiguous for t in trades)),
        "gross_atr": float(g.mean()),
        "net_atr": float(w.mean()),
        "median_atr": float(np.median(w)),
        "win_rate": float(wins.mean()),
        "avg_win": float(w[wins].mean()) if wins.any() else 0.0,
        "avg_loss": float(w[~wins].mean()) if (~wins).any() else 0.0,
        "mfe_mean": float(mfe.mean()),
        "mae_mean": float(mae.mean()),
        "capture": float(np.median(w / np.maximum(mfe, 1e-9))),
        "max_drawdown_atr": drawdown,
        "total_atr": float(w.sum()),
        "pnl_share_largest_1pct": float(largest / w.sum()) if w.sum() != 0 else float("nan"),
        "pnl_share_best_month": float(best_month / w.sum()) if w.sum() != 0 else float("nan"),
        "months_covered": len(month_totals),
        "by_year": {
            int(y): float(w[years == y].mean()) for y in sorted(set(years.tolist()))
        },
        "by_direction": {
            ("LONG" if d == 1 else "SHORT"): float(w[dirs == d].mean())
            for d in sorted(set(dirs.tolist()))
        },
        "outcomes": {
            k: int(v)
            for k, v in zip(*np.unique([t.outcome for t in trades], return_counts=True))
        },
    }


def attach_meta(entries: pl.DataFrame, trades) -> None:
    for trade, row in zip(trades, entries.iter_rows(named=True)):
        trade.year = row["entry_year"]
        trade.regime_id = row["regime_id"]


def screen_entries(market, regimes, scored, years, labels, families) -> list[dict]:
    out = []
    for family in families:
        for label in labels:
            entries = FAMILIES[family](scored, label).filter(
                pl.col("entry_year").is_in(list(years))
            )
            if entries.height < 100:
                continue
            trades = [
                simulate(
                    market, regimes, r["checkpoint_decision_ns"], r["direction"],
                    r["checkpoint_reference_price"], r["atr_at_checkpoint"],
                    BASELINE_EXIT,
                )
                for r in entries.iter_rows(named=True)
            ]
            attach_meta(entries, trades)
            row = summarize(trades, entries)
            row["family"], row["threshold"] = family, label
            out.append(row)
            print(
                f"  {family:16s} {label:8s} n={row['resolved']:>6,} "
                f"net={row['net_atr']:+.4f} gross={row['gross_atr']:+.4f} "
                f"win={row['win_rate']:.3f} mfe={row['mfe_mean']:.2f}",
                flush=True,
            )
    return out


EXIT_FAMILIES = {
    "opposing_flip_stop1.0": ExitPolicy(stop_atr=1.0),
    "opposing_flip_stop0.75": ExitPolicy(stop_atr=0.75),
    "opposing_flip_stop1.5": ExitPolicy(stop_atr=1.5),
    "no_stop": ExitPolicy(stop_atr=None),
    "target1.0": ExitPolicy(stop_atr=1.0, target_atr=1.0),
    "target1.5": ExitPolicy(stop_atr=1.0, target_atr=1.5),
    "target2.0": ExitPolicy(stop_atr=1.0, target_atr=2.0),
    "target3.0": ExitPolicy(stop_atr=1.0, target_atr=3.0),
    "giveback0.33": ExitPolicy(stop_atr=1.0, giveback_frac=0.33, mfe_floor_atr=0.5),
    "giveback0.50": ExitPolicy(stop_atr=1.0, giveback_frac=0.50, mfe_floor_atr=0.5),
    "giveback0.33_floor1.0": ExitPolicy(stop_atr=1.0, giveback_frac=0.33, mfe_floor_atr=1.0),
    "trail0.75": ExitPolicy(stop_atr=1.0, trail_atr=0.75, mfe_floor_atr=0.5),
    "trail1.0": ExitPolicy(stop_atr=1.0, trail_atr=1.0, mfe_floor_atr=0.5),
    "breakeven1.0": ExitPolicy(stop_atr=1.0, breakeven_at_atr=1.0),
    "breakeven0.5": ExitPolicy(stop_atr=1.0, breakeven_at_atr=0.5),
    "direction_flip": ExitPolicy(stop_atr=1.0, hold_to_opposing_flip=False),
    "time900": ExitPolicy(stop_atr=1.0, time_stop_s=900),
    "time1800": ExitPolicy(stop_atr=1.0, time_stop_s=1800),
}


def screen_exits(market, regimes, scored, years, entry_family, label) -> list[dict]:
    entries = FAMILIES[entry_family](scored, label).filter(
        pl.col("entry_year").is_in(list(years))
    )
    out = []
    for name, policy in EXIT_FAMILIES.items():
        trades = [
            simulate(
                market, regimes, r["checkpoint_decision_ns"], r["direction"],
                r["checkpoint_reference_price"], r["atr_at_checkpoint"], policy,
            )
            for r in entries.iter_rows(named=True)
        ]
        attach_meta(entries, trades)
        row = summarize(trades, entries)
        row["exit"], row["entry_family"], row["threshold"] = name, entry_family, label
        out.append(row)
        print(
            f"  {name:22s} n={row['resolved']:>6,} net={row['net_atr']:+.4f} "
            f"gross={row['gross_atr']:+.4f} win={row['win_rate']:.3f} "
            f"cap={row['capture']:+.2f} dd={row['max_drawdown_atr']:.1f}",
            flush=True,
        )
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=["entries", "exits"], required=True)
    parser.add_argument("--entry-family", default="first_qualifying")
    parser.add_argument("--threshold", default="top_2_5")
    args = parser.parse_args()

    years = DISCOVERY_YEARS
    print(f"loading market for {years} ...", flush=True)
    market = load_market(years=years)
    regimes = load_regimes()
    scored = load_scored(years=years)
    print(f"  {market.n:,} RTH bars, {scored.height:,} in-domain checkpoints\n", flush=True)
    print(f"cost: {COST_POINTS} pts round-turn, ATR-normalized per trade\n", flush=True)

    RESULTS.mkdir(parents=True, exist_ok=True)
    if args.stage == "entries":
        print("STAGE 1 - ENTRY FAMILY SCREEN (exit fixed: 1.0 ATR stop + opposing flip)")
        rows = screen_entries(
            market, regimes, scored, years,
            labels=["top_20", "top_10", "top_5", "top_2_5", "top_1", "top_0_5"],
            families=list(FAMILIES),
        )
        out = RESULTS / "stage1_entries.json"
    else:
        print(f"STAGE 1 - EXIT FAMILY SCREEN (entry fixed: {args.entry_family} {args.threshold})")
        rows = screen_exits(market, regimes, scored, years, args.entry_family, args.threshold)
        out = RESULTS / "stage1_exits.json"

    out.write_text(json.dumps(rows, indent=2, default=str))
    print(f"\nwrote {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
