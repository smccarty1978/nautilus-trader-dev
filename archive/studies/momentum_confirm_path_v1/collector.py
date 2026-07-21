"""Path-diagnostics collector for momentum-confirm strategies.

Re-derives V_A and V_B momentum-confirmed trades, then walks 1s bars
from fill to causal regime exit. Produces:

  trades_<mode>_<year>.parquet  — one row per trade with all path
                                   labels (max MFE/MAE, time-to-
                                   threshold, capture ratio, etc.)
  paths_<mode>_<year>.parquet   — sampled per-trade path: one row per
                                   (trade_id, elapsed_s) at 5s steps
                                   up to regime exit (or 1800s cap)

Causal: regime_end_ts = next opposing flip's ts_init (1m bar CLOSE),
regime_exit_price = next opposing flip bar's close.
"""

from __future__ import annotations
import os, sys, time, argparse
from pathlib import Path
import numpy as np
import pandas as pd
import pytz

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
os.chdir(project_root)
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "studies/hmm_5s_v1"))

from nautilus_trader.persistence.catalog import ParquetDataCatalog
from hmm_pipeline import SimpleRegimeTracker

OUT = Path("studies/momentum_confirm_path_v1/results")
OUT.mkdir(parents=True, exist_ok=True)
NQ_MULT = 20.0
COMMISSION = 5.0
TICK_COST = 5.0
CT = pytz.timezone("America/Chicago")
PATH_STEP_S = 5
PATH_MAX_S = 1200      # cap for sampled path output (Section 6)
LABEL_MAX_S = 3600     # cap for label computation (max MFE/MAE)
                       # most trades are well under this
MFE_THRESHOLDS = [0.25, 0.50, 0.75, 1.00, 1.50, 2.00, 3.00]
MAE_THRESHOLDS = [0.25, 0.50, 0.75, 1.00, 1.50, 2.00]
CHECKPOINTS_S = [30, 60, 120, 180, 300, 600, 900, 1200]


def compute_atr_series(h, l, c, period=14):
    n = len(c)
    tr = np.empty(n, dtype=float)
    tr[0] = h[0] - l[0]
    prev_c = c[:-1]
    tr[1:] = np.maximum.reduce([
        h[1:] - l[1:], np.abs(h[1:] - prev_c), np.abs(l[1:] - prev_c)])
    atr = np.full(n, np.nan, dtype=float)
    if n < period:
        return atr
    atr[period - 1] = tr[:period].mean()
    for i in range(period, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
    return atr


def enumerate_flips(bars_h, bars_l, bars_o, bars_c, bars_ts,
                       bars_init, year_start_ns):
    tracker = SimpleRegimeTracker()
    flips = []
    for i in range(len(bars_c)):
        flipped = tracker.update(bars_h[i], bars_l[i], bars_c[i])
        if flipped and bars_ts[i] >= year_start_ns:
            flips.append({
                "flip_bar_idx": i,
                "flip_bar_ts_event": int(bars_ts[i]),
                "flip_bar_ts_init": int(bars_init[i]),
                "flip_bar_o": float(bars_o[i]),
                "flip_bar_h": float(bars_h[i]),
                "flip_bar_l": float(bars_l[i]),
                "flip_bar_c": float(bars_c[i]),
                "new_regime": int(tracker.regime),
            })
    df = pd.DataFrame(flips)
    if not len(df):
        return df
    df = df.sort_values("flip_bar_ts_event").reset_index(drop=True)
    df["next_flip_ts_init"] = df["flip_bar_ts_init"].shift(-1).fillna(
        df["flip_bar_ts_init"].max() + 30 * 24 * 3600 * int(1e9)
    ).astype("int64")
    df["next_flip_close"] = df["flip_bar_c"].shift(-1).fillna(0.0)
    return df


def first_cross(seq: np.ndarray, threshold: float,
                  elapsed_s: np.ndarray) -> float:
    mask = seq >= threshold
    if not mask.any():
        return float("nan")
    idx = int(np.argmax(mask))
    return float(elapsed_s[idx])


def compute_trade_path(seg_h, seg_l, seg_c, seg_ts, fill_price,
                          fill_ts, atr, direction,
                          regime_end_price):
    """Walk 1s bars from fill to end. Returns (labels, path_rows).

    seg covers fill_ts to min(regime_end_ts, fill+LABEL_MAX_S).
    final_pnl uses regime_end_price (causal exit), NOT seg[-1].
    """
    n = len(seg_h)
    if n == 0:
        return None, None

    if direction == 1:
        mfe_seq = (seg_h - fill_price) / atr
        mae_seq = (fill_price - seg_l) / atr
    else:
        mfe_seq = (fill_price - seg_l) / atr
        mae_seq = (seg_h - fill_price) / atr
    peak_mfe = np.maximum.accumulate(mfe_seq)
    peak_mae = np.maximum.accumulate(mae_seq)
    elapsed_s = (seg_ts - fill_ts) / 1e9
    pnl_atr = (seg_c - fill_price) * direction / atr

    # Final PnL ALWAYS at regime exit price (causal)
    final_pnl_atr = (regime_end_price - fill_price) * direction / atr

    max_mfe_atr = float(peak_mfe[-1])
    max_mae_atr = float(peak_mae[-1])
    time_to_max_mfe = float(elapsed_s[int(np.argmax(mfe_seq))])
    time_to_max_mae = float(elapsed_s[int(np.argmax(mae_seq))])
    pct_time_positive = float((pnl_atr > 0).mean())
    pct_time_negative = float((pnl_atr < 0).mean())

    labels = {
        "final_pnl_atr": float(final_pnl_atr),
        "final_pnl_dollars": float(final_pnl_atr * atr * NQ_MULT),
        "max_mfe_atr": max_mfe_atr,
        "max_mae_atr": max_mae_atr,
        "time_to_max_mfe_s": time_to_max_mfe,
        "time_to_max_mae_s": time_to_max_mae,
        "pct_time_positive": pct_time_positive,
        "pct_time_negative": pct_time_negative,
        "duration_s": float(elapsed_s[-1]),
    }
    for thr in MFE_THRESHOLDS:
        labels[f"t_mfe_{int(thr*100):03d}_s"] = first_cross(
            peak_mfe, thr, elapsed_s)
    for thr in MAE_THRESHOLDS:
        labels[f"t_mae_{int(thr*100):03d}_s"] = first_cross(
            peak_mae, thr, elapsed_s)
    giveback_seq = peak_mfe - pnl_atr
    labels["peak_giveback_atr"] = float(giveback_seq.max())
    if max_mfe_atr > 0:
        labels["mfe_capture_ratio"] = float(
            final_pnl_atr / max_mfe_atr)
    else:
        labels["mfe_capture_ratio"] = float("nan")

    # Sampled path at PATH_STEP_S intervals up to PATH_MAX_S
    path_rows = []
    target_ts = 0
    i = 0
    seg_max = elapsed_s[-1]
    while target_ts <= seg_max and target_ts <= PATH_MAX_S:
        while i + 1 < n and elapsed_s[i + 1] <= target_ts:
            i += 1
        path_rows.append({
            "elapsed_s": int(target_ts),
            "peak_mfe_atr": float(peak_mfe[i]),
            "peak_mae_atr": float(peak_mae[i]),
            "pnl_atr": float(pnl_atr[i]),
            "close_price": float(seg_c[i]),
        })
        target_ts += PATH_STEP_S
    return labels, path_rows


def process_mode(mode: str, year: int, flips, bars_1m_o, bars_1m_h,
                    bars_1m_l, bars_1m_c, bars_1m_ts, bars_1m_init,
                    bars_ts, bars_h, bars_l, bars_o, bars_c,
                    atr_series):
    """For each flip, check confirmation per mode, walk path, emit
    trade row + sampled path rows. Returns (trades_df, paths_df)."""
    trades = []
    paths = []
    trade_id = 0

    for _, row in flips.iterrows():
        d = int(row["new_regime"])
        flip_idx = int(row["flip_bar_idx"])
        flip_init = int(row["flip_bar_ts_init"])
        flip_h = float(row["flip_bar_h"])
        flip_l = float(row["flip_bar_l"])
        regime_end_ts = int(row["next_flip_ts_init"])
        regime_end_price = float(row["next_flip_close"])

        # ATR at signal (using bar+1's ATR — same as collector)
        if flip_idx + 1 >= len(bars_1m_c):
            continue
        atr = float(atr_series[flip_idx + 1])
        if not np.isfinite(atr) or atr <= 0:
            continue

        # Confirmation per mode
        if mode == "1m_momentum":
            signal_time = flip_init + 60 * int(1e9)
            if regime_end_ts <= signal_time:
                continue
            b1_o = float(bars_1m_o[flip_idx + 1])
            b1_h = float(bars_1m_h[flip_idx + 1])
            b1_l = float(bars_1m_l[flip_idx + 1])
            b1_c = float(bars_1m_c[flip_idx + 1])
            if d == 1:
                hhll = b1_h > flip_h
                mom = b1_c > b1_o
            else:
                hhll = b1_l < flip_l
                mom = b1_c < b1_o
            if not (hhll and mom):
                continue
            fill_ts_target = signal_time + 30 * int(1e9)
        else:  # 30s_momentum
            signal_time = flip_init + 30 * int(1e9)
            if regime_end_ts <= signal_time:
                continue
            cw_lo = np.searchsorted(bars_ts, flip_init, side="left")
            cw_hi = np.searchsorted(bars_ts, signal_time, side="left")
            if cw_hi <= cw_lo:
                continue
            c30_o = float(bars_o[cw_lo])
            c30_c = float(bars_c[cw_hi - 1])
            c30_h = float(bars_h[cw_lo:cw_hi].max())
            c30_l = float(bars_l[cw_lo:cw_hi].min())
            if d == 1:
                hhll = c30_h > flip_h
                mom = c30_c > c30_o
            else:
                hhll = c30_l < flip_l
                mom = c30_c < c30_o
            if not (hhll and mom):
                continue
            fill_ts_target = signal_time + 30 * int(1e9)

        # Get fill bar
        fi = np.searchsorted(bars_ts, fill_ts_target, side="left")
        if fi >= len(bars_ts):
            continue
        actual_fill_ts = int(bars_ts[fi])
        if actual_fill_ts - fill_ts_target > 60 * int(1e9):
            continue
        fill_price = float(bars_o[fi])

        # Walk to min(regime_end_ts, fill+LABEL_MAX_S) for label/path
        walk_end = min(regime_end_ts,
                         actual_fill_ts + LABEL_MAX_S * int(1e9))
        walk_lo = fi
        walk_hi = np.searchsorted(bars_ts, walk_end, side="left")
        walk_hi = min(walk_hi, len(bars_ts))
        if walk_hi <= walk_lo:
            continue

        seg_h = bars_h[walk_lo:walk_hi]
        seg_l = bars_l[walk_lo:walk_hi]
        seg_c = bars_c[walk_lo:walk_hi]
        seg_ts = bars_ts[walk_lo:walk_hi]

        labels, path_rows = compute_trade_path(
            seg_h, seg_l, seg_c, seg_ts,
            fill_price, actual_fill_ts, atr, d, regime_end_price)
        if labels is None:
            continue

        # Final PnL net of cost (1-tick exit slip on regime exit)
        final_net_pnl = (labels["final_pnl_dollars"]
                            - COMMISSION - TICK_COST)
        is_winner_net = int(final_net_pnl > 0)

        trade_row = {
            "trade_id": trade_id,
            "year": year,
            "mode": mode,
            "flip_bar_ts_event": int(row["flip_bar_ts_event"]),
            "direction": d,
            "atr_at_signal": atr,
            "fill_ts": actual_fill_ts,
            "fill_price": fill_price,
            "regime_end_ts": regime_end_ts,
            "regime_end_price": regime_end_price,
            "regime_dur_s": (regime_end_ts - flip_init) / 1e9,
            "final_net_pnl": final_net_pnl,
            "is_winner_net": is_winner_net,
            **labels,
        }
        trades.append(trade_row)

        for pr in path_rows:
            paths.append({
                "trade_id": trade_id,
                **pr,
            })
        trade_id += 1

    return pd.DataFrame(trades), pd.DataFrame(paths)


def main(year: int, mode: str):
    print("=" * 72)
    print(f"PATH DIAGNOSTICS COLLECTOR — YEAR {year} MODE {mode}")
    print("=" * 72)

    catalog = ParquetDataCatalog("data/catalog/NQ_2020_2025")
    print(f"\nLoading 1m bars...")
    bars_1m_nt = catalog.bars(
        bar_types=["NQ.XCME-1-MINUTE-LAST-EXTERNAL"],
        start=pd.Timestamp(f"{year}-01-01", tz="UTC")
              - pd.Timedelta(days=30),
        end=pd.Timestamp(f"{year}-12-31 23:59:59", tz="UTC"))
    bars_1m_ts = np.array([b.ts_event for b in bars_1m_nt])
    bars_1m_init = np.array([b.ts_init for b in bars_1m_nt])
    bars_1m_o = np.array([float(b.open) for b in bars_1m_nt])
    bars_1m_h = np.array([float(b.high) for b in bars_1m_nt])
    bars_1m_l = np.array([float(b.low) for b in bars_1m_nt])
    bars_1m_c = np.array([float(b.close) for b in bars_1m_nt])
    print(f"  {len(bars_1m_nt):,} 1m bars")

    year_start_ns = pd.Timestamp(f"{year}-01-01", tz="UTC").value
    flips = enumerate_flips(
        bars_1m_h, bars_1m_l, bars_1m_o, bars_1m_c, bars_1m_ts,
        bars_1m_init, year_start_ns)
    flip_dts = pd.to_datetime(flips["flip_bar_ts_event"], unit="ns",
                                  utc=True).dt.tz_convert(CT)
    flip_minutes = flip_dts.dt.hour * 60 + flip_dts.dt.minute
    rth_mask = (flip_minutes >= 510) & (flip_minutes < 900)
    flips = flips[rth_mask].copy()
    print(f"  RTH flips: {len(flips):,}")
    atr_series = compute_atr_series(bars_1m_h, bars_1m_l, bars_1m_c)

    print(f"\nLoading 1s bars...")
    bars_1s_nt = catalog.bars(
        bar_types=["NQ.XCME-1-SECOND-LAST-EXTERNAL"],
        start=pd.Timestamp(f"{year}-01-01", tz="UTC"),
        end=pd.Timestamp(f"{year}-12-31 23:59:59", tz="UTC"))
    bars_ts = np.array([b.ts_event for b in bars_1s_nt])
    bars_h = np.array([float(b.high) for b in bars_1s_nt])
    bars_l = np.array([float(b.low) for b in bars_1s_nt])
    bars_o = np.array([float(b.open) for b in bars_1s_nt])
    bars_c = np.array([float(b.close) for b in bars_1s_nt])
    print(f"  {len(bars_1s_nt):,} 1s bars")

    print(f"\nProcessing trades + paths...")
    t0 = time.time()
    df_trades, df_paths = process_mode(
        mode, year, flips, bars_1m_o, bars_1m_h, bars_1m_l, bars_1m_c,
        bars_1m_ts, bars_1m_init,
        bars_ts, bars_h, bars_l, bars_o, bars_c, atr_series)
    print(f"  Done in {time.time()-t0:.0f}s. "
           f"{len(df_trades):,} trades, {len(df_paths):,} path rows")

    df_trades.to_parquet(
        OUT / f"trades_{mode}_{year}.parquet", index=False)
    df_paths.to_parquet(
        OUT / f"paths_{mode}_{year}.parquet", index=False)
    print(f"\nSaved:")
    print(f"  trades_{mode}_{year}.parquet")
    print(f"  paths_{mode}_{year}.parquet")
    if len(df_trades):
        wr = df_trades["is_winner_net"].mean() * 100
        print(f"  WR (net): {wr:.1f}%, mean ${df_trades['final_net_pnl'].mean():.2f}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--mode", required=True,
                          choices=["1m_momentum", "30s_momentum"])
    args = parser.parse_args()
    main(args.year, args.mode)
