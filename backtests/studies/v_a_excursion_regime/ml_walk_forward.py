"""Walk-forward validation of the +1m LGB classifier.

Two rolling fits, same threshold-selection rule (largest threshold where
train C1 cut <= 5%):

  Fit 1: train on 2024 ONLY (C1+C5)
         predict on 2025 (true OOS) and 2026 (further OOS)

  Fit 2: train on 2024+2025 (C1+C5)  (current pipeline)
         predict on 2026 (true OOS)

If 2026 lift is consistent across both fits AND C1 cut stays under 5%
across all OOS years, the +$1,335 OOS lift from the original fit is
credible. If Fit 1 shows wildly different behavior on 2025/2026, the
LGB pattern is fit-window-specific and not generalizable.

Same model hyperparameters (max_depth=3, n_estimators=100, lr=0.05).
Same feature set (10 +1m features). No re-tuning on holdout.
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
    ts_rows = []
    for yr in (2024, 2025, 2026):
        wex = pd.read_parquet(OUT / f"v_a_v0_{yr}_with_excursion.parquet")
        filt = wex[(wex["total_excursion_slow"] >= SLOW_LO_CUT)
                     & (wex["total_excursion_slow"] < SLOW_HI_CUT)].copy()
        sub = filt[["entry_ts", "exit_ts"]].copy()
        sub["year"] = yr; sub["trade_idx"] = filt.index
        ts_rows.append(sub)
    ts_df = pd.concat(ts_rows, ignore_index=True)
    plus1m = plus1m.merge(ts_df, on=["year", "trade_idx"], how="left")
    cmap = {"1_good_runner": "C1", "2_good_normal_win": "C2",
              "3_v4_false_exit": "C3", "4_v4_true_save": "C4",
              "5_v4_missed_loser": "C5"}
    plus1m["cls"] = plus1m["class"].map(cmap)
    return plus1m.dropna(subset=FEATURES).copy()


def fit_lgb(train_df):
    train_df = train_df[train_df["cls"].isin(["C1", "C5"])].copy()
    train_df["label"] = (train_df["cls"] == "C5").astype(int)
    X = train_df[FEATURES]
    y = train_df["label"].values
    m = lgb.LGBMClassifier(
        max_depth=3, n_estimators=100, learning_rate=0.05,
        num_leaves=7, min_child_samples=50,
        class_weight="balanced", random_state=42, n_jobs=1, verbose=-1,
    )
    m.fit(X.values, y)
    return m, train_df, X, y


def select_threshold(model, train_df, X, y, c1_cap_pct=5.0):
    """Largest threshold where train C1 cut <= c1_cap_pct AND > 0."""
    proba = model.predict_proba(X.values)[:, 1]
    train_df = train_df.copy()
    train_df["proba"] = proba
    n_c1 = (train_df["cls"] == "C1").sum()
    rows = []
    for th in np.arange(0.50, 0.96, 0.025):
        th = round(th, 3)
        fired = train_df["proba"] >= th
        c1_cut = ((train_df["cls"] == "C1") & fired).sum()
        c5_catch = ((train_df["cls"] == "C5") & fired).sum()
        c1_pct = 100 * c1_cut / max(n_c1, 1)
        c5_pct = (100 * c5_catch
                    / max((train_df["cls"] == "C5").sum(), 1))
        rows.append({"thresh": th, "c1_pct": c1_pct, "c5_pct": c5_pct})
    valid = [r for r in rows if r["c1_pct"] <= c1_cap_pct]
    if not valid:
        return rows[-1]["thresh"], rows
    sel = max(valid, key=lambda r: r["c5_pct"])
    return sel["thresh"], rows


def evaluate_on_year(model, scaled_threshold, eval_year_df, bars_arrs):
    """Compute LGB fires, fill_at_1m, baseline, V4, stack PnL on a year."""
    eval_year_df = eval_year_df.copy()
    eval_year_df["proba"] = model.predict_proba(
        eval_year_df[FEATURES].values)[:, 1]
    eval_year_df["fires"] = eval_year_df["proba"] >= scaled_threshold

    fill_at_1m = []; v4_pnl_recon = []
    for _, tr in eval_year_df.iterrows():
        yr = int(tr["year"])
        ts_idx, opens = bars_arrs[yr]
        entry_ts = int(tr["entry_ts"])
        exit_ts = int(tr["exit_ts"])
        direction = int(tr["direction"])
        fill_px = float(tr["fill_price"])
        cp1 = entry_ts + 60 * 1_000_000_000
        fill_at_1m.append(
            fill_open_at(cp1, ts_idx, opens) if cp1 < exit_ts else np.nan)
        if not bool(tr["v4_fired"]):
            v4_pnl_recon.append(float(tr["net_pnl"])); continue
        cp4 = entry_ts + 240 * 1_000_000_000
        if cp4 >= exit_ts:
            v4_pnl_recon.append(float(tr["net_pnl"])); continue
        fp4 = fill_open_at(cp4, ts_idx, opens)
        v4_pnl_recon.append(compute_alt_pnl(direction, fill_px, fp4))
    eval_year_df["fill_at_1m"] = fill_at_1m
    eval_year_df["alt_pnl_1m"] = eval_year_df.apply(
        lambda r: compute_alt_pnl(int(r["direction"]),
                                       float(r["fill_price"]),
                                       r["fill_at_1m"]), axis=1)
    eval_year_df["v4_pnl"] = v4_pnl_recon
    eval_year_df["baseline_pnl"] = eval_year_df["net_pnl"]
    eval_year_df["stack_pnl"] = np.where(
        eval_year_df["fires"] & eval_year_df["alt_pnl_1m"].notna(),
        eval_year_df["alt_pnl_1m"],
        np.where(eval_year_df["v4_fired"], eval_year_df["v4_pnl"],
                  eval_year_df["baseline_pnl"]))
    return eval_year_df


t0 = None


def main():
    global t0
    t0 = time.time()
    print("=" * 78)
    print("ML CLASSIFIER WALK-FORWARD VALIDATION")
    print("=" * 78)

    df = load_eval_data()
    print(f"\n  total +1m rows: {len(df):,}")

    # Pre-load bars once
    bars_by_year = {y: load_year_bars(y) for y in (2024, 2025, 2026)}
    arrs = {y: (b.index.astype("int64").to_numpy(),
                 b["open"].values.astype(np.float64))
              for y, b in bars_by_year.items()}

    # ============================================================
    # FIT 1: train on 2024 only, predict on 2025 + 2026
    # ============================================================
    print(f"\n{'='*78}")
    print(f"FIT 1: train on 2024 only")
    print(f"{'='*78}")
    train1 = df[df["year"] == 2024]
    train1_cs = train1[train1["cls"].isin(["C1", "C5"])]
    print(f"  train rows: {len(train1_cs):,}  "
          f"(C1={(train1_cs['cls']=='C1').sum():,}, "
          f"C5={(train1_cs['cls']=='C5').sum():,})")

    m1, tr1_df, X1, y1 = fit_lgb(train1)
    train_proba = m1.predict_proba(X1.values)[:, 1]
    auc1 = roc_auc_score(y1, train_proba)
    print(f"  Fit 1 train AUC: {auc1:.3f}")
    th1, rows1 = select_threshold(m1, tr1_df, X1, y1, c1_cap_pct=5.0)
    print(f"  Fit 1 selected threshold: {th1:.3f}")

    print(f"\n  Threshold sweep on Fit 1 train (2024):")
    print(f"  {'thresh':>7} {'c1_cut%':>8} {'c5_catch%':>10}")
    for r in rows1:
        marker = "  ←" if r["thresh"] == th1 else ""
        print(f"  {r['thresh']:>7.3f} {r['c1_pct']:>+7.1f}% "
              f"{r['c5_pct']:>+9.1f}%{marker}")

    # Evaluate on 2024 (train), 2025 (OOS), 2026 (further OOS)
    print(f"\n  --- Fit 1 results per year ---")
    for yr in (2024, 2025, 2026):
        sub = df[df["year"] == yr]
        if not len(sub): continue
        ev = evaluate_on_year(m1, th1, sub, arrs)
        n_c1 = (ev["cls"] == "C1").sum()
        n_c5 = (ev["cls"] == "C5").sum()
        c1_cut = ((ev["cls"] == "C1") & ev["fires"]).sum()
        c5_catch = ((ev["cls"] == "C5") & ev["fires"]).sum()
        c1_pct = 100 * c1_cut / max(n_c1, 1)
        c5_pct = 100 * c5_catch / max(n_c5, 1)
        base = ev["baseline_pnl"].sum()
        v4 = ev["v4_pnl"].sum()
        stack = ev["stack_pnl"].sum()
        dd = add_drawdown(ev, "stack_pnl")["dd"].min()
        gate_pnl = stack > v4
        gate_c1 = c1_pct <= 5.0 if yr != 2024 else True
        v = "TRAIN" if yr == 2024 else (
            "PASS" if (gate_pnl and gate_c1) else (
                "C1>5" if not gate_c1 else "no_pnl"))
        print(f"  {yr}: C1 {c1_cut}/{n_c1}={c1_pct:.1f}%  "
              f"C5 {c5_catch}/{n_c5}={c5_pct:.1f}%  "
              f"base ${base:>+9,.0f}  V4 ${v4:>+9,.0f}  "
              f"stack ${stack:>+9,.0f}  Δv4 ${stack-v4:>+8,.0f}  "
              f"DD ${dd:>+9,.0f}  [{v}]")

    # ============================================================
    # FIT 2: train on 2024+2025, predict on 2026
    # ============================================================
    print(f"\n{'='*78}")
    print(f"FIT 2: train on 2024+2025 (current pipeline)")
    print(f"{'='*78}")
    train2 = df[df["year"].isin([2024, 2025])]
    train2_cs = train2[train2["cls"].isin(["C1", "C5"])]
    print(f"  train rows: {len(train2_cs):,}  "
          f"(C1={(train2_cs['cls']=='C1').sum():,}, "
          f"C5={(train2_cs['cls']=='C5').sum():,})")

    m2, tr2_df, X2, y2 = fit_lgb(train2)
    auc2 = roc_auc_score(y2, m2.predict_proba(X2.values)[:, 1])
    print(f"  Fit 2 train AUC: {auc2:.3f}")
    th2, rows2 = select_threshold(m2, tr2_df, X2, y2, c1_cap_pct=5.0)
    print(f"  Fit 2 selected threshold: {th2:.3f}")

    print(f"\n  --- Fit 2 results per year ---")
    for yr in (2024, 2025, 2026):
        sub = df[df["year"] == yr]
        if not len(sub): continue
        ev = evaluate_on_year(m2, th2, sub, arrs)
        n_c1 = (ev["cls"] == "C1").sum()
        n_c5 = (ev["cls"] == "C5").sum()
        c1_cut = ((ev["cls"] == "C1") & ev["fires"]).sum()
        c5_catch = ((ev["cls"] == "C5") & ev["fires"]).sum()
        c1_pct = 100 * c1_cut / max(n_c1, 1)
        c5_pct = 100 * c5_catch / max(n_c5, 1)
        base = ev["baseline_pnl"].sum()
        v4 = ev["v4_pnl"].sum()
        stack = ev["stack_pnl"].sum()
        dd = add_drawdown(ev, "stack_pnl")["dd"].min()
        gate_pnl = stack > v4
        gate_c1 = c1_pct <= 5.0 if yr == 2026 else True
        v = "TRAIN" if yr in (2024, 2025) else (
            "PASS" if (gate_pnl and gate_c1) else (
                "C1>5" if not gate_c1 else "no_pnl"))
        print(f"  {yr}: C1 {c1_cut}/{n_c1}={c1_pct:.1f}%  "
              f"C5 {c5_catch}/{n_c5}={c5_pct:.1f}%  "
              f"base ${base:>+9,.0f}  V4 ${v4:>+9,.0f}  "
              f"stack ${stack:>+9,.0f}  Δv4 ${stack-v4:>+8,.0f}  "
              f"DD ${dd:>+9,.0f}  [{v}]")

    # ============================================================
    # Cross-fit consistency on 2025 and 2026
    # ============================================================
    print(f"\n{'='*78}")
    print("CROSS-FIT CONSISTENCY (true OOS years)")
    print(f"{'='*78}")
    print(f"\n  2025 OOS:")
    print(f"    Fit 1 (trained on 2024)        — predicted on 2025")
    print(f"    Fit 2 trained ON 2025 (in-sample) — for reference")
    print(f"\n  2026 OOS:")
    print(f"    Fit 1 (trained on 2024)        — further OOS")
    print(f"    Fit 2 (trained on 2024+2025)    — current pipeline OOS")

    # Compute and tabulate both fits on each year
    print(f"\n  {'year':<6} {'fit':<4} {'thresh':>6} {'C1cut%':>7} "
          f"{'C5catch%':>9} {'stackΔ_v4':>10} {'in/out':>7}")
    for yr in (2024, 2025, 2026):
        sub = df[df["year"] == yr]
        if not len(sub): continue
        for fit_name, model, th, train_years in [
            ("F1", m1, th1, [2024]),
            ("F2", m2, th2, [2024, 2025]),
        ]:
            ev = evaluate_on_year(model, th, sub, arrs)
            n_c1 = (ev["cls"] == "C1").sum()
            n_c5 = (ev["cls"] == "C5").sum()
            c1_cut = ((ev["cls"] == "C1") & ev["fires"]).sum()
            c5_catch = ((ev["cls"] == "C5") & ev["fires"]).sum()
            c1_pct = 100 * c1_cut / max(n_c1, 1)
            c5_pct = 100 * c5_catch / max(n_c5, 1)
            v4 = ev["v4_pnl"].sum()
            stack = ev["stack_pnl"].sum()
            in_out = "TRAIN" if yr in train_years else "OOS"
            print(f"  {yr:<6} {fit_name:<4} {th:>6.3f} {c1_pct:>+6.1f}% "
                  f"{c5_pct:>+8.1f}% {stack-v4:>+9,.0f}  {in_out:>7}")

    # ============================================================
    # OOS-only summary: was the lift consistent?
    # ============================================================
    print(f"\n{'='*78}")
    print("OOS-ONLY SUMMARY (each fit, each holdout year)")
    print(f"{'='*78}")
    oos_results = []
    for fit_name, model, th, train_years in [
        ("F1", m1, th1, [2024]),
        ("F2", m2, th2, [2024, 2025]),
    ]:
        for yr in (2024, 2025, 2026):
            if yr in train_years: continue
            sub = df[df["year"] == yr]
            ev = evaluate_on_year(model, th, sub, arrs)
            n_c1 = (ev["cls"] == "C1").sum()
            c1_cut = ((ev["cls"] == "C1") & ev["fires"]).sum()
            c1_pct = 100 * c1_cut / max(n_c1, 1)
            v4 = ev["v4_pnl"].sum()
            stack = ev["stack_pnl"].sum()
            oos_results.append({
                "fit": fit_name, "year": yr, "threshold": th,
                "c1_pct": c1_pct, "stack_delta_v4": stack - v4,
                "passes_gate": (stack > v4) and (c1_pct <= 5.0),
            })
    oos = pd.DataFrame(oos_results)
    oos.to_csv(OUT / "ml_walk_forward_oos.csv", index=False)
    print(f"\n  {'fit':<4} {'year':<6} {'thresh':>6} {'C1cut%':>7} "
          f"{'Δv4':>10} {'gate':>6}")
    for _, r in oos.iterrows():
        v = "PASS" if r["passes_gate"] else (
            "C1>5" if r["c1_pct"] > 5 else "no_pnl")
        print(f"  {r['fit']:<4} {int(r['year']):<6} {r['threshold']:>6.3f} "
              f"{r['c1_pct']:>+6.1f}% {r['stack_delta_v4']:>+9,.0f}  {v:>6}")

    # Verdict
    n_pass = oos["passes_gate"].sum()
    n_oos = len(oos)
    print(f"\n  Overall: {n_pass}/{n_oos} OOS cells pass gate.")
    if n_pass == n_oos:
        print(f"  → Consistent gate-passing across walk-forward fits. "
              f"Edge looks generalizable.")
    elif n_pass == 0:
        print(f"  → No fit passes OOS. Apparent lift was IS-fit.")
    else:
        print(f"  → Mixed result. Gate-passing depends on fit window.")

    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
