"""Verify pandas study's 1m bars match the FIXED catalog convention.

The pandas study uses load_v0_1s (which shifts ts_event by +1s to
ts_close convention) and then resample(closed='right'). Trace whether
this combo produces look-ahead or correct [T-60s, T) windows.
"""
from __future__ import annotations
import os, sys
from pathlib import Path
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

from studies.level_momentum_continuation.level_study import (
    load_v0_1s, resample_1s_to_1m,
)

T = pd.Timestamp("2025-02-05 14:45:00", tz="UTC")

bars_1s = load_v0_1s(Path("data/raw/NQ_v0_1s_2025.parquet"))
bars_1m = resample_1s_to_1m(bars_1s)

print(f"Pandas study's 1m bar at label {T}:")
row = bars_1m.loc[T]
print(f"  open={row['open']:.2f} high={row['high']:.2f} "
      f"low={row['low']:.2f} close={row['close']:.2f}")
print(f"\nPrior 1m bar (label {T - pd.Timedelta(minutes=1)}):")
row2 = bars_1m.loc[T - pd.Timedelta(minutes=1)]
print(f"  open={row2['open']:.2f} high={row2['high']:.2f} "
      f"low={row2['low']:.2f} close={row2['close']:.2f}")
print(f"\nReference values:")
print(f"  BUGGY catalog 1m close at 14:45:00 = 21576.00 (look-ahead)")
print(f"  FIXED catalog 1m close at 14:45:00 = 21569.25 (correct)")
print(f"\nPandas matches: ", end="")
if abs(row['close'] - 21569.25) < 0.01:
    print("FIXED (CORRECT — no bug in pandas study)")
elif abs(row['close'] - 21576.00) < 0.01:
    print("BUGGY (look-ahead present in pandas study)")
else:
    print(f"NEITHER ({row['close']})")
