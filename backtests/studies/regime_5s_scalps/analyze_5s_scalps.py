"""NQ 5s Regime Scalp Study Results Analyzer.

Loads simulation parquets, merges entries and labels, applies cost models,
computes all required metrics, performs extensive segmentation bucketing, ranks
the best-performing buckets, and writes a detailed markdown report.

Selection / validation separation (audit W4, MEMORY[[grid_tune_vs_validate_separation]]):
  * The best bracket config AND the segmentation tertile edges are FIT on the
    2021-2024 in-sample (IS) population only.
  * A held-out OOS year (default 2025), never used for any selection, is then
    scored under the SAME config and the SAME IS-fitted bucket edges. The IS
    bucket "winners" are reported side-by-side with their OOS net $/trade so the
    reader can see whether any IS edge survives out of sample.

Study population is RTH-only (08:30-15:00 CT) by construction in the collector.
"""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent.parent
os.chdir(PROJECT_ROOT)

OUT = Path("studies/regime_5s_scalps/results")

# Per-instrument economics. NQ = $20/pt ($5/tick); ES = $50/pt ($12.50/tick).
# Tick = 0.25 for both. Commission is $5 RT for both (same assumption as the NQ
# study). Set by main() from --instrument.
INSTRUMENTS = {
    "NQ": dict(mult=20.0, tick_val=5.0, prefix=""),
    "ES": dict(mult=50.0, tick_val=12.5, prefix="es_"),
}
TICK = 0.25
MULT = INSTRUMENTS["NQ"]["mult"]
TICK_VAL = INSTRUMENTS["NQ"]["tick_val"]
PREFIX = INSTRUMENTS["NQ"]["prefix"]
COMM = 5.0


def calc_net_pnl(pnl_pts: pd.Series, reason: pd.Series, cost_type: str) -> pd.Series:
    """Dollar PnL under a cost model. PT (reason==1) is a limit fill -> 0
    slippage; every other exit pays slippage of 0.5 tick (primary) / 1.0 tick
    (stress). Commission is $5 RT always. All dollar figures are instrument-aware
    via MULT / TICK_VAL."""
    pnl_usd = pnl_pts * MULT
    if cost_type == "gross":
        return pnl_usd
    if cost_type == "primary":
        slip = np.where(reason == 1, 0.0, 0.5 * TICK_VAL)
    elif cost_type == "stress":
        slip = np.where(reason == 1, 0.0, 1.0 * TICK_VAL)
    else:
        raise ValueError(f"Unknown cost type: {cost_type}")
    return pnl_usd - (COMM + slip)


def compute_metrics(df: pd.DataFrame, col_prefix: str, cost_type: str = "primary") -> dict:
    if len(df) == 0:
        return dict(trades=0, win_pct=0.0, be_win_pct=0.0, edge=0.0,
                    gross_pnl_trade=0.0, net_pnl_trade=0.0, gross_pf=0.0,
                    net_pf=0.0, avg_hold=0.0, med_hold=0.0, max_dd=0.0,
                    mean_mfe=0.0, mean_mae=0.0, p10=0.0, p90=0.0,
                    years_positive=0, n_years=0, total_net=0.0)
    pnl_pts = df[f"pnl_{col_prefix}"].astype(np.float64)
    reason = df[f"reason_{col_prefix}"].astype(np.int64)
    hold_s = df[f"hold_{col_prefix}"].astype(np.float64)
    mfe_pts = df[f"mfe_{col_prefix}"].astype(np.float64)
    mae_pts = df[f"mae_{col_prefix}"].astype(np.float64)

    net_pnl = calc_net_pnl(pnl_pts, reason, cost_type)
    gross_pnl = calc_net_pnl(pnl_pts, reason, "gross")

    n_trades = len(net_pnl)
    wins = net_pnl > 0
    win_pct = wins.mean() * 100.0

    net_winners = net_pnl[net_pnl > 0]
    net_losers = net_pnl[net_pnl <= 0]
    mean_gain = net_winners.mean() if len(net_winners) > 0 else 0.0
    mean_loss = net_losers.mean() if len(net_losers) > 0 else 0.0
    abs_mean_loss = abs(mean_loss)
    be_win_pct = ((abs_mean_loss / (mean_gain + abs_mean_loss)) * 100.0
                  if (mean_gain + abs_mean_loss) > 0 else 0.0)
    edge = win_pct - be_win_pct

    gross_wins_sum = gross_pnl[gross_pnl > 0].sum()
    gross_losses_sum = abs(gross_pnl[gross_pnl < 0].sum())
    gross_pf = gross_wins_sum / gross_losses_sum if gross_losses_sum > 0 else float("inf")
    net_wins_sum = net_pnl[net_pnl > 0].sum()
    net_losses_sum = abs(net_pnl[net_pnl < 0].sum())
    net_pf = net_wins_sum / net_losses_sum if net_losses_sum > 0 else float("inf")

    # chronological max drawdown of cumulative net equity
    order = np.argsort(df["entry_ts"].values)
    sorted_pnl = net_pnl.values[order]
    cum = sorted_pnl.cumsum()
    run_max = np.maximum.accumulate(cum)
    max_dd = float((run_max - cum).max()) if len(cum) else 0.0

    years_pnl = net_pnl.groupby(df["year"]).sum()
    years_positive = int((years_pnl > 0).sum())
    n_years = int(years_pnl.shape[0])

    return dict(
        trades=n_trades, win_pct=win_pct, be_win_pct=be_win_pct, edge=edge,
        gross_pnl_trade=gross_pnl.mean(), net_pnl_trade=net_pnl.mean(),
        gross_pf=gross_pf, net_pf=net_pf, avg_hold=hold_s.mean(),
        med_hold=hold_s.median(), max_dd=max_dd, mean_mfe=mfe_pts.mean(),
        mean_mae=mae_pts.mean(), p10=net_pnl.quantile(0.10),
        p90=net_pnl.quantile(0.90), years_positive=years_positive,
        n_years=n_years, total_net=float(net_pnl.sum()))


def format_row(name: str, m: dict) -> str:
    pf = f"{m['net_pf']:.2f}" if m["net_pf"] != float("inf") else "inf"
    return (f"| {name} | {m['trades']:,} | {m['win_pct']:.1f}% | {m['be_win_pct']:.1f}% | "
            f"{m['edge']:.1f}% | ${m['gross_pnl_trade']:.2f} | ${m['net_pnl_trade']:.2f} | "
            f"{pf} | {m['years_positive']}/{m['n_years']} |")


# ----- bucketing with fit/apply separation (for valid OOS scoring) -----
TERTILE_FEATURES = [
    "1m_pnl_atr", "1m_mfe_atr", "1m_mae_atr", "1m_mfe_mae_ratio",
    "1m_path_efficiency", "prior_5s_duration", "prior_5s_mfe", "prior_5s_mae",
    "prior_5s_pnl", "flips_60s", "flips_120s", "flip_bar_range_atr",
    "flip_bar_body_pct", "flip_bar_close_loc", "ema9_1m_slope", "ema9_5s_slope",
    "spread_9_21_1m", "spread_9_21_5s", "ema9_1m_dist_atr", "ema9_5s_dist_atr",
    "age_5m", "vol_5s_vs_avg", "vol_5s_accel", "vol_1m_ratio",
    "vol_aligned_opposing_ratio",
]


def _tertile(df, col, edges_store, fit):
    if col not in df or df[col].nunique() <= 1:
        return pd.Series(["Neutral"] * len(df), index=df.index)
    try:
        if fit:
            cats, bins = pd.qcut(df[col], q=3, labels=["Low", "Mid", "High"],
                                 duplicates="drop", retbins=True)
            edges_store[col] = bins
            return cats
        bins = edges_store.get(col)
        if bins is None or len(bins) < 3:
            return pd.Series(["Neutral"] * len(df), index=df.index)
        b = bins.copy()
        b[0] = -np.inf
        b[-1] = np.inf
        return pd.cut(df[col], bins=b, labels=["Low", "Mid", "High"][:len(b) - 1],
                      include_lowest=True)
    except Exception:
        return pd.Series(["Neutral"] * len(df), index=df.index)


def build_buckets(df: pd.DataFrame, edges_store: dict, fit: bool) -> pd.DataFrame:
    """Add all bucket_<feature> columns. fit=True computes & stores tertile
    edges (IS); fit=False applies stored edges (OOS)."""
    df = df.copy()
    t_bins = [-np.inf, 30, 60, 90, 120, 180, 300, 600, np.inf]
    t_labels = ["0–30s", "30–60s", "60–90s", "90–120s", "120–180s", "180–300s", "300–600s", "600s+"]
    df["bucket_time_since_1m"] = pd.cut(df["time_since_1m"], bins=t_bins, labels=t_labels)
    ord_bins = [-np.inf, 1, 2, 3, 4, np.inf]
    ord_labels = ["1st aligned 5s flip", "2nd", "3rd", "4th", "5th+"]
    df["bucket_1m_ordinal"] = pd.cut(df["1m_ordinal"], bins=ord_bins, labels=ord_labels)
    df["flips_already_seen"] = df["5s_chop_count"] - 1
    chop_bins = [-np.inf, 0, 1, 2, 3, 5, np.inf]
    chop_labels = ["0", "1", "2", "3", "4–5", "6+"]
    df["bucket_flips_seen"] = pd.cut(df["flips_already_seen"], bins=chop_bins, labels=chop_labels)
    for k, lbls in [("1m_reached_025", ("MFE < 0.25 ATR", "MFE >= 0.25 ATR")),
                    ("1m_reached_050", ("MFE < 0.50 ATR", "MFE >= 0.50 ATR")),
                    ("1m_reached_100", ("MFE < 1.00 ATR", "MFE >= 1.00 ATR")),
                    ("1m_reached_150", ("MFE < 1.50 ATR", "MFE >= 1.50 ATR")),
                    ("1m_net_positive", ("Net Negative", "Net Positive"))]:
        df[f"bucket_{k}"] = df[k].map({0: lbls[0], 1: lbls[1]})
    for col in TERTILE_FEATURES:
        df[f"bucket_{col}"] = _tertile(df, col, edges_store, fit)
    df["bucket_regime_5m"] = df["regime_5m"].map({0: "Neutral", 1: "Bull", -1: "Bear"})
    df["bucket_aligned_5m_1m"] = df["aligned_5m_1m"].map({0: "Not Aligned", 1: "5m/1m Aligned"})
    return df


def load_years(years, suffix=""):
    e_list, l_list = [], []
    for y in years:
        ef = OUT / f"{PREFIX}5s_scalp_entries_{y}{suffix}.parquet"
        lf = OUT / f"{PREFIX}5s_scalp_labels_{y}{suffix}.parquet"
        if ef.exists() and lf.exists():
            de = pd.read_parquet(ef); dl = pd.read_parquet(lf)
            de["entry_id"] = de["entry_id"] + y * 1_000_000
            dl["entry_id"] = dl["entry_id"] + y * 1_000_000
            e_list.append(de); l_list.append(dl)
        else:
            print(f"  (missing parquet for {y}{suffix})")
    if not e_list:
        return None
    de = pd.concat(e_list, ignore_index=True)
    dl = pd.concat(l_list, ignore_index=True)
    return pd.merge(de, dl, on="entry_id")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instrument", default="NQ", choices=sorted(INSTRUMENTS))
    ap.add_argument("--years", default="2021,2022,2023,2024")
    ap.add_argument("--oos-years", default="2025")
    ap.add_argument("--smoke", type=int, default=0)
    args = ap.parse_args()

    global MULT, TICK_VAL, PREFIX
    cfg_i = INSTRUMENTS[args.instrument]
    MULT = cfg_i["mult"]; TICK_VAL = cfg_i["tick_val"]; PREFIX = cfg_i["prefix"]
    print(f"Instrument={args.instrument}  MULT=${MULT}/pt  tick=${TICK_VAL}  prefix='{PREFIX}'")

    years = [int(y) for y in args.years.split(",")]
    oos_years = [int(y) for y in args.oos_years.split(",") if y.strip()]
    suffix = f"_smoke{args.smoke}" if args.smoke else ""

    print("Loading IS parquets...")
    df = load_years(years, suffix)
    if df is None:
        print("No IS files found!"); return
    print(f"IS merged size: {len(df):,}")
    # Save entries and labels Parquet files separately in results folder
    lbl_cols = [c for c in df.columns if any(c.startswith(p) for p in ("pnl_", "reason_", "hold_", "mfe_", "mae_"))]
    lbl_cols.append("entry_id")
    ent_cols = [c for c in df.columns if c not in lbl_cols or c == "entry_id"]
    df[ent_cols].to_parquet(OUT / f"{PREFIX}5s_scalp_entries.parquet", index=False)
    df[lbl_cols].to_parquet(OUT / f"{PREFIX}5s_scalp_labels.parquet", index=False)


    pnl_cols = [c for c in df.columns if c.startswith("pnl_")]
    configs = [c[4:] for c in pnl_cols]
    print(f"Found {len(configs)} configurations.")

    print("Evaluating all configs (IS)...")
    rows = []
    for cfg in configs:
        parts = cfg.split("_")
        rows.append(dict(config=cfg, br_name=parts[0], atr_type=parts[1],
                         exit_flavor=parts[2], max_hold=parts[3],
                         primary=compute_metrics(df, cfg, "primary"),
                         stress=compute_metrics(df, cfg, "stress"),
                         gross=compute_metrics(df, cfg, "gross"),
                         long=compute_metrics(df[df.direction == 1], cfg, "primary"),
                         short=compute_metrics(df[df.direction == -1], cfg, "primary")))
    df_global = pd.DataFrame(rows)
    df_global["net_pnl_trade"] = df_global["primary"].apply(lambda x: x["net_pnl_trade"])
    df_global = df_global.sort_values("net_pnl_trade", ascending=False).reset_index(drop=True)
    best_cfg = df_global.iloc[0]["config"]
    print(f"Best IS config: {best_cfg} ({df_global.iloc[0]['net_pnl_trade']:+.2f} $/tr)")

    edges = {}
    df = build_buckets(df, edges, fit=True)
    segment_cols = [c for c in df.columns if c.startswith("bucket_")]
    brecs = []
    for col in segment_cols:
        for name, sub in df.groupby(col, observed=False):
            m = compute_metrics(sub, best_cfg, "primary")
            brecs.append(dict(feature=col.replace("bucket_", ""), bucket=str(name),
                              trades=m["trades"], win_pct=m["win_pct"],
                              be_win_pct=m["be_win_pct"], edge=m["edge"],
                              gross_pnl_trade=m["gross_pnl_trade"],
                              net_pnl_trade=m["net_pnl_trade"], net_pf=m["net_pf"],
                              years_positive=m["years_positive"], n_years=m["n_years"]))
    df_buckets = pd.DataFrame(brecs)
    df_buckets.to_parquet(OUT / f"{PREFIX}5s_scalp_bucket_summary.parquet", index=False)
    df_buckets_ranked = df_buckets[df_buckets["trades"] >= 200].sort_values(
        "net_pnl_trade", ascending=False).reset_index(drop=True)

    oos = None
    if oos_years:
        print(f"Loading OOS parquets {oos_years}...")
        df_oos = load_years(oos_years, suffix)
        if df_oos is not None and f"pnl_{best_cfg}" in df_oos.columns:
            df_oos = build_buckets(df_oos, edges, fit=False)
            oos = dict(year_label=",".join(str(y) for y in oos_years),
                       n=len(df_oos),
                       best=compute_metrics(df_oos, best_cfg, "primary"),
                       best_gross=compute_metrics(df_oos, best_cfg, "gross"))
            val = []
            for _, r in df_buckets_ranked.head(10).iterrows():
                col = f"bucket_{r['feature']}"
                if col in df_oos.columns:
                    sub = df_oos[df_oos[col].astype(str) == r["bucket"]]
                    mo = compute_metrics(sub, best_cfg, "primary")
                else:
                    mo = compute_metrics(df_oos.iloc[0:0], best_cfg, "primary")
                val.append(dict(feature=r["feature"], bucket=r["bucket"],
                                is_net=r["net_pnl_trade"],
                                is_yrs=f"{r['years_positive']}/{r['n_years']}",
                                oos_net=mo["net_pnl_trade"], oos_trades=mo["trades"]))
            oos["bucket_val"] = pd.DataFrame(val)
            print(f"OOS best_cfg net/tr: {oos['best']['net_pnl_trade']:+.2f}")
        else:
            print("  (no usable OOS data)")

    write_report(df, df_global, df_buckets_ranked, best_cfg, years, oos)


def _fmt_bucket_row(r):
    pf = f"{r['net_pf']:.2f}" if r["net_pf"] != float("inf") else "inf"
    return (f"| {r['feature']} | {r['bucket']} | {r['trades']:,} | {r['win_pct']:.1f}% | "
            f"{r['be_win_pct']:.1f}% | {r['edge']:.1f}% | ${r['gross_pnl_trade']:.2f} | "
            f"${r['net_pnl_trade']:.2f} | {pf} | {r['years_positive']}/{r['n_years']} |")


def write_report(df, df_global, df_buckets, best_cfg, years, oos):
    print("Generating report...")
    best = df_global.iloc[0]
    L = []
    instr = "ES" if PREFIX == "es_" else "NQ"
    L.append(f"# {instr} 5s Regime Scalp Study Inside Active 1m Regimes")
    L.append("")
    L.append("## Objective")
    L.append("Evaluate whether 5s regime flips that align with the active 1m regime "
             "direction are independently tradable scalps (not adds to the 1m trade). "
             "RTH-only (08:30–15:00 CT). Causal MTF replay; next-1s-open fills; "
             "no phantom fills. Best config + tertile edges are FIT on "
             f"{years[0]}–{years[-1]} and VALIDATED on a held-out OOS year.")
    L.append("")
    L.append("## Summary of Findings")
    npt = best["net_pnl_trade"]; eb = best["primary"]["edge"]
    oos_npt = oos["best"]["net_pnl_trade"] if oos else None
    n_yr = best["primary"]["n_years"]
    robust = (npt > 0 and eb > 2.0
              and best["primary"]["years_positive"] >= max(3, n_yr - 1)
              and (oos_npt is None or oos_npt > 0))
    if robust:
        L.append(f"> [!TIP]\n> **Possible edge.** Best IS config **{best_cfg}** = **${npt:.2f}/tr** "
                 f"(edge {eb:.1f}pp), held up OOS (${oos_npt:.2f}/tr). Investigate further "
                 "before any deployment claim.")
    elif npt > 0:
        oos_txt = (f" OOS it was **${oos_npt:.2f}/tr**." if oos_npt is not None else "")
        L.append(f"> [!WARNING]\n> **Friction-capped / not robust.** Best IS config **{best_cfg}** is only "
                 f"**${npt:.2f}/tr** (edge {eb:.1f}pp).{oos_txt} The gross edge is consumed by costs "
                 "and/or it fails the robustness bar (≥3/4 yrs AND positive OOS).")
    else:
        L.append(f"> [!WARNING]\n> **Negative expectancy.** No config is net-positive after primary costs. "
                 f"Best IS config **{best_cfg}** averaged **${npt:.2f}/tr**.")
    L.append("")
    L.append("---")
    L.append("")
    L.append("## 1. Global 5s Scalp Performance (IS)")
    L.append("Top configs by IS primary net $/trade ($5 RT commission + 0.5-tick non-PT slippage).")
    L.append("")
    hdr = ("| Configuration | Trades | Win % | BE Win % | Edge % | Gross $/Trade | "
           "Net $/Trade | Net PF | Yrs+ |")
    sep = "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"
    L.append(hdr); L.append(sep)
    for _, r in df_global.head(10).iterrows():
        L.append(format_row(r["config"], r["primary"]))
    L.append("")
    L.append("### Side split (best config)")
    L.append(hdr.replace("Configuration", "Side")); L.append(sep)
    L.append(format_row("Longs", best["long"]))
    L.append(format_row("Shorts", best["short"]))
    L.append("")
    L.append("### Cost scenarios (best config)")
    L.append(hdr.replace("Configuration", "Cost")); L.append(sep)
    L.append(format_row("Gross", best["gross"]))
    L.append(format_row("Primary Net", best["primary"]))
    L.append(format_row("Stress Net", best["stress"]))
    L.append("")
    L.append("### No-bracket (held to 5s/1m regime flip)")
    L.append("Side question: is simply holding the 5s regime to its next opposite flip "
             "(or the parent 1m flip) profitable on its own?")
    L.append("")
    L.append(hdr); L.append(sep)
    for _, r in df_global[df_global["br_name"] == "nobr"].head(5).iterrows():
        L.append(format_row(r["config"], r["primary"]))

    if oos:
        L.append(""); L.append("---"); L.append("")
        L.append(f"## 1b. OUT-OF-SAMPLE validation ({oos['year_label']}, n={oos['n']:,})")
        L.append("IS-best config and IS-fitted bucket edges applied UNCHANGED to a year never "
                 "used for selection. This is the deployment-relevant number.")
        L.append("")
        L.append("| | Gross $/Trade | Net $/Trade | Net PF | Win % |")
        L.append("| --- | --- | --- | --- | --- |")
        bg, bp = oos["best_gross"], oos["best"]
        L.append(f"| OOS best config ({best_cfg}) | ${bg['gross_pnl_trade']:.2f} | "
                 f"${bp['net_pnl_trade']:.2f} | {bp['net_pf']:.2f} | {bp['win_pct']:.1f}% |")
        L.append("")
        L.append("### IS bucket 'winners' vs OOS")
        L.append("> [!CAUTION]\n> Section 2's IS bucket table is the maximum of ~80 in-sample "
                 "tertile draws under the in-sample-best config — a multiple-comparisons selection. "
                 "Here each IS-top bucket is re-scored on OOS with the SAME edges. Survivors must "
                 "stay net-positive OOS; collapses are noise.")
        L.append("")
        L.append("| Feature | Bucket | IS Net $/tr | IS Yrs+ | OOS Net $/tr | OOS Trades |")
        L.append("| --- | --- | --- | --- | --- | --- |")
        for _, r in oos["bucket_val"].iterrows():
            L.append(f"| {r['feature']} | {r['bucket']} | ${r['is_net']:.2f} | {r['is_yrs']} | "
                     f"${r['oos_net']:.2f} | {r['oos_trades']:,} |")

    L.append(""); L.append("---"); L.append("")
    L.append("## 2. Best IS Buckets (in-sample; see OOS caveat above)")
    L.append("> [!CAUTION]\n> In-sample tertile descriptions under the in-sample-best bracket. "
             "NOT validated edges — see Section 1b. A bucket is only 'interesting' if net-positive, "
             "edge > 2pp, positive in ≥3/4 years, AND survives OOS.")
    L.append("")
    L.append("| Feature | Bucket | Trades | Win % | BE Win % | Edge % | Gross $/Trade | Net $/Trade | Net PF | Yrs+ |")
    L.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for _, r in df_buckets.head(12).iterrows():
        L.append(_fmt_bucket_row(r))

    def feature_table(title, desc, feat, order=None, label="Bucket"):
        L.append(""); L.append(f"## {title}"); L.append(desc); L.append("")
        L.append(f"| {label} | Trades | Win % | BE Win % | Edge % | Gross $/Trade | Net $/Trade | Net PF | Yrs+ |")
        L.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
        sub = (df_buckets[df_buckets["feature"] == feat] if isinstance(feat, str)
               else df_buckets[df_buckets["feature"].isin(feat)])
        if order and isinstance(feat, str):
            sub = sub.set_index("bucket").reindex(order).dropna(how="all").reset_index()
        for _, r in sub.iterrows():
            nm = r["bucket"] if isinstance(feat, str) else f"{r['feature']}: {r['bucket']}"
            pf = f"{r['net_pf']:.2f}" if r["net_pf"] != float("inf") else "inf"
            L.append(f"| {nm} | {r['trades']:,} | {r['win_pct']:.1f}% | {r['be_win_pct']:.1f}% | "
                     f"{r['edge']:.1f}% | ${r['gross_pnl_trade']:.2f} | ${r['net_pnl_trade']:.2f} | "
                     f"{pf} | {r['years_positive']}/{r['n_years']} |")
        return sub

    t_df = feature_table("3. Time-in-1m-Regime Table",
                         "Net by time since the parent 1m regime flipped.", "time_since_1m",
                         order=["0–30s", "30–60s", "60–90s", "90–120s", "120–180s",
                                "180–300s", "300–600s", "600s+"], label="Time since 1m Flip")
    o_df = feature_table("4. 5s Flip Ordinal Table",
                         "Net by the aligned 5s flip ordinal inside the parent 1m regime.",
                         "1m_ordinal",
                         order=["1st aligned 5s flip", "2nd", "3rd", "4th", "5th+"], label="Ordinal")
    feature_table("5. Parent Regime Quality Table",
                  "Net conditioned on parent 1m state at scalp entry.",
                  ["1m_net_positive", "1m_reached_025", "1m_reached_050", "1m_reached_100", "1m_reached_150"],
                  label="Parent Condition")
    ema_df = feature_table("6. EMA / Slope Bucket Table",
                           "Net by trend geometry tertiles.",
                           ["ema9_1m_slope", "ema9_5s_slope", "spread_9_21_1m", "spread_9_21_5s",
                            "ema9_1m_dist_atr", "ema9_5s_dist_atr"], label="EMA Feature & tertile")

    L.append(""); L.append("---"); L.append(""); L.append("## Critical Questions"); L.append("")
    g = best["gross"]; p = best["primary"]
    L.append("**Q1 — Positive expectancy (gross)?** "
             + (f"Yes, gross **${g['net_pnl_trade']:.2f}/tr** (best config {best_cfg})."
                if g["net_pnl_trade"] > 0 else "No, not even gross."))
    L.append("")
    L.append("**Q2 — Positive after realistic costs?** "
             + (f"Yes, **${p['net_pnl_trade']:.2f}/tr** primary." if p["net_pnl_trade"] > 0
                else "No — every config is net-negative after primary costs; the gross edge is "
                     "smaller than the per-trade friction."))
    L.append("")
    top_br = best["br_name"]
    brk = "symmetric 1:1" if top_br.startswith("sym") else ("no-bracket" if top_br == "nobr" else "positive-RR")
    L.append(f"**Q3 — 1:1 vs positive-RR?** Best is **{brk}** ({top_br}).")
    L.append("")
    if len(t_df):
        bt = t_df.loc[t_df["net_pnl_trade"].idxmax()]; wt = t_df.loc[t_df["net_pnl_trade"].idxmin()]
        L.append(f"**Q4 — Depends on position in parent 1m regime?** Best at **{bt['bucket']}** "
                 f"(${bt['net_pnl_trade']:.2f}/tr), worst at **{wt['bucket']}** (${wt['net_pnl_trade']:.2f}/tr). "
                 "In-sample shape, not a validated rule.")
        L.append("")
    if len(o_df):
        o1 = o_df[o_df.bucket == "1st aligned 5s flip"]["net_pnl_trade"]
        o2 = o_df[o_df.bucket == "2nd"]["net_pnl_trade"]
        v1 = o1.iloc[0] if len(o1) else 0.0; v2 = o2.iloc[0] if len(o2) else 0.0
        L.append("**Q5 — Recovery flips better than the 1st aligned flip?** "
                 + (f"Yes (2nd ${v2:.2f} > 1st ${v1:.2f})." if v2 > v1
                    else f"No — 1st (${v1:.2f}) ≥ 2nd (${v2:.2f})."))
        L.append("")
    al = df_buckets[df_buckets.feature == "aligned_5m_1m"]
    ay = al[al.bucket == "5m/1m Aligned"]["net_pnl_trade"]
    an = al[al.bucket == "Not Aligned"]["net_pnl_trade"]
    vay = ay.iloc[0] if len(ay) else 0.0; van = an.iloc[0] if len(an) else 0.0
    L.append("**Q6 — Does 5m alignment help?** "
             + (f"Aligned ${vay:.2f}/tr vs not-aligned ${van:.2f}/tr — "
                + ("materially better." if vay - van > 2 else "not materially different.")))
    L.append("")
    if len(ema_df):
        be_ = ema_df.loc[ema_df["net_pnl_trade"].idxmax()]
        L.append(f"**Q7 — EMA slope/distance identify better flips?** In-sample best cell is "
                 f"**{be_['feature']} {be_['bucket']}** (${be_['net_pnl_trade']:.2f}/tr) — in-sample only.")
        L.append("")
    vol_df = df_buckets[df_buckets.feature.str.startswith("vol_")]
    if len(vol_df):
        bv = vol_df.loc[vol_df["net_pnl_trade"].idxmax()]
        L.append(f"**Q8 — Volume features identify better flips?** In-sample best is "
                 f"**{bv['feature']} {bv['bucket']}** (${bv['net_pnl_trade']:.2f}/tr) — needs OOS (Section 1b).")
        L.append("")
    L.append(f"**Q9 — Stable by year and side?** Best config positive in "
             f"**{p['years_positive']}/{p['n_years']}** IS years; longs ${best['long']['net_pnl_trade']:.2f}/tr "
             f"vs shorts ${best['short']['net_pnl_trade']:.2f}/tr"
             + (f"; OOS {oos['best']['net_pnl_trade']:+.2f}/tr." if oos else "."))
    L.append("")
    if oos:
        verdict = ("a repeatable edge — survives costs AND OOS" if (npt > 0 and oos_npt > 0 and eb > 2)
                   else "another near-scratch gross edge consumed by costs / not robust OOS")
    else:
        verdict = ("net-positive in-sample but UNVALIDATED (no OOS year present)" if npt > 0
                   else "a friction-capped near-scratch edge")
    L.append(f"**Q10 — Repeatable intraregime scalp, or near-scratch?** Conclusion: **{verdict}.** "
             f"Best IS primary ${npt:.2f}/tr" + (f", OOS ${oos_npt:.2f}/tr." if oos else "."))

    (OUT / f"{PREFIX}5s_scalp_results.md").write_text("\n".join(L), encoding="utf-8")
    print(f"Wrote results/{PREFIX}5s_scalp_results.md")


if __name__ == "__main__":
    main()
