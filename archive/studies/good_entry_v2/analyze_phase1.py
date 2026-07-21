"""Phase 1 descriptive analysis for the good-entry study.

For each checkpoint T in [0, 600] every 30s, report:
  - fillable count and %
  - good_entry_300s base rate (overall + RTH/ETH + Long/Short)
  - censoring rate at the 300s window
  - economic discrimination: regime_exit $ and PT100 win-rate for the
    good_entry_300s == 1 subset vs all fillable rows
"""

from __future__ import annotations
import numpy as np
import pandas as pd


def _rate(num: int, den: int) -> float:
    return num / den if den else float("nan")


def _agg_pnl(s: pd.Series) -> dict:
    s = s.dropna()
    if len(s) == 0:
        return {"n": 0, "mean": float("nan"), "median": float("nan")}
    return {"n": int(len(s)), "mean": float(s.mean()),
             "median": float(s.median())}


def build_phase1_table(cohort: pd.DataFrame) -> pd.DataFrame:
    """One row per (T, stratum) with descriptive stats."""
    rows: list[dict] = []
    strata = [
        ("All", lambda d: d),
        ("RTH", lambda d: d[d["is_rth_checkpoint"] == 1]),
        ("ETH", lambda d: d[d["is_rth_checkpoint"] == 0]),
        ("Long", lambda d: d[d["signal_direction"] == 1]),
        ("Short", lambda d: d[d["signal_direction"] == -1]),
        ("RTH-Long", lambda d: d[(d["is_rth_checkpoint"] == 1)
                                  & (d["signal_direction"] == 1)]),
        ("RTH-Short", lambda d: d[(d["is_rth_checkpoint"] == 1)
                                   & (d["signal_direction"] == -1)]),
        ("ETH-Long", lambda d: d[(d["is_rth_checkpoint"] == 0)
                                  & (d["signal_direction"] == 1)]),
        ("ETH-Short", lambda d: d[(d["is_rth_checkpoint"] == 0)
                                   & (d["signal_direction"] == -1)]),
    ]

    for T in sorted(cohort["checkpoint_s"].unique()):
        slice_T = cohort[cohort["checkpoint_s"] == T]
        for stratum, fn in strata:
            sub = fn(slice_T)
            n_total = len(sub)
            fillable = sub[sub["fillable_at_T"] == True]
            n_fill = len(fillable)
            good = fillable[fillable["good_entry_300s"] == 1]
            n_good = len(good)
            censored = fillable["mfe_300s_censored"].sum() if (
                "mfe_300s_censored" in fillable.columns) else 0

            # Subset PnL (good_entry_300s == 1)
            sub_pnl = _agg_pnl(good["regime_exit_pnl_dollars"])
            # All fillable PnL
            all_pnl = _agg_pnl(fillable["regime_exit_pnl_dollars"])

            # PT100 win rates (drop NaN — bracket unresolved means
            # neither side hit, EXCLUDED from rate denominator per
            # standard convention; this is a labeling-stat report,
            # not a tradeability filter so survivor bias doesn't apply)
            sub_pt = good["pt100_before_sl100"].dropna()
            sub_pt_rate = (sub_pt == 1).mean() if len(sub_pt) else float("nan")
            all_pt = fillable["pt100_before_sl100"].dropna()
            all_pt_rate = (all_pt == 1).mean() if len(all_pt) else float("nan")

            rows.append({
                "T": int(T),
                "stratum": stratum,
                "n_total": n_total,
                "n_fillable": n_fill,
                "fillable_rate": _rate(n_fill, n_total),
                "n_good_entry": n_good,
                "good_entry_rate": _rate(n_good, n_fill),
                "censored_rate_300s": _rate(int(censored), n_fill),
                "subset_pnl_n": sub_pnl["n"],
                "subset_pnl_mean": sub_pnl["mean"],
                "subset_pnl_median": sub_pnl["median"],
                "all_pnl_mean": all_pnl["mean"],
                "all_pnl_median": all_pnl["median"],
                "subset_pt100_rate": sub_pt_rate,
                "all_pt100_rate": all_pt_rate,
                "subset_pt100_lift": (
                    sub_pt_rate - all_pt_rate
                    if not pd.isna(sub_pt_rate)
                       and not pd.isna(all_pt_rate)
                    else float("nan")),
            })
    return pd.DataFrame(rows)


def write_phase1_report(
    desc: pd.DataFrame,
    cohort: pd.DataFrame,
    out_path,
) -> None:
    lines: list[str] = []
    lines.append("# Good Entry v2 — Phase 1 Descriptive Report")
    lines.append("")
    n_events = cohort["event_id"].nunique()
    n_rows = len(cohort)
    n_fill = int((cohort["fillable_at_T"] == True).sum())
    n_good = int((cohort["good_entry_300s"] == 1).sum())
    base_rate = n_good / n_fill if n_fill else 0
    lines.append(f"- Cohort: {n_rows:,} (event, T) rows from "
                  f"{n_events:,} distinct events")
    lines.append(f"- T range: {sorted(cohort['checkpoint_s'].unique())}")
    lines.append(f"- Fillable: {n_fill:,} ({100 * n_fill / n_rows:.1f}%)")
    lines.append(
        f"- `good_entry_300s == 1`: {n_good:,} "
        f"({100 * base_rate:.1f}% of fillable)")
    lines.append("")

    # ===== Base rate by T (ALL stratum) =====
    lines.append("## Base rate of `good_entry_300s` by T (ALL)")
    lines.append("")
    lines.append("| T | n_fill | n_good | rate | censored% |")
    lines.append("|--:|--:|--:|--:|--:|")
    all_rows = desc[desc["stratum"] == "All"].sort_values("T")
    for _, r in all_rows.iterrows():
        lines.append(
            f"| {r['T']} | {int(r['n_fillable']):,} | "
            f"{int(r['n_good_entry']):,} | "
            f"{100 * r['good_entry_rate']:.2f}% | "
            f"{100 * r['censored_rate_300s']:.1f}% |")
    lines.append("")

    # ===== Base rate by T × stratum =====
    lines.append("## Base rate by T × stratum")
    lines.append("")
    pivot = (desc
              .pivot_table(index="T", columns="stratum",
                            values="good_entry_rate"))
    cols = ["All", "RTH", "ETH", "Long", "Short",
             "RTH-Long", "RTH-Short", "ETH-Long", "ETH-Short"]
    pivot = pivot[cols]
    lines.append("| T | " + " | ".join(cols) + " |")
    lines.append("|--:|" + "|".join("--:" for _ in cols) + "|")
    for T, row in pivot.iterrows():
        cells = " | ".join(
            f"{100 * v:.1f}%" if not pd.isna(v) else "—"
            for v in row.values)
        lines.append(f"| {int(T)} | {cells} |")
    lines.append("")

    # ===== Economic discrimination: subset PnL vs all PnL (ALL) =====
    lines.append(
        "## Economic discrimination — `good_entry_300s == 1` subset "
        "vs ALL fillable (regime_exit $ mean)")
    lines.append("")
    lines.append("| T | All-fillable mean $ | Subset mean $ | Lift $ "
                  "| Subset n | Subset PT100% | All PT100% | PT lift |")
    lines.append("|--:|--:|--:|--:|--:|--:|--:|--:|")
    for _, r in all_rows.iterrows():
        lift = (r["subset_pnl_mean"] - r["all_pnl_mean"]
                 if not pd.isna(r["subset_pnl_mean"])
                    and not pd.isna(r["all_pnl_mean"])
                 else float("nan"))
        lines.append(
            f"| {r['T']} | "
            f"{_d(r['all_pnl_mean'])} | "
            f"{_d(r['subset_pnl_mean'])} | "
            f"{_d(lift)} | "
            f"{int(r['subset_pnl_n']):,} | "
            f"{_p(r['subset_pt100_rate'])} | "
            f"{_p(r['all_pt100_rate'])} | "
            f"{_p(r['subset_pt100_lift'])} |")
    lines.append("")

    # ===== Subset PnL by stratum (mean) =====
    lines.append("## Subset mean regime-exit $ by T × stratum "
                  "(`good_entry_300s == 1` only)")
    lines.append("")
    pe = (desc.pivot_table(index="T", columns="stratum",
                            values="subset_pnl_mean"))
    pe = pe[cols]
    lines.append("| T | " + " | ".join(cols) + " |")
    lines.append("|--:|" + "|".join("--:" for _ in cols) + "|")
    for T, row in pe.iterrows():
        cells = " | ".join(_d(v) for v in row.values)
        lines.append(f"| {int(T)} | {cells} |")
    lines.append("")

    # ===== Verdict heuristic =====
    lines.append("## Phase 1 verdict")
    lines.append("")
    rates = all_rows["good_entry_rate"].values
    rate_max = float(np.nanmax(rates))
    rate_min = float(np.nanmin(rates))
    rate_mean = float(np.nanmean(rates))
    spread = rate_max - rate_min

    pnls = all_rows["subset_pnl_mean"].values
    pnl_max = float(np.nanmax(pnls))
    pnl_min = float(np.nanmin(pnls))

    lines.append(
        f"- Base rate spread across T (ALL): "
        f"{100 * rate_min:.1f}% – {100 * rate_max:.1f}% "
        f"(mean {100 * rate_mean:.1f}%, range {100 * spread:.1f}pp)")
    lines.append(
        f"- Subset mean $ across T: ${pnl_min:.2f} – ${pnl_max:.2f}")

    structure = "WEAK"
    if spread > 0.05 or pnl_max > 30:
        structure = "STRONG"
    elif spread > 0.02 or pnl_max > 15:
        structure = "MODERATE"

    if structure == "STRONG":
        lines.append(
            "- VERDICT: STRONG structure across T — Phase 2 ML modeling "
            "warranted. Train on contract `model_feature` columns with "
            "checkpoint_s included; event-grouped chronological split.")
    elif structure == "MODERATE":
        lines.append(
            "- VERDICT: MODERATE structure — Phase 2 worth attempting "
            "but expect modest AUC. Inspect stratum tables to see "
            "where structure concentrates before training.")
    else:
        lines.append(
            "- VERDICT: WEAK structure — base rate roughly uniform "
            "across T and subset PnL not clearly elevated. ML unlikely "
            "to find an actionable signal at this label horizon.")

    out_path = str(out_path)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _d(v) -> str:
    if pd.isna(v):
        return "—"
    return f"${v:,.2f}" if abs(v) < 1000 else f"${v:,.0f}"


def _p(v) -> str:
    if pd.isna(v):
        return "—"
    return f"{100 * v:.1f}%"
