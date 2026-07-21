"""Rolling-model trainer for the live-style walk-forward salvage test.

Pipeline:
  1. Load the on-stream feature log (collected by the live strategy
     over 2020-2026 — every eligible candidate's 20 features).
  2. Compute label_T1 (V_A-confirmed flip at +60s) offline from 1m
     bars. Validate against the augmented candidate table on 2024-2026.
  3. Rolling train: for each deploy month M, train LightGBM on the
     prior TRAIN_MONTHS months only, early-stopping on a chrono-tail
     val split (the established walk-forward fold methodology).
     Recalibrate entry/rescore thresholds on the TRAIN window only.
  4. Save model_<YYYY-MM>.txt + a manifest with per-month thresholds.

Strict causality: model for deploy-month M sees ONLY months < M.
"""
from __future__ import annotations
import os, sys, json, time
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd
import lightgbm as lgb

FEAT_LOG_DIR = Path("studies/v_a_excursion_regime/results_v0/"
                       "live_feature_log")
FROZEN = Path("studies/v_a_excursion_regime/results_v0/frozen_t1")
AUG = ("studies/v_a_excursion_regime/results_v0/"
          "pre_flip_candidates_augmented.parquet")
ONE_S = {y: f"data/raw/NQ_v0_1s_{y}.parquet"
            for y in range(2020, 2026)}
ONE_S[2026] = "data/raw/NQ_v0_1s_2026_ytd.parquet"
OUT = Path("studies/v_a_excursion_regime/results_v0/rolling_models_6m")
TRAIN_MONTHS = 6
SEED = 42
VAL_FRAC = 0.20
NS = 1_000_000_000


def fit_es(X_tr, y_tr, X_val, y_val):
    m = lgb.LGBMClassifier(
        n_estimators=500, max_depth=6, num_leaves=31,
        learning_rate=0.05, feature_fraction=0.8,
        bagging_fraction=0.8, bagging_freq=5,
        min_data_in_leaf=50, random_state=SEED, n_jobs=-1,
        is_unbalance=True, verbose=-1)
    m.fit(X_tr, y_tr, eval_set=[(X_val, y_val)],
          callbacks=[lgb.early_stopping(50, verbose=False),
                      lgb.log_evaluation(0)])
    return m


def build_1m_bars(year):
    """Epoch-floor 1m bars from 1s raw data (matches strategy bucketing)."""
    b = pd.read_parquet(ONE_S[year],
                            columns=["open", "high", "low", "close"])
    b.index = pd.to_datetime(b.index, utc=True)
    ts = b.index.view("int64")
    bucket = (ts // (60 * NS)) * (60 * NS)
    g = pd.DataFrame({
        "bucket": bucket, "open": b["open"].values,
        "high": b["high"].values, "low": b["low"].values,
        "close": b["close"].values})
    agg = g.groupby("bucket").agg(
        open=("open", "first"), high=("high", "max"),
        low=("low", "min"), close=("close", "last"))
    # Audit W2: 1m buckets must be UTC-minute-aligned. If the raw file
    # index were in a non-UTC tz, floor boundaries would be offset and
    # the strategy's UTC-ns candidate timestamps would never match.
    assert int(agg.index[0]) % (60 * NS) == 0, (
        "1m bucket misaligned — check raw 1s file timezone")
    return agg  # indexed by bucket-open ts_ns


def compute_1m_regime(one_m):
    """Sticky 1m regime on the 1m bar series (matches strategy logic).

    ema3/ema9 of high & low (adjust=False), sticky:
      +1 if close>ema3_h and close>ema9_h
      -1 if close<ema3_l and close<ema9_l
      else carry previous.
    """
    h = one_m["high"].to_numpy()
    l = one_m["low"].to_numpy()
    c = one_m["close"].to_numpy()
    n = len(c)
    e3h = e9h = e3l = e9l = None
    reg = np.zeros(n, dtype=np.int8)
    cur = 0
    for i in range(n):
        if e3h is None:
            e3h, e9h, e3l, e9l = h[i], h[i], l[i], l[i]
        else:
            e3h = 0.5 * h[i] + 0.5 * e3h
            e9h = 0.2 * h[i] + 0.8 * e9h
            e3l = 0.5 * l[i] + 0.5 * e3l
            e9l = 0.2 * l[i] + 0.8 * e9l
        if c[i] > e3h and c[i] > e9h:
            cur = 1
        elif c[i] < e3l and c[i] < e9l:
            cur = -1
        reg[i] = cur
    return reg


def main():
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)

    feats = json.loads((FROZEN / "feature_list.json").read_text())

    # --- 1. Load feature log ---
    logs = sorted(FEAT_LOG_DIR.glob("feat_*.parquet"))
    if not logs:
        print("No feature-log parquets found; run collection first.")
        return
    df = pd.concat([pd.read_parquet(p) for p in logs],
                      ignore_index=True)
    df["dt"] = pd.to_datetime(df["close_ts_ns"], unit="ns", utc=True)
    df["ym"] = df["dt"].dt.tz_convert("America/Chicago").dt.to_period("M")
    df = df.sort_values("close_ts_ns").reset_index(drop=True)
    print(f"Feature log: {len(df):,} candidate rows  "
          f"{df['ym'].min()} .. {df['ym'].max()}")

    # --- 2. Labels: V_A-confirmed flip at +60s ---
    print("Computing label_T1 from 1m bars...")
    bars1m = {}
    for y in range(2020, 2027):
        try:
            bars1m[y] = build_1m_bars(y)
        except FileNotFoundError:
            pass
    one_m = pd.concat(bars1m.values()).sort_index()
    om_ts = one_m.index.values
    om_h = one_m["high"].values
    om_l = one_m["low"].values
    om_o = one_m["open"].values
    om_c = one_m["close"].values
    # STRICT label needs the actual 1m regime flip, not just the bar
    # pattern. Compute the sticky 1m regime over the full series.
    om_reg = compute_1m_regime(one_m)

    def bar_at(ts_ns):
        i = np.searchsorted(om_ts, ts_ns)
        if i < len(om_ts) and om_ts[i] == ts_ns:
            return i
        return -1

    labels = np.zeros(len(df), dtype=np.int8)
    for k in range(len(df)):
        cts = int(df["close_ts_ns"].iat[k])
        d = int(df["direction"].iat[k])
        fb = bar_at(cts)            # flip bar opens at close_ts
        b1 = bar_at(cts + 60 * NS)  # bar1 opens at close_ts+60s
        if fb < 0 or b1 < 0 or fb == 0:
            continue
        # STRICT: a genuine 1m regime flip TO d at the flip bar
        # (collector rule: new!=0, prev!=0, new!=prev).
        flip_to_d = (om_reg[fb] == d and om_reg[fb] != 0
                        and om_reg[fb - 1] != 0
                        and om_reg[fb] != om_reg[fb - 1])
        if not flip_to_d:
            continue
        if d == 1:
            hhll = om_h[b1] > om_h[fb]
            mom = om_c[b1] > om_o[b1]
        else:
            hhll = om_l[b1] < om_l[fb]
            mom = om_c[b1] < om_o[b1]
        labels[k] = 1 if (hhll and mom) else 0
    df["label_T1"] = labels
    print(f"  label-1 rate: {df['label_T1'].mean():.1%}")

    # Validate against augmented candidate table (2024-2026)
    aug = pd.read_parquet(AUG, columns=["close_ts_ns",
                                              "candidate_direction",
                                              "label_T1"])
    aug = aug.rename(columns={"candidate_direction": "direction",
                                    "label_T1": "label_aug"})
    chk = df.merge(aug, on=["close_ts_ns", "direction"], how="inner")
    if len(chk):
        agree = (chk["label_T1"] == chk["label_aug"]).mean()
        print(f"  label validation vs augmented table: "
              f"{agree:.2%} agree (n={len(chk):,})")

    # --- 3. Rolling train ---
    months = sorted(df["ym"].unique())
    print(f"\nRolling 6m-train / 1m-deploy:")
    manifest = {}
    n_done = 0
    for i, deploy_m in enumerate(months):
        if i < TRAIN_MONTHS:
            continue   # not enough prior history
        train_ms = months[i - TRAIN_MONTHS:i]
        tr = df[df["ym"].isin(train_ms)].sort_values("close_ts_ns")
        if len(tr) < 500 or tr["label_T1"].sum() < 20:
            continue
        n_val = int(len(tr) * VAL_FRAC)
        n_tro = len(tr) - n_val
        model = fit_es(
            tr.iloc[:n_tro][feats], tr.iloc[:n_tro]["label_T1"],
            tr.iloc[n_tro:][feats], tr.iloc[n_tro:]["label_T1"])
        # Audit C1: calibrate thresholds on the TRAIN-PROPER portion
        # only (exclude the early-stopping val tail, whose score
        # distribution is elevated by early-stopping selection).
        tr_scores = model.predict_proba(
            tr.iloc[:n_tro][feats])[:, 1]
        entry_thr = float(np.quantile(tr_scores, 0.90))
        rescore_thr = float(np.quantile(tr_scores, 0.50))
        mpath = OUT / f"model_{deploy_m}.txt"
        model.booster_.save_model(str(mpath))
        manifest[str(deploy_m)] = {
            "model": mpath.name,
            "entry_top10": entry_thr,
            "rescore_top50": rescore_thr,
            "train_months": [str(m) for m in train_ms],
            "n_train": int(len(tr)),
            "best_iter": int(model.booster_.best_iteration or
                                model.booster_.num_trees()),
        }
        n_done += 1
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"  trained {n_done} monthly models  "
          f"({months[TRAIN_MONTHS]} .. {months[-1]})")
    # Summary of best_iters + thresholds
    bi = [v["best_iter"] for v in manifest.values()]
    et = [v["entry_top10"] for v in manifest.values()]
    print(f"  best_iter: min {min(bi)} median "
          f"{int(np.median(bi))} max {max(bi)}")
    print(f"  entry_thr: min {min(et):.4f} median "
          f"{np.median(et):.4f} max {max(et):.4f}")
    print(f"\n[done] runtime: {time.time()-t0:.0f}s  -> {OUT}/")


if __name__ == "__main__":
    main()
