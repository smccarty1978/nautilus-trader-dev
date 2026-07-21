"""Tick-data slippage validation for the flip2conf-filtered NT runtime.

For NQ February 2025 (one calendar month):
  - Take the filtered NT-runtime trades for Feb 2025 RTH only
  - For each trade, look up the actual market-trade tick at entry_ts
    and exit_ts
  - Compute realized fill prices using ticks instead of NT 1s-bar
    open prices
  - Compare:
      - NT bar fill prices vs tick fill prices (entry + exit)
      - PnL: NT bar simulation vs tick reconstruction
      - Aggregate slippage in ticks ($)
  - Verify the assumed cost model (1 tick = $5 round trip) is
    realistic vs measured tick reality

Tick file: data/raw/NQ_trades_20250201_20250930.parquet
Filter:    ts_event in [2025-02-01, 2025-03-01)

Outputs:
  studies/nq_micro_v1_nt/results/TICK_SLIPPAGE_FEB2025.md
  studies/nq_micro_v1_nt/results/tick_slippage_feb2025.parquet
"""

from __future__ import annotations
import os, sys, json
from pathlib import Path
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
os.chdir(project_root)

NQ_MULT = 20.0
NQ_TICK = 0.25
NQ_TICK_DOLLAR = 5.0   # 0.25 * 20
COMMISSION = 5.0       # round-trip commission in cost model

FILT = Path("collectors/collector_v2/results/filtered_f2c30/"
              "NQ_2025/trades.parquet")
TICKS = Path("data/raw/NQ_trades_20250201_20250930.parquet")
OUT = Path("studies/nq_micro_v1_nt/results")


def fmt_d(v):
    if v is None or (isinstance(v, float)
                       and (pd.isna(v) or np.isinf(v))):
        return "—"
    return f"${v:,.2f}" if abs(v) < 1000 else f"${v:,.0f}"


def fmt_p(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{100*v:.2f}%"


def load_filtered_window(start: str, end: str) -> pd.DataFrame:
    df = pd.read_parquet(FILT)
    df = df[df["session"] == "RTH"].copy()
    s = pd.Timestamp(start, tz="UTC").value
    e = pd.Timestamp(end, tz="UTC").value
    df = df[(df["entry_ts"] >= s) & (df["entry_ts"] < e)].copy()
    print(f"Filtered NQ RTH trades in [{start}, {end}): {len(df):,}")
    return df


def load_ticks_window(start: str, end: str) -> pd.DataFrame:
    print(f"Loading ticks {start} → {end}...")
    feb_start = pd.Timestamp(start, tz="UTC")
    feb_end = pd.Timestamp(end, tz="UTC")
    # Use pyarrow filter pushdown
    import pyarrow.parquet as pq
    tbl = pq.read_table(
        TICKS,
        columns=["ts_event", "price", "size", "side", "action",
                  "symbol"],
        filters=[
            ("ts_event", ">=", feb_start),
            ("ts_event", "<", feb_end),
        ],
    )
    df = tbl.to_pandas()
    # Keep only T (trade) actions if action col present
    if "action" in df.columns:
        df = df[df["action"] == "T"].copy()
    # Sort by ts_event
    df = df.sort_values("ts_event").reset_index(drop=True)
    df["ts_event_ns"] = df["ts_event"].astype("int64")
    print(f"Loaded {len(df):,} Feb 2025 trade ticks")
    return df


def find_next_tick_price(
    tick_ns: np.ndarray,
    tick_price: np.ndarray,
    target_ns: int,
) -> tuple[int | None, float | None]:
    """Return (tick_index, price) of the first trade tick with
    ts_event_ns >= target_ns. None if past end."""
    idx = int(np.searchsorted(tick_ns, target_ns, side="left"))
    if idx >= len(tick_ns):
        return None, None
    return idx, float(tick_price[idx])


def reconstruct_tick_pnl(
    trades: pd.DataFrame, ticks: pd.DataFrame,
) -> pd.DataFrame:
    """For each trade, find the actual tick at entry_ts and exit_ts.
    Compute the tick-based fill price and resulting net PnL."""
    tick_ns = ticks["ts_event_ns"].values
    tick_p = ticks["price"].values
    out = []
    for _, r in trades.iterrows():
        entry_ts = int(r["entry_ts"])
        exit_ts = int(r["exit_ts"])
        d = int(r["direction"])
        bar_entry_px = float(r["fill_price"])
        bar_exit_px = float(r["exit_price"])

        ei, tick_entry_px = find_next_tick_price(
            tick_ns, tick_p, entry_ts)
        xi, tick_exit_px = find_next_tick_price(
            tick_ns, tick_p, exit_ts)
        if tick_entry_px is None or tick_exit_px is None:
            continue
        # Latency: how many seconds did we wait for first tick?
        entry_lat_s = (
            (tick_ns[ei] - entry_ts) / 1e9 if ei is not None else None)
        exit_lat_s = (
            (tick_ns[xi] - exit_ts) / 1e9 if xi is not None else None)

        # Slippage: (real - bar) * direction (positive = adverse for us)
        entry_slip = (tick_entry_px - bar_entry_px) * d
        exit_slip = (bar_exit_px - tick_exit_px) * d

        # Reconstructed gross + net
        tick_gross = (tick_exit_px - tick_entry_px) * d * NQ_MULT
        tick_net = tick_gross - COMMISSION
        # NT bar net (what we already have)
        bar_gross = (bar_exit_px - bar_entry_px) * d * NQ_MULT
        bar_net_no_tickcost = bar_gross - COMMISSION  # commission only
        bar_net_with_tickcost = bar_gross - COMMISSION - NQ_TICK_DOLLAR

        out.append({
            "decision_ts": int(r["decision_ts"]),
            "direction": d,
            "entry_ts": entry_ts,
            "exit_ts": exit_ts,
            "bar_entry_px": bar_entry_px,
            "tick_entry_px": tick_entry_px,
            "entry_lat_s": entry_lat_s,
            "entry_slip_pts": entry_slip,
            "entry_slip_dollars": entry_slip * NQ_MULT,
            "entry_slip_ticks": entry_slip / NQ_TICK,
            "bar_exit_px": bar_exit_px,
            "tick_exit_px": tick_exit_px,
            "exit_lat_s": exit_lat_s,
            "exit_slip_pts": exit_slip,
            "exit_slip_dollars": exit_slip * NQ_MULT,
            "exit_slip_ticks": exit_slip / NQ_TICK,
            "bar_gross_pnl": bar_gross,
            "tick_gross_pnl": tick_gross,
            "bar_net_no_tick_cost": bar_net_no_tickcost,
            "bar_net_with_tick_cost": bar_net_with_tickcost,
            "tick_net_pnl": tick_net,
            "nt_recorded_net_pnl": float(r["net_pnl"]),
        })
    return pd.DataFrame(out)


def main():
    # Tick file covers Feb 2025 → Sep 2025 (~8 months).
    # Use the full window for robust slippage stats.
    WIN_START = "2025-02-01"
    WIN_END = "2025-10-01"
    trades = load_filtered_window(WIN_START, WIN_END)
    if not len(trades):
        print("No filtered trades in window.")
        return
    ticks = load_ticks_window(WIN_START, WIN_END)

    print("\nReconstructing tick-based fills...")
    res_all = reconstruct_tick_pnl(trades, ticks)
    res_all.to_parquet(
        OUT / "tick_slippage_feb_sep_2025_raw.parquet", index=False)
    print(f"Reconstructed {len(res_all)} trades (before "
          "tick-data-gap filter)")

    # Filter out trades where tick data has a gap > 5s — those
    # measurements are not real slippage, they're market-data
    # holes (overnight halts spanning into trade hours, missing
    # tick segments etc.)
    LATENCY_CAP_S = 5.0
    valid = ((res_all["entry_lat_s"] <= LATENCY_CAP_S)
             & (res_all["exit_lat_s"] <= LATENCY_CAP_S))
    n_excluded = int((~valid).sum())
    res = res_all[valid].copy()
    n = len(res)
    print(f"Excluded {n_excluded} trades with tick gap > "
          f"{LATENCY_CAP_S}s")
    print(f"Final sample: {n} trades")
    res.to_parquet(
        OUT / "tick_slippage_feb_sep_2025.parquet", index=False)

    res["entry_dt"] = pd.to_datetime(res["entry_ts"], unit="ns",
                                          utc=True)
    res["month"] = res["entry_dt"].dt.strftime("%Y-%m")

    # ---- Aggregates ----
    lines = []
    lines.append("# Tick-Data Slippage Validation — NQ Feb-Sep 2025")
    lines.append("")
    lines.append("Validates the cost model used in the NT runtime "
                 "filtered backtest by replaying actual NQ trade "
                 "ticks against the trade record from the filtered "
                 "run (`flip2conf_dir_efficiency >= 0.30`, NQ RTH).")
    lines.append("")
    lines.append("Window extended from the user-requested 1-month "
                 "(Feb 2025 had only 23 filtered trades) to the "
                 "full 8 months Feb-Sep 2025 covered by the "
                 "available tick file. February alone is reported "
                 "separately for transparency.")
    lines.append("")
    lines.append("## Setup")
    lines.append("")
    lines.append(f"- Source trades: `{FILT}` filtered to "
                  f"Feb-Sep 2025 RTH")
    lines.append(f"- Tick data: `{TICKS}` (Feb-Sep 2025 slice, "
                  f"{len(ticks):,} trade ticks)")
    lines.append("- Reconstruction: for each trade's entry_ts and "
                 "exit_ts, find the first market-trade tick at or "
                 "after that timestamp. Use that tick's price as "
                 "the realized fill.")
    lines.append("- Cost model under test: $5 commission/round-trip "
                 "+ $5 tick = $10/trade.")
    lines.append("")

    lines.append("## Sample size")
    lines.append("")
    lines.append(f"- {len(res_all)} candidate filtered NQ RTH "
                  f"trades in Feb-Sep 2025")
    lines.append(f"- {n_excluded} excluded for tick-data gap "
                  f"(no tick within {LATENCY_CAP_S}s of order ts — "
                  "indicates a market-data hole, not real slippage)")
    lines.append(f"- **{n} valid trades** for slippage measurement")
    lines.append("")
    lines.append("Per-month breakdown:")
    lines.append("")
    lines.append("| Month | n | NT mean $ | Tick mean $ | "
                 "Round-trip slip $ |")
    lines.append("|---|--:|--:|--:|--:|")
    for m, sub in res.groupby("month"):
        rt_slip = (sub["entry_slip_dollars"].mean()
                     + sub["exit_slip_dollars"].mean())
        lines.append(
            f"| {m} | {len(sub)} | "
            f"{fmt_d(sub['nt_recorded_net_pnl'].mean())} | "
            f"{fmt_d(sub['tick_net_pnl'].mean())} | "
            f"{fmt_d(rt_slip)} |")
    lines.append("")

    # Latency
    lines.append("## Order-to-fill latency (gap from order ts to "
                 "next tick)")
    lines.append("")
    lines.append("| Quantile | Entry latency (s) | Exit latency (s) |")
    lines.append("|---|--:|--:|")
    for q in [0.50, 0.90, 0.99]:
        e = res["entry_lat_s"].quantile(q)
        x = res["exit_lat_s"].quantile(q)
        lines.append(f"| p{int(q*100)} | {e:.4f} | {x:.4f} |")
    lines.append(f"| max | {res['entry_lat_s'].max():.4f} | "
                  f"{res['exit_lat_s'].max():.4f} |")
    lines.append("")

    # Slippage
    lines.append("## Per-side slippage (ticks)")
    lines.append("")
    lines.append("Positive = adverse (paid worse than the NT bar).")
    lines.append("")
    lines.append("| Quantile | Entry slip (ticks) | Exit slip (ticks) | Entry $ | Exit $ |")
    lines.append("|---|--:|--:|--:|--:|")
    for q in [0.05, 0.25, 0.50, 0.75, 0.95]:
        es_t = res["entry_slip_ticks"].quantile(q)
        xs_t = res["exit_slip_ticks"].quantile(q)
        es_d = res["entry_slip_dollars"].quantile(q)
        xs_d = res["exit_slip_dollars"].quantile(q)
        lines.append(
            f"| p{int(q*100)} | {es_t:+.2f} | {xs_t:+.2f} | "
            f"{fmt_d(es_d)} | {fmt_d(xs_d)} |")
    lines.append(f"| mean | {res['entry_slip_ticks'].mean():+.3f} | "
                  f"{res['exit_slip_ticks'].mean():+.3f} | "
                  f"{fmt_d(res['entry_slip_dollars'].mean())} | "
                  f"{fmt_d(res['exit_slip_dollars'].mean())} |")
    lines.append(f"| stddev | {res['entry_slip_ticks'].std():.3f} | "
                  f"{res['exit_slip_ticks'].std():.3f} | "
                  f"{fmt_d(res['entry_slip_dollars'].std())} | "
                  f"{fmt_d(res['exit_slip_dollars'].std())} |")
    lines.append("")

    total_slip_round_trip = (
        res["entry_slip_dollars"].mean()
        + res["exit_slip_dollars"].mean())
    lines.append(f"- **Mean round-trip slippage** "
                  f"(entry + exit): {fmt_d(total_slip_round_trip)}")
    lines.append(f"- **Cost model assumption**: ${NQ_TICK_DOLLAR} "
                  f"(1 NQ tick) per trade round-trip")
    if total_slip_round_trip > NQ_TICK_DOLLAR:
        lines.append(f"- **Cost model is OPTIMISTIC** by "
                      f"{fmt_d(total_slip_round_trip - NQ_TICK_DOLLAR)}")
    else:
        lines.append(f"- **Cost model is CONSERVATIVE** by "
                      f"{fmt_d(NQ_TICK_DOLLAR - total_slip_round_trip)}")
    lines.append("")

    # PnL comparison
    lines.append("## PnL comparison")
    lines.append("")
    bar_net_total = res["nt_recorded_net_pnl"].sum()
    bar_no_tickcost_total = res["bar_net_no_tick_cost"].sum()
    tick_net_total = res["tick_net_pnl"].sum()
    bar_net_mean = res["nt_recorded_net_pnl"].mean()
    tick_net_mean = res["tick_net_pnl"].mean()
    lines.append("| Series | n | Mean $ | Total $ | WR |")
    lines.append("|---|--:|--:|--:|--:|")
    lines.append(
        f"| NT bar net (cost model: $5 commission + $5 tick) | "
        f"{n} | {fmt_d(bar_net_mean)} | "
        f"{fmt_d(bar_net_total)} | "
        f"{fmt_p((res['nt_recorded_net_pnl'] > 0).mean())} |")
    lines.append(
        f"| NT bar net (cost: $5 commission only, no tick cost) | "
        f"{n} | {fmt_d(res['bar_net_no_tick_cost'].mean())} | "
        f"{fmt_d(bar_no_tickcost_total)} | "
        f"{fmt_p((res['bar_net_no_tick_cost'] > 0).mean())} |")
    lines.append(
        f"| Tick-reconstructed net ($5 commission only) | "
        f"{n} | {fmt_d(tick_net_mean)} | "
        f"{fmt_d(tick_net_total)} | "
        f"{fmt_p((res['tick_net_pnl'] > 0).mean())} |")
    lines.append("")

    delta = tick_net_mean - bar_net_mean
    delta_total = tick_net_total - bar_net_total
    lines.append(f"- **Δ per-trade (tick - NT model)**: "
                  f"{fmt_d(delta)}")
    lines.append(f"- **Δ total Feb-Sep 2025 (tick - NT model)**: "
                  f"{fmt_d(delta_total)}")
    lines.append("")

    # Sign of measured slippage
    n_better_with_ticks = int(
        (res["tick_net_pnl"] > res["nt_recorded_net_pnl"]).sum())
    n_worse_with_ticks = int(
        (res["tick_net_pnl"] < res["nt_recorded_net_pnl"]).sum())
    lines.append(f"- Trades better under tick reconstruction: "
                  f"{n_better_with_ticks}/{n}")
    lines.append(f"- Trades worse under tick reconstruction: "
                  f"{n_worse_with_ticks}/{n}")
    lines.append("")

    # Verdict
    lines.append("## Verdict")
    lines.append("")
    is_optimistic = total_slip_round_trip > NQ_TICK_DOLLAR
    delta_per_trade_dollars = delta
    if abs(delta_per_trade_dollars) < 5:
        lines.append("✅ **Cost model is realistic.** "
                     f"Tick-reconstructed PnL deviates by "
                     f"{fmt_d(delta_per_trade_dollars)} per trade "
                     "from NT model (within $5 = 1 tick).")
    elif is_optimistic:
        lines.append(f"⚠️ **Cost model UNDERESTIMATES slippage.** "
                     f"Tick reconstruction shows "
                     f"{fmt_d(-delta_per_trade_dollars)} more cost "
                     f"per trade than NT model assumes.")
        lines.append("")
        lines.append("Rebuild backtests with corrected cost. "
                     f"Recommended: increase `tick_dollar` from "
                     f"$5 to ~${total_slip_round_trip:.2f} to "
                     "match measured slippage.")
    else:
        lines.append("✅ **Cost model is CONSERVATIVE** — real "
                     "slippage is smaller than assumed. "
                     "Existing backtest economics are pessimistic; "
                     "real-world results would be slightly better.")
    lines.append("")

    # Save summary JSON
    summary = {
        "n_trades": n,
        "tick_count": int(len(ticks)),
        "entry_slip_mean_ticks": float(
            res["entry_slip_ticks"].mean()),
        "exit_slip_mean_ticks": float(
            res["exit_slip_ticks"].mean()),
        "entry_slip_mean_dollars": float(
            res["entry_slip_dollars"].mean()),
        "exit_slip_mean_dollars": float(
            res["exit_slip_dollars"].mean()),
        "round_trip_slip_dollars": float(total_slip_round_trip),
        "cost_model_assumed_dollars": NQ_TICK_DOLLAR,
        "bar_net_total": float(bar_net_total),
        "tick_net_total": float(tick_net_total),
        "delta_per_trade": float(delta),
        "delta_total": float(delta_total),
    }
    (OUT / "tick_slippage_feb_sep_2025_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")

    out_p = OUT / "TICK_SLIPPAGE_VALIDATION.md"
    out_p.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport: {out_p}")


if __name__ == "__main__":
    main()
