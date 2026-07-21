"""Quick test — does the ML model help as a real-time trade filter on
actual NT outcomes (after removing the survivor bias)?

Procedure:
  1. Re-train baseline LightGBM on TRAIN years (2020-2023), RTH-only,
     target = target_5m_flip_within_300s (drop censored rows for training,
     which is correct — model learns from observable labels).
  2. Predict on EVERY T_d=0 RTH non-aligned 2025 row (no label filter
     here — we want a score for every NT trade).
  3. Join predictions to NT 2025 trades by event_id = signal_ts.
  4. Bin NT PnL by predicted score (deciles, quintiles, halves).
  5. Report per-bin: n, WR, avg$, PF, total$.

If any bin shows materially better economics than the baseline (~+$4/trade),
ML has filter value. If not, the model learned something about the label
but not about tradeable outcomes.
"""

import sys
import os
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd
import numpy as np
import lightgbm as lgb
from sklearn.metrics import roc_auc_score

DS_PATH = ("studies/ml_5m_flip_prediction/results/"
            "ml_5m_flip_prediction_dataset.parquet")
NT_PATH = ("backtests/results/flip_5m_nonaligned_bracket/"
           "trades_2025.parquet")
OUT_LOG = Path("studies/ml_5m_flip_prediction/results/"
                "ml_filter_on_nt.log")
TARGET = "target_5m_flip_within_300s"

METADATA_COLS = {
    "trade_id", "signal_time", "signal_ts", "year", "date", "session",
    "event_id", "decision_ts", "decision_fill_ts",
}

LGB_PARAMS = {
    "objective": "binary",
    "metric": "auc",
    "learning_rate": 0.05,
    "num_leaves": 63,
    "min_data_in_leaf": 100,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 5,
    "lambda_l1": 0.1,
    "lambda_l2": 0.1,
    "verbose": -1,
}


def fmt_pf(pf):
    if pf == float("inf"):
        return " inf"
    if pd.isna(pf):
        return " n/a"
    return f"{pf:>4.2f}"


def stats(pnl: pd.Series) -> dict:
    n = len(pnl)
    if n == 0:
        return {"n": 0}
    wr = (pnl > 0).mean() * 100
    avg = pnl.mean()
    total = pnl.sum()
    gp = pnl[pnl > 0].sum()
    gl = abs(pnl[pnl <= 0].sum())
    pf = gp / gl if gl > 0 else float("inf")
    return {"n": n, "wr%": wr, "avg$": avg, "total$": total, "pf": pf}


def fmt_row(label, s):
    if s["n"] == 0:
        return f"  {label:<22} (n=0)"
    return (
        f"  {label:<22} N={s['n']:>5,} "
        f"WR={s['wr%']:>5.1f}% Avg=${s['avg$']:>+7.1f} "
        f"PF={fmt_pf(s['pf'])} Total=${s['total$']:>+8,.0f}"
    )


def main():
    print("Loading dataset + NT trades...")
    ds = pd.read_parquet(DS_PATH)
    nt = pd.read_parquet(NT_PATH)
    cutoff = pd.Timestamp("2025-01-01", tz="UTC").value
    nt_2025 = nt[nt["signal_time"] >= cutoff].copy()
    print(f"  ML dataset rows: {len(ds):,}")
    print(f"  NT 2025 trades:  {len(nt_2025):,}")

    feat_cols = [c for c in ds.columns
                 if c not in METADATA_COLS
                 and not c.startswith("target_")
                 and c != "is_rth"]

    # Train on TRAIN years RTH only (same setup as baseline_model.py)
    train_mask = (
        ds["year"].isin([2020, 2021, 2022, 2023])
        & (ds["is_rth"] == 1)
        & ds[TARGET].notna()
    )
    val_mask = (
        (ds["year"] == 2024)
        & (ds["is_rth"] == 1)
        & ds[TARGET].notna()
    )
    print(f"  Train rows: {train_mask.sum():,}")
    print(f"  Val rows:   {val_mask.sum():,}")

    X_train = ds.loc[train_mask, feat_cols].values
    y_train = ds.loc[train_mask, TARGET].astype(int).values
    X_val = ds.loc[val_mask, feat_cols].values
    y_val = ds.loc[val_mask, TARGET].astype(int).values

    print("\nTraining LightGBM...")
    train_ds = lgb.Dataset(X_train, label=y_train, feature_name=feat_cols)
    val_ds = lgb.Dataset(
        X_val, label=y_val, reference=train_ds,
        feature_name=feat_cols)
    model = lgb.train(
        LGB_PARAMS, train_ds, num_boost_round=2000,
        valid_sets=[train_ds, val_ds], valid_names=["train", "val"],
        callbacks=[lgb.early_stopping(50), lgb.log_evaluation(0)],
    )
    print(f"  Best iter: {model.best_iteration}")

    # Predict on EVERY 2025 T_d=0 RTH non-aligned row (no label filter)
    pred_mask = (
        (ds["year"] == 2025)
        & (ds["is_rth"] == 1)
        & (ds["decision_checkpoint_s"] == 0)
    )
    pred_rows = ds[pred_mask].copy()
    print(f"\n  Prediction population (T_d=0 RTH 2025): "
          f"{len(pred_rows):,}")

    X_pred = pred_rows[feat_cols].values
    pred_rows["pred"] = model.predict(X_pred)

    # Among prediction rows that have valid 300s label, what's the AUC?
    valid = pred_rows[TARGET].notna()
    if valid.sum() > 0:
        auc_2025 = roc_auc_score(
            pred_rows.loc[valid, TARGET].astype(int),
            pred_rows.loc[valid, "pred"])
    else:
        auc_2025 = np.nan

    # Join with NT trades by event_id = signal_time
    pred_lookup = pred_rows.set_index("event_id")["pred"]
    nt_2025["pred"] = nt_2025["signal_time"].map(pred_lookup)
    n_matched = nt_2025["pred"].notna().sum()
    n_unmatched = nt_2025["pred"].isna().sum()
    print(f"  NT trades matched with prediction: "
          f"{n_matched:,} ({n_matched/len(nt_2025)*100:.1f}%)")
    print(f"  NT trades NOT matched (no T_d=0 row in dataset): "
          f"{n_unmatched:,}")

    matched = nt_2025[nt_2025["pred"].notna()].copy()
    matched_sorted = matched.sort_values("pred", ascending=False)

    # Build the log
    lines = []
    lines.append("=" * 110)
    lines.append("ML AS REAL-TIME FILTER ON NT OUTCOMES (2025)")
    lines.append("=" * 110)
    lines.append("")
    lines.append(
        f"  Train rows (RTH 2020-2023, valid label): {train_mask.sum():,}")
    lines.append(
        f"  Val rows (RTH 2024, valid label):        {val_mask.sum():,}")
    lines.append(
        f"  Best LightGBM iter:                      "
        f"{model.best_iteration}")
    lines.append(
        f"  AUC on RTH 2025 valid-label rows:        "
        f"{auc_2025:.4f}" if not pd.isna(auc_2025) else "N/A")
    lines.append("")
    lines.append(
        f"  Prediction population (T_d=0 RTH 2025): {len(pred_rows):,}")
    lines.append(
        f"  NT trades matched with prediction:      {n_matched:,}")

    n = len(matched_sorted)
    base = stats(matched_sorted["pnl_dollars"])
    lines.append(f"\n--- Baseline (no filter, all matched NT trades) ---")
    lines.append(fmt_row("ALL", base))

    # Decile bins (D1=highest pred, D10=lowest)
    lines.append(f"\n--- Decile bins (D1=highest predicted prob, D10=lowest) ---")
    deciles = np.array_split(matched_sorted, 10)
    for i, d in enumerate(deciles, 1):
        s = stats(d["pnl_dollars"])
        # Show pred range
        if len(d) > 0:
            lines.append(
                fmt_row(
                    f"D{i:>2} pred={d['pred'].min():.3f}-"
                    f"{d['pred'].max():.3f}",
                    s))

    # Quintiles
    lines.append(f"\n--- Quintile bins ---")
    quintiles = np.array_split(matched_sorted, 5)
    for i, q in enumerate(quintiles, 1):
        s = stats(q["pnl_dollars"])
        if len(q) > 0:
            lines.append(
                fmt_row(
                    f"Q{i:>2} pred={q['pred'].min():.3f}-"
                    f"{q['pred'].max():.3f}",
                    s))

    # Halves
    lines.append(f"\n--- Halves ---")
    n2 = n // 2
    s_top = stats(matched_sorted.iloc[:n2]["pnl_dollars"])
    s_bot = stats(matched_sorted.iloc[n2:]["pnl_dollars"])
    lines.append(fmt_row("TOP HALF (high pred)", s_top))
    lines.append(fmt_row("BOTTOM HALF (low)", s_bot))

    # Threshold-based filters: drop top-X%, drop bottom-X%
    lines.append(
        "\n--- Filter strategies (which subset to KEEP for trading) ---")
    for label, subset in [
        ("Drop top 10%", matched_sorted.iloc[n // 10:]),
        ("Drop top 20%", matched_sorted.iloc[n // 5:]),
        ("Drop top 30%", matched_sorted.iloc[3 * n // 10:]),
        ("Drop bottom 10%", matched_sorted.iloc[:-n // 10]),
        ("Drop bottom 20%", matched_sorted.iloc[:-n // 5]),
        ("Keep bottom 10% only",
         matched_sorted.iloc[-n // 10:]),
        ("Keep bottom 25% only",
         matched_sorted.iloc[-n // 4:]),
        ("Keep bottom 50% only",
         matched_sorted.iloc[-n // 2:]),
        ("Keep middle 50%",
         matched_sorted.iloc[n // 4:3 * n // 4]),
    ]:
        s = stats(subset["pnl_dollars"])
        lines.append(fmt_row(label, s))

    # By exit reason within top/bottom decile
    lines.append("\n--- Top decile vs bottom decile: exit reason mix ---")
    top10 = matched_sorted.iloc[:n // 10]
    bot10 = matched_sorted.iloc[-n // 10:]
    for lbl, grp in [("TOP DECILE (high pred)", top10),
                      ("BOTTOM DECILE (low pred)", bot10)]:
        lines.append(f"  {lbl}:")
        rmix = grp["exit_reason"].value_counts(normalize=True) * 100
        for r in ["pt", "sl", "regime_flip", "sl_same_bar_both"]:
            pct = rmix.get(r, 0)
            n_r = (grp["exit_reason"] == r).sum()
            avg_r = (grp[grp["exit_reason"] == r]["pnl_dollars"].mean()
                      if n_r > 0 else 0)
            lines.append(
                f"    {r:<20}: N={n_r:>4,} ({pct:>5.1f}%) "
                f"avg=${avg_r:+.1f}")

    # Final summary verdict
    lines.append("\n--- VERDICT ---")
    base_avg = base["avg$"]
    best_label = None
    best_avg = base_avg
    candidates = [
        ("Drop top 10%", matched_sorted.iloc[n // 10:]),
        ("Drop top 20%", matched_sorted.iloc[n // 5:]),
        ("Drop top 30%", matched_sorted.iloc[3 * n // 10:]),
        ("Keep bottom 10% only", matched_sorted.iloc[-n // 10:]),
        ("Keep bottom 25% only", matched_sorted.iloc[-n // 4:]),
        ("Keep bottom 50% only", matched_sorted.iloc[-n // 2:]),
    ]
    for lbl, sub in candidates:
        s = stats(sub["pnl_dollars"])
        if s["avg$"] > best_avg:
            best_avg = s["avg$"]
            best_label = lbl
    lines.append(
        f"  Baseline (no filter):  Avg=${base_avg:+.1f}/trade, "
        f"N={base['n']:,}")
    if best_label:
        lines.append(
            f"  Best filter found:     '{best_label}'  "
            f"Avg=${best_avg:+.1f}/trade  "
            f"(lift: ${best_avg - base_avg:+.1f}/trade)")
        # Significance check — is this lift big enough to matter?
        # Round-trip slippage ≈ $10. We need >$10 lift to convert
        # baseline ~$4 into something tradeable.
        if best_avg - base_avg >= 10:
            lines.append(
                "  → MEANINGFUL filter (lift > $10/trade slippage threshold)")
        elif best_avg - base_avg >= 5:
            lines.append(
                "  → MODEST filter — possibly real but small. "
                "Validate carefully before deploying.")
        else:
            lines.append(
                "  → MARGINAL — within sampling noise. "
                "ML did not provide a useful filter for this rule.")
    else:
        lines.append("  No filter improved over baseline.")

    out = "\n".join(lines)
    print(out)
    OUT_LOG.write_text(out, encoding="utf-8")
    print(f"\n  Saved: {OUT_LOG}")


if __name__ == "__main__":
    main()
