"""Phase 2 (Sub-Minute) — sub-minute flips (30s, 15s, 5s) with 5m HMM macro filter.

Universe : NT-detected sub-minute regime flips (30s, 15s, 5s) compiled from 1s bars.
Filter   : 5m macro HMM state looked up causally at flip moment T.
Exits    :
  A. Dynamic Regime Exit on target sub-minute timeframe.
  B. Symmetric Bracket Exit (1.0 ATR Target vs 1.0 ATR Stop) using:
     - The trigger timeframe's own ATR
     - The 30s ATR (as a commission-safety filter)
Transaction Frictions: $10 total cost per trade ($5 RT commission + $5 slippage).
"""
from __future__ import annotations
import os, sys, time
from pathlib import Path
import numpy as np
import pandas as pd
from numba import njit

NS = 1_000_000_000
ATR_PERIOD = 14
ALPHA_EMA3 = 0.5
ALPHA_EMA9 = 0.2

PRODUCT = os.environ.get("PRODUCT", "NQ").upper()
PRODUCT_DATA = {
    "NQ": {"raw": {**{y: f"data/raw/NQ_v0_1s_{y}.parquet"
                       for y in range(2019, 2026)},
                    2026: "data/raw/NQ_v0_1s_2026_ytd.parquet"},
            "mult": 20.0},
    "ES": {"raw": {**{y: f"data/raw/ES_v0_1s_{y}.parquet"
                       for y in range(2019, 2026)},
                    2026: "data/raw/ES_v0_1s_2026_ytd.parquet"},
            "mult": 50.0},
}
PD = PRODUCT_DATA[PRODUCT]
OOS_YEARS = (2023, 2024, 2025, 2026)

@njit
def wilder_atr(h, l, c, period):
    n = len(c)
    atr = np.full(n, np.nan)
    if n < period:
        return atr
    tr_sum = 0.0
    for i in range(period):
        if i == 0:
            tr = h[i] - l[i]
        else:
            tr = max(h[i] - l[i], abs(h[i] - c[i-1]), abs(l[i] - c[i-1]))
        tr_sum += tr
    atr[period - 1] = tr_sum / period
    for i in range(period, n):
        tr = max(h[i] - l[i], abs(h[i] - c[i-1]), abs(l[i] - c[i-1]))
        atr[i] = (atr[i-1] * (period - 1) + tr) / period
    return atr

@njit
def compute_regime(h, l, c):
    n = len(c)
    reg = np.zeros(n, dtype=np.int64)
    e3h = e9h = e3l = e9l = 0.0
    cur = 0
    for i in range(n):
        if i == 0:
            e3h = h[i]; e9h = h[i]; e3l = l[i]; e9l = l[i]
        else:
            e3h = ALPHA_EMA3 * h[i] + (1.0 - ALPHA_EMA3) * e3h
            e9h = ALPHA_EMA9 * h[i] + (1.0 - ALPHA_EMA9) * e9h
            e3l = ALPHA_EMA3 * l[i] + (1.0 - ALPHA_EMA3) * e3l
            e9l = ALPHA_EMA9 * l[i] + (1.0 - ALPHA_EMA9) * e9l
        new_reg = cur
        if c[i] > e3h and c[i] > e9h:
            new_reg = 1
        elif c[i] < e3l and c[i] < e9l:
            new_reg = -1
        reg[i] = new_reg
        cur = new_reg
    return reg

@njit
def detect_flips(m_ts, reg):
    """Detect indices of new regime flips (where reg changes to a non-zero state)."""
    flips = []
    for i in range(1, len(reg)):
        if reg[i] != reg[i-1] and reg[i] != 0:
            flips.append(i)
    return np.array(flips)

@njit
def race_bracket(start_ts, anchor_px, d, atr, ts_1s, h_1s, l_1s):
    if not (anchor_px == anchor_px) or atr <= 0:
        return -1
    j = np.searchsorted(ts_1s, start_ts, side="left")
    if d == 1:
        tgt, stp = anchor_px + atr, anchor_px - atr
    else:
        tgt, stp = anchor_px - atr, anchor_px + atr
    while j < len(ts_1s):
        h, l = h_1s[j], l_1s[j]
        if d == 1:
            ht, hs = h >= tgt, l <= stp
        else:
            ht, hs = l <= tgt, h >= stp
        if ht and hs:
            return 0
        if ht:
            return 1
        if hs:
            return 0
        j += 1
    return -1

def aggregate_bars(bars_1s, wsec):
    ts = bars_1s.index.values.astype(np.int64)
    bucket = (ts // (wsec * NS)) * (wsec * NS)
    g = pd.DataFrame({
        "b": bucket,
        "o": bars_1s["open"].values,
        "h": bars_1s["high"].values,
        "l": bars_1s["low"].values,
        "c": bars_1s["close"].values,
    })
    return g.groupby("b").agg(
        o=("o", "first"), h=("h", "max"),
        l=("l", "min"), c=("c", "last")
    )

def lookup_state_causal(target_ts_arr, state_ts_arr, state_arr, bar_duration_ns):
    state_arr = np.asarray(state_arr).flatten().astype(np.int64)
    state_ts_arr = np.asarray(state_ts_arr).flatten().astype(np.int64)
    target_ts_arr = np.asarray(target_ts_arr).flatten().astype(np.int64)
    
    query_ts = target_ts_arr - bar_duration_ns
    idx = np.searchsorted(state_ts_arr, query_ts, side="right") - 1
    
    out = np.full(len(target_ts_arr), -1, dtype=np.int64)
    valid = (idx >= 0) & (idx < len(state_ts_arr))
    out[valid] = state_arr[idx[valid]]
    return out

def run_study_for_wsec(wsec, bars_1s, df_30s_atr, states_5m, state_ts_5m):
    t0 = time.time()
    print(f"\n{'='*60}\nTrigger Timeframe: {wsec}s\n{'='*60}")
    
    # 1. Aggregate bars
    agg = aggregate_bars(bars_1s, wsec)
    m_ts = agg.index.values.astype(np.int64)
    m_o = agg["o"].to_numpy(np.float64)
    m_h = agg["h"].to_numpy(np.float64)
    m_l = agg["l"].to_numpy(np.float64)
    m_c = agg["c"].to_numpy(np.float64)
    
    # 2. Compute EMA regimes & flips
    reg = compute_regime(m_h, m_l, m_c)
    flip_idxs = detect_flips(m_ts, reg)
    print(f"  Aggregated {len(agg):,} bars. Detected {len(flip_idxs):,} flips.")
    if len(flip_idxs) == 0:
        return
        
    # 3. Calculate ATR
    m_atr = wilder_atr(m_h, m_l, m_c, ATR_PERIOD)
    
    # 4. Build trade cohort dataframe
    flip_ts = m_ts[flip_idxs]
    flip_dir = reg[flip_idxs]
    flip_px = m_c[flip_idxs]
    flip_atr = m_atr[flip_idxs]
    
    df = pd.DataFrame(index=pd.to_datetime(flip_ts, unit="ns", utc=True))
    df.index.name = "entry_ts"
    df["year"] = df.index.year
    df["direction"] = flip_dir
    df["entry_px"] = flip_px
    df["own_atr"] = flip_atr
    
    # Map 30s ATR for commission-safety
    if wsec == 30:
        df["safety_atr"] = flip_atr
    else:
        # Interpolate 30s ATR to sub-minute flip timestamps
        idx_30s = df_30s_atr.index.values.astype(np.int64)
        atr_30s = df_30s_atr.values
        pos = np.searchsorted(idx_30s, flip_ts) - 1
        valid = (pos >= 0) & (pos < len(atr_30s))
        safety_atr = np.full(len(flip_ts), np.nan)
        safety_atr[valid] = atr_30s[pos[valid]]
        df["safety_atr"] = safety_atr
        
    # Drop rows with NaN ATR
    df = df.dropna().copy()
    print(f"  Valid flips with full ATR: {len(df):,}")
    
    # 5. Load 1s bars for racing bracket outcomes
    ts_1s = bars_1s.index.values.astype(np.int64)
    h_1s = bars_1s["high"].to_numpy(np.float64)
    l_1s = bars_1s["low"].to_numpy(np.float64)
    
    # Compute exits
    print("  Simulating exit outcomes...")
    n = len(df)
    ets = df.index.values.astype(np.int64)
    drs = df["direction"].values
    pxs = df["entry_px"].values
    own_atrs = df["own_atr"].values
    saf_atrs = df["safety_atr"].values
    
    hit_own = np.full(n, -1)
    hit_saf = np.full(n, -1)
    exit_reg_ts = np.full(n, -1, dtype=np.int64)
    exit_reg_px = np.full(n, np.nan)
    
    # Map index to speed up regime scan
    idx_map = {int(t): i for i, t in enumerate(m_ts)}
    
    for k in range(n):
        T = int(ets[k])
        d = int(drs[k])
        px = float(pxs[k])
        
        # Race own ATR
        hit_own[k] = race_bracket(T, px, d, float(own_atrs[k]), ts_1s, h_1s, l_1s)
        
        # Race safety (30s) ATR
        hit_saf[k] = race_bracket(T, px, d, float(saf_atrs[k]), ts_1s, h_1s, l_1s)
        
        # Scan regime exit
        fb_i = idx_map.get(T, -1)
        if fb_i >= 0:
            for j in range(fb_i + 1, len(reg)):
                if reg[j] != d and reg[j] != 0:
                    exit_reg_ts[k] = m_ts[j] + wsec * NS
                    exit_reg_px[k] = m_c[j]
                    break
                    
    df["hit_own"] = hit_own
    df["hit_saf"] = hit_saf
    df["exit_reg_ts"] = exit_reg_ts
    df["exit_reg_px"] = exit_reg_px
    
    df["win_own"] = (df["hit_own"] == 1).astype(int)
    df["win_saf"] = (df["hit_saf"] == 1).astype(int)
    df["win_reg"] = ((df["exit_reg_px"] - df["entry_px"]) * df["direction"] > 0).astype(int)
    
    df["resolved_own"] = df["hit_own"] >= 0
    df["resolved_saf"] = df["hit_saf"] >= 0
    df["resolved_reg"] = df["exit_reg_ts"] > 0
    
    # 6. Apply HMM Macro primary filter (hmm_3 state 2)
    state_arr = states_5m["hmm_3"].to_numpy(np.int64)
    df["macro_state"] = lookup_state_causal(ets, state_ts_5m, state_arr, 300 * NS)
    
    # 7. Evaluate and report OOS Performance (2023-2026)
    for exit_name, resolved_col, win_col, atr_col in (
        ("Own ATR Bracket", "resolved_own", "win_own", "own_atr"),
        ("30s ATR Safety Bracket", "resolved_saf", "win_saf", "safety_atr"),
        ("Regime Exit", "resolved_reg", "win_reg", "own_atr")
    ):
        sub = df[df[resolved_col] & (df["macro_state"] == 2) & df["year"].isin(OOS_YEARS)]
        total_sub = df[df[resolved_col] & df["year"].isin(OOS_YEARS)]
        
        if len(sub) == 0:
            continue
            
        base_win = total_sub[win_col].mean()
        filt_win = sub[win_col].mean()
        lift = (filt_win - base_win) * 100
        
        # Calculate EV in points and dollars
        if "Bracket" in exit_name:
            # Symmetrically, wins net +1 ATR, losses cost -1 ATR
            # Mean PnL in ATR units = Win Rate - Loss Rate = 2 * Win Rate - 1
            mean_atr_pnl = 2 * filt_win - 1
            mean_pts_pnl = mean_atr_pnl * sub[atr_col].mean()
            net_dollars = mean_pts_pnl * PD["mult"] - 10.0  # Apply $10 friction
        else:
            # Regime exit is dynamic
            pnl_pts = (sub["exit_reg_px"] - sub["entry_px"]) * sub["direction"]
            mean_pts_pnl = pnl_pts.mean()
            net_dollars = mean_pts_pnl * PD["mult"] - 10.0
            
        print(f"\n    Exit: {exit_name}")
        print(f"      OOS Pool size : {len(sub):,} trades (vs {len(total_sub):,} unfiltered)")
        print(f"      Win Rate      : {filt_win:.1%} (base {base_win:.1%}, lift {lift:+.1f}pp)")
        print(f"      Net PnL/Trade : ${net_dollars:+.2f} (after $10 RT commission/slippage)")
        
        # Year-by-year detail
        yr_strs = []
        for y in OOS_YEARS:
            g = sub[sub["year"] == y]
            if len(g) > 0:
                y_win = g[win_col].mean()
                if "Bracket" in exit_name:
                    y_pts = (2 * y_win - 1) * g[atr_col].mean()
                else:
                    y_pts = ((g["exit_reg_px"] - g["entry_px"]) * g["direction"]).mean()
                y_dlr = y_pts * PD["mult"] - 10.0
                yr_strs.append(f"{y}:{len(g)}/${y_dlr:+.1f}")
        print(f"      Year-by-year  : " + "  ".join(yr_strs))
        
    print(f"  [done {wsec}s] {(time.time()-t0)/60:.2f} min")

def main():
    t0 = time.time()
    years = list(range(2019, 2027))
    print(f"PRODUCT={PRODUCT}")
    print("Loading 1s bars for 2019-2026...")
    parts = []
    for y in years:
        p = PD["raw"].get(y)
        if p and Path(p).exists():
            parts.append(pd.read_parquet(
                p, columns=["open", "high", "low", "close"]))
    bars = pd.concat(parts).sort_index()
    bars = bars[~bars.index.duplicated(keep="first")]
    if bars.index.tz is None:
        bars.index = bars.index.tz_localize("UTC")
    print(f"  Loaded {len(bars):,} 1s bars. ({time.time()-t0:.0f}s)")
    
    # Pre-compute 30s ATR to use as safety ATR for 15s and 5s triggers
    print("Pre-computing 30s ATR...")
    bars_30s = aggregate_bars(bars, 30)
    h_30s = bars_30s["h"].to_numpy(np.float64)
    l_30s = bars_30s["l"].to_numpy(np.float64)
    c_30s = bars_30s["c"].to_numpy(np.float64)
    atr_30s = pd.Series(wilder_atr(h_30s, l_30s, c_30s, ATR_PERIOD), index=bars_30s.index)
    
    # Load 5m macro HMM states
    states_5m = pd.read_parquet("studies/regime_classification/results/states_nq_5m.parquet")
    state_ts_5m = states_5m.index.values.astype(np.int64)
    
    # Run sub-minute timeframe overlay studies
    for wsec in (30, 15, 5):
        run_study_for_wsec(wsec, bars, atr_30s, states_5m, state_ts_5m)
        
    print(f"\nAll studies completed in {(time.time()-t0)/60:.2f} min")

if __name__ == "__main__":
    main()
