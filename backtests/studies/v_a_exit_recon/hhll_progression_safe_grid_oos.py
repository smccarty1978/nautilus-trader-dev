"""HH/LL Progression Safe Replay — OOS expansion 2020-2023.

Triggered ONLY if any rule survived in IS 2024-2026 (see
hhll_progression_safe_grid.py). Runs the same primary-mode safe
replay on 2020-2023 RTH and reports per-year vs baseline.

Usage:
  python studies/v_a_exit_recon/hhll_progression_safe_grid_oos.py \
    --rules A_stall_30s_5,B_be_30s_3   # comma-separated rule names

If --rules is omitted, runs the entire 36-rule grid OOS.

Outputs:
  studies/v_a_exit_recon/results/safe_grid_oos/
    trades_<rule>.parquet
    grid_summary_oos.parquet
    GRID_REPORT_OOS.md
"""

from __future__ import annotations
import os, sys, time, argparse
from pathlib import Path
import numpy as np
import pandas as pd
import pytz

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

from studies.v_a_exit_recon.hhll_progression import (
    precompute_progression,
    replay_family_a, replay_family_b_safe, replay_family_c_safe,
    _use_original, stats, fmt_d, fmt_p, fmt_pf,
)
from studies.v_a_exit_recon.hhll_progression_safe_grid import (
    GRANULARITIES, A_STALLS, B_STALLS, C_STALLS, C_LOCK_PCTS,
    build_bars_lookup, run_rule, per_year_stats, safe_bool_col,
)
from utils.audit_replay_fills import audit_trades, AuditConfig

CT = pytz.timezone("America/Chicago")
PORT = Path("collectors/collector_v2/results/with_tape")
OUT = Path("studies/v_a_exit_recon/results/safe_grid_oos")
OUT.mkdir(parents=True, exist_ok=True)

OOS_YEARS = [2020, 2021, 2022, 2023]


def load_oos_years():
    all_trades = []; all_tape = []
    for yr in OOS_YEARS:
        d = PORT / f"NQ_{yr}"
        if not d.exists():
            print(f"  WARN: {d} missing, skip year {yr}")
            continue
        trades = pd.read_parquet(d / "trades.parquet")
        tape = pd.read_parquet(d / "trade_tape.parquet")
        rth = trades[trades["session"] == "RTH"].copy()
        rth_ids = set(rth["decision_event_id"])
        tape_rth = tape[
            tape["decision_event_id"].isin(rth_ids)].copy()
        OFFSET = yr * 1_000_000
        rth["trade_id"] = rth["decision_event_id"] + OFFSET
        tape_rth["trade_id"] = (
            tape_rth["decision_event_id"] + OFFSET)
        rth["baseline_net_pnl"] = rth["net_pnl"]
        all_trades.append(rth)
        all_tape.append(tape_rth)
        print(f"  NQ {yr}: {len(rth):,} RTH trades, "
              f"{len(tape_rth):,} tape rows")
    return (pd.concat(all_trades, ignore_index=True),
              pd.concat(all_tape, ignore_index=True))


def build_grid(rule_filter: list | None = None):
    grid = []
    for col, label in GRANULARITIES:
        for stall in A_STALLS:
            grid.append({
                "name": f"A_stall_{label}_{stall}",
                "family": "A", "col": col, "stall": stall,
                "lock": None})
    for col, label in GRANULARITIES[1:]:
        for stall in B_STALLS[label]:
            grid.append({
                "name": f"B_be_{label}_{stall}",
                "family": "B", "col": col, "stall": stall,
                "lock": None})
    for col, label in GRANULARITIES[1:]:
        for stall in C_STALLS[label]:
            for lock in C_LOCK_PCTS:
                grid.append({
                    "name": (f"C_lock{int(lock*100)}_"
                             f"{label}_{stall}"),
                    "family": "C", "col": col, "stall": stall,
                    "lock": lock})
    if rule_filter:
        grid = [r for r in grid if r["name"] in rule_filter]
    return grid


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--rules", type=str, default=None,
        help="Comma-separated rule names (default: full grid)")
    args = ap.parse_args()
    rule_filter = (args.rules.split(",")
                       if args.rules else None)

    t0 = time.time()
    print("=" * 70)
    print("HH/LL Progression Safe Replay — OOS 2020-2023")
    print("=" * 70)

    print("\nLoading OOS trades + tape...")
    trades, tape = load_oos_years()
    print(f"Total OOS: {len(trades):,} trades")
    print("\nPrecomputing progression...")
    tape = precompute_progression(tape)
    print("\nBuilding bars_lookup_fn...")
    bars_lookup_fn = build_bars_lookup(tape)
    base_pnl_by_id = trades.set_index(
        "trade_id")["baseline_net_pnl"].to_dict()

    # Baseline
    print("\nBaseline (regime exit) reference...")
    base_rows = [_use_original(t) for _, t in trades.iterrows()]
    base_df = pd.DataFrame(base_rows)
    base_df["baseline_net_pnl"] = base_df["trade_id"].map(
        base_pnl_by_id)
    base_summary_oos = _per_year_stats_oos(
        "BASELINE_regime", base_df, base_pnl_by_id)
    print(f"  baseline OOS: n={base_summary_oos['all_n']:,}, "
          f"total={fmt_d(base_summary_oos['all_total'])}")

    # Grid
    grid = build_grid(rule_filter)
    print(f"\nGrid: {len(grid)} rules")
    summaries = [base_summary_oos]
    audits = []
    fail_rules = []
    for i, r in enumerate(grid, 1):
        st = time.time()
        df = run_rule(r["family"], r["name"], trades, tape,
                          r["col"], r["stall"], r["lock"])
        if "baseline_net_pnl" not in df.columns or df[
                "baseline_net_pnl"].isna().any():
            df["baseline_net_pnl"] = df["trade_id"].map(
                base_pnl_by_id)
        df.to_parquet(OUT / f"trades_{r['name']}.parquet",
                          index=False)
        ar = audit_trades(df, bars_lookup_fn,
                                AuditConfig(
                                    hard_fail_on_impossible=False))
        if ar.has_impossible_fills:
            fail_rules.append(r["name"])
        audits.append({"rule": r["name"],
                            "n": len(df),
                            "impossible": ar.impossible_fills_n})
        summaries.append(_per_year_stats_oos(
            r["name"], df, base_pnl_by_id))
        elapsed = time.time() - st
        n_fired = int(df["fired_rule"].sum())
        print(f"  [{i:2d}/{len(grid)}] {r['name']:<30} "
              f"n={len(df):,} fired={n_fired:,} "
              f"imposs={ar.impossible_fills_n} ({elapsed:.1f}s)")

    summ_df = pd.DataFrame(summaries)
    summ_df.to_parquet(OUT / "grid_summary_oos.parquet",
                              index=False)

    print(f"\nAudit verdict: "
          f"{'FAIL' if fail_rules else 'PASS'}")

    # ---- Survivors OOS ----
    base_total = base_summary_oos["all_total"]
    surviving = [s for s in summaries[1:]
                    if s["all_total"] is not None
                    and s["all_total"] > base_total]
    print(f"\nOOS Survivors (beat baseline {fmt_d(base_total)}): "
          f"{len(surviving)}")
    for s in surviving:
        print(f"  {s['rule']}: total {fmt_d(s['all_total'])}, "
              f"delta +{fmt_d(s['all_vs_base_total'])}")

    # ---- Markdown ----
    lines = []
    lines.append("# HH/LL Progression Safe Replay — OOS 2020-2023")
    lines.append("")
    lines.append(f"Run: {pd.Timestamp.now(tz='UTC').isoformat()}")
    lines.append("")
    lines.append(f"- Span: NQ RTH {OOS_YEARS[0]}-{OOS_YEARS[-1]}")
    lines.append(f"- Population: {base_summary_oos['all_n']:,} V_A trades")
    lines.append(f"- Audit: "
                  f"{'FAIL' if fail_rules else 'PASS'} "
                  f"({len(fail_rules)} rules with phantom fills)")
    lines.append("")
    lines.append(f"## Baseline OOS")
    lines.append("")
    lines.append(f"- Total: **{fmt_d(base_total)}**")
    lines.append(f"- Mean: {fmt_d(base_summary_oos['all_mean'])}/trade")
    lines.append(f"- PF: {fmt_pf(base_summary_oos['all_pf'])}")
    lines.append(f"- WR: {fmt_p(base_summary_oos['all_wr'])}")
    lines.append("")
    lines.append("## OOS Survivors")
    lines.append("")
    if not surviving:
        lines.append("**No rule beats baseline OOS.**")
    else:
        lines.append("| Rule | Total | vs Base | Mean | PF | WR |")
        lines.append("|---|--:|--:|--:|--:|--:|")
        for s in surviving:
            lines.append(
                f"| `{s['rule']}` | "
                f"{fmt_d(s['all_total'])} | "
                f"+{fmt_d(s['all_vs_base_total'])} | "
                f"{fmt_d(s['all_mean'])} | "
                f"{fmt_pf(s['all_pf'])} | "
                f"{fmt_p(s['all_wr'])} |")
    lines.append("")
    lines.append("## Per-rule per-year totals")
    lines.append("")
    yr_cols = " | ".join(
        f"{yr} total" for yr in OOS_YEARS)
    lines.append(f"| Rule | All total | vs Base | {yr_cols} |")
    lines.append("|" + "|".join(["---"] * (3 + len(OOS_YEARS)))
                  + "|")
    for s in summaries:
        if s["rule"] == "BASELINE_regime":
            yr_str = " | ".join(
                fmt_d(s.get(f"y{yr}_total"))
                for yr in OOS_YEARS)
            lines.append(
                f"| **`{s['rule']}`** | "
                f"**{fmt_d(s['all_total'])}** | (base) | "
                f"{yr_str} |")
        else:
            yr_str = " | ".join(
                fmt_d(s.get(f"y{yr}_total"))
                for yr in OOS_YEARS)
            delta = s.get("all_vs_base_total", 0.0)
            sign = "+" if delta >= 0 else ""
            lines.append(
                f"| `{s['rule']}` | "
                f"{fmt_d(s['all_total'])} | "
                f"{sign}{fmt_d(delta)} | "
                f"{yr_str} |")
    lines.append("")
    (OUT / "GRID_REPORT_OOS.md").write_text(
        "\n".join(lines), encoding="utf-8")
    print(f"\nReport: {OUT / 'GRID_REPORT_OOS.md'}")
    print(f"Done. Total: {(time.time() - t0)/60:.1f} min")
    return 0 if not fail_rules else 1


def _per_year_stats_oos(name, df, base_pnl_by_id):
    """Mirror of per_year_stats() but with OOS year set."""
    out = {"rule": name}
    df = df.copy()
    df["year"] = df["entry_ts"].apply(
        lambda ts: pd.Timestamp(int(ts), tz="UTC")
        .tz_convert(CT).year)
    if "baseline_net_pnl" not in df.columns or df[
            "baseline_net_pnl"].isna().any():
        df["baseline_net_pnl"] = df["trade_id"].map(
            base_pnl_by_id).astype(float)
    for yr in OOS_YEARS:
        sub = df[df["year"] == yr]
        s = stats(sub["net_pnl"])
        out[f"y{yr}_n"] = s.get("n", 0)
        out[f"y{yr}_mean"] = s.get("mean")
        out[f"y{yr}_total"] = s.get("sum")
        out[f"y{yr}_pf"] = s.get("pf")
        out[f"y{yr}_wr"] = s.get("wr")
    s_all = stats(df["net_pnl"])
    out["all_n"] = s_all.get("n", 0)
    out["all_mean"] = s_all.get("mean")
    out["all_total"] = s_all.get("sum")
    out["all_pf"] = s_all.get("pf")
    out["all_wr"] = s_all.get("wr")
    out["pct_fired"] = float(df["fired_rule"].mean())
    inv = safe_bool_col(df, "hhll_stop_invalid_at_arm")
    out["pct_invalid_at_arm"] = float(inv.mean())
    out["all_vs_base_total"] = float(
        df["net_pnl"].sum() - df["baseline_net_pnl"].sum())
    out["all_vs_base_mean"] = float(
        (df["net_pnl"] - df["baseline_net_pnl"]).mean())
    return out


if __name__ == "__main__":
    sys.exit(main())
