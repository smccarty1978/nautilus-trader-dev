"""Verify the off-by-one in catalog 1m bars at 2025-02-05 14:45 UTC.

Compare:
  A) raw 1s bars at ts_event 14:44:00..14:45:00 — what should the 1m bar
     covering [14:44:00, 14:45:00) close be?
  B) catalog 1m bar at ts_init=14:45:00 — what does it actually contain?
  C) the 'fixed' resample (closed='left') equivalent

Expected bug: catalog 1m close = close of 1s bar at ts_event=14:45:00
(i.e., the FIRST second of the NEXT minute), not 14:44:59.
"""
from __future__ import annotations
import os, sys
from pathlib import Path
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

T = pd.Timestamp("2025-02-05 14:45:00", tz="UTC")

# --- Raw 1s data ---
df = pd.read_parquet("data/raw/NQ_v0_1s_2025.parquet")
if df.index.tz is None:
    df.index = df.index.tz_localize("UTC")

window = df[(df.index >= T - pd.Timedelta(seconds=10))
            & (df.index <= T + pd.Timedelta(seconds=2))]
print("=== Raw 1s bars (ts_event indexed) around 2025-02-05 14:45:00 UTC ===")
print(window[["open", "high", "low", "close", "volume"]].to_string())

# --- Two resample variants ---
df_in = df[["open", "high", "low", "close", "volume"]].copy()

# BUGGY (current): closed='right'
buggy = df_in.resample("1min", label="right", closed="right").agg({
    "open": "first", "high": "max", "low": "min",
    "close": "last", "volume": "sum",
}).dropna()
print(f"\n=== BUGGY resample (closed='right') ===")
print(f"1m bar at label {T}: {buggy.loc[T].to_dict()}")
print(f"  -> covers indices ({T - pd.Timedelta(seconds=60)}, {T}] (60 1s bars)")
print(f"  -> includes ts_event=14:45:00 (covers REAL TIME [14:45:00, 14:45:01))")

# FIXED: closed='left'
fixed = df_in.resample("1min", label="right", closed="left").agg({
    "open": "first", "high": "max", "low": "min",
    "close": "last", "volume": "sum",
}).dropna()
print(f"\n=== FIXED resample (closed='left') ===")
print(f"1m bar at label {T}: {fixed.loc[T].to_dict()}")
print(f"  -> covers indices [{T - pd.Timedelta(seconds=60)}, {T}) (60 1s bars)")
print(f"  -> includes ts_event=14:44:00..14:44:59, real time [14:44:00, 14:45:00)")

# --- Diff ---
print(f"\n=== Diff (BUGGY - FIXED) for 1m bar at {T} ===")
b = buggy.loc[T]; f = fixed.loc[T]
print(f"  close: buggy {b['close']:.2f}  fixed {f['close']:.2f}  diff {b['close']-f['close']:+.2f}")
print(f"  high : buggy {b['high']:.2f}  fixed {f['high']:.2f}  diff {b['high']-f['high']:+.2f}")
print(f"  low  : buggy {b['low']:.2f}  fixed {f['low']:.2f}  diff {b['low']-f['low']:+.2f}")
print(f"  open : buggy {b['open']:.2f}  fixed {f['open']:.2f}  diff {b['open']-f['open']:+.2f}")

print(f"\n=== Trigger logic at this 1m bar (breach=21575 long entry) ===")
print(f"  BUGGY 1m close = {b['close']:.2f}, breach > 21575? {b['close'] > 21575}")
print(f"  FIXED 1m close = {f['close']:.2f}, breach > 21575? {f['close'] > 21575}")
print(f"  Prior 1m bar (label {T - pd.Timedelta(minutes=1)}):")
prev_t = T - pd.Timedelta(minutes=1)
print(f"    BUGGY prev close = {buggy.loc[prev_t, 'close']:.2f}, prior_unbreached? "
      f"{buggy.loc[prev_t, 'close'] <= 21575}")
print(f"    FIXED prev close = {fixed.loc[prev_t, 'close']:.2f}, prior_unbreached? "
      f"{fixed.loc[prev_t, 'close'] <= 21575}")
