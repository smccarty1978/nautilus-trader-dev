"""Aug-Oct 2024 long collapse forensic.

The robustness battery established:
  - 2024 long PnL: -$95.31/tr (n=129) — catastrophic, ENTIRE 2024 break
  - Damage time-clustered: Aug -$6,090, Sep -$3,635, Oct -$6,505 (≈ $16K of $9.9K total loss)
  - Jan-May 2024 longs were POSITIVE: +$7,930 cumulative
  - 2024 shorts were FINE: +$14.57/tr (n=163)

Question: what changed in Aug-Oct 2024 that broke longs (but not shorts)?

Decompose 2024 longs into 3 periods:
  PRE  = 2024-01 → 2024-07
  CRASH= 2024-08 → 2024-10  (the cluster)
  POST = 2024-11 → 2024-12

Compare against controls:
  2024 shorts (full year)
  2025 longs (full year)

Compute per cohort:
  - n, WR, $/tr, mean ATR, mean state_dur_before
  - Exit reason mix (PT vs regime_flip)
  - Time-of-day distribution (et_hour bucket)
  - MFE/MAE from 1s walk (entry -> regime/PT exit)
  - Hold time distribution
  - State-3 population character (occupancy, rv_300s, range_atr_60s in each period)

Goal: surface the distributional shift that explains the long-side collapse.
"""
from __future__ import annotations
import os, sys
from pathlib import Path

import numpy as np
import pandas as pd
from numba import njit

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

NQ_MULT = 20.0
COMM = 5.0
NS_PER_S = 1_000_000_000
RES = Path("backtests/hmm_state_filtered/results")
STATES = Path("studies/regime_classification/results/states_nq_1m.parquet")
FEATS  = Path("studies/regime_classification/results/features_nq_1m.parquet")
ONE_S = {y: f"data/raw/NQ_v0_1s_{y}.parquet" for y in range(2019, 2026)}
ONE_S[2026] = "data/raw/NQ_v0_1s_2026_ytd.parquet"

PRE_MO   = ["2024-01","2024-02","2024-03","2024-04","2024-05","2024-06","2024-07"]
CRASH_MO = ["2024-08","2024-09","2024-10"]
POST_MO  = ["2024-11","2024-12"]


@njit
def walk_mfe_mae(entry_ts, exit_ts, entry_px, dir_arr, atr_arr,
                  ts_1s, h_1s, l_1s):
    n = len(entry_ts)
    mfe = np.full(n, np.nan)
    mae = np.full(n, np.nan)
    for k in range(n):
        T0 = entry_ts[k]; Tx = exit_ts[k]
        ep = entry_px[k]; d = dir_arr[k]; atr = atr_arr[k]
        if T0 < 0 or Tx <= T0 or atr <= 0:
            continue
        i_lo = np.searchsorted(ts_1s, T0, side="left")
        i_hi = np.searchsorted(ts_1s, Tx, side="left")
        if i_hi <= i_lo:
            continue
        best_mfe = 0.0
        best_mae = 0.0
        for j in range(i_lo, i_hi):
            h = h_1s[j]; l = l_1s[j]
            if d == 1:
                pos = h - ep
                neg = ep - l
            else:
                pos = ep - l
                neg = h - ep
            if pos > best_mfe: best_mfe = pos
            if neg > best_mae: best_mae = neg
        mfe[k] = best_mfe / atr
        mae[k] = best_mae / atr
    return mfe, mae


def load_trades_with_walk(years):
    """Load NT P4 trades for given years; walk 1s for MFE/MAE."""
    out = []
    for y in years:
        p = RES / f"nq_hmm_4_s3_pt2p0_{y}/trades.parquet"
        if not p.exists():
            continue
        tr = pd.read_parquet(p)
        if not len(tr):
            continue
        one_s_p = ONE_S.get(y)
        if not (one_s_p and Path(one_s_p).exists()):
            continue
        bars = pd.read_parquet(one_s_p, columns=["high", "low"])
        if bars.index.tz is None:
            bars.index = bars.index.tz_localize("UTC")
        ts_1s = bars.index.values.astype(np.int64)
        h_1s = bars["high"].to_numpy(np.float64)
        l_1s = bars["low"].to_numpy(np.float64)
        e_ts = tr["entry_ts"].astype(np.int64).to_numpy()
        x_ts = tr["exit_ts"].astype(np.int64).to_numpy()
        e_px = tr["entry_px"].astype(np.float64).to_numpy()
        d    = tr["signal_direction"].astype(np.int64).to_numpy()
        atr  = tr["entry_atr"].astype(np.float64).to_numpy()
        mfe, mae = walk_mfe_mae(e_ts, x_ts, e_px, d, atr, ts_1s, h_1s, l_1s)
        tr["year"] = y
        tr["mfe_atr"] = mfe
        tr["mae_atr"] = mae
        tr["hold_min"] = (tr["exit_ts"] - tr["entry_ts"]) / 60e9
        tr["pnl_$"] = (tr["exit_px"] - tr["entry_px"]) * tr["signal_direction"] * NQ_MULT - COMM
        tr["pnl_atr"] = (tr["exit_px"] - tr["entry_px"]) * tr["signal_direction"] / tr["entry_atr"]
        tr["entry_dt"] = pd.to_datetime(tr["entry_ts"])
        tr["month"] = tr["entry_dt"].dt.to_period("M").astype(str)
        tr["et_hour_utc"] = tr["entry_dt"].dt.hour
        out.append(tr)
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def add_features(tr: pd.DataFrame, feat_cols):
    """Look up features at the flip-bar open ts (= entry_ts rounded down to 1m, then -60s)."""
    feats = pd.read_parquet(FEATS, columns=feat_cols)
    states = pd.read_parquet(STATES, columns=["hmm_4"])
    df = feats.join(states, how="inner")
    # For each trade, lookup time = entry_ts truncated to 60s boundary, then minus 60s (flip bar open)
    entry_ns = tr["entry_ts"].astype(np.int64).values
    flip_bar_open_ns = (entry_ns // (60 * NS_PER_S) * (60 * NS_PER_S)) - 60 * NS_PER_S
    flip_ts = pd.to_datetime(flip_bar_open_ns, utc=True)
    lookup = df.reindex(flip_ts)
    for c in feat_cols + ["hmm_4"]:
        tr[f"feat_{c}"] = lookup[c].values
    return tr


def state_dur_before(tr: pd.DataFrame):
    """For each trade, count consecutive state-3 bars ending at flip-bar."""
    df = pd.read_parquet(STATES, columns=["hmm_4"])
    state_ns = df.index.values.astype(np.int64)
    state_arr = df["hmm_4"].values.astype(np.int64)
    state_map = dict(zip(state_ns, state_arr))
    durs = []
    entry_ns = tr["entry_ts"].astype(np.int64).values
    for ts in entry_ns:
        flip_open_ns = (ts // (60 * NS_PER_S) * (60 * NS_PER_S)) - 60 * NS_PER_S
        dur = 0
        cur = flip_open_ns
        while state_map.get(cur, -1) == 3:
            dur += 1
            cur -= 60 * NS_PER_S
        durs.append(dur)
    tr["state_dur_before"] = durs
    return tr


def cohort_stats(tr: pd.DataFrame, label: str):
    if not len(tr):
        return {"label": label, "n": 0}
    pt = tr[tr["exit_reason"] == "PT"]
    rg = tr[tr["exit_reason"] == "regime_flip"]
    return {
        "label":         label,
        "n":             len(tr),
        "WR":            (tr["pnl_$"] > 0).mean(),
        "$/tr":          tr["pnl_$"].mean(),
        "total$":        tr["pnl_$"].sum(),
        "ATR_mean":      tr["entry_atr"].mean(),
        "ATR_med":       tr["entry_atr"].median(),
        "MFE_mean":      tr["mfe_atr"].mean(),
        "MAE_mean":      tr["mae_atr"].mean(),
        "hold_min":      tr["hold_min"].mean(),
        "PT_rate":       len(pt) / len(tr),
        "PT_avg$":       pt["pnl_$"].mean() if len(pt) else np.nan,
        "regime_avg$":   rg["pnl_$"].mean() if len(rg) else np.nan,
        "state_dur":     tr["state_dur_before"].mean() if "state_dur_before" in tr else np.nan,
        "rv_300s":       tr.get("feat_rv_300s", pd.Series()).mean(),
        "range_atr_60s": tr.get("feat_range_atr_60s", pd.Series()).mean(),
        "range_atr_300s":tr.get("feat_range_atr_300s", pd.Series()).mean(),
        "vol_expansion": tr.get("feat_vol_expansion", pd.Series()).mean(),
        "hour_med":      tr["et_hour_utc"].median(),
    }


def print_cohort(d):
    print(f"  {d['label']:<32}", end="")
    if d["n"] == 0:
        print("(empty)"); return
    print(f"n={d['n']:<4} WR={d['WR']:>5.1%} $/tr={d['$/tr']:>+8.1f} "
          f"tot$={d['total$']:>+9,.0f} | ATR={d['ATR_mean']:>6.2f} | "
          f"MFE={d['MFE_mean']:>+5.2f} MAE={d['MAE_mean']:>+5.2f} | "
          f"PT%={d['PT_rate']:>5.1%} | hold={d['hold_min']:>5.1f}m | "
          f"sdur={d['state_dur']:>4.1f} | rng60={d['range_atr_60s']:>+5.2f} | "
          f"rv300={d['rv_300s']:>+.5f}")


def report_2024_long_periods(tr_24: pd.DataFrame, tr_24_short: pd.DataFrame,
                              tr_25_long: pd.DataFrame):
    print(f"\n{'='*120}\n  2024 LONG cohort by period vs CONTROLS\n{'='*120}")
    pre   = tr_24[tr_24["month"].isin(PRE_MO)]
    crash = tr_24[tr_24["month"].isin(CRASH_MO)]
    post  = tr_24[tr_24["month"].isin(POST_MO)]

    print_cohort(cohort_stats(tr_25_long, "CTRL: 2025 longs"))
    print_cohort(cohort_stats(tr_24_short, "CTRL: 2024 shorts (full yr)"))
    print()
    print_cohort(cohort_stats(pre,   "2024 longs PRE  (Jan-Jul)"))
    print_cohort(cohort_stats(crash, "2024 longs CRASH (Aug-Oct)"))
    print_cohort(cohort_stats(post,  "2024 longs POST (Nov-Dec)"))


def report_2024_long_monthly(tr_24_long: pd.DataFrame):
    print(f"\n{'='*92}\n  2024 LONGS — monthly breakdown\n{'='*92}")
    print(f"  {'month':<10}{'n':>5}{'WR':>7}{'$/tr':>9}{'tot$':>11}"
          f"{'ATR':>8}{'MFE':>7}{'MAE':>7}{'PT%':>7}{'rng60':>8}")
    for m in sorted(tr_24_long["month"].unique()):
        sub = tr_24_long[tr_24_long["month"] == m]
        if not len(sub):
            continue
        pt = sub["exit_reason"].eq("PT").mean()
        marker = "  *CRASH" if m in CRASH_MO else ""
        print(f"  {m:<10}{len(sub):>5}{(sub['pnl_$']>0).mean():>7.1%}"
              f"{sub['pnl_$'].mean():>+9.1f}{sub['pnl_$'].sum():>+11,.0f}"
              f"{sub['entry_atr'].mean():>+8.2f}{sub['mfe_atr'].mean():>+7.2f}"
              f"{sub['mae_atr'].mean():>+7.2f}{pt:>7.1%}"
              f"{sub.get('feat_range_atr_60s', pd.Series([np.nan])).mean():>+8.2f}{marker}")


def report_population_state3(period_label: str, t0: pd.Timestamp, t1: pd.Timestamp):
    """Population character of state-3 bars within a time window."""
    feats = pd.read_parquet(FEATS, columns=["rv_30s","rv_300s","atr_1m",
                                              "range_atr_60s","range_atr_300s","year"])
    states = pd.read_parquet(STATES, columns=["hmm_4"])
    df = feats.join(states, how="inner")
    df = df[(df.index >= t0) & (df.index < t1)]
    if not len(df):
        return
    total = len(df)
    s3 = df[df["hmm_4"] == 3]
    print(f"  {period_label:<28}{total:>7,} bars  state3 share={len(s3)/total:>6.2%}  "
          f"atr_1m={s3['atr_1m'].mean():>6.2f}  "
          f"rng60={s3['range_atr_60s'].mean():>+5.2f}  "
          f"rng300={s3['range_atr_300s'].mean():>+5.2f}  "
          f"rv300={s3['rv_300s'].mean():>+.5f}")


def main():
    print("Loading 2024 + 2025 NT P4 trades, walking 1s for MFE/MAE...")
    tr = load_trades_with_walk([2024, 2025])
    print(f"  loaded {len(tr):,} trades")

    print("Joining causal features (at flip-bar open) + state_dur_before...")
    feat_cols = ["rv_30s","rv_300s","range_atr_60s","range_atr_300s",
                  "vol_expansion","atr_1m"]
    tr = add_features(tr, feat_cols)
    tr = state_dur_before(tr)

    tr_24_long  = tr[(tr["year"] == 2024) & (tr["signal_direction"] == 1)].copy()
    tr_24_short = tr[(tr["year"] == 2024) & (tr["signal_direction"] == -1)].copy()
    tr_25_long  = tr[(tr["year"] == 2025) & (tr["signal_direction"] == 1)].copy()

    print(f"  2024 longs: {len(tr_24_long)}, 2024 shorts: {len(tr_24_short)}, "
          f"2025 longs: {len(tr_25_long)}")

    report_2024_long_periods(tr_24_long, tr_24_short, tr_25_long)
    report_2024_long_monthly(tr_24_long)

    print(f"\n{'='*92}\n  POPULATION state-3 character by period (all bars)\n{'='*92}")
    print(f"  {'period':<28}{'bars':>9}{'':>15}{'atr_1m':>8}{'':>2}{'rng60':>5}"
          f"{'':>1}{'rng300':>6}{'':>1}{'rv300':>6}")
    report_population_state3("CTRL: 2025 full",
                              pd.Timestamp("2025-01-01", tz="UTC"),
                              pd.Timestamp("2026-01-01", tz="UTC"))
    report_population_state3("2024 PRE (Jan-Jul)",
                              pd.Timestamp("2024-01-01", tz="UTC"),
                              pd.Timestamp("2024-08-01", tz="UTC"))
    report_population_state3("2024 CRASH (Aug-Oct)",
                              pd.Timestamp("2024-08-01", tz="UTC"),
                              pd.Timestamp("2024-11-01", tz="UTC"))
    report_population_state3("2024 POST (Nov-Dec)",
                              pd.Timestamp("2024-11-01", tz="UTC"),
                              pd.Timestamp("2025-01-01", tz="UTC"))


if __name__ == "__main__":
    main()
