"""HH/LL tick-NT validation — attribution audit.

Tests the hypothesis: tick-NT failure is implementation semantics
(reactive market exit after 1s bar close detects breach) rather
than rule failure.

Version A (current tick-NT): internal monitor at 1s bar close
detects high/low cross of protect_px → submit MARKET → fill at
next tick AFTER bar close. This adds 1+ seconds of slippage.

Version B (true resting stop): would have been placed at arm time;
NT matching engine triggers and fills on FIRST tick that crosses
protect_px during any 1s bar. Fill at protect_px.

Version C (offline tick replay assuming Version B semantics):
scan tick stream after arm_ts; first tick crossing protect_px
triggers exit at protect_px. Held to regime exit otherwise.

Per HH/LL-armed trade, computes:
  - arm_ts, protect_px
  - first tick post-arm that crosses protect_px (Version C exit ts/px)
  - tick-NT actual exit ts/px (Version A)
  - difference in ticks
  - whether resting stop would be VALID at arm time
    (protect_px not already past the current tick price)

Aggregates Version A vs Version C economics across all trades.

Inputs:
  hhll_FebSep_audit_*/trades.parquet  (must have hhll_arm_ts)
  data/raw/NQ_trades_20250201_20250930.parquet
"""

from __future__ import annotations
import os, sys, json
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
NQ_MULT = 20.0
COST_RT = 5.0  # commission only (tick fills replace tick proxy)


def fmt_d(v):
    if v is None or (isinstance(v, float)
                       and (pd.isna(v) or np.isinf(v))):
        return "—"
    return f"${v:,.2f}" if abs(v) < 1000 else f"${v:,.0f}"


def fmt_p(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{100*v:.1f}%"


def fmt_pf(v):
    if v is None or (isinstance(v, float)
                       and (pd.isna(v) or np.isinf(v))):
        return "—"
    return f"{v:.2f}"


def stats(pnl):
    s = pd.Series(pnl).dropna()
    n = len(s)
    if n == 0: return {"n": 0}
    wins = s[s > 0]; losses = s[s < 0]
    pf = (wins.sum() / abs(losses.sum())
          if len(losses) and losses.sum() != 0
          else float("inf"))
    return {"n": n, "wr": float((s > 0).mean()),
              "mean": float(s.mean()), "sum": float(s.sum()),
              "pf": float(pf)}


def find_run_dir(prefix: str) -> Path | None:
    candidates = sorted(TICK_NT.glob(f"{prefix}*"))
    if not candidates: return None
    return candidates[-1]


def main():
    print("Loading tick-NT HH/LL audit run...")
    run_dir = find_run_dir("hhll_FebSep_audit")
    if run_dir is None:
        print("Could not find hhll_FebSep_audit_* — abort")
        return
    trades = pd.read_parquet(run_dir / "trades.parquet")
    if "hhll_arm_ts" not in trades.columns:
        print("ERROR: trades.parquet does not have hhll_arm_ts. "
              "Re-run tick-NT with the arm_ts patch.")
        return
    rth = trades[trades["session"] == "RTH"].copy()
    print(f"  RTH trades: {len(rth):,}")
    armed = rth[(rth.get("hhll_armed", False) == True)
                  & (rth["hhll_arm_ts"] > 0)].copy()
    print(f"  Armed RTH: {len(armed):,}")
    fired = armed[armed["exit_reason"] == "hhll_protect"].copy()
    not_fired = armed[
        armed["exit_reason"] != "hhll_protect"].copy()
    print(f"  Fired: {len(fired):,}, "
          f"Armed-but-didn't-fire: {len(not_fired):,}")

    print("\nLoading Feb-Sep 2025 tick data...")
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
    ticks["ts_ns"] = ticks["ts_event"].astype("int64")
    tick_ts = ticks["ts_ns"].values
    tick_px = ticks["price"].values
    print(f"  Loaded {len(tick_px):,} trade ticks")

    # ---- Per-trade Version C reconstruction ----
    print("\nRunning per-trade audit...")
    rows = []
    for _, t in armed.iterrows():
        arm_ts = int(t["hhll_arm_ts"])
        protect_px = float(t["hhll_protect_px"])
        d = int(t["direction"])
        ep = float(t["fill_price"])
        regime_exit_ts = int(t["exit_ts"])
        regime_exit_px = float(t["exit_price"])

        # Find first tick at or AFTER arm_ts
        idx_start = int(np.searchsorted(
            tick_ts, arm_ts, side="left"))
        if idx_start >= len(tick_ts):
            continue

        # Validity check: would resting stop have been valid at
        # arm time? Look at the LAST tick BEFORE arm_ts
        idx_pre = idx_start - 1 if idx_start > 0 else 0
        px_at_arm = float(tick_px[idx_pre])
        if d == 1:
            # SELL stop — valid if protect_px < current price
            stop_valid_at_arm = protect_px < px_at_arm
        else:
            # BUY stop — valid if protect_px > current price
            stop_valid_at_arm = protect_px > px_at_arm

        # Find first tick post-arm that crosses protect_px.
        # Scan window MUST end at the trade's actual exit_ts
        # (cannot trigger a stop after the trade is closed).
        # Add a 5-second buffer to handle same-bar arm+exit cases
        # where regime_exit_ts ≈ arm_ts at the nanosecond level.
        scan_end_ts = int(regime_exit_ts) + 5 * 1_000_000_000
        idx_end = int(np.searchsorted(
            tick_ts, scan_end_ts, side="right"))
        scan_px = tick_px[idx_start:idx_end]
        scan_ts = tick_ts[idx_start:idx_end]
        # Only count crosses BEFORE the actual trade exit_ts.
        # Beyond exit_ts the trade is closed; a "stop" can't fire.
        valid_window_mask = scan_ts <= int(regime_exit_ts)
        if len(scan_px) == 0:
            continue
        if d == 1:
            cross_mask = scan_px <= protect_px
        else:
            cross_mask = scan_px >= protect_px
        # Restrict cross detection to within the actual trade window
        cross_mask_valid = cross_mask & valid_window_mask
        if cross_mask_valid.any():
            first_cross_idx = int(np.argmax(cross_mask_valid))
            version_c_exit_ts = int(scan_ts[first_cross_idx])
            version_c_exit_px = float(scan_px[first_cross_idx])
            crossed = True
        else:
            # Never crossed during trade lifetime — Version C also
            # goes to regime exit (same as Version A)
            version_c_exit_ts = regime_exit_ts
            version_c_exit_px = regime_exit_px
            crossed = False

        # Version A is the actual tick-NT exit (whatever exit_reason
        # was). For "fired" trades it's the market fill after bar
        # close. For "didn't fire" trades it's the regime exit
        # (same as Version C in that case).
        version_a_exit_ts = regime_exit_ts
        version_a_exit_px = regime_exit_px

        # Slippage in ticks (between Version C and Version A)
        slip_pts = (version_a_exit_px - version_c_exit_px) * d
        slip_ticks = slip_pts / 0.25
        slip_dollars = slip_pts * NQ_MULT

        # PnL under each version (gross of cost, then minus $5 commission)
        pnl_a_gross = (version_a_exit_px - ep) * d * NQ_MULT
        pnl_c_gross = (version_c_exit_px - ep) * d * NQ_MULT
        # If Version C uses protect_px exactly (assumed-stop-fill
        # convention), use that. Otherwise use scan_px (next tick
        # at-or-past).
        # Two sub-versions:
        #   C_strict: exit at protect_px (standard backtest stop
        #     fill assumption — what tape replay used)
        #   C_realistic: exit at first-cross tick price (more
        #     pessimistic if protect was leaped past)
        c_strict_exit_px = (protect_px if crossed
                              else regime_exit_px)
        pnl_c_strict_gross = (c_strict_exit_px - ep) * d * NQ_MULT

        rows.append({
            "trade_id": int(t["decision_event_id"]),
            "session": t["session"],
            "direction": d,
            "fill_price": ep,
            "atr_at_signal": float(t.get("atr_at_signal", 0)),
            "arm_ts": arm_ts,
            "protect_px": protect_px,
            "px_at_arm": px_at_arm,
            "stop_valid_at_arm": stop_valid_at_arm,
            "crossed_protect_post_arm": crossed,
            "first_cross_ts": version_c_exit_ts if crossed else None,
            "first_cross_px": version_c_exit_px if crossed else None,
            "regime_exit_ts": regime_exit_ts,
            "regime_exit_px": regime_exit_px,
            "version_a_exit_ts": version_a_exit_ts,
            "version_a_exit_px": version_a_exit_px,
            "version_c_strict_exit_px": c_strict_exit_px,
            "version_c_realistic_exit_px": version_c_exit_px,
            "slip_a_vs_c_realistic_ticks": slip_ticks,
            "slip_a_vs_c_realistic_dollars": slip_dollars,
            "pnl_a_gross": pnl_a_gross,
            "pnl_c_strict_gross": pnl_c_strict_gross,
            "pnl_c_realistic_gross": pnl_c_gross,
            "pnl_a_net": pnl_a_gross - COST_RT,
            "pnl_c_strict_net": pnl_c_strict_gross - COST_RT,
            "pnl_c_realistic_net": pnl_c_gross - COST_RT,
            "exit_reason_a": t["exit_reason"],
        })

    audit = pd.DataFrame(rows)
    audit.to_parquet(OUT / "hhll_attribution_audit.parquet",
                       index=False)
    print(f"  Built {len(audit):,} audit rows")

    # ---- Aggregate stats ----
    s_a = stats(audit["pnl_a_net"])
    s_c_strict = stats(audit["pnl_c_strict_net"])
    s_c_real = stats(audit["pnl_c_realistic_net"])

    n_armed = len(audit)
    n_crossed = int(audit["crossed_protect_post_arm"].sum())
    n_stop_valid = int(audit["stop_valid_at_arm"].sum())
    n_stop_in_market = n_armed - n_stop_valid
    print()
    print("=== Validity at arm time ===")
    print(f"  Resting stop VALID at arm:   {n_stop_valid:,} "
          f"({n_stop_valid/n_armed*100:.1f}%)")
    print(f"  Resting stop IN MARKET (would reject): "
          f"{n_stop_in_market:,} "
          f"({n_stop_in_market/n_armed*100:.1f}%)")
    print()
    print("=== Whether protect_px crossed post-arm ===")
    print(f"  Crossed: {n_crossed:,} "
          f"({n_crossed/n_armed*100:.1f}%)")
    print(f"  Held to regime: {n_armed - n_crossed:,}")
    print()
    print("=== Slippage (Version A vs Version C realistic) "
          "for crossed trades ===")
    crossed_audit = audit[audit["crossed_protect_post_arm"]]
    if len(crossed_audit):
        print(f"  Mean slip: {crossed_audit['slip_a_vs_c_realistic_ticks'].mean():.2f} ticks "
              f"({fmt_d(crossed_audit['slip_a_vs_c_realistic_dollars'].mean())})")
        print(f"  Median slip: {crossed_audit['slip_a_vs_c_realistic_ticks'].median():.2f} ticks")
        print(f"  p90 slip: {crossed_audit['slip_a_vs_c_realistic_ticks'].quantile(0.9):.2f} ticks")
        print(f"  Max slip: {crossed_audit['slip_a_vs_c_realistic_ticks'].max():.2f} ticks")
    print()
    print("=== Per-trade PnL distributions (armed trades only) ===")
    print(f"{'Version':<32} {'n':>6} {'WR':>7} "
          f"{'Mean $':>10} {'Total $':>12} {'PF':>5}")
    for label, s in [
        ("A: tick-NT actual (reactive market)", s_a),
        ("C_strict: stop fills @ protect_px", s_c_strict),
        ("C_realistic: stop fills @ first cross", s_c_real),
    ]:
        print(f"{label:<32} {s['n']:>6,} "
              f"{s['wr']*100:>6.1f}% {s['mean']:>10,.2f} "
              f"{s['sum']:>12,.0f} {s['pf']:>5.2f}")
    print()
    delta_a_to_c_strict = s_c_strict["mean"] - s_a["mean"]
    delta_a_to_c_real = s_c_real["mean"] - s_a["mean"]
    print(f"Δ per trade (C_strict − A): "
          f"{fmt_d(delta_a_to_c_strict)}")
    print(f"Δ per trade (C_realistic − A): "
          f"{fmt_d(delta_a_to_c_real)}")
    print(f"Total armed-trade Δ (C_strict − A): "
          f"{fmt_d(s_c_strict['sum'] - s_a['sum'])}")
    print(f"Total armed-trade Δ (C_realistic − A): "
          f"{fmt_d(s_c_real['sum'] - s_a['sum'])}")

    # ---- Build markdown report ----
    lines = []
    lines.append("# HH/LL Tick-NT Validation — Attribution Audit")
    lines.append("")
    lines.append("Tests whether tick-NT HH/LL failure was caused by "
                 "implementation semantics (reactive market exit "
                 "after 1s bar close) vs rule failure.")
    lines.append("")
    lines.append("## Versions tested")
    lines.append("")
    lines.append("- **Version A (actual tick-NT)**: internal monitor "
                 "at 1s bar close detects breach → submit MARKET → "
                 "fill at next tick AFTER bar close. Adds 1+ seconds "
                 "of detection latency.")
    lines.append("- **Version C_strict (assumed-fill stop)**: scan "
                 "tick stream from arm_ts; first tick crossing "
                 "protect_px triggers exit at protect_px exactly "
                 "(standard backtest stop convention; what tape "
                 "replay assumed).")
    lines.append("- **Version C_realistic (first-cross stop)**: "
                 "scan tick stream from arm_ts; first tick crossing "
                 "protect_px triggers exit at THAT tick's price "
                 "(more honest than C_strict).")
    lines.append("")
    lines.append(f"- Population: {n_armed:,} armed RTH trades from "
                  "tick-NT HH/LL Feb-Sep 2025 run")
    lines.append(f"- Tick data: NQ trades Feb-Sep 2025 (~59M)")
    lines.append("")

    lines.append("## Stop validity at arm time")
    lines.append("")
    lines.append(f"- Resting stop would be VALID at arm "
                  f"(protect_px not already past current price): "
                  f"**{n_stop_valid:,} ({n_stop_valid/n_armed*100:.1f}%)**")
    lines.append(f"- Resting stop would be IN MARKET at arm "
                  f"(NT would REJECT, fall through to market): "
                  f"**{n_stop_in_market:,} "
                  f"({n_stop_in_market/n_armed*100:.1f}%)**")
    lines.append("")

    lines.append("## Crossed-protect rate")
    lines.append("")
    lines.append(f"- Crossed protect_px after arm: "
                  f"**{n_crossed:,} ({n_crossed/n_armed*100:.1f}%)**")
    lines.append(f"- Held to regime exit: {n_armed - n_crossed:,}")
    lines.append("")

    if len(crossed_audit):
        lines.append("## Slippage (Version A vs Version C realistic) — "
                     "crossed trades only")
        lines.append("")
        lines.append("Positive = tick-NT exit WORSE than first cross.")
        lines.append("")
        lines.append("| Quantile | Slip (ticks) | Slip ($) |")
        lines.append("|---|--:|--:|")
        for q in [0.05, 0.25, 0.50, 0.75, 0.95]:
            lines.append(
                f"| p{int(q*100)} | "
                f"{crossed_audit['slip_a_vs_c_realistic_ticks'].quantile(q):+.2f} | "
                f"{fmt_d(crossed_audit['slip_a_vs_c_realistic_dollars'].quantile(q))} |")
        lines.append(
            f"| mean | "
            f"{crossed_audit['slip_a_vs_c_realistic_ticks'].mean():+.2f} | "
            f"{fmt_d(crossed_audit['slip_a_vs_c_realistic_dollars'].mean())} |")
        lines.append(
            f"| max | "
            f"{crossed_audit['slip_a_vs_c_realistic_ticks'].max():+.2f} | "
            f"{fmt_d(crossed_audit['slip_a_vs_c_realistic_dollars'].max())} |")
        lines.append("")

    lines.append("## Per-trade PnL — armed cohort only")
    lines.append("")
    lines.append("| Version | n | WR | Mean $ | Total $ | PF |")
    lines.append("|---|--:|--:|--:|--:|--:|")
    for label, s in [
        ("A: tick-NT actual (reactive market)", s_a),
        ("**C_strict: stop fills at protect_px (tape replay convention)**", s_c_strict),
        ("C_realistic: stop fills at first cross", s_c_real),
    ]:
        lines.append(
            f"| {label} | {s['n']:,} | {fmt_p(s['wr'])} | "
            f"{fmt_d(s['mean'])} | {fmt_d(s['sum'])} | "
            f"{fmt_pf(s['pf'])} |")
    lines.append("")
    lines.append(f"- Δ mean per trade (C_strict − A): "
                  f"**{fmt_d(delta_a_to_c_strict)}**")
    lines.append(f"- Δ mean per trade (C_realistic − A): "
                  f"**{fmt_d(delta_a_to_c_real)}**")
    lines.append(f"- Δ total armed (C_strict − A): "
                  f"**{fmt_d(s_c_strict['sum'] - s_a['sum'])}**")
    lines.append("")

    # ---- Verdict ----
    lines.append("## Verdict")
    lines.append("")
    if delta_a_to_c_strict > 30:
        lines.append("✅ **Implementation semantics are the root "
                     "cause.** Switching from reactive market exit "
                     "(Version A) to a true resting stop (Version "
                     f"C_strict) recovers ~{fmt_d(delta_a_to_c_strict)} "
                     "per armed trade. The HH/LL rule is not dead; "
                     "the implementation needs to use a real STOP_"
                     "MARKET order placed at arm time. NEXT: "
                     "implement Version B in NT (handle "
                     "'in-market' rejections via immediate market "
                     "exit at current price). The realistic best-"
                     "case (C_realistic) gives a fair lower bound: "
                     f"+{fmt_d(delta_a_to_c_real)}/trade.")
    elif delta_a_to_c_real > 5:
        lines.append("⚠️ **Mixed result.** C_strict is much better "
                     "than A, but C_realistic (more honest) shows "
                     "a smaller improvement. Real fills will be "
                     "between the two; LIMIT orders at protect_px "
                     "or N-tick confirmation may be appropriate.")
    else:
        lines.append("❌ **Rule is bad regardless of implementation.** "
                     "Even with a perfect resting stop fill at "
                     "protect_px, economics are essentially "
                     "unchanged from reactive market exit. "
                     "Confirms tape-replay was wrong — the rule "
                     "doesn't capture real edge.")
    lines.append("")
    lines.append("## Files")
    lines.append("")
    lines.append("- Per-trade audit: `studies/v_a_exit_recon/results/hhll_attribution_audit.parquet`")
    lines.append("- This report: `studies/v_a_exit_recon/results/HHLL_ATTRIBUTION_AUDIT.md`")

    out_p = OUT / "HHLL_ATTRIBUTION_AUDIT.md"
    out_p.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport: {out_p}")


if __name__ == "__main__":
    main()
