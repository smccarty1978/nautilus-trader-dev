"""HH/LL Progression Safe Replay Re-Test — full 36-rule grid.

Re-runs the original `hhll_progression.py` 36-rule grid through the
Safe Exit Replay Framework (utils/safe_replay). Question:

  After removing phantom fills, does any HH/LL progression exit
  still survive vs baseline regime exit?

Grid (unchanged from HHLL_PROGRESSION_REPORT.md):
  Family A: stall exit (bar close)
    granularities {1s, 5s, 30s} × stalls {5, 10, 20, 30}      = 12
  Family B: move-to-BE after stall
    granularities {5s, 30s} × stalls (5s:{5,10,20}, 30s:{2,3,5}) = 6
  Family C: lock pct of MFE after stall
    same as B × lock_pcts {0.0, 0.25, 0.50}                       = 18
                                                          total = 36

Family A exits at bar close (already inside OHLC by construction).
Families B and C use replay_family_b_safe / replay_family_c_safe.

Primary economics (executable mode):
  fill_model = conservative_ohlc
  ohlc_convention = at_or_worse_close
  invalid_stop_policy = market_exit_now

Diagnostic sensitivity (reported but not primary):
  ohlc_convention = worst_in_bar
  invalid_stop_policy = skip_rule_and_hold

Data: NQ RTH 2024+2025+2026 (IS span). If any rule survives, expand
to 2020-2023 OOS (out of scope for this script — handled separately).

Outputs:
  studies/v_a_exit_recon/results/safe_grid/
    trades_<rule>.parquet         (one per rule, primary mode)
    sensitivity_<rule>.parquet    (only for representative subset)
    audit_summary.parquet         (per-rule audit results)
    grid_summary.parquet          (per-rule per-year stats)
    GRID_REPORT.md
"""

from __future__ import annotations
import os, sys, json, time
from pathlib import Path
import numpy as np
import pandas as pd
import pytz

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

from studies.v_a_exit_recon.hhll_progression import (
    load_3_years, precompute_progression,
    replay_family_a, replay_family_b_safe, replay_family_c_safe,
    _use_original, stats, mfe_capture_ratio, fmt_d, fmt_p, fmt_pf,
)
from utils.audit_replay_fills import audit_trades, AuditConfig

CT = pytz.timezone("America/Chicago")
OUT_BASE = Path("studies/v_a_exit_recon/results")
OUT = OUT_BASE / "safe_grid"
OUT.mkdir(parents=True, exist_ok=True)

NQ_MULT = 20.0
COST_RT = 10.0
YEARS = [2024, 2025, 2026]


# ---------------- Grid spec ----------------
GRANULARITIES = [
    ("bars_since_new_1s", "1s"),
    ("bars_since_new_5s_buckets", "5s"),
    ("bars_since_new_30s_buckets", "30s"),
]
A_STALLS = [5, 10, 20, 30]
B_STALLS = {"5s": [5, 10, 20], "30s": [2, 3, 5]}
C_STALLS = {"5s": [5, 10, 20], "30s": [2, 3, 5]}
C_LOCK_PCTS = [0.0, 0.25, 0.50]

# Diagnostic sensitivity: rerun a single representative rule with
# alternative settings to bound the dependence.
SENSITIVITY_RULES = [
    ("C_lock50_30s_5", "C", "bars_since_new_30s_buckets", 5, 0.50),
    ("C_lock25_30s_3", "C", "bars_since_new_30s_buckets", 3, 0.25),
    ("B_be_30s_5",      "B", "bars_since_new_30s_buckets", 5, None),
]


def build_bars_lookup(tape: pd.DataFrame):
    """Build ts_init -> (open_proxy, h, l, c) lookup from tape.
    The tape carries bar OHLC at every 1s; OHLC at a given ts_init is
    the same across trades, so dedup is safe.
    """
    ohlc = (tape[["ts_init", "h", "l", "c"]]
            .drop_duplicates(subset="ts_init", keep="first")
            .set_index("ts_init"))
    print(f"  bars_lookup_fn: {len(ohlc):,} unique ts_init bars")
    def lookup(ts_ns: int):
        if ts_ns not in ohlc.index:
            return None
        row = ohlc.loc[ts_ns]
        return (float(row["c"]), float(row["h"]),
                float(row["l"]), float(row["c"]))
    return lookup


def run_rule(family: str, name: str, trades: pd.DataFrame,
                tape: pd.DataFrame, granularity_col: str,
                stall_bars: int, lock_pct: float | None,
                fill_model: str = "conservative_ohlc",
                ohlc_convention: str = "at_or_worse_close",
                invalid_stop_policy: str = "market_exit_now",
                ) -> pd.DataFrame:
    if family == "A":
        df = replay_family_a(trades, tape, granularity_col,
                                stall_bars)
    elif family == "B":
        df = replay_family_b_safe(
            trades, tape, granularity_col, stall_bars,
            fill_model=fill_model,
            ohlc_convention=ohlc_convention,
            invalid_stop_policy=invalid_stop_policy)
    elif family == "C":
        df = replay_family_c_safe(
            trades, tape, granularity_col, stall_bars,
            lock_pct=lock_pct,
            fill_model=fill_model,
            ohlc_convention=ohlc_convention,
            invalid_stop_policy=invalid_stop_policy)
    else:
        raise ValueError(family)
    return df


def safe_bool_col(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series([False] * len(df), index=df.index)
    return df[col].apply(
        lambda v: bool(v) if pd.notna(v) else False)


def per_year_stats(name: str, df: pd.DataFrame,
                       baseline_pnl_by_id: dict) -> dict:
    out = {"rule": name}
    df = df.copy()
    df["year"] = df["entry_ts"].apply(
        lambda ts: pd.Timestamp(int(ts), tz="UTC")
        .tz_convert(CT).year)
    if "baseline_net_pnl" not in df.columns or df[
            "baseline_net_pnl"].isna().any():
        df["baseline_net_pnl"] = (df["trade_id"].map(
            baseline_pnl_by_id)).astype(float)
    for yr in YEARS:
        sub = df[df["year"] == yr]
        s = stats(sub["net_pnl"])
        out[f"y{yr}_n"] = s.get("n", 0)
        out[f"y{yr}_mean"] = s.get("mean")
        out[f"y{yr}_pf"] = s.get("pf")
        out[f"y{yr}_total"] = s.get("sum")
        out[f"y{yr}_dd"] = s.get("max_dd")
        out[f"y{yr}_wr"] = s.get("wr")
        # vs baseline
        bsub = sub["baseline_net_pnl"]
        if len(sub):
            out[f"y{yr}_vs_base_total"] = float(
                sub["net_pnl"].sum() - bsub.sum())
            out[f"y{yr}_vs_base_mean"] = float(
                (sub["net_pnl"] - bsub).mean())
        else:
            out[f"y{yr}_vs_base_total"] = 0.0
            out[f"y{yr}_vs_base_mean"] = 0.0
    s_all = stats(df["net_pnl"])
    out["all_n"] = s_all.get("n", 0)
    out["all_mean"] = s_all.get("mean")
    out["all_pf"] = s_all.get("pf")
    out["all_total"] = s_all.get("sum")
    out["all_dd"] = s_all.get("max_dd")
    out["all_wr"] = s_all.get("wr")
    out["med_hold_s"] = float(df["hold_s"].median())
    out["pct_fired"] = float(df["fired_rule"].mean())
    inv = safe_bool_col(df, "hhll_stop_invalid_at_arm")
    out["pct_invalid_at_arm"] = float(inv.mean())
    if inv.any():
        out["invalid_market_exit_total_$"] = float(
            df.loc[inv, "net_pnl"].sum())
    else:
        out["invalid_market_exit_total_$"] = 0.0
    # vs baseline overall
    out["all_vs_base_total"] = float(
        df["net_pnl"].sum()
        - df["baseline_net_pnl"].sum())
    out["all_vs_base_mean"] = float(
        (df["net_pnl"] - df["baseline_net_pnl"]).mean())
    # Top-1% share
    s = df["net_pnl"].sort_values(ascending=False)
    top1 = s.head(max(1, int(len(s) * 0.01))).sum()
    total = s.sum()
    out["top1_share"] = (
        float(top1 / total) if total != 0 else float("nan"))
    return out


def main():
    t_start = time.time()
    print("=" * 70)
    print("HH/LL Progression Safe Replay Re-Test — IS 2024-2026")
    print("=" * 70)

    # ---- Load and prep ----
    print("\n[Step 1] Loading 3 years of trades + tape...")
    trades, tape = load_3_years()
    print(f"  total: {len(trades):,} trades, {len(tape):,} tape rows")
    print("\n[Step 2] Precomputing progression columns...")
    tape = precompute_progression(tape)
    print("  done")
    print("\n[Step 3] Building bars_lookup_fn for audit...")
    bars_lookup_fn = build_bars_lookup(tape)
    base_pnl_by_id = trades.set_index(
        "trade_id")["baseline_net_pnl"].to_dict()

    # ---- Baseline reference ----
    print("\n[Step 4] Baseline (regime exit) reference...")
    base_rows = [_use_original(t) for _, t in trades.iterrows()]
    base_df = pd.DataFrame(base_rows)
    # baseline_net_pnl needs to come back from the original trades
    base_df["baseline_net_pnl"] = base_df["trade_id"].map(
        base_pnl_by_id)
    base_df.to_parquet(OUT / "trades_BASELINE_regime.parquet",
                            index=False)
    base_summary = per_year_stats(
        "BASELINE_regime", base_df, base_pnl_by_id)
    print(f"  baseline: n={base_summary['all_n']:,}, "
          f"total={fmt_d(base_summary['all_total'])}, "
          f"mean={fmt_d(base_summary['all_mean'])}, "
          f"WR={fmt_p(base_summary['all_wr'])}")

    # ---- Build grid ----
    grid = []
    # Family A
    for col, label in GRANULARITIES:
        for stall in A_STALLS:
            grid.append({
                "name": f"A_stall_{label}_{stall}",
                "family": "A", "col": col, "stall": stall,
                "lock": None})
    # Family B
    for col, label in GRANULARITIES[1:]:
        for stall in B_STALLS[label]:
            grid.append({
                "name": f"B_be_{label}_{stall}",
                "family": "B", "col": col, "stall": stall,
                "lock": None})
    # Family C
    for col, label in GRANULARITIES[1:]:
        for stall in C_STALLS[label]:
            for lock in C_LOCK_PCTS:
                grid.append({
                    "name": f"C_lock{int(lock*100)}_{label}_{stall}",
                    "family": "C", "col": col, "stall": stall,
                    "lock": lock})
    print(f"\n[Step 5] Grid: {len(grid)} rules "
          f"({sum(1 for r in grid if r['family']=='A')} A + "
          f"{sum(1 for r in grid if r['family']=='B')} B + "
          f"{sum(1 for r in grid if r['family']=='C')} C)")

    # ---- Run + audit each rule ----
    print("\n[Step 6] Running primary mode (conservative_ohlc / "
          "at_or_worse_close / market_exit_now)...")
    summaries = [base_summary]
    audits = []
    audit_failed_rules = []
    for i, r in enumerate(grid, 1):
        t0 = time.time()
        df = run_rule(r["family"], r["name"], trades, tape,
                          r["col"], r["stall"], r["lock"])
        # baseline_net_pnl present from _finalize, but reconfirm
        if "baseline_net_pnl" not in df.columns or df[
                "baseline_net_pnl"].isna().any():
            df["baseline_net_pnl"] = df["trade_id"].map(
                base_pnl_by_id)
        df.to_parquet(OUT / f"trades_{r['name']}.parquet",
                          index=False)
        # Audit
        audit_cfg = AuditConfig(hard_fail_on_impossible=False)
        ar = audit_trades(df, bars_lookup_fn, audit_cfg)
        audit_row = {"rule": r["name"], "n": len(df),
                          "impossible_fills": ar.impossible_fills_n,
                          "impossible_fills_pnl": ar.impossible_fills_pnl,
                          **{f"flag_{k}_count": v.count
                              for k, v in ar.flags.items()}}
        audits.append(audit_row)
        if ar.has_impossible_fills:
            audit_failed_rules.append(r["name"])
        # Summary
        summaries.append(per_year_stats(r["name"], df,
                                              base_pnl_by_id))
        elapsed = time.time() - t0
        n_fired = int(df["fired_rule"].sum())
        n_inv = int(safe_bool_col(
            df, "hhll_stop_invalid_at_arm").sum())
        print(f"  [{i:2d}/{len(grid)}] {r['name']:<30} "
              f"n={len(df):,} fired={n_fired:,} "
              f"inv={n_inv:,} imposs={ar.impossible_fills_n} "
              f"({elapsed:.1f}s)")

    summ_df = pd.DataFrame(summaries)
    audit_df = pd.DataFrame(audits)
    summ_df.to_parquet(OUT / "grid_summary.parquet", index=False)
    audit_df.to_parquet(OUT / "audit_summary.parquet",
                              index=False)

    print("\n[Step 7] Audit verdict")
    if audit_failed_rules:
        print(f"  FAIL — {len(audit_failed_rules)} rules with "
              f"impossible fills:")
        for n in audit_failed_rules: print(f"    {n}")
    else:
        print("  PASS — 0 impossible fills across all "
              f"{len(grid)} rules")

    # ---- Diagnostic sensitivity ----
    print("\n[Step 8] Diagnostic sensitivity on selected rules...")
    sens_rows = []
    for srule in SENSITIVITY_RULES:
        name, fam, col, stall, lock = srule
        for sens_label, sens_kwargs in [
            ("worst_in_bar", {
                "ohlc_convention": "worst_in_bar",
                "invalid_stop_policy": "market_exit_now"}),
            ("skip_rule_and_hold", {
                "ohlc_convention": "at_or_worse_close",
                "invalid_stop_policy": "skip_rule_and_hold"}),
        ]:
            df = run_rule(fam, name, trades, tape, col, stall,
                              lock, **sens_kwargs)
            if "baseline_net_pnl" not in df.columns or df[
                    "baseline_net_pnl"].isna().any():
                df["baseline_net_pnl"] = df["trade_id"].map(
                    base_pnl_by_id)
            df.to_parquet(
                OUT / f"sensitivity_{name}_{sens_label}.parquet",
                index=False)
            s = per_year_stats(
                f"{name}__{sens_label}", df, base_pnl_by_id)
            sens_rows.append(s)
            print(f"  {name} [{sens_label}]: total "
                  f"{fmt_d(s['all_total'])}, mean "
                  f"{fmt_d(s['all_mean'])}/trade")
    sens_df = pd.DataFrame(sens_rows)
    sens_df.to_parquet(OUT / "sensitivity_summary.parquet",
                              index=False)

    # ---- Old vs new comparison ----
    print("\n[Step 9] Loading OLD phantom-replay results...")
    old_compare = []
    for r in grid:
        old_p = OUT_BASE / f"trades_{r['name']}.parquet"
        if not old_p.exists():
            old_compare.append({"rule": r["name"],
                                       "old_total": None,
                                       "old_mean": None,
                                       "old_wr": None})
            continue
        odf = pd.read_parquet(old_p)
        old_compare.append({
            "rule": r["name"],
            "old_n": int(len(odf)),
            "old_total": float(odf["net_pnl"].sum()),
            "old_mean": float(odf["net_pnl"].mean()),
            "old_wr": float((odf["net_pnl"] > 0).mean()),
            "old_pct_fired": float(
                odf["fired_rule"].mean()) if "fired_rule"
                in odf.columns else float("nan"),
        })
    old_df = pd.DataFrame(old_compare)
    old_df.to_parquet(OUT / "old_vs_new_compare.parquet",
                              index=False)

    # ---- Identify survivors ----
    base_total = base_summary["all_total"]
    surviving = []
    for s in summaries[1:]:
        if s["all_total"] is None: continue
        if s["all_total"] > base_total:
            surviving.append(s)
    print(f"\n[Step 10] Survivors (beat baseline {fmt_d(base_total)} "
          f"all-years): {len(surviving)}")
    for s in surviving:
        print(f"  {s['rule']}: total {fmt_d(s['all_total'])}, "
              f"delta vs baseline +{fmt_d(s['all_vs_base_total'])}, "
              f"mean {fmt_d(s['all_mean'])}, "
              f"PF {fmt_pf(s['all_pf'])}")

    # ---- Markdown report ----
    print("\n[Step 11] Writing GRID_REPORT.md...")
    write_report(summaries, audits, sens_df, old_df, base_summary,
                       audit_failed_rules, surviving)

    elapsed_total = time.time() - t_start
    print(f"\nDone. Total: {elapsed_total/60:.1f} min")
    return 0 if not audit_failed_rules else 1


def write_report(summaries, audits, sens_df, old_df,
                       base_summary, audit_failed_rules, surviving):
    base_total = base_summary["all_total"]
    base_mean = base_summary["all_mean"]
    base_pf = base_summary["all_pf"]
    base_wr = base_summary["all_wr"]

    lines = []
    lines.append("# HH/LL Progression Safe Replay Re-Test "
                  "— IS 2024-2026")
    lines.append("")
    lines.append(f"Run: {pd.Timestamp.now(tz='UTC').isoformat()}")
    lines.append("")
    lines.append("Re-runs the original 36-rule grid through "
                  "`utils/safe_replay`. Question: after removing "
                  "phantom fills, does any HH/LL exit rule still "
                  "beat baseline regime exit?")
    lines.append("")
    lines.append("## Configuration")
    lines.append("")
    lines.append("- Span: NQ RTH 2024 + 2025 + 2026")
    lines.append(f"- Population: {base_summary['all_n']:,} V_A "
                  "trades")
    lines.append("- Cost: $5 commission + $5 tick = $10 RT")
    lines.append("- Primary mode: `conservative_ohlc` / "
                  "`at_or_worse_close` / `market_exit_now`")
    lines.append("- Family A: stall exit at bar close (no protect_px)")
    lines.append("- Family B: move stop to BE after stall + MFE")
    lines.append("- Family C: lock pct of MFE after stall + MFE>=1ATR")
    lines.append("")

    # ---- Audit verdict ----
    lines.append("## Audit verdict")
    lines.append("")
    if audit_failed_rules:
        lines.append(f"- **FAIL** — {len(audit_failed_rules)} rules "
                      "produced impossible fills:")
        for n in audit_failed_rules:
            lines.append(f"  - `{n}`")
    else:
        lines.append(f"- **PASS** — 0 impossible fills across all "
                      f"{len(audits)} rules")
    lines.append("")

    # ---- Baseline ----
    lines.append("## Baseline (regime exit)")
    lines.append("")
    lines.append(f"- n = {base_summary['all_n']:,}")
    lines.append(f"- Total: **{fmt_d(base_total)}**")
    lines.append(f"- Mean: {fmt_d(base_mean)}/trade")
    lines.append(f"- PF: {fmt_pf(base_pf)}")
    lines.append(f"- WR: {fmt_p(base_wr)}")
    lines.append("")
    for yr in YEARS:
        lines.append(f"  - {yr}: total {fmt_d(base_summary[f'y{yr}_total'])}, "
                      f"mean {fmt_d(base_summary[f'y{yr}_mean'])}, "
                      f"PF {fmt_pf(base_summary[f'y{yr}_pf'])}, "
                      f"WR {fmt_p(base_summary[f'y{yr}_wr'])}")
    lines.append("")

    # ---- Survivor headline ----
    lines.append("## Survivors (beat baseline all-years)")
    lines.append("")
    if not surviving:
        lines.append("**ZERO rules beat baseline all-years total. "
                      "HH/LL progression is dead under safe replay.**")
    else:
        lines.append(f"{len(surviving)} rules beat baseline:")
        lines.append("")
        lines.append("| Rule | Total | vs Base | Mean | PF | WR | "
                     "%fired | %inv@arm |")
        lines.append("|---|--:|--:|--:|--:|--:|--:|--:|")
        for s in surviving:
            lines.append(
                f"| `{s['rule']}` | "
                f"{fmt_d(s['all_total'])} | "
                f"+{fmt_d(s['all_vs_base_total'])} | "
                f"{fmt_d(s['all_mean'])} | "
                f"{fmt_pf(s['all_pf'])} | "
                f"{fmt_p(s['all_wr'])} | "
                f"{fmt_p(s['pct_fired'])} | "
                f"{fmt_p(s['pct_invalid_at_arm'])} |")
    lines.append("")

    # ---- Full scoreboard ----
    lines.append("## Full rule scoreboard (primary mode)")
    lines.append("")
    lines.append("| Rule | n | %fired | %inv@arm | All total | "
                 "vs base | All mean | All PF | All WR | "
                 "2024 total | 2025 total | 2026 total | top-1% |")
    lines.append("|" + "|".join(["---"] * 13) + "|")
    for s in summaries:
        if s["rule"] == "BASELINE_regime":
            lines.append(
                f"| **`{s['rule']}`** | {s['all_n']:,} | "
                f"— | — | "
                f"**{fmt_d(s['all_total'])}** | (base) | "
                f"{fmt_d(s['all_mean'])} | "
                f"{fmt_pf(s['all_pf'])} | "
                f"{fmt_p(s['all_wr'])} | "
                f"{fmt_d(s.get('y2024_total'))} | "
                f"{fmt_d(s.get('y2025_total'))} | "
                f"{fmt_d(s.get('y2026_total'))} | "
                f"{fmt_p(s.get('top1_share', 0))} |")
        else:
            delta = s.get("all_vs_base_total", 0.0)
            sign = "+" if delta >= 0 else ""
            lines.append(
                f"| `{s['rule']}` | {s['all_n']:,} | "
                f"{fmt_p(s['pct_fired'])} | "
                f"{fmt_p(s.get('pct_invalid_at_arm', 0))} | "
                f"{fmt_d(s['all_total'])} | "
                f"{sign}{fmt_d(delta)} | "
                f"{fmt_d(s['all_mean'])} | "
                f"{fmt_pf(s['all_pf'])} | "
                f"{fmt_p(s['all_wr'])} | "
                f"{fmt_d(s.get('y2024_total'))} | "
                f"{fmt_d(s.get('y2025_total'))} | "
                f"{fmt_d(s.get('y2026_total'))} | "
                f"{fmt_p(s.get('top1_share', 0))} |")
    lines.append("")

    # ---- Old vs new ----
    lines.append("## Old phantom-fill vs new safe replay")
    lines.append("")
    lines.append("Old result is from "
                  "`HHLL_PROGRESSION_REPORT.md` (replay_family_c "
                  "with phantom fills). New result is the same rule "
                  "under safe replay. Δ shows the phantom-fill "
                  "inflation per rule.")
    lines.append("")
    lines.append("| Rule | Old total | New total | Δ (new-old) | "
                 "Old mean | New mean | Old WR | New WR |")
    lines.append("|---|--:|--:|--:|--:|--:|--:|--:|")
    new_by_rule = {s["rule"]: s for s in summaries}
    for _, o in old_df.iterrows():
        n = new_by_rule.get(o["rule"])
        if n is None: continue
        delta = (n["all_total"] - o["old_total"]
                  if o["old_total"] is not None else None)
        lines.append(
            f"| `{o['rule']}` | "
            f"{fmt_d(o['old_total']) if o['old_total'] is not None else '—'} | "
            f"{fmt_d(n['all_total'])} | "
            f"{fmt_d(delta) if delta is not None else '—'} | "
            f"{fmt_d(o['old_mean']) if o['old_mean'] is not None else '—'} | "
            f"{fmt_d(n['all_mean'])} | "
            f"{fmt_p(o['old_wr']) if o['old_wr'] is not None else '—'} | "
            f"{fmt_p(n['all_wr'])} |")
    lines.append("")

    # ---- Sensitivity ----
    lines.append("## Diagnostic sensitivity")
    lines.append("")
    lines.append("Bounds on how the result moves under alternative "
                  "(non-default) settings.")
    lines.append("")
    lines.append("| Rule | Mode | Total | Mean | PF | WR | %fired |")
    lines.append("|---|---|--:|--:|--:|--:|--:|")
    for _, r in sens_df.iterrows():
        rule_name, mode = r["rule"].split("__", 1)
        lines.append(
            f"| `{rule_name}` | {mode} | "
            f"{fmt_d(r['all_total'])} | "
            f"{fmt_d(r['all_mean'])} | "
            f"{fmt_pf(r['all_pf'])} | "
            f"{fmt_p(r['all_wr'])} | "
            f"{fmt_p(r['pct_fired'])} |")
    lines.append("")

    # ---- Audit detail ----
    lines.append("## Audit detail")
    lines.append("")
    lines.append("| Rule | n | impossible | inv@arm | "
                 "exit_before_arm | sign_inconsistent | "
                 "off_tick_grid |")
    lines.append("|---|--:|--:|--:|--:|--:|--:|")
    for a in audits:
        lines.append(
            f"| `{a['rule']}` | {a['n']:,} | "
            f"{a['impossible_fills']} | "
            f"{a.get('flag_exit_before_arm_count', 0) + a.get('flag_exit_before_arm_count', 0)} | "
            f"{a.get('flag_exit_before_arm_count', 0)} | "
            f"{a.get('flag_direction_sign_inconsistent_count', 0)} | "
            f"{a.get('flag_protect_not_on_tick_grid_count', 0)} |")
    lines.append("")

    # ---- Conclusion ----
    lines.append("## Conclusion")
    lines.append("")
    if not surviving:
        lines.append("**HH/LL progression as a class is DEAD under "
                      "safe replay.** No rule (out of 36) beats "
                      "baseline regime exit on the IS 2024-2026 "
                      "span. The original study's positive results "
                      "were entirely an artifact of the "
                      "phantom-fill replay bug. No expansion to "
                      "2020-2023 OOS is warranted.")
    else:
        lines.append(f"{len(surviving)} rule(s) beat baseline "
                      "all-years. Recommend OOS expansion to "
                      "2020-2023 to test robustness:")
        for s in surviving:
            lines.append(f"- `{s['rule']}`")
    lines.append("")

    (OUT / "GRID_REPORT.md").write_text("\n".join(lines),
                                                encoding="utf-8")
    print(f"  Report: {OUT / 'GRID_REPORT.md'}")


if __name__ == "__main__":
    sys.exit(main())
