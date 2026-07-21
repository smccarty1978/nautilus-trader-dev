"""Post-process NT backtest results: monthly stability + slippage.

Loads positions.parquet from the NT run and:

1. Classifies each exit as PT / SL / regime_exit (by comparing
   close-minus-entry to ±1 ATR from the schedule's atr_at_signal).
2. Applies $5 commission (the NT run used $0 — my config gap).
3. Adds 1-tick adverse slippage per configurable rule:
     - Entry (market): always -1 tick adverse
     - Exit via SL (stop_market): -1 tick adverse
     - Exit via regime_exit (market close): -1 tick adverse
     - Exit via PT (limit): no additional slippage (limit fills at level)
4. Emits monthly and stratified tables under three scenarios:
     A. As-reported (NT bar-execution, $0 commission)
     B. + Commission ($5/trade)
     C. + Slippage (1-tick adverse entry + 1-tick adverse SL/regime)
"""

from __future__ import annotations
import argparse
from pathlib import Path
import numpy as np
import pandas as pd

TICK_SIZE = 0.25
NQ_MULT = 20.0
COMMISSION = 5.0
SLIPPAGE_TICKS = 1


def classify_exit(row, tol_atr: float = 0.05) -> str:
    """Decide PT/SL/regime_exit from close-minus-entry and signal direction.

    row must have: avg_px_open, avg_px_close, direction, atr_at_signal
    """
    d = row["direction"]
    move = (row["avg_px_close"] - row["avg_px_open"]) * d
    atr = row["atr_at_signal"]
    if atr <= 0:
        return "unknown"
    atr_move = move / atr
    if atr_move >= 1.0 - tol_atr:
        return "pt"
    if atr_move <= -(1.0 - tol_atr):
        return "sl"
    return "regime_exit"


def build_trades(positions_path: Path, schedule_path: Path) -> pd.DataFrame:
    """Merge NT positions with schedule to get direction + atr."""
    pos = pd.read_parquet(positions_path)
    sched = pd.read_parquet(schedule_path)

    # Schedule key: entry_ts_ns → direction + atr
    sched = sched.sort_values("entry_ts_ns")
    # Convert ts_opened (NT timestamp pandas) to ns
    pos = pos.copy()
    pos["entry_ts_ns"] = pos["ts_opened"].astype("int64")
    pos["exit_ts_ns"] = pos["ts_closed"].astype("int64")

    # Merge: schedule's entry_ts_ns may not match position's ts_opened
    # exactly (NT bar fills slightly after). Use nearest-forward merge.
    sched_sel = sched[["entry_ts_ns", "direction", "atr_at_signal",
                        "regime_exit_ts_ns", "event_id",
                        "checkpoint_s", "score"]]
    pos = pd.merge_asof(
        pos.sort_values("entry_ts_ns"),
        sched_sel.sort_values("entry_ts_ns"),
        on="entry_ts_ns",
        direction="nearest",
        tolerance=60 * 1_000_000_000,  # ±60s tolerance
    )

    # Drop any rows where merge failed
    pos = pos.dropna(subset=["direction", "atr_at_signal"])
    pos["direction"] = pos["direction"].astype(int)
    pos["exit_reason"] = pos.apply(classify_exit, axis=1)

    # Per-trade PnL under three scenarios
    entry_px = pos["avg_px_open"].astype(float).values
    exit_px = pos["avg_px_close"].astype(float).values
    d = pos["direction"].values
    reasons = pos["exit_reason"].values

    # Scenario A: raw (what NT reported, $0 commission)
    pnl_a = (exit_px - entry_px) * d * NQ_MULT

    # Scenario B: + commission
    pnl_b = pnl_a - COMMISSION

    # Scenario C: + slippage
    # Entry: adverse by 1 tick → worsen entry by TICK_SIZE×d
    # Exit SL / regime_exit: adverse by 1 tick → worsen exit by TICK_SIZE×(-d)
    # Exit PT (limit): no slippage
    adj_entry = np.where(d == 1, TICK_SIZE, -TICK_SIZE)
    exit_is_slippage_prone = np.isin(reasons, ["sl", "regime_exit", "unknown"])
    adj_exit = np.where(d == 1, -TICK_SIZE, TICK_SIZE) * exit_is_slippage_prone
    slip_cost = (adj_entry - adj_exit) * d * NQ_MULT  # ticks × mult
    # Actually recompute: adverse entry means we pay TICK*d worse (+1 tick for long)
    # Adverse exit for SL/regime means we get TICK*(-d) worse at exit
    # Net PnL = (exit+adj_exit - (entry+adj_entry)) * d * mult
    slip_entry = entry_px + adj_entry  # worse entry
    slip_exit = np.where(exit_is_slippage_prone,
                          exit_px + np.where(d == 1, -TICK_SIZE,
                                              TICK_SIZE),
                          exit_px)
    pnl_c_raw = (slip_exit - slip_entry) * d * NQ_MULT
    pnl_c = pnl_c_raw - COMMISSION

    pos["pnl_raw"] = pnl_a
    pos["pnl_commission"] = pnl_b
    pos["pnl_full_slip"] = pnl_c

    # Month bucket
    pos["exit_dt_utc"] = pd.to_datetime(pos["exit_ts_ns"], unit="ns",
                                           utc=True)
    pos["month"] = pos["exit_dt_utc"].dt.to_period("M").astype(str)

    return pos


def metrics(s: pd.Series) -> dict:
    s = s.dropna()
    if len(s) == 0:
        return {"n": 0}
    wins = s[s > 0]
    losses = s[s < 0]
    return {
        "n": len(s),
        "mean": float(s.mean()),
        "median": float(s.median()),
        "sum": float(s.sum()),
        "win_rate": float((s > 0).mean()),
        "pf": (float(wins.sum() / abs(losses.sum()))
                if len(losses) and losses.sum() != 0
                else float("inf")),
    }


def _d(v) -> str:
    if v is None or pd.isna(v):
        return "—"
    if isinstance(v, float) and np.isinf(v):
        return "∞"
    return f"${v:,.2f}" if abs(v) < 1000 else f"${v:,.0f}"


def _p(v) -> str:
    if v is None or pd.isna(v):
        return "—"
    return f"{100*v:.1f}%"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--positions",
                     default="backtests/good_entry_v2_bracket/results/"
                              "nt_run_bev2/positions.parquet")
    ap.add_argument("--schedule",
                     default="backtests/good_entry_v2_bracket/results/"
                              "schedule_bev2_rth_top10.parquet")
    ap.add_argument("--out",
                     default="backtests/good_entry_v2_bracket/results/"
                              "nt_run_bev2/MONTHLY_SLIPPAGE_REPORT.md")
    args = ap.parse_args()

    trades = build_trades(Path(args.positions), Path(args.schedule))
    print(f"Trades merged: {len(trades):,}")
    print(f"Exit mix: {trades['exit_reason'].value_counts().to_dict()}")
    print()

    lines: list[str] = []
    lines.append("# Monthly & Slippage Sensitivity — Bracket-Aligned v2")
    lines.append("")
    lines.append(f"- N trades merged: {len(trades):,}")
    lines.append(f"- Exit mix: {trades['exit_reason'].value_counts().to_dict()}")
    lines.append(f"- Classification: `exit_reason` derived from "
                  "`(avg_px_close - avg_px_open) / atr_at_signal`")
    lines.append("")

    # --- Scenario totals ---
    lines.append("## Scenario totals")
    lines.append("")
    lines.append("| Scenario | n | Mean $ | Median $ | Win% | PF | Total $ |")
    lines.append("|---|--:|--:|--:|--:|--:|--:|")
    for label, col in [
        ("A — NT raw ($0 commission, no slippage)", "pnl_raw"),
        ("B — + $5 commission", "pnl_commission"),
        ("C — + 1-tick slippage (entry + SL/regime exit)", "pnl_full_slip"),
    ]:
        m = metrics(trades[col])
        lines.append(
            f"| {label} | {m['n']:,} | {_d(m['mean'])} | "
            f"{_d(m['median'])} | {_p(m['win_rate'])} | "
            f"{m['pf']:.2f} | {_d(m['sum'])} |")
    lines.append("")

    # --- Monthly breakdown (all 3 scenarios) ---
    lines.append("## Monthly PnL under each scenario")
    lines.append("")
    lines.append("| Month | n | A: raw $ | B: +comm | C: +slip | "
                  "C Mean $/tr | C Win% | C PF |")
    lines.append("|---|--:|--:|--:|--:|--:|--:|--:|")
    for month, sub in trades.groupby("month"):
        ma = metrics(sub["pnl_raw"])
        mb = metrics(sub["pnl_commission"])
        mc = metrics(sub["pnl_full_slip"])
        lines.append(
            f"| {month} | {ma['n']:,} | "
            f"{_d(ma['sum'])} | {_d(mb['sum'])} | {_d(mc['sum'])} | "
            f"{_d(mc['mean'])} | {_p(mc['win_rate'])} | "
            f"{mc['pf']:.2f} |")
    lines.append("")

    # --- By exit reason, scenario C (realistic) ---
    lines.append("## Scenario C breakdown by exit reason")
    lines.append("")
    lines.append("| Exit | n | Mean $ | Median $ | Total $ |")
    lines.append("|---|--:|--:|--:|--:|")
    for reason, sub in trades.groupby("exit_reason"):
        m = metrics(sub["pnl_full_slip"])
        lines.append(
            f"| {reason} | {m['n']:,} | {_d(m['mean'])} | "
            f"{_d(m['median'])} | {_d(m['sum'])} |")
    lines.append("")

    # --- By side, scenario C ---
    lines.append("## Scenario C by direction")
    lines.append("")
    lines.append("| Direction | n | Mean $ | Median $ | Win% | PF | Total $ |")
    lines.append("|---|--:|--:|--:|--:|--:|--:|")
    for d_, sub in trades.groupby("direction"):
        label = "Long" if d_ == 1 else "Short"
        m = metrics(sub["pnl_full_slip"])
        lines.append(
            f"| {label} | {m['n']:,} | {_d(m['mean'])} | "
            f"{_d(m['median'])} | {_p(m['win_rate'])} | "
            f"{m['pf']:.2f} | {_d(m['sum'])} |")
    lines.append("")

    # --- Sharpe comparison across scenarios ---
    lines.append("## Approximate Sharpe across scenarios")
    lines.append("")
    lines.append("| Scenario | Daily mean | Daily std | Sharpe (252d) |")
    lines.append("|---|--:|--:|--:|")
    for label, col in [
        ("A — raw", "pnl_raw"),
        ("B — +comm", "pnl_commission"),
        ("C — +slip", "pnl_full_slip"),
    ]:
        daily = (trades.assign(
                     day=trades["exit_dt_utc"].dt.date)
                 .groupby("day")[col].sum())
        mean_d = daily.mean()
        std_d = daily.std()
        sharpe = (mean_d / std_d * (252 ** 0.5)
                   if std_d > 0 else float("nan"))
        lines.append(f"| {label} | {_d(mean_d)} | {_d(std_d)} | "
                      f"{sharpe:.2f} |")
    lines.append("")

    # --- Stability summary ---
    lines.append("## Stability summary (scenario C)")
    lines.append("")
    monthly_c = (trades.groupby("month")["pnl_full_slip"].sum())
    n_pos = int((monthly_c > 0).sum())
    n_neg = int((monthly_c < 0).sum())
    lines.append(f"- Positive months: {n_pos} / {len(monthly_c)}")
    lines.append(f"- Negative months: {n_neg} / {len(monthly_c)}")
    lines.append(f"- Best month: {_d(monthly_c.max())} "
                  f"({monthly_c.idxmax()})")
    lines.append(f"- Worst month: {_d(monthly_c.min())} "
                  f"({monthly_c.idxmin()})")
    lines.append(f"- Std dev across months: {_d(monthly_c.std())}")
    lines.append("")

    Path(args.out).write_text("\n".join(lines), encoding="utf-8")
    print(f"Report: {args.out}")

    # Quick stdout print of scenario totals
    print("\n=== Scenario totals ===")
    for label, col in [("A raw", "pnl_raw"),
                        ("B +comm", "pnl_commission"),
                        ("C +slip", "pnl_full_slip")]:
        m = metrics(trades[col])
        print(f"  {label:<10s} total={_d(m['sum']):<12s} "
               f"mean={_d(m['mean']):<10s} "
               f"PF={m['pf']:.2f}  Win%={_p(m['win_rate'])}")


if __name__ == "__main__":
    main()
