"""2025 ensemble baseline (failure + winner models) on full live pop.

Cheap analog of failure_filter_v1/combo_screening.py but for 2025
instead of 2026. Uses existing model predictions where available,
else trains the missing models with the right OOS split.

Two output flavors:
  A. Standard (signal_time + 30s fill) — same as prior screening
  B. Flip-fill-timing variant: same trade selection, but simulate
     fill at flip_time + 30s instead of signal_time + 30s. ACK
     lookahead in scoring; informational only.
"""

from __future__ import annotations
import os, sys, time, json
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
os.chdir(project_root)
sys.path.insert(0, str(project_root))

from nautilus_trader.persistence.catalog import ParquetDataCatalog

OUT = Path("studies/hmm_5s_v1/results")
OUT.mkdir(parents=True, exist_ok=True)
NQ_MULT = 20.0
COMMISSION = 5.0
TICK_COST = 5.0


def bracket_pnl_formulaic(df: pd.DataFrame, fill_price_col: str,
                             pnl_col_name: str) -> pd.Series:
    """Per-row bracket PnL based on pt100 + atr_at_signal.

    Doesn't depend on actual exit prices — uses formulaic outcome.
    Use fill_price_col only for unresolved-rows fallback.
    """
    pt = df["pt100_before_sl100"].values
    atr = df["atr_at_signal"].values
    out = np.empty(len(df), dtype=float)
    for i in range(len(df)):
        v = pt[i]
        if pd.isna(v):
            out[i] = -0.7 * atr[i] * NQ_MULT - COMMISSION - TICK_COST
        elif v == 1:
            out[i] = atr[i] * NQ_MULT - COMMISSION - TICK_COST
        else:
            out[i] = -atr[i] * NQ_MULT - COMMISSION - 2 * TICK_COST
    return pd.Series(out, index=df.index, name=pnl_col_name)


def stats(df: pd.DataFrame, pnl_col: str) -> dict:
    s = df[pnl_col].dropna()
    if len(s) == 0:
        return {"n": 0}
    wins = s[s > 0]
    losses = s[s < 0]
    k = int(len(s) * 0.05)
    trim = (s.sort_values().iloc[k:len(s) - k].mean()
             if k * 2 < len(s) else float("nan"))
    pt = df["pt100_before_sl100"]
    return {
        "n": len(s),
        "mean": float(s.mean()),
        "median": float(s.median()),
        "trimmed_5pct": float(trim),
        "sum": float(s.sum()),
        "win_rate": float((s > 0).mean()),
        "pf": (float(wins.sum() / abs(losses.sum()))
                if len(losses) and losses.sum() != 0
                else float("inf")),
        "pt_pct": float((pt == 1).mean()),
        "sl_pct": float((pt == 0).mean()),
        "regime_pct": float(pt.isna().mean()),
    }


def fmt_d(v):
    if v is None or pd.isna(v):
        return "—"
    if isinstance(v, float) and np.isinf(v):
        return "∞"
    return f"${v:,.2f}" if abs(v) < 1000 else f"${v:,.0f}"


def fmt_p(v):
    if v is None or pd.isna(v):
        return "—"
    return f"{100 * v:.1f}%"


def main():
    print("Loading 2025 OOS predictions from prior studies...")

    # Failure model: need 2025 OOS = train 2020-2023, val 2024
    # We have: failure_filter_v1/models_oos_2024 (train 2020-2022, val 2023)
    # We don't have a 2025-OOS-split failure model. Train fresh.

    sys.path.insert(0,
        str(project_root / "studies/bracket_entry_v2/feature_reduction"))
    sys.path.insert(0,
        str(project_root / "studies/failure_filter_v1"))
    from sweep import train_lgbm  # noqa
    from collect_and_train import (  # noqa
        add_failure_label, load_features, select_numeric)

    print("\n  Training failure model with 2025 OOS split...")
    cohort = pd.read_parquet(
        "studies/bracket_entry_v3_fullpop/results/cohort_v3.parquet")
    cohort = add_failure_label(cohort)
    feature_names = load_features(
        "models/ml_5m_flip/feature_contract_v2.json")
    feat_cols = select_numeric(cohort, feature_names)

    tr = cohort[cohort["year"].isin([2020, 2021, 2022, 2023])]
    va = cohort[cohort["year"] == 2024]
    oos = cohort[cohort["year"] == 2025]
    print(f"    Splits: tr={len(tr):,} va={len(va):,} oos={len(oos):,}")

    t0 = time.time()
    failure_model = train_lgbm(
        tr[feat_cols], tr["is_failure"],
        va[feat_cols], va["is_failure"])
    print(f"    Failure model trained in {time.time()-t0:.1f}s")

    # Score val + OOS
    val_failure_scores = failure_model.predict(
        va[feat_cols], num_iteration=failure_model.best_iteration)
    failure_threshold = float(np.quantile(val_failure_scores, 0.90))
    print(f"    Failure threshold (val 2024 p90): "
           f"{failure_threshold:.4f}")

    oos = oos.copy()
    oos["failure_score"] = failure_model.predict(
        oos[feat_cols], num_iteration=failure_model.best_iteration)

    # Train winner model with 2025 OOS split (train 2020-2023, val 2024)
    print("\n  Training winner model (PT-first label) with 2025 OOS split...")
    cohort_v3 = pd.read_parquet(
        "studies/bracket_entry_v3_fullpop/results/cohort_v3.parquet")
    # Use is_pt_first label (already in cohort_v3)
    tr_w = cohort_v3[
        (cohort_v3["year"].isin([2020, 2021, 2022, 2023]))
        & (cohort_v3["resolved"] == 1)]
    va_w = cohort_v3[
        (cohort_v3["year"] == 2024)
        & (cohort_v3["resolved"] == 1)]
    print(f"    Splits: tr={len(tr_w):,} (resolved only) "
           f"va={len(va_w):,}")
    winner_feat_cols = [c for c in feat_cols if c in cohort_v3.columns]
    t0 = time.time()
    winner_model = train_lgbm(
        tr_w[winner_feat_cols], tr_w["is_pt_first"],
        va_w[winner_feat_cols], va_w["is_pt_first"])
    print(f"    Winner model trained in {time.time()-t0:.1f}s")
    val_winner_scores = winner_model.predict(va_w[winner_feat_cols])
    winner_threshold = float(np.quantile(val_winner_scores, 0.90))
    print(f"    Winner threshold (val 2024 p90): "
           f"{winner_threshold:.4f}")

    # Score 2025 OOS (full population, not resolved-only)
    oos["winner_score"] = winner_model.predict(oos[winner_feat_cols])

    oos_merged = oos.copy()
    print(f"  Merged 2025 OOS rows: {len(oos_merged):,}")

    # Compute bracket PnL (formulaic)
    oos_merged["pnl_a"] = bracket_pnl_formulaic(
        oos_merged, "fill_price", "pnl_a")

    # Build slices
    rows = []

    def record(label, sub):
        s = stats(sub, "pnl_a")
        long_n = int((sub["signal_direction"] == 1).sum())
        short_n = int((sub["signal_direction"] == -1).sum())
        rows.append({
            "label": label, **s,
            "long_pct": (long_n / s["n"] if s["n"] else 0),
            "short_pct": (short_n / s["n"] if s["n"] else 0),
        })

    # 1. ALL
    record("ALL (no filter, no selection)", oos_merged)

    # 2. Winner only
    win_only = oos_merged[
        oos_merged["winner_score"] >= winner_threshold]
    record("Winner only (score >= val p90)", win_only)

    # 3. Failure only — 3 levels
    f_p98 = oos_merged["failure_score"].quantile(0.98)
    f_p95 = oos_merged["failure_score"].quantile(0.95)
    f_p90 = oos_merged["failure_score"].quantile(0.90)
    record("Failure-filter only excl worst 2%",
            oos_merged[oos_merged["failure_score"] < f_p98])
    record("Failure-filter only excl worst 5%",
            oos_merged[oos_merged["failure_score"] < f_p95])
    record("Failure-filter only excl worst 10%",
            oos_merged[oos_merged["failure_score"] < f_p90])

    # 4. Combined
    for label, mask in [
        ("excl worst 2%", oos_merged["failure_score"] < f_p98),
        ("excl worst 5%", oos_merged["failure_score"] < f_p95),
        ("excl worst 10%", oos_merged["failure_score"] < f_p90),
    ]:
        survivors = oos_merged[mask]
        # On survivors, top-10% winner
        w_thr = survivors["winner_score"].quantile(0.90)
        combo = survivors[survivors["winner_score"] >= w_thr]
        record(f"Combined: {label} + winner top-10%", combo)

    # Build report
    df_summary = pd.DataFrame(rows)
    df_summary.to_parquet(OUT / "ensemble_baseline_2025.parquet",
                            index=False)

    lines = ["# 2025 Ensemble Baseline (failure + winner v3)",
              "",
              "Standard entry timing: signal_time + 30s fill.",
              "Cost: $5 commission + 1-tick adverse entry + 1-tick "
              "exit slip on losses. Unresolved scored at -0.7 ATR.",
              "",
              "## Comparison matrix",
              "",
              "| Slice | n | Mean $ | Median | Trim 5% | PF | Win% "
              "| PT% | Reg% | L/S% | Total $ |",
              "|---|--:|--:|--:|--:|--:|--:|--:|--:|---|--:|"]
    for r in rows:
        lines.append(
            f"| {r['label']} | {int(r['n']):,} | "
            f"{fmt_d(r.get('mean'))} | {fmt_d(r.get('median'))} | "
            f"{fmt_d(r.get('trimmed_5pct'))} | "
            f"{r.get('pf', float('nan')):.2f} | "
            f"{fmt_p(r.get('win_rate'))} | "
            f"{fmt_p(r.get('pt_pct'))} | "
            f"{fmt_p(r.get('regime_pct'))} | "
            f"{100*r.get('long_pct',0):.0f}/"
            f"{100*r.get('short_pct',0):.0f} | "
            f"{fmt_d(r.get('sum'))} |")
    out_md = OUT / "ENSEMBLE_BASELINE_2025.md"
    out_md.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport: {out_md}")

    print("\n=== Quick scan ===")
    print(df_summary[["label", "n", "mean", "pf", "win_rate",
                       "pt_pct"]].to_string(
        index=False, float_format=lambda x: f"{x:.4f}"))


if __name__ == "__main__":
    main()
