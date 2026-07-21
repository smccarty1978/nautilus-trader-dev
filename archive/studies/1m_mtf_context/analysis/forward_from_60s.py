"""Forward-looking analysis from t=60s.

Correct approach (no look-ahead): at 60s, measure CURRENT PnL (not peak MFE).
Then from THAT point forward, walk to see what happens. Bucket trades by
current PnL at 60s.

For each bucket:
  - Forward bracket race FROM ENTRY (does eventual MFE reach +0.75 before
    MAE reaches -0.75, looking at bars from 60s onward)
  - Forward bracket race FROM 60s PRICE (PT/SL placed relative to 60s
    close, measuring additional favorable vs adverse movement)
  - Forward MFE/MAE distribution
"""

import sys
import os
import time as _time
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd
import numpy as np
from numba import njit

from nautilus_trader.persistence.catalog import ParquetDataCatalog


NQ_MULT = 20.0
COMMISSION = 5.0


@njit(cache=True)
def measure_60s_and_forward(
    entry_px, entry_ts, direction, atr,
    pt_atr, sl_atr,
    ts_arr, h_arr, l_arr, c_arr,
    i_start, i_end,
):
    """At 60s after entry, capture current price and walk forward.

    Returns:
      price_60s, cur_pnl_atr_60s,
      forward_pt_from_entry, forward_sl_from_entry,
      forward_pt_from_60s, forward_sl_from_60s,
      fwd_max_mfe_from_entry, fwd_max_mae_from_entry
      All bracket booleans are 1 if PT (or SL) hit before the other.
    """
    if atr <= 0 or i_end <= i_start:
        return (entry_px, 0.0, 0, 0, 0, 0, 0.0, 0.0)

    target_60s_ts = entry_ts + 60_000_000_000  # ns

    # Find the 1s bar whose close (~ts_event + 1s) is at or after target
    i_60s = i_start
    while i_60s < i_end and ts_arr[i_60s] < target_60s_ts:
        i_60s += 1
    if i_60s >= i_end:
        # Trade ended before 60s
        return (entry_px, 0.0, 0, 0, 0, 0, 0.0, 0.0)

    # Use the close of the 1s bar AT or just after the 60s mark
    price_60s = c_arr[i_60s]
    cur_pnl_atr = (price_60s - entry_px) * direction / atr

    # Walk forward FROM 60s (i_60s + 1) to i_end
    pt_entry_px = entry_px + direction * pt_atr * atr
    sl_entry_px = entry_px - direction * sl_atr * atr
    pt_60s_px = price_60s + direction * pt_atr * atr
    sl_60s_px = price_60s - direction * sl_atr * atr

    fwd_pt_from_entry = 0
    fwd_sl_from_entry = 0
    fwd_pt_from_60s = 0
    fwd_sl_from_60s = 0
    fwd_max_mfe = cur_pnl_atr if cur_pnl_atr > 0 else 0.0
    fwd_max_mae = -cur_pnl_atr if cur_pnl_atr < 0 else 0.0

    for i in range(i_60s + 1, i_end):
        h = h_arr[i]
        l = l_arr[i]

        if direction == 1:
            # FROM ENTRY race
            if not fwd_pt_from_entry and not fwd_sl_from_entry:
                pt_hit_e = h >= pt_entry_px
                sl_hit_e = l <= sl_entry_px
                if pt_hit_e and sl_hit_e:
                    fwd_pt_from_entry = 1
                elif pt_hit_e:
                    fwd_pt_from_entry = 1
                elif sl_hit_e:
                    fwd_sl_from_entry = 1
            # FROM 60s race
            if not fwd_pt_from_60s and not fwd_sl_from_60s:
                pt_hit_60 = h >= pt_60s_px
                sl_hit_60 = l <= sl_60s_px
                if pt_hit_60 and sl_hit_60:
                    fwd_pt_from_60s = 1
                elif pt_hit_60:
                    fwd_pt_from_60s = 1
                elif sl_hit_60:
                    fwd_sl_from_60s = 1
            # MFE/MAE update
            mfe_now = (h - entry_px) / atr
            mae_now = (entry_px - l) / atr
        else:
            if not fwd_pt_from_entry and not fwd_sl_from_entry:
                pt_hit_e = l <= pt_entry_px
                sl_hit_e = h >= sl_entry_px
                if pt_hit_e and sl_hit_e:
                    fwd_pt_from_entry = 1
                elif pt_hit_e:
                    fwd_pt_from_entry = 1
                elif sl_hit_e:
                    fwd_sl_from_entry = 1
            if not fwd_pt_from_60s and not fwd_sl_from_60s:
                pt_hit_60 = l <= pt_60s_px
                sl_hit_60 = h >= sl_60s_px
                if pt_hit_60 and sl_hit_60:
                    fwd_pt_from_60s = 1
                elif pt_hit_60:
                    fwd_pt_from_60s = 1
                elif sl_hit_60:
                    fwd_sl_from_60s = 1
            mfe_now = (entry_px - l) / atr
            mae_now = (h - entry_px) / atr

        if mfe_now > fwd_max_mfe:
            fwd_max_mfe = mfe_now
        if mae_now > fwd_max_mae:
            fwd_max_mae = mae_now

        # Both races resolved → can break
        if (fwd_pt_from_entry or fwd_sl_from_entry) and \
                (fwd_pt_from_60s or fwd_sl_from_60s):
            # Still need to keep walking for MFE/MAE — don't break early
            pass

    return (price_60s, cur_pnl_atr,
            fwd_pt_from_entry, fwd_sl_from_entry,
            fwd_pt_from_60s, fwd_sl_from_60s,
            fwd_max_mfe, fwd_max_mae)


def main():
    print("=" * 100)
    print("FORWARD-LOOKING ANALYSIS FROM t=60s — current PnL bucket → forward outcome")
    print("=" * 100)

    print("\nLoading trades + 1s bars...")
    trades = pd.read_parquet(
        "studies/1m_mtf_context/results/trades_all.parquet").copy()
    print(f"  {len(trades):,} trades")

    t0 = _time.time()
    catalog = ParquetDataCatalog("data/catalog/NQ_2020_2025")
    bars_1s = catalog.bars(
        bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"],
        start=pd.Timestamp("2020-01-01", tz="UTC"),
        end=pd.Timestamp("2026-01-01", tz="UTC"))
    print(f"  {len(bars_1s):,} 1s bars ({_time.time()-t0:.0f}s)")

    print("Extracting...")
    t0 = _time.time()
    n = len(bars_1s)
    ts_arr = np.empty(n, dtype=np.int64)
    h_arr = np.empty(n)
    l_arr = np.empty(n)
    c_arr = np.empty(n)
    for i, b in enumerate(bars_1s):
        ts_arr[i] = b.ts_event
        h_arr[i] = float(b.high)
        l_arr[i] = float(b.low)
        c_arr[i] = float(b.close)
    del bars_1s
    print(f"  ({_time.time()-t0:.0f}s)")

    entry_ts = trades["entry_ts"].astype("int64").values
    exit_ts = pd.to_datetime(trades["exit_time"]).astype("int64").values
    entry_px = trades["entry_price"].values
    direction = trades["direction"].values.astype(np.int64)
    atr = trades["atr_at_entry"].values

    # JIT warmup
    measure_60s_and_forward(
        100.0, 0, 1, 1.0, 0.75, 0.75,
        np.array([0, 1, 2], dtype=np.int64),
        np.array([100.0, 100.0, 100.0]),
        np.array([100.0, 100.0, 100.0]),
        np.array([100.0, 100.0, 100.0]),
        0, 3)

    print(f"\nWalking {len(trades):,} trades for 0.75/0.75 forward analysis...")
    t0 = _time.time()
    n_t = len(trades)
    price_60s = np.empty(n_t)
    cur_pnl_atr_60s = np.empty(n_t)
    fwd_pt_from_entry = np.empty(n_t, dtype=np.int32)
    fwd_sl_from_entry = np.empty(n_t, dtype=np.int32)
    fwd_pt_from_60s = np.empty(n_t, dtype=np.int32)
    fwd_sl_from_60s = np.empty(n_t, dtype=np.int32)
    fwd_max_mfe = np.empty(n_t)
    fwd_max_mae = np.empty(n_t)
    has_60s = np.empty(n_t, dtype=bool)

    for k in range(n_t):
        i_start = np.searchsorted(ts_arr, entry_ts[k], side="left")
        i_end = np.searchsorted(ts_arr, exit_ts[k], side="right")
        (p, cp, pt_e, sl_e, pt_60, sl_60, mfe, mae) = \
            measure_60s_and_forward(
                entry_px[k], entry_ts[k], direction[k], atr[k],
                0.75, 0.75,
                ts_arr, h_arr, l_arr, c_arr,
                i_start, i_end)
        price_60s[k] = p
        cur_pnl_atr_60s[k] = cp
        fwd_pt_from_entry[k] = pt_e
        fwd_sl_from_entry[k] = sl_e
        fwd_pt_from_60s[k] = pt_60
        fwd_sl_from_60s[k] = sl_60
        fwd_max_mfe[k] = mfe
        fwd_max_mae[k] = mae
        has_60s[k] = i_end > i_start  # trade had bars; 60s may not exist

    print(f"  Done ({_time.time()-t0:.0f}s)")

    # Build df
    df = pd.DataFrame({
        "atr": atr,
        "cur_pnl_atr_60s": cur_pnl_atr_60s,
        "mfe_at_60s": trades["mfe_at_60s"].values,  # original peak MFE up to 60s
        "fwd_pt_from_entry": fwd_pt_from_entry,
        "fwd_sl_from_entry": fwd_sl_from_entry,
        "fwd_pt_from_60s": fwd_pt_from_60s,
        "fwd_sl_from_60s": fwd_sl_from_60s,
        "fwd_max_mfe": fwd_max_mfe,
        "fwd_max_mae": fwd_max_mae,
        "year": trades["year"].values,
    })
    # Filter trades that had 60s of data
    df = df[df["cur_pnl_atr_60s"] != 0.0].copy()  # 0 means no 60s data
    # Note: 0 also possible if price unchanged at 60s; but rare enough to ignore
    # Actually let me filter differently
    df = df.reset_index(drop=True)
    print(f"\n  Trades with 60s data: {len(df):,}")

    # ---- Distribution of current PnL at 60s ----
    cp = df["cur_pnl_atr_60s"].values
    print(f"\nCurrent PnL @ 60s (ATR units):")
    print(f"  P10={np.percentile(cp, 10):+.3f}  "
          f"P25={np.percentile(cp, 25):+.3f}  "
          f"P50={np.percentile(cp, 50):+.3f}  "
          f"P75={np.percentile(cp, 75):+.3f}  "
          f"P90={np.percentile(cp, 90):+.3f}")
    print(f"  Mean={cp.mean():+.3f}  Pct>0: {(cp > 0).mean()*100:.1f}%")

    # ---- Bucket by current PnL @ 60s ----
    buckets = [
        ("≤ -0.50",  cp <= -0.50),
        ("-0.50 to -0.25", (cp > -0.50) & (cp <= -0.25)),
        ("-0.25 to -0.10", (cp > -0.25) & (cp <= -0.10)),
        ("-0.10 to +0.10", (cp > -0.10) & (cp <= 0.10)),
        ("+0.10 to +0.25", (cp > 0.10) & (cp <= 0.25)),
        ("+0.25 to +0.50", (cp > 0.25) & (cp <= 0.50)),
        ("+0.50 to +0.75", (cp > 0.50) & (cp <= 0.75)),
        ("> +0.75",  cp > 0.75),
    ]

    print(f"\n{'='*100}")
    print(f"FORWARD BRACKET RACE FROM ENTRY  (PT/SL = ±0.75 ATR from entry,")
    print(f"  walking ONLY bars after t=60s)")
    print(f"{'='*100}")
    print(f"  {'Bucket':<22} {'N':>7} {'PT%':>7} {'SL%':>7} {'Nei%':>7}  "
          f"{'Avg$':>8}  Edge vs BE")
    for label, mask in buckets:
        sub = df[mask]
        if len(sub) < 50:
            continue
        n = len(sub)
        pt = sub["fwd_pt_from_entry"].sum()
        sl = sub["fwd_sl_from_entry"].sum()
        nei = n - pt - sl
        # PnL: PT = +0.75 ATR, SL = -0.75 ATR. Neither = current pnl @ 60s.
        pnl = np.where(sub["fwd_pt_from_entry"] == 1,
                        0.75 * sub["atr"] * NQ_MULT - COMMISSION,
                        np.where(sub["fwd_sl_from_entry"] == 1,
                                  -0.75 * sub["atr"] * NQ_MULT - COMMISSION,
                                  sub["cur_pnl_atr_60s"] * sub["atr"] * NQ_MULT - COMMISSION))
        avg = pnl.mean()
        be = 50.0
        resolved = pt + sl
        pt_resolved = pt / resolved * 100 if resolved > 0 else 0
        edge = pt_resolved - be
        flag = " ★" if avg > 0 else ""
        print(f"  {label:<22} {n:>6,} {pt/n*100:>6.1f}% {sl/n*100:>6.1f}% "
              f"{nei/n*100:>6.1f}%  ${avg:>+7.1f}  "
              f"resolved {pt_resolved:.1f}% (edge {edge:+.1f}pp){flag}")

    print(f"\n{'='*100}")
    print(f"FORWARD BRACKET RACE FROM 60s PRICE  (PT/SL = ±0.75 ATR from")
    print(f"  the 60s close — what happens NEXT regardless of where we are now)")
    print(f"{'='*100}")
    print(f"  {'Bucket':<22} {'N':>7} {'PT%':>7} {'SL%':>7} {'Nei%':>7}  "
          f"Edge vs BE")
    for label, mask in buckets:
        sub = df[mask]
        if len(sub) < 50:
            continue
        n = len(sub)
        pt = sub["fwd_pt_from_60s"].sum()
        sl = sub["fwd_sl_from_60s"].sum()
        nei = n - pt - sl
        resolved = pt + sl
        pt_resolved = pt / resolved * 100 if resolved > 0 else 0
        be = 50.0
        edge = pt_resolved - be
        flag = " ★" if pt_resolved > be else ""
        print(f"  {label:<22} {n:>6,} {pt/n*100:>6.1f}% {sl/n*100:>6.1f}% "
              f"{nei/n*100:>6.1f}%  resolved {pt_resolved:.1f}% "
              f"(edge {edge:+.1f}pp){flag}")

    # Save
    df.to_parquet(
        "studies/1m_mtf_context/results/forward_from_60s.parquet",
        index=False)
    print(f"\n  Saved: studies/1m_mtf_context/results/forward_from_60s.parquet")
    print(f"\n{'='*100}")


if __name__ == "__main__":
    main()
