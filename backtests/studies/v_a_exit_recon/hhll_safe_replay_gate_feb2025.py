"""HH/LL Safe Replay Gate — Feb 2025 RTH only.

Gate sequence (mandatory before any expansion beyond Feb):
  1. Run `replay_family_c_safe` with `C_lock50_30s_5` params on Feb
     2025 RTH trades (using utils/safe_replay framework)
  2. Audit output with `audit_trades` — MUST report 0 impossible fills
  3. Per-trade compare patched replay vs tick-NT runtime
  4. Hard-fail unless |median diff| < $5/trade and impossible_fills == 0
  5. Only report economics if gate passes

Inputs:
  collectors/collector_v2/results/with_tape/NQ_2025/{trades,trade_tape}.parquet
  collectors/collector_v2/results/tick_nt/hhll_FebSep_audit_*/trades.parquet

Outputs:
  studies/v_a_exit_recon/results/safe_gate_feb2025/
    safe_replay_trades.parquet
    audit_result.json
    per_trade_diff.parquet
    GATE_REPORT.md
"""

from __future__ import annotations
import os, sys, json
from pathlib import Path
from dataclasses import asdict
import numpy as np
import pandas as pd
import pytz

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

from studies.v_a_exit_recon.hhll_progression import (
    precompute_progression, replay_family_c_safe,
)
from utils.audit_replay_fills import audit_trades, AuditConfig

CT = pytz.timezone("America/Chicago")
PORT = Path("collectors/collector_v2/results/with_tape")
TICK_NT = Path("collectors/collector_v2/results/tick_nt")
OUT = Path("studies/v_a_exit_recon/results/safe_gate_feb2025")
OUT.mkdir(parents=True, exist_ok=True)

NQ_MULT = 20.0
COST_RT = 10.0
GATE_MEDIAN_HARD_FAIL = 5.0   # $/trade
GATE_MEAN_SOFT_WARN = 5.0     # $/trade


def fmt_d(v):
    if v is None or (isinstance(v, float)
                       and (pd.isna(v) or np.isinf(v))):
        return "—"
    return f"${v:,.2f}" if abs(v) < 1000 else f"${v:,.0f}"


def main():
    feb_start = pd.Timestamp("2025-02-01", tz="UTC").value
    mar_start = pd.Timestamp("2025-03-01", tz="UTC").value

    print("=" * 70)
    print("HH/LL Safe Replay Gate — Feb 2025 RTH")
    print("=" * 70)

    # ---- Load 2025 tape & trades ----
    print("\n[1/6] Loading 2025 with_tape data...")
    trades_all = pd.read_parquet(PORT / "NQ_2025/trades.parquet")
    tape_all = pd.read_parquet(PORT / "NQ_2025/trade_tape.parquet")
    print(f"  total trades={len(trades_all):,}, "
          f"tape rows={len(tape_all):,}")

    # ---- Filter Feb 2025 RTH ----
    rth = trades_all[trades_all["session"] == "RTH"].copy()
    feb = rth[(rth["entry_ts"] >= feb_start)
               & (rth["entry_ts"] < mar_start)].copy()
    feb["trade_id"] = feb["decision_event_id"] + 2025 * 1_000_000
    feb["baseline_net_pnl"] = feb["net_pnl"]
    feb_ids = set(feb["decision_event_id"])
    feb_tape = tape_all[
        tape_all["decision_event_id"].isin(feb_ids)].copy()
    feb_tape["trade_id"] = (feb_tape["decision_event_id"]
                                + 2025 * 1_000_000)
    print(f"  Feb 2025 RTH: trades={len(feb)}, "
          f"tape rows={len(feb_tape):,}")

    # ---- Precompute progression on Feb tape ----
    print("\n[2/6] Precomputing progression columns on tape...")
    feb_tape = precompute_progression(feb_tape)
    print(f"  added cols: bars_since_new_1s, "
          f"bars_since_new_5s_buckets, bars_since_new_30s_buckets")

    # ---- Run safe replay (C_lock50_30s_5) ----
    print("\n[3/6] Running replay_family_c_safe (C_lock50_30s_5, "
          "defaults: conservative_ohlc / at_or_worse_close / "
          "market_exit_now)...")
    safe_trades = replay_family_c_safe(
        trades=feb, tape=feb_tape,
        granularity_col="bars_since_new_30s_buckets",
        stall_bars=5, lock_pct=0.50, min_mfe_atr=1.0,
        fill_model="conservative_ohlc",
        ohlc_convention="at_or_worse_close",
        invalid_stop_policy="market_exit_now",
    )
    safe_trades.to_parquet(
        OUT / "safe_replay_trades.parquet", index=False)
    print(f"  output trades: {len(safe_trades)}")
    n_fired = int(safe_trades["fired_rule"].sum())
    print(f"  fired_rule=True: {n_fired} "
          f"({100*n_fired/max(1,len(safe_trades)):.1f}%)")
    if "hhll_stop_invalid_at_arm" in safe_trades.columns:
        n_invalid = int(
            safe_trades["hhll_stop_invalid_at_arm"]
            .fillna(False).sum())
        print(f"  stop_invalid_at_arm: {n_invalid} "
              f"(market_exit_now policy applied)")

    # ---- Build bars_lookup_fn from tape ----
    # The tape carries (ts_init, h, l, c) at every 1s bar a trade
    # was active in. OHLC at a given ts_init is the same across
    # trades, so dedup is safe.
    print("\n[4/6] Building bars_lookup_fn from tape "
          "(ts_init -> OHLC)...")
    ohlc_lookup = (
        feb_tape[["ts_init", "h", "l", "c"]]
        .drop_duplicates(subset="ts_init", keep="first")
        .set_index("ts_init"))
    print(f"  unique ts_init bars in lookup: {len(ohlc_lookup):,}")

    def bars_lookup_fn(ts_ns: int):
        if ts_ns not in ohlc_lookup.index:
            return None
        row = ohlc_lookup.loc[ts_ns]
        # Tape doesn't expose OPEN, but audit only uses high/low.
        return (float(row["c"]), float(row["h"]),
                float(row["l"]), float(row["c"]))

    # ---- Run audit (hard-fail mode) ----
    print("\n[5/6] Running audit_trades (hard-fail mode)...")
    audit_cfg = AuditConfig(hard_fail_on_impossible=True)
    audit_failed = False
    audit_err_msg = None
    try:
        audit_result = audit_trades(
            safe_trades, bars_lookup_fn, audit_cfg)
        print("  AUDIT PASSED — 0 impossible fills detected.")
    except RuntimeError as e:
        audit_failed = True
        audit_err_msg = str(e)
        # Re-run in soft mode to get the breakdown
        audit_cfg_soft = AuditConfig(
            hard_fail_on_impossible=False)
        audit_result = audit_trades(
            safe_trades, bars_lookup_fn, audit_cfg_soft)
        print(f"  AUDIT FAILED: {audit_err_msg}")
        print(f"  Continuing in soft mode for diagnostics...")

    audit_summary = dict(audit_result.summary)
    audit_summary["flags"] = {
        k: v.to_dict() for k, v in audit_result.flags.items()}
    with (OUT / "audit_result.json").open("w") as f:
        json.dump(audit_summary, f, indent=2, default=float)

    # ---- Per-trade comparison vs tick-NT ----
    print("\n[6/6] Per-trade comparison vs tick-NT runtime...")
    runs = sorted(TICK_NT.glob("hhll_FebSep_audit*"))
    if not runs:
        print("  ERROR: no hhll_FebSep_audit* dirs in TICK_NT")
        sys.exit(2)
    ticknt = pd.read_parquet(runs[-1] / "trades.parquet")
    ticknt_feb = ticknt[
        (ticknt["session"] == "RTH")
        & (ticknt["entry_ts"] >= feb_start)
        & (ticknt["entry_ts"] < mar_start)].copy()
    print(f"  tick-NT Feb RTH trades: {len(ticknt_feb)}")

    # Match on entry_ts
    safe_idx = safe_trades.set_index("entry_ts")
    tick_idx = ticknt_feb.set_index("entry_ts")
    common = set(safe_idx.index) & set(tick_idx.index)
    print(f"  common entry_ts (matched): {len(common)}")

    rows = []
    for ts in sorted(common):
        s = safe_idx.loc[ts]
        n = tick_idx.loc[ts]
        if isinstance(s, pd.DataFrame): s = s.iloc[0]
        if isinstance(n, pd.DataFrame): n = n.iloc[0]
        rows.append({
            "entry_ts": int(ts),
            "direction": int(s["direction"]),
            "fill_price_safe": float(s["fill_price"]),
            "fill_price_tick": float(n["fill_price"]),
            "exit_price_safe": float(s["exit_price"]),
            "exit_price_tick": float(n["exit_price"]),
            "exit_ts_safe": int(s["exit_ts"]),
            "exit_ts_tick": int(n["exit_ts"]),
            "exit_reason_safe": str(s["exit_reason"]),
            "exit_reason_tick": str(n["exit_reason"]),
            "fired_rule_safe": bool(s["fired_rule"]),
            "tick_hhll_armed": bool(
                n.get("hhll_armed", False)),
            "net_pnl_safe": float(s["net_pnl"]),
            "net_pnl_tick": float(n["net_pnl"]),
            "pnl_diff_safe_minus_tick": (
                float(s["net_pnl"]) - float(n["net_pnl"])),
            "stop_invalid_at_arm": (
                bool(s["hhll_stop_invalid_at_arm"])
                if "hhll_stop_invalid_at_arm" in s.index
                and pd.notna(s.get("hhll_stop_invalid_at_arm"))
                else False),
            "fill_outside_arm_bar_ohlc": (
                bool(s["hhll_fill_outside_arm_bar_ohlc"])
                if "hhll_fill_outside_arm_bar_ohlc" in s.index
                and pd.notna(s.get("hhll_fill_outside_arm_bar_ohlc"))
                else False),
        })
    diff = pd.DataFrame(rows)
    diff.to_parquet(OUT / "per_trade_diff.parquet", index=False)

    if not len(diff):
        print("  WARN: no matched trades.")
        median_diff = mean_diff = float("nan")
    else:
        median_diff = float(diff["pnl_diff_safe_minus_tick"].median())
        mean_diff = float(diff["pnl_diff_safe_minus_tick"].mean())
        sum_diff = float(diff["pnl_diff_safe_minus_tick"].sum())
        print(f"  matched n={len(diff)}")
        print(f"  median (safe - tick) = "
              f"{fmt_d(median_diff)}/trade")
        print(f"  mean   (safe - tick) = "
              f"{fmt_d(mean_diff)}/trade")
        print(f"  sum    (safe - tick) = {fmt_d(sum_diff)}")

    # ---- Gate decision ----
    print("\n" + "=" * 70)
    print("GATE DECISION")
    print("=" * 70)
    impossible_n = audit_result.impossible_fills_n
    median_ok = (not pd.isna(median_diff)
                  and abs(median_diff) <= GATE_MEDIAN_HARD_FAIL)
    audit_ok = (impossible_n == 0)
    gate_passed = audit_ok and median_ok
    mean_warn = (not pd.isna(mean_diff)
                  and abs(mean_diff) > GATE_MEAN_SOFT_WARN)

    print(f"  Impossible fills: {impossible_n} "
          f"{'OK' if audit_ok else 'FAIL (must be 0)'}")
    print(f"  |Median diff| ≤ ${GATE_MEDIAN_HARD_FAIL:.2f}/trade: "
          f"{'OK' if median_ok else 'FAIL'} "
          f"(actual {fmt_d(median_diff)}/trade)")
    if mean_warn:
        print(f"  WARN: |Mean diff| > ${GATE_MEAN_SOFT_WARN:.2f}"
              f"/trade (actual {fmt_d(mean_diff)})")
    print()
    if gate_passed:
        print("  >>> GATE PASSED — safe to report Feb economics <<<")
    else:
        print("  >>> GATE FAILED — DO NOT report economics <<<")

    # ---- Markdown report ----
    print("\nWriting GATE_REPORT.md...")
    lines = []
    lines.append("# HH/LL Safe Replay Gate — Feb 2025 RTH")
    lines.append("")
    lines.append(f"Run: {pd.Timestamp.now(tz='UTC').isoformat()}")
    lines.append("")
    lines.append("## Configuration")
    lines.append("")
    lines.append("- Rule: `C_lock50_30s_5` "
                  "(stall_bars=5, lock_pct=0.50, min_mfe_atr=1.0, "
                  "granularity=30s buckets)")
    lines.append("- Framework: `utils/safe_replay`")
    lines.append("- fill_model: `conservative_ohlc`")
    lines.append("- ohlc_convention: `at_or_worse_close`")
    lines.append("- invalid_stop_policy: `market_exit_now`")
    lines.append("")
    lines.append("## Gate Result")
    lines.append("")
    lines.append(f"- **Audit (impossible fills): "
                  f"{'PASS' if audit_ok else 'FAIL'}** "
                  f"({impossible_n} impossible fills)")
    lines.append(f"- **Median diff vs tick-NT: "
                  f"{'PASS' if median_ok else 'FAIL'}** "
                  f"({fmt_d(median_diff)}/trade, threshold ±$"
                  f"{GATE_MEDIAN_HARD_FAIL:.2f})")
    if mean_warn:
        lines.append(f"- WARN: |mean diff| > "
                     f"${GATE_MEAN_SOFT_WARN:.2f} "
                     f"(actual {fmt_d(mean_diff)})")
    lines.append("")
    lines.append(f"### **Overall: "
                  f"{'PASS' if gate_passed else 'FAIL'}**")
    lines.append("")

    lines.append("## Audit detail")
    lines.append("")
    lines.append(audit_result.as_markdown())
    lines.append("")

    lines.append("## Replay vs tick-NT diff stats")
    lines.append("")
    if len(diff):
        lines.append(f"- Matched trades: **{len(diff)}**")
        lines.append(f"- Sum diff (safe - tick): "
                      f"**{fmt_d(diff['pnl_diff_safe_minus_tick'].sum())}**")
        lines.append(f"- Median diff: "
                      f"**{fmt_d(median_diff)}/trade**")
        lines.append(f"- Mean diff: **{fmt_d(mean_diff)}/trade**")
        lines.append(f"- Std: "
                      f"{fmt_d(float(diff['pnl_diff_safe_minus_tick'].std()))}")
        # Quantiles
        q = diff['pnl_diff_safe_minus_tick'].quantile(
            [0.05, 0.25, 0.50, 0.75, 0.95])
        lines.append("")
        lines.append("| Quantile | $/trade |")
        lines.append("|---|--:|")
        for k, v in q.items():
            lines.append(f"| p{int(100*k)} | {fmt_d(v)} |")
        lines.append("")

        # Stop-invalid-at-arm cases
        n_inv = int(diff["stop_invalid_at_arm"].sum())
        if n_inv:
            lines.append(f"### Stop-invalid-at-arm cases: {n_inv}")
            lines.append("")
            sub = diff[diff["stop_invalid_at_arm"]]
            lines.append(f"- mean diff in this subset: "
                          f"{fmt_d(sub['pnl_diff_safe_minus_tick'].mean())}/trade")
            lines.append(f"- sum: "
                          f"{fmt_d(sub['pnl_diff_safe_minus_tick'].sum())}")
            lines.append("")
    else:
        lines.append("- No matched trades.")
        lines.append("")

    lines.append("## Per-rule headline economics")
    lines.append("")
    if gate_passed:
        n = len(safe_trades)
        sum_pnl = float(safe_trades["net_pnl"].sum())
        mean_pnl = float(safe_trades["net_pnl"].mean())
        median_pnl = float(safe_trades["net_pnl"].median())
        wr = float((safe_trades["net_pnl"] > 0).mean())
        n_baseline = float(
            safe_trades["baseline_net_pnl"].sum())
        delta = sum_pnl - n_baseline
        lines.append(f"- n={n}, sum {fmt_d(sum_pnl)}, "
                      f"mean {fmt_d(mean_pnl)}/trade, "
                      f"median {fmt_d(median_pnl)}/trade, "
                      f"WR {100*wr:.1f}%")
        lines.append(f"- vs baseline (regime exit): sum "
                      f"{fmt_d(n_baseline)}, "
                      f"delta {fmt_d(delta)}")
    else:
        lines.append("- WITHHELD — gate did not pass.")
    lines.append("")

    (OUT / "GATE_REPORT.md").write_text(
        "\n".join(lines), encoding="utf-8")
    print(f"\nReport: {OUT / 'GATE_REPORT.md'}")

    sys.exit(0 if gate_passed else 1)


if __name__ == "__main__":
    main()
