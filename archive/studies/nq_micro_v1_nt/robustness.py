"""Robustness validation for flip2conf_dir_efficiency filter.

Sections:
  1. Threshold sensitivity — 0.20, 0.25, 0.30, 0.35, 0.40, 0.50
  2. Bootstrap CIs per year (1,000 samples)
  3. Rolling 50- and 100-trade PnL stability
  4. 2022 failure diagnostic — kept vs filtered-out

All derived from existing offline portfolio outputs. NT-runtime
parity is structural (proven in NT_VALIDATION_REPORT.md), so
threshold changes don't require re-running NT.
"""

from __future__ import annotations
import os, sys, json
from pathlib import Path
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
os.chdir(project_root)

PORT = Path("collectors/collector_v2/results/portfolio")
OUT = Path("studies/nq_micro_v1_nt/results")
OUT.mkdir(parents=True, exist_ok=True)
YEARS = [2020, 2021, 2022, 2023, 2024, 2025, 2026]
THRESHOLDS = [0.20, 0.25, 0.30, 0.35, 0.40, 0.50]
SEED = 42


def fmt_d(v):
    if v is None or (isinstance(v, float)
                       and (pd.isna(v) or np.isinf(v))):
        return "—"
    return f"${v:,.2f}" if abs(v) < 1000 else f"${v:,.0f}"


def fmt_p(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{100*v:.2f}%"


def max_dd(s):
    if len(s) == 0:
        return 0.0
    cum = pd.Series(s).cumsum().values
    peak = np.maximum.accumulate(cum)
    return float((cum - peak).min())


def stats(pnl):
    s = pd.Series(pnl).dropna()
    n = len(s)
    if n == 0:
        return {"n": 0, "wr": None, "mean": None, "sum": None,
                "pf": None, "max_dd": None}
    wins = s[s > 0]; losses = s[s < 0]
    pf = (wins.sum() / abs(losses.sum())
          if len(losses) and losses.sum() != 0 else float("inf"))
    return {
        "n": n,
        "wr": float((s > 0).mean()),
        "mean": float(s.mean()),
        "sum": float(s.sum()),
        "pf": float(pf),
        "max_dd": max_dd(s),
    }


def load_year_with_eff(year: int) -> pd.DataFrame:
    """RTH trades for one year with flip2conf_dir_efficiency joined
    on decision_event_id from micro_pre."""
    base = pd.read_parquet(PORT / f"NQ_{year}/trades.parquet")
    micro = pd.read_parquet(PORT / f"NQ_{year}/micro_pre.parquet")
    base = base[base["session"] == "RTH"].copy()
    keep = ["decision_event_id", "flip2conf_dir_efficiency",
              "w60s_dir_efficiency", "w60s_sign_flip_rate",
              "w60s_net_move_atr",
              "flip2conf_net_move_atr",
              "bar1_internal_dir_efficiency",
              "atr_1m_at_signal",
              "bar1_extreme_pos_pct",
              "bar1_giveback_from_ext_atr"]
    keep = [c for c in keep if c in micro.columns]
    micro_keep = micro[keep]
    df = base.merge(micro_keep, on="decision_event_id", how="left")
    df["year"] = year
    return df


def all_years_df() -> pd.DataFrame:
    frames = [load_year_with_eff(yr) for yr in YEARS]
    return pd.concat(frames, ignore_index=True)


# ============== Section 1: threshold sensitivity ==============
def threshold_sensitivity(df: pd.DataFrame, lines: list):
    lines.append("## 1. Threshold sensitivity")
    lines.append("")
    lines.append("Sweeps `flip2conf_dir_efficiency` threshold across "
                 "0.20-0.50. NT parity is structural (proven in "
                 "NT_VALIDATION_REPORT.md), so each threshold's "
                 "economics derive directly from filtering the "
                 "baseline pool — no new NT runs needed.")
    lines.append("")
    rows_by_thr = {}
    for thr in THRESHOLDS:
        per_year_rows = []
        for yr in YEARS:
            sub = df[df["year"] == yr]
            kept = sub[sub["flip2conf_dir_efficiency"] >= thr]
            s = stats(kept["net_pnl"])
            per_year_rows.append({"year": yr, "threshold": thr,
                                       **s})
        rows_by_thr[thr] = per_year_rows

    # Aggregate per threshold
    lines.append("### Aggregate per threshold (7-year totals)")
    lines.append("")
    lines.append("| Threshold | n | %kept | WR | Mean $ | PF | "
                 "Total $ | Max DD | Years +mean |")
    lines.append(
        "|---|--:|--:|--:|--:|--:|--:|--:|--:|")
    base_n = len(df)
    for thr in THRESHOLDS:
        rows = rows_by_thr[thr]
        agg = stats(
            df[df["flip2conf_dir_efficiency"] >= thr]["net_pnl"])
        years_pos = sum(1 for r in rows
                          if r.get("mean") is not None
                          and r["mean"] > 0)
        pf_str = (f"{agg['pf']:.2f}"
                  if agg.get("pf") and not np.isinf(agg["pf"])
                  else "—")
        pct_kept = (agg["n"] / base_n) if base_n else 0
        lines.append(
            f"| {thr:.2f} | {agg['n']:,} | "
            f"{fmt_p(pct_kept)} | "
            f"{fmt_p(agg.get('wr'))} | "
            f"{fmt_d(agg.get('mean'))} | {pf_str} | "
            f"{fmt_d(agg.get('sum'))} | "
            f"{fmt_d(agg.get('max_dd'))} | "
            f"{years_pos}/7 |")
    lines.append("")

    # Per-year by threshold
    lines.append("### Per-year per-threshold mean $ and PF")
    lines.append("")
    lines.append("| Year | "
                 + " | ".join(f"thr={t:.2f}" for t in THRESHOLDS)
                 + " |")
    lines.append("|---|" + "|".join(["--:"] * len(THRESHOLDS)) + "|")
    for yr in YEARS:
        cells = []
        for thr in THRESHOLDS:
            r = next(r for r in rows_by_thr[thr] if r["year"] == yr)
            mean = r.get("mean")
            n = r.get("n", 0)
            cells.append(f"{fmt_d(mean)} (n={n})")
        lines.append(f"| {yr} | " + " | ".join(cells) + " |")
    lines.append("")

    return rows_by_thr


# ============== Section 2: bootstrap CI per year ==============
def bootstrap_section(df: pd.DataFrame, lines: list,
                          threshold: float = 0.30,
                          n_bootstrap: int = 2000):
    lines.append("## 2. Bootstrap confidence intervals "
                 f"(threshold = {threshold:.2f})")
    lines.append("")
    lines.append(f"For each year, resample trades with replacement "
                 f"{n_bootstrap:,} times. Report distribution of "
                 "mean per-trade PnL.")
    lines.append("")
    rng = np.random.default_rng(SEED)
    rows = []
    for yr in YEARS:
        sub = df[(df["year"] == yr)
                    & (df["flip2conf_dir_efficiency"]
                        >= threshold)]
        pnl = sub["net_pnl"].values
        n = len(pnl)
        if n < 2:
            rows.append({
                "year": yr, "n": n, "obs_mean": None,
                "boot_mean": None, "boot_std": None,
                "boot_p05": None, "boot_p95": None,
                "p_zero_or_better_below": None,
            })
            continue
        boot_means = np.empty(n_bootstrap)
        for i in range(n_bootstrap):
            sample = rng.choice(pnl, size=n, replace=True)
            boot_means[i] = sample.mean()
        rows.append({
            "year": yr, "n": n,
            "obs_mean": float(pnl.mean()),
            "boot_mean": float(boot_means.mean()),
            "boot_std": float(boot_means.std()),
            "boot_p05": float(np.percentile(boot_means, 5)),
            "boot_p95": float(np.percentile(boot_means, 95)),
            "p_zero_or_below": float(
                (boot_means <= 0).mean()),
        })
    lines.append("| Year | n | Observed mean $ | Boot mean $ | "
                 "Boot std | 5th %ile | 95th %ile | P(mean ≤ 0) |")
    lines.append(
        "|---|--:|--:|--:|--:|--:|--:|--:|")
    for r in rows:
        if r["obs_mean"] is None:
            lines.append(f"| {r['year']} | {r['n']} | — | — | — | "
                          "— | — | — |")
            continue
        lines.append(
            f"| {r['year']} | {r['n']} | "
            f"{fmt_d(r['obs_mean'])} | "
            f"{fmt_d(r['boot_mean'])} | "
            f"{fmt_d(r['boot_std'])} | "
            f"{fmt_d(r['boot_p05'])} | "
            f"{fmt_d(r['boot_p95'])} | "
            f"{fmt_p(r['p_zero_or_below'])} |")
    lines.append("")
    # Plain-English interpretation
    n_robust = sum(1 for r in rows
                     if r.get("boot_p05") is not None
                     and r["boot_p05"] > 0)
    lines.append(f"- Years where 5th-%ile bootstrap mean > $0: "
                  f"**{n_robust}/7**")
    n_marginal = sum(1 for r in rows
                       if r.get("boot_p05") is not None
                       and r["boot_p05"] <= 0
                       and r["boot_p95"] > 0)
    lines.append(f"- Years where bootstrap CI straddles zero "
                  f"(positive mean but not robust): **{n_marginal}/7**")
    lines.append("")
    return rows


# ============== Section 3: rolling window stability ==============
def rolling_section(df: pd.DataFrame, lines: list,
                       threshold: float = 0.30):
    lines.append("## 3. Rolling-window stability "
                 f"(threshold = {threshold:.2f})")
    lines.append("")
    lines.append("Computes rolling 50- and 100-trade window mean "
                 "PnL across the chronologically-ordered filtered "
                 "trade stream (all years concatenated).")
    lines.append("")
    sub = df[df["flip2conf_dir_efficiency"] >= threshold].copy()
    sub = sub.sort_values("entry_ts").reset_index(drop=True)
    sub["roll_50"] = sub["net_pnl"].rolling(50).mean()
    sub["roll_100"] = sub["net_pnl"].rolling(100).mean()

    # Worst windows
    worst_50 = sub.dropna(subset=["roll_50"]).nsmallest(
        5, "roll_50")
    best_50 = sub.dropna(subset=["roll_50"]).nlargest(5, "roll_50")
    worst_100 = sub.dropna(subset=["roll_100"]).nsmallest(
        5, "roll_100")
    best_100 = sub.dropna(subset=["roll_100"]).nlargest(
        5, "roll_100")
    lines.append("### Worst 5 rolling-50 windows")
    lines.append("")
    lines.append("| Date (entry_ts of window-end trade) | "
                 "Roll 50 mean $ |")
    lines.append("|---|--:|")
    for _, r in worst_50.iterrows():
        dt = pd.Timestamp(int(r["entry_ts"]), tz="UTC")
        lines.append(f"| {dt:%Y-%m-%d %H:%M} | "
                      f"{fmt_d(r['roll_50'])} |")
    lines.append("")
    lines.append("### Best 5 rolling-50 windows")
    lines.append("")
    lines.append("| Date | Roll 50 mean $ |")
    lines.append("|---|--:|")
    for _, r in best_50.iterrows():
        dt = pd.Timestamp(int(r["entry_ts"]), tz="UTC")
        lines.append(f"| {dt:%Y-%m-%d %H:%M} | "
                      f"{fmt_d(r['roll_50'])} |")
    lines.append("")
    lines.append("### Rolling-100 worst / best")
    lines.append("")
    lines.append("| Type | Date | Roll 100 mean $ |")
    lines.append("|---|---|--:|")
    for _, r in worst_100.iterrows():
        dt = pd.Timestamp(int(r["entry_ts"]), tz="UTC")
        lines.append(f"| worst | {dt:%Y-%m-%d %H:%M} | "
                      f"{fmt_d(r['roll_100'])} |")
    for _, r in best_100.iterrows():
        dt = pd.Timestamp(int(r["entry_ts"]), tz="UTC")
        lines.append(f"| best | {dt:%Y-%m-%d %H:%M} | "
                      f"{fmt_d(r['roll_100'])} |")
    lines.append("")

    # Aggregate distribution
    lines.append("### Distribution of rolling-window means")
    lines.append("")
    lines.append("| Quantile | Roll 50 mean $ | Roll 100 mean $ |")
    lines.append("|---|--:|--:|")
    for q in [0.05, 0.25, 0.50, 0.75, 0.95]:
        v50 = sub["roll_50"].quantile(q)
        v100 = sub["roll_100"].quantile(q)
        lines.append(f"| p{int(q*100)} | {fmt_d(v50)} | "
                      f"{fmt_d(v100)} |")
    lines.append(f"| min | {fmt_d(sub['roll_50'].min())} | "
                  f"{fmt_d(sub['roll_100'].min())} |")
    lines.append(f"| max | {fmt_d(sub['roll_50'].max())} | "
                  f"{fmt_d(sub['roll_100'].max())} |")
    lines.append(f"| % of windows positive | "
                  f"{fmt_p((sub['roll_50'] > 0).mean())} | "
                  f"{fmt_p((sub['roll_100'] > 0).mean())} |")
    lines.append("")
    sub.to_parquet(
        OUT / "rolling_window_pnl.parquet", index=False)


# ============== Section 4: 2022 failure diagnostic ==============
def diagnostic_2022(df: pd.DataFrame, lines: list,
                       threshold: float = 0.30):
    lines.append(f"## 4. 2022 failure diagnostic "
                  f"(threshold = {threshold:.2f})")
    lines.append("")
    lines.append("2022 is the only loser year (-$39.53/trade, "
                 "289 trades). Diagnose the kept-vs-filtered-out "
                 "split: what's different about the trades the "
                 "filter accepts in this high-ATR regime?")
    lines.append("")
    sub2022 = df[df["year"] == 2022].copy()
    kept = sub2022[
        sub2022["flip2conf_dir_efficiency"] >= threshold]
    rejected = sub2022[
        sub2022["flip2conf_dir_efficiency"] < threshold]

    lines.append(f"- 2022 baseline: {len(sub2022):,} RTH trades")
    lines.append(f"- Kept by filter: {len(kept):,} trades, "
                  f"mean {fmt_d(kept['net_pnl'].mean())}")
    lines.append(f"- Filtered out: {len(rejected):,} trades, "
                  f"mean {fmt_d(rejected['net_pnl'].mean())}")
    lines.append("")
    # If filtered-out is BETTER, the filter is inverting on 2022
    delta = kept["net_pnl"].mean() - rejected["net_pnl"].mean()
    lines.append(f"- Δ (kept - rejected): {fmt_d(delta)} "
                  f"per trade — "
                  + ("filter is INVERTING on 2022 (kept worse "
                     "than rejected)"
                     if delta < 0 else
                     "filter is HELPING on 2022 but not enough"))
    lines.append("")

    # Compare key features kept vs rejected vs other years' kept
    diag_features = [
        "atr_1m_at_signal",
        "flip2conf_net_move_atr",
        "w60s_net_move_atr",
        "bar1_internal_dir_efficiency",
        "bar1_extreme_pos_pct",
        "bar1_giveback_from_ext_atr",
        "w60s_sign_flip_rate",
        "flip2conf_dir_efficiency",
    ]
    lines.append("### Feature medians: 2022 kept vs 2022 rejected "
                 "vs 2024-2025 kept (the working pocket)")
    lines.append("")
    pocket = df[(df["year"].isin([2024, 2025]))
                  & (df["flip2conf_dir_efficiency"]
                      >= threshold)]
    lines.append("| Feature | 2022 kept | 2022 rejected | "
                 "24-25 kept | 22kept - 22rej | 22kept - 24-25kept |")
    lines.append("|---|--:|--:|--:|--:|--:|")
    for f in diag_features:
        if f not in df.columns:
            continue
        m22k = kept[f].median()
        m22r = rejected[f].median()
        m24k = pocket[f].median()
        lines.append(
            f"| {f} | {m22k:.4f} | {m22r:.4f} | {m24k:.4f} | "
            f"{m22k - m22r:+.4f} | {m22k - m24k:+.4f} |")
    lines.append("")

    # ATR distribution comparison
    lines.append("### ATR distribution — 2022 kept vs working pocket")
    lines.append("")
    lines.append("| Quantile | 2022 kept atr_1m | 24-25 kept atr_1m | Δ |")
    lines.append("|---|--:|--:|--:|")
    for q in [0.10, 0.25, 0.50, 0.75, 0.90]:
        a22 = kept["atr_1m_at_signal"].quantile(q)
        a24 = pocket["atr_1m_at_signal"].quantile(q)
        lines.append(f"| p{int(q*100)} | {a22:.2f} | "
                      f"{a24:.2f} | {a22-a24:+.2f} |")
    lines.append("")

    # PnL bucketed by ATR within 2022 kept
    lines.append("### 2022 kept PnL bucketed by atr_1m_at_signal")
    lines.append("")
    if len(kept) >= 4:
        # Quartile buckets
        kept_sorted = kept.sort_values("atr_1m_at_signal")
        kept_sorted["atr_q"] = pd.qcut(
            kept_sorted["atr_1m_at_signal"], q=4,
            labels=["Q1 lowest", "Q2", "Q3", "Q4 highest"],
            duplicates="drop")
        atr_buckets = kept_sorted.groupby("atr_q",
                                              observed=True).agg(
            n=("net_pnl", "count"),
            atr_med=("atr_1m_at_signal", "median"),
            mean_pnl=("net_pnl", "mean"),
            sum_pnl=("net_pnl", "sum"),
            wr=("net_pnl", lambda s: (s > 0).mean()),
        )
        lines.append("| Quartile | n | atr_1m median | "
                     "Mean $ | Total $ | WR |")
        lines.append("|---|--:|--:|--:|--:|--:|")
        for q, r in atr_buckets.iterrows():
            lines.append(
                f"| {q} | {int(r['n'])} | "
                f"{r['atr_med']:.2f} | "
                f"{fmt_d(r['mean_pnl'])} | "
                f"{fmt_d(r['sum_pnl'])} | "
                f"{fmt_p(r['wr'])} |")
        lines.append("")

    # PnL bucketed by flip2conf_dir_efficiency within 2022 kept
    lines.append("### 2022 kept PnL bucketed by "
                 "flip2conf_dir_efficiency value")
    lines.append("")
    if len(kept) >= 4:
        kept_sorted = kept.sort_values("flip2conf_dir_efficiency")
        kept_sorted["eff_q"] = pd.qcut(
            kept_sorted["flip2conf_dir_efficiency"], q=4,
            labels=["Q1 lowest", "Q2", "Q3", "Q4 highest"],
            duplicates="drop")
        eff_buckets = kept_sorted.groupby("eff_q",
                                              observed=True).agg(
            n=("net_pnl", "count"),
            eff_med=("flip2conf_dir_efficiency", "median"),
            mean_pnl=("net_pnl", "mean"),
            sum_pnl=("net_pnl", "sum"),
        )
        lines.append("| Quartile | n | eff median | Mean $ | "
                     "Total $ |")
        lines.append("|---|--:|--:|--:|--:|")
        for q, r in eff_buckets.iterrows():
            lines.append(
                f"| {q} | {int(r['n'])} | {r['eff_med']:.3f} | "
                f"{fmt_d(r['mean_pnl'])} | "
                f"{fmt_d(r['sum_pnl'])} |")
        lines.append("")

    # Direction split within 2022 kept
    lines.append("### 2022 kept direction split")
    lines.append("")
    long_k = kept[kept["direction"] == 1]
    short_k = kept[kept["direction"] == -1]
    lines.append("| Direction | n | WR | Mean $ | Total $ |")
    lines.append("|---|--:|--:|--:|--:|")
    for label, sub in [("Long", long_k), ("Short", short_k)]:
        s = stats(sub["net_pnl"])
        lines.append(
            f"| {label} | {s['n']} | {fmt_p(s.get('wr'))} | "
            f"{fmt_d(s.get('mean'))} | {fmt_d(s.get('sum'))} |")
    lines.append("")


def main():
    print("Loading 7 years of data...")
    df = all_years_df()
    print(f"Loaded {len(df):,} RTH trades across {len(YEARS)} years")
    print()

    lines = []
    lines.append("# NQ V_A flip2conf Filter — Robustness Validation")
    lines.append("")
    lines.append("Four-section robustness study of the NT-validated "
                 "`flip2conf_dir_efficiency >= 0.30` filter.")
    lines.append("")

    threshold_sensitivity(df, lines)
    bootstrap_section(df, lines, threshold=0.30,
                          n_bootstrap=2000)
    rolling_section(df, lines, threshold=0.30)
    diagnostic_2022(df, lines, threshold=0.30)

    out_p = OUT / "NQ_MICRO_FILTER_ROBUSTNESS.md"
    out_p.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport: {out_p}")


if __name__ == "__main__":
    main()
