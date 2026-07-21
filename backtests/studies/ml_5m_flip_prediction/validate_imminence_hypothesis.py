"""Validate the 'imminence vs entry-quality' hypothesis for the inverse
ML filter.

Hypothesis: the model predicts 'imminent 5m flip', and high-score rows are
those where the 5m flip is already nearly mechanically forced — meaning
price has extended, the move is late-stage, and a fresh 1ATR bracket
entered there has worse timing.

Three checks (adapted to T_d=0-only prediction setup):

  1. Score vs proximity to next 5m boundary
     5m closes at minute_of_hour % 5 == 4. At signal time, compute
     'minutes_until_next_5m_close' as a proxy for 'how baked-in is the
     5m flip already?'.

  2. Score vs extension features (direction-adjusted at T_d=0)
     - price_vs_sma20_30s_atr_T × direction  (price already pushed our way?)
     - price_vs_sma20_5m_atr_T × direction
     - ema_spread_30s_atr_T  (30s trend strength)
     - ema_spread_5m_atr_T  (5m trend strength)
     - regime_30s_duration_bars_T  (30s regime longevity)
     - regime_5m_duration_bars_T  (5m regime longevity)
     - micro_net_return_atr_T × direction  (last 12s in our favor?)
     - bar_range_30s_current_atr_T  (current 30s bar volatility)
     Plus root features:
     - flip_range_atr  (size of flip bar)
     - bar1_range_atr  (size of bar+1)
     - flip_close_location  (close position in flip bar range)

  3. Forward path / exit timing
     - forward_peak_mfe_atr_T_000  (post-fill peak MFE)
     - forward_peak_mae_atr_T_000  (post-fill peak MAE)
     - forward_regime_remaining_s_T_000  (time to regime exit)
     - bracket outcome distribution

Hypothesis is supported if high-score rows show:
  * lower minutes_until_next_5m_close (closer to 5m boundary)
  * larger extension (price already pushed in trade direction)
  * larger 30s/5m EMA spread / longer regime durations
  * smaller forward MFE, larger MAE, faster regime exit
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

DS_PATH = ("studies/ml_5m_flip_prediction/results/"
            "ml_5m_flip_prediction_dataset.parquet")
TRADES_PATH = ("studies/1m_delayed_checkpoint_context/results/"
               "trades_all.parquet")
OUT_LOG = Path("studies/ml_5m_flip_prediction/results/"
                "validate_imminence_hypothesis.log")
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


def train_and_predict_all_oos(ds, feat_cols):
    """Walk-forward predictions pooled across 2022-2025 OOS years."""
    configs = [
        (2022, [2020], 2021),
        (2023, [2020, 2021], 2022),
        (2024, [2020, 2021, 2022], 2023),
        (2025, [2020, 2021, 2022, 2023], 2024),
    ]
    all_preds = []
    for predict_year, train_years, val_year in configs:
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
        if len(pred_rows) > 0:
            pred_rows["pred"] = model.predict(pred_rows[feat_cols].values)
            all_preds.append(pred_rows)
    return pd.concat(all_preds, ignore_index=True) if all_preds else None


def main():
    print("Loading dataset + trades_all...")
    ds = pd.read_parquet(DS_PATH)
    trades = pd.read_parquet(TRADES_PATH)
    trades = trades.drop_duplicates(subset=["signal_ts"], keep="first")
    trades_idx = trades.set_index("signal_ts")
    print(f"  ML dataset rows: {len(ds):,}")

    feat_cols = [c for c in ds.columns
                 if c not in METADATA_COLS
                 and not c.startswith("target_")
                 and c != "is_rth"]

    print("\nGenerating walk-forward predictions for 2022-2025...")
    preds = train_and_predict_all_oos(ds, feat_cols)
    print(f"  Pooled OOS predictions: {len(preds):,}")

    # Pull collector forward fields for each row by event_id
    eids = preds["event_id"].values
    for col in ["forward_peak_mfe_atr_T_000",
                 "forward_peak_mae_atr_T_000",
                 "forward_regime_remaining_s_T_000",
                 "forward_regime_pnl_dollars_T_000",
                 "forward_pt100_before_sl100_T_000"]:
        preds[col] = trades_idx[col].reindex(eids).values

    # Compute derived features
    d = preds["signal_direction"].values
    # Direction-adjusted extension features
    preds["ext_price_vs_sma20_30s"] = (
        preds["price_vs_sma20_30s_atr_T"] * d)
    preds["ext_price_vs_sma20_5m"] = (
        preds["price_vs_sma20_5m_atr_T"] * d)
    preds["ext_micro_net_return"] = (
        preds["micro_net_return_atr_T"] * d)

    # Proximity to next 5m boundary at signal time
    # 5m bars close at minute_of_hour % 5 == 4 (so close happens at minutes
    # 4, 9, 14, ..., 59 of each hour)
    # Signal time = bar+1 close. minute_of_hour at signal IS the bar+1's
    # close minute. For minute m, distance to next 5m close in minutes:
    #   if m % 5 == 4: 0 (this is itself a 5m close)
    #   else: 4 - (m % 5) if m % 5 < 4 else 5
    # Actually m % 5 ∈ {0,1,2,3,4}. Distance to next 5m close (next minute
    # with m % 5 == 4):
    m = preds["minute_of_hour"].values
    mod = m % 5
    # If mod == 4, we're at a 5m close — distance = 0 (or 5 to NEXT next one)
    # For our purposes "this signal is at a 5m boundary" → distance = 0
    distance_to_next_5m_close = np.where(mod == 4, 0, 4 - mod)
    preds["minutes_until_next_5m_close"] = distance_to_next_5m_close
    # Also useful: is this signal AT a 5m boundary?
    preds["signal_at_5m_close"] = (mod == 4).astype(int)

    # Sort by predicted score, build deciles
    preds_sorted = preds.sort_values("pred", ascending=False).reset_index(
        drop=True)
    n = len(preds_sorted)
    decile_size = n // 10
    preds_sorted["decile"] = np.clip(
        preds_sorted.index.values // decile_size, 0, 9) + 1

    lines = []
    lines.append("=" * 130)
    lines.append(
        "VALIDATING 'IMMINENCE vs ENTRY QUALITY' HYPOTHESIS")
    lines.append(
        f"  Pooled OOS predictions (2022-2025 walk-forward): {n:,} rows")
    lines.append("=" * 130)

    # ----- CHECK 1 -----
    lines.append("\n--- CHECK 1: Score vs proximity to next 5m close ---")
    lines.append(
        "  Hypothesis support: HIGH-score rows should have SMALL "
        "minutes_until_next_5m_close")
    lines.append(
        f"  {'Decile':>7} {'N':>5} {'pred':>6} "
        f"{'mean_min_to_next_5m':>20} {'%_at_5m_close':>15}")
    lines.append("  " + "-" * 64)
    for dec in range(1, 11):
        sub = preds_sorted[preds_sorted["decile"] == dec]
        mean_pred = sub["pred"].mean()
        mean_min = sub["minutes_until_next_5m_close"].mean()
        pct_at_5m = sub["signal_at_5m_close"].mean() * 100
        lines.append(
            f"  D{dec:>2}     {len(sub):>5,} {mean_pred:>5.3f} "
            f"{mean_min:>19.2f} {pct_at_5m:>14.1f}%")

    # ----- CHECK 2 -----
    lines.append("\n--- CHECK 2: Score vs extension features (direction-adj) ---")
    lines.append(
        "  Hypothesis support: HIGH-score rows should have larger extension")
    lines.append(
        "  (price already pushed in trade direction, longer regime durations,")
    lines.append(
        "  larger EMA spreads, etc.)")

    feat_groups = [
        ("ext_price_vs_sma20_30s",
         "price vs 30s SMA (× dir)"),
        ("ext_price_vs_sma20_5m",
         "price vs 5m SMA (× dir)"),
        ("ema_spread_30s_atr_T",
         "30s EMA spread (ATR)"),
        ("ema_spread_5m_atr_T",
         "5m EMA spread (ATR)"),
        ("regime_30s_duration_bars_T",
         "30s regime duration (bars)"),
        ("regime_5m_duration_bars_T",
         "5m regime duration (bars)"),
        ("ext_micro_net_return",
         "micro 12s net return (× dir)"),
        ("bar_range_30s_current_atr_T",
         "current 30s bar range (ATR)"),
        ("flip_range_atr", "flip bar range (ATR)"),
        ("bar1_range_atr", "bar+1 range (ATR)"),
        ("flip_close_location",
         "flip close location (0=low,1=high)"),
        ("atr_14_at_T", "ATR(14) at decision (pts)"),
    ]
    for col, label in feat_groups:
        lines.append(f"\n  {label}:")
        lines.append(
            f"    {'Decile':>7} {'N':>5}  {'mean':>10}  {'median':>10}")
        for dec in range(1, 11):
            sub = preds_sorted[preds_sorted["decile"] == dec]
            mean = sub[col].mean()
            med = sub[col].median()
            lines.append(
                f"    D{dec:>2}     {len(sub):>5,}  "
                f"{mean:>+10.3f}  {med:>+10.3f}")
        # Spearman-style spread
        d1 = preds_sorted[preds_sorted["decile"] == 1][col].mean()
        d10 = preds_sorted[preds_sorted["decile"] == 10][col].mean()
        lines.append(f"    D1−D10 spread: {d1 - d10:+.3f}")

    # ----- CHECK 3 -----
    lines.append("\n--- CHECK 3: Score vs forward path (retrace sensitivity) ---")
    lines.append(
        "  Hypothesis support: HIGH-score rows should have less forward MFE,")
    lines.append("  similar/larger MAE, and faster regime exit.")
    lines.append(
        f"\n  {'Decile':>7} {'N':>5}  {'med_MFE':>8} {'med_MAE':>8} "
        f"{'med_ratio':>10}  {'med_time_to_exit_s':>19}  {'pt%':>5} "
        f"{'sl%':>5} {'reg%':>5}")
    lines.append("  " + "-" * 100)
    for dec in range(1, 11):
        sub = preds_sorted[preds_sorted["decile"] == dec]
        mfe = sub["forward_peak_mfe_atr_T_000"]
        mae = sub["forward_peak_mae_atr_T_000"]
        ratio = mfe / mae.replace(0, np.nan)
        rem = sub["forward_regime_remaining_s_T_000"]
        bracket = sub["forward_pt100_before_sl100_T_000"]
        pt_pct = (bracket == 1).sum() / len(sub) * 100
        sl_pct = (bracket == 0).sum() / len(sub) * 100
        nth_pct = bracket.isna().sum() / len(sub) * 100
        lines.append(
            f"  D{dec:>2}     {len(sub):>5,}  "
            f"{mfe.median():>7.2f}  {mae.median():>7.2f}  "
            f"{ratio.median():>9.2f}   {rem.median():>17.0f}s  "
            f"{pt_pct:>4.1f}% {sl_pct:>4.1f}% {nth_pct:>4.1f}%"
        )

    # ----- SUMMARY -----
    lines.append("\n--- HYPOTHESIS SUPPORT SUMMARY ---")

    d1 = preds_sorted[preds_sorted["decile"] == 1]
    d10 = preds_sorted[preds_sorted["decile"] == 10]

    summary_rows = []

    def cmp(label, d1_val, d10_val, supports_high_means):
        """supports_high_means: True if D1 > D10 supports hypothesis."""
        if supports_high_means:
            ok = d1_val > d10_val
        else:
            ok = d1_val < d10_val
        return (label, d1_val, d10_val, "✓" if ok else "✗")

    summary_rows.append(cmp(
        "minutes_until_next_5m_close",
        d1["minutes_until_next_5m_close"].mean(),
        d10["minutes_until_next_5m_close"].mean(),
        False))
    summary_rows.append(cmp(
        "ext_price_vs_sma20_30s (direction-adj)",
        d1["ext_price_vs_sma20_30s"].mean(),
        d10["ext_price_vs_sma20_30s"].mean(),
        True))
    summary_rows.append(cmp(
        "ext_price_vs_sma20_5m (direction-adj)",
        d1["ext_price_vs_sma20_5m"].mean(),
        d10["ext_price_vs_sma20_5m"].mean(),
        True))
    summary_rows.append(cmp(
        "ema_spread_30s_atr_T",
        d1["ema_spread_30s_atr_T"].mean(),
        d10["ema_spread_30s_atr_T"].mean(),
        True))
    summary_rows.append(cmp(
        "ema_spread_5m_atr_T",
        d1["ema_spread_5m_atr_T"].mean(),
        d10["ema_spread_5m_atr_T"].mean(),
        True))
    summary_rows.append(cmp(
        "regime_30s_duration_bars_T",
        d1["regime_30s_duration_bars_T"].mean(),
        d10["regime_30s_duration_bars_T"].mean(),
        True))
    summary_rows.append(cmp(
        "regime_5m_duration_bars_T",
        d1["regime_5m_duration_bars_T"].mean(),
        d10["regime_5m_duration_bars_T"].mean(),
        True))
    summary_rows.append(cmp(
        "ext_micro_net_return (direction-adj)",
        d1["ext_micro_net_return"].mean(),
        d10["ext_micro_net_return"].mean(),
        True))
    summary_rows.append(cmp(
        "atr_14_at_T (volatility)",
        d1["atr_14_at_T"].mean(),
        d10["atr_14_at_T"].mean(),
        True))
    summary_rows.append(cmp(
        "median forward MFE",
        d1["forward_peak_mfe_atr_T_000"].median(),
        d10["forward_peak_mfe_atr_T_000"].median(),
        False))
    summary_rows.append(cmp(
        "median forward MAE",
        d1["forward_peak_mae_atr_T_000"].median(),
        d10["forward_peak_mae_atr_T_000"].median(),
        True))
    summary_rows.append(cmp(
        "median time-to-regime-exit",
        d1["forward_regime_remaining_s_T_000"].median(),
        d10["forward_regime_remaining_s_T_000"].median(),
        False))

    lines.append(
        f"  {'metric':<42} {'D1 (high pred)':>15} {'D10 (low pred)':>15}  "
        f"{'support?':>8}")
    lines.append("  " + "-" * 90)
    n_support = 0
    for label, d1_val, d10_val, sup in summary_rows:
        lines.append(
            f"  {label:<42} {d1_val:>15.3f} {d10_val:>15.3f}  "
            f"{sup:>8}")
        if sup == "✓":
            n_support += 1
    lines.append("")
    lines.append(
        f"  Supporting metrics: {n_support}/{len(summary_rows)}")
    if n_support >= len(summary_rows) * 0.7:
        lines.append(
            "  → STRONG SUPPORT for the imminence hypothesis")
    elif n_support >= len(summary_rows) * 0.5:
        lines.append(
            "  → MODERATE SUPPORT for the imminence hypothesis")
    else:
        lines.append(
            "  → WEAK SUPPORT — hypothesis not clearly confirmed")

    out = "\n".join(lines)
    print(out)
    OUT_LOG.write_text(out, encoding="utf-8")
    print(f"\n  Saved: {OUT_LOG}")


if __name__ == "__main__":
    main()
