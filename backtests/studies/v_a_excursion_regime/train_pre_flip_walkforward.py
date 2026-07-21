"""Phase 2: walk-forward training + trading sim for pre-flip prediction.

Three independent binary models — one per horizon (T-1, T-2, T-3) —
trained monthly via expanding-window walk-forward starting Apr 2024.

For each horizon model, per scoring month:
  - Train: all prior-month candidates
  - Eval: candidates in scoring month
  - Aggregate OOS predictions across all months

Reports per horizon:
  - Mean fold AUC, overall OOS AUC
  - Precision/recall at top 1%, 2%, 5%, 10% of predictions
  - Lift vs random selection
  - Top-15 feature importance (final fold)
  - Importance stability: how often each feature appears in top-15 across folds

Trading simulation (only on horizons that show OOS AUC > 0.55):
  - For each "fired" candidate (top quantile by p_score):
    - Entry at next 1s bar open after candidate.close_ts in direction d
    - If V_A confirms flip at horizon (matching direction): exit at V_A's
      regime-flip outcome (use trades.parquet net_pnl)
    - Else (no flip): TWO exit variants reported side-by-side
       (a) Bar-close at t+X (the predicted-flip bar)
       (b) Time-stop at +5 min from entry
"""
from __future__ import annotations
import os, sys, time
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import lightgbm as lgb
from sklearn.metrics import roc_auc_score


OUT = Path("studies/v_a_excursion_regime/results_v0")
NQ_MULT = 20.0
COMMISSION_ONE_WAY = 5.0
SEED = 42
VAL_FRAC = 0.20
FIRST_SCORED_MONTH = "2024-04"
LAST_SCORED_MONTH = "2026-04"

# Trading sim parameters
TIME_STOP_S = 300              # 5min time-stop alternative


def load_candidates():
    df = pd.read_parquet(OUT / "pre_flip_candidates.parquet")
    df["close_dt"] = pd.to_datetime(df["close_ts_ns"], unit="ns", utc=True)
    df["year_month"] = (df["close_dt"].dt.tz_convert("America/Chicago")
                          ).dt.to_period("M")
    return df


def feature_columns(df: pd.DataFrame) -> list[str]:
    """All columns that are valid model features (drop raw prices,
    timestamps, identifiers, year, labels)."""
    drop = set([
        # Identifiers / timestamps
        "ts_event_ns", "close_ts_ns", "close_dt", "year_month", "year",
        # Raw prices (year-proxy risk, per prior auditor)
        "open_1m", "high_1m", "low_1m", "close_1m",
        "ema3_h_1m", "ema9_h_1m", "ema3_l_1m", "ema9_l_1m",
        "close_5s", "close_15s", "close_30s",
        # Raw flip threshold (already direction-aware below)
        # Labels
        "label_T1", "label_T2", "label_T3",
    ])
    feats = [c for c in df.columns if c not in drop]
    # Drop any object/datetime cols
    feats = [c for c in feats
                if df[c].dtype not in ("object", "datetime64[ns, UTC]")]
    return feats


def fit_horizon_model(X_tr, y_tr, X_val, y_val):
    model = lgb.LGBMClassifier(
        n_estimators=500, max_depth=6, num_leaves=31,
        learning_rate=0.05, feature_fraction=0.8,
        bagging_fraction=0.8, bagging_freq=5,
        min_data_in_leaf=50, random_state=SEED, n_jobs=-1,
        is_unbalance=True, verbose=-1)
    model.fit(X_tr, y_tr, eval_set=[(X_val, y_val)],
              callbacks=[lgb.early_stopping(50, verbose=False),
                          lgb.log_evaluation(0)])
    return model


def walk_forward_horizon(df: pd.DataFrame, feats: list[str],
                            label_col: str, horizon_name: str):
    """Expanding-window monthly walk-forward for a single horizon."""
    print(f"\n{'='*78}\nHORIZON {horizon_name} — walk-forward\n{'='*78}")
    months = sorted(df["year_month"].unique())
    start_idx = next(i for i, m in enumerate(months)
                       if str(m) >= FIRST_SCORED_MONTH)
    fold_records = []
    oos_records = []
    importance_records = []
    for i in range(start_idx, len(months)):
        scoring_month = months[i]
        if str(scoring_month) > LAST_SCORED_MONTH:
            break
        train_mask = df["year_month"] < scoring_month
        oos_mask = df["year_month"] == scoring_month
        n_train = int(train_mask.sum())
        n_oos = int(oos_mask.sum())
        if n_train < 500 or n_oos < 20:
            continue
        # Temporal val split within training
        train_df = df[train_mask].sort_values("close_ts_ns")
        n_val = int(len(train_df) * VAL_FRAC)
        n_tr_only = len(train_df) - n_val
        X_tr = train_df.iloc[:n_tr_only][feats]
        y_tr = train_df.iloc[:n_tr_only][label_col]
        X_val = train_df.iloc[n_tr_only:][feats]
        y_val = train_df.iloc[n_tr_only:][label_col]
        oos_df = df[oos_mask]
        X_oos = oos_df[feats]
        y_oos = oos_df[label_col]
        if y_tr.sum() < 5 or y_val.sum() < 1:
            print(f"  skip {scoring_month}: too few positives "
                  f"(tr={int(y_tr.sum())}, val={int(y_val.sum())})")
            continue
        model = fit_horizon_model(X_tr, y_tr, X_val, y_val)
        p_oos = model.predict_proba(X_oos)[:, 1]
        if y_oos.nunique() < 2:
            auc = np.nan
        else:
            auc = roc_auc_score(y_oos, p_oos)
        fold_records.append({
            "month": str(scoring_month), "n_train": n_train,
            "n_oos": n_oos, "n_pos_oos": int(y_oos.sum()),
            "auc": float(auc),
            "best_iter": int(model.best_iteration_),
        })
        for k in range(len(oos_df)):
            oos_records.append({
                "close_ts_ns": int(oos_df["close_ts_ns"].iloc[k]),
                "direction": int(oos_df["candidate_direction"].iloc[k]),
                "year": int(oos_df["year"].iloc[k]),
                "month": str(scoring_month),
                "p_score": float(p_oos[k]),
                "label": int(y_oos.iloc[k]),
            })
        # Feature importance (gain)
        imp = pd.DataFrame({
            "feat": feats,
            "gain": model.booster_.feature_importance(
                importance_type="gain"),
        }).sort_values("gain", ascending=False).head(15)
        imp["month"] = str(scoring_month)
        importance_records.append(imp)
        print(f"  {scoring_month}: train n={n_train:>5,}  oos={n_oos:>4}  "
              f"pos_oos={int(y_oos.sum()):>3}  AUC={auc:.4f}  "
              f"best_iter={model.best_iteration_:>3}")
    return (pd.DataFrame(fold_records),
              pd.DataFrame(oos_records),
              pd.concat(importance_records, ignore_index=True))


def report_horizon(name: str, folds: pd.DataFrame, oos: pd.DataFrame,
                       imp: pd.DataFrame):
    print(f"\n{'='*78}\nRESULTS — {name}\n{'='*78}")
    mean_auc = folds["auc"].mean()
    median_auc = folds["auc"].median()
    auc_above_05 = (folds["auc"] > 0.50).sum()
    auc_above_055 = (folds["auc"] > 0.55).sum()
    print(f"\n  Per-fold AUC: mean={mean_auc:.4f}  median={median_auc:.4f}")
    print(f"    Folds with AUC > 0.50: {auc_above_05} / {len(folds)} "
          f"({auc_above_05/len(folds):.0%})")
    print(f"    Folds with AUC > 0.55: {auc_above_055} / {len(folds)} "
          f"({auc_above_055/len(folds):.0%})")
    # Aggregate OOS AUC
    if oos["label"].nunique() > 1:
        agg_auc = roc_auc_score(oos["label"], oos["p_score"])
    else:
        agg_auc = np.nan
    base_rate = oos["label"].mean()
    print(f"  Aggregate OOS AUC: {agg_auc:.4f}  base rate={base_rate:.3%}  "
          f"n={len(oos):,}")

    # Top-K precision/recall/lift
    print(f"\n  Top-quantile performance (label = positive flip at horizon):")
    print(f"    {'gate':<10}  {'kept':>5}  {'prec':>7}  {'rec':>7}  "
          f"{'lift':>6}")
    for q in [0.01, 0.02, 0.05, 0.10]:
        thresh = oos["p_score"].quantile(1 - q)
        kept = oos[oos["p_score"] >= thresh]
        n_pos_kept = int(kept["label"].sum())
        total_pos = int(oos["label"].sum())
        precision = n_pos_kept / max(len(kept), 1)
        recall = n_pos_kept / max(total_pos, 1)
        lift = precision / max(base_rate, 1e-9)
        print(f"    top {q*100:>3.0f}%   {len(kept):>5,}  "
              f"{precision:>6.2%}  {recall:>6.2%}  {lift:>5.2f}x")

    # Feature importance stability
    print(f"\n  Feature importance stability (top-15 across {len(folds)} folds):")
    feat_appearances = imp.groupby("feat").size().sort_values(ascending=False)
    avg_gain = imp.groupby("feat")["gain"].mean()
    consistency = pd.DataFrame({
        "n_appearances": feat_appearances,
        "avg_gain": avg_gain.reindex(feat_appearances.index),
        "stability_pct": feat_appearances / len(folds),
    }).sort_values("stability_pct", ascending=False).head(15)
    print(consistency.to_string())


def trade_sim_horizon(name: str, oos: pd.DataFrame, horizon: int,
                          candidates: pd.DataFrame, va_flips: pd.DataFrame,
                          bars_1s_by_year: dict[int, dict],
                          top_quantile: float = 0.05):
    """Trade simulation for the top quantile of OOS predictions.

    Entry at next 1s bar OPEN after candidate.close_ts in direction d.
    Exit logic:
      (1) If V_A confirms flip at exact horizon: exit at V_A trade's
          natural regime-flip exit (use trades.parquet net_pnl).
      (2a) No flip + bar-close exit: exit at 1s bar OPEN price at
           candidate.close_ts + horizon*60s.
      (2b) No flip + time-stop exit: exit at 1s bar OPEN at
           candidate.close_ts + TIME_STOP_S.
    """
    # Join candidate metadata (fill_price proxy = close_1m, atr_at_signal)
    # to predictions
    cand_lookup = candidates.set_index(
        ["close_ts_ns", "candidate_direction"])
    thresh = oos["p_score"].quantile(1 - top_quantile)
    fired = oos[oos["p_score"] >= thresh].copy()
    print(f"\n  TRADE SIM — top {top_quantile*100:.0f}%  ({name})")
    print(f"    n fired: {len(fired):,}")
    if len(fired) == 0:
        return

    # Build V_A flip lookup: (flip_bar_close_ts, direction) -> trade
    # We need the net_pnl when V_A actually entered after the flip
    va_lookup = va_flips.set_index(["flip_bar_close_ts", "direction"])

    rows = []
    for _, fr in fired.iterrows():
        cts = int(fr["close_ts_ns"])
        d = int(fr["direction"])
        yr = int(fr["year"])
        bars = bars_1s_by_year[yr]
        bars_ts = bars["ts"]; bars_o = bars["o"]; bars_c = bars["c"]
        # Get candidate context (atr, fill_price)
        try:
            cand = cand_lookup.loc[(cts, d)]
        except KeyError:
            continue
        atr = float(cand["atr_1m"])
        # Entry at next 1s bar open after candidate close_ts
        i_entry = int(np.searchsorted(bars_ts, cts, side="left"))
        if i_entry >= len(bars_ts):
            continue
        entry_px = float(bars_o[i_entry])
        entry_ts_actual = int(bars_ts[i_entry])
        # Outcome 1: V_A confirmed flip at horizon
        target_flip_ts = cts + horizon * 60_000_000_000
        try:
            va_row = va_lookup.loc[(target_flip_ts, d)]
            # V_A confirmed at expected horizon
            va_exit_px = float(va_row["exit_price"])
            va_pnl_raw = (va_exit_px - entry_px) * d * NQ_MULT
            outcome_va = "va_confirm"
            pnl_va = va_pnl_raw - 2 * COMMISSION_ONE_WAY
        except KeyError:
            outcome_va = "no_va_flip"
            pnl_va = None
            va_exit_px = None
        # Outcome 2a: bar-close exit at predicted-flip bar
        no_flip_close_ts = cts + horizon * 60_000_000_000
        i_close = int(np.searchsorted(
            bars_ts, no_flip_close_ts, side="left"))
        if i_close < len(bars_ts):
            close_px_2a = float(bars_o[i_close])
            pnl_2a_raw = (close_px_2a - entry_px) * d * NQ_MULT
            pnl_2a = pnl_2a_raw - 2 * COMMISSION_ONE_WAY
        else:
            pnl_2a = np.nan
        # Outcome 2b: time-stop exit at +5min
        ts_stop = cts + TIME_STOP_S * 1_000_000_000
        i_stop = int(np.searchsorted(bars_ts, ts_stop, side="left"))
        if i_stop < len(bars_ts):
            stop_px = float(bars_o[i_stop])
            pnl_2b_raw = (stop_px - entry_px) * d * NQ_MULT
            pnl_2b = pnl_2b_raw - 2 * COMMISSION_ONE_WAY
        else:
            pnl_2b = np.nan
        rows.append({
            "close_ts_ns": cts, "direction": d, "year": yr,
            "p_score": float(fr["p_score"]),
            "label": int(fr["label"]),
            "atr": atr, "entry_px": entry_px,
            "outcome_va": outcome_va,
            "pnl_va_confirm": pnl_va,
            "pnl_no_flip_barclose": pnl_2a,
            "pnl_no_flip_timestop": pnl_2b,
        })
    sim_df = pd.DataFrame(rows)
    # Combined PnL: if V_A confirmed, use V_A exit; else use either 2a or 2b
    sim_df["pnl_combined_barclose"] = np.where(
        sim_df["pnl_va_confirm"].notna(),
        sim_df["pnl_va_confirm"],
        sim_df["pnl_no_flip_barclose"])
    sim_df["pnl_combined_timestop"] = np.where(
        sim_df["pnl_va_confirm"].notna(),
        sim_df["pnl_va_confirm"],
        sim_df["pnl_no_flip_timestop"])
    n = len(sim_df)
    n_va = int(sim_df["pnl_va_confirm"].notna().sum())
    n_noflip = n - n_va
    print(f"    Outcomes: VA-confirmed n={n_va}  ({n_va/n:.1%})  "
          f"no-flip n={n_noflip}  ({n_noflip/n:.1%})")
    print(f"\n    Combined PnL with bar-close exit on no-flip:")
    bc = sim_df["pnl_combined_barclose"]
    print(f"      total=${bc.sum():+,.0f}  mean=${bc.mean():+.2f}/tr  "
          f"WR={(bc > 0).mean():.1%}")
    print(f"    Combined PnL with time-stop exit on no-flip:")
    ts = sim_df["pnl_combined_timestop"]
    print(f"      total=${ts.sum():+,.0f}  mean=${ts.mean():+.2f}/tr  "
          f"WR={(ts > 0).mean():.1%}")
    # Per-year
    print(f"\n    Per-year (combined bar-close / time-stop):")
    print(f"      {'year':>4}  {'n':>4}  {'barclose_$':>11}  "
          f"{'timestop_$':>11}  {'va%':>5}")
    for yr in sorted(sim_df["year"].unique()):
        ysub = sim_df[sim_df["year"] == yr]
        bc_y = ysub["pnl_combined_barclose"].sum()
        ts_y = ysub["pnl_combined_timestop"].sum()
        va_y = ysub["pnl_va_confirm"].notna().mean() * 100
        print(f"      {yr:>4}  {len(ysub):>4}  ${bc_y:>+8,.0f}  "
              f"${ts_y:>+8,.0f}  {va_y:>4.1f}%")
    return sim_df


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    print("=" * 78)
    print("PRE-FLIP WALK-FORWARD TRAINING (T-1, T-2, T-3)")
    print("=" * 78)

    df = load_candidates()
    print(f"\nLoaded {len(df):,} candidates")
    feats = feature_columns(df)
    print(f"  Features: {len(feats)}")
    print(f"  Per-year: {df.groupby('year').size().to_dict()}")

    all_results = {}
    for H in [1, 2, 3]:
        label_col = f"label_T{H}"
        folds, oos, imp = walk_forward_horizon(
            df, feats, label_col, f"T-{H}")
        report_horizon(f"T-{H}", folds, oos, imp)
        oos.to_parquet(OUT / f"pre_flip_oos_T{H}.parquet")
        folds.to_csv(OUT / f"pre_flip_folds_T{H}.csv", index=False)
        all_results[H] = {"folds": folds, "oos": oos, "imp": imp}

    # Trade sim only on horizons with aggregate OOS AUC > 0.55
    print(f"\n{'='*78}\nTRADING SIM (only horizons with OOS AUC > 0.55)")
    print(f"{'='*78}")
    # Load V_A flip outcomes for trade sim
    print(f"\n  Loading V_A trades for outcome lookup...")
    va_rows = []
    for yr in [2024, 2025, 2026]:
        snap = pd.read_parquet(
            f"collectors/collector_v2/results/v_a_v0_{yr}/snapshots_with_vol_vwap.parquet",
            columns=["kind", "decision_ts", "direction", "became_trade",
                       "session"])
        trades = pd.read_parquet(
            f"collectors/collector_v2/results/v_a_v0_{yr}/trades.parquet",
            columns=["decision_ts", "direction", "fill_price", "exit_price",
                       "net_pnl", "atr_at_signal", "exit_ts", "session"])
        b1 = snap[(snap["kind"] == "bar1_check")
                    & (snap["became_trade"])
                    & (snap["session"] == "RTH")].copy()
        b1["flip_bar_close_ts"] = b1["decision_ts"] - 61_000_000_000
        b1_with_trade = b1.merge(
            trades[trades["session"] == "RTH"][[
                "decision_ts", "direction", "exit_price", "net_pnl"]],
            on=["decision_ts", "direction"], how="inner")
        va_rows.append(b1_with_trade[[
            "flip_bar_close_ts", "direction", "exit_price", "net_pnl"]])
    va_flips = pd.concat(va_rows, ignore_index=True).drop_duplicates(
        subset=["flip_bar_close_ts", "direction"])
    print(f"    V_A flip outcomes: {len(va_flips):,}")

    # Load 1s OHLC for trade sim
    print(f"  Loading 1s OHLC per year for entry/exit prices...")
    bars_by_year = {}
    for yr in [2024, 2025, 2026]:
        df_1s = pd.read_parquet(
            f"data/raw/NQ_v0_1s_{yr}{'_ytd' if yr == 2026 else ''}.parquet",
            columns=["ts_event", "open", "close"])
        if "ts_event" not in df_1s.columns:
            df_1s = df_1s.reset_index()
        df_1s = df_1s.sort_values("ts_event").reset_index(drop=True)
        if df_1s["ts_event"].dt.tz is None:
            df_1s["ts_event"] = df_1s["ts_event"].dt.tz_localize("UTC")
        ts_naive = df_1s["ts_event"].dt.tz_localize(None)
        bars_by_year[yr] = {
            "ts": ts_naive.astype("datetime64[ns]").astype("int64").to_numpy(),
            "o": df_1s["open"].to_numpy(),
            "c": df_1s["close"].to_numpy(),
        }

    for H in [1, 2, 3]:
        oos_h = all_results[H]["oos"]
        agg_auc = (roc_auc_score(oos_h["label"], oos_h["p_score"])
                       if oos_h["label"].nunique() > 1 else np.nan)
        if agg_auc < 0.55 or np.isnan(agg_auc):
            print(f"\n  T-{H} OOS AUC={agg_auc:.4f} < 0.55 — skipping trade sim")
            continue
        for q in [0.01, 0.02, 0.05, 0.10]:
            sim_df = trade_sim_horizon(
                f"T-{H} top {q*100:.0f}%", oos_h, H, df, va_flips,
                bars_by_year, top_quantile=q)
            if sim_df is not None:
                sim_df.to_parquet(
                    OUT / f"pre_flip_trade_sim_T{H}_top{int(q*100)}.parquet")

    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
