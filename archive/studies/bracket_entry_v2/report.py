"""Markdown report writer for the bracket-entry study.

Computes classification metrics + bracket economics on OOS, stratified
by session-side and T bucket.

Bracket PnL is computed from pt100 + atr_at_signal only (no regime-exit
fallback — unresolved rows are excluded from economic tables per the
target rule).
"""

from __future__ import annotations
import numpy as np
import pandas as pd
from sklearn.metrics import (
    roc_auc_score, average_precision_score, brier_score_loss,
)

NQ_MULT = 20.0
COMMISSION = 5.0


def compute_bracket_pnl(df: pd.DataFrame) -> pd.Series:
    """PT: +atr × 20 − 5; SL: −atr × 20 − 5; Unresolved: NaN."""
    pt = df["pt100_before_sl100"].values
    atr = df["atr_at_signal"].values
    out = np.full(len(df), np.nan, dtype=float)
    for i in range(len(df)):
        v = pt[i]
        if pd.isna(v):
            continue
        if v == 1:
            out[i] = atr[i] * NQ_MULT - COMMISSION
        else:
            out[i] = -atr[i] * NQ_MULT - COMMISSION
    return pd.Series(out, index=df.index)


def risk(s: pd.Series) -> dict:
    s = s.dropna()
    if len(s) == 0:
        return {"n": 0, "mean": np.nan, "median": np.nan,
                 "trimmed_5pct": np.nan, "sum": 0.0,
                 "win_rate": np.nan, "pf": np.nan}
    wins = s[s > 0]
    losses = s[s < 0]
    k = int(len(s) * 0.05)
    trimmed = (s.sort_values().iloc[k:len(s) - k].mean()
                if k * 2 < len(s) else np.nan)
    return {
        "n": int(len(s)),
        "mean": float(s.mean()),
        "median": float(s.median()),
        "trimmed_5pct": float(trimmed),
        "sum": float(s.sum()),
        "win_rate": float((s > 0).mean()),
        "pf": (float(wins.sum() / abs(losses.sum()))
                if len(losses) and losses.sum() != 0
                else float("inf")),
    }


def _d(v) -> str:
    if v is None or pd.isna(v):
        return "—"
    if isinstance(v, float) and np.isinf(v):
        return "∞"
    return f"${v:,.2f}" if abs(v) < 1000 else f"${v:,.0f}"


def _p(v) -> str:
    if v is None or pd.isna(v):
        return "—"
    return f"{100 * v:.1f}%"


def _metrics(y_true, y_score) -> dict:
    if len(y_true) == 0 or y_true.sum() == 0 or y_true.sum() == len(y_true):
        return {"n": len(y_true), "base_rate": float("nan"),
                 "auc": float("nan"), "pr_auc": float("nan"),
                 "brier": float("nan")}
    return {
        "n": len(y_true),
        "base_rate": float(y_true.mean()),
        "auc": float(roc_auc_score(y_true, y_score)),
        "pr_auc": float(average_precision_score(y_true, y_score)),
        "brier": float(brier_score_loss(y_true, y_score)),
    }


def _stratify(df: pd.DataFrame, stratum: str) -> pd.DataFrame:
    if stratum == "ALL RTH":
        return df
    if stratum == "RTH-Long":
        return df[df["signal_direction"] == 1]
    if stratum == "RTH-Short":
        return df[df["signal_direction"] == -1]
    if stratum.startswith("T "):
        lo, hi = {"T 0-90s": (0, 90), "T 90-180s": (90, 180),
                   "T 180-300s": (180, 300), "T 300-450s": (300, 450),
                   "T 450-600s": (450, 601)}[stratum]
        return df[(df["checkpoint_s"] >= lo)
                   & (df["checkpoint_s"] < hi)]
    raise ValueError(stratum)


STRATA = ["ALL RTH", "RTH-Long", "RTH-Short",
          "T 0-90s", "T 90-180s", "T 180-300s",
          "T 300-450s", "T 450-600s"]


def build_topk_row(sub_resolved: pd.DataFrame, frac: float | None,
                    label: str) -> dict:
    """Return a row of bracket economics for a stratum × top-k cut."""
    if frac is None:
        top = sub_resolved
    else:
        k = int(round(frac * len(sub_resolved)))
        top = sub_resolved.sort_values("score",
                                         ascending=False).head(k)
    r = risk(top["bracket_pnl"])
    return {"label": label, **r}


def write_report(train_df: pd.DataFrame, val_df: pd.DataFrame,
                   oos_df_with_score: pd.DataFrame,
                   cohort_all_oos: pd.DataFrame,
                   feat_cols: list[str],
                   model, out_path) -> None:
    """Write the Phase-1 bracket-entry report.

    oos_df_with_score: the TRAINING-eligible rows from OOS (resolved
    only, with `score` column). Used for classification metrics and
    bracket economics.

    cohort_all_oos: the full OOS cohort including unresolved (no
    `score` column). Used for unresolved-rate reporting only.
    """
    lines: list[str] = []
    lines.append("# Bracket-Aligned Entry Quality Model — OOS 2025 Report")
    lines.append("")

    # --- Setup ---
    lines.append("## Setup")
    lines.append("")
    lines.append(f"- Features: {len(feat_cols)} "
                  "(role == model_feature, numeric, no pruning)")
    lines.append(f"- Target: `good_bracket_entry` "
                  "(pt100=1 AND mfe_mae_ratio_300s>1.25 AND "
                  "bracket_resolution_time_s ≤ 360s)")
    lines.append(f"- Unresolved rows EXCLUDED from training "
                  "and bracket economics.")
    lines.append(f"- Train: {len(train_df):,} rows from "
                  f"{train_df['event_id'].nunique():,} events "
                  f"(2020-2023, resolved only)")
    lines.append(f"- Val:   {len(val_df):,} rows from "
                  f"{val_df['event_id'].nunique():,} events "
                  f"(2024, resolved only)")
    lines.append(f"- OOS:   {len(oos_df_with_score):,} rows from "
                  f"{oos_df_with_score['event_id'].nunique():,} events "
                  f"(2025, resolved only)")
    lines.append(f"- Best iteration: {model.best_iteration}")
    lines.append("")

    # --- Unresolved reporting ---
    lines.append("## Unresolved rate (reporting only — not filtered on)")
    lines.append("")
    lines.append("| Stratum | n_total | n_unres | unres % |")
    lines.append("|---|--:|--:|--:|")
    for s in STRATA:
        sub = _stratify(cohort_all_oos, s)
        n_total = len(sub)
        n_unres = int(sub["unresolved"].sum())
        rate = n_unres / n_total if n_total else 0
        lines.append(f"| {s} | {n_total:,} | {n_unres:,} | "
                      f"{_p(rate)} |")
    lines.append("")

    # --- Classification metrics on OOS ---
    lines.append("## OOS classification metrics (resolved rows only)")
    lines.append("")
    y = oos_df_with_score["good_bracket_entry"].values
    s = oos_df_with_score["score"].values
    m = _metrics(y, s)
    lines.append(f"- N: {m['n']:,}")
    lines.append(f"- Base rate: {_p(m['base_rate'])}")
    lines.append(f"- **AUC: {m['auc']:.4f}**")
    lines.append(f"- **PR-AUC: {m['pr_auc']:.4f}** "
                  f"(baseline = {m['base_rate']:.4f})")
    lines.append(f"- Brier: {m['brier']:.4f}")
    lines.append("")

    lines.append("### Classification by stratum")
    lines.append("")
    lines.append("| Stratum | n | Base rate | AUC | PR-AUC |")
    lines.append("|---|--:|--:|--:|--:|")
    for st in STRATA:
        sub = _stratify(oos_df_with_score, st)
        mm = _metrics(sub["good_bracket_entry"].values,
                        sub["score"].values)
        lines.append(f"| {st} | {mm['n']:,} | "
                      f"{_p(mm['base_rate'])} | "
                      f"{mm['auc']:.4f} | {mm['pr_auc']:.4f} |")
    lines.append("")

    # --- Calibration ---
    lines.append("## Calibration (10 score deciles, OOS)")
    lines.append("")
    d = oos_df_with_score.copy()
    d["bucket"] = pd.qcut(d["score"].rank(method="first"),
                            q=10, labels=False)
    cal = (d.groupby("bucket")
             .agg(n=("good_bracket_entry", "size"),
                   pred_mean=("score", "mean"),
                   actual_rate=("good_bracket_entry", "mean"),
                   pnl_mean=("bracket_pnl", "mean"))
             .reset_index())
    lines.append("| Decile | n | Predicted | Actual | Mean $ |")
    lines.append("|--:|--:|--:|--:|--:|")
    for _, r in cal.iterrows():
        lines.append(f"| {int(r['bucket'])} | {int(r['n']):,} | "
                      f"{r['pred_mean']:.4f} | "
                      f"{_p(r['actual_rate'])} | "
                      f"{_d(r['pnl_mean'])} |")
    lines.append("")

    # --- Economics by stratum × top-k ---
    lines.append("## OOS bracket economics by stratum × top-k")
    lines.append("")
    lines.append("| Stratum | Cut | n | Mean $ | Median $ | "
                  "Trim 5% | Win% | PF | Total $ |")
    lines.append("|---|---|--:|--:|--:|--:|--:|--:|--:|")
    for st in STRATA:
        sub = _stratify(oos_df_with_score, st)
        if len(sub) == 0:
            continue
        rows = []
        rows.append(build_topk_row(sub, None, "ALL"))
        for frac in [0.30, 0.20, 0.10, 0.05]:
            rows.append(build_topk_row(sub, frac,
                                          f"top {int(frac*100)}%"))
        for rr in rows:
            lines.append(
                f"| {st} | {rr['label']} | {rr['n']:,} | "
                f"{_d(rr['mean'])} | {_d(rr['median'])} | "
                f"{_d(rr['trimmed_5pct'])} | "
                f"{_p(rr['win_rate'])} | "
                f"{rr['pf']:.2f} | {_d(rr['sum'])} |")
    lines.append("")

    # --- Feature importance ---
    lines.append("## Top 25 feature importances (gain)")
    lines.append("")
    imp = pd.DataFrame({
        "feature": feat_cols,
        "gain": model.feature_importance(importance_type="gain"),
        "split": model.feature_importance(importance_type="split"),
    }).sort_values("gain", ascending=False)
    total_gain = imp["gain"].sum()
    imp["pct"] = imp["gain"] / total_gain
    lines.append("| Rank | Feature | % gain | Splits |")
    lines.append("|--:|---|--:|--:|")
    for i, (_, r) in enumerate(imp.head(25).iterrows()):
        lines.append(f"| {i+1} | `{r['feature']}` | "
                      f"{100 * r['pct']:.1f}% | "
                      f"{int(r['split']):,} |")
    lines.append("")

    # --- Verdict ---
    lines.append("## Verdict")
    lines.append("")
    # Top-10% lift on ALL RTH
    all_oos = _stratify(oos_df_with_score, "ALL RTH")
    base = risk(all_oos["bracket_pnl"])
    top10 = build_topk_row(all_oos, 0.10, "top 10%")
    lift = top10["mean"] - base["mean"]
    lines.append(f"- OOS AUC: {m['auc']:.4f}")
    lines.append(f"- Base rate: {_p(m['base_rate'])}")
    lines.append(f"- ALL RTH top-10% economics: "
                  f"{_d(top10['mean'])} mean, "
                  f"{_d(top10['trimmed_5pct'])} trimmed, "
                  f"PF {top10['pf']:.2f}, "
                  f"lift {_d(lift)} vs baseline {_d(base['mean'])}")

    if m["auc"] > 0.60 and lift > 20:
        v = ("STRONG — AUC and economics both clear. "
              "Consider NT backtest with this score filter.")
    elif m["auc"] > 0.55 or lift > 10:
        v = ("MODERATE — measurable signal. Inspect stratum/T-bucket "
              "tables for concentration before committing.")
    else:
        v = ("WEAK — limited predictive signal. Target reframe or "
              "label adjustment may be needed.")
    lines.append(f"- VERDICT: {v}")

    out_path = str(out_path)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
