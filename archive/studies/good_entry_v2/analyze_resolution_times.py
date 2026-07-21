"""Resolution-time analysis for the 1 ATR / 1 ATR bracket.

For PT hits and SL hits, show how quickly the bracket resolves across
the RTH OOS 2025 population. Strata include:
  - overall (PT vs SL)
  - by direction (Long × PT, Long × SL, Short × PT, Short × SL)
  - by entry T bucket (0-90s, 90-180s, 180-300s, 300-450s, 450-600s)
  - by model-score decile
  - cumulative distribution (% resolved within {30, 60, 120, 300,
    600, 1200, 1800}s)

Reads resolution times from the 2025 labels parquet (they aren't in
the Phase 3 predictions file).
"""

from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd


LABELS_PATH = Path(
    "studies/1m_regime_collector_v2/results/v2_outcome_labels_2025.parquet")
PRED_PATH = Path(
    "studies/good_entry_v2/results/phase3_oos_predictions_huber.parquet")
OUT = Path("studies/good_entry_v2/results/RESOLUTION_TIMES.md")

RES_COL = "bracket_resolution_time_s_pt100_before_sl100"
OUTCOME_COL = "pt100_before_sl100"


def risk_time(s: pd.Series) -> dict:
    s = s.dropna()
    if len(s) == 0:
        return {"n": 0}
    return {
        "n": int(len(s)),
        "mean": float(s.mean()),
        "median": float(s.median()),
        "p25": float(s.quantile(0.25)),
        "p75": float(s.quantile(0.75)),
        "p90": float(s.quantile(0.90)),
        "min": float(s.min()),
        "max": float(s.max()),
    }


def cdf_row(s: pd.Series, thresholds: list[int]) -> dict:
    s = s.dropna()
    if len(s) == 0:
        return {f"pct_le_{t}s": float("nan") for t in thresholds}
    return {f"pct_le_{t}s": float((s <= t).mean())
            for t in thresholds}


def fmt_t(v) -> str:
    if v is None or pd.isna(v):
        return "—"
    if v >= 100:
        return f"{v:,.0f}s"
    return f"{v:.1f}s"


def fmt_p(v) -> str:
    if v is None or pd.isna(v):
        return "—"
    return f"{100 * v:.1f}%"


def main():
    # Load labels (has the resolution time) and predictions (has score)
    labels = pd.read_parquet(LABELS_PATH)[
        ["event_id", "checkpoint_s", OUTCOME_COL, RES_COL]]
    preds = pd.read_parquet(PRED_PATH)

    df = preds.merge(labels, on=["event_id", "checkpoint_s"],
                      how="inner", suffixes=("", "_lbl"))
    # Use the labels version of pt100 (they should be identical but
    # merge cleanly)
    outcome = df[OUTCOME_COL] if OUTCOME_COL in df.columns else df[
        OUTCOME_COL + "_lbl"]
    df[OUTCOME_COL] = outcome
    res_col = RES_COL if RES_COL in df.columns else RES_COL + "_lbl"
    df[RES_COL] = df[res_col]

    resolved = df[df[OUTCOME_COL].notna()].copy()
    print(f"Rows: {len(df):,}  resolved: {len(resolved):,}")

    # Only rows with both outcome and resolution time
    resolved = resolved.dropna(subset=[RES_COL])
    resolved["outcome_str"] = np.where(
        resolved[OUTCOME_COL] == 1, "PT", "SL")
    resolved["direction_str"] = np.where(
        resolved["signal_direction"] == 1, "Long", "Short")

    # T bucket for entry
    def t_bucket(t):
        if t < 90:
            return "0-90s"
        if t < 180:
            return "90-180s"
        if t < 300:
            return "180-300s"
        if t < 450:
            return "300-450s"
        return "450-600s"
    resolved["t_bucket"] = resolved["checkpoint_s"].apply(t_bucket)

    # Score decile
    resolved["score_decile"] = pd.qcut(
        resolved["score"].rank(method="first"),
        q=10, labels=False)

    lines: list[str] = []
    lines.append("# Bracket Resolution Times (PT/SL = 1 ATR)")
    lines.append("")
    lines.append(f"Source: RTH OOS 2025 (n={len(df):,}, "
                  f"resolved={len(resolved):,})")
    lines.append("")

    # ---- 1. Overall PT vs SL ----
    lines.append("## Overall PT vs SL resolution time (seconds)")
    lines.append("")
    lines.append("| Outcome | n | Mean | Median | p25 | p75 | p90 "
                  "| Min | Max |")
    lines.append("|---|--:|--:|--:|--:|--:|--:|--:|--:|")
    for outcome in ["PT", "SL"]:
        sub = resolved[resolved["outcome_str"] == outcome]
        r = risk_time(sub[RES_COL])
        lines.append(
            f"| {outcome} | {r['n']:,} | "
            f"{fmt_t(r['mean'])} | {fmt_t(r['median'])} | "
            f"{fmt_t(r['p25'])} | {fmt_t(r['p75'])} | "
            f"{fmt_t(r['p90'])} | {fmt_t(r['min'])} | "
            f"{fmt_t(r['max'])} |")
    lines.append("")

    # ---- 2. By direction × outcome ----
    lines.append("## Resolution time by direction × outcome")
    lines.append("")
    lines.append("| Direction | Outcome | n | Mean | Median | p25 | "
                  "p75 | p90 |")
    lines.append("|---|---|--:|--:|--:|--:|--:|--:|")
    for direction in ["Long", "Short"]:
        for outcome in ["PT", "SL"]:
            sub = resolved[(resolved["direction_str"] == direction)
                            & (resolved["outcome_str"] == outcome)]
            r = risk_time(sub[RES_COL])
            lines.append(
                f"| {direction} | {outcome} | {r['n']:,} | "
                f"{fmt_t(r['mean'])} | {fmt_t(r['median'])} | "
                f"{fmt_t(r['p25'])} | {fmt_t(r['p75'])} | "
                f"{fmt_t(r['p90'])} |")
    lines.append("")

    # ---- 3. Cumulative distribution ----
    lines.append("## Cumulative resolution (% resolved within X seconds)")
    lines.append("")
    thresholds = [30, 60, 120, 180, 300, 600, 1200, 1800]
    lines.append("| Cut | " + " | ".join(f"≤{t}s" for t in thresholds)
                  + " |")
    lines.append("|---|" + "|".join("--:" for _ in thresholds) + "|")
    for label, mask in [
        ("All PT", resolved["outcome_str"] == "PT"),
        ("All SL", resolved["outcome_str"] == "SL"),
        ("Long PT", (resolved["outcome_str"] == "PT")
                     & (resolved["direction_str"] == "Long")),
        ("Long SL", (resolved["outcome_str"] == "SL")
                     & (resolved["direction_str"] == "Long")),
        ("Short PT", (resolved["outcome_str"] == "PT")
                      & (resolved["direction_str"] == "Short")),
        ("Short SL", (resolved["outcome_str"] == "SL")
                      & (resolved["direction_str"] == "Short")),
    ]:
        sub = resolved[mask]
        cdf = cdf_row(sub[RES_COL], thresholds)
        cells = " | ".join(fmt_p(cdf[f"pct_le_{t}s"]) for t in thresholds)
        lines.append(f"| {label} (n={len(sub):,}) | {cells} |")
    lines.append("")

    # ---- 4. By entry T bucket × outcome ----
    lines.append("## Resolution time by entry T bucket × outcome")
    lines.append("")
    lines.append("| T bucket | Outcome | n | Mean | Median | p25 "
                  "| p75 | p90 |")
    lines.append("|---|---|--:|--:|--:|--:|--:|--:|")
    for t_label in ["0-90s", "90-180s", "180-300s", "300-450s",
                      "450-600s"]:
        for outcome in ["PT", "SL"]:
            sub = resolved[(resolved["t_bucket"] == t_label)
                            & (resolved["outcome_str"] == outcome)]
            r = risk_time(sub[RES_COL])
            if r["n"] == 0:
                continue
            lines.append(
                f"| {t_label} | {outcome} | {r['n']:,} | "
                f"{fmt_t(r['mean'])} | {fmt_t(r['median'])} | "
                f"{fmt_t(r['p25'])} | {fmt_t(r['p75'])} | "
                f"{fmt_t(r['p90'])} |")
    lines.append("")

    # ---- 5. By score decile × outcome ----
    lines.append("## Resolution time by score decile × outcome")
    lines.append("")
    lines.append("| Decile | Outcome | n | Mean | Median | p25 | "
                  "p75 | Hit rate in decile |")
    lines.append("|---|---|--:|--:|--:|--:|--:|--:|")
    for d in range(10):
        for outcome in ["PT", "SL"]:
            sub = resolved[(resolved["score_decile"] == d)
                            & (resolved["outcome_str"] == outcome)]
            r = risk_time(sub[RES_COL])
            if r["n"] == 0:
                continue
            # Hit rate = fraction of this decile that had this outcome
            total_in_decile = int(
                (resolved["score_decile"] == d).sum())
            rate = r["n"] / total_in_decile if total_in_decile else 0
            lines.append(
                f"| D{d} | {outcome} | {r['n']:,} | "
                f"{fmt_t(r['mean'])} | {fmt_t(r['median'])} | "
                f"{fmt_t(r['p25'])} | {fmt_t(r['p75'])} | "
                f"{fmt_p(rate)} |")
    lines.append("")

    # ---- 6. Key reading ----
    lines.append("## Quick reading guide")
    lines.append("")
    # Compute some headline numbers for the summary
    pt_all = resolved[resolved["outcome_str"] == "PT"][RES_COL]
    sl_all = resolved[resolved["outcome_str"] == "SL"][RES_COL]
    lines.append(
        f"- Median time to PT: **{fmt_t(pt_all.median())}** "
        f"(mean {fmt_t(pt_all.mean())})")
    lines.append(
        f"- Median time to SL: **{fmt_t(sl_all.median())}** "
        f"(mean {fmt_t(sl_all.mean())})")
    pt_under_60 = float((pt_all <= 60).mean())
    sl_under_60 = float((sl_all <= 60).mean())
    lines.append(
        f"- Within first 60 seconds: {fmt_p(pt_under_60)} of PTs "
        f"hit vs {fmt_p(sl_under_60)} of SLs")
    pt_under_300 = float((pt_all <= 300).mean())
    sl_under_300 = float((sl_all <= 300).mean())
    lines.append(
        f"- Within 300 seconds: {fmt_p(pt_under_300)} PTs vs "
        f"{fmt_p(sl_under_300)} SLs")
    lines.append("")

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote: {OUT}")


if __name__ == "__main__":
    main()
