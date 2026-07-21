"""Pullback Scalp v1 feasibility analysis.

Loads each variant's trades.parquet, computes the full requested
stats, and produces SCALP_V1_FEASIBILITY.md.
"""

from __future__ import annotations
import os, sys, json
from pathlib import Path
import numpy as np
import pandas as pd
import pytz

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
os.chdir(project_root)

CT = pytz.timezone("America/Chicago")
RES = Path("collectors/collector_v2/results/scalp_v1")
OUT = Path("studies/scalp_v1/results")
OUT.mkdir(parents=True, exist_ok=True)


def fmt_d(v):
    if v is None or (isinstance(v, float)
                       and (pd.isna(v) or np.isinf(v))):
        return "—"
    return f"${v:,.2f}" if abs(v) < 1000 else f"${v:,.0f}"


def fmt_p(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{100*v:.1f}%"


def max_dd_pnl(s):
    if len(s) == 0: return 0.0
    cum = pd.Series(s).cumsum().values
    peak = np.maximum.accumulate(cum)
    return float((cum - peak).min())


def rolling_dd(net_pnl: pd.Series, window: int) -> float:
    """Worst rolling-window cumulative PnL (max DD WITHIN any
    window)."""
    if len(net_pnl) < window:
        return 0.0
    cum = net_pnl.cumsum().values
    # max drawdown using rolling: for each rolling window, compute
    # min(cum[i+1..i+w]) - cum[i]. Direct approach for clarity.
    worst = 0.0
    for i in range(len(cum) - window):
        win_cum = cum[i:i+window+1]
        run_max = np.maximum.accumulate(win_cum)
        dd = (win_cum - run_max).min()
        if dd < worst:
            worst = float(dd)
    return worst


def analyze_variant(label: str, year: int) -> dict:
    d = RES / f"{label}_NQ_{year}"
    tp = d / "trades.parquet"
    if not tp.exists():
        return {"label": label, "year": year,
                "missing": True}
    df = pd.read_parquet(tp)
    cfg_p = d / "config.json"
    cfg = json.load(open(cfg_p)) if cfg_p.exists() else {}
    diag_p = d / "diag.json"
    diag = json.load(open(diag_p)) if diag_p.exists() else {}
    n = len(df)
    if n == 0:
        return {"label": label, "year": year, "n": 0,
                "config": cfg, "diag": diag}

    # Daily aggregation (CT date of entry)
    df["entry_dt_ct"] = pd.to_datetime(
        df["entry_ts"], unit="ns", utc=True).dt.tz_convert(CT)
    df["day"] = df["entry_dt_ct"].dt.date
    daily = df.groupby("day").agg(
        n=("net_pnl", "count"),
        pnl=("net_pnl", "sum"),
        wr=("net_pnl", lambda s: (s > 0).mean()),
    )
    n_days = len(daily)
    trades_per_day = daily["n"]
    daily_pnl = daily["pnl"]
    winning_days = (daily["pnl"] > 0).sum()

    df_sorted = df.sort_values("entry_ts").reset_index(drop=True)
    s = df_sorted["net_pnl"]
    wins = s[s > 0]; losses = s[s < 0]
    pf = (wins.sum() / abs(losses.sum())
            if len(losses) and losses.sum() != 0 else float("inf"))

    # Rolling drawdowns
    roll20 = rolling_dd(s, 20)
    roll50 = rolling_dd(s, 50)

    return {
        "label": label,
        "year": year,
        "config": cfg,
        "diag": diag,
        "n": n,
        "n_days": n_days,
        "trades_per_day_median": float(trades_per_day.median()),
        "trades_per_day_mean": float(trades_per_day.mean()),
        "trades_per_day_min": int(trades_per_day.min()),
        "trades_per_day_max": int(trades_per_day.max()),
        "wr": float((s > 0).mean()),
        "mean": float(s.mean()),
        "median": float(s.median()),
        "total": float(s.sum()),
        "pf": float(pf),
        "max_dd": max_dd_pnl(s),
        "rolling_20_dd": roll20,
        "rolling_50_dd": roll50,
        "avg_win": float(wins.mean()) if len(wins) else 0.0,
        "avg_loss": float(losses.mean()) if len(losses) else 0.0,
        "median_hold_s": float(df["hold_s"].median()),
        "mean_hold_s": float(df["hold_s"].mean()),
        "daily_pnl_median": float(daily_pnl.median()),
        "daily_pnl_mean": float(daily_pnl.mean()),
        "daily_pnl_p10": float(daily_pnl.quantile(0.10)),
        "daily_pnl_p25": float(daily_pnl.quantile(0.25)),
        "daily_pnl_p75": float(daily_pnl.quantile(0.75)),
        "daily_pnl_p90": float(daily_pnl.quantile(0.90)),
        "worst_day": float(daily_pnl.min()),
        "best_day": float(daily_pnl.max()),
        "winning_days_pct": float(winning_days / n_days),
        "exit_pt_pct": float(
            (df["exit_reason"] == "pt").mean()),
        "exit_sl_pct": float(
            (df["exit_reason"]
             .isin(["sl", "sl_intra_both"])).mean()),
        "exit_max_hold_pct": float(
            (df["exit_reason"] == "max_hold").mean()),
        # Top 1% dependence
        "top_1pct_share_of_pnl": (
            float(s.nlargest(max(1, int(n * 0.01))).sum()
                  / max(abs(s.sum()), 1))
            if s.sum() != 0 else float("nan")),
    }


def variant_table(results: list[dict], lines: list):
    lines.append("## Per-variant feasibility scoreboard")
    lines.append("")
    lines.append("| Variant | n | trades/day "
                 "(med/mean) | WR | Mean $ | Median $ | PF | "
                 "Total $ | Max DD | Roll-20 DD | Roll-50 DD | "
                 "Avg Win | Avg Loss | Med Hold s | "
                 "Daily $ med | Worst day | Win days % | "
                 "PT/SL/Hold mix |")
    lines.append("|" + "|".join(["---"] * 17) + "|")
    for r in results:
        if r.get("missing"):
            lines.append(f"| {r['label']} (NQ {r['year']}) "
                          "| — | — | — | — | — | — | — | — | "
                          "— | — | — | — | — | — | — | — |")
            continue
        if r.get("n", 0) == 0:
            lines.append(f"| {r['label']} (NQ {r['year']}) | "
                          "0 | 0/0 | — | — | — | — | — | — | "
                          "— | — | — | — | — | — | — | — |")
            continue
        mix = (f"{fmt_p(r['exit_pt_pct'])} / "
                 f"{fmt_p(r['exit_sl_pct'])} / "
                 f"{fmt_p(r['exit_max_hold_pct'])}")
        lines.append(
            f"| {r['label']} (NQ {r['year']}) | "
            f"{r['n']:,} | "
            f"{r['trades_per_day_median']:.0f} / "
            f"{r['trades_per_day_mean']:.0f} | "
            f"{fmt_p(r['wr'])} | "
            f"{fmt_d(r['mean'])} | "
            f"{fmt_d(r['median'])} | "
            f"{r['pf']:.2f} | "
            f"{fmt_d(r['total'])} | "
            f"{fmt_d(r['max_dd'])} | "
            f"{fmt_d(r['rolling_20_dd'])} | "
            f"{fmt_d(r['rolling_50_dd'])} | "
            f"{fmt_d(r['avg_win'])} | "
            f"{fmt_d(r['avg_loss'])} | "
            f"{r['median_hold_s']:.1f} | "
            f"{fmt_d(r['daily_pnl_median'])} | "
            f"{fmt_d(r['worst_day'])} | "
            f"{fmt_p(r['winning_days_pct'])} | {mix} |")
    lines.append("")


def daily_distribution_table(results: list[dict], lines: list):
    lines.append("## Daily PnL distribution")
    lines.append("")
    lines.append("| Variant | Best day | p90 | p75 | Median | "
                 "p25 | p10 | Worst day |")
    lines.append("|---|--:|--:|--:|--:|--:|--:|--:|")
    for r in results:
        if r.get("missing") or r.get("n", 0) == 0:
            continue
        lines.append(
            f"| {r['label']} (NQ {r['year']}) | "
            f"{fmt_d(r['best_day'])} | "
            f"{fmt_d(r['daily_pnl_p90'])} | "
            f"{fmt_d(r['daily_pnl_p75'])} | "
            f"{fmt_d(r['daily_pnl_median'])} | "
            f"{fmt_d(r['daily_pnl_p25'])} | "
            f"{fmt_d(r['daily_pnl_p10'])} | "
            f"{fmt_d(r['worst_day'])} |")
    lines.append("")


def goal_score(r: dict) -> str:
    """Simple bullet for each variant against the user goals."""
    goals = []
    tpd = r["trades_per_day_median"]
    in_band = 20 <= tpd <= 30
    near_band = 10 <= tpd < 20 or 30 < tpd <= 60
    goals.append(
        ("✅" if in_band else
         ("⚠️" if near_band else "❌"))
        + f" trades/day ~20-30 (got {tpd:.0f})")
    goals.append(("✅" if r["wr"] >= 0.55 else
                       "❌")
                  + f" WR ~55%+ (got {fmt_p(r['wr'])})")
    goals.append(
        ("✅" if r["daily_pnl_median"] >= 500 else "❌")
        + f" daily $ ~500 (got "
          f"{fmt_d(r['daily_pnl_median'])})")
    goals.append(
        ("⚠️ check" if r["top_1pct_share_of_pnl"] > 0.5
         else "✅ low outlier dep")
        + f" (top-1%-share = "
          f"{fmt_p(r['top_1pct_share_of_pnl'])})")
    return "  - " + "\n  - ".join(goals)


def main():
    variants = [
        ("v1_base", 2025),
        ("v2_tight", 2025),
        ("v3_asym", 2025),
        ("v4_tight_asym", 2025),
        ("v5_2to1", 2025),
    ]
    results = [analyze_variant(lbl, yr) for lbl, yr in variants]

    lines = []
    lines.append("# Pullback Scalp v1 — Feasibility Report")
    lines.append("")
    lines.append("First-cut feasibility test of the micro pullback "
                 "continuation scalp on NQ 2025 RTH. Four mechanical "
                 "variants, no grid search. Goal: determine whether "
                 "this strategy class can approach 20-30 trades/day "
                 "at ~55% WR with ~$500/day average.")
    lines.append("")
    lines.append("## Variants tested")
    lines.append("")
    lines.append("| Variant | Impulse |body|/atr | Pullback range | "
                 "Re-accel | Bracket PT/SL | Max Hold | Cooldown |")
    lines.append("|---|--:|--:|--:|--:|--:|--:|")
    for r in results:
        if r.get("missing"):
            lines.append(f"| {r['label']} | (run missing) | — | "
                          "— | — | — | — |")
            continue
        c = r.get("config", {})
        lines.append(
            f"| {r['label']} | {c.get('impulse_body_atr', '—')} | "
            f"{c.get('pullback_min_atr', '—')}-"
            f"{c.get('pullback_max_atr', '—')} | "
            f"{c.get('reaccel_atr', '—')} | "
            f"{c.get('pt_atr', '—')}/{c.get('sl_atr', '—')} | "
            f"{c.get('max_hold_s', '—')}s | "
            f"{c.get('cooldown_s', '—')}s |")
    lines.append("")

    variant_table(results, lines)
    daily_distribution_table(results, lines)

    # Per-variant goal alignment
    lines.append("## Goal alignment per variant")
    lines.append("")
    for r in results:
        if r.get("missing") or r.get("n", 0) == 0:
            continue
        lines.append(f"### {r['label']}")
        lines.append(goal_score(r))
        lines.append("")

    # Verdict
    lines.append("## Verdict")
    lines.append("")
    valid = [r for r in results
                if not r.get("missing") and r.get("n", 0) > 0]
    if not valid:
        lines.append("No valid variants to evaluate.")
    else:
        in_band = [r for r in valid
                       if 20 <= r["trades_per_day_median"] <= 30
                       and r["wr"] >= 0.50
                       and r["mean"] >= 0]
        any_positive = [r for r in valid if r["mean"] > 0]
        lines.append(f"- Variants in 20-30 trades/day band with "
                      f"≥50% WR AND positive mean: "
                      f"**{len(in_band)}/{len(valid)}**")
        lines.append(f"- Variants with ANY positive mean per-trade: "
                      f"**{len(any_positive)}/{len(valid)}**")
        lines.append("")
        if not any_positive:
            lines.append("⚠️ **All four variants are net negative.** "
                         "The base mechanical setup at this PT/SL "
                         "scale produces too many noisy fills. "
                         "Cost model ($10 round trip) eats into "
                         "PT-sized targets significantly.")
        else:
            best = max(any_positive, key=lambda r: r["mean"])
            lines.append(f"Best variant by mean per-trade: "
                          f"**{best['label']}** "
                          f"(mean {fmt_d(best['mean'])}, "
                          f"WR {fmt_p(best['wr'])}, "
                          f"trades/day {best['trades_per_day_median']:.0f}).")
    lines.append("")

    # Diagnostics: where does the funnel narrow?
    lines.append("## Funnel diagnostics (per variant)")
    lines.append("")
    lines.append("| Variant | RTH impulses | Pullback confirmed | "
                 "Re-accel entries | Trades completed | "
                 "PT exits | SL exits | Hold-stop exits |")
    lines.append("|---|--:|--:|--:|--:|--:|--:|--:|")
    for r in results:
        if r.get("missing"): continue
        d = r.get("diag", {})
        lines.append(
            f"| {r['label']} | "
            f"{d.get('rth_impulses_qualified', 0):,} | "
            f"{d.get('pullback_confirmed', 0):,} | "
            f"{d.get('reaccel_entries', 0):,} | "
            f"{d.get('trades_completed', 0):,} | "
            f"{d.get('exits_pt', 0):,} | "
            f"{d.get('exits_sl', 0):,} | "
            f"{d.get('exits_max_hold', 0):,} |")
    lines.append("")

    out_p = OUT / "SCALP_V1_FEASIBILITY.md"
    out_p.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport: {out_p}")
    # Save summary JSON
    (OUT / "summary.json").write_text(
        json.dumps(results, indent=2, default=str),
        encoding="utf-8")


if __name__ == "__main__":
    main()
