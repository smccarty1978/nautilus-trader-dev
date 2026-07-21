"""1s-bar replay vs MBP-1 tick replay reconciliation on 2026 OOS.

Purpose: validate whether NQ.v.0 1s bars (NQ_v0_1s_*.parquet) are an
acceptable proxy for NQ.v.0 MBP-1 ticks when MBP-1 isn't available.
We have MBP-1 for 2026 (clean), and 1s bars for all years 2016-2026.
If 1s ≈ tick on 2026, we can confidently use 1s for 2025.

Method:
  1. Take the same 2026 F4 fade signals (PT=1.5/SL=3.0) used by
     tick_validate_pt15_sl30_f4.py.
  2. For each signal: replay via NQ_v0_1s_2026_ytd.parquet bars with
     the following conventions:
       ENTRY: at first 1s bar at-or-after signal_ts. Fill = bar OPEN
              (best approximation in absence of bid/ask).
       PT (limit): trigger when 1s bar's HIGH >= pt_px.
              Fill = pt_px EXACTLY (limit semantics — no favorable
              slippage above).
       SL (stop-market): trigger when 1s bar's LOW <= sl_px.
              Fill = sl_px - 0.25 (conservative 1-tick adverse slippage
              past the stop level, since we lack actual bid).
       EOD: at session close (15:00 CT), market exit at the close of
              the last 1s bar BEFORE eod_ts, minus 0.25 (bid approx).
  3. Compare per-trade to tick_pt15_sl30_f4_2026.csv: exit_reason match,
     fill price delta, P&L delta.
  4. Aggregate match: trade count, PT/SL/EOD distribution, WR resolved,
     mean NET per trade. Target: 1s within ±10% of tick on aggregate.

Output: studies/reversion_after_5_streak/results/recon_1s_vs_tick_2026.csv
        + a summary in the console.
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


NQ_MULT = 20.0
COMMISSION_RT = 5.0
PT_ATR = 1.5
SL_ATR = 3.0
SLIPPAGE_TICKS = 1.0           # 1 tick adverse on market SL/EOD fills
TICK_SIZE = 0.25
RTH_END_MIN = 15 * 60
OUT = Path("studies/reversion_after_5_streak/results")
ONE_S_PATH = "data/raw/NQ_v0_1s_2026_ytd.parquet"
TICK_CSV = OUT / "tick_pt15_sl30_f4_2026.csv"


def session_end_ts(ts_init_ns: int) -> int:
    dt = pd.Timestamp(ts_init_ns, tz="UTC").tz_convert("America/Chicago")
    eod_ct = dt.replace(hour=15, minute=0, second=0, microsecond=0, nanosecond=0)
    return int(eod_ct.tz_convert("UTC").value)


def load_1s_bars(path):
    """Load 1s OHLC bars. ts_event is bar OPEN time. ts_close = ts_event + 1s.
    We use ts_event as the canonical key (when the 1s bar starts).
    """
    print(f"Loading {path}...", flush=True)
    df = pq.read_table(path,
                         columns=["ts_event", "open", "high", "low", "close"]
                         ).to_pandas()
    # ts_event may be set as the index column by the parquet's pandas metadata.
    if "ts_event" not in df.columns:
        df = df.reset_index()
    df = df.sort_values("ts_event").reset_index(drop=True)
    df["ts_event_ns"] = df["ts_event"].astype("int64")
    print(f"  {len(df):,} 1s bars  "
          f"range: {df['ts_event'].iloc[0]} -> {df['ts_event'].iloc[-1]}",
          flush=True)
    return df


def replay_1s(signal_ts, eod_ts, atr_i, pt_a, sl_a,
                bars_ts, bars_open, bars_high, bars_low, bars_close):
    """Replay one trade using 1s OHLC. Returns dict mirroring tick replay
    output (entry/exit fill prices, exit_reason, etc.)."""
    # Entry: first 1s bar whose ts_event >= signal_ts.
    i_entry = np.searchsorted(bars_ts, signal_ts, side="left")
    if i_entry >= len(bars_ts) or bars_ts[i_entry] >= eod_ts:
        return None
    entry_ts = int(bars_ts[i_entry])
    fill_buy = float(bars_open[i_entry])    # best proxy for ask
    pt_px = fill_buy + pt_a * atr_i
    sl_px = fill_buy - sl_a * atr_i

    # Forward window (1s bars after entry, before EOD).
    i_end = np.searchsorted(bars_ts, eod_ts, side="left")
    if i_end <= i_entry + 1:
        # No forward 1s bars before EOD; exit at entry close (no movement).
        return {
            "entry_fill_ts": entry_ts, "entry_fill_px": fill_buy,
            "exit_ts": entry_ts, "exit_px": fill_buy,
            "exit_reason": "eod_no_ticks",
            "tick_outcome_pts": 0.0,
            "tick_outcome_atr": 0.0,
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
            # Conservative: fill 1 tick worse than sl_px (bid below stop)
            exit_px = sl_px - SLIPPAGE_TICKS * TICK_SIZE
            # But cap at the bar's low — fill can't be lower than the
            # actual print low if the market never went there. For SL
            # market orders this is realistic.
            exit_px = max(exit_px, float(seg_l[idx]))
            # Actually the worst realistic fill is the bar's low (if
            # we hit at the absolute bottom). The bar's CLOSE is too
            # optimistic. Use:
            #   fill = max(sl_px - 1 tick, bar_low)
            exit_reason = "sl"
        else:
            idx = i_pt
            exit_px = pt_px         # limit fills at limit
            exit_reason = "pt"
        exit_ts = int(seg_ts[idx])
    else:
        # EOD: market exit at last 1s bar's close, minus 1 tick.
        idx = len(seg_ts) - 1
        exit_px = float(seg_c[idx]) - SLIPPAGE_TICKS * TICK_SIZE
        exit_ts = int(seg_ts[idx])
        exit_reason = "eod"

    tick_pts = exit_px - fill_buy
    return {
        "entry_fill_ts": entry_ts, "entry_fill_px": fill_buy,
        "exit_ts": exit_ts, "exit_px": float(exit_px),
        "exit_reason": exit_reason,
        "tick_outcome_pts": float(tick_pts),
        "tick_outcome_atr": float(tick_pts / atr_i) if atr_i > 0 else np.nan,
        "hold_seconds": float(max(exit_ts - entry_ts, 0) / 1e9),
    }


def main():
    OUT.mkdir(parents=True, exist_ok=True)

    print("Loading existing tick results for 2026...", flush=True)
    tick_df = pd.read_csv(TICK_CSV)
    print(f"  {len(tick_df):,} tick rows", flush=True)

    bars = load_1s_bars(ONE_S_PATH)
    bars_ts = bars["ts_event_ns"].to_numpy()
    bars_open = bars["open"].to_numpy()
    bars_high = bars["high"].to_numpy()
    bars_low = bars["low"].to_numpy()
    bars_close = bars["close"].to_numpy()

    # Build the 1s-replay results. Apply the SAME single-position dedup
    # but using 1s exit timestamps (which will differ slightly from tick).
    sigs = tick_df.sort_values("signal_ts").reset_index(drop=True)
    rows = []
    last_exit_ts = -10**18
    t0 = time.time()
    n_skipped_overlap = 0
    for _, r in sigs.iterrows():
        sig_ts = int(r["signal_ts"])
        if sig_ts <= last_exit_ts:
            n_skipped_overlap += 1
            continue
        atr_i = float(r["atr_at_signal"])
        eod_ts = session_end_ts(sig_ts)
        result = replay_1s(sig_ts, eod_ts, atr_i, PT_ATR, SL_ATR,
                            bars_ts, bars_open, bars_high, bars_low,
                            bars_close)
        if result is None:
            continue
        result["signal_ts"] = sig_ts
        result["atr_at_signal"] = atr_i
        result["total_exc_fast"] = float(r["total_exc_fast"])
        # bring across the tick-replay outcome for comparison
        result["tick_outcome_pts_TICK"] = float(r["tick_outcome_pts"])
        result["tick_exit_reason_TICK"] = r["exit_reason"]
        result["gross_pnl_TICK"] = float(r["gross_pnl_nq"])
        rows.append(result)
        if result["exit_ts"] > 0:
            last_exit_ts = result["exit_ts"]
    print(f"  1s replay done in {time.time()-t0:.0f}s, "
          f"{len(rows):,} taken, {n_skipped_overlap:,} skipped overlap")

    out = pd.DataFrame(rows)
    out["gross_pnl_1s"] = out["tick_outcome_pts"] * NQ_MULT
    out["net_pnl_1s"] = out["gross_pnl_1s"] - COMMISSION_RT
    out["net_pnl_TICK"] = out["gross_pnl_TICK"] - COMMISSION_RT
    out["delta_pnl_1s_vs_tick"] = out["gross_pnl_1s"] - out["gross_pnl_TICK"]
    out["exit_reason_match"] = (out["exit_reason"] == out["tick_exit_reason_TICK"])
    out.to_csv(OUT / "recon_1s_vs_tick_2026.csv", index=False)

    # === Aggregate comparison ===
    n_1s = len(out)
    n_tick = len(tick_df)
    pt_1s = (out["exit_reason"] == "pt").sum()
    sl_1s = (out["exit_reason"] == "sl").sum()
    eod_1s = out["exit_reason"].isin(["eod", "eod_no_ticks"]).sum()
    pt_tick = (tick_df["exit_reason"] == "pt").sum()
    sl_tick = (tick_df["exit_reason"] == "sl").sum()
    eod_tick = tick_df["exit_reason"].isin(["eod", "eod_no_ticks"]).sum()

    print()
    print("=" * 70)
    print("1s-BAR REPLAY vs MBP-1 TICK REPLAY — 2026 RECONCILIATION")
    print("=" * 70)
    print(f"Trade count:      1s={n_1s}    tick={n_tick}    "
          f"delta={n_1s - n_tick}")
    print()
    print("Outcome distribution:")
    print(f"  PT-first        1s={pt_1s}    tick={pt_tick}    "
          f"delta={pt_1s - pt_tick}")
    print(f"  SL-first        1s={sl_1s}    tick={sl_tick}    "
          f"delta={sl_1s - sl_tick}")
    print(f"  EOD             1s={eod_1s}    tick={eod_tick}    "
          f"delta={eod_1s - eod_tick}")
    print()
    wr_1s = pt_1s / max(pt_1s + sl_1s, 1) * 100
    wr_tick = pt_tick / max(pt_tick + sl_tick, 1) * 100
    print(f"WR resolved:      1s={wr_1s:.2f}%    tick={wr_tick:.2f}%    "
          f"delta={wr_1s - wr_tick:+.2f}pp")
    print()
    print(f"Mean NET $/trade (NQ, -$5 comm):")
    print(f"  1s  mean: {out['net_pnl_1s'].mean():+.2f}")
    print(f"  tick mean: {out['net_pnl_TICK'].mean():+.2f}")
    print(f"  delta:   {(out['net_pnl_1s'] - out['net_pnl_TICK']).mean():+.2f}")
    print()
    print(f"Total NET $ (NQ):")
    print(f"  1s   total: {out['net_pnl_1s'].sum():+,.0f}")
    print(f"  tick total: {out['net_pnl_TICK'].sum():+,.0f}")
    print()
    pair_match = out["exit_reason_match"].sum()
    print(f"Per-trade exit-reason agreement: {pair_match}/{n_1s} = "
          f"{pair_match/n_1s*100:.1f}%")
    print()
    print("Per-trade gross PnL delta (1s - tick) distribution:")
    d = out["delta_pnl_1s_vs_tick"]
    print(f"  mean   : {d.mean():+.2f}")
    print(f"  median : {d.median():+.2f}")
    print(f"  p10/p90: {d.quantile(0.1):+.2f} / {d.quantile(0.9):+.2f}")
    print(f"  min/max: {d.min():+.2f} / {d.max():+.2f}")
    print()
    print(f"Wrote: {OUT/'recon_1s_vs_tick_2026.csv'}")


if __name__ == "__main__":
    main()
