"""Fast Resolution Expansion Study v1 — analyzer.

Builds 8 required tables + HMM-specific tables. Pure descriptive.
"""

from __future__ import annotations
import os, sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
os.chdir(project_root)

OUT = Path("studies/fast_resolution_v1/results")
YEARS = [2024, 2025, 2026]
ENTRY_CANDIDATES_S = [0, 30, 60, 90]
WINDOWS_S = [30, 60, 120, 180, 300]
RACES = [(0.50, 0.50), (0.75, 0.50), (1.00, 0.50),
          (1.00, 0.75), (1.25, 0.75)]
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


def race_pnl_for_row(row, pt_R, sl_R, w, policy):
    """Compute PnL for a (race, window, policy) on one row.
    policy: 'exit_at_close' or 'exclude_unresolved' (returns nan).
    """
    tag = f"race_{int(pt_R*100)}_{int(sl_R*100)}_{w}s"
    outcome = row[f"{tag}_outcome"]
    atr = row["atr_at_signal"]
    if outcome == "pt":
        return pt_R * atr * NQ_MULT - COMMISSION - TICK_COST
    elif outcome == "sl":
        return -sl_R * atr * NQ_MULT - COMMISSION - 2 * TICK_COST
    else:  # unresolved
        if policy == "exclude_unresolved":
            return np.nan
        # exit at window close
        close_w = row[f"close_at_{w}s_price"]
        fill = row["fill_price"]
        d = row["direction"]
        if pd.isna(close_w):
            return np.nan
        return ((close_w - fill) * d * NQ_MULT
                  - COMMISSION - TICK_COST)


def race_hold_time_for_row(row, pt_R, sl_R, w, policy):
    tag = f"race_{int(pt_R*100)}_{int(sl_R*100)}_{w}s"
    outcome = row[f"{tag}_outcome"]
    if outcome in ("pt", "sl"):
        return float(row[f"{tag}_resolution_s"])
    if policy == "exclude_unresolved":
        return float("nan")
    return float(w)


def race_stats(df, pt_R, sl_R, w, policy="exit_at_close"):
    """Compute economics for a (race, window, policy) on a dataframe."""
    if len(df) == 0:
        return {"n": 0}
    tag = f"race_{int(pt_R*100)}_{int(sl_R*100)}_{w}s"
    out_col = f"{tag}_outcome"
    pnl = df.apply(lambda r: race_pnl_for_row(r, pt_R, sl_R, w, policy),
                     axis=1)
    hold = df.apply(
        lambda r: race_hold_time_for_row(r, pt_R, sl_R, w, policy),
        axis=1)
    valid = ~pnl.isna()
    pnl_valid = pnl[valid]
    hold_valid = hold[valid]
    n = len(pnl_valid)
    if n == 0:
        return {"n": 0}
    wins = pnl_valid[pnl_valid > 0]
    losses = pnl_valid[pnl_valid < 0]
    pf = (wins.sum() / abs(losses.sum())
            if len(losses) and losses.sum() != 0 else float("inf"))
    cum = pnl_valid.cumsum().values
    peak = np.maximum.accumulate(cum)
    mdd = float((cum - peak).min()) if len(cum) else 0.0
    out = {
        "n": n,
        "pt_pct": float((df[out_col] == "pt").mean()),
        "sl_pct": float((df[out_col] == "sl").mean()),
        "unresolved_pct": float((df[out_col] == "unresolved").mean()),
        "mean": float(pnl_valid.mean()),
        "median": float(pnl_valid.median()),
        "sum": float(pnl_valid.sum()),
        "pf": float(pf),
        "max_dd": mdd,
        "mean_hold_s": float(hold_valid.mean()),
        "median_hold_s": float(hold_valid.median()),
    }
    return out


def main():
    # Load all years
    dfs = {}
    for year in YEARS:
        path = OUT / f"trades_{year}.parquet"
        if path.exists():
            dfs[year] = pd.read_parquet(path)
            print(f"  {year}: {len(dfs[year]):,} rows")

    lines = []
    lines.append("# Fast Resolution Expansion Study v1")
    lines.append("")
    lines.append("**Population**: HH/LL-confirmed RTH 1m regime flips, "
                 "2024 + 2025 + 2026.")
    lines.append("")
    lines.append("**Entry candidates**: at signal, +30s, +60s, +90s "
                 "from signal_time. Decision at checkpoint close, "
                 "fill 30s later. Causal regime check at decision "
                 "time only (no future-survival filtering).")
    lines.append("")
    lines.append("**Races**: 5 PT-before-SL combos. **Windows**: "
                 "30/60/120/180/300s.")
    lines.append("")
    lines.append("**Cost model**: $5 commission + 1-tick (PT) or "
                 "2-tick (SL) exit slip. Unresolved exits at window "
                 "close pay 1-tick.")
    lines.append("")
    lines.append("**No regime-exit PnL anywhere.** Unresolved trades "
                 "are unresolved.")
    lines.append("")

    # ============================================================
    # TABLE 1: Baseline economics by entry time
    # Headline race for each entry candidate: (1.00 / 0.50, w=120)
    # ============================================================
    lines.append("## 1. Baseline fast-resolution economics by entry "
                 "time (race 1.00 PT / 0.50 SL, window 120s, "
                 "exit_at_close)")
    lines.append("")
    lines.append("| Year | Entry @ | n | PT% | SL% | Unres% | "
                 "Mean $ | Median $ | PF | Total $ | Med hold | "
                 "Max DD |")
    lines.append("|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
    for year, df in dfs.items():
        for ec_s in ENTRY_CANDIDATES_S:
            sub = df[df["entry_candidate_s"] == ec_s]
            r = race_stats(sub, 1.00, 0.50, 120, "exit_at_close")
            if r["n"] == 0:
                continue
            lines.append(
                f"| {year} | +{ec_s}s | {r['n']:,} | "
                f"{fmt_p(r['pt_pct'])} | {fmt_p(r['sl_pct'])} | "
                f"{fmt_p(r['unresolved_pct'])} | "
                f"{fmt_d(r['mean'])} | {fmt_d(r['median'])} | "
                f"{r['pf']:.2f} | {fmt_d(r['sum'])} | "
                f"{r['median_hold_s']:.0f}s | "
                f"{fmt_d(r['max_dd'])} |")
    lines.append("")

    # ============================================================
    # TABLE 2: Race label results by window (entry @ +30s)
    # ============================================================
    lines.append("## 2. Race label results by window "
                 "(entry @ +30s checkpoint, exit_at_close)")
    lines.append("")
    for year, df in dfs.items():
        sub_y = df[df["entry_candidate_s"] == 30]
        lines.append(f"### {year}")
        lines.append("")
        lines.append("| Race PT/SL | Window | n | PT% | SL% | Unres% "
                     "| Mean $ | PF | Total $ | Med hold |")
        lines.append("|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
        for pt_R, sl_R in RACES:
            for w in WINDOWS_S:
                r = race_stats(sub_y, pt_R, sl_R, w, "exit_at_close")
                if r["n"] == 0:
                    continue
                lines.append(
                    f"| {pt_R}/{sl_R} | {w}s | {r['n']:,} | "
                    f"{fmt_p(r['pt_pct'])} | "
                    f"{fmt_p(r['sl_pct'])} | "
                    f"{fmt_p(r['unresolved_pct'])} | "
                    f"{fmt_d(r['mean'])} | {r['pf']:.2f} | "
                    f"{fmt_d(r['sum'])} | "
                    f"{r['median_hold_s']:.0f}s |")
        lines.append("")

    # ============================================================
    # TABLE 3: Unresolved-rate table (race 1.00/0.50, by entry × window)
    # ============================================================
    lines.append("## 3. Unresolved rate by entry × window "
                 "(race 1.00 PT / 0.50 SL)")
    lines.append("")
    for year, df in dfs.items():
        lines.append(f"### {year}")
        lines.append("")
        cols = "| Entry @ | " + " | ".join(f"{w}s" for w in WINDOWS_S) + " |"
        sep = "|---|" + "---|" * len(WINDOWS_S)
        lines.append(cols)
        lines.append(sep)
        for ec_s in ENTRY_CANDIDATES_S:
            sub = df[df["entry_candidate_s"] == ec_s]
            cells = [f"+{ec_s}s"]
            for w in WINDOWS_S:
                r = race_stats(sub, 1.00, 0.50, w, "exit_at_close")
                cells.append(fmt_p(r.get("unresolved_pct", float("nan"))))
            lines.append("| " + " | ".join(cells) + " |")
        lines.append("")

    # ============================================================
    # TABLE 4: Results by HMM state (entry @ +30s, race 1.00/0.50, w=120s)
    # ============================================================
    lines.append("## 4. Fast-resolution results by HMM state at "
                 "decision (entry @ +30s, race 1.00/0.50, w=120s, "
                 "exit_at_close)")
    lines.append("")
    lines.append("| Year | State | n | PT% | SL% | Unres% | "
                 "Mean $ | PF | Med Res t | <60s | <120s |")
    lines.append("|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
    for year, df in dfs.items():
        sub_y = df[df["entry_candidate_s"] == 30]
        for st in [0, 1, 2, 3]:
            sub = sub_y[sub_y["hmm_state_at_decision"] == st]
            if len(sub) == 0:
                continue
            r = race_stats(sub, 1.00, 0.50, 120, "exit_at_close")
            tag = "race_100_50_120s"
            res_col = f"{tag}_resolution_s"
            res = sub[res_col].dropna()
            within_60 = (res <= 60).mean() if len(res) else 0
            within_120 = (res <= 120).mean() if len(res) else 0
            lines.append(
                f"| {year} | {st} | {r['n']:,} | "
                f"{fmt_p(r['pt_pct'])} | "
                f"{fmt_p(r['sl_pct'])} | "
                f"{fmt_p(r['unresolved_pct'])} | "
                f"{fmt_d(r['mean'])} | {r['pf']:.2f} | "
                f"{r['median_hold_s']:.0f}s | "
                f"{fmt_p(within_60)} | {fmt_p(within_120)} |")
    lines.append("")

    # ============================================================
    # TABLE 5: Results by early-progress bucket
    # bucket on progress_since_signal_atr at decision (entry @ +30s, +60s)
    # ============================================================
    lines.append("## 5. Results by early-progress bucket "
                 "(progress_since_signal_atr at decision, "
                 "race 1.00/0.50, w=120s)")
    lines.append("")
    for year, df in dfs.items():
        sub_y = df[df["entry_candidate_s"].isin([30, 60])]
        if len(sub_y) == 0:
            continue
        prog = sub_y["progress_since_signal_atr"]
        # Quartile buckets
        q = prog.quantile([0.25, 0.50, 0.75]).values
        sub_y = sub_y.copy()
        sub_y["prog_bucket"] = pd.cut(
            prog, bins=[-np.inf, q[0], q[1], q[2], np.inf],
            labels=["Q1 (least)", "Q2", "Q3", "Q4 (most)"])
        lines.append(f"### {year}")
        lines.append("")
        lines.append("| Progress bucket | n | PT% | SL% | Unres% | "
                     "Mean $ | PF | Med Res t |")
        lines.append("|---|--:|--:|--:|--:|--:|--:|--:|")
        for bucket in ["Q1 (least)", "Q2", "Q3", "Q4 (most)"]:
            sub = sub_y[sub_y["prog_bucket"] == bucket]
            r = race_stats(sub, 1.00, 0.50, 120, "exit_at_close")
            if r["n"] == 0:
                continue
            lines.append(
                f"| {bucket} | {r['n']:,} | "
                f"{fmt_p(r['pt_pct'])} | "
                f"{fmt_p(r['sl_pct'])} | "
                f"{fmt_p(r['unresolved_pct'])} | "
                f"{fmt_d(r['mean'])} | {r['pf']:.2f} | "
                f"{r['median_hold_s']:.0f}s |")
        lines.append("")

    # ============================================================
    # TABLE 6: Results by ATR quartile
    # ============================================================
    lines.append("## 6. Results by ATR quartile "
                 "(entry @ +30s, race 1.00/0.50, w=120s)")
    lines.append("")
    for year, df in dfs.items():
        sub_y = df[df["entry_candidate_s"] == 30].copy()
        if len(sub_y) == 0:
            continue
        atr = sub_y["atr_at_signal"]
        q = atr.quantile([0.25, 0.50, 0.75]).values
        sub_y["atr_q"] = pd.cut(
            atr, bins=[-np.inf, q[0], q[1], q[2], np.inf],
            labels=["Q1 (low ATR)", "Q2", "Q3", "Q4 (high ATR)"])
        lines.append(f"### {year}")
        lines.append("")
        lines.append("| ATR quartile | n | Mean ATR | PT% | SL% | "
                     "Unres% | Mean $ | PF |")
        lines.append("|---|--:|--:|--:|--:|--:|--:|--:|")
        for bucket in ["Q1 (low ATR)", "Q2", "Q3", "Q4 (high ATR)"]:
            sub = sub_y[sub_y["atr_q"] == bucket]
            r = race_stats(sub, 1.00, 0.50, 120, "exit_at_close")
            if r["n"] == 0:
                continue
            lines.append(
                f"| {bucket} | {r['n']:,} | "
                f"{sub['atr_at_signal'].mean():.2f} | "
                f"{fmt_p(r['pt_pct'])} | {fmt_p(r['sl_pct'])} | "
                f"{fmt_p(r['unresolved_pct'])} | "
                f"{fmt_d(r['mean'])} | {r['pf']:.2f} |")
        lines.append("")

    # ============================================================
    # TABLE 7: Best descriptive slice per year
    # Scan all (entry, race, window) for best mean$ at PF >= 1.10 with n > 200
    # ============================================================
    lines.append("## 7. Best descriptive slice per year (scan all "
                 "entry × race × window, requires PF >= 1.10 and "
                 "n >= 200)")
    lines.append("")
    lines.append("| Year | Entry @ | Race PT/SL | Window | n | "
                 "Mean $ | PF | PT% | Total $ |")
    lines.append("|---|---|---|--:|--:|--:|--:|--:|--:|")
    best_per_year = {}
    for year, df in dfs.items():
        scan_results = []
        for ec_s in ENTRY_CANDIDATES_S:
            sub_y = df[df["entry_candidate_s"] == ec_s]
            for pt_R, sl_R in RACES:
                for w in WINDOWS_S:
                    r = race_stats(sub_y, pt_R, sl_R, w,
                                     "exit_at_close")
                    if r["n"] >= 200 and r["pf"] >= 1.10:
                        scan_results.append({
                            "ec_s": ec_s, "pt_R": pt_R,
                            "sl_R": sl_R, "w": w, **r})
        if scan_results:
            best = max(scan_results, key=lambda x: x["mean"])
            best_per_year[year] = best
            lines.append(
                f"| {year} | +{best['ec_s']}s | "
                f"{best['pt_R']}/{best['sl_R']} | "
                f"{best['w']}s | {best['n']:,} | "
                f"{fmt_d(best['mean'])} | "
                f"{best['pf']:.2f} | "
                f"{fmt_p(best['pt_pct'])} | "
                f"{fmt_d(best['sum'])} |")
        else:
            lines.append(
                f"| {year} | — | — | — | — | — | "
                f"**no slice meets PF >= 1.10** | — | — |")
    lines.append("")

    # ============================================================
    # TABLE 8: Cross-year stability — pick the best slice from
    # one year, evaluate on others
    # ============================================================
    lines.append("## 8. Cross-year stability (apply each year's "
                 "best slice to other years)")
    lines.append("")
    if best_per_year:
        lines.append("| Anchor year | Spec | Anchor mean | Anchor PF | "
                     "Other years (mean $ / PF) |")
        lines.append("|---|---|--:|--:|---|")
        for anchor_year, best in best_per_year.items():
            spec = (f"+{best['ec_s']}s, "
                     f"{best['pt_R']}/{best['sl_R']}, "
                     f"{best['w']}s")
            others = []
            for other_year, df_other in dfs.items():
                if other_year == anchor_year:
                    continue
                sub = df_other[
                    df_other["entry_candidate_s"] == best["ec_s"]]
                r = race_stats(sub, best["pt_R"], best["sl_R"],
                                 best["w"], "exit_at_close")
                others.append(
                    f"{other_year}: {fmt_d(r.get('mean'))} / "
                    f"{r.get('pf', float('nan')):.2f}")
            lines.append(
                f"| {anchor_year} | {spec} | "
                f"{fmt_d(best['mean'])} | "
                f"{best['pf']:.2f} | {' • '.join(others)} |")
    else:
        lines.append("No anchor slice met PF >= 1.10 in any year.")
    lines.append("")

    # ============================================================
    # HMM-Specific: HMM × early-progress interaction
    # ============================================================
    lines.append("## 9. HMM × early-progress interaction "
                 "(entry @ +30s, race 1.00/0.50, w=120s)")
    lines.append("")
    lines.append("| Year | HMM state | Progress bucket | n | "
                 "PT% | SL% | Mean $ | PF |")
    lines.append("|---|---|---|--:|--:|--:|--:|--:|")
    for year, df in dfs.items():
        sub_y = df[df["entry_candidate_s"] == 30].copy()
        prog = sub_y["progress_since_signal_atr"]
        q = prog.quantile([0.5]).values
        sub_y["prog_bin"] = np.where(prog <= q[0], "low", "high")
        for st in [0, 1, 2, 3]:
            for pb in ["low", "high"]:
                sub = sub_y[(sub_y["hmm_state_at_decision"] == st)
                              & (sub_y["prog_bin"] == pb)]
                r = race_stats(sub, 1.00, 0.50, 120,
                                 "exit_at_close")
                if r["n"] < 50:
                    continue
                lines.append(
                    f"| {year} | {st} | {pb} | {r['n']:,} | "
                    f"{fmt_p(r['pt_pct'])} | "
                    f"{fmt_p(r['sl_pct'])} | "
                    f"{fmt_d(r['mean'])} | {r['pf']:.2f} |")
    lines.append("")

    # ============================================================
    # HMM Transition analysis
    # ============================================================
    lines.append("## 10. HMM transition analysis "
                 "(entry @ +30s, race 1.00/0.50, w=120s)")
    lines.append("")
    lines.append("| Year | Group | n | PT% | SL% | Mean $ | PF |")
    lines.append("|---|---|--:|--:|--:|--:|--:|")
    for year, df in dfs.items():
        sub_y = df[df["entry_candidate_s"] == 30]
        groups = [
            ("Stable same-state", ~sub_y[
                "hmm_state_changed_since_signal"]),
            ("Recent transition (signal->dec)", sub_y[
                "hmm_state_changed_since_signal"]),
            ("Transition INTO state 3",
             sub_y["hmm_state_changed_since_signal"]
             & (sub_y["hmm_state_at_decision"] == 3)),
            ("Transition OUT OF state 3",
             sub_y["hmm_state_changed_since_signal"]
             & (sub_y["hmm_state_at_confirmed_signal"] == 3)
             & (sub_y["hmm_state_at_decision"] != 3)),
        ]
        for label, mask in groups:
            sub = sub_y[mask]
            r = race_stats(sub, 1.00, 0.50, 120, "exit_at_close")
            if r["n"] == 0:
                continue
            lines.append(
                f"| {year} | {label} | {r['n']:,} | "
                f"{fmt_p(r['pt_pct'])} | "
                f"{fmt_p(r['sl_pct'])} | "
                f"{fmt_d(r['mean'])} | {r['pf']:.2f} |")
    lines.append("")

    # ============================================================
    # Verdict
    # ============================================================
    lines.append("## Verdict")
    lines.append("")
    yrs_passing = sum(
        1 for y, b in best_per_year.items() if b["mean"] > 0)
    lines.append(
        f"**Years with at least one slice at PF >= 1.10**: "
        f"{len(best_per_year)} / {len(dfs)}.")
    if best_per_year:
        for y, b in best_per_year.items():
            lines.append(
                f"- {y}: best slice +{b['ec_s']}s, "
                f"{b['pt_R']}/{b['sl_R']}, {b['w']}s — "
                f"{fmt_d(b['mean'])}/trade PF {b['pf']:.2f} "
                f"on n={b['n']:,}")
    lines.append("")
    if len(best_per_year) >= 2:
        lines.append(
            "Cross-year stability table above tells whether the same "
            "spec holds across years.")
    else:
        lines.append(
            "**Insufficient cross-year stability** — fewer than 2 "
            "years yielded any slice at PF >= 1.10 + n >= 200. "
            "Per the success criteria, the fast-resolution edge does "
            "not exist in this event family.")
    lines.append("")

    out_path = OUT / "FAST_RES_REPORT.md"
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport: {out_path}")
    print(f"\nQuick scan — best slice per year:")
    for y, b in best_per_year.items():
        print(f"  {y}: +{b['ec_s']}s {b['pt_R']}/{b['sl_R']} "
               f"w={b['w']}s n={b['n']:,} mean=${b['mean']:.2f} "
               f"PF={b['pf']:.2f}")


if __name__ == "__main__":
    main()
