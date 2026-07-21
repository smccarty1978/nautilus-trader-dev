"""Forensic audit of HH/LL tick-NT high-slip exits.

For each protective exit with slip > {5, 10, 25, 50} ticks:
  - trade id, date, time CT
  - direction, protect_px, first-cross tick price, NT fill price
  - slip in ticks
  - seconds to next tick after detection
  - distance to RTH close, RTH open, ETH close
  - whether trade held past EOD (16:00 CT close)
  - whether the exit happened across a session gap

Inputs: existing
  studies/v_a_exit_recon/results/hhll_attribution_audit.parquet
  collectors/collector_v2/results/tick_nt/hhll_FebSep_audit_*/trades.parquet
  data/raw/NQ_trades_20250201_20250930.parquet (tick stream)

Output:
  studies/v_a_exit_recon/results/HHLL_FORENSIC_SLIPPAGE.md
  studies/v_a_exit_recon/results/hhll_high_slip_trades.parquet
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

# RTH session boundaries (CT minutes from midnight)
RTH_OPEN = 510    # 08:30 CT
RTH_CLOSE = 900   # 15:00 CT
ETH_CLOSE = 960   # 16:00 CT (NQ globex close)
ETH_REOPEN = 1020 # 17:00 CT (NQ globex reopen — next session)


def fmt_d(v):
    if v is None or (isinstance(v, float)
                       and (pd.isna(v) or np.isinf(v))):
        return "—"
    return f"${v:,.2f}" if abs(v) < 1000 else f"${v:,.0f}"


def fmt_p(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{100*v:.1f}%"


def ts_ct(ns: int) -> pd.Timestamp:
    return pd.Timestamp(int(ns), tz="UTC").tz_convert(CT)


def main():
    audit_p = OUT / "hhll_attribution_audit.parquet"
    if not audit_p.exists():
        print(f"Missing {audit_p} — run hhll_attribution_audit.py "
              "first")
        return
    audit = pd.read_parquet(audit_p)
    print(f"Loaded {len(audit):,} audit rows")

    # Load tick data for gap analysis
    print("Loading Feb-Sep 2025 ticks (for gap diagnostics)...")
    import pyarrow.parquet as pq
    feb_start = pd.Timestamp("2025-02-01", tz="UTC")
    sep_end = pd.Timestamp("2025-10-01", tz="UTC")
    tbl = pq.read_table(
        "data/raw/NQ_trades_20250201_20250930.parquet",
        columns=["ts_event", "price", "action"],
        filters=[
            ("ts_event", ">=", feb_start),
            ("ts_event", "<", sep_end),
            ("action", "=", "T"),
        ],
    )
    ticks = tbl.to_pandas().sort_values("ts_event").reset_index(
        drop=True)
    tick_ts = ticks["ts_event"].astype("int64").values
    tick_px = ticks["price"].values
    print(f"  {len(tick_ts):,} trade ticks loaded")

    # ---- Diagnostic columns ----
    print("\nComputing forensic columns per audit row...")
    rows = []
    for _, t in audit.iterrows():
        arm_ts = int(t.get("arm_ts", 0))
        if arm_ts == 0: continue
        first_cross_ts = (int(t["first_cross_ts"])
                              if t.get("first_cross_ts")
                              and pd.notna(t.get("first_cross_ts"))
                              else None)
        nt_exit_ts = int(t["version_a_exit_ts"])
        if first_cross_ts is None:
            continue   # no cross — Version A and C agree
        # Time-CT diagnostics — use the FIRST CROSS time as reference
        cross_ct = ts_ct(first_cross_ts)
        cross_min_ct = cross_ct.hour * 60 + cross_ct.minute
        nt_exit_ct = ts_ct(nt_exit_ts)
        # Distance to RTH/ETH boundaries (positive = past, negative = before)
        min_to_rth_close = cross_min_ct - RTH_CLOSE
        min_to_eth_close = cross_min_ct - ETH_CLOSE
        min_to_rth_open = cross_min_ct - RTH_OPEN
        # Did NT exit happen across the 16:00→17:00 ETH close gap?
        # Bucket the cross day vs nt_exit day
        cross_day = cross_ct.normalize()
        nt_exit_day = nt_exit_ct.normalize()
        # Gap to next tick after first cross
        idx = int(np.searchsorted(tick_ts, first_cross_ts,
                                          side="left"))
        if idx + 1 < len(tick_ts):
            next_tick_gap_s = float(
                (tick_ts[idx + 1] - tick_ts[idx]) / 1e9)
        else:
            next_tick_gap_s = float("nan")
        # Gap from first cross to NT fill (= bar close + 1 tick lag)
        ts_to_nt_fill_s = float(
            (nt_exit_ts - first_cross_ts) / 1e9)
        # Held past 16:00 CT
        held_past_eth_close = (
            cross_min_ct >= ETH_CLOSE
            or (cross_min_ct < ETH_CLOSE
                and nt_exit_ct.hour * 60 + nt_exit_ct.minute
                    >= ETH_CLOSE)
            or cross_day != nt_exit_day)
        # Crossed into next-day session
        crossed_eth_session = (cross_day != nt_exit_day)
        # Tick gap > 1s nearby
        tick_gap_above_1s = next_tick_gap_s > 1.0
        rows.append({
            **t.to_dict(),
            "cross_ct_minute": cross_min_ct,
            "cross_ct_time": cross_ct.strftime(
                "%Y-%m-%d %H:%M:%S"),
            "nt_exit_ct_time": nt_exit_ct.strftime(
                "%Y-%m-%d %H:%M:%S"),
            "min_to_rth_close": min_to_rth_close,
            "min_to_eth_close": min_to_eth_close,
            "next_tick_gap_s": next_tick_gap_s,
            "first_cross_to_nt_fill_s": ts_to_nt_fill_s,
            "tick_gap_above_1s": tick_gap_above_1s,
            "held_past_eth_close": held_past_eth_close,
            "crossed_eth_session": crossed_eth_session,
        })
    forensic = pd.DataFrame(rows)
    forensic.to_parquet(
        OUT / "hhll_forensic_audit_full.parquet", index=False)
    print(f"  Built {len(forensic):,} forensic rows")

    # ---- Threshold breakdown ----
    print("\n=== Slippage threshold breakdown ===")
    print(f"{'Bucket':<25} {'n':>5} {'%':>6} {'Mean $':>10} "
          f"{'Total $':>12}")
    thresholds = [(0, 5), (5, 10), (10, 25), (25, 50), (50, 1e9)]
    for lo, hi in thresholds:
        sub = forensic[
            (forensic["slip_a_vs_c_realistic_ticks"] > lo)
            & (forensic["slip_a_vs_c_realistic_ticks"] <= hi)]
        n = len(sub)
        pct = n / max(len(forensic), 1) * 100
        # Aggregate of slip_dollars for this bucket
        slip_sum = sub["slip_a_vs_c_realistic_dollars"].sum()
        slip_mean = (sub["slip_a_vs_c_realistic_dollars"].mean()
                       if n > 0 else 0)
        print(f"  >{lo:>3} ≤{hi if hi < 1e9 else '∞':<5} | "
              f"{n:>5} {pct:>5.1f}%  {fmt_d(slip_mean):>10}  "
              f"{fmt_d(slip_sum):>12}")
    n_zero = (forensic["slip_a_vs_c_realistic_ticks"] == 0).sum()
    print(f"  exactly 0 ticks slip: {n_zero:,} "
          f"({n_zero/len(forensic)*100:.1f}%)")

    # ---- Worst 10 ----
    print("\n=== Top 10 worst-slip trades ===")
    worst = forensic.nlargest(
        10, "slip_a_vs_c_realistic_ticks")
    for _, r in worst.iterrows():
        print(f"  {r['cross_ct_time']} CT, dir={int(r['direction']):+d}, "
              f"slip {r['slip_a_vs_c_realistic_ticks']:.0f} ticks "
              f"({fmt_d(r['slip_a_vs_c_realistic_dollars'])}), "
              f"min_to_rth_close={int(r['min_to_rth_close'])}, "
              f"min_to_eth_close={int(r['min_to_eth_close'])}, "
              f"next_tick_gap={r['next_tick_gap_s']:.2f}s, "
              f"held_past_eth={bool(r['held_past_eth_close'])}, "
              f"crossed_session={bool(r['crossed_eth_session'])}")

    # ---- Aggregate diagnostics ----
    print("\n=== Aggregate diagnostics for high-slip cohort "
          "(slip > 5 ticks) ===")
    high_slip = forensic[
        forensic["slip_a_vs_c_realistic_ticks"] > 5]
    n_hs = len(high_slip)
    if n_hs > 0:
        print(f"  Total high-slip trades: {n_hs:,} "
              f"({n_hs/len(forensic)*100:.1f}% of crosses)")
        print(f"  Held past 16:00 CT: "
              f"{(high_slip['held_past_eth_close'].sum())} "
              f"({high_slip['held_past_eth_close'].mean()*100:.1f}%)")
        print(f"  Crossed ETH session boundary: "
              f"{(high_slip['crossed_eth_session'].sum())} "
              f"({high_slip['crossed_eth_session'].mean()*100:.1f}%)")
        print(f"  After RTH close (cross_min_ct >= 900): "
              f"{(high_slip['cross_ct_minute'] >= 900).sum()} "
              f"({(high_slip['cross_ct_minute']>=900).mean()*100:.1f}%)")
        print(f"  Within last 15 min RTH (cross_min_ct >= 885): "
              f"{(high_slip['cross_ct_minute'] >= 885).sum()}")
        print(f"  Tick gap > 1s nearby: "
              f"{(high_slip['tick_gap_above_1s'].sum())} "
              f"({high_slip['tick_gap_above_1s'].mean()*100:.1f}%)")
        print(f"  Tick gap > 5s nearby: "
              f"{(high_slip['next_tick_gap_s'] > 5).sum()}")
        print(f"  Tick gap > 60s nearby (likely halt/close): "
              f"{(high_slip['next_tick_gap_s'] > 60).sum()}")

    # Distribution of cross times for high-slip
    print("\n=== High-slip exit-time distribution (CT minute "
          "from midnight) ===")
    if n_hs > 0:
        hs_minutes = high_slip["cross_ct_minute"]
        print(f"  Median: {hs_minutes.median():.0f}, "
              f"p25: {hs_minutes.quantile(0.25):.0f}, "
              f"p75: {hs_minutes.quantile(0.75):.0f}")
        print(f"  Min: {hs_minutes.min()}, Max: {hs_minutes.max()}")

    # Save high-slip cohort
    high_slip.to_parquet(
        OUT / "hhll_high_slip_trades.parquet", index=False)

    # ---- Markdown report ----
    lines = []
    lines.append("# HH/LL Tick-NT Forensic Slippage Audit")
    lines.append("")
    lines.append("Forensic audit of high-slip exits in the tick-NT "
                 "HH/LL validation. Tests whether large slippage "
                 "tail is caused by session boundaries / halts / "
                 "data gaps that we would never trade through "
                 "live.")
    lines.append("")
    lines.append(f"- Population: {len(forensic):,} crossed armed "
                  "trades (Feb-Sep 2025 RTH)")
    lines.append("")

    lines.append("## Slippage threshold buckets")
    lines.append("")
    lines.append("| Bucket (ticks) | n | % of crosses | "
                 "Mean slip $ | Total slip $ |")
    lines.append("|---|--:|--:|--:|--:|")
    for lo, hi in thresholds:
        sub = forensic[
            (forensic["slip_a_vs_c_realistic_ticks"] > lo)
            & (forensic["slip_a_vs_c_realistic_ticks"] <= hi)]
        n = len(sub)
        pct = n / max(len(forensic), 1) * 100
        slip_sum = sub["slip_a_vs_c_realistic_dollars"].sum()
        slip_mean = (sub["slip_a_vs_c_realistic_dollars"].mean()
                       if n > 0 else 0)
        hi_label = f"{hi:.0f}" if hi < 1e9 else "∞"
        lines.append(
            f"| (>{lo}, ≤{hi_label}] | {n} | {pct:.1f}% | "
            f"{fmt_d(slip_mean)} | {fmt_d(slip_sum)} |")
    lines.append(f"| exactly 0 | {n_zero} | "
                  f"{n_zero/len(forensic)*100:.1f}% | $0 | $0 |")
    lines.append("")

    lines.append("## Top 20 worst-slip trades")
    lines.append("")
    lines.append("| Cross time CT | Dir | Slip ticks | Slip $ | "
                 "Min→RTHclose | Min→ETHclose | Next-tick gap s | "
                 "Held past ETH close | Crossed session |")
    lines.append("|---|---|--:|--:|--:|--:|--:|---|---|")
    worst_20 = forensic.nlargest(
        20, "slip_a_vs_c_realistic_ticks")
    for _, r in worst_20.iterrows():
        lines.append(
            f"| {r['cross_ct_time']} | "
            f"{int(r['direction']):+d} | "
            f"{r['slip_a_vs_c_realistic_ticks']:.0f} | "
            f"{fmt_d(r['slip_a_vs_c_realistic_dollars'])} | "
            f"{int(r['min_to_rth_close'])} | "
            f"{int(r['min_to_eth_close'])} | "
            f"{r['next_tick_gap_s']:.2f} | "
            f"{'YES' if r['held_past_eth_close'] else 'no'} | "
            f"{'YES' if r['crossed_eth_session'] else 'no'} |")
    lines.append("")

    lines.append("## High-slip cohort diagnostics (slip > 5 ticks)")
    lines.append("")
    if n_hs > 0:
        n_held = int(high_slip['held_past_eth_close'].sum())
        n_crossed_sess = int(high_slip['crossed_eth_session'].sum())
        n_after_rth = int((high_slip['cross_ct_minute']
                            >= 900).sum())
        n_last15 = int((high_slip['cross_ct_minute']
                          >= 885).sum())
        n_gap_1s = int(high_slip['tick_gap_above_1s'].sum())
        n_gap_5s = int((high_slip['next_tick_gap_s']
                          > 5).sum())
        n_gap_60s = int((high_slip['next_tick_gap_s']
                           > 60).sum())
        lines.append(f"- Total high-slip: **{n_hs}** "
                      f"({n_hs/len(forensic)*100:.1f}% of crosses)")
        lines.append(f"- Held past 16:00 CT (ETH close): "
                      f"**{n_held}** ({n_held/n_hs*100:.1f}% of "
                      "high-slip)")
        lines.append(f"- Crossed ETH session boundary: "
                      f"**{n_crossed_sess}** "
                      f"({n_crossed_sess/n_hs*100:.1f}%)")
        lines.append(f"- After RTH close (≥15:00 CT): "
                      f"**{n_after_rth}** "
                      f"({n_after_rth/n_hs*100:.1f}%)")
        lines.append(f"- Within last 15 min RTH (≥14:45 CT): "
                      f"**{n_last15}** "
                      f"({n_last15/n_hs*100:.1f}%)")
        lines.append(f"- Tick gap > 1s nearby: **{n_gap_1s}** "
                      f"({n_gap_1s/n_hs*100:.1f}%)")
        lines.append(f"- Tick gap > 5s nearby: **{n_gap_5s}**")
        lines.append(f"- Tick gap > 60s nearby (halt/close-like): "
                      f"**{n_gap_60s}**")
    lines.append("")

    # ---- Verdict ----
    lines.append("## Forensic verdict")
    lines.append("")
    n_top5 = 5
    top5 = forensic.nlargest(
        n_top5, "slip_a_vs_c_realistic_ticks")
    top5_dollar_impact = float(
        top5["slip_a_vs_c_realistic_dollars"].sum())
    lines.append(f"- Top 5 worst-slip trades alone account for "
                  f"{fmt_d(top5_dollar_impact)} of slippage")
    lines.append(f"- Top 20 worst account for "
                  f"{fmt_d(worst_20['slip_a_vs_c_realistic_dollars'].sum())}")
    lines.append("")

    out_p = OUT / "HHLL_FORENSIC_SLIPPAGE.md"
    out_p.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport: {out_p}")


if __name__ == "__main__":
    main()
