"""2026 Failure Anatomy + Max-MFE Structural analyzer."""

from __future__ import annotations
import os, sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
os.chdir(project_root)

OUT = Path("studies/momentum_2026_anatomy_v1/results")
PATH_OUT = Path("studies/momentum_confirm_path_v1/results")
YEARS = [2024, 2025, 2026]
MODES = ["1m_momentum", "30s_momentum"]
NQ_MULT = 20.0

NUMERIC_FEATURES = [
    "atr_at_signal", "atr_pct_500", "atr_slope_10",
    "rr_5_atr", "rr_10_atr", "rr_20_atr",
    "chop_5", "chop_10", "bar_overlap_pct",
    "flip_count_30m", "flip_count_60m", "avg_dur_5_bars",
    "confirm_body_pct", "confirm_range_atr",
    "confirm_close_loc", "confirm_wickiness",
    "confirm_vol_z", "hhll_amount_atr",
    "close_through_amt_atr",
    "prior_3_net_move_atr", "prior_5_net_move_atr",
    "prior_10_net_move_atr", "eff_5", "eff_10",
    "dist_recent_h_atr", "dist_recent_l_atr",
    "position_in_range",
    "minutes_since_open", "dist_sess_h_atr",
    "dist_sess_l_atr", "dist_sess_mid_atr", "sess_range_atr",
    "regime_5m_aligned", "regime_5m_age_5m_bars",
    "hmm_state_at_flip", "hmm_state_at_signal",
    "hmm_state_changed", "hmm_state_prob_3", "hmm_entropy",
]


def fmt_d(v):
    if v is None or (isinstance(v, float) and (pd.isna(v) or np.isinf(v))):
        return "—"
    return f"${v:,.2f}" if abs(v) < 1000 else f"${v:,.0f}"


def fmt_p(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{100 * v:.1f}%"


def max_dd(s):
    if len(s) == 0:
        return 0.0
    cum = pd.Series(s).cumsum().values
    peak = np.maximum.accumulate(cum)
    return float((cum - peak).min())


def stats_pnl(p):
    s = pd.Series(p).dropna()
    if len(s) == 0:
        return {"n": 0}
    wins = s[s > 0]
    losses = s[s < 0]
    pf = (wins.sum() / abs(losses.sum())
            if len(losses) and losses.sum() != 0 else float("inf"))
    return {"n": len(s), "wr": float((s > 0).mean()),
            "mean": float(s.mean()), "median": float(s.median()),
            "sum": float(s.sum()), "pf": pf,
            "max_dd": max_dd(s),
            "avg_win": float(wins.mean()) if len(wins) else float("nan"),
            "avg_loss": float(losses.mean()) if len(losses)
                          else float("nan")}


def cohen_d(a, b):
    a = pd.Series(a).dropna()
    b = pd.Series(b).dropna()
    if len(a) < 2 or len(b) < 2:
        return float("nan")
    pooled = np.sqrt(((len(a) - 1) * a.var()
                        + (len(b) - 1) * b.var())
                       / (len(a) + len(b) - 2))
    if pooled == 0:
        return float("nan")
    return (a.mean() - b.mean()) / pooled


def load_all():
    dfs = {}
    for year in YEARS:
        for mode in MODES:
            p = OUT / f"features_{mode}_{year}.parquet"
            if p.exists():
                dfs[(year, mode)] = pd.read_parquet(p)
    return dfs


# =============================================================
# LAYER 1: 2026 FAILURE ANATOMY
# =============================================================

def layer1_year_comparison(dfs, lines):
    lines.append("## L1.1 — Year comparison")
    lines.append("")
    lines.append("| Year | Mode | n | WR | Mean $ | PF | Avg Win | "
                 "Avg Loss | Med Dur | Med ATR | Med Reg Age | "
                 "Med Chop_10 | Med Flip 60m |")
    lines.append(
        "|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
    for (year, mode), df in dfs.items():
        s = stats_pnl(df["final_net_pnl"])
        med_dur = df["duration_s"].median() / 60
        med_atr = df["atr_at_signal"].median()
        med_age = df["avg_dur_5_bars"].median()
        med_chop = df["chop_10"].median()
        med_flip = df["flip_count_60m"].median()
        lines.append(
            f"| {year} | {mode} | {s['n']:,} | "
            f"{fmt_p(s['wr'])} | {fmt_d(s['mean'])} | "
            f"{s['pf']:.2f} | {fmt_d(s['avg_win'])} | "
            f"{fmt_d(s['avg_loss'])} | {med_dur:.1f}m | "
            f"{med_atr:.2f} | {med_age:.1f} | "
            f"{med_chop:.2f} | {med_flip:.0f} |")
    lines.append("")


def layer1_winner_vs_loser(dfs, lines):
    lines.append("## L1.2 — Winner vs loser feature differences")
    lines.append("")
    lines.append("Per year-mode: median for winners vs losers, "
                 "and Cohen's d effect size. Top |d| ranked.")
    lines.append("")
    for (year, mode), df in dfs.items():
        winners = df[df["is_winner_net"] == 1]
        losers = df[df["is_winner_net"] == 0]
        if not len(winners) or not len(losers):
            continue
        rows = []
        for f in NUMERIC_FEATURES:
            if f not in df.columns:
                continue
            wm = winners[f].median()
            lm = losers[f].median()
            d = cohen_d(winners[f], losers[f])
            if pd.isna(d):
                continue
            rows.append((f, wm, lm, d))
        rows.sort(key=lambda r: -abs(r[3]))
        lines.append(f"### {year} — {mode} (top 12 by |d|)")
        lines.append("")
        lines.append("| Feature | Med Win | Med Loss | Δ | "
                     "Cohen's d |")
        lines.append("|---|--:|--:|--:|--:|")
        for f, wm, lm, d in rows[:12]:
            lines.append(
                f"| {f} | {wm:.3f} | {lm:.3f} | "
                f"{wm - lm:+.3f} | {d:+.3f} |")
        lines.append("")


def layer1_2026_vs_others(dfs, lines):
    lines.append("## L1.3 — 2026 vs 2024/2025 difference")
    lines.append("")
    lines.append("Compare 2026 trades (all) vs 2024+2025 trades (all) "
                 "per mode. Shows what is structurally different "
                 "about 2026 entries.")
    lines.append("")
    for mode in MODES:
        df_2026 = dfs.get((2026, mode), pd.DataFrame())
        df_other = pd.concat([dfs.get((2024, mode), pd.DataFrame()),
                                dfs.get((2025, mode), pd.DataFrame())],
                                ignore_index=True)
        if not len(df_2026) or not len(df_other):
            continue
        rows = []
        for f in NUMERIC_FEATURES:
            if f not in df_2026.columns:
                continue
            m26 = df_2026[f].median()
            mo = df_other[f].median()
            d = cohen_d(df_2026[f], df_other[f])
            if pd.isna(d):
                continue
            rows.append((f, m26, mo, d))
        rows.sort(key=lambda r: -abs(r[3]))
        lines.append(f"### {mode} — top 15 differences (2026 vs "
                     f"2024+2025)")
        lines.append("")
        lines.append("| Feature | Med 2026 | Med 24+25 | Δ | "
                     "Cohen's d |")
        lines.append("|---|--:|--:|--:|--:|")
        for f, m26, mo, d in rows[:15]:
            lines.append(
                f"| {f} | {m26:.3f} | {mo:.3f} | "
                f"{m26 - mo:+.3f} | {d:+.3f} |")
        lines.append("")

    lines.append("### 2026-LOSING vs 2024/2025-PROFITABLE — direct "
                 "cohort comparison")
    lines.append("")
    for mode in MODES:
        df_2026_l = dfs.get((2026, mode), pd.DataFrame())
        if len(df_2026_l):
            df_2026_l = df_2026_l[
                df_2026_l["is_winner_net"] == 0]
        df_other_w = pd.concat([
            dfs.get((2024, mode), pd.DataFrame()),
            dfs.get((2025, mode), pd.DataFrame())],
            ignore_index=True)
        if len(df_other_w):
            df_other_w = df_other_w[
                df_other_w["is_winner_net"] == 1]
        if not len(df_2026_l) or not len(df_other_w):
            continue
        rows = []
        for f in NUMERIC_FEATURES:
            m26l = df_2026_l[f].median()
            mow = df_other_w[f].median()
            d = cohen_d(df_2026_l[f], df_other_w[f])
            if pd.isna(d):
                continue
            rows.append((f, m26l, mow, d))
        rows.sort(key=lambda r: -abs(r[3]))
        lines.append(f"#### {mode} — 2026 losers vs 24+25 winners "
                     "(top 12)")
        lines.append("")
        lines.append("| Feature | Med 2026L | Med 24+25W | Δ | d |")
        lines.append("|---|--:|--:|--:|--:|")
        for f, m26l, mow, d in rows[:12]:
            lines.append(
                f"| {f} | {m26l:.3f} | {mow:.3f} | "
                f"{m26l - mow:+.3f} | {d:+.3f} |")
        lines.append("")


def layer1_simple_filters(dfs, lines):
    lines.append("## L1.4 — Simple candidate filters")
    lines.append("")
    lines.append("Each filter applied per (year, mode). A filter "
                 "is **promising** only if it improves 2026 without "
                 "destroying 2024/2025.")
    lines.append("")

    # Define filters from features that ranked high in L1.3
    filters = [
        ("low chop (chop_10 <= year median)",
         lambda d, med: d["chop_10"] <= med["chop_10"]),
        ("strong confirm (close_loc >= 0.7 if bull, "
         "<= 0.3 if bear)",
         lambda d, med: (
             ((d["direction"] == 1) & (d["confirm_close_loc"] >= 0.7))
             | ((d["direction"] == -1) & (d["confirm_close_loc"] <= 0.3)))),
        ("strong confirm body (body_pct >= 0.5)",
         lambda d, med: d["confirm_body_pct"] >= 0.5),
        ("low recent flip count (flip_count_60m <= 5)",
         lambda d, med: d["flip_count_60m"] <= 5),
        ("high pre-signal efficiency (eff_10 >= 0.4)",
         lambda d, med: d["eff_10"] >= 0.4),
        ("5m aligned",
         lambda d, med: d["regime_5m_aligned"] == 1),
        ("morning session (minutes_since_open <= 60)",
         lambda d, med: d["minutes_since_open"] <= 60),
        ("not afternoon (minutes_since_open <= 240)",
         lambda d, med: d["minutes_since_open"] <= 240),
        ("HMM state not 3 at signal",
         lambda d, med: d["hmm_state_at_signal"] != 3),
        ("not high ATR pct (atr_pct_500 < 0.7)",
         lambda d, med: d["atr_pct_500"] < 0.7),
        ("low chop + strong confirm",
         lambda d, med: (d["chop_10"] <= med["chop_10"])
                          & (d["confirm_body_pct"] >= 0.5)),
        ("low chop + 5m aligned",
         lambda d, med: (d["chop_10"] <= med["chop_10"])
                          & (d["regime_5m_aligned"] == 1)),
        ("strong confirm + 5m aligned",
         lambda d, med: (d["confirm_body_pct"] >= 0.5)
                          & (d["regime_5m_aligned"] == 1)),
    ]
    lines.append("| Filter | Mode | Year | %kept | n | WR | "
                 "Mean $ | PF | Total $ | Max DD | Δ Mean | Δ Total |")
    lines.append(
        "|---|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
    for fname, ffn in filters:
        for mode in MODES:
            for year in YEARS:
                df = dfs.get((year, mode))
                if df is None or not len(df):
                    continue
                base = stats_pnl(df["final_net_pnl"])
                med = df.median(numeric_only=True)
                mask = ffn(df, med)
                kept = df[mask]
                if not len(kept):
                    continue
                ks = stats_pnl(kept["final_net_pnl"])
                lines.append(
                    f"| {fname} | {mode} | {year} | "
                    f"{fmt_p(len(kept) / len(df))} | "
                    f"{ks['n']:,} | {fmt_p(ks['wr'])} | "
                    f"{fmt_d(ks['mean'])} | {ks['pf']:.2f} | "
                    f"{fmt_d(ks['sum'])} | "
                    f"{fmt_d(ks['max_dd'])} | "
                    f"{fmt_d(ks['mean'] - base['mean'])} | "
                    f"{fmt_d(ks['sum'] - base['sum'])} |")
        lines.append("")


def layer1_scaleup_cohort(dfs, lines):
    lines.append("## L1.5 — Scale-up eligible cohort search")
    lines.append("")
    lines.append("For each promising filter from L1.4, report "
                 "cross-year stability. Eligible only if positive in "
                 "all 3 years.")
    lines.append("")
    # Re-evaluate the top filters across all 3 years
    filters = [
        ("low chop + strong confirm",
         lambda d, med: (d["chop_10"] <= med["chop_10"])
                          & (d["confirm_body_pct"] >= 0.5)),
        ("low chop + 5m aligned",
         lambda d, med: (d["chop_10"] <= med["chop_10"])
                          & (d["regime_5m_aligned"] == 1)),
        ("strong confirm + 5m aligned",
         lambda d, med: (d["confirm_body_pct"] >= 0.5)
                          & (d["regime_5m_aligned"] == 1)),
        ("morning + 5m aligned",
         lambda d, med: (d["minutes_since_open"] <= 60)
                          & (d["regime_5m_aligned"] == 1)),
        ("morning + low chop",
         lambda d, med: (d["minutes_since_open"] <= 60)
                          & (d["chop_10"] <= med["chop_10"])),
        ("high HHLL break + 5m aligned",
         lambda d, med: (d["hhll_amount_atr"] >= 0.20)
                          & (d["regime_5m_aligned"] == 1)),
        ("strong confirm + low recent flips",
         lambda d, med: (d["confirm_body_pct"] >= 0.5)
                          & (d["flip_count_60m"] <= 5)),
    ]
    lines.append("| Filter | Mode | n_24 | mean_24 | n_25 | mean_25 | "
                 "n_26 | mean_26 | All 3 yrs +? |")
    lines.append("|---|---|--:|--:|--:|--:|--:|--:|---|")
    for fname, ffn in filters:
        for mode in MODES:
            cells = []
            year_means = {}
            year_ns = {}
            for year in YEARS:
                df = dfs.get((year, mode))
                if df is None or not len(df):
                    continue
                med = df.median(numeric_only=True)
                kept = df[ffn(df, med)]
                ks = stats_pnl(kept["final_net_pnl"])
                year_ns[year] = ks["n"]
                year_means[year] = ks["mean"]
            if len(year_means) < 3:
                continue
            all_pos = all(v > 0 for v in year_means.values())
            lines.append(
                f"| {fname} | {mode} | "
                f"{year_ns.get(2024, 0):,} | "
                f"{fmt_d(year_means.get(2024))} | "
                f"{year_ns.get(2025, 0):,} | "
                f"{fmt_d(year_means.get(2025))} | "
                f"{year_ns.get(2026, 0):,} | "
                f"{fmt_d(year_means.get(2026))} | "
                f"{'**YES**' if all_pos else 'no'} |")
    lines.append("")


# =============================================================
# LAYER 2: MAX-MFE STRUCTURAL STUDY
# =============================================================

def layer2_loser_mfe_buckets(dfs, lines):
    lines.append("# Layer 2 — Max-MFE Structural Study")
    lines.append("")
    lines.append("## L2.1 — Loser MFE buckets")
    lines.append("")
    lines.append("Among eventual losers, distribution of max MFE.")
    lines.append("")
    lines.append("| Year | Mode | Bucket (max MFE ATR) | n | "
                 "%losers | Avg Loss | Med Loss | Med Time-to-MFE | "
                 "Med Giveback | Med Time MFE→Exit |")
    lines.append(
        "|---|---|---|--:|--:|--:|--:|--:|--:|--:|")
    for (year, mode), df in dfs.items():
        losers = df[df["is_winner_net"] == 0]
        n_losers = len(losers)
        if not n_losers:
            continue
        buckets = [
            ("<0.25", losers["max_mfe_atr"] < 0.25),
            ("0.25-0.50",
             (losers["max_mfe_atr"] >= 0.25)
             & (losers["max_mfe_atr"] < 0.50)),
            ("0.50-0.75",
             (losers["max_mfe_atr"] >= 0.50)
             & (losers["max_mfe_atr"] < 0.75)),
            ("0.75-1.00",
             (losers["max_mfe_atr"] >= 0.75)
             & (losers["max_mfe_atr"] < 1.00)),
            ("1.00-1.50",
             (losers["max_mfe_atr"] >= 1.00)
             & (losers["max_mfe_atr"] < 1.50)),
            (">=1.50", losers["max_mfe_atr"] >= 1.50),
        ]
        for bname, mask in buckets:
            sub = losers[mask]
            n = len(sub)
            if not n:
                continue
            avg_l = sub["final_net_pnl"].mean()
            med_l = sub["final_net_pnl"].median()
            med_t_mfe = sub["time_to_max_mfe_s"].median()
            med_give = sub["peak_giveback_atr"].median()
            med_t_exit = (sub["duration_s"]
                            - sub["time_to_max_mfe_s"]).median()
            lines.append(
                f"| {year} | {mode} | {bname} | {n:,} | "
                f"{fmt_p(n / n_losers)} | "
                f"{fmt_d(avg_l)} | {fmt_d(med_l)} | "
                f"{med_t_mfe:.0f}s | "
                f"{med_give:.2f} ATR | "
                f"{med_t_exit:.0f}s |")
        lines.append("")


def layer2_mfe_structural_predictors(dfs, lines):
    lines.append("## L2.2 — Structural predictors of max MFE")
    lines.append("")
    lines.append("Compare trades reaching max MFE >= threshold vs "
                 "those that don't. Cohen's d on key features. "
                 "Combined across all years per mode.")
    lines.append("")
    for mode in MODES:
        all_df = pd.concat([dfs.get((y, mode), pd.DataFrame())
                              for y in YEARS], ignore_index=True)
        if not len(all_df):
            continue
        lines.append(f"### {mode}")
        lines.append("")
        for thr in [0.5, 1.0, 1.5, 2.0]:
            reached = all_df[all_df["max_mfe_atr"] >= thr]
            not_reached = all_df[all_df["max_mfe_atr"] < thr]
            if not len(reached) or not len(not_reached):
                continue
            n_reach = len(reached)
            n_total = len(all_df)
            lines.append(
                f"#### Max MFE >= {thr} ATR "
                f"({n_reach:,} / {n_total:,} = "
                f"{100*n_reach/n_total:.1f}%)")
            lines.append("")
            rows = []
            for f in NUMERIC_FEATURES:
                if f not in all_df.columns:
                    continue
                d = cohen_d(reached[f], not_reached[f])
                if pd.isna(d):
                    continue
                rm = reached[f].median()
                nm = not_reached[f].median()
                rows.append((f, rm, nm, d))
            rows.sort(key=lambda r: -abs(r[3]))
            lines.append("| Feature | Med Reached | Med Not | "
                         "Δ | d |")
            lines.append("|---|--:|--:|--:|--:|")
            for f, rm, nm, d in rows[:8]:
                lines.append(
                    f"| {f} | {rm:.3f} | {nm:.3f} | "
                    f"{rm - nm:+.3f} | {d:+.3f} |")
            lines.append("")


def layer2_early_path_predictors(dfs, lines):
    lines.append("## L2.3 — Early path predictors of max MFE")
    lines.append("")
    lines.append("For each (mode), pull paths_<mode>_<year>.parquet "
                 "and check whether path state at 30/60/120/180/300s "
                 "predicts final max MFE >= 1.0 ATR.")
    lines.append("")
    for mode in MODES:
        all_paths = []
        for year in YEARS:
            pp = (PATH_OUT / f"paths_{mode}_{year}.parquet")
            if not pp.exists():
                continue
            paths = pd.read_parquet(pp)
            tp = (PATH_OUT / f"trades_{mode}_{year}.parquet")
            trades = pd.read_parquet(tp)
            paths = paths.merge(
                trades[["trade_id", "max_mfe_atr",
                          "is_winner_net", "final_net_pnl"]],
                on="trade_id")
            all_paths.append(paths)
        if not all_paths:
            continue
        ap = pd.concat(all_paths, ignore_index=True)
        lines.append(f"### {mode}")
        lines.append("")
        lines.append("| Checkpoint | Med PnL ATR | Med MFE ATR | "
                     "Med MAE ATR | Med Giveback | %trades MFE>=1.0 "
                     "(eventual) | Cor(curr_PnL, max_MFE) |")
        lines.append("|--:|--:|--:|--:|--:|--:|--:|")
        for cp in [30, 60, 120, 180, 300]:
            cp_df = ap[ap["elapsed_s"] == cp]
            if not len(cp_df):
                continue
            med_pnl = cp_df["pnl_atr"].median()
            med_mfe = cp_df["peak_mfe_atr"].median()
            med_mae = cp_df["peak_mae_atr"].median()
            give = cp_df["peak_mfe_atr"] - cp_df["pnl_atr"]
            med_give = give.median()
            pct_event = (cp_df["max_mfe_atr"] >= 1.0).mean()
            cor = float(cp_df[
                ["pnl_atr", "max_mfe_atr"]].corr().iloc[0, 1])
            lines.append(
                f"| {cp}s | {med_pnl:.2f} | {med_mfe:.2f} | "
                f"{med_mae:.2f} | {med_give:.2f} | "
                f"{fmt_p(pct_event)} | {cor:.3f} |")
        lines.append("")

        lines.append("Conditional: at each checkpoint, "
                     "P(final max MFE >= 1.0 | current state) "
                     "for buckets of current PnL ATR.")
        lines.append("")
        lines.append("| Checkpoint | Bucket | n | "
                     "P(max MFE >= 1.0) | P(max MFE >= 1.5) | "
                     "P(eventual win) |")
        lines.append("|--:|---|--:|--:|--:|--:|")
        for cp in [60, 120, 180]:
            cp_df = ap[ap["elapsed_s"] == cp]
            if not len(cp_df):
                continue
            for label, mask in [
                ("PnL < 0",
                 cp_df["pnl_atr"] < 0),
                ("0 <= PnL < 0.25",
                 (cp_df["pnl_atr"] >= 0)
                 & (cp_df["pnl_atr"] < 0.25)),
                ("0.25 <= PnL < 0.5",
                 (cp_df["pnl_atr"] >= 0.25)
                 & (cp_df["pnl_atr"] < 0.5)),
                ("PnL >= 0.5",
                 cp_df["pnl_atr"] >= 0.5),
            ]:
                sub = cp_df[mask]
                if not len(sub):
                    continue
                p_mfe10 = (sub["max_mfe_atr"] >= 1.0).mean()
                p_mfe15 = (sub["max_mfe_atr"] >= 1.5).mean()
                p_win = sub["is_winner_net"].mean()
                lines.append(
                    f"| {cp}s | {label} | {len(sub):,} | "
                    f"{fmt_p(p_mfe10)} | {fmt_p(p_mfe15)} | "
                    f"{fmt_p(p_win)} |")
        lines.append("")


def layer2_exit_near_max(dfs, lines):
    lines.append("## L2.4 — Exit-near-max diagnostic")
    lines.append("")
    lines.append("Conditional 'after MFE >= X, exit if giveback "
                 ">= Y' rules. Reports separately for eventual "
                 "winners, losers, and all trades. "
                 "**Key**: a rule helping losers but destroying "
                 "winners must be rejected.")
    lines.append("")
    rules = [
        ("MFE>=0.50, giveback>=0.25", 0.50, 0.25),
        ("MFE>=0.75, giveback>=0.25", 0.75, 0.25),
        ("MFE>=1.00, giveback>=0.50", 1.00, 0.50),
        ("MFE>=1.50, giveback>=0.75", 1.50, 0.75),
    ]
    for mode in MODES:
        # Combine across years using path data
        all_dfs = []
        for year in YEARS:
            pp = (PATH_OUT / f"paths_{mode}_{year}.parquet")
            tp = (PATH_OUT / f"trades_{mode}_{year}.parquet")
            if not pp.exists() or not tp.exists():
                continue
            paths = pd.read_parquet(pp)
            trades = pd.read_parquet(tp)
            all_dfs.append((trades, paths, year))
        if not all_dfs:
            continue
        lines.append(f"### {mode}")
        lines.append("")
        lines.append("| Rule | Year | Group | n | Mean $ | "
                     "Δ vs hold-to-end | "
                     "Avg saved/sacrificed |")
        lines.append("|---|---|---|--:|--:|--:|--:|")
        for rname, mfe_thr, give_thr in rules:
            for trades, paths, year in all_dfs:
                # For each trade simulate the rule
                grouped = paths.groupby("trade_id")
                rule_pnl = []
                for _, row in trades.iterrows():
                    tid = row["trade_id"]
                    if tid not in grouped.groups:
                        rule_pnl.append(row["final_net_pnl"])
                        continue
                    path = grouped.get_group(tid).sort_values(
                        "elapsed_s")
                    pmfe = path["peak_mfe_atr"].values
                    ppnl = path["pnl_atr"].values
                    pclose = path["close_price"].values
                    active = False
                    exit_idx = None
                    for i in range(len(pmfe)):
                        if not active and pmfe[i] >= mfe_thr:
                            active = True
                        if active:
                            give = pmfe[i] - ppnl[i]
                            if give >= give_thr:
                                exit_idx = i
                                break
                    if exit_idx is not None:
                        atr = row["atr_at_signal"]
                        d = row["direction"]
                        fill = row["fill_price"]
                        gross = (pclose[exit_idx] - fill) * d * NQ_MULT
                        pnl = gross - 5.0 - 5.0  # comm + 1tick
                        rule_pnl.append(pnl)
                    else:
                        rule_pnl.append(row["final_net_pnl"])
                trades = trades.copy()
                trades["rule_pnl"] = rule_pnl
                for label, sub in [
                    ("eventual winners",
                     trades[trades["is_winner_net"] == 1]),
                    ("eventual losers",
                     trades[trades["is_winner_net"] == 0]),
                    ("all", trades),
                ]:
                    if not len(sub):
                        continue
                    base_mean = sub["final_net_pnl"].mean()
                    rule_mean = sub["rule_pnl"].mean()
                    diff = (sub["rule_pnl"]
                              - sub["final_net_pnl"])
                    lines.append(
                        f"| {rname} | {year} | {label} | "
                        f"{len(sub):,} | {fmt_d(rule_mean)} | "
                        f"{fmt_d(rule_mean - base_mean)} | "
                        f"{fmt_d(diff.mean())} |")
        lines.append("")


def layer2_key_summary(dfs, lines):
    lines.append("## L2.5 — Key summary table")
    lines.append("")
    lines.append("| Year | Mode | n total | %losers MFE>=0.5 | "
                 ">=0.75 | >=1.0 | >=1.5 | Avg loser final | "
                 "Med loser MFE | Med loser giveback |")
    lines.append(
        "|---|---|--:|--:|--:|--:|--:|--:|--:|--:|")
    for (year, mode), df in dfs.items():
        losers = df[df["is_winner_net"] == 0]
        n_l = len(losers)
        if not n_l:
            continue
        cells = [str(year), mode, f"{len(df):,}"]
        for thr in [0.5, 0.75, 1.0, 1.5]:
            cells.append(fmt_p((losers["max_mfe_atr"] >= thr).mean()))
        cells.append(fmt_d(losers["final_net_pnl"].mean()))
        cells.append(f"{losers['max_mfe_atr'].median():.2f}")
        cells.append(
            f"{losers['peak_giveback_atr'].median():.2f}")
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")


def main():
    dfs = load_all()
    print(f"Loaded {len(dfs)} (year, mode) feature tables")
    for k, v in dfs.items():
        print(f"  {k}: {len(v):,} rows")

    lines = []
    lines.append("# Momentum Confirm 2026 Failure Anatomy v1")
    lines.append("")
    lines.append("Two-layer diagnostic study using only pre-entry / "
                 "at-entry features (Layer 1) and full path labels "
                 "(Layer 2). Goal: identify what structurally "
                 "differs about 2026 trades, and whether eventual "
                 "losers have harvestable MFE first.")
    lines.append("")

    print("\nLayer 1...")
    layer1_year_comparison(dfs, lines)
    layer1_winner_vs_loser(dfs, lines)
    layer1_2026_vs_others(dfs, lines)
    layer1_simple_filters(dfs, lines)
    layer1_scaleup_cohort(dfs, lines)

    print("Layer 2...")
    layer2_loser_mfe_buckets(dfs, lines)
    layer2_mfe_structural_predictors(dfs, lines)
    layer2_early_path_predictors(dfs, lines)
    layer2_exit_near_max(dfs, lines)
    layer2_key_summary(dfs, lines)

    out_path = OUT / "ANATOMY_REPORT.md"
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport: {out_path}")


if __name__ == "__main__":
    main()
