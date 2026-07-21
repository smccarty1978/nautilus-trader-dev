"""Volatility Exhaustion Study v1 — analyzer."""

from __future__ import annotations
import os, sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
os.chdir(project_root)

OUT = Path("studies/volatility_exhaustion_v1/results")
YEARS = [2024, 2025, 2026]
WINDOWS_S = [60, 120, 180, 300]
RACES = [(0.50, 0.50), (0.75, 0.50), (1.00, 0.50),
          (1.00, 0.75), (1.50, 0.75)]
TRIGGERS = ["close_loc", "no_new_30s", "no_new_60s", "wick_rejection"]
NQ_MULT = 20.0
COMMISSION = 5.0
TICK_COST = 5.0


def fmt_d(v):
    if v is None or (isinstance(v, float) and (pd.isna(v) or np.isinf(v))):
        return "—"
    return f"${v:,.2f}" if abs(v) < 1000 else f"${v:,.0f}"


def fmt_p(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{100 * v:.1f}%"


def race_pnl(row, pt_R, sl_R, w, policy):
    tag = f"race_{int(pt_R*100)}_{int(sl_R*100)}_{w}s"
    out = row[f"{tag}_outcome"]
    atr = row["atr_at_impulse"]
    if out == "pt":
        return pt_R * atr * NQ_MULT - COMMISSION - TICK_COST
    if out == "sl":
        return -sl_R * atr * NQ_MULT - COMMISSION - 2 * TICK_COST
    if policy == "exclude":
        return np.nan
    close_w = row[f"close_at_{w}s_price"]
    fill = row["fill_price"]
    d = row["entry_direction"]
    if pd.isna(close_w):
        return np.nan
    return (close_w - fill) * d * NQ_MULT - COMMISSION - TICK_COST


def race_hold(row, pt_R, sl_R, w, policy):
    tag = f"race_{int(pt_R*100)}_{int(sl_R*100)}_{w}s"
    out = row[f"{tag}_outcome"]
    if out in ("pt", "sl"):
        return float(row[f"{tag}_resolution_s"])
    if policy == "exclude":
        return float("nan")
    return float(w)


def race_stats(df, pt_R, sl_R, w, policy="exit_at_close"):
    if len(df) == 0:
        return {"n": 0}
    tag = f"race_{int(pt_R*100)}_{int(sl_R*100)}_{w}s"
    out_col = f"{tag}_outcome"
    pnl = df.apply(lambda r: race_pnl(r, pt_R, sl_R, w, policy), axis=1)
    hold = df.apply(lambda r: race_hold(r, pt_R, sl_R, w, policy),
                      axis=1)
    valid = ~pnl.isna()
    pnl_v = pnl[valid]
    hold_v = hold[valid]
    n = len(pnl_v)
    if n == 0:
        return {"n": 0}
    wins = pnl_v[pnl_v > 0]
    losses = pnl_v[pnl_v < 0]
    pf = (wins.sum() / abs(losses.sum())
            if len(losses) and losses.sum() != 0 else float("inf"))
    cum = pnl_v.cumsum().values
    peak = np.maximum.accumulate(cum)
    mdd = float((cum - peak).min()) if len(cum) else 0.0
    return {
        "n": n,
        "pt_pct": float((df[out_col] == "pt").mean()),
        "sl_pct": float((df[out_col] == "sl").mean()),
        "unresolved_pct": float(
            (df[out_col] == "unresolved").mean()),
        "mean": float(pnl_v.mean()),
        "median": float(pnl_v.median()),
        "sum": float(pnl_v.sum()),
        "pf": float(pf),
        "max_dd": mdd,
        "median_hold_s": float(hold_v.median()),
    }


def main():
    dfs = {}
    for year in YEARS:
        path = OUT / f"trades_{year}.parquet"
        if path.exists():
            dfs[year] = pd.read_parquet(path)
            print(f"  {year}: {len(dfs[year]):,} rows")

    lines = []
    lines.append("# Volatility Exhaustion / Failure Study v1")
    lines.append("")
    lines.append("**Population**: HMM state 3 (vol burst) impulses "
                 "during a 1m regime. Continuation only (impulse "
                 "direction matches regime). 4 failure triggers "
                 "post state-3 exit. Entry direction = REVERSAL "
                 "(opposite of impulse).")
    lines.append("")
    lines.append("**Causal timing**: decision at trigger close, fill "
                 "30s later. No future-survival filtering. **No "
                 "regime-exit edge anywhere.**")
    lines.append("")
    lines.append("**5 reversal brackets × 4 windows × 4 triggers** "
                 "= 80 cells per year.")
    lines.append("")

    # ============================================================
    # 1. Setup frequency
    # ============================================================
    lines.append("## 1. Setup frequency")
    lines.append("")
    lines.append("| Year | Total trade rows | Unique impulses | "
                 "Long entries | Short entries | Avg regime age (1m bars) "
                 "| Avg ATR |")
    lines.append("|---|--:|--:|--:|--:|--:|--:|")
    for year, df in dfs.items():
        n_total = len(df)
        n_imp = df["impulse_id"].nunique()
        n_long = int((df["entry_direction"] == 1).sum())
        n_short = int((df["entry_direction"] == -1).sum())
        avg_age = float(df["regime_age_bars"].mean())
        avg_atr = float(df["atr_at_impulse"].mean())
        lines.append(
            f"| {year} | {n_total:,} | {n_imp:,} | {n_long:,} | "
            f"{n_short:,} | {avg_age:.1f} | {avg_atr:.2f} |")
    lines.append("")

    # Trigger counts
    lines.append("Trigger counts:")
    lines.append("")
    lines.append("| Year | close_loc | no_new_30s | no_new_60s | "
                 "wick_rejection |")
    lines.append("|---|--:|--:|--:|--:|")
    for year, df in dfs.items():
        cells = [str(year)]
        for trig in TRIGGERS:
            cells.append(f"{int((df['trigger_type'] == trig).sum()):,}")
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")

    # ============================================================
    # 2. Baseline reversal economics by trigger
    # Fixed race for clarity: 1.00 PT / 0.50 SL, w=120s, exit_at_close
    # ============================================================
    lines.append("## 2. Baseline reversal economics by trigger "
                 "(race 1.00/0.50, w=120s, exit_at_close)")
    lines.append("")
    lines.append("| Year | Trigger | n | PT% | SL% | Unres% | "
                 "Mean $ | Median $ | PF | Total $ | Max DD | "
                 "Med hold |")
    lines.append("|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
    for year, df in dfs.items():
        for trig in TRIGGERS:
            sub = df[df["trigger_type"] == trig]
            r = race_stats(sub, 1.00, 0.50, 120, "exit_at_close")
            if r["n"] == 0:
                continue
            lines.append(
                f"| {year} | {trig} | {r['n']:,} | "
                f"{fmt_p(r['pt_pct'])} | {fmt_p(r['sl_pct'])} | "
                f"{fmt_p(r['unresolved_pct'])} | "
                f"{fmt_d(r['mean'])} | {fmt_d(r['median'])} | "
                f"{r['pf']:.2f} | {fmt_d(r['sum'])} | "
                f"{fmt_d(r['max_dd'])} | "
                f"{r['median_hold_s']:.0f}s |")
    lines.append("")

    # Same table at race 0.50/0.50 (tighter, more "exhaustion-like")
    lines.append("## 2b. Same as above, race 0.50/0.50, w=120s")
    lines.append("")
    lines.append("| Year | Trigger | n | PT% | SL% | Unres% | "
                 "Mean $ | PF | Total $ |")
    lines.append("|---|---|--:|--:|--:|--:|--:|--:|--:|")
    for year, df in dfs.items():
        for trig in TRIGGERS:
            sub = df[df["trigger_type"] == trig]
            r = race_stats(sub, 0.50, 0.50, 120, "exit_at_close")
            if r["n"] == 0:
                continue
            lines.append(
                f"| {year} | {trig} | {r['n']:,} | "
                f"{fmt_p(r['pt_pct'])} | {fmt_p(r['sl_pct'])} | "
                f"{fmt_p(r['unresolved_pct'])} | "
                f"{fmt_d(r['mean'])} | {r['pf']:.2f} | "
                f"{fmt_d(r['sum'])} |")
    lines.append("")

    # ============================================================
    # 3. Direction split
    # ============================================================
    lines.append("## 3. Direction split "
                 "(race 0.50/0.50, w=120s, exit_at_close)")
    lines.append("")
    lines.append("| Year | Setup | n | PT% | SL% | Mean $ | PF | "
                 "Total $ |")
    lines.append("|---|---|--:|--:|--:|--:|--:|--:|")
    for year, df in dfs.items():
        # Failed bullish impulse → short
        sub_short = df[df["entry_direction"] == -1]
        sub_long = df[df["entry_direction"] == 1]
        for label, sub in [
            ("Failed bullish impulse → SHORT", sub_short),
            ("Failed bearish impulse → LONG", sub_long),
        ]:
            r = race_stats(sub, 0.50, 0.50, 120, "exit_at_close")
            if r["n"] == 0:
                continue
            lines.append(
                f"| {year} | {label} | {r['n']:,} | "
                f"{fmt_p(r['pt_pct'])} | {fmt_p(r['sl_pct'])} | "
                f"{fmt_d(r['mean'])} | {r['pf']:.2f} | "
                f"{fmt_d(r['sum'])} |")
    lines.append("")

    # ============================================================
    # 4. HMM transition table — already filtered to "transition out
    # of state 3" by construction. This compares trigger types as
    # different post-exit failure modes.
    # ============================================================
    lines.append("## 4. Transition-out trigger comparison "
                 "(same as Table 2)")
    lines.append("")
    lines.append("All rows in this study ARE transition-out events "
                 "(state 3 exits). Table 2 above is the comparison; "
                 "no separate \"in/stable\" cohort here because "
                 "the entry rule requires exit.")
    lines.append("")

    # ============================================================
    # 5. Location / extension buckets
    # ============================================================
    lines.append("## 5. Location / extension buckets "
                 "(close_loc trigger, race 0.50/0.50, w=120s)")
    lines.append("")
    for year, df in dfs.items():
        sub_y = df[df["trigger_type"] == "close_loc"].copy()
        if len(sub_y) == 0:
            continue
        # For shorts (failed bullish), "near session high" = small
        # dist_from_session_high. For longs (failed bearish), "near
        # session low" = small dist_from_session_low. Combine as
        # "distance from relevant extreme".
        sub_y["dist_from_extreme_atr"] = np.where(
            sub_y["entry_direction"] == -1,  # short = failed bullish
            sub_y["dist_from_session_high_atr"],
            sub_y["dist_from_session_low_atr"])
        d_q = sub_y["dist_from_extreme_atr"].quantile(
            [0.25, 0.5, 0.75]).values
        sub_y["dist_bucket"] = pd.cut(
            sub_y["dist_from_extreme_atr"],
            bins=[-np.inf, d_q[0], d_q[1], d_q[2], np.inf],
            labels=["Q1 (near extreme)", "Q2", "Q3", "Q4 (far)"])
        lines.append(f"### {year} — distance from session extreme")
        lines.append("")
        lines.append("| Bucket | n | PT% | SL% | Mean $ | PF |")
        lines.append("|---|--:|--:|--:|--:|--:|")
        for b in ["Q1 (near extreme)", "Q2", "Q3", "Q4 (far)"]:
            sub = sub_y[sub_y["dist_bucket"] == b]
            r = race_stats(sub, 0.50, 0.50, 120, "exit_at_close")
            if r["n"] == 0:
                continue
            lines.append(
                f"| {b} | {r['n']:,} | "
                f"{fmt_p(r['pt_pct'])} | {fmt_p(r['sl_pct'])} | "
                f"{fmt_d(r['mean'])} | {r['pf']:.2f} |")
        lines.append("")

        # Extension from regime start
        ext_q = sub_y["extension_from_regime_atr"].quantile(
            [0.25, 0.5, 0.75]).values
        sub_y["ext_bucket"] = pd.cut(
            sub_y["extension_from_regime_atr"],
            bins=[-np.inf, ext_q[0], ext_q[1], ext_q[2], np.inf],
            labels=["Q1 (low ext)", "Q2", "Q3", "Q4 (high ext)"])
        lines.append(f"### {year} — extension from regime start")
        lines.append("")
        lines.append("| Bucket | n | PT% | SL% | Mean $ | PF |")
        lines.append("|---|--:|--:|--:|--:|--:|")
        for b in ["Q1 (low ext)", "Q2", "Q3", "Q4 (high ext)"]:
            sub = sub_y[sub_y["ext_bucket"] == b]
            r = race_stats(sub, 0.50, 0.50, 120, "exit_at_close")
            if r["n"] == 0:
                continue
            lines.append(
                f"| {b} | {r['n']:,} | "
                f"{fmt_p(r['pt_pct'])} | {fmt_p(r['sl_pct'])} | "
                f"{fmt_d(r['mean'])} | {r['pf']:.2f} |")
        lines.append("")

        # Impulse range ATR
        ir_q = sub_y["impulse_range_atr"].quantile(
            [0.25, 0.5, 0.75]).values
        sub_y["ir_bucket"] = pd.cut(
            sub_y["impulse_range_atr"],
            bins=[-np.inf, ir_q[0], ir_q[1], ir_q[2], np.inf],
            labels=["Q1 (small)", "Q2", "Q3", "Q4 (large)"])
        lines.append(f"### {year} — impulse range (ATR)")
        lines.append("")
        lines.append("| Bucket | n | PT% | SL% | Mean $ | PF |")
        lines.append("|---|--:|--:|--:|--:|--:|")
        for b in ["Q1 (small)", "Q2", "Q3", "Q4 (large)"]:
            sub = sub_y[sub_y["ir_bucket"] == b]
            r = race_stats(sub, 0.50, 0.50, 120, "exit_at_close")
            if r["n"] == 0:
                continue
            lines.append(
                f"| {b} | {r['n']:,} | "
                f"{fmt_p(r['pt_pct'])} | {fmt_p(r['sl_pct'])} | "
                f"{fmt_d(r['mean'])} | {r['pf']:.2f} |")
        lines.append("")

        # Impulse close location (how exhausted the impulse closed)
        cl_q = sub_y["impulse_close_loc"].quantile(
            [0.25, 0.5, 0.75]).values
        sub_y["cl_bucket"] = pd.cut(
            sub_y["impulse_close_loc"],
            bins=[-np.inf, cl_q[0], cl_q[1], cl_q[2], np.inf],
            labels=["Q1 (weak close)", "Q2", "Q3",
                    "Q4 (strong close)"])
        lines.append(f"### {year} — impulse close location")
        lines.append("")
        lines.append("| Bucket | n | PT% | SL% | Mean $ | PF |")
        lines.append("|---|--:|--:|--:|--:|--:|")
        for b in ["Q1 (weak close)", "Q2", "Q3", "Q4 (strong close)"]:
            sub = sub_y[sub_y["cl_bucket"] == b]
            r = race_stats(sub, 0.50, 0.50, 120, "exit_at_close")
            if r["n"] == 0:
                continue
            lines.append(
                f"| {b} | {r['n']:,} | "
                f"{fmt_p(r['pt_pct'])} | {fmt_p(r['sl_pct'])} | "
                f"{fmt_d(r['mean'])} | {r['pf']:.2f} |")
        lines.append("")

    # ============================================================
    # 6. Cross-year stability — scan all (trigger × race × window),
    # require PF >= 1.10, n >= 200 per year
    # ============================================================
    lines.append("## 6. Cross-year stability (scan all trigger × "
                 "race × window, threshold PF >= 1.10 + n >= 200)")
    lines.append("")
    # Build per-(trigger, race, window) stats per year
    spec_results = {}  # (trigger, pt, sl, w) → {year: stats}
    for trig in TRIGGERS:
        for pt_R, sl_R in RACES:
            for w in WINDOWS_S:
                key = (trig, pt_R, sl_R, w)
                spec_results[key] = {}
                for year, df in dfs.items():
                    sub = df[df["trigger_type"] == trig]
                    r = race_stats(sub, pt_R, sl_R, w,
                                     "exit_at_close")
                    spec_results[key][year] = r

    # Find specs that pass in 2+ years
    passing_specs = []
    for key, yr_dict in spec_results.items():
        passing_years = [
            y for y, r in yr_dict.items()
            if r.get("n", 0) >= 200 and r.get("pf", 0) >= 1.10
            and r.get("mean", 0) > 0
        ]
        if len(passing_years) >= 2:
            passing_specs.append((key, passing_years, yr_dict))

    # Also list any single-year hits as candidate (no auto-pass)
    single_year_hits = []
    for key, yr_dict in spec_results.items():
        for y, r in yr_dict.items():
            if r.get("n", 0) >= 200 and r.get("pf", 0) >= 1.10:
                single_year_hits.append((key, y, r))

    if passing_specs:
        lines.append(
            "**Specs passing in >=2 years (PF >= 1.10, n >= 200):**")
        lines.append("")
        lines.append("| Trigger | Race | Window | "
                     "2024 (n / mean / PF) | "
                     "2025 (n / mean / PF) | "
                     "2026 (n / mean / PF) |")
        lines.append("|---|---|--:|---|---|---|")
        for key, passing, yr_dict in passing_specs:
            trig, pt_R, sl_R, w = key
            cells = [trig, f"{pt_R}/{sl_R}", f"{w}s"]
            for yr in YEARS:
                r = yr_dict.get(yr, {})
                if r.get("n", 0) == 0:
                    cells.append("—")
                else:
                    cells.append(
                        f"{r['n']:,} / {fmt_d(r['mean'])} / "
                        f"{r['pf']:.2f}")
            lines.append("| " + " | ".join(cells) + " |")
        lines.append("")
    else:
        lines.append("**No spec passed in >=2 years.**")
        lines.append("")

    # Single-year hits summary
    if single_year_hits:
        lines.append(f"Single-year hits "
                      f"(PF >= 1.10 + n >= 200, may not generalize): "
                      f"{len(single_year_hits)}")
        # Show top 10 by mean
        single_year_hits.sort(key=lambda x: -x[2]["mean"])
        lines.append("")
        lines.append("| Year | Trigger | Race | Window | n | "
                     "Mean $ | PF |")
        lines.append("|---|---|---|--:|--:|--:|--:|")
        for key, yr, r in single_year_hits[:10]:
            trig, pt_R, sl_R, w = key
            lines.append(
                f"| {yr} | {trig} | {pt_R}/{sl_R} | {w}s | "
                f"{r['n']:,} | {fmt_d(r['mean'])} | "
                f"{r['pf']:.2f} |")
    else:
        lines.append("**No single-year hits either.** Strategy fails "
                      "the success criteria entirely.")
    lines.append("")

    # ============================================================
    # 7. Unresolved policy stress test
    # ============================================================
    lines.append("## 7. Unresolved policy stress (race 0.50/0.50, "
                 "w=120s) — exit_at_close vs exclude")
    lines.append("")
    lines.append("| Year | Trigger | Policy | n | PT% | SL% | "
                 "Mean $ | PF |")
    lines.append("|---|---|---|--:|--:|--:|--:|--:|")
    for year, df in dfs.items():
        for trig in TRIGGERS:
            sub = df[df["trigger_type"] == trig]
            for policy_name, policy_arg in [
                ("exit_at_close", "exit_at_close"),
                ("exclude", "exclude"),
            ]:
                r = race_stats(sub, 0.50, 0.50, 120, policy_arg)
                if r["n"] == 0:
                    continue
                lines.append(
                    f"| {year} | {trig} | {policy_name} | "
                    f"{r['n']:,} | {fmt_p(r['pt_pct'])} | "
                    f"{fmt_p(r['sl_pct'])} | "
                    f"{fmt_d(r['mean'])} | {r['pf']:.2f} |")
    lines.append("")

    # ============================================================
    # Verdict
    # ============================================================
    lines.append("## Verdict")
    lines.append("")
    lines.append(f"**Specs passing success criteria** (PF >= 1.10, "
                 f"n >= 200, positive mean, >=2 years): "
                 f"{len(passing_specs)}")
    lines.append("")
    if passing_specs:
        lines.append("Cross-year stable specs found above. Drill in "
                     "with NT runtime parity before claiming an edge.")
    else:
        lines.append(
            "No spec meets the success criteria across multiple "
            "years. The 'trade against failed expansion' hypothesis "
            "does not generate a stable reversal edge in this "
            "event family.")
    lines.append("")

    out_path = OUT / "VOL_EXHAUSTION_REPORT.md"
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport: {out_path}")
    print(f"\nPassing specs (>=2 years): {len(passing_specs)}")
    for key, passing, yr_dict in passing_specs[:5]:
        print(f"  {key}: {passing}")


if __name__ == "__main__":
    main()
