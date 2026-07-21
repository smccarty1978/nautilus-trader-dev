"""Augmented model ablation across all 3 horizons.

Uses the 97-feature AUGMENTED candidate table. Removes
`dist_to_1m_flip_threshold_atr_dir`. Trains walk-forward T-1, T-2,
T-3. Reports AUC, top-quantile lift, feature importance, VA-confirm%,
no-flip $/tr, and PnL using bar-close fail-fast sim.

Goal: determine whether the augmented volume/VWAP/calendar features
add real signal once the dominant threshold-distance feature is
removed.
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
ABLATED_FEATURE = "dist_to_1m_flip_threshold_atr_dir"


def feature_columns(df: pd.DataFrame, exclude_ablated=True) -> list[str]:
    drop = set([
        "ts_event_ns", "close_ts_ns", "close_dt", "year_month", "year",
        "open_1m", "high_1m", "low_1m", "close_1m",
        "ema3_h_1m", "ema9_h_1m", "ema3_l_1m", "ema9_l_1m",
        "close_5s", "close_15s", "close_30s",
        "close_3m", "close_5m",
        "vwap_value",
        "label_T1", "label_T2", "label_T3",
    ])
    if exclude_ablated:
        drop.add(ABLATED_FEATURE)
    feats = [c for c in df.columns if c not in drop]
    feats = [c for c in feats
              if df[c].dtype not in ("object", "datetime64[ns, UTC]")]
    return feats


def fit_model(X_tr, y_tr, X_val, y_val):
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


def walk_forward(df, feats, label_col, horizon_name):
    print(f"\n{'='*78}\nHORIZON {horizon_name}\n{'='*78}")
    months = sorted(df["year_month"].unique())
    start_idx = next(i for i, m in enumerate(months)
                       if str(m) >= FIRST_SCORED_MONTH)
    fold_records = []
    oos_records = []
    imp_records = []
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
            continue
        model = fit_model(X_tr, y_tr, X_val, y_val)
        p_oos = model.predict_proba(X_oos)[:, 1]
        auc = (roc_auc_score(y_oos, p_oos) if y_oos.nunique() > 1
                  else np.nan)
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
        imp = pd.DataFrame({
            "feat": feats,
            "gain": model.booster_.feature_importance(
                importance_type="gain"),
        }).sort_values("gain", ascending=False).head(20)
        imp["month"] = str(scoring_month)
        imp_records.append(imp)
        print(f"  {scoring_month}: train={n_train:>5,}  oos={n_oos:>4}  "
              f"AUC={auc:.4f}")
    return (pd.DataFrame(fold_records),
              pd.DataFrame(oos_records),
              pd.concat(imp_records, ignore_index=True))


def report_horizon_aucs(name, folds, oos):
    mean_auc = folds["auc"].mean()
    above_055 = (folds["auc"] > 0.55).sum()
    print(f"\n  --- {name} AUC ---")
    print(f"  Per-fold AUC: mean={mean_auc:.4f}  "
          f"folds > 0.55: {above_055}/{len(folds)}")
    agg_auc = (roc_auc_score(oos["label"], oos["p_score"])
                  if oos["label"].nunique() > 1 else np.nan)
    base_rate = oos["label"].mean()
    print(f"  Aggregate OOS AUC: {agg_auc:.4f}  base rate: {base_rate:.3%}")
    print(f"  Top-quantile lift:")
    for q in [0.01, 0.02, 0.05, 0.10]:
        thresh = oos["p_score"].quantile(1 - q)
        kept = oos[oos["p_score"] >= thresh]
        prec = kept["label"].mean()
        lift = prec / max(base_rate, 1e-9)
        print(f"    top {q*100:>3.0f}%   n={len(kept):>5,}  "
              f"prec={prec:>5.2%}  lift={lift:.2f}x")
    return agg_auc


def report_horizon_features(name, imp, folds):
    print(f"\n  --- {name} top 15 features ---")
    feat_avg = imp.groupby("feat")["gain"].mean().sort_values(
        ascending=False).head(15)
    feat_count = imp.groupby("feat").size().reindex(feat_avg.index)
    aug_prefixes = ("vol_", "vwap_", "obv_", "dist_close_to_vwap",
                       "dist_to_vwap_", "regime_3m", "regime_5m",
                       "bars_in_regime_3m", "bars_in_regime_5m",
                       "atr_3m", "atr_5m", "cum_vol", "minute_",
                       "hour_", "day_of_week", "minutes_since")
    for f, g in feat_avg.items():
        n = feat_count.loc[f]
        is_aug = "  <NEW>" if f.startswith(aug_prefixes) else ""
        print(f"    {f:<42}  gain={g:>8.0f}  in {n}/{len(folds)}{is_aug}")


def load_va_flips_for_sim():
    rows = []
    for yr in [2024, 2025, 2026]:
        snap = pd.read_parquet(
            f"collectors/collector_v2/results/v_a_v0_{yr}/snapshots_with_vol_vwap.parquet",
            columns=["kind", "decision_ts", "direction",
                       "became_trade", "session"])
        trades = pd.read_parquet(
            f"collectors/collector_v2/results/v_a_v0_{yr}/trades.parquet",
            columns=["decision_ts", "direction", "exit_ts",
                       "exit_price", "session"])
        b1 = snap[(snap["kind"] == "bar1_check")
                    & (snap["became_trade"])
                    & (snap["session"] == "RTH")].copy()
        b1["flip_bar_close_ts"] = b1["decision_ts"] - 61_000_000_000
        merged = b1.merge(
            trades[trades["session"] == "RTH"][[
                "decision_ts", "direction", "exit_ts", "exit_price"]],
            on=["decision_ts", "direction"], how="inner")
        rows.append(merged[[
            "flip_bar_close_ts", "direction", "exit_ts", "exit_price"]])
    va = pd.concat(rows, ignore_index=True).drop_duplicates(
        subset=["flip_bar_close_ts", "direction"])
    return va


def load_bars_per_year():
    bars = {}
    for yr in [2024, 2025, 2026]:
        path = f"data/raw/NQ_v0_1s_{yr}{'_ytd' if yr == 2026 else ''}.parquet"
        df = pq.read_table(
            path, columns=["ts_event", "open"]).to_pandas()
        if "ts_event" not in df.columns:
            df = df.reset_index()
        df = df.sort_values("ts_event").reset_index(drop=True)
        if df["ts_event"].dt.tz is None:
            df["ts_event"] = df["ts_event"].dt.tz_localize("UTC")
        ts = df["ts_event"].dt.tz_localize(None
            ).astype("datetime64[ns]").astype("int64")
        bars[yr] = {"ts": ts.to_numpy(), "o": df["open"].to_numpy()}
    return bars


def trade_sim(oos, horizon, va_lookup, bars_by_year,
                  top_quantile=0.10):
    """Bar-close fail-fast simulation.

    For each top-quantile fired candidate:
      - Entry at next 1s bar OPEN after candidate.close_ts in direction d
      - If V_A confirms at target_flip_ts = close_ts + horizon*60s:
          exit at V_A's regime-flip outcome (exit_price)
      - Else: exit at close_ts + horizon*60s (bar OPEN at that time)
    """
    thresh = oos["p_score"].quantile(1 - top_quantile)
    fired = oos[oos["p_score"] >= thresh].copy().reset_index(drop=True)
    n = len(fired)
    rows = []
    for _, fr in fired.iterrows():
        cts = int(fr["close_ts_ns"])
        d = int(fr["direction"])
        yr = int(fr["year"])
        bars = bars_by_year[yr]
        bars_ts = bars["ts"]; bars_o = bars["o"]
        i_entry = int(np.searchsorted(bars_ts, cts, side="left"))
        if i_entry >= len(bars_ts):
            continue
        entry_px = float(bars_o[i_entry])
        target_ts = cts + horizon * 60_000_000_000
        try:
            va = va_lookup.loc[(target_ts, d)]
            outcome = "va_confirm"
            exit_px = float(va["exit_price"])
        except KeyError:
            outcome = "no_flip"
            i_exit = int(np.searchsorted(bars_ts, target_ts, side="left"))
            if i_exit >= len(bars_ts):
                continue
            exit_px = float(bars_o[i_exit])
        pnl = (exit_px - entry_px) * d * NQ_MULT - 2 * COMMISSION_ONE_WAY
        rows.append({
            "year": yr, "outcome": outcome, "pnl": pnl,
            "p_score": float(fr["p_score"]),
        })
    return pd.DataFrame(rows)


def report_sim(name, sim_df, horizon, top_quantile):
    n = len(sim_df)
    if n == 0:
        print(f"\n  --- {name} sim — NO TRADES ---")
        return
    total = sim_df["pnl"].sum()
    mean = sim_df["pnl"].mean()
    wr = (sim_df["pnl"] > 0).mean()
    va = sim_df[sim_df["outcome"] == "va_confirm"]
    nf = sim_df[sim_df["outcome"] == "no_flip"]
    va_pct = len(va) / n
    print(f"\n  --- {name} sim (top {top_quantile*100:.0f}%, T-{horizon}) ---")
    print(f"  n={n:,}  total=${total:+,.0f}  mean=${mean:+.2f}/tr  WR={wr:.1%}")
    print(f"  VA-confirm rate: {va_pct:.1%} ({len(va)}/{n})")
    if len(va):
        print(f"    VA-confirm: total=${va['pnl'].sum():+,.0f}  "
              f"mean=${va['pnl'].mean():+.2f}/tr")
    if len(nf):
        print(f"    No-flip:    total=${nf['pnl'].sum():+,.0f}  "
              f"mean=${nf['pnl'].mean():+.2f}/tr")
    # Per-year
    print(f"  Per-year:")
    for yr in sorted(sim_df["year"].unique()):
        ysub = sim_df[sim_df["year"] == yr]
        ysub_va = ysub[ysub["outcome"] == "va_confirm"]
        print(f"    {yr}  n={len(ysub):>4}  total=${ysub['pnl'].sum():>+8,.0f}  "
              f"mean=${ysub['pnl'].mean():>+6.2f}/tr  "
              f"VA%={len(ysub_va)/max(len(ysub),1):.1%}")


def main():
    t0 = time.time()
    print("=" * 78)
    print("AUGMENTED ABLATION — drop dist_to_1m_flip_threshold_atr_dir")
    print("Train T-1 / T-2 / T-3 on 97-feature augmented set minus 1")
    print("=" * 78)

    aug_path = OUT / "pre_flip_candidates_augmented.parquet"
    df = pd.read_parquet(aug_path)
    df["close_dt"] = pd.to_datetime(df["close_ts_ns"], unit="ns", utc=True)
    df["year_month"] = (df["close_dt"].dt.tz_convert("America/Chicago")
                          ).dt.to_period("M")
    print(f"\nLoaded {len(df):,} augmented candidates")
    feats_full = feature_columns(df, exclude_ablated=False)
    feats_ablated = feature_columns(df, exclude_ablated=True)
    print(f"  full features:    {len(feats_full)}")
    print(f"  ablated features: {len(feats_ablated)} (dropped '{ABLATED_FEATURE}')")

    # Baselines (with the dominant feature)
    baselines = {1: 0.6950, 2: 0.5444, 3: 0.5139}
    # Ablation reference (50-feature ablation)
    ablation_50f = 0.6895

    # Walk-forward all horizons
    results = {}
    for H in [1, 2, 3]:
        folds, oos, imp = walk_forward(
            df, feats_ablated, f"label_T{H}", f"T-{H} (97-feat ablated)")
        agg_auc = report_horizon_aucs(f"T-{H} (97-feat ablated)",
                                              folds, oos)
        report_horizon_features(f"T-{H} (97-feat ablated)", imp, folds)
        results[H] = {"folds": folds, "oos": oos, "imp": imp,
                          "auc": agg_auc}
        oos.to_parquet(
            OUT / f"pre_flip_aug_ablation_oos_T{H}.parquet", index=False)

    # Final AUC comparison
    print(f"\n{'='*78}\nAUC COMPARISON\n{'='*78}")
    print(f"  {'Horizon':<10}  {'Baseline 97f':>14}  "
          f"{'Ablated 97f':>14}  {'Δ':>8}  {'Ablated 50f':>14}")
    for H in [1, 2, 3]:
        delta = results[H]["auc"] - baselines[H]
        ref_50 = ablation_50f if H == 1 else "—"
        print(f"  T-{H:<8}  {baselines[H]:>14.4f}  "
              f"{results[H]['auc']:>14.4f}  {delta:>+8.4f}  "
              f"{(f'{ref_50:.4f}' if H == 1 else '—'):>14}")

    # Trade simulation per horizon
    print(f"\n{'='*78}\nTRADE SIMULATION (bar-close fail-fast)\n{'='*78}")
    va = load_va_flips_for_sim()
    va_lookup = va.set_index(["flip_bar_close_ts", "direction"])
    print(f"  V_A flip outcomes loaded: {len(va):,}")
    bars_by_year = load_bars_per_year()
    print(f"  1s bars loaded for 2024/2025/2026")

    for H in [1, 2, 3]:
        oos_h = results[H]["oos"]
        for q in [0.10, 0.05, 0.02]:
            sim = trade_sim(oos_h, H, va_lookup, bars_by_year, q)
            report_sim(f"T-{H} ablated 97f", sim, H, q)
            if len(sim):
                sim.to_parquet(
                    OUT / f"pre_flip_aug_ablation_sim_T{H}_top{int(q*100)}.parquet",
                    index=False)

    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
