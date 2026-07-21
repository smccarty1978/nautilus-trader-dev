"""Walk-forward cross-year validation of the ML inverse filter.

Procedure (per OOS year Y in {2022, 2023, 2024, 2025}):
  1. Train on RTH valid-label rows from years < Y, last prior year as VAL.
  2. Predict on year Y's T_d=0 RTH non-aligned + fillable population.
  3. Compute simulated bracket PnL (PT=1.0/SL=1.0) using collector forward
     fields + per-trade ATR. Reconciliation showed sim ≈ NT within $0.7.
  4. Bin by predicted score, report:
     - baseline (no filter)
     - drop top 30%
     - keep bottom 50%
     - keep bottom 25%

For 2025 also cross-check using actual NT trade outcomes (we have them).

Goal: see whether the inverse-filter edge from 2025 holds across years.
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
TRADES_PATH = ("studies/1m_delayed_checkpoint_context/results/"
               "trades_all.parquet")
NT_PATH = ("backtests/results/flip_5m_nonaligned_bracket/"
           "trades_2025.parquet")
OUT_LOG = Path("studies/ml_5m_flip_prediction/results/"
                "walk_forward_filter_validation.log")
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

NQ_MULT = 20.0
COMMISSION = 5.0


def fmt_pf(pf):
    if pf == float("inf"):
        return " inf"
    if pd.isna(pf):
        return " n/a"
    return f"{pf:>4.2f}"


def stats(pnl: pd.Series) -> dict:
    n = len(pnl)
    if n == 0:
        return {"n": 0, "wr%": np.nan, "avg$": np.nan,
                "total$": np.nan, "pf": np.nan}
    wr = (pnl > 0).mean() * 100
    avg = pnl.mean()
    total = pnl.sum()
    gp = pnl[pnl > 0].sum()
    gl = abs(pnl[pnl <= 0].sum())
    pf = gp / gl if gl > 0 else float("inf")
    return {"n": n, "wr%": wr, "avg$": avg, "total$": total, "pf": pf}


def fmt_filter_row(label, s):
    return (
        f"  {label:<22} N={s['n']:>5,}  WR={s['wr%']:>5.1f}%  "
        f"Avg=${s['avg$']:>+7.1f}  PF={fmt_pf(s['pf'])}  "
        f"Total=${s['total$']:>+9,.0f}"
    )


def sim_bracket_pnl(rows: pd.DataFrame, trades_idx: pd.DataFrame,
                     pt_r=1.0, sl_r=1.0,
                     bracket_col="forward_pt100_before_sl100_T_000",
                     reg_col="forward_regime_pnl_dollars_T_000") -> pd.Series:
    """Compute per-row simulated $ PnL via collector bracket race."""
    eids = rows["event_id"].values
    atr = trades_idx["atr_at_signal"].reindex(eids).values
    bracket = trades_idx[bracket_col].reindex(eids).values
    reg_pnl = trades_idx[reg_col].reindex(eids).values
    n = len(rows)
    pnl = np.full(n, np.nan)
    pt_first = bracket == 1
    sl_first = bracket == 0
    neither = pd.isna(bracket)
    pnl[pt_first] = (pt_r * atr[pt_first] * NQ_MULT) - COMMISSION
    pnl[sl_first] = (-sl_r * atr[sl_first] * NQ_MULT) - COMMISSION
    pnl[neither] = reg_pnl[neither]
    return pd.Series(pnl, index=rows.index)


def filter_table(rows_sorted: pd.DataFrame, pnl: pd.Series,
                  lines: list, label_prefix: str = ""):
    """Print baseline + the four filter outcomes per spec."""
    n = len(rows_sorted)
    base = stats(pnl)
    lines.append(fmt_filter_row(f"{label_prefix}NO FILTER", base))
    # drop top 30%: keep bottom 70%
    keep = pnl.iloc[3 * n // 10:]
    lines.append(fmt_filter_row(f"{label_prefix}drop top 30%",
                                 stats(keep)))
    # keep bottom 50%
    keep = pnl.iloc[n // 2:]
    lines.append(fmt_filter_row(f"{label_prefix}keep bottom 50%",
                                 stats(keep)))
    # keep bottom 25%
    keep = pnl.iloc[3 * n // 4:]
    lines.append(fmt_filter_row(f"{label_prefix}keep bottom 25%",
                                 stats(keep)))


def train_predict(ds: pd.DataFrame, train_years, val_year, predict_year,
                   feat_cols):
    """Train on train_years (with valid label, RTH), validate on val_year,
    predict on predict_year T_d=0 RTH non-aligned (no label filter)."""
    train_mask = (
        ds["year"].isin(train_years)
        & (ds["is_rth"] == 1)
        & ds[TARGET].notna()
    )
    val_mask = (
        (ds["year"] == val_year)
        & (ds["is_rth"] == 1)
        & ds[TARGET].notna()
    )
    pred_mask = (
        (ds["year"] == predict_year)
        & (ds["is_rth"] == 1)
        & (ds["decision_checkpoint_s"] == 0)
    )

    X_tr = ds.loc[train_mask, feat_cols].values
    y_tr = ds.loc[train_mask, TARGET].astype(int).values
    X_vl = ds.loc[val_mask, feat_cols].values
    y_vl = ds.loc[val_mask, TARGET].astype(int).values

    train_ds = lgb.Dataset(X_tr, label=y_tr, feature_name=feat_cols)
    val_ds = lgb.Dataset(X_vl, label=y_vl, reference=train_ds,
                          feature_name=feat_cols)
    model = lgb.train(
        LGB_PARAMS, train_ds, num_boost_round=2000,
        valid_sets=[train_ds, val_ds], valid_names=["train", "val"],
        callbacks=[lgb.early_stopping(50), lgb.log_evaluation(0)],
    )

    pred_rows = ds[pred_mask].copy()
    if len(pred_rows) == 0:
        return None, model, train_mask.sum(), val_mask.sum()

    X_pr = pred_rows[feat_cols].values
    pred_rows["pred"] = model.predict(X_pr)
    return pred_rows, model, train_mask.sum(), val_mask.sum()


def main():
    print("Loading dataset + trades_all...")
    ds = pd.read_parquet(DS_PATH)
    trades = pd.read_parquet(TRADES_PATH)
    trades = trades.drop_duplicates(subset=["signal_ts"], keep="first")
    trades_idx = trades.set_index("signal_ts")
    nt = pd.read_parquet(NT_PATH)
    cutoff = pd.Timestamp("2025-01-01", tz="UTC").value
    nt_2025 = nt[nt["signal_time"] >= cutoff].copy()
    print(f"  ML dataset rows: {len(ds):,}")
    print(f"  Trades index:    {len(trades_idx):,}")
    print(f"  NT 2025 trades:  {len(nt_2025):,}")

    feat_cols = [c for c in ds.columns
                 if c not in METADATA_COLS
                 and not c.startswith("target_")
                 and c != "is_rth"]

    # Walk-forward year configs:
    # (predict_year, train_years (excluding val), val_year)
    # Need at least 2 prior years for meaningful train.
    configs = [
        (2022, [2020], 2021),
        (2023, [2020, 2021], 2022),
        (2024, [2020, 2021, 2022], 2023),
        (2025, [2020, 2021, 2022, 2023], 2024),
    ]

    all_lines = []
    all_lines.append("=" * 110)
    all_lines.append(
        "WALK-FORWARD INVERSE-FILTER VALIDATION (collector bracket sim)")
    all_lines.append("=" * 110)
    all_lines.append("")
    all_lines.append(
        "  PnL is collector bracket race PT=1.0/SL=1.0 with per-trade ATR")
    all_lines.append(
        "  (matches NT within $0.7/trade per reconciliation).")
    all_lines.append(
        "  Population per year: T_d=0 + RTH + 5m_not_aligned + fillable_T_000")

    summary_rows = []  # for final cross-year table

    for predict_year, train_years, val_year in configs:
        print(f"\n  Year {predict_year}: train on {train_years} + "
              f"val {val_year}...")
        pred_rows, model, n_tr, n_vl = train_predict(
            ds, train_years, val_year, predict_year, feat_cols)
        if pred_rows is None:
            print(f"    no predict population")
            continue

        # Compute AUC on year's valid-label subset
        valid = pred_rows[TARGET].notna()
        if valid.sum() > 20:
            auc = roc_auc_score(
                pred_rows.loc[valid, TARGET].astype(int),
                pred_rows.loc[valid, "pred"])
        else:
            auc = np.nan

        # Compute simulated bracket PnL for ALL pred rows
        pnl_sim = sim_bracket_pnl(pred_rows, trades_idx)

        # Sort by pred descending, align PnL accordingly
        order = pred_rows.sort_values("pred", ascending=False).index
        pred_sorted = pred_rows.loc[order]
        pnl_sorted = pnl_sim.loc[order]

        all_lines.append("")
        all_lines.append("=" * 110)
        all_lines.append(
            f"YEAR {predict_year}  (train {train_years} val {val_year})  "
            f"train_n={n_tr:,}  val_n={n_vl:,}  best_iter={model.best_iteration}")
        all_lines.append(
            f"  AUC on year-valid-label rows: "
            f"{auc:.4f}" if not pd.isna(auc) else "  AUC: N/A")
        all_lines.append(
            f"  Predict population (T_d=0 RTH non-aligned + fillable): "
            f"{len(pred_rows):,}")
        all_lines.append("")
        filter_table(pred_sorted, pnl_sorted, all_lines)

        # Capture for summary
        n = len(pred_sorted)
        s_base = stats(pnl_sorted)
        s_drop30 = stats(pnl_sorted.iloc[3 * n // 10:])
        s_b50 = stats(pnl_sorted.iloc[n // 2:])
        s_b25 = stats(pnl_sorted.iloc[3 * n // 4:])
        summary_rows.append({
            "year": predict_year,
            "auc": auc,
            "n_total": n,
            "base_avg": s_base["avg$"],
            "base_pf": s_base["pf"],
            "drop30_n": s_drop30["n"],
            "drop30_avg": s_drop30["avg$"],
            "drop30_pf": s_drop30["pf"],
            "drop30_total": s_drop30["total$"],
            "b50_n": s_b50["n"],
            "b50_avg": s_b50["avg$"],
            "b50_pf": s_b50["pf"],
            "b50_total": s_b50["total$"],
            "b25_n": s_b25["n"],
            "b25_avg": s_b25["avg$"],
            "b25_pf": s_b25["pf"],
            "b25_total": s_b25["total$"],
        })

        # For 2025 also cross-check on actual NT outcomes
        if predict_year == 2025:
            all_lines.append("")
            all_lines.append("  2025 cross-check on ACTUAL NT outcomes:")
            pred_lookup = pred_rows.set_index("event_id")["pred"]
            nt_2025_pred = nt_2025.copy()
            nt_2025_pred["pred"] = nt_2025_pred[
                "signal_time"].map(pred_lookup)
            matched_nt = nt_2025_pred[nt_2025_pred["pred"].notna()].copy()
            matched_nt = matched_nt.sort_values("pred", ascending=False)
            pnl_nt = matched_nt["pnl_dollars"]
            filter_table(matched_nt, pnl_nt, all_lines, label_prefix="NT ")

    # Cross-year summary table
    all_lines.append("")
    all_lines.append("=" * 110)
    all_lines.append("CROSS-YEAR SUMMARY (collector bracket sim PnL)")
    all_lines.append("=" * 110)
    all_lines.append(
        f"  {'Year':>4} {'AUC':>5} {'N_total':>8}  "
        f"{'Baseline$':>10} {'BaselinePF':>10}  "
        f"{'Drop30 N':>8} {'Drop30$':>9} {'Drop30PF':>9}  "
        f"{'B50 N':>6} {'B50$':>9} {'B50PF':>7}  "
        f"{'B25 N':>6} {'B25$':>9} {'B25PF':>7}")
    all_lines.append("  " + "-" * 130)
    for r in summary_rows:
        all_lines.append(
            f"  {r['year']:>4} "
            f"{r['auc']:>5.3f} {r['n_total']:>8,}  "
            f"${r['base_avg']:>+8.1f} {fmt_pf(r['base_pf']):>10}  "
            f"{r['drop30_n']:>8,} ${r['drop30_avg']:>+7.1f} "
            f"{fmt_pf(r['drop30_pf']):>9}  "
            f"{r['b50_n']:>6,} ${r['b50_avg']:>+7.1f} "
            f"{fmt_pf(r['b50_pf']):>7}  "
            f"{r['b25_n']:>6,} ${r['b25_avg']:>+7.1f} "
            f"{fmt_pf(r['b25_pf']):>7}"
        )

    # Total $ summary
    all_lines.append("")
    all_lines.append("--- 4-year totals (sim PnL) ---")
    base_t = sum(r["base_avg"] * r["n_total"] for r in summary_rows)
    drop30_t = sum(r["drop30_total"] for r in summary_rows)
    b50_t = sum(r["b50_total"] for r in summary_rows)
    b25_t = sum(r["b25_total"] for r in summary_rows)
    all_lines.append(f"  No filter:        ${base_t:>+12,.0f}")
    all_lines.append(f"  Drop top 30%:     ${drop30_t:>+12,.0f}")
    all_lines.append(f"  Keep bottom 50%:  ${b50_t:>+12,.0f}")
    all_lines.append(f"  Keep bottom 25%:  ${b25_t:>+12,.0f}")

    # Verdict
    all_lines.append("")
    all_lines.append("--- VERDICT ---")
    drop30_avgs = [r["drop30_avg"] for r in summary_rows]
    b50_avgs = [r["b50_avg"] for r in summary_rows]
    base_avgs = [r["base_avg"] for r in summary_rows]
    drop30_neg_years = sum(1 for x in drop30_avgs if x < 0)
    b50_neg_years = sum(1 for x in b50_avgs if x < 0)
    all_lines.append(f"  Drop top 30% — avg per year: "
                      f"${np.mean(drop30_avgs):+.1f}  "
                      f"negative years: {drop30_neg_years}/{len(summary_rows)}")
    all_lines.append(f"  Keep bottom 50% — avg per year: "
                      f"${np.mean(b50_avgs):+.1f}  "
                      f"negative years: {b50_neg_years}/{len(summary_rows)}")
    all_lines.append(f"  Baseline — avg per year: "
                      f"${np.mean(base_avgs):+.1f}")

    # Save
    out = "\n".join(all_lines)
    print(out)
    OUT_LOG.write_text(out, encoding="utf-8")
    print(f"\n  Saved: {OUT_LOG}")


if __name__ == "__main__":
    main()
