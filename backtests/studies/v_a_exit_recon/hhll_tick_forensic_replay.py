"""Tick-by-tick forensic replay of the worst-slip HH/LL trade.

For the trade with the largest |slip| in the audit, prints:
  - Trade metadata (all fields)
  - Raw ticks from arm_ts - 10s through fill_ts + 10s
  - Calculation validations (tick size, $/tick, sign, rounding)
  - Sequence around the protect_px crossing
  - Distribution sanity for slips > 50 ticks

Inputs:
  studies/v_a_exit_recon/results/hhll_forensic_audit_full.parquet
  collectors/collector_v2/results/tick_nt/hhll_FebSep_audit_*/trades.parquet
  data/raw/NQ_trades_20250201_20250930.parquet
  data/raw/NQ_bbo_20250201_20250930.parquet (if available)

Output:
  studies/v_a_exit_recon/results/HHLL_TICK_FORENSIC_REPLAY.md
  studies/v_a_exit_recon/results/worst_slip_tick_window.parquet
"""

from __future__ import annotations
import os, sys
from pathlib import Path
import numpy as np
import pandas as pd
import pytz

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

CT = pytz.timezone("America/Chicago")
TICK_NT = Path("collectors/collector_v2/results/tick_nt")
OUT = Path("studies/v_a_exit_recon/results")
NQ_TICK_SIZE = 0.25
NQ_DOLLAR_PER_TICK = 5.00
NQ_MULT = 20.0


def fmt_d(v):
    if v is None or (isinstance(v, float)
                       and (pd.isna(v) or np.isinf(v))):
        return "—"
    return f"${v:,.2f}" if abs(v) < 1000 else f"${v:,.0f}"


def find_run_dir(prefix: str) -> Path | None:
    candidates = sorted(TICK_NT.glob(f"{prefix}*"))
    if not candidates: return None
    return candidates[-1]


def load_ticks_window(start_ts_ns: int, end_ts_ns: int,
                          paths: list[str]) -> pd.DataFrame:
    """Load all trade ticks in the [start, end] window."""
    import pyarrow.parquet as pq
    start = pd.Timestamp(start_ts_ns, tz="UTC")
    end = pd.Timestamp(end_ts_ns, tz="UTC")
    frames = []
    for p in paths:
        if not os.path.exists(p): continue
        tbl = pq.read_table(
            p,
            columns=["ts_event", "ts_recv", "price", "size",
                       "side", "action", "sequence"],
            filters=[
                ("ts_event", ">=", start),
                ("ts_event", "<=", end),
                ("action", "=", "T"),
            ],
        )
        df = tbl.to_pandas()
        if len(df): frames.append(df)
    if not frames: return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    df = df.sort_values("ts_event").reset_index(drop=True)
    return df


def load_bbo_window(start_ts_ns: int, end_ts_ns: int,
                       paths: list[str]) -> pd.DataFrame:
    import pyarrow.parquet as pq
    start = pd.Timestamp(start_ts_ns, tz="UTC")
    end = pd.Timestamp(end_ts_ns, tz="UTC")
    frames = []
    for p in paths:
        if not os.path.exists(p): continue
        try:
            tbl = pq.read_table(
                p,
                columns=["ts_event", "bid_px_00", "ask_px_00",
                          "bid_sz_00", "ask_sz_00"],
                filters=[
                    ("ts_event", ">=", start),
                    ("ts_event", "<=", end),
                ],
            )
        except Exception as e:
            print(f"  BBO load failed: {e}")
            continue
        df = tbl.to_pandas()
        if len(df): frames.append(df)
    if not frames: return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    df = df.sort_values("ts_event").reset_index(drop=True)
    return df


def replay_one_trade(trade_row: pd.Series,
                          audit_row: pd.Series, lines: list):
    """Print all metadata + raw ticks + sequence for one trade."""
    ts_ct = lambda ns: pd.Timestamp(int(ns),
                                            tz="UTC").tz_convert(CT)

    direction = int(trade_row["direction"])
    entry_ts = int(trade_row["entry_ts"])
    entry_px = float(trade_row["fill_price"])
    arm_ts = int(trade_row["hhll_arm_ts"])
    protect_px = float(trade_row["hhll_protect_px"])
    mfe_at_arm = float(
        trade_row.get("hhll_mfe_at_arm", float("nan")))
    exit_ts = int(trade_row["exit_ts"])
    exit_px = float(trade_row["exit_price"])
    exit_reason = str(trade_row.get("exit_reason", ""))

    first_cross_ts = (int(audit_row["first_cross_ts"])
                          if pd.notna(audit_row["first_cross_ts"])
                          else None)
    first_cross_px = (float(audit_row["first_cross_px"])
                          if pd.notna(audit_row["first_cross_px"])
                          else None)
    slip_ticks = float(audit_row["slip_a_vs_c_realistic_ticks"])
    slip_dollars = float(
        audit_row["slip_a_vs_c_realistic_dollars"])
    atr = float(trade_row.get("atr_at_signal", float("nan")))

    lines.append("## 1. Trade metadata")
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("|---|---|")
    lines.append(f"| trade_id | {int(trade_row['decision_event_id'])} |")
    lines.append(f"| direction | {direction:+d} (long if +1) |")
    lines.append(f"| entry_ts (UTC ns) | {entry_ts} |")
    lines.append(f"| entry_ts (CT) | {ts_ct(entry_ts)} |")
    lines.append(f"| entry_price | {entry_px:.4f} |")
    lines.append(f"| arm_ts (UTC ns) | {arm_ts} |")
    lines.append(f"| arm_ts (CT) | {ts_ct(arm_ts)} |")
    lines.append(f"| mfe_at_arm (pts) | {mfe_at_arm:.4f} |")
    lines.append(f"| protect_px | {protect_px:.4f} |")
    lines.append(f"| atr_at_signal (pts) | {atr:.4f} |")
    lines.append(f"| first_cross_ts (CT) | "
                  f"{ts_ct(first_cross_ts) if first_cross_ts else 'N/A'} |")
    fcp_str = (f"{first_cross_px:.4f}" if first_cross_px
                  else "N/A")
    lines.append(f"| first_cross_px | {fcp_str} |")
    lines.append(f"| exit_ts (UTC ns) | {exit_ts} |")
    lines.append(f"| exit_ts (CT) | {ts_ct(exit_ts)} |")
    lines.append(f"| exit_price (NT fill) | {exit_px:.4f} |")
    lines.append(f"| exit_reason | {exit_reason} |")
    lines.append(f"| reported slip_ticks (A vs C) | "
                  f"{slip_ticks:+.2f} |")
    lines.append(f"| reported slip_dollars | "
                  f"{slip_dollars:+,.2f} |")
    lines.append("")

    # ---- 2. Raw tick window ----
    if first_cross_ts is None:
        lines.append("(No cross detected — skipping tick replay)")
        return
    win_start_ns = arm_ts - 10 * 1_000_000_000
    win_end_ns = exit_ts + 10 * 1_000_000_000
    print(f"  Loading ticks from "
          f"{ts_ct(win_start_ns)} to {ts_ct(win_end_ns)}...")
    paths = [
        "data/raw/NQ_trades_jan2025.parquet",
        "data/raw/NQ_trades_20250201_20250930.parquet",
        "data/raw/NQ_trades_oct_dec_2025.parquet",
    ]
    ticks = load_ticks_window(win_start_ns, win_end_ns, paths)
    print(f"    {len(ticks):,} ticks in window")

    bbo_paths = [
        "data/raw/NQ_bbo_jan2025.parquet",
        "data/raw/NQ_bbo_20250201_20250930.parquet",
        "data/raw/NQ_bbo_oct_dec_2025.parquet",
    ]
    bbo = load_bbo_window(win_start_ns, win_end_ns, bbo_paths)
    print(f"    {len(bbo):,} BBO snapshots in window")
    if len(bbo):
        # Map BBO to nearest preceding tick by ts_event for context
        ticks["ts_ns"] = ticks["ts_event"].astype("int64")
        bbo["ts_ns"] = bbo["ts_event"].astype("int64")
        bbo_idx = np.searchsorted(
            bbo["ts_ns"].values, ticks["ts_ns"].values,
            side="right") - 1
        bbo_idx = np.clip(bbo_idx, 0, len(bbo) - 1)
        ticks["bid"] = bbo["bid_px_00"].values[bbo_idx]
        ticks["ask"] = bbo["ask_px_00"].values[bbo_idx]
        ticks["spread"] = ticks["ask"] - ticks["bid"]

    # Save full window
    ticks.to_parquet(
        OUT / "worst_slip_tick_window.parquet", index=False)

    lines.append("## 2. Raw tick window summary")
    lines.append("")
    lines.append(f"Window: arm_ts−10s → exit_ts+10s = "
                  f"{ts_ct(win_start_ns)} → {ts_ct(win_end_ns)}")
    lines.append(f"Total ticks in window: {len(ticks):,}")
    if len(bbo):
        lines.append(f"BBO snapshots: {len(bbo):,}")
    lines.append("")
    if len(ticks):
        px_min, px_max = ticks["price"].min(), ticks["price"].max()
        lines.append(f"Tick price range in window: "
                      f"{px_min:.2f} → {px_max:.2f} "
                      f"({(px_max-px_min)/NQ_TICK_SIZE:.0f} ticks)")
        lines.append("")

    # ---- 3. Calculation validation ----
    lines.append("## 3. Calculation validation")
    lines.append("")
    lines.append(f"- NQ tick size: **{NQ_TICK_SIZE}** "
                  "(verified)")
    lines.append(f"- NQ $/tick: **${NQ_DOLLAR_PER_TICK}** "
                  "(0.25 × $20 multiplier)")
    lines.append(f"- protect_px = entry_price + lock_pct × "
                  "MFE_at_arm × direction")
    expected_protect_raw = entry_px + 0.5 * mfe_at_arm * direction
    lines.append(f"  - expected: {entry_px:.4f} + 0.5 × "
                  f"{mfe_at_arm:.4f} × {direction:+d} = "
                  f"{expected_protect_raw:.4f}")
    lines.append(f"  - actual stored: {protect_px:.4f}")
    diff = expected_protect_raw - protect_px
    lines.append(f"  - delta from raw: {diff:+.4f} (rounding to "
                  f"tick = expected ≤ 0.25)")
    is_valid_tick = (abs(round(protect_px / NQ_TICK_SIZE)
                            * NQ_TICK_SIZE - protect_px) < 1e-9)
    lines.append(f"  - is protect_px valid NQ tick? {is_valid_tick}")
    lines.append("")
    if first_cross_ts and first_cross_px is not None:
        # Slip formula
        slip_pts_recomp = (exit_px - first_cross_px) * direction
        slip_ticks_recomp = slip_pts_recomp / NQ_TICK_SIZE
        slip_dollars_recomp = slip_pts_recomp * NQ_MULT
        lines.append("- Slip formula: "
                      "(exit_px − first_cross_px) × direction / 0.25")
        lines.append(f"  - exit_px {exit_px:.4f} − first_cross_px "
                      f"{first_cross_px:.4f} = "
                      f"{exit_px - first_cross_px:+.4f} pts")
        lines.append(f"  - × direction ({direction:+d}) = "
                      f"{slip_pts_recomp:+.4f} pts")
        lines.append(f"  - / 0.25 = {slip_ticks_recomp:+.2f} ticks "
                      f"(audit reported: {slip_ticks:+.2f})")
        lines.append(f"  - × $20 mult = {slip_dollars_recomp:+,.2f} "
                      f"(audit reported: {slip_dollars:+,.2f})")
        lines.append(f"  - signs match audit: "
                      f"{abs(slip_ticks_recomp - slip_ticks) < 0.01}")
    lines.append("")
    # Validate protect was favorable to entry at arm
    move_in_dir = (protect_px - entry_px) * direction
    lines.append(f"- protect_px favorable side of entry by "
                  f"{move_in_dir:+.4f} pts "
                  f"({move_in_dir/NQ_TICK_SIZE:+.1f} ticks)")
    lines.append(f"  - For long, protect_px > entry. For short, "
                  "protect_px < entry. Sign check: "
                  f"{'OK' if move_in_dir > 0 else 'INVERTED'}")
    lines.append("")
    # MFE relationship
    lines.append(f"- mfe_at_arm = {mfe_at_arm:.4f} pts; "
                  f"protect_offset = 0.5 × mfe = "
                  f"{0.5*mfe_at_arm:.4f}")
    lines.append("")

    # ---- 4. Manual replay sequence ----
    if len(ticks):
        ticks["ts_ns"] = ticks["ts_event"].astype("int64")
        ticks["ts_ct_str"] = ticks["ts_event"].dt.tz_convert(
            CT).dt.strftime("%H:%M:%S.%f").str[:-3]
        # Find tick crossing protect_px in our window
        if direction == 1:
            cross_mask = ticks["price"] <= protect_px
        else:
            cross_mask = ticks["price"] >= protect_px
        # Only count ticks AFTER arm_ts
        post_arm_mask = ticks["ts_ns"] >= arm_ts
        cross_post_arm = ticks[cross_mask & post_arm_mask]
        if len(cross_post_arm):
            first_cross_idx = cross_post_arm.index[0]
            # Last tick before protect was crossed
            last_pre_cross = ticks.iloc[
                max(first_cross_idx - 1, 0)]
            first_cross_tick = ticks.iloc[first_cross_idx]
            # Tick(s) used for fill
            fill_tick_idx = (
                ticks["ts_ns"] >= exit_ts).idxmax() if (
                ticks["ts_ns"] >= exit_ts).any() else -1
            lines.append("## 4. Manual tick sequence "
                         "around the cross + fill")
            lines.append("")
            lines.append("Last tick before protect_px is crossed:")
            lines.append("")
            cols = ["ts_ct_str", "price", "size", "side"]
            if "bid" in last_pre_cross:
                cols += ["bid", "ask", "spread"]
            lines.append(f"- {dict(last_pre_cross[cols])}")
            lines.append("")
            lines.append("First tick crossing protect_px:")
            lines.append(f"- {dict(first_cross_tick[cols])}")
            lines.append("")
            if fill_tick_idx >= 0:
                lines.append("Fill tick (first tick at or after exit_ts):")
                lines.append(f"- {dict(ticks.iloc[fill_tick_idx][cols])}")
                lines.append("")
                lines.append("Next 10 ticks after fill:")
                lines.append("")
                lines.append("| time CT | price | size | side |")
                lines.append("|---|--:|--:|---|")
                for i in range(min(10, len(ticks)
                                       - fill_tick_idx - 1)):
                    rr = ticks.iloc[fill_tick_idx + 1 + i]
                    lines.append(
                        f"| {rr['ts_ct_str']} | "
                        f"{rr['price']:.2f} | {rr['size']} | "
                        f"{rr['side']} |")
            lines.append("")
            # Compute time deltas for understanding
            cross_to_fill_ms = (exit_ts - int(
                first_cross_tick["ts_ns"])) / 1e6
            lines.append(f"Time from first_cross to NT fill: "
                          f"{cross_to_fill_ms:.1f} ms")
            # Price between cross and fill
            mid_window = ticks[
                (ticks["ts_ns"] >= int(
                    first_cross_tick["ts_ns"]))
                & (ticks["ts_ns"] <= exit_ts)]
            if len(mid_window):
                px_min = mid_window["price"].min()
                px_max = mid_window["price"].max()
                lines.append(f"Price range during cross→fill "
                              f"window: {px_min:.2f} → {px_max:.2f} "
                              f"({(px_max-px_min)/NQ_TICK_SIZE:.0f} ticks)")
                lines.append(f"Number of ticks in cross→fill: "
                              f"{len(mid_window):,}")
    lines.append("")

    # ---- 5. Sequence visualization (sample ticks every 100ms) ----
    if len(ticks):
        lines.append("## 5. Sample of ticks across the window")
        lines.append("")
        lines.append("First 10, middle 10, last 10 ticks (showing "
                      "price movement):")
        lines.append("")
        lines.append("| Position | time CT | price | side |")
        lines.append("|---|---|--:|---|")
        sample_idx = (list(range(min(10, len(ticks))))
                          + list(range(max(0, len(ticks)//2 - 5),
                                          min(len(ticks),
                                              len(ticks)//2 + 5)))
                          + list(range(max(0, len(ticks) - 10),
                                          len(ticks))))
        sample_idx = sorted(set(sample_idx))
        for i in sample_idx:
            rr = ticks.iloc[i]
            label = ("FIRST" if i < 10
                       else ("MIDDLE" if abs(i - len(ticks)//2) <= 5
                              else "LAST"))
            lines.append(
                f"| {label} #{i} | {rr['ts_ct_str']} | "
                f"{rr['price']:.2f} | {rr.get('side', '?')} |")
    lines.append("")


def distribution_sanity_50plus(forensic: pd.DataFrame,
                                       trades: pd.DataFrame,
                                       lines: list):
    lines.append("## 6. Distribution sanity for |slip| > 50 ticks")
    lines.append("")
    huge = forensic[
        forensic["slip_a_vs_c_realistic_ticks"].abs() > 50]
    n_huge = len(huge)
    lines.append(f"Total trades with |slip| > 50 ticks: **{n_huge}**")
    lines.append("")
    lines.append("| Date/time CT | Dir | Slip ticks | Slip $ | "
                 "exit_reason | min_to_RTH_close | "
                 "next_tick_gap_s | Tape replay claim "
                 "(crossed?) |")
    lines.append("|---|---|--:|--:|---|--:|--:|---|")
    for _, r in huge.iterrows():
        # Look up exit_reason from trade record
        ev_id = int(r["trade_id"])
        tr = trades[trades["decision_event_id"] == ev_id]
        exit_reason = (tr.iloc[0]["exit_reason"]
                          if len(tr) else "?")
        lines.append(
            f"| {r['cross_ct_time']} | "
            f"{int(r['direction']):+d} | "
            f"{r['slip_a_vs_c_realistic_ticks']:+.0f} | "
            f"{fmt_d(r['slip_a_vs_c_realistic_dollars'])} | "
            f"{exit_reason} | "
            f"{int(r['min_to_rth_close'])} | "
            f"{r['next_tick_gap_s']:.2f} | "
            f"{'YES' if r['crossed_protect_post_arm'] else 'NO'} |")
    lines.append("")


def main():
    print("Loading audit + trades...")
    audit = pd.read_parquet(
        OUT / "hhll_forensic_audit_full.parquet")
    run_dir = find_run_dir("hhll_FebSep_audit")
    trades = pd.read_parquet(run_dir / "trades.parquet")

    # Find the worst-slip trade by ABSOLUTE slip
    audit["abs_slip"] = audit[
        "slip_a_vs_c_realistic_ticks"].abs()
    worst = audit.nlargest(1, "abs_slip").iloc[0]
    # Audit uses 'trade_id', trades.parquet uses 'decision_event_id'
    ev_id = int(worst["trade_id"])
    trade_row = trades[trades["decision_event_id"] == ev_id]
    if not len(trade_row):
        print(f"Could not find trade {ev_id} in trades.parquet")
        return
    trade_row = trade_row.iloc[0]
    print(f"Worst-slip trade: id={ev_id}, "
          f"slip={worst['slip_a_vs_c_realistic_ticks']:.0f} ticks "
          f"({fmt_d(worst['slip_a_vs_c_realistic_dollars'])})")
    print(f"  exit_reason: {trade_row.get('exit_reason', '?')}")

    lines = []
    lines.append("# HH/LL Tick Forensic Replay — Worst-Slip Trade")
    lines.append("")
    lines.append("Tick-by-tick forensic replay of the single "
                  "largest-|slip| HH/LL trade. Validates all "
                  "calculations and reconstructs the actual price "
                  "movement around the protect_px crossing.")
    lines.append("")
    replay_one_trade(trade_row, worst, lines)

    # Distribution sanity for |slip| > 50
    distribution_sanity_50plus(audit, trades, lines)

    out_p = OUT / "HHLL_TICK_FORENSIC_REPLAY.md"
    out_p.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport: {out_p}")


if __name__ == "__main__":
    main()
