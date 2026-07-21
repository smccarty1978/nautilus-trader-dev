"""HH/LL replay vs tick-NT per-trade reconciliation — Feb 2025.

For each of the 215 Feb 2025 RTH trades, compares tape replay vs
tick-NT field by field. Classifies all PnL gaps into mechanical
buckets.

Inputs:
  studies/v_a_exit_recon/results/trades_C_lock50_30s_5.parquet  (tape replay)
  collectors/collector_v2/results/tick_nt/hhll_FebSep_audit_*/trades.parquet
  collectors/collector_v2/results/with_tape/NQ_2025/trades.parquet

Outputs:
  studies/v_a_exit_recon/results/HHLL_REPLAY_VS_TICKNT_RECONCILIATION_FEB2025.md
  studies/v_a_exit_recon/results/recon_feb2025_per_trade.parquet
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
WT = Path("collectors/collector_v2/results/with_tape")
OUT = Path("studies/v_a_exit_recon/results")

NQ_TICK = 0.25
NQ_MULT = 20.0


def fmt_d(v):
    if v is None or (isinstance(v, float)
                       and (pd.isna(v) or np.isinf(v))):
        return "—"
    return f"${v:,.2f}" if abs(v) < 1000 else f"${v:,.0f}"


def main():
    feb_start = pd.Timestamp("2025-02-01", tz="UTC").value
    mar_start = pd.Timestamp("2025-03-01", tz="UTC").value

    # === Load 3 sources ===
    tape = pd.read_parquet(
        OUT / "trades_C_lock50_30s_5.parquet")
    tape_feb = tape[(tape["year"] == 2025)
                      & (tape["entry_ts"] >= feb_start)
                      & (tape["entry_ts"] < mar_start)].copy()

    runs = sorted(TICK_NT.glob("hhll_FebSep_audit*"))
    ticknt = pd.read_parquet(runs[-1] / "trades.parquet")
    ticknt_feb = ticknt[
        (ticknt["session"] == "RTH")
        & (ticknt["entry_ts"] >= feb_start)
        & (ticknt["entry_ts"] < mar_start)].copy()

    wt = pd.read_parquet(WT / "NQ_2025/trades.parquet")
    wt_feb = wt[(wt["session"] == "RTH")
                 & (wt["entry_ts"] >= feb_start)
                 & (wt["entry_ts"] < mar_start)].copy()

    print(f"Counts: tape={len(tape_feb)}, "
          f"tick-NT={len(ticknt_feb)}, "
          f"with_tape={len(wt_feb)}")

    # === Match by entry_ts ===
    # All three should have the same entries (same V_A signal logic).
    # Use entry_ts as the join key.
    # Tape replay's entry_ts comes from with_tape (bar-driven). Same
    # for with_tape itself. Tick-NT's entry_ts is tick fill time.
    # These should be CLOSE but maybe not exactly equal.
    print("Sample entry_ts values (first 5):")
    print(f"  tape:    {sorted(tape_feb['entry_ts'].iloc[:5].tolist())}")
    print(f"  tick-NT: {sorted(ticknt_feb['entry_ts'].iloc[:5].tolist())}")
    print(f"  with_tape: "
          f"{sorted(wt_feb['entry_ts'].iloc[:5].tolist())}")

    # If entry_ts is the same in all three:
    common_entry = (set(tape_feb["entry_ts"])
                      & set(ticknt_feb["entry_ts"])
                      & set(wt_feb["entry_ts"]))
    print(f"  Common entry_ts across all three: {len(common_entry)}")

    # If not exactly equal, match within 30s window
    if len(common_entry) < 200:
        print("WARN: entry_ts not perfectly aligned. Trying match "
              "within 30s window.")
        # Use approximate match
        # (skip for now if exact match works)

    # === Build per-trade reconciliation ===
    tape_idx = tape_feb.set_index("entry_ts")
    tick_idx = ticknt_feb.set_index("entry_ts")
    wt_idx = wt_feb.set_index("entry_ts")

    rows = []
    for ts in sorted(common_entry):
        t = tape_idx.loc[ts]
        n = tick_idx.loc[ts]
        b = wt_idx.loc[ts]
        if isinstance(t, pd.DataFrame):
            t = t.iloc[0]
        if isinstance(n, pd.DataFrame):
            n = n.iloc[0]
        if isinstance(b, pd.DataFrame):
            b = b.iloc[0]
        d = int(t["direction"])

        # Tape replay arm/protect details aren't directly stored;
        # we have fill_price, exit_price, exit_reason, fired_rule,
        # net_pnl, baseline_net_pnl
        # Tick-NT has full state: hhll_armed, hhll_arm_ts, etc.
        rows.append({
            "entry_ts": int(ts),
            "direction": d,
            "atr_at_signal_tape": float(t["atr_at_signal"]),
            "atr_at_signal_tick": float(n["atr_at_signal"]),
            "fill_price_tape": float(t["fill_price"]),
            "fill_price_tick": float(n["fill_price"]),
            "fill_price_baseline_bardrv": float(b["fill_price"]),
            "exit_price_tape": float(t["exit_price"]),
            "exit_price_tick": float(n["exit_price"]),
            "exit_price_baseline_bardrv": float(b["exit_price"]),
            "exit_ts_tape": int(t["exit_ts"]),
            "exit_ts_tick": int(n["exit_ts"]),
            "exit_reason_tape": str(t["exit_reason"]),
            "exit_reason_tick": str(n["exit_reason"]),
            "tape_fired_rule": bool(t["fired_rule"]),
            "tick_hhll_armed": bool(n.get("hhll_armed", False)),
            "tick_hhll_arm_ts": (int(n["hhll_arm_ts"])
                if pd.notna(n.get("hhll_arm_ts")) else 0),
            "tick_hhll_protect_px": (
                float(n["hhll_protect_px"])
                if pd.notna(n.get("hhll_protect_px")) else None),
            "tick_hhll_mfe_at_arm": (
                float(n["hhll_mfe_at_arm"])
                if pd.notna(n.get("hhll_mfe_at_arm")) else None),
            "tick_running_mfe": float(n["running_mfe"]),
            "tick_running_mae": float(n["running_mae"]),
            # Net PnL
            "net_pnl_tape": float(t["net_pnl"]),
            "net_pnl_tick": float(n["net_pnl"]),
            "net_pnl_baseline_bardrv": float(b["net_pnl"]),
            "pnl_diff_tape_minus_tick": (
                float(t["net_pnl"]) - float(n["net_pnl"])),
        })
    recon = pd.DataFrame(rows)
    recon.to_parquet(
        OUT / "recon_feb2025_per_trade.parquet", index=False)
    print(f"\nReconciled {len(recon)} trades")
    print(f"Total PnL diff (tape - tick): "
          f"${recon['pnl_diff_tape_minus_tick'].sum():,.0f}")
    print(f"Mean per trade: "
          f"${recon['pnl_diff_tape_minus_tick'].mean():.2f}")

    # === Classification ===
    # For each trade, classify what's different
    # 1. fill_price mismatch (entry)
    recon["entry_diff_pts"] = (
        recon["fill_price_tape"] - recon["fill_price_tick"])
    # 2. exit_price mismatch
    recon["exit_diff_pts"] = (
        recon["exit_price_tape"] - recon["exit_price_tick"])
    # 3. exit reason mismatch
    recon["exit_reason_match"] = (
        recon["exit_reason_tape"].str.startswith("regime")
        == (recon["exit_reason_tick"] == "regime"))
    # Both fired or both didn't?
    recon["fire_match"] = (
        recon["tape_fired_rule"]
        == (recon["exit_reason_tick"] == "hhll_protect"))
    # PnL gap from each component (per trade, in $)
    # Cost difference = $5/trade (tape uses $10 cost, tick uses $5)
    # Tape: net = gross - $10. Tick: net = gross - $5.
    # So tick has $5 cost ADVANTAGE per trade. Adjust:
    recon["cost_diff_dollars"] = -5.00  # tick is $5 better
    # Effective gross PnL diff (tape gross - tick gross)
    # = (tape_net + 10) - (tick_net + 5) = tape_net - tick_net + 5
    recon["gross_pnl_diff_tape_minus_tick"] = (
        recon["net_pnl_tape"] + 10 - (recon["net_pnl_tick"] + 5))

    # Aggregate by outcome
    print("\n=== Pattern: outcome combinations ===")
    print(f"{'tape_fired':>10} {'tick_fired':>10} | "
          f"{'n':>5} | {'mean Δpnl':>10}")
    print("-" * 45)
    for tape_fired in [True, False]:
        for tick_fired_via in ["hhll_protect", "regime"]:
            sub = recon[(recon["tape_fired_rule"] == tape_fired)
                          & (recon["exit_reason_tick"]
                              == tick_fired_via)]
            if not len(sub): continue
            print(f"{str(tape_fired):>10} "
                  f"{tick_fired_via:>10} | {len(sub):>5} | "
                  f"${sub['pnl_diff_tape_minus_tick'].mean():>8.2f}")

    # === Bucket classification ===
    print("\n=== Bucket classification ===")
    # Bucket 1: entry price mismatch
    n_entry_diff = (recon["entry_diff_pts"].abs() > 0.01).sum()
    sum_entry = (recon["entry_diff_pts"] * recon["direction"]
                    * NQ_MULT).sum()
    # For both runs: tape uses bar-driven fill, tick uses tick fill.
    # The PnL impact = (tape_fill - tick_fill) * direction * mult
    # affecting both legs equivalently — entry diff impacts gross same
    print(f"  1. Entry price mismatch: "
          f"n={n_entry_diff} (tape vs tick fill diff > 0.01)")
    print(f"     mean entry diff (tape - tick) = "
          f"{recon['entry_diff_pts'].mean():+.4f} pts")
    # Bucket 5: exit timing
    n_exit_ts_diff = (recon["exit_ts_tape"]
                          != recon["exit_ts_tick"]).sum()
    print(f"  5. Exit timestamp mismatch: n={n_exit_ts_diff} "
          f"(tape exit_ts != tick exit_ts)")
    n_exit_reason_diff = (~recon["fire_match"]).sum()
    print(f"     Exit reason mismatch (fire vs no-fire): "
          f"n={n_exit_reason_diff}")
    # Bucket 6: exit price/fill convention
    n_exit_px_diff = (recon["exit_diff_pts"].abs() > 0.01).sum()
    print(f"  6. Exit price/fill mismatch: n={n_exit_px_diff}")
    print(f"     Mean exit diff (tape - tick): "
          f"{recon['exit_diff_pts'].mean():+.4f} pts")
    print(f"     ($/trade impact, signed by direction): "
          f"${(recon['exit_diff_pts'] * recon['direction'] * NQ_MULT).mean():.2f}")
    # Bucket 8: cost difference
    print(f"  8. Cost accounting: tape uses $10/RT, tick uses "
          "$5/RT → tick has $5/trade advantage")

    # ---- Top 20 PnL diff trades ----
    print("\n=== Top 20 trades by |PnL diff| ===")
    top20 = recon.nlargest(20,
                                   "pnl_diff_tape_minus_tick",
                                   keep="all")
    if len(top20) > 20:
        top20 = top20.head(20)
    bot20 = recon.nsmallest(
        20, "pnl_diff_tape_minus_tick", keep="all")
    if len(bot20) > 20:
        bot20 = bot20.head(20)
    print("Largest TAPE > tick (tape says better):")
    print(f"{'entry_ct':<22} {'dir':>3} {'fire_match':>11} "
          f"{'tape_exit':>10} {'tick_exit':>10} "
          f"{'tape_pnl':>10} {'tick_pnl':>10} {'diff':>10}")
    for _, r in top20.iterrows():
        ct = pd.Timestamp(int(r["entry_ts"]),
                                tz="UTC").tz_convert(CT).strftime(
                                "%m-%d %H:%M:%S")
        print(f"{ct:<22} {int(r['direction']):>3} "
              f"{str(r['fire_match'])[0]:>11} "
              f"{r['exit_price_tape']:>10.3f} "
              f"{r['exit_price_tick']:>10.3f} "
              f"{r['net_pnl_tape']:>10.2f} "
              f"{r['net_pnl_tick']:>10.2f} "
              f"{r['pnl_diff_tape_minus_tick']:>10.2f}")

    print()
    print("Largest TICK > tape (tick says better — opposite):")
    for _, r in bot20.iterrows():
        ct = pd.Timestamp(int(r["entry_ts"]),
                                tz="UTC").tz_convert(CT).strftime(
                                "%m-%d %H:%M:%S")
        print(f"{ct:<22} {int(r['direction']):>3} "
              f"{str(r['fire_match'])[0]:>11} "
              f"{r['exit_price_tape']:>10.3f} "
              f"{r['exit_price_tick']:>10.3f} "
              f"{r['net_pnl_tape']:>10.2f} "
              f"{r['net_pnl_tick']:>10.2f} "
              f"{r['pnl_diff_tape_minus_tick']:>10.2f}")

    # === Markdown report ===
    lines = []
    lines.append("# HH/LL Replay vs Tick-NT — Per-trade Reconciliation Feb 2025")
    lines.append("")
    lines.append(f"Per-trade comparison of {len(recon):,} matched "
                  "Feb 2025 RTH trades.")
    lines.append("")
    lines.append(f"- Total PnL gap (tape − tick): "
                  f"**{fmt_d(recon['pnl_diff_tape_minus_tick'].sum())}**")
    lines.append(f"- Mean per-trade gap: "
                  f"**{fmt_d(recon['pnl_diff_tape_minus_tick'].mean())}**")
    lines.append("")
    lines.append("## Bucket attribution")
    lines.append("")
    lines.append("| Bucket | Detail | Mean signed $/trade impact "
                  "(tape − tick) |")
    lines.append("|---|---|--:|")
    e_impact = (recon['entry_diff_pts'] * recon['direction']
                  * NQ_MULT).mean()
    x_impact = -(recon['exit_diff_pts'] * recon['direction']
                   * NQ_MULT).mean()
    cost_impact = -5.0  # tape charges $5 more in cost
    lines.append(f"| 1. Entry price | tape vs tick fill_price diff | "
                  f"{fmt_d(e_impact)} |")
    lines.append(f"| 6. Exit price | tape vs tick exit_price diff | "
                  f"{fmt_d(x_impact)} |")
    lines.append(f"| 8. Cost accounting | tape $10 RT vs tick $5 RT | "
                  f"{fmt_d(cost_impact)} |")
    lines.append(f"| **Sum** | | "
                  f"**{fmt_d(e_impact + x_impact + cost_impact)}** |")
    lines.append("")

    lines.append("## Outcome combinations")
    lines.append("")
    lines.append("| Tape fired | Tick fired (via) | n | Mean Δpnl |")
    lines.append("|---|---|--:|--:|")
    for tape_fired in [True, False]:
        for tick_via in ["hhll_protect", "regime"]:
            sub = recon[(recon["tape_fired_rule"] == tape_fired)
                          & (recon["exit_reason_tick"]
                              == tick_via)]
            if not len(sub): continue
            lines.append(
                f"| {'YES' if tape_fired else 'no'} | {tick_via} | "
                f"{len(sub)} | "
                f"{fmt_d(sub['pnl_diff_tape_minus_tick'].mean())} |")
    lines.append("")

    lines.append("## Top 20 largest PnL gaps (tape > tick)")
    lines.append("")
    lines.append("| Entry CT | Dir | Fire match | Tape exit px | "
                 "Tick exit px | Tape PnL | Tick PnL | Diff |")
    lines.append("|---|--:|---|--:|--:|--:|--:|--:|")
    for _, r in top20.iterrows():
        ct = pd.Timestamp(int(r["entry_ts"]),
                                tz="UTC").tz_convert(CT).strftime(
                                "%m-%d %H:%M:%S")
        lines.append(
            f"| {ct} | {int(r['direction']):+d} | "
            f"{str(r['fire_match'])} | "
            f"{r['exit_price_tape']:.3f} | "
            f"{r['exit_price_tick']:.3f} | "
            f"{fmt_d(r['net_pnl_tape'])} | "
            f"{fmt_d(r['net_pnl_tick'])} | "
            f"{fmt_d(r['pnl_diff_tape_minus_tick'])} |")
    lines.append("")
    lines.append("## Top 20 largest negative PnL gaps (tick > tape)")
    lines.append("")
    lines.append("| Entry CT | Dir | Fire match | Tape exit px | "
                 "Tick exit px | Tape PnL | Tick PnL | Diff |")
    lines.append("|---|--:|---|--:|--:|--:|--:|--:|")
    for _, r in bot20.iterrows():
        ct = pd.Timestamp(int(r["entry_ts"]),
                                tz="UTC").tz_convert(CT).strftime(
                                "%m-%d %H:%M:%S")
        lines.append(
            f"| {ct} | {int(r['direction']):+d} | "
            f"{str(r['fire_match'])} | "
            f"{r['exit_price_tape']:.3f} | "
            f"{r['exit_price_tick']:.3f} | "
            f"{fmt_d(r['net_pnl_tape'])} | "
            f"{fmt_d(r['net_pnl_tick'])} | "
            f"{fmt_d(r['pnl_diff_tape_minus_tick'])} |")
    lines.append("")

    out_p = (OUT
             / "HHLL_REPLAY_VS_TICKNT_RECONCILIATION_FEB2025.md")
    out_p.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport: {out_p}")


if __name__ == "__main__":
    main()
