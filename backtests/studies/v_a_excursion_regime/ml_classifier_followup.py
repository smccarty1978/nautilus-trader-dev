"""Follow-up analysis on the +1m ML early-kill classifier.

Three steps:
  1. Re-evaluate at TIGHTER threshold (LGB 0.700) — does 2026 C1 cut
     drop below 5% AND does PnL still improve?
  2. Inspect the C1 (runner) cuts in 2026 — borderline or strong runners?
  3. LGB feature importances — does the model use sensible features?

Same data, same models, same train/test split (no re-tuning).
"""
from __future__ import annotations
import os, sys, time
from pathlib import Path
import pandas as pd
import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score
import lightgbm as lgb

NQ_MULT = 20.0
COMMISSION = 5.0
SLOW_LO_CUT = 43.00
SLOW_HI_CUT = 71.75
OUT = Path("studies/v_a_excursion_regime/results_v0")

FEATURES = [
    "unrealized_pnl",
    "current_mfe_atr",
    "current_mae_atr",
    "mfe_to_mae",
    "close_loc_in_range",
    "net_move_xfast",
    "efficiency_xfast",
    "xfast_ratio",
    "dd_from_peak_mfe",
    "rec_from_max_mae",
]


def load_year_bars(year):
    parts = []
    files_for_year = {
        2024: ["data/raw/NQ_v0_1s_2023.parquet",
                "data/raw/NQ_v0_1s_2024.parquet"],
        2025: ["data/raw/NQ_v0_1s_2024.parquet",
                "data/raw/NQ_v0_1s_2025.parquet"],
        2026: ["data/raw/NQ_v0_1s_2025.parquet",
                "data/raw/NQ_v0_1s_2026_ytd.parquet"],
    }
    for f in files_for_year[year]:
        if Path(f).exists():
            df = pd.read_parquet(f, columns=["open","high","low","close"])
            if df.index.tz is None:
                df.index = df.index.tz_localize("UTC")
            parts.append(df)
    bars = pd.concat(parts).sort_index()
    bars = bars[~bars.index.duplicated(keep="first")]
    return bars


def fill_open_at(t_ns, ts_idx, opens):
    i = np.searchsorted(ts_idx, t_ns, side="left")
    if i >= len(opens): return np.nan
    return float(opens[i])


def compute_alt_pnl(direction, fill_px, alt_px):
    if pd.isna(alt_px): return np.nan
    pts = (alt_px - fill_px) if direction == 1 else (fill_px - alt_px)
    return pts * NQ_MULT - 2 * COMMISSION


def add_drawdown(df, col):
    df = df.sort_values("entry_ts").copy()
    df["cum"] = df[col].cumsum()
    df["cum_max"] = df["cum"].cummax()
    df["dd"] = df["cum"] - df["cum_max"]
    return df


def yearly_metrics(df, col):
    if not len(df): return {}
    n = len(df)
    wins = (df[col] > 0).sum()
    net = df[col].sum()
    df_dd = add_drawdown(df, col)
    max_dd = df_dd["dd"].min()
    df = df.copy()
    df["entry_dt"] = pd.to_datetime(df["entry_ts"], unit="ns", utc=True)
    df["month"] = df["entry_dt"].dt.tz_convert("UTC").dt.to_period("M")
    monthly = df.groupby("month")[col].sum()
    return {"n": n, "wr_pct": wins / n * 100, "net_pnl": net,
            "per_trade": net / n, "max_dd": max_dd,
            "pos_months": (monthly > 0).sum(),
            "total_months": len(monthly)}


def load_eval_data():
    """Reproduce the eval_data DataFrame as in the main script."""
    df = pd.read_parquet(OUT / "trade_quality_attribution.parquet")
    plus1m = df[df["cp"] == "+1m"].copy()
    rename = {
        "cp_unrealized_pnl": "unrealized_pnl",
        "cp_current_mfe_atr": "current_mfe_atr",
        "cp_current_mae_atr": "current_mae_atr",
        "cp_mfe_to_mae": "mfe_to_mae",
        "cp_close_loc_in_range": "close_loc_in_range",
        "cp_net_move_xfast": "net_move_xfast",
        "cp_efficiency_xfast": "efficiency_xfast",
        "cp_ratio_xfast": "xfast_ratio",
        "cp_dd_from_peak_mfe_atr": "dd_from_peak_mfe",
        "cp_rec_from_max_mae_atr": "rec_from_max_mae",
    }
    plus1m = plus1m.rename(columns=rename)

    # Join entry/exit ts
    ts_rows = []
    for yr in (2024, 2025, 2026):
        wex = pd.read_parquet(OUT / f"v_a_v0_{yr}_with_excursion.parquet")
        filt = wex[(wex["total_excursion_slow"] >= SLOW_LO_CUT)
                     & (wex["total_excursion_slow"] < SLOW_HI_CUT)].copy()
        sub = filt[["entry_ts", "exit_ts"]].copy()
        sub["year"] = yr
        sub["trade_idx"] = filt.index
        ts_rows.append(sub)
    ts_df = pd.concat(ts_rows, ignore_index=True)
    plus1m = plus1m.merge(ts_df, on=["year", "trade_idx"], how="left")

    class_map = {
        "1_good_runner": "C1", "2_good_normal_win": "C2",
        "3_v4_false_exit": "C3", "4_v4_true_save": "C4",
        "5_v4_missed_loser": "C5",
    }
    plus1m["cls"] = plus1m["class"].map(class_map)
    return plus1m


t_start = None  # global for end-of-main timing


def main():
    global t_start
    t_start = time.time()
    print("=" * 78)
    print("ML CLASSIFIER FOLLOW-UP — tighter threshold + diagnostics")
    print("=" * 78)

    # Load eval data
    df = load_eval_data()
    df = df.dropna(subset=FEATURES).copy()
    print(f"\n  eval rows: {len(df):,}")

    # Train (2024+2025, C1 vs C5)
    train = df[(df["year"].isin([2024, 2025]))
                 & (df["cls"].isin(["C1", "C5"]))].copy()
    train["label"] = (train["cls"] == "C5").astype(int)
    X_train = train[FEATURES]
    y_train = train["label"].values
    print(f"  train: {len(train):,} (C1={int((y_train==0).sum())}, "
          f"C5={int((y_train==1).sum())})")

    # Train both models
    scaler = StandardScaler().fit(X_train)
    lr = LogisticRegression(max_iter=2000, C=1.0,
                                class_weight="balanced",
                                random_state=42)
    lr.fit(scaler.transform(X_train), y_train)
    lgb_model = lgb.LGBMClassifier(
        max_depth=3, n_estimators=100, learning_rate=0.05,
        num_leaves=7, min_child_samples=50,
        class_weight="balanced", random_state=42, n_jobs=1, verbose=-1,
    )
    lgb_model.fit(X_train.values, y_train)

    # Predict on full eval set
    df["prob_LR"] = lr.predict_proba(scaler.transform(df[FEATURES]))[:, 1]
    df["prob_LGB"] = lgb_model.predict_proba(df[FEATURES].values)[:, 1]

    # Compute fill_at_1m and v4_pnl
    print(f"\n  computing +1m fills + V4 alt-fills...")
    bars_by_year = {y: load_year_bars(y) for y in (2024, 2025, 2026)}
    arrs = {}
    for yr, b in bars_by_year.items():
        arrs[yr] = (b.index.astype("int64").to_numpy(),
                     b["open"].values.astype(np.float64))
    fill_at_1m = []
    v4_pnl_recon = []
    for _, tr in df.iterrows():
        yr = int(tr["year"])
        ts_idx, opens = arrs[yr]
        entry_ts = int(tr["entry_ts"])
        exit_ts = int(tr["exit_ts"])
        direction = int(tr["direction"])
        fill_px = float(tr["fill_price"])
        # +1m
        cp1 = entry_ts + 60 * 1_000_000_000
        fill_at_1m.append(fill_open_at(cp1, ts_idx, opens)
                            if cp1 < exit_ts else np.nan)
        # V4 alt at +4m if v4_fired
        if not bool(tr["v4_fired"]):
            v4_pnl_recon.append(float(tr["net_pnl"])); continue
        cp4 = entry_ts + 240 * 1_000_000_000
        if cp4 >= exit_ts:
            v4_pnl_recon.append(float(tr["net_pnl"])); continue
        fp4 = fill_open_at(cp4, ts_idx, opens)
        v4_pnl_recon.append(compute_alt_pnl(direction, fill_px, fp4))
    df["fill_at_1m"] = fill_at_1m
    df["alt_pnl_1m"] = df.apply(
        lambda r: compute_alt_pnl(int(r["direction"]),
                                       float(r["fill_price"]),
                                       r["fill_at_1m"]), axis=1)
    df["v4_pnl"] = v4_pnl_recon
    df["baseline_pnl"] = df["net_pnl"]

    # ---------------------------------------------------------------
    # 1. Tighter threshold sweep — focus LGB at 0.675, 0.700, 0.725
    # ---------------------------------------------------------------
    print(f"\n{'='*78}")
    print("1. TIGHTER-THRESHOLD SWEEP (LGB)")
    print(f"{'='*78}")
    thresholds = [0.625, 0.650, 0.675, 0.700, 0.725, 0.750]
    rows = []
    for th in thresholds:
        df["fires_t"] = df["prob_LGB"] >= th
        df["ek_only_t"] = np.where(
            df["fires_t"] & df["alt_pnl_1m"].notna(),
            df["alt_pnl_1m"], df["baseline_pnl"])
        df["stack_t"] = np.where(
            df["fires_t"] & df["alt_pnl_1m"].notna(),
            df["alt_pnl_1m"],
            np.where(df["v4_fired"], df["v4_pnl"], df["baseline_pnl"]))
        for yr in (2024, 2025, 2026):
            sub = df[df["year"] == yr]
            if not len(sub): continue
            c1 = sub[sub["cls"] == "C1"]
            c5 = sub[sub["cls"] == "C5"]
            c1_cut = c1["fires_t"].sum()
            c5_catch = c5["fires_t"].sum()
            c1_pct = 100 * c1_cut / max(len(c1), 1)
            c5_pct = 100 * c5_catch / max(len(c5), 1)
            ek_net = sub["ek_only_t"].sum()
            stack_net = sub["stack_t"].sum()
            v4_net = sub["v4_pnl"].sum()
            base_net = sub["baseline_pnl"].sum()
            stack_dd = add_drawdown(sub, "stack_t")["dd"].min()
            rows.append({
                "thresh": th, "year": yr,
                "n_c1": len(c1), "c1_cut": c1_cut, "c1_pct": c1_pct,
                "n_c5": len(c5), "c5_catch": c5_catch, "c5_pct": c5_pct,
                "stack_net": stack_net, "v4_net": v4_net,
                "base_net": base_net, "stack_minus_v4": stack_net - v4_net,
                "stack_dd": stack_dd,
            })

    sweep = pd.DataFrame(rows)
    sweep.to_csv(OUT / "ml_followup_threshold_sweep.csv", index=False)
    for th in thresholds:
        s = sweep[sweep["thresh"] == th]
        print(f"\n  --- LGB threshold = {th:.3f} ---")
        print(f"  {'year':<6} {'C1':>4} {'cut':>3} {'cut%':>5} "
              f"{'C5':>5} {'catch':>5} {'cat%':>5} "
              f"{'stack':>9} {'V4':>9} {'Δv4':>8} {'maxDD':>9} "
              f"{'gate':>5}")
        for _, r in s.iterrows():
            gate_pnl = r["stack_net"] > r["v4_net"]
            gate_c1 = r["c1_pct"] <= 5.0
            v = "PASS" if (gate_pnl and gate_c1) else (
                "no_pnl" if not gate_pnl else "C1>5")
            print(f"  {int(r['year']):<6} {int(r['n_c1']):>4} "
                  f"{int(r['c1_cut']):>3} {r['c1_pct']:>4.1f}% "
                  f"{int(r['n_c5']):>5} {int(r['c5_catch']):>5} "
                  f"{r['c5_pct']:>4.1f}% "
                  f"{r['stack_net']:>+8,.0f} {r['v4_net']:>+8,.0f} "
                  f"{r['stack_minus_v4']:>+7,.0f} "
                  f"{r['stack_dd']:>+8,.0f} {v:>5}")

    # ---------------------------------------------------------------
    # 2. Inspect 2026 C1 cuts at threshold 0.650 (selected) and 0.700
    # ---------------------------------------------------------------
    print(f"\n{'='*78}")
    print("2. INSPECT C1 (RUNNER) CUTS IN 2026")
    print(f"{'='*78}")
    for th in (0.650, 0.700):
        df["fires"] = df["prob_LGB"] >= th
        c1_2026_cut = df[(df["year"] == 2026)
                            & (df["cls"] == "C1")
                            & (df["fires"])].copy()
        n_c1_2026 = ((df["year"] == 2026) & (df["cls"] == "C1")).sum()
        print(f"\n  --- LGB threshold = {th:.3f} | "
              f"{len(c1_2026_cut)} of {n_c1_2026} 2026 C1 runners cut ---")
        if not len(c1_2026_cut): continue
        c1_2026_cut["entry_dt"] = pd.to_datetime(
            c1_2026_cut["entry_ts"], unit="ns", utc=True)
        c1_2026_cut["alt_minus_base"] = (c1_2026_cut["alt_pnl_1m"]
                                                - c1_2026_cut["baseline_pnl"])
        cols_to_show = ["entry_dt", "direction", "prob_LGB",
                         "current_mfe_atr", "current_mae_atr",
                         "mfe_to_mae", "close_loc_in_range",
                         "net_move_xfast", "final_mfe_atr",
                         "baseline_pnl", "alt_pnl_1m", "alt_minus_base"]
        show = c1_2026_cut[cols_to_show].copy()
        # Format
        print(f"  {'entry_dt':<19} {'dir':>3} {'prob':>5} "
              f"{'mfe_a':>6} {'mae_a':>6} {'m/m':>5} "
              f"{'cloc':>5} {'xnet':>6} {'finMFE':>7} "
              f"{'base$':>7} {'alt$':>7} {'Δ':>7}")
        for _, r in show.iterrows():
            print(f"  {r['entry_dt'].strftime('%Y-%m-%d %H:%M:%S'):<19} "
                  f"{int(r['direction']):>+3} "
                  f"{r['prob_LGB']:>5.3f} "
                  f"{r['current_mfe_atr']:>+6.2f} "
                  f"{r['current_mae_atr']:>+6.2f} "
                  f"{r['mfe_to_mae']:>+5.2f} "
                  f"{r['close_loc_in_range']:>5.2f} "
                  f"{r['net_move_xfast']:>+6.2f} "
                  f"{r['final_mfe_atr']:>+7.2f} "
                  f"{r['baseline_pnl']:>+6.0f} "
                  f"{r['alt_pnl_1m']:>+6.0f} "
                  f"{r['alt_minus_base']:>+6.0f}")
        # Summary stats on cuts
        print(f"\n  Summary of cuts:")
        print(f"    median final_mfe_atr: "
              f"{c1_2026_cut['final_mfe_atr'].median():.2f}  "
              f"(C1 runners are by definition >= 3.0)")
        print(f"    median alt_minus_base: "
              f"${c1_2026_cut['alt_minus_base'].median():+,.0f}")
        print(f"    total foregone PnL: "
              f"${c1_2026_cut['alt_minus_base'].sum():+,.0f}")

    # ---------------------------------------------------------------
    # 3. LGB feature importance
    # ---------------------------------------------------------------
    print(f"\n{'='*78}")
    print("3. LGB FEATURE IMPORTANCES")
    print(f"{'='*78}")
    fi_gain = lgb_model.booster_.feature_importance(importance_type="gain")
    fi_split = lgb_model.booster_.feature_importance(importance_type="split")
    fi_df = pd.DataFrame({
        "feature": FEATURES,
        "gain": fi_gain, "split": fi_split,
    }).sort_values("gain", ascending=False)
    fi_df["gain_pct"] = 100 * fi_df["gain"] / fi_df["gain"].sum()
    fi_df.to_csv(OUT / "ml_followup_feature_importance.csv", index=False)
    print(f"\n  {'feature':<22} {'gain':>9} {'gain%':>6} {'splits':>7}")
    for _, r in fi_df.iterrows():
        print(f"  {r['feature']:<22} {r['gain']:>9.0f} {r['gain_pct']:>5.1f}% "
              f"{int(r['split']):>7}")

    # Also show LR coefficients for cross-check
    print(f"\n  LR coefficients (post-scaling):")
    print(f"  {'feature':<22} {'coef':>+8} {'abs':>6}")
    coef_df = pd.DataFrame({
        "feature": FEATURES,
        "coef": lr.coef_[0],
        "abs": np.abs(lr.coef_[0]),
    }).sort_values("abs", ascending=False)
    for _, r in coef_df.iterrows():
        print(f"  {r['feature']:<22} {r['coef']:>+7.3f} {r['abs']:>5.3f}")

    # ---------------------------------------------------------------
    # 4. Class-level PnL changes at threshold 0.700
    # ---------------------------------------------------------------
    th = 0.700
    df["fires"] = df["prob_LGB"] >= th
    print(f"\n{'='*78}")
    print(f"4. CLASS-LEVEL PnL DELTAS (LGB threshold {th:.3f})")
    print(f"{'='*78}")
    print(f"\n  {'class':<6} {'n':>5} {'fired':>5} {'fire%':>6} "
          f"{'baseline$':>10} {'EK$':>10} {'Δ':>10}")
    df["ek_pnl"] = np.where(
        df["fires"] & df["alt_pnl_1m"].notna(),
        df["alt_pnl_1m"], df["baseline_pnl"])
    for cls in ["C1", "C2", "C3", "C4", "C5"]:
        sub = df[df["cls"] == cls]
        n = len(sub)
        if not n: continue
        fired = sub["fires"].sum()
        base = sub["baseline_pnl"].sum()
        ek = sub["ek_pnl"].sum()
        print(f"  {cls:<6} {n:>5,} {int(fired):>5,} "
              f"{100*fired/n:>5.1f}% "
              f"{base:>+9,.0f} {ek:>+9,.0f} {ek - base:>+9,.0f}")

    print(f"\n[done] runtime: {time.time()-t_start:.0f}s")


if __name__ == "__main__":
    main()
