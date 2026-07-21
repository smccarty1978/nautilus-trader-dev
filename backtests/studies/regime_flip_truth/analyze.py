"""Analyze the Regime Flip Truth datasets -> flip_truth_summary.md.

STRICTLY DESCRIPTIVE. No ML, no optimization, no parameter search. We only:
  - report outcome distributions (milestone reach rates)
  - report path-quality distributions (clean/persistent/elite)
  - measure which entry features most separate Elite vs non-Elite
    (Cohen's d, rank ordering, decile monotonicity)
  - measure how early Elite is separable using the checkpoint panel

Run AFTER run_collector.py has produced per-year datasets.
    python studies/regime_flip_truth/analyze.py
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd

RES = Path("studies/regime_flip_truth/results")
YEARS = (2021, 2022, 2023, 2024)
MILESTONES = ["reached_0_5_atr", "reached_1_0_atr",
              "reached_2_0_atr", "reached_3_0_atr"]
MS_LABEL = {"reached_0_5_atr": "0.5 ATR", "reached_1_0_atr": "1.0 ATR",
            "reached_2_0_atr": "2.0 ATR", "reached_3_0_atr": "3.0 ATR"}
LABELS = ["clean_trend_a", "clean_trend_b", "persistent_trend", "elite_trend"]
CHECKPOINT_ORDER = ["entry", "+30s", "+60s", "+90s", "+120s", "+180s",
                    "Bar2", "Bar3", "Bar5"]


def load() -> tuple[pd.DataFrame, pd.DataFrame]:
    ev_parts, ck_parts = [], []
    for y in YEARS:
        ep = RES / f"flip_truth_dataset_{y}.parquet"
        cp = RES / f"flip_checkpoint_dataset_{y}.parquet"
        if ep.exists():
            d = pd.read_parquet(ep); d["year"] = y
            # make event_id globally unique across years
            d["uid"] = d["year"] * 10_000_000 + d["event_id"]
            ev_parts.append(d)
        if cp.exists():
            c = pd.read_parquet(cp); c["year"] = y
            c["uid"] = c["year"] * 10_000_000 + c["event_id"]
            ck_parts.append(c)
    ev = pd.concat(ev_parts, ignore_index=True)
    ck = pd.concat(ck_parts, ignore_index=True)
    return ev, ck


def cohens_d(a: np.ndarray, b: np.ndarray) -> float:
    a = a[~np.isnan(a)]; b = b[~np.isnan(b)]
    if len(a) < 10 or len(b) < 10:
        return np.nan
    na, nb = len(a), len(b)
    va, vb = a.var(ddof=1), b.var(ddof=1)
    pooled = ((na - 1) * va + (nb - 1) * vb) / (na + nb - 2)
    if pooled <= 0:
        return np.nan
    return (a.mean() - b.mean()) / np.sqrt(pooled)


def decile_spread(df: pd.DataFrame, feat: str, target: str) -> tuple:
    """Return (bottom-decile target rate, top-decile target rate, monotonic?)
    for a feature vs a binary target."""
    sub = df[[feat, target]].dropna()
    if len(sub) < 200 or sub[feat].nunique() < 10:
        return (np.nan, np.nan, False)
    try:
        sub = sub.copy()
        sub["dec"] = pd.qcut(sub[feat], 10, labels=False, duplicates="drop")
    except Exception:
        return (np.nan, np.nan, False)
    rate = sub.groupby("dec")[target].mean()
    if len(rate) < 5:
        return (np.nan, np.nan, False)
    # monotonic if Spearman of decile index vs rate is strong
    rho = np.corrcoef(rate.index.values, rate.values)[0, 1]
    return (rate.iloc[0], rate.iloc[-1], abs(rho) >= 0.8)


def feature_separation(ev: pd.DataFrame, target: str, feat_cols: list) -> pd.DataFrame:
    pos = ev[ev[target]]
    neg = ev[~ev[target]]
    rows = []
    for f in feat_cols:
        d = cohens_d(pos[f].to_numpy(float), neg[f].to_numpy(float))
        if np.isnan(d):
            continue
        bot, top, mono = decile_spread(ev, f, target)
        rows.append({
            "feature": f.replace("feat_", ""),
            "cohens_d": d,
            "pos_mean": pos[f].mean(),
            "neg_mean": neg[f].mean(),
            "decile_lo": bot, "decile_hi": top,
            "decile_spread": (top - bot) if not np.isnan(top) else np.nan,
            "monotonic": mono,
        })
    out = pd.DataFrame(rows)
    out["abs_d"] = out["cohens_d"].abs()
    return out.sort_values("abs_d", ascending=False).reset_index(drop=True)


def df_to_md(df: pd.DataFrame, index_name: str = "") -> str:
    """Render an indexed DataFrame to markdown without the `tabulate` dep."""
    cols = [str(c) for c in df.columns]
    hdr = "| " + " | ".join([index_name] + cols) + " |\n"
    sep = "| " + " | ".join("---" for _ in range(len(cols) + 1)) + " |\n"
    body = ""
    for idx, row in df.iterrows():
        cells = [str(idx)] + [str(row[c]) for c in df.columns]
        body += "| " + " | ".join(cells) + " |\n"
    return hdr + sep + body


def md_table(df: pd.DataFrame, cols: list, fmt: dict) -> str:
    hdr = "| " + " | ".join(cols) + " |\n"
    sep = "| " + " | ".join("---" for _ in cols) + " |\n"
    body = ""
    for _, r in df.iterrows():
        cells = [fmt.get(c, lambda x: str(x))(r[c]) for c in cols]
        body += "| " + " | ".join(cells) + " |\n"
    return hdr + sep + body


def main():
    ev, ck = load()
    n_all = len(ev)
    warm = ev[ev["warmed_up"]].copy()

    # Convert MTF alignment (string) to a numeric score that is comparable
    # across long & short (aligned=+1, neutral=0, opposed=-1). The raw
    # feat_regime_{tf} ints encode trade DIRECTION, not quality, so we exclude
    # them from the separation analysis and use alignment instead.
    _align_map = {"aligned": 1, "neutral": 0, "opposed": -1}
    for tf in ("5s", "30s", "5m"):   # 1m is the entry tf (always aligned)
        col = f"feat_align_{tf}"
        if col in warm.columns:
            warm[f"feat_alignnum_{tf}"] = warm[col].map(_align_map)
    drop = {f"feat_regime_{tf}" for tf in ("5s", "30s", "1m", "5m")}
    feat_cols = [c for c in warm.columns if c.startswith("feat_")
                 and c not in drop and pd.api.types.is_numeric_dtype(warm[c])]

    lines = []
    P = lines.append
    P("# Regime Flip Truth — Summary Report\n")
    P("Descriptive only. No ML, no optimization, no parameter search. "
      "All metrics are 1s-precision path outcomes from entry to the next "
      "opposite 1m regime flip. Features are causal entry snapshots.\n")
    P(f"**Universe:** NQ `NQ.v.0`, {YEARS[0]}–{YEARS[-1]}, 24h Globex "
      f"(events tagged `rth_flag`). Catalog `NQ_v0_2020_2026` "
      f"(safe `closed='left'` build).\n")

    # ---- population sizes ----
    P("## 1. Population sizes\n")
    rows = []
    for pop in ("A", "B"):
        s = ev[ev.population == pop]; w = warm[warm.population == pop]
        rows.append({"pop": f"{pop} ({'raw flip' if pop=='A' else 'bar1-confirmed'})",
                     "n_total": len(s), "n_warmed": len(w),
                     "rth_share": w["rth_flag"].mean() if len(w) else np.nan})
    dfp = pd.DataFrame(rows)
    P(md_table(dfp, ["pop", "n_total", "n_warmed", "rth_share"],
               {"n_total": lambda x: f"{int(x):,}", "n_warmed": lambda x: f"{int(x):,}",
                "rth_share": lambda x: f"{x:.0%}"}))
    P(f"\nWarmup-gated (`warmed_up`) events are used for all rate/feature "
      f"stats below. Total raw events across years: {n_all:,}.\n")
    P("Per-year warmed counts:\n")
    yr = warm.groupby(["year", "population"]).size().unstack(fill_value=0)
    P(df_to_md(yr, "year") + "\n")

    # ---- outcome distribution ----
    P("## 2. Outcome distribution — milestone reach rates\n")
    P("Share of events whose MFE reached each ATR multiple before the regime "
      "ended.\n")
    rows = []
    for pop in ("A", "B"):
        w = warm[warm.population == pop]
        r = {"population": pop, "n": len(w)}
        for m in MILESTONES:
            r[MS_LABEL[m]] = w[m].mean()
        rows.append(r)
    dfo = pd.DataFrame(rows)
    P(md_table(dfo, ["population", "n"] + [MS_LABEL[m] for m in MILESTONES],
               {"n": lambda x: f"{int(x):,}",
                **{MS_LABEL[m]: (lambda x: f"{x:.1%}") for m in MILESTONES}}))
    P("")
    # rth vs overnight
    P("By session (Population A):\n")
    rows = []
    for lab, mask in [("RTH", warm.rth_flag), ("Overnight", ~warm.rth_flag)]:
        w = warm[(warm.population == "A") & mask]
        r = {"session": lab, "n": len(w)}
        for m in MILESTONES:
            r[MS_LABEL[m]] = w[m].mean()
        rows.append(r)
    dfs = pd.DataFrame(rows)
    P(md_table(dfs, ["session", "n"] + [MS_LABEL[m] for m in MILESTONES],
               {"n": lambda x: f"{int(x):,}",
                **{MS_LABEL[m]: (lambda x: f"{x:.1%}") for m in MILESTONES}}))
    P("")

    # ---- path quality distribution ----
    P("## 3. Path-quality distribution\n")
    P("Clean Trend A: MFE≥2 & MAE≤0.75 ATR. Clean Trend B: MFE≥3 & MAE≤1. "
      "Persistent: duration≥15 bars. Elite: persistent & MFE≥2 & MAE≤0.75.\n")
    rows = []
    for pop in ("A", "B"):
        w = warm[warm.population == pop]
        r = {"population": pop, "n": len(w)}
        for L in LABELS:
            r[L] = w[L].mean()
        r["median_dur_bars"] = w["regime_duration_bars"].median()
        r["mean_term_pnl_atr"] = w["terminal_pnl_atr"].mean()
        rows.append(r)
    dfq = pd.DataFrame(rows)
    P(md_table(dfq, ["population", "n"] + LABELS
               + ["median_dur_bars", "mean_term_pnl_atr"],
               {"n": lambda x: f"{int(x):,}",
                **{L: (lambda x: f"{x:.1%}") for L in LABELS},
                "median_dur_bars": lambda x: f"{x:.0f}",
                "mean_term_pnl_atr": lambda x: f"{x:+.2f}"}))
    P("")
    P("Per-year Elite rate (Population A / B):\n")
    el = warm.groupby(["year", "population"])["elite_trend"].mean().unstack()
    el_fmt = el.apply(lambda s: s.map(
        lambda x: f"{x:.1%}" if pd.notna(x) else "—"))
    P(df_to_md(el_fmt, "year") + "\n")

    # ---- feature separation (Elite) ----
    P("## 4. Feature separation — Elite vs non-Elite\n")
    P("Cohen's d on causal ENTRY features (positive d ⇒ higher in Elite). "
      "`decile_lo/hi` = Elite rate in the bottom/top feature decile; "
      "`monotonic` = |corr(decile, rate)| ≥ 0.8. Pooled Population A+B warmed.\n")
    sep = feature_separation(warm, "elite_trend", feat_cols)
    top = sep.head(25)
    P(md_table(top, ["feature", "cohens_d", "pos_mean", "neg_mean",
                     "decile_lo", "decile_hi", "decile_spread", "monotonic"],
               {"cohens_d": lambda x: f"{x:+.3f}",
                "pos_mean": lambda x: f"{x:+.3f}", "neg_mean": lambda x: f"{x:+.3f}",
                "decile_lo": lambda x: f"{x:.1%}" if pd.notna(x) else "—",
                "decile_hi": lambda x: f"{x:.1%}" if pd.notna(x) else "—",
                "decile_spread": lambda x: f"{x:+.1%}" if pd.notna(x) else "—",
                "monotonic": lambda x: "yes" if x else "no"}))
    P("")
    P(f"Max |Cohen's d| = {sep['abs_d'].max():.3f}. As a yardstick: |d|<0.2 "
      f"negligible, 0.2–0.5 small, 0.5–0.8 medium, >0.8 large.\n")

    # ---- secondary targets ----
    for tgt, name in [("clean_trend_a", "Clean Trend A"),
                      ("persistent_trend", "Persistent Trend")]:
        s2 = feature_separation(warm, tgt, feat_cols).head(10)
        P(f"Top-10 separators for **{name}**:\n")
        P(md_table(s2, ["feature", "cohens_d", "decile_lo", "decile_hi", "monotonic"],
                   {"cohens_d": lambda x: f"{x:+.3f}",
                    "decile_lo": lambda x: f"{x:.1%}" if pd.notna(x) else "—",
                    "decile_hi": lambda x: f"{x:.1%}" if pd.notna(x) else "—",
                    "monotonic": lambda x: "yes" if x else "no"}))
        P("")

    # ---- early recognition (checkpoint panel) ----
    P("## 5. Can we recognize Elite EARLY?\n")
    P("Cohen's d at each checkpoint for `cur_mfe_atr`, `cur_pnl_atr`, "
      "`path_efficiency` between events that EVENTUALLY become Elite vs not. "
      "Larger |d| earlier ⇒ recognizable sooner. (Warmed Population A+B.)\n")
    lab = warm.set_index("uid")["elite_trend"]
    ckw = ck[ck["uid"].isin(lab.index)].copy()
    ckw["elite"] = ckw["uid"].map(lab)
    rows = []
    for cpt in CHECKPOINT_ORDER:
        sub = ckw[ckw["checkpoint"] == cpt]
        if len(sub) < 50:
            continue
        pos = sub[sub.elite]; neg = sub[~sub.elite]
        r = {"checkpoint": cpt, "n": len(sub)}
        for met in ["cur_mfe_atr", "cur_pnl_atr", "path_efficiency"]:
            r[met] = cohens_d(pos[met].to_numpy(float), neg[met].to_numpy(float))
        rows.append(r)
    dce = pd.DataFrame(rows)
    P(md_table(dce, ["checkpoint", "n", "cur_mfe_atr", "cur_pnl_atr", "path_efficiency"],
               {"n": lambda x: f"{int(x):,}",
                "cur_mfe_atr": lambda x: f"{x:+.2f}" if pd.notna(x) else "—",
                "cur_pnl_atr": lambda x: f"{x:+.2f}" if pd.notna(x) else "—",
                "path_efficiency": lambda x: f"{x:+.2f}" if pd.notna(x) else "—"}))
    P("")

    # ---- caveats ----
    P("## 6. Caveats\n")
    P("- This is a TRUTH dataset, not a strategy. Terminal PnL is measured to "
      "the next opposite 1m flip at that bar's close — not an executable exit "
      "(no spread, slippage, or fill mechanics). Do not read PnL columns as "
      "tradeable edge.\n")
    P("- Labels (Elite etc.) use the FULL forward path; they are outcomes, not "
      "signals. Section 4 quantifies whether ENTRY features separate them; "
      "Section 5 whether EARLY-path state separates them.\n")
    P("- `mfe_atr`/`mae_atr` are signed: a negative MAE means the trade never "
      "traded against entry (rare, short regimes); negative MFE means it never "
      "traded favorably. Both are real, ~2% of events.\n")
    P("- No ML was used. Cohen's d / deciles are univariate; they do not "
      "capture interactions. A small univariate |d| does not preclude a "
      "multivariate signal — but a large univariate separation is the cheapest "
      "evidence of a real, early-recognizable distinction.\n")

    out = RES / "flip_truth_summary.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {out}")
    # also echo the headline numbers
    print("\n=== HEADLINE ===")
    print(dfq.to_string(index=False))
    print(f"\nTop entry separators for Elite (|d|):")
    print(sep.head(8)[["feature", "cohens_d", "decile_lo", "decile_hi", "monotonic"]].to_string(index=False))


if __name__ == "__main__":
    main()
