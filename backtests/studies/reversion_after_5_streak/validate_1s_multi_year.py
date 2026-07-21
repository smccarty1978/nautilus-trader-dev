"""Multi-year 1s-bar validation 2020-2026 — the deployment-grade test.

Architecture (clean, single-source data lineage):
  - Signal generation: 1m bars from `data/catalog/NQ_v0_2020_2026`
    (built from `data/raw/NQ_v0_1s_*.parquet` via `closed='left'` resample).
  - Execution simulation: same `NQ_v0_1s_<year>.parquet` 1s OHLC files
    used to build the 1m catalog. No contract mismatch.

Trade rule (unchanged from prior validations):
  - L=4 bear streak in 1m sticky regime = -1, RTH only.
  - F4 filter: total_exc_fast >= 57.75 (5-min lookback) at signal bar.
  - Long fade: PT=1.5 ATR (limit at pt_px), SL=3.0 ATR (stop-market).
  - EOD-flatten at 15:00 CT, single-position dedup by 1s exit timestamp.

Fill model (matches the 2026 1s vs MBP-1 reconciliation):
  - Entry: 1s bar OPEN at first bar at-or-after signal_ts.
  - PT: trigger when bar high >= pt_px; fill at pt_px (limit exact).
  - SL: trigger when bar low <= sl_px; fill at max(sl_px - 1 tick, bar low).
  - EOD: market exit at close of last in-session 1s bar, minus 1 tick.

Output: studies/reversion_after_5_streak/results/multi_year_1s_summary.csv
        + per-year detail CSV.
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
import pyarrow.parquet as pq
from nautilus_trader.persistence.catalog import ParquetDataCatalog


CATALOG = "data/catalog/NQ_v0_2020_2026"
BAR_TYPE = "NQ.XCME-1-MINUTE-LAST-EXTERNAL"
ATR_PERIOD = 14
EMA_SHORT = 3
EMA_LONG = 9
STREAK_LEN = 4
PT_ATR = 1.5
SL_ATR = 3.0
F4_CUTOFF = 57.75
FAST_WINDOW = 5
NQ_MULT = 20.0
MNQ_MULT = 2.0
COMMISSION_RT_NQ = 5.0
COMMISSION_RT_MNQ = 2.50
SLIPPAGE_TICKS = 1.0
TICK_SIZE = 0.25
RTH_START_MIN = 8 * 60 + 30
RTH_END_MIN = 15 * 60

YEARS = [2020, 2021, 2022, 2023, 2024, 2025, 2026]
ONE_S_PATHS = {
    2020: "data/raw/NQ_v0_1s_2020.parquet",
    2021: "data/raw/NQ_v0_1s_2021.parquet",
    2022: "data/raw/NQ_v0_1s_2022.parquet",
    2023: "data/raw/NQ_v0_1s_2023.parquet",
    2024: "data/raw/NQ_v0_1s_2024.parquet",
    2025: "data/raw/NQ_v0_1s_2025.parquet",
    2026: "data/raw/NQ_v0_1s_2026_ytd.parquet",
}
OUT = Path("studies/reversion_after_5_streak/results")


def load_1m_df():
    print("Loading 1m bars 2020-2026...", flush=True)
    t0 = time.time()
    catalog = ParquetDataCatalog(CATALOG)
    bars = catalog.bars(
        bar_types=[BAR_TYPE],
        start=pd.Timestamp("2020-01-01", tz="UTC"),
        end=pd.Timestamp("2026-04-30 23:59:59", tz="UTC"),
    )
    df = pd.DataFrame({
        "ts_init":  [b.ts_init  for b in bars],
        "open":     [float(b.open)  for b in bars],
        "high":     [float(b.high)  for b in bars],
        "low":      [float(b.low)   for b in bars],
        "close":    [float(b.close) for b in bars],
    }).sort_values("ts_init").reset_index(drop=True)
    print(f"  {len(df):,} bars in {time.time()-t0:.0f}s", flush=True)
    return df


def compute_atr_wilder(df, period):
    high = df["high"].to_numpy(); low = df["low"].to_numpy(); close = df["close"].to_numpy()
    n = len(df); tr = np.empty(n); tr[0] = high[0] - low[0]
    if n > 1:
        prev_close = close[:-1]
        tr[1:] = np.maximum.reduce([
            high[1:] - low[1:],
            np.abs(high[1:] - prev_close),
            np.abs(low[1:] - prev_close),
        ])
    atr = np.full(n, np.nan)
    if n >= period:
        atr[period - 1] = tr[:period].mean()
        for i in range(period, n):
            atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
    return atr


def compute_regime(df):
    high = df["high"]; low = df["low"]; close = df["close"]
    sH = high.ewm(span=EMA_SHORT, adjust=False).mean().to_numpy()
    lH = high.ewm(span=EMA_LONG,  adjust=False).mean().to_numpy()
    sL = low.ewm(span=EMA_SHORT,  adjust=False).mean().to_numpy()
    lL = low.ewm(span=EMA_LONG,   adjust=False).mean().to_numpy()
    c = close.to_numpy()
    n = len(df); regime = np.zeros(n, dtype=np.int8); cur = 0
    for i in range(n):
        if c[i] > sH[i] and c[i] > lH[i]: cur = 1
        elif c[i] < sL[i] and c[i] < lL[i]: cur = -1
        regime[i] = cur
    return regime


def compute_total_exc_fast(open_arr, high_arr, low_arr, close_arr, ts_arr,
                              window=FAST_WINDOW):
    n = len(open_arr)
    consec = np.zeros(n, dtype=bool)
    consec[1:] = (ts_arr[1:] - ts_arr[:-1]) == 60_000_000_000
    out = np.full(n, np.nan)
    for i in range(window - 1, n):
        lo = i - window + 1
        if not consec[lo + 1:i + 1].all():
            continue
        start_open = open_arr[lo]
        w_high = high_arr[lo:i + 1].max()
        w_low  = low_arr[lo:i + 1].min()
        out[i] = (w_high - start_open) + (start_open - w_low)
    return out


def session_of_close_ct(ts_init_ns):
    dt = pd.to_datetime(ts_init_ns, unit="ns", utc=True).tz_convert("America/Chicago")
    minutes = dt.hour * 60 + dt.minute
    rth = (minutes >= RTH_START_MIN) & (minutes < RTH_END_MIN)
    return np.where(rth, "RTH", "ETH")


def session_end_ts(ts_init_ns: int) -> int:
    dt = pd.Timestamp(ts_init_ns, tz="UTC").tz_convert("America/Chicago")
    eod_ct = dt.replace(hour=15, minute=0, second=0, microsecond=0, nanosecond=0)
    return int(eod_ct.tz_convert("UTC").value)


def find_signals_for_year(df, atr, regime, tef, ct_years, target_year):
    """Generate F4-filtered signals whose signal bar (ts_init in CT) falls
    in target_year. ATR/regime/F4 are computed on the FULL series (which
    spans 2020-2026), so warmup boundaries don't truncate any year."""
    sess = session_of_close_ct(df["ts_init"].to_numpy())
    close = df["close"].to_numpy()
    openp = df["open"].to_numpy()
    ts    = df["ts_init"].to_numpy()
    bear = (close < openp)
    consec = np.zeros(len(df), dtype=bool)
    consec[1:] = (ts[1:] - ts[:-1]) == 60_000_000_000
    out = []
    for i in range(STREAK_LEN - 1, len(df)):
        if ct_years[i] != target_year:
            continue
        if not bear[i - STREAK_LEN + 1:i + 1].all():
            continue
        if not consec[i - STREAK_LEN + 2:i + 1].all():
            continue
        if regime[i] != -1:
            continue
        if sess[i] != "RTH":
            continue
        a = atr[i]
        if not np.isfinite(a) or a <= 0:
            continue
        sig_ts = int(ts[i])
        eod_ts = session_end_ts(sig_ts)
        if eod_ts - sig_ts < 60_000_000_000:
            continue
        f4_val = tef[i]
        if not np.isfinite(f4_val) or f4_val < F4_CUTOFF:
            continue
        out.append({
            "i": i, "signal_ts": sig_ts, "session_end_ts": eod_ts,
            "close_at_signal": float(close[i]), "atr_at_signal": float(a),
            "total_exc_fast": float(f4_val),
        })
    return out


def load_1s_bars(path):
    df = pq.read_table(path,
                         columns=["ts_event", "open", "high", "low", "close"]
                         ).to_pandas()
    if "ts_event" not in df.columns:
        df = df.reset_index()
    df = df.sort_values("ts_event").reset_index(drop=True)
    df["ts_event_ns"] = df["ts_event"].astype("int64")
    return df


def replay_1s(signal, bars_ts, bars_open, bars_high, bars_low, bars_close):
    sig_ts = signal["signal_ts"]
    eod_ts = signal["session_end_ts"]
    atr_i = signal["atr_at_signal"]
    i_entry = np.searchsorted(bars_ts, sig_ts, side="left")
    if i_entry >= len(bars_ts) or bars_ts[i_entry] >= eod_ts:
        return None
    entry_ts = int(bars_ts[i_entry])
    fill_buy = float(bars_open[i_entry])
    pt_px = fill_buy + PT_ATR * atr_i
    sl_px = fill_buy - SL_ATR * atr_i
    i_end = np.searchsorted(bars_ts, eod_ts, side="left")
    if i_end <= i_entry + 1:
        return {
            **signal,
            "entry_fill_ts": entry_ts, "entry_fill_px": fill_buy,
            "exit_ts": entry_ts, "exit_px": fill_buy,
            "exit_reason": "eod_no_ticks",
            "tick_outcome_pts": 0.0, "tick_outcome_atr": 0.0,
            "hold_seconds": 0,
        }
    seg_h = bars_high[i_entry + 1:i_end]
    seg_l = bars_low[i_entry + 1:i_end]
    seg_c = bars_close[i_entry + 1:i_end]
    seg_ts = bars_ts[i_entry + 1:i_end]
    hit_pt = seg_h >= pt_px
    hit_sl = seg_l <= sl_px
    if hit_pt.any() or hit_sl.any():
        i_pt = int(np.argmax(hit_pt)) if hit_pt.any() else 10**9
        i_sl = int(np.argmax(hit_sl)) if hit_sl.any() else 10**9
        if i_sl <= i_pt:
            idx = i_sl
            exit_px = max(sl_px - SLIPPAGE_TICKS * TICK_SIZE, float(seg_l[idx]))
            exit_reason = "sl"
        else:
            idx = i_pt
            exit_px = pt_px
            exit_reason = "pt"
        exit_ts = int(seg_ts[idx])
    else:
        idx = len(seg_ts) - 1
        exit_px = float(seg_c[idx]) - SLIPPAGE_TICKS * TICK_SIZE
        exit_ts = int(seg_ts[idx])
        exit_reason = "eod"
    tick_pts = exit_px - fill_buy
    return {
        **signal,
        "entry_fill_ts": entry_ts, "entry_fill_px": fill_buy,
        "exit_ts": exit_ts, "exit_px": float(exit_px),
        "exit_reason": exit_reason,
        "tick_outcome_pts": float(tick_pts),
        "tick_outcome_atr": float(tick_pts / atr_i) if atr_i > 0 else np.nan,
        "hold_seconds": float(max(exit_ts - entry_ts, 0) / 1e9),
    }


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    df = load_1m_df()
    print("Computing ATR(14), regime, F4 feature on full series...", flush=True)
    t0 = time.time()
    atr = compute_atr_wilder(df, ATR_PERIOD)
    regime = compute_regime(df)
    tef = compute_total_exc_fast(
        df["open"].to_numpy(), df["high"].to_numpy(),
        df["low"].to_numpy(), df["close"].to_numpy(),
        df["ts_init"].to_numpy(),
    )
    ct_years = pd.to_datetime(df["ts_init"].to_numpy(), unit="ns", utc=True)\
                 .tz_convert("America/Chicago").year.to_numpy()
    print(f"  done in {time.time()-t0:.0f}s", flush=True)

    summary_rows = []
    all_trades = []

    for year in YEARS:
        print(f"\n=== YEAR {year} ===", flush=True)
        signals = find_signals_for_year(df, atr, regime, tef, ct_years, year)
        print(f"  F4-filtered signals: {len(signals):,}", flush=True)
        if not signals:
            continue
        one_s_path = ONE_S_PATHS[year]
        if not Path(one_s_path).exists():
            print(f"  MISSING 1s file: {one_s_path}"); continue
        t0 = time.time()
        bars = load_1s_bars(one_s_path)
        print(f"  Loaded {len(bars):,} 1s bars ({time.time()-t0:.0f}s)",
              flush=True)
        bars_ts = bars["ts_event_ns"].to_numpy()
        bars_open = bars["open"].to_numpy()
        bars_high = bars["high"].to_numpy()
        bars_low = bars["low"].to_numpy()
        bars_close = bars["close"].to_numpy()

        rows = []
        last_exit_ts = -10**18
        n_skipped = 0
        for s in signals:
            if s["signal_ts"] <= last_exit_ts:
                n_skipped += 1
                continue
            r = replay_1s(s, bars_ts, bars_open, bars_high, bars_low, bars_close)
            if r is None:
                continue
            r["year"] = year
            rows.append(r)
            if r["exit_ts"] > 0:
                last_exit_ts = r["exit_ts"]
        print(f"  Replay: {len(rows):,} taken, {n_skipped:,} skipped overlap",
              flush=True)
        all_trades.extend(rows)

        ydf = pd.DataFrame(rows)
        ydf["gross_nq"] = ydf["tick_outcome_pts"] * NQ_MULT
        ydf["gross_mnq"] = ydf["tick_outcome_pts"] * MNQ_MULT
        ydf["net_nq"] = ydf["gross_nq"] - COMMISSION_RT_NQ
        ydf["net_mnq"] = ydf["gross_mnq"] - COMMISSION_RT_MNQ
        ydf = ydf.sort_values("entry_fill_ts").reset_index(drop=True)
        ydf["cum_nq"] = ydf["net_nq"].cumsum()
        ydf["dd_nq"] = ydf["cum_nq"] - ydf["cum_nq"].cummax()
        ydf["cum_mnq"] = ydf["net_mnq"].cumsum()
        ydf["dd_mnq"] = ydf["cum_mnq"] - ydf["cum_mnq"].cummax()
        valid = ydf[~ydf["exit_reason"].isin(["no_entry_ticks"])]
        n_v = len(valid)
        pt = (valid["exit_reason"] == "pt").sum()
        sl = (valid["exit_reason"] == "sl").sum()
        eod = (valid["exit_reason"].isin(["eod", "eod_no_ticks"])).sum()
        wr = pt / max(pt + sl, 1) * 100
        summary_rows.append({
            "year": year, "n": n_v, "pt": pt, "sl": sl, "eod": eod,
            "wr_resolved": wr,
            "mean_net_nq": valid["net_nq"].mean() if n_v else np.nan,
            "total_net_nq": valid["net_nq"].sum() if n_v else 0,
            "max_dd_nq": valid["dd_nq"].min() if n_v else 0,
            "mean_net_mnq": valid["net_mnq"].mean() if n_v else np.nan,
            "total_net_mnq": valid["net_mnq"].sum() if n_v else 0,
            "max_dd_mnq": valid["dd_mnq"].min() if n_v else 0,
            "worst_nq": valid["net_nq"].min() if n_v else 0,
            "best_nq": valid["net_nq"].max() if n_v else 0,
        })

    # === Aggregate ===
    sdf = pd.DataFrame(summary_rows)
    sdf.to_csv(OUT / "multi_year_1s_summary.csv", index=False)
    # All per-trade rows
    all_df = pd.DataFrame(all_trades)
    if len(all_df) > 0:
        all_df["gross_nq"] = all_df["tick_outcome_pts"] * NQ_MULT
        all_df["gross_mnq"] = all_df["tick_outcome_pts"] * MNQ_MULT
        all_df["net_nq"] = all_df["gross_nq"] - COMMISSION_RT_NQ
        all_df["net_mnq"] = all_df["gross_mnq"] - COMMISSION_RT_MNQ
        all_df.to_csv(OUT / "multi_year_1s_trades.csv", index=False)

    print("\n" + "=" * 70)
    print("MULTI-YEAR 1s VALIDATION SUMMARY (PT=1.5 / SL=3.0 + F4)")
    print("=" * 70)
    with pd.option_context("display.max_columns", None,
                            "display.width", 220,
                            "display.float_format", "{:.2f}".format):
        cols = ["year", "n", "pt", "sl", "eod", "wr_resolved",
                "mean_net_nq", "total_net_nq", "max_dd_nq",
                "mean_net_mnq", "total_net_mnq", "max_dd_mnq",
                "worst_nq", "best_nq"]
        print(sdf[cols].to_string(index=False))

    # Multi-year totals
    total_n = sdf["n"].sum()
    total_net_nq = sdf["total_net_nq"].sum()
    total_net_mnq = sdf["total_net_mnq"].sum()
    mean_nq = total_net_nq / max(total_n, 1)
    mean_mnq = total_net_mnq / max(total_n, 1)
    n_pos_years = (sdf["mean_net_nq"] > 0).sum()
    print(f"\nMulti-year totals (2020-2026, {total_n:,} trades):")
    print(f"  Total NET NQ:  ${total_net_nq:+,.0f}")
    print(f"  Mean $/trade NQ: ${mean_nq:+.2f}")
    print(f"  Total NET MNQ: ${total_net_mnq:+,.0f}")
    print(f"  Mean $/trade MNQ: ${mean_mnq:+.2f}")
    print(f"  Years positive: {n_pos_years} / {len(sdf)}")
    print(f"\nWrote: {OUT/'multi_year_1s_summary.csv'}, "
          f"{OUT/'multi_year_1s_trades.csv'}")


if __name__ == "__main__":
    main()
