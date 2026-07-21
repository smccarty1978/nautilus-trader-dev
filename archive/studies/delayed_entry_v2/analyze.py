"""Descriptive analysis on the matched-cohort table.

For each (T_d, stratum), compute:
  - N (matched cohort size)
  - T=0 baseline metrics
  - T_d delayed metrics
  - paired delta (T_d − T=0)

Strata: All, RTH, ETH, Long, Short, RTH×Long, RTH×Short, ETH×Long,
ETH×Short.

Output: one row per (T_d × stratum × endpoint) in a long-format
parquet, plus a wide-format markdown report.
"""

from __future__ import annotations
import numpy as np
import pandas as pd

# Endpoints with how to aggregate
# (suffix-stripped name, agg fn name, label for report)
ENDPOINTS = [
    ("regime_exit_pnl_dollars", "mean",   "regime_exit $ (mean)"),
    ("regime_exit_pnl_dollars", "median", "regime_exit $ (median)"),
    ("regime_exit_pnl_atr",     "mean",   "regime_exit ATR (mean)"),
    ("pt100_before_sl100",      "rate",   "PT100/SL100 win-rate"),
    ("pt150_before_sl100",      "rate",   "PT150/SL100 win-rate"),
    ("pt200_before_sl100",      "rate",   "PT200/SL100 win-rate"),
    ("mfe_60s_atr",             "mean",   "MFE 60s (ATR, mean)"),
    ("mae_60s_atr",             "mean",   "MAE 60s (ATR, mean)"),
    ("mfe_300s_atr",            "mean",   "MFE 300s (ATR, mean)"),
    ("clean_path_300s",         "rate",   "clean_path_300s rate"),
    ("fast_fail_60s",           "rate",   "fast_fail_60s rate"),
]


def _agg(series: pd.Series, kind: str) -> float:
    if len(series) == 0:
        return float("nan")
    s = series.dropna()
    if len(s) == 0:
        return float("nan")
    if kind == "mean":
        return float(s.mean())
    if kind == "median":
        return float(s.median())
    if kind == "rate":
        # "rate" assumes 0/1/NaN — for bracket outcomes, NaN means
        # neither side hit. Per project policy we EXCLUDE NaN from
        # the denominator (rate = wins / (wins + losses)).
        return float((s == 1).sum()) / float(len(s))
    raise ValueError(f"unknown kind: {kind}")


def _stratify(df: pd.DataFrame, stratum: str) -> pd.DataFrame:
    """Slice the matched-cohort table by stratum label."""
    if stratum == "All":
        return df
    if stratum == "RTH":
        return df[df["is_rth_checkpoint_t0"] == 1]
    if stratum == "ETH":
        return df[df["is_rth_checkpoint_t0"] == 0]
    if stratum == "Long":
        return df[df["signal_direction_t0"] == 1]
    if stratum == "Short":
        return df[df["signal_direction_t0"] == -1]
    if stratum == "RTH-Long":
        return df[(df["is_rth_checkpoint_t0"] == 1)
                   & (df["signal_direction_t0"] == 1)]
    if stratum == "RTH-Short":
        return df[(df["is_rth_checkpoint_t0"] == 1)
                   & (df["signal_direction_t0"] == -1)]
    if stratum == "ETH-Long":
        return df[(df["is_rth_checkpoint_t0"] == 0)
                   & (df["signal_direction_t0"] == 1)]
    if stratum == "ETH-Short":
        return df[(df["is_rth_checkpoint_t0"] == 0)
                   & (df["signal_direction_t0"] == -1)]
    raise ValueError(stratum)


STRATA = ["All", "RTH", "ETH", "Long", "Short",
          "RTH-Long", "RTH-Short", "ETH-Long", "ETH-Short"]


def build_descriptive_table(matched: pd.DataFrame) -> pd.DataFrame:
    """One row per (T_d, stratum, endpoint) with t0 / td / delta values."""
    rows = []
    for T_d in sorted(matched["T_d"].unique()):
        td_slice = matched[matched["T_d"] == T_d]
        for stratum in STRATA:
            sub = _stratify(td_slice, stratum)
            n = len(sub)
            for col, kind, label in ENDPOINTS:
                t0_val = _agg(sub[f"{col}_t0"], kind)
                td_val = _agg(sub[f"{col}_td"], kind)
                rows.append({
                    "T_d": T_d,
                    "stratum": stratum,
                    "n": n,
                    "endpoint": col,
                    "agg": kind,
                    "label": label,
                    "t0_value": t0_val,
                    "td_value": td_val,
                    "delta": td_val - t0_val,
                })
    return pd.DataFrame(rows)


def write_markdown_report(
    desc: pd.DataFrame,
    matched: pd.DataFrame,
    out_path,
) -> None:
    """Render a focused markdown report from the descriptive table."""
    lines: list[str] = []
    lines.append("# Delayed Entry Study v2 — Descriptive Report")
    lines.append("")
    lines.append("Source: `studies/delayed_entry_v2/results/"
                  "matched_cohort_long.parquet`")
    lines.append("")
    lines.append(f"- Total matched-cohort rows: {len(matched):,}")
    n_events = matched["event_id"].nunique()
    lines.append(f"- Distinct events: {n_events:,}")
    lines.append("")

    # Per-T_d cohort sizes
    cohort_sizes = matched.groupby("T_d")["event_id"].nunique()
    lines.append("## Matched cohort size by T_d")
    lines.append("")
    lines.append("| T_d (s) | Events fillable at both T=0 and T_d |")
    lines.append("|--------:|---:|")
    for T_d, n in cohort_sizes.items():
        lines.append(f"| {T_d} | {n:,} |")
    lines.append("")
    if 0 in cohort_sizes.index and 600 in cohort_sizes.index:
        n0 = cohort_sizes[0]
        n600 = cohort_sizes[600]
        retention = 100 * n600 / n0 if n0 else 0
        lines.append(
            f"Retention at T=600: {retention:.1f}% "
            f"({n600:,} / {n0:,})")
        lines.append("")

    # All-stratum endpoint table
    lines.append("## ALL stratum — endpoints by T_d")
    lines.append("")
    all_table = (desc[desc["stratum"] == "All"]
                  .pivot_table(index="T_d", columns="label",
                                values=["t0_value", "td_value",
                                        "delta"]))
    # Render compact table
    for label in [e[2] for e in ENDPOINTS]:
        lines.append(f"### {label}")
        lines.append("")
        sub = desc[(desc["stratum"] == "All")
                    & (desc["label"] == label)]
        lines.append("| T_d (s) | T=0 | T_d | Δ (T_d − T=0) |")
        lines.append("|--------:|----:|----:|----:|")
        for _, r in sub.iterrows():
            lines.append(
                f"| {int(r['T_d'])} | "
                f"{_fmt(r['t0_value'])} | "
                f"{_fmt(r['td_value'])} | "
                f"{_fmt(r['delta'])} |")
        lines.append("")

    # Stratified table for the bottom-line economic endpoint
    lines.append("## Regime-exit $ (mean) by stratum × T_d")
    lines.append("")
    pe = (desc[(desc["label"] == "regime_exit $ (mean)")]
            .pivot_table(index="T_d", columns="stratum",
                          values="td_value"))
    pe = pe[STRATA]  # reorder columns
    lines.append("| T_d | " + " | ".join(STRATA) + " |")
    lines.append("|--:|" + "|".join("--:" for _ in STRATA) + "|")
    for T_d, row in pe.iterrows():
        cells = " | ".join(_fmt(v) for v in row.values)
        lines.append(f"| {int(T_d)} | {cells} |")
    lines.append("")

    # Verdict heuristic
    lines.append("## Recommendation")
    lines.append("")
    all_pnl = desc[(desc["stratum"] == "All")
                    & (desc["label"] == "regime_exit $ (mean)")]
    pos_deltas = (all_pnl["delta"] > 0).sum()
    neg_deltas = (all_pnl["delta"] < 0).sum()
    max_pos = all_pnl["delta"].max()
    max_neg = all_pnl["delta"].min()
    lines.append(
        f"- ALL-stratum regime-exit $ delta sign across T_d>0: "
        f"{int(pos_deltas)} positive, {int(neg_deltas)} negative")
    lines.append(
        f"- Best (T_d $ - T=0 $): {_fmt(max_pos)}; worst: {_fmt(max_neg)}")
    if max_pos > 5:
        lines.append("- VERDICT: positive delta worth investigating "
                      "with ML ranking on this matched cohort.")
    elif max_neg < -5:
        lines.append("- VERDICT: delay clearly hurts on regime-exit "
                      "$ — ML unlikely to recover.")
    else:
        lines.append("- VERDICT: deltas near zero on regime-exit $ — "
                      "look at bracket / clean-path metrics for "
                      "alternative signal before committing to ML.")

    out_path = str(out_path)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _fmt(v) -> str:
    if pd.isna(v):
        return "—"
    if abs(v) >= 100:
        return f"{v:,.0f}"
    if abs(v) >= 10:
        return f"{v:,.1f}"
    if abs(v) >= 1:
        return f"{v:,.2f}"
    if v == 0:
        return "0"
    return f"{v:.3f}"
