"""+1m ML early-kill classifier for V_A filtered trades.

Stack on top of V4. Goal: detect C5 uncaught losers at +1m using ONLY
features observable AT +1m. Causally-strict feature set, no outcome-
derived inputs.

Train: 2024 + 2025, classes C1 (label 0) vs C5 (label 1) only.
Holdout: 2026 (no fitting, no threshold tuning on this set).
Threshold selection: largest threshold on train where C1 cut rate <= 5%.

Features (10, all evaluated at +1m elapsed):
  unrealized_pnl
  current_mfe_atr
  current_mae_atr
  mfe_to_mae
  close_loc_in_range
  net_move_xfast      (5x30s = 2.5min, direction-aware)
  efficiency_xfast
  xfast_ratio         (alias for ratio_xfast)
  drawdown_from_peak_mfe
  recovery_from_max_mae

Models:
  M1: Logistic Regression (with feature scaling)
  M2: LightGBM shallow (max_depth=3, n_estimators=100)

Stack semantics:
  Earliest fire wins. Classifier fires at +1m (always before V4 at +4m).
  If classifier_fires(trade) at +1m → exit at OPEN of next 1s bar at +1m
  Else if V4 fires at +4m → V4 exit
  Else → baseline regime exit

Causality safeguards (all checked in audit):
  - All features computed strictly from data with ts_event < (entry +1m)
  - No use of running_mfe / final_mfe / hold_s / class label as feature
  - Train labels (C5 vs C1) are post-hoc outcomes — used ONLY for label
  - 2026 not used for train, model fit, or threshold selection
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

try:
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics import roc_auc_score, confusion_matrix
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False
    print("WARN: scikit-learn missing — LR will be skipped")

try:
    import lightgbm as lgb
    HAS_LGB = True
except ImportError:
    HAS_LGB = False
    print("WARN: lightgbm missing — LightGBM will be skipped")

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
    "xfast_ratio",            # alias for ratio_xfast
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


def load_attribution_at_1m():
    """Load attribution parquet, filter to +1m rows, build feature matrix.
    Each trade is one row. Renames cp_* columns to feature names. Also
    joins entry_ts/exit_ts from v_a_v0_{year}_with_excursion.parquet
    via (year, trade_idx) — these timestamps are needed downstream for
    fill-price computation.
    """
    df = pd.read_parquet(OUT / "trade_quality_attribution.parquet")
    plus1m = df[df["cp"] == "+1m"].copy()
    print(f"  attribution rows at +1m: {len(plus1m):,}")

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

    # Join entry_ts / exit_ts from with_excursion parquets.
    # Match the same trade_idx assignment as the attribution script:
    # filter to total_excursion_slow=mid then reset_index → trade_idx is
    # the post-reset row index.
    # Attribution script uses ORIGINAL wex pandas index (no reset_index)
    # for trade_idx. Must match exactly here.
    ts_rows = []
    for yr in (2024, 2025, 2026):
        wex = pd.read_parquet(OUT / f"v_a_v0_{yr}_with_excursion.parquet")
        filt = wex[(wex["total_excursion_slow"] >= SLOW_LO_CUT)
                     & (wex["total_excursion_slow"] < SLOW_HI_CUT)].copy()
        # NO reset_index — keep original wex index as trade_idx
        sub = filt[["entry_ts", "exit_ts"]].copy()
        sub["year"] = yr
        sub["trade_idx"] = filt.index
        ts_rows.append(sub)
    ts_df = pd.concat(ts_rows, ignore_index=True)
    plus1m = plus1m.merge(ts_df, on=["year", "trade_idx"], how="left")
    n_missing = plus1m["entry_ts"].isna().sum()
    if n_missing:
        print(f"  WARN: {n_missing:,} rows missing entry_ts after merge")
    return plus1m


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


def main():
    t_start = time.time()
    print("=" * 78)
    print("ML EARLY-KILL CLASSIFIER @ +1m — V_A T0 + filter mid + V4 stack")
    print("=" * 78)

    if not HAS_SKLEARN and not HAS_LGB:
        print("FATAL: neither sklearn nor lightgbm available")
        sys.exit(1)

    # Load attribution data filtered to +1m
    df = load_attribution_at_1m()

    # Map class names to short codes (the saved attribution uses long
    # names like "1_good_runner")
    class_map = {
        "1_good_runner": "C1",
        "2_good_normal_win": "C2",
        "3_v4_false_exit": "C3",
        "4_v4_true_save": "C4",
        "5_v4_missed_loser": "C5",
    }
    df["cls"] = df["class"].map(class_map)

    # Sanity check feature columns present
    missing = [f for f in FEATURES if f not in df.columns]
    if missing:
        print(f"FATAL: missing features in attribution parquet: {missing}")
        sys.exit(1)

    # CAUSALITY GUARDRAIL: print the feature set we will use
    print(f"\nUsing {len(FEATURES)} features (all from +1m only):")
    for f in FEATURES: print(f"  {f}")

    # Verify training never sees outcome-derived inputs
    forbidden = ["final_mfe_atr", "running_mfe", "running_mae",
                  "net_pnl", "hold_s", "exit_price", "v4_pnl",
                  "v4_fired", "class", "cls"]
    for f in FEATURES:
        if f in forbidden:
            print(f"FATAL CAUSALITY: feature {f} is outcome-derived")
            sys.exit(1)

    # Build train (2024+2025) and holdout (2026) sets
    train = df[(df["year"].isin([2024, 2025]))
                 & (df["cls"].isin(["C1", "C5"]))].copy()
    holdout = df[df["year"] == 2026].copy()
    full_eval = df.copy()
    print(f"\nTrain set: {len(train):,} (C1+C5 in 2024+2025)")
    print(f"  C1 (label 0): {(train['cls'] == 'C1').sum():,}")
    print(f"  C5 (label 1): {(train['cls'] == 'C5').sum():,}")
    print(f"Holdout: {len(holdout):,} (all 2026 trades, all classes)")

    train["label"] = (train["cls"] == "C5").astype(int)
    X_train = train[FEATURES].copy()
    y_train = train["label"].values

    # Drop any rows with NaN features (rare — incomplete +1m windows)
    mask = X_train.notna().all(axis=1)
    X_train = X_train[mask]
    y_train = y_train[mask.values]
    train = train[mask].copy()
    print(f"  After NaN drop: {len(X_train):,} train rows")

    # ---------------- Train models ----------------
    models = {}
    if HAS_SKLEARN:
        scaler = StandardScaler().fit(X_train)
        X_train_s = scaler.transform(X_train)
        lr = LogisticRegression(max_iter=2000, C=1.0,
                                    class_weight="balanced",
                                    random_state=42).fit(X_train_s, y_train)
        train_proba_lr = lr.predict_proba(X_train_s)[:, 1]
        try:
            auc = roc_auc_score(y_train, train_proba_lr)
        except Exception:
            auc = float("nan")
        print(f"\nLR train AUC: {auc:.3f}")
        models["LR"] = (lr, scaler)

    if HAS_LGB:
        lgb_model = lgb.LGBMClassifier(
            max_depth=3,
            n_estimators=100,
            learning_rate=0.05,
            num_leaves=7,
            min_child_samples=50,
            class_weight="balanced",
            random_state=42,
            n_jobs=1,
            verbose=-1,
        )
        lgb_model.fit(X_train.values, y_train)
        train_proba_lgb = lgb_model.predict_proba(X_train.values)[:, 1]
        try:
            auc_l = roc_auc_score(y_train, train_proba_lgb)
        except Exception:
            auc_l = float("nan")
        print(f"LGBM train AUC: {auc_l:.3f}")
        models["LGB"] = lgb_model

    # ---------------- Predict on full filtered population ----------------
    eval_data = full_eval.copy()
    eval_mask = eval_data[FEATURES].notna().all(axis=1)
    eval_data = eval_data[eval_mask].copy()
    print(f"\nFull eval set: {len(eval_data):,} trades")

    for name, m in models.items():
        if name == "LR":
            lr, scaler = m
            eval_data[f"prob_{name}"] = lr.predict_proba(
                scaler.transform(eval_data[FEATURES]))[:, 1]
        else:
            eval_data[f"prob_{name}"] = m.predict_proba(
                eval_data[FEATURES].values)[:, 1]

    # ---------------- Compute +1m fill prices AND v4_pnl ----------------
    # The attribution parquet has v4_fired but NOT v4_pnl. Per audit
    # finding, recompute v4_pnl on-the-fly so the V4-only and stack
    # reporting are correct.
    print(f"\nComputing +1m fill prices and V4 alt-fills from bars...")
    bars_by_year = {y: load_year_bars(y) for y in (2024, 2025, 2026)}
    # Pre-extract numpy arrays per year for speed
    arrs = {}
    for yr, b in bars_by_year.items():
        arrs[yr] = (
            b.index.astype("int64").to_numpy(),
            b["open"].values.astype(np.float64),
            b["high"].values.astype(np.float64),
            b["low"].values.astype(np.float64),
            b["close"].values.astype(np.float64),
        )

    fill_at_1m = []
    v4_pnl_recon = []
    for _, tr in eval_data.iterrows():
        yr = int(tr["year"])
        ts_idx, opens, highs, lows, closes = arrs[yr]
        entry_ts = int(tr["entry_ts"])
        exit_ts = int(tr["exit_ts"])
        direction = int(tr["direction"])
        atr = float(tr["atr"])
        fill_px = float(tr["fill_price"])

        # +1m fill price
        cp_ts = entry_ts + 60 * 1_000_000_000
        if cp_ts >= exit_ts:
            fill_at_1m.append(np.nan)
        else:
            fill_at_1m.append(fill_open_at(cp_ts, ts_idx, opens))

        # V4: candidate at +3m (unr<-50 AND mfe<0.25), confirm at +4m
        # (unr<0 AND mfe<0.35 AND xfast_net_move<0). Exit at +4m fill.
        # If V4 didn't fire, v4_pnl = baseline (net_pnl).
        if not bool(tr["v4_fired"]):
            v4_pnl_recon.append(float(tr["net_pnl"]))
            continue
        # Compute the +4m fill price
        ts_4m = entry_ts + 240 * 1_000_000_000
        if ts_4m >= exit_ts:
            v4_pnl_recon.append(float(tr["net_pnl"]))
            continue
        fp4 = fill_open_at(ts_4m, ts_idx, opens)
        v4_pnl_recon.append(compute_alt_pnl(direction, fill_px, fp4))

    eval_data["fill_at_1m"] = fill_at_1m
    eval_data["alt_pnl_1m"] = eval_data.apply(
        lambda r: compute_alt_pnl(int(r["direction"]),
                                       float(r["fill_price"]),
                                       r["fill_at_1m"]), axis=1)
    eval_data["v4_pnl"] = v4_pnl_recon
    eval_data["baseline_pnl"] = eval_data["net_pnl"]
    n_v4_fires = int(eval_data["v4_fired"].sum())
    print(f"  V4 fired on {n_v4_fires:,} trades; "
          f"v4_pnl reconstructed for all rows.")

    # ---------------- Threshold sweep on TRAIN ONLY ----------------
    print(f"\n{'='*78}")
    print("THRESHOLD SWEEP ON TRAIN (2024+2025, C1 cut <= 5%)")
    print(f"{'='*78}")
    thresholds = [round(t, 3) for t in np.arange(0.50, 1.0, 0.025)]
    selected = {}
    for name in models:
        prob_col = f"prob_{name}"
        train_eval = eval_data[(eval_data["year"].isin([2024, 2025]))
                                  & (eval_data["cls"].isin(["C1", "C5"]))]
        n_c1 = (train_eval["cls"] == "C1").sum()
        n_c5 = (train_eval["cls"] == "C5").sum()
        print(f"\n  Model {name} (n_C1={n_c1}, n_C5={n_c5} in train):")
        print(f"  {'thresh':>8} {'C1cut%':>7} {'C5catch%':>9} "
              f"{'precision':>10} {'recall':>7}")
        rows = []
        for th in thresholds:
            fired = (train_eval[prob_col] >= th)
            c1_cut = ((train_eval["cls"] == "C1") & fired).sum()
            c5_caught = ((train_eval["cls"] == "C5") & fired).sum()
            c1_cut_pct = 100 * c1_cut / max(n_c1, 1)
            c5_catch_pct = 100 * c5_caught / max(n_c5, 1)
            tp = c5_caught
            fp = c1_cut
            prec = tp / max(tp + fp, 1) * 100
            recall = c5_catch_pct
            rows.append({"thresh": th, "c1_cut_pct": c1_cut_pct,
                          "c5_catch_pct": c5_catch_pct,
                          "precision": prec, "recall": recall})
            print(f"  {th:>8.3f} {c1_cut_pct:>+6.1f}% {c5_catch_pct:>+8.1f}% "
                  f"{prec:>9.1f}% {recall:>+6.1f}%")

        # Find LARGEST threshold (most aggressive C5-catching) where
        # C1 cut <= 5%
        valid = [r for r in rows if r["c1_cut_pct"] <= 5.0]
        if not valid:
            print(f"  [{name}] No threshold meets C1 cut <= 5% — most "
                  f"conservative (highest threshold) shown above")
            sel = max(rows, key=lambda r: r["thresh"])
        else:
            # Of those passing the gate, pick the one with highest C5 catch
            sel = max(valid, key=lambda r: r["c5_catch_pct"])
        print(f"  [{name}] SELECTED threshold={sel['thresh']:.3f}  "
              f"(train C1 cut {sel['c1_cut_pct']:.1f}%, "
              f"C5 catch {sel['c5_catch_pct']:.1f}%)")
        selected[name] = sel["thresh"]

    # ---------------- Apply threshold to all data ----------------
    for name, th in selected.items():
        prob_col = f"prob_{name}"
        eval_data[f"{name}_fires"] = eval_data[prob_col] >= th

    # ---------------- Stack with V4 ----------------
    # If classifier fires (at +1m) AND has valid alt_pnl_1m → use that
    # Else if V4 fires → use V4 PnL (need v4_pnl col)
    # Else baseline
    has_v4_pnl = "v4_pnl" in eval_data.columns
    for name in models:
        ek_col = f"{name}_fires"
        # Early-kill only PnL
        eval_data[f"{name}_only_pnl"] = np.where(
            eval_data[ek_col] & eval_data["alt_pnl_1m"].notna(),
            eval_data["alt_pnl_1m"],
            eval_data["baseline_pnl"])
        # Stack with V4
        if has_v4_pnl:
            v4_col = "v4_pnl"
        else:
            # Fallback: if v4_fired, leave baseline (can't compute V4 alt)
            v4_col = "baseline_pnl"
        eval_data[f"{name}_stack_pnl"] = np.where(
            eval_data[ek_col] & eval_data["alt_pnl_1m"].notna(),
            eval_data["alt_pnl_1m"],
            np.where(eval_data["v4_fired"], eval_data[v4_col],
                       eval_data["baseline_pnl"]))

    # ---------------- Reporting: per-class catches ----------------
    print(f"\n{'='*78}")
    print("PER-CLASS CATCH RATES (full evaluation set)")
    print(f"{'='*78}")
    classes_ordered = ["C1", "C2", "C3", "C4", "C5"]
    print(f"\n  {'model/year':<14} " + "".join(
        f"{c:>9}" for c in classes_ordered))
    for name in models:
        ek_col = f"{name}_fires"
        for yr in (2024, 2025, 2026):
            line = f"  {name}/{yr:<10} "
            for c in classes_ordered:
                sub = eval_data[(eval_data["year"] == yr)
                                 & (eval_data["cls"] == c)]
                if not len(sub):
                    line += f"{'-':>9}"; continue
                fired = sub[ek_col].sum()
                pct = 100 * fired / len(sub)
                line += f"{pct:>+8.1f}%"
            print(line)

    # ---------------- Reporting: per-year stack metrics ----------------
    print(f"\n{'='*78}")
    print("PER-YEAR PERFORMANCE")
    print(f"{'='*78}")
    for yr in (2024, 2025, 2026):
        print(f"\n--- {yr} ---")
        sub = eval_data[eval_data["year"] == yr]
        if not len(sub): continue

        rows = []
        for label, col in [("baseline", "baseline_pnl"),
                            ("V4 only", "v4_pnl" if has_v4_pnl
                                else "baseline_pnl")]:
            m = yearly_metrics(sub, col)
            m["label"] = label
            rows.append(m)
        for name in models:
            m = yearly_metrics(sub, f"{name}_only_pnl")
            m["label"] = f"{name} EK only"
            rows.append(m)
            m = yearly_metrics(sub, f"{name}_stack_pnl")
            m["label"] = f"V4 + {name}"
            rows.append(m)

        print(f"  {'variant':<18} {'n':>5} {'WR%':>5} {'net':>10} "
              f"{'$/tr':>7} {'maxDD':>10} {'posM':>6}")
        baseline_net = rows[0]["net_pnl"]
        for r in rows:
            d = r["net_pnl"] - baseline_net if r["label"] != "baseline" else 0
            print(f"  {r['label']:<18} {int(r['n']):>5,} "
                  f"{r['wr_pct']:>4.1f}% {r['net_pnl']:>+9,.0f} "
                  f"{r['per_trade']:>+6.1f} {r['max_dd']:>+9,.0f} "
                  f"{int(r['pos_months']):>2}/"
                  f"{int(r['total_months']):>2}  Δ {d:>+8,.0f}")

    # ---------------- ALL YEARS rollup ----------------
    print(f"\n--- ALL YEARS rollup ---")
    for label, col in [("baseline", "baseline_pnl"),
                        ("V4 only", "v4_pnl" if has_v4_pnl
                            else "baseline_pnl")]:
        m = yearly_metrics(eval_data, col)
        print(f"  {label:<18} n={int(m['n']):>5,}  net ${m['net_pnl']:+,.0f}  "
              f"$/tr {m['per_trade']:+.1f}  maxDD ${m['max_dd']:+,.0f}")
    for name in models:
        for suffix in ("only_pnl", "stack_pnl"):
            label = f"{name} {'EK only' if suffix == 'only_pnl' else 'STACK'}"
            m = yearly_metrics(eval_data, f"{name}_{suffix}")
            print(f"  {label:<18} n={int(m['n']):>5,}  "
                  f"net ${m['net_pnl']:+,.0f}  $/tr {m['per_trade']:+.1f}  "
                  f"maxDD ${m['max_dd']:+,.0f}")

    # ---------------- 2026 deployment gate ----------------
    print(f"\n{'='*78}")
    print("2026 DEPLOYMENT GATE")
    print(f"{'='*78}")
    if has_v4_pnl:
        v4_2026 = eval_data[eval_data["year"] == 2026]["v4_pnl"].sum()
    else:
        v4_2026 = eval_data[eval_data["year"] == 2026]["baseline_pnl"].sum()
    for name in models:
        sub_2026 = eval_data[eval_data["year"] == 2026]
        c1_2026 = sub_2026[sub_2026["cls"] == "C1"]
        c1_cut_2026 = c1_2026[f"{name}_fires"].sum()
        c1_cut_2026_pct = 100 * c1_cut_2026 / max(len(c1_2026), 1)
        stack_2026 = sub_2026[f"{name}_stack_pnl"].sum()
        improves = stack_2026 > v4_2026
        c1_safe = c1_cut_2026_pct <= 5.0
        verdict = ("PASS" if improves and c1_safe
                     else f"FAIL ({'C1>5%' if not c1_safe else 'no improvement'})")
        print(f"  {name}: stack_2026=${stack_2026:+,.0f} "
              f"vs V4_2026=${v4_2026:+,.0f}  "
              f"C1 cut 2026={c1_cut_2026_pct:.1f}%  → {verdict}")

    # Save outputs
    eval_data.to_parquet(OUT / "ml_early_kill_results.parquet")
    print(f"\nWrote {OUT}/ml_early_kill_results.parquet")
    print(f"\n[done] runtime: {time.time()-t_start:.0f}s")


if __name__ == "__main__":
    main()
