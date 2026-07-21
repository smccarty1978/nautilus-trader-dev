"""Smoke test for 1m→1s entry alignment in the breakout-filter pipeline.

Verifies:
  1. Databento ts_event → ts_close conversion: 1s bars indexed at OPEN+1s.
  2. Resampled 1m bars: index = ts_close (label='right', closed='right').
  3. The 1m bar's close price equals the LAST 1s bar in that minute's close.
  4. Entry mapping: 1s bar with ts_close = trigger_1m_ts_close + 1s.
  5. Entry price = open of that 1s bar (no lookahead).
  6. The first second's high/low/MFE/MAE are computed strictly from
     1s data AFTER the 1m bar closed (no spillover from inside the 1m bar).
  7. Sample clean-winner trades show the actual path data.
"""
from __future__ import annotations
import os, sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

from studies.level_momentum_continuation.level_study import (
    load_v0_1s, resample_1s_to_1m, annotate_sessions_ct,
)
from studies.level_momentum_continuation.analyze_breakout_filter import (
    detect_triggers_breakout, assign_group,
)
from studies.level_momentum_continuation.analyze_1s_precision import (
    annotate_sessions_1s, precompute_eod_1s, map_1m_trigger_to_1s_entry,
)


def main():
    year = 2025
    print(f"=== smoke test on NQ.v.0 {year} ===\n")

    print("[1] Loading 1s parquet...")
    bars_1s = load_v0_1s(Path(f"data/raw/NQ_v0_1s_{year}.parquet"))
    print(f"  rows: {len(bars_1s):,}")
    print(f"  index name: {bars_1s.index.name}")
    print(f"  index tz: {bars_1s.index.tz}")
    print(f"  first 3 rows (ts_close index):")
    print(bars_1s.head(3))
    print(f"\n  Verify: ts_close should be ts_event + 1s.")
    print(f"  Source ts_event = ts_close - 1s")
    print(f"  First ts_close = {bars_1s.index[0]}")
    print(f"  Implied first ts_event = "
          f"{bars_1s.index[0] - pd.Timedelta(seconds=1)}")
    print(f"  Spacing between 1s bars (should be 1s):")
    print(f"    diff[1] = {bars_1s.index[1] - bars_1s.index[0]}")
    print(f"    diff[2] = {bars_1s.index[2] - bars_1s.index[1]}")

    bars_1s = annotate_sessions_1s(bars_1s)

    print(f"\n[2] Resampling 1s -> 1m (label='right', closed='right')...")
    bars_1m = bars_1s[
        ["open", "high", "low", "close", "volume"]
    ].resample("1min", label="right", closed="right").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum"
    }).dropna(subset=["open", "high", "low", "close"])
    bars_1m = annotate_sessions_ct(bars_1m)
    print(f"  rows: {len(bars_1m):,}")
    print(f"  first 3 rows:")
    print(bars_1m.head(3)[["open", "high", "low", "close", "volume"]])

    print(f"\n[3] Reconcile 1m bar close with last 1s bar in that minute...")
    # Pick an active RTH 1m bar in mid-2025
    rth_1m = bars_1m[bars_1m["session"] == "RTH"]
    sample_1m_ts = rth_1m.index[len(rth_1m) // 2]
    sample_1m = bars_1m.loc[sample_1m_ts]
    print(f"  sample 1m bar ts_close = {sample_1m_ts}")
    print(f"  sample 1m bar OHLC = "
          f"O={sample_1m.open} H={sample_1m.high} "
          f"L={sample_1m.low} C={sample_1m.close}")

    # Find all 1s bars with ts_close in (sample_1m_ts - 60s, sample_1m_ts]
    lo = sample_1m_ts - pd.Timedelta(seconds=59)
    hi = sample_1m_ts
    inside = bars_1s[(bars_1s.index >= lo) & (bars_1s.index <= hi)]
    print(f"  {len(inside)} 1s bars inside this 1m bar")
    print(f"  1s open[first]={inside.iloc[0].open}, "
          f"1s close[last]={inside.iloc[-1].close}")
    print(f"  1m bar reports open={sample_1m.open}, close={sample_1m.close}")
    print(f"  1m high (max of 1s highs) = "
          f"{inside.high.max()} vs 1m reports {sample_1m.high}")
    print(f"  1m low  (min of 1s lows)  = "
          f"{inside.low.min()} vs 1m reports {sample_1m.low}")
    assert inside.iloc[0].open == sample_1m.open, "open mismatch"
    assert inside.iloc[-1].close == sample_1m.close, "close mismatch"
    assert inside.high.max() == sample_1m.high, "high mismatch"
    assert inside.low.min() == sample_1m.low, "low mismatch"
    print("  ✓ 1m OHLC matches 1s aggregates")

    print(f"\n[4] Detect breakout triggers and verify entry mapping...")
    triggers = detect_triggers_breakout(bars_1m)
    print(f"  triggers: {len(triggers):,}")

    bars_1s_reset = bars_1s.reset_index(drop=False)
    opens = bars_1s_reset["open"].values.astype(np.float64)
    highs = bars_1s_reset["high"].values.astype(np.float64)
    lows = bars_1s_reset["low"].values.astype(np.float64)
    closes = bars_1s_reset["close"].values.astype(np.float64)
    sessions = bars_1s_reset["session"].values
    ts_close_1s = pd.DatetimeIndex(bars_1s_reset["ts_close"])
    if ts_close_1s.tz is None:
        ts_close_1s = ts_close_1s.tz_localize("UTC")
    else:
        ts_close_1s = ts_close_1s.tz_convert("UTC")

    # Pick the first 5 RTH triggers
    rth_triggers = [t for t in triggers if t["bar_session"] == "RTH"][:5]
    for k, tr in enumerate(rth_triggers):
        print(f"\n  --- trigger {k+1}: {tr['level_pair']} ---")
        ts = pd.Timestamp(tr["bar_ts_close"])
        if ts.tz is None:
            ts = ts.tz_localize("UTC")
        else:
            ts = ts.tz_convert("UTC")
        print(f"  trigger 1m ts_close = {ts}")
        # 1m bar OHLC
        m = bars_1m.loc[ts]
        print(f"  trigger 1m OHLC: O={m.open} H={m.high} "
              f"L={m.low} C={m.close}")
        print(f"  prev 1m close = {bars_1m.loc[bars_1m.index < ts].iloc[-1].close}")
        print(f"  breach_level={tr['breach_level']}, "
              f"target={tr['target']}, stop={tr['stop']}")
        print(f"  bar shape: open={m.open} (must be <= L for long, "
              f">= L for short), close={m.close} "
              f"(must be {'in' if tr['direction']==1 else 'in'} zone)")

        # Map to 1s entry
        e = map_1m_trigger_to_1s_entry(ts, ts_close_1s)
        if e < 0:
            print(f"  *** map returned -1 (no 1s bar at ts_close+1s) ***")
            continue
        print(f"  entry 1s idx = {e}")
        print(f"  entry 1s ts_close = {ts_close_1s[e]} "
              f"(should be 1m ts_close + 1s = {ts + pd.Timedelta(seconds=1)})")
        assert ts_close_1s[e] == ts + pd.Timedelta(seconds=1), \
            "entry 1s ts_close != trigger_ts + 1s"

        entry_px = float(opens[e])
        print(f"  entry price = open of entry 1s bar = {entry_px}")
        print(f"  (vs 1m close price = {m.close} — these may differ "
              f"if first 1s tick after close was at a different price)")

        # Print first 10 seconds of the path
        print(f"\n  First 10 seconds AFTER entry (1s bars):")
        print(f"  {'s':>3}  {'ts_close':<26}  "
              f"{'open':>8} {'high':>8} {'low':>8} {'close':>8} "
              f"{'mfe':>6} {'mae':>6}")
        di = tr["direction"]
        for s in range(10):
            i = e + s
            if i >= len(opens):
                break
            o = opens[i]; h = highs[i]; l = lows[i]; c = closes[i]
            if di == 1:
                mfe = h - entry_px
                mae = entry_px - l
            else:
                mfe = entry_px - l
                mae = h - entry_px
            print(f"  {s:>3}  {ts_close_1s[i]}  "
                  f"{o:>8.2f} {h:>8.2f} {l:>8.2f} {c:>8.2f} "
                  f"{mfe:>+6.2f} {mae:>+6.2f}")

    print(f"\n[5] Look-ahead audit: confirm entry 1s bar has "
          f"ts_close STRICTLY GREATER than trigger 1m ts_close...")
    for k, tr in enumerate(rth_triggers):
        ts = pd.Timestamp(tr["bar_ts_close"])
        if ts.tz is None: ts = ts.tz_localize("UTC")
        else: ts = ts.tz_convert("UTC")
        e = map_1m_trigger_to_1s_entry(ts, ts_close_1s)
        if e < 0: continue
        delta = (ts_close_1s[e] - ts).total_seconds()
        print(f"  trigger {k+1}: 1s_ts_close - 1m_ts_close = {delta}s "
              f"({'PASS' if delta == 1.0 else 'FAIL'})")

    print(f"\n[6] Sample clean winner: walk full path with no look-ahead...")
    # Find a clean winner from the saved analysis
    paths_path = Path(
        "studies/level_momentum_continuation/results_breakout/"
        "rth_path_chars.parquet")
    if paths_path.exists():
        paths = pd.read_parquet(paths_path)
        cw = paths[(paths["bucket"] == "win_clean") &
                    (paths["group"] == "A_25pt") &
                    (paths["year"] == year)]
        if len(cw) > 0:
            sample = cw.iloc[0]
            print(f"  Sample clean winner from saved data:")
            cols = ['level_pair', 'direction', 'outcome',
                    'max_mfe', 'max_mae', 'duration_s', 'pnl_dollars',
                    'mfe_at_T5', 'mae_at_T5']
            print(f"  {sample[cols].to_string()}")
            print(f"  t_mfe_0.5 = {sample['t_mfe_0.5']}s "
                  f"(when MFE first crossed +0.5)")
            print(f"  t_mfe_1.0 = {sample['t_mfe_1.0']}s")
            print(f"  t_mfe_2.0 = {sample['t_mfe_2.0']}s")
            print(f"  t_mfe_3.0 = {sample['t_mfe_3.0']}s")
            print(f"  t_mfe_5.0 = {sample['t_mfe_5.0']}s")
            print(f"  t_mae_1.0 = {sample['t_mae_1.0']}s")
            print(f"  t_mae_2.0 = {sample['t_mae_2.0']}s")
        else:
            print(f"  no clean winners in {year} group A_25pt")
    else:
        print(f"  paths file not found: {paths_path}")

    print(f"\n[7] Sample 1s bar high-vs-open spread audit "
          f"(does 'instant MFE' simply reflect intra-second move?)")
    # Sample 1000 random 1s bars in RTH and look at high-open spread
    rth_mask = sessions == "RTH"
    rth_idx = np.where(rth_mask)[0]
    sample_idx = np.random.choice(rth_idx, 1000, replace=False)
    spreads = highs[sample_idx] - opens[sample_idx]
    print(f"  1s bar (high - open) distribution across 1000 random "
          f"RTH bars (NQ.v.0 {year}):")
    for q in (10, 25, 50, 75, 90, 95, 99):
        print(f"    p{q:>2}: {np.percentile(spreads, q):>5.2f} pts")
    print(f"    mean: {spreads.mean():.2f} pts")
    print(f"    max: {spreads.max():.2f} pts")
    print(f"  Pct of 1s bars where high-open >= 1.0 pt: "
          f"{100*(spreads >= 1.0).mean():.1f}%")
    print(f"  Pct of 1s bars where high-open >= 0.5 pt: "
          f"{100*(spreads >= 0.5).mean():.1f}%")
    print(f"\n  This sets a baseline for what 'instant MFE' looks "
          f"like in 1s NQ data.")


if __name__ == "__main__":
    main()
