"""T-1 score as an OVERLAY on the already-confirmed V_A universe.

Question: among V_A-confirmed flips (a real, tradeable cohort), does
the pre-flip T-1 pressure score — computed one bar BEFORE the flip —
distinguish better continuation trades?

Universe: every V_A-confirmed flip 2020-2026 that had an eligible
pre-flip candidate (so a T-1 score exists). Strict V_A-confirm =
genuine 1m regime flip to d + bar1 HH/LL + momentum.

T-1 score: each confirmed flip's pre-flip candidate is re-scored with
the ROLLING model of its deploy month (fully OOS — model trained only
on prior 6 months). Confirmed flips before the first rolling month
(2020-07) are dropped.

Forward PnL: normal V_A mechanics — enter at the 1s open after bar1's
close (close_ts+120s), exit at the 1s open after the next 1m bar whose
regime is no longer d (regime-flip exit). $5 RT commission.

Output: confirmed flips bucketed by T-1 score quintile, split by year
2020-2026 — trade count, $/tr, win rate. (No no-flip split: the whole
universe is confirmed.)
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

sys.path.insert(0, str(project_root / "studies" / "v_a_excursion_regime"))
from rolling_train import build_1m_bars, compute_1m_regime

NS = 1_000_000_000
NQ_MULT = 20.0
COMMISSION = 5.0
FEAT_LOG_DIR = Path("studies/v_a_excursion_regime/results_v0/"
                       "live_feature_log")
ROLL_DIR = Path("studies/v_a_excursion_regime/results_v0/"
                   "rolling_models_6m")
FROZEN = Path("studies/v_a_excursion_regime/results_v0/frozen_t1")
ONE_S = {y: f"data/raw/NQ_v0_1s_{y}.parquet" for y in range(2020, 2026)}
ONE_S[2026] = "data/raw/NQ_v0_1s_2026_ytd.parquet"


def main():
    t0 = time.time()
    feats = json.loads((FROZEN / "feature_list.json").read_text())

    # --- feature log (pre-flip candidates, 2020-2026) ---
    df = pd.concat([pd.read_parquet(p)
                       for p in sorted(FEAT_LOG_DIR.glob("feat_*.parquet"))],
                      ignore_index=True)
    df["dt"] = pd.to_datetime(df["close_ts_ns"], unit="ns", utc=True)
    df["ym"] = df["dt"].dt.tz_convert("America/Chicago").dt.to_period("M")
    df["year"] = df["dt"].dt.year
    df = df.sort_values("close_ts_ns").reset_index(drop=True)
    print(f"Feature-log candidates: {len(df):,}")

    # --- 1m bars + regime for label + V_A PnL ---
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
    om_reg = compute_1m_regime(one_m)
    ts_to_idx = {int(t): i for i, t in enumerate(om_ts)}

    # --- 1s bars for fills ---
    s_ts, s_open = {}, {}
    for y, p in ONE_S.items():
        b = pd.read_parquet(p, columns=["open"])
        b.index = pd.to_datetime(b.index, utc=True)
        b = b.sort_index()
        s_ts[y] = b.index.view("int64")
        s_open[y] = b["open"].to_numpy()

    def open_at(ts):
        for y in (2020, 2021, 2022, 2023, 2024, 2025, 2026):
            arr = s_ts.get(y)
            if arr is None or len(arr) == 0:
                continue
            if arr[0] <= ts <= arr[-1] + NS:
                i = np.searchsorted(arr, ts, side="left")
                if i < len(arr):
                    return float(s_open[y][i])
        return np.nan

    # --- strict label + V_A forward PnL per candidate ---
    print("Labelling confirmed flips + V_A forward PnL...")
    is_conf = np.zeros(len(df), dtype=bool)
    va_pnl = np.full(len(df), np.nan)
    for k in range(len(df)):
        cts = int(df["close_ts_ns"].iat[k])
        d = int(df["direction"].iat[k])
        fb = ts_to_idx.get(cts, -1)            # flip bar opens at cts
        b1 = ts_to_idx.get(cts + 60 * NS, -1)  # bar1 opens at cts+60s
        if fb < 1 or b1 < 0:
            continue
        flip_to_d = (om_reg[fb] == d and om_reg[fb - 1] != 0
                        and om_reg[fb] != om_reg[fb - 1])
        if not flip_to_d:
            continue
        if d == 1:
            conf = om_h[b1] > om_h[fb] and om_c[b1] > om_o[b1]
        else:
            conf = om_l[b1] < om_l[fb] and om_c[b1] < om_o[b1]
        if not conf:
            continue
        is_conf[k] = True
        # V_A entry: 1s open after bar1 close (cts + 120s)
        entry_px = open_at(cts + 120 * NS)
        # V_A exit: first 1m bar after flip bar where regime != d
        exit_idx = -1
        j = fb + 1
        while j < len(om_reg):
            if om_reg[j] != d:
                exit_idx = j
                break
            j += 1
        if exit_idx < 0 or np.isnan(entry_px):
            continue
        exit_ts = int(om_ts[exit_idx]) + 60 * NS  # that bar's close
        exit_px = open_at(exit_ts)
        if np.isnan(exit_px):
            continue
        va_pnl[k] = (exit_px - entry_px) * d * NQ_MULT - COMMISSION
    df["is_confirmed"] = is_conf
    df["va_pnl"] = va_pnl
    conf = df[df["is_confirmed"] & df["va_pnl"].notna()].copy()
    print(f"  confirmed flips with V_A PnL: {len(conf):,}")
    print(f"  raw confirmed-universe $/tr: "
          f"${conf['va_pnl'].mean():+.2f}  "
          f"total ${conf['va_pnl'].sum():+,.0f}")

    # --- score each confirmed flip with its deploy-month rolling model ---
    print("Scoring with rolling models (OOS)...")
    manifest = json.loads((ROLL_DIR / "manifest.json").read_text())
    roll = {ym: lgb.Booster(model_file=str(ROLL_DIR / info["model"]))
            for ym, info in manifest.items()}
    conf["t1_score"] = np.nan
    for ym, sub in conf.groupby(conf["ym"].astype(str)):
        if ym not in roll:
            continue
        sc = roll[ym].predict(sub[feats])
        conf.loc[sub.index, "t1_score"] = sc
    scored = conf[conf["t1_score"].notna()].copy()
    print(f"  confirmed flips scored OOS (2020-07+): {len(scored):,}")

    # --- bucket by T-1 score quintile, overall + per year ---
    scored["q"] = pd.qcut(scored["t1_score"], 5,
                              labels=["Q1", "Q2", "Q3", "Q4", "Q5"])
    print(f"\n{'='*78}")
    print(f"CONFIRMED V_A FLIPS — forward PnL by pre-flip T-1 score "
          f"quintile")
    print(f"{'='*78}")
    print(f"  (Q1 = lowest pre-flip score, Q5 = highest)")
    print(f"\n  {'Quintile':<9} {'n':>6} {'$/tr':>9} {'total$':>11} "
          f"{'WR':>7} {'score rng':>18}")
    for q in ["Q1", "Q2", "Q3", "Q4", "Q5"]:
        s = scored[scored["q"] == q]
        print(f"  {q:<9} {len(s):>6} "
              f"${s['va_pnl'].mean():>+7.2f} "
              f"${s['va_pnl'].sum():>+9,.0f} "
              f"{(s['va_pnl']>0).mean():>6.1%} "
              f"  [{s['t1_score'].min():.4f},{s['t1_score'].max():.4f}]")

    # Per-year × quintile $/tr
    print(f"\n{'='*78}")
    print(f"PER-YEAR  —  $/tr by quintile  (n in parens)")
    print(f"{'='*78}")
    print(f"  {'Year':<6} {'Q1':>14} {'Q2':>14} {'Q3':>14} "
          f"{'Q4':>14} {'Q5':>14}")
    for yr in range(2020, 2027):
        ys = scored[scored["year"] == yr]
        if len(ys) == 0:
            continue
        cells = []
        for q in ["Q1", "Q2", "Q3", "Q4", "Q5"]:
            s = ys[ys["q"] == q]
            if len(s):
                cells.append(f"{s['va_pnl'].mean():+7.0f}({len(s):>3})")
            else:
                cells.append(f"{'-':>12}")
        print(f"  {yr:<6} " + " ".join(f"{c:>14}" for c in cells))

    # Top-half vs bottom-half (cleaner signal read)
    print(f"\n{'='*78}")
    print(f"TOP-HALF vs BOTTOM-HALF of pre-flip T-1 score, per year")
    print(f"{'='*78}")
    med = scored["t1_score"].median()
    scored["half"] = np.where(scored["t1_score"] >= med, "top", "bot")
    print(f"  {'Year':<6} {'bot n':>6} {'bot $/tr':>10} "
          f"{'top n':>6} {'top $/tr':>10} {'top-bot':>9}")
    for yr in range(2020, 2027):
        ys = scored[scored["year"] == yr]
        if len(ys) == 0:
            continue
        b = ys[ys["half"] == "bot"]
        t = ys[ys["half"] == "top"]
        if len(b) and len(t):
            print(f"  {yr:<6} {len(b):>6} ${b['va_pnl'].mean():>+8.2f} "
                  f"{len(t):>6} ${t['va_pnl'].mean():>+8.2f} "
                  f"${t['va_pnl'].mean()-b['va_pnl'].mean():>+7.2f}")

    scored.to_parquet("studies/v_a_excursion_regime/results_v0/"
                          "t1_overlay_confirmed.parquet", index=False)
    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
