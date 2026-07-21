"""Deep-dive on bar1_confirm + bar1-close + regime-exit survivor cells.

For each survivor (state_anchor, model_k, state_value):
  1. $/trade (net of $5 RT commission)
  2. mean ATR/trade
  3. median winner (ATR units)
  4. median loser (ATR units)
  5. 90th-pct winner (ATR units)
  6. max adverse excursion (MAE) — mean / median, ATR units
  7. holding time — mean / median (minutes)
  8. year-by-year $/trade and win rate
  9. long vs short split
  10. transition probabilities from entry to +1m, +5m, +10m, +30m
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
from numba import njit

NS = 1_000_000_000
PRODUCT = os.environ.get("PRODUCT", "NQ").upper()
OUT = Path("studies/regime_classification/results")
OOS_YEARS = (2023, 2024, 2025, 2026)
COMM = 5.0
NQ_MULT = 20.0
ES_MULT = 50.0
MULT = NQ_MULT if PRODUCT == "NQ" else ES_MULT

ONE_S = {y: f"data/raw/{PRODUCT}_v0_1s_{y}.parquet" for y in range(2019, 2026)}
ONE_S[2026] = f"data/raw/{PRODUCT}_v0_1s_2026_ytd.parquet"

# Survivor cells to inspect (model_k, state_moment_col, state_value, label)
# Top positive and worst negative cells from the prior sweep
SURVIVOR_CELLS = [
    # (model_k,    state_moment,            state, descriptive_label)
    ("kmeans_6",   "state_anchor_bar1",     4, "kmeans_6 bar1 s4 (+7.4pp)"),
    ("kmeans_5",   "state_anchor_bar1",     4, "kmeans_5 bar1 s4 (+7.1pp)"),
    ("gmm_5",      "state_anchor_flip",     4, "gmm_5 flip s4 (+5.9pp)"),
    ("hmm_4",      "state_anchor_flip",     3, "hmm_4 flip s3 (+5.6pp)"),
    ("hmm_3",      "state_anchor_flip",     2, "hmm_3 flip s2 (+5.3pp)"),
    ("hmm_3",      "state_anchor_bar1",     2, "hmm_3 bar1 s2 (+4.7pp)"),
    ("hmm_4",      "state_anchor_bar1",     3, "hmm_4 bar1 s3 (+4.6pp)"),
    # Negative filter-OUT cell
    ("gmm_6",      "state_anchor_bar1",     3, "gmm_6 bar1 s3 (-9.5pp)"),
]


@njit
def compute_mae(entry_ts_arr, exit_ts_arr, entry_px_arr, dir_arr, atr_arr,
                 ts_1s, h_1s, l_1s):
    """For each trade, compute MAE in ATR units during [entry_ts, exit_ts)."""
    n = len(entry_ts_arr)
    out = np.full(n, np.nan)
    for k in range(n):
        T0 = entry_ts_arr[k]
        T1 = exit_ts_arr[k]
        if T0 < 0 or T1 <= T0 or not np.isfinite(entry_px_arr[k]) \
                or atr_arr[k] <= 0:
            continue
        i_lo = np.searchsorted(ts_1s, T0, side="left")
        i_hi = np.searchsorted(ts_1s, T1, side="left")
        if i_hi <= i_lo:
            continue
        ep = entry_px_arr[k]
        d = dir_arr[k]
        if d == 1:
            seg_min = l_1s[i_lo:i_hi].min()
            mae_pts = ep - seg_min
        else:
            seg_max = h_1s[i_lo:i_hi].max()
            mae_pts = seg_max - ep
        if mae_pts < 0:
            mae_pts = 0.0
        out[k] = mae_pts / atr_arr[k]
    return out


def annotate_mae(cohort):
    parts = []
    for y in sorted(cohort["year"].unique()):
        sub = cohort[cohort["year"] == y]
        years_to_load = (y - 1, y, y + 1)
        bars_parts = []
        for yy in years_to_load:
            p = ONE_S.get(yy)
            if p and Path(p).exists():
                bars_parts.append(pd.read_parquet(
                    p, columns=["high", "low"]))
        bars = pd.concat(bars_parts).sort_index()
        bars = bars[~bars.index.duplicated(keep="first")]
        if bars.index.tz is None:
            bars.index = bars.index.tz_localize("UTC")
        ts_1s = bars.index.values.astype(np.int64)
        h_1s = bars["high"].to_numpy(np.float64)
        l_1s = bars["low"].to_numpy(np.float64)
        ets = (sub["entry_ts"].to_numpy(np.int64) + 60 * NS)  # bar1 close
        exts = sub["exit_ts"].to_numpy(np.int64)
        eps = sub["entry_px_bar1"].to_numpy(np.float64)
        drs = sub["signal_direction"].to_numpy(np.int64)
        ats = sub["entry_atr"].to_numpy(np.float64)
        mae = compute_mae(ets, exts, eps, drs, ats, ts_1s, h_1s, l_1s)
        addl = pd.DataFrame({"mae_atr": mae}, index=sub.index)
        parts.append(addl)
        print(f"  MAE {y}: {len(sub):,} ({addl['mae_atr'].notna().sum()} resolved)")
    return pd.concat(parts)


def lookup_state(target_ts_arr, state_ts_arr, state_arr):
    state_arr = np.asarray(state_arr).flatten().astype(np.int64)
    state_ts_arr = np.asarray(state_ts_arr).flatten().astype(np.int64)
    target_ts_arr = np.asarray(target_ts_arr).flatten().astype(np.int64)
    out = np.full(len(target_ts_arr), -1, dtype=np.int64)
    i = np.searchsorted(state_ts_arr, target_ts_arr, side="left")
    valid = (i < len(state_ts_arr)) & \
             (state_ts_arr[np.clip(i, 0, len(state_ts_arr)-1)]
              == target_ts_arr)
    out[valid] = state_arr[i[valid]]
    return out


def transition_table(entry_states, future_states, k_states):
    """Per entry-state, distribution of states at a future moment."""
    tbl = np.zeros((k_states, k_states + 1), dtype=np.int64)
    # last column = "-1" (no future state available)
    for es, fs in zip(entry_states, future_states):
        if es < 0:
            continue
        if fs < 0:
            tbl[es, k_states] += 1
        else:
            tbl[es, fs] += 1
    return tbl


def describe_cell(label, sub, mult):
    """Print all metrics for one cell."""
    print(f"\n{'─'*78}\n{label}  n={len(sub):,}\n{'─'*78}")
    if len(sub) == 0:
        print("  empty"); return None

    pnl_atr = sub["regime_pnl_atr_bar1"]
    pnl_dollar = pnl_atr * sub["entry_atr"] * mult - COMM
    sub = sub.copy()
    sub["pnl_dollar"] = pnl_dollar

    wins = pnl_atr > 0
    n_win = int(wins.sum())
    n_loss = int((pnl_atr <= 0).sum())

    print(f"  1. $/trade (net):         ${pnl_dollar.mean():+.2f}")
    print(f"  2. ATR/trade (mean):      {pnl_atr.mean():+.3f}")
    print(f"  3. median win (ATR):      "
          f"{pnl_atr[wins].median() if n_win else np.nan:+.3f}  (n={n_win:,})")
    print(f"  4. median loss (ATR):     "
          f"{pnl_atr[~wins].median() if n_loss else np.nan:+.3f}  (n={n_loss:,})")
    print(f"  5. 90th-pct winner:       "
          f"{pnl_atr[wins].quantile(0.9) if n_win else np.nan:+.3f}")
    if "mae_atr" in sub.columns:
        m = sub["mae_atr"].dropna()
        print(f"  6. MAE mean/median ATR:   "
              f"{m.mean():.3f} / {m.median():.3f}")
    print(f"  7. hold mean/med (min):   "
          f"{sub['hold_min_bar1'].mean():.1f} / "
          f"{sub['hold_min_bar1'].median():.1f}")
    print(f"  8. year-by-year:")
    print(f"     {'year':<6}{'n':>6}{'win%':>8}{'meanATR':>10}{'$/tr':>10}")
    for y in OOS_YEARS:
        g = sub[sub["year"] == y]
        if len(g) == 0:
            continue
        wr = (g["regime_pnl_atr_bar1"] > 0).mean()
        ma = g["regime_pnl_atr_bar1"].mean()
        dol = g["pnl_dollar"].mean()
        print(f"     {y:<6}{len(g):>6,}{wr:>7.1%}{ma:>+10.3f}{dol:>+10.2f}")
    print(f"  9. long vs short:")
    for d, dn in ((1, "long"), (-1, "short")):
        g = sub[sub["signal_direction"] == d]
        if len(g) == 0:
            continue
        wr = (g["regime_pnl_atr_bar1"] > 0).mean()
        ma = g["regime_pnl_atr_bar1"].mean()
        dol = g["pnl_dollar"].mean()
        print(f"     {dn:<6} n={len(g):>5,}  win={wr:.1%}  "
              f"meanATR={ma:+.3f}  $/tr=${dol:+.2f}")
    return sub


def main():
    t0 = time.time()
    print(f"PRODUCT={PRODUCT}")
    cohort = pd.read_parquet(OUT / f"bar1_deployable_state_{PRODUCT.lower()}.parquet")
    cohort = cohort[cohort["resolved"]].copy()
    print(f"  bar1_confirm + regime-exit resolved: {len(cohort):,}")

    print("Computing MAE per trade ...")
    mae_df = annotate_mae(cohort)
    cohort = cohort.join(mae_df["mae_atr"])

    states = pd.read_parquet(OUT / f"states_{PRODUCT.lower()}_1m.parquet")
    state_ts = states.index.values.astype(np.int64)

    # OOS only
    oos = cohort[cohort["year"].isin(OOS_YEARS)].copy()

    # Baseline (no state filter)
    print(f"\n{'='*78}\nBASELINE (bar1_confirm + bar1-close + regime-exit, OOS only)\n{'='*78}")
    describe_cell("BASELINE (all OOS)", oos, MULT)

    # For each survivor cell, filter to OOS rows in the state
    for model_k, anchor_col, st_val, label in SURVIVOR_CELLS:
        if model_k not in states.columns:
            print(f"\n[skip] {model_k} not in states parquet")
            continue
        state_arr = states[model_k].to_numpy(np.int64)
        anchor_ts = oos[anchor_col].to_numpy(np.int64)
        st = lookup_state(anchor_ts, state_ts, state_arr)
        sub = oos[st == st_val].copy()
        described = describe_cell(label, sub, MULT)

        # 10. Transition probabilities from entry state to future states
        if described is not None and len(sub) > 30:
            print(f"  10. Transitions from entry state (at bar1 close = "
                  f"open_ts of bar1) to FUTURE states:")
            # use the state at entry (bar1 close moment = state of bar with
            # open_ts = entry_ts)
            entry_state_anchor = sub["entry_ts"].to_numpy(np.int64)
            es = lookup_state(entry_state_anchor, state_ts, state_arr)
            k = int(state_arr.max()) + 1
            for lag_min, lag_label in ((1, "+1m"), (5, "+5m"),
                                         (10, "+10m"), (30, "+30m")):
                fut_anchor = sub["entry_ts"].to_numpy(np.int64) + lag_min * 60 * NS
                fs = lookup_state(fut_anchor, state_ts, state_arr)
                tbl = transition_table(es, fs, k)
                tot = tbl.sum(axis=1, keepdims=True)
                tot[tot == 0] = 1
                pct = tbl / tot
                # Just show the row corresponding to the cell's entry state
                row = pct[st_val]
                row_str = " ".join(
                    f"s{i}={row[i]*100:.0f}%"
                    for i in range(k))
                missing = row[k] * 100
                print(f"     {lag_label:<5}  entry={st_val}: {row_str}  "
                      f"(missing/no-data: {missing:.0f}%)")

    print(f"\n[done] {(time.time()-t0)/60:.1f} min")


if __name__ == "__main__":
    main()
