"""Diagnose differences between NT backtest and collector trades.

Loads NT trades + collector trades for Q4 2025, joins by flip time
(rounded to 1m), reports:
  - Trades in collector but NOT in NT (lost flips)
  - Trades in NT but NOT in collector (extra/spurious)
  - Matched trades: timing/price/ATR diffs
"""

import sys
import os
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd

NT_FILE = "studies/1m_confirmed_flip/results/nt_trail_q4_2025_tight.parquet"
COL_FILE = "studies/1m_confirmed_flip/results/trades_all.parquet"


def main():
    print("=" * 72)
    print("NT vs Collector — Q4 2025 trade diff")
    print("=" * 72)

    nt = pd.read_parquet(NT_FILE).copy()
    col = pd.read_parquet(COL_FILE).copy()
    col["entry_dt"] = pd.to_datetime(col["entry_ts"], unit="ns", utc=True)
    col_q4 = col[
        (col["entry_dt"] >= "2025-10-01") &
        (col["entry_dt"] < "2026-01-01")
    ].copy()

    print(f"\n  NT trades: {len(nt):,}")
    print(f"  Collector Q4 trades: {len(col_q4):,}")
    print(f"  Diff: {len(col_q4) - len(nt):+,}")

    # Build join keys: (flip_time rounded to minute, direction)
    nt["flip_min"] = pd.to_datetime(nt["flip_time"]).dt.floor("min")
    col_q4["flip_min"] = pd.to_datetime(
        col_q4["flip_time"]).dt.floor("min")

    nt_keys = set(zip(nt["flip_min"], nt["direction"]))
    col_keys = set(zip(col_q4["flip_min"], col_q4["direction"]))

    in_both = nt_keys & col_keys
    only_nt = nt_keys - col_keys
    only_col = col_keys - nt_keys

    print(f"\n  Matched (same flip min + direction): {len(in_both):,}")
    print(f"  Only in NT (extra): {len(only_nt):,}")
    print(f"  Only in collector (lost): {len(only_col):,}")

    # Sample of lost flips
    print(f"\n  Sample LOST flips (in collector, not in NT):")
    lost = col_q4[
        col_q4.apply(
            lambda r: (r["flip_min"], r["direction"]) in only_col, axis=1)
    ].head(20)
    for _, r in lost.iterrows():
        d = "L" if r["direction"] == 1 else "S"
        print(f"    {r['flip_min']}  {d}  "
              f"flip@{r['flip_bar_high']:.2f}/{r['flip_bar_low']:.2f}  "
              f"ATR={r['atr_at_flip']:.2f}  "
              f"PnL=${r['regime_pnl_dollars']:+.0f}")

    # Sample of extra flips
    print(f"\n  Sample EXTRA flips (in NT, not in collector):")
    extra = nt[
        nt.apply(
            lambda r: (r["flip_min"], r["direction"]) in only_nt, axis=1)
    ].head(20)
    for _, r in extra.iterrows():
        d = "L" if r["direction"] == 1 else "S"
        print(f"    {r['flip_min']}  {d}  entry={r['entry_price']:.2f}  "
              f"ATR={r['atr_at_entry']:.2f}  PnL=${r['pnl_dollars']:+.0f}")

    # Matched trades — check timing/ATR drift
    print(f"\n  Matched trade comparison (first 10):")
    matched_keys = list(in_both)[:10]
    for fm, d in matched_keys:
        nt_t = nt[(nt["flip_min"] == fm) & (nt["direction"] == d)].iloc[0]
        col_t = col_q4[(col_q4["flip_min"] == fm)
                       & (col_q4["direction"] == d)].iloc[0]
        side = "L" if d == 1 else "S"
        print(f"    {fm} {side}: "
              f"NT atr={nt_t['atr_at_entry']:.2f} entry={nt_t['entry_price']:.2f}  "
              f"COL atr={col_t['atr_at_flip']:.2f} entry={col_t['entry_price']:.2f}  "
              f"d_atr={nt_t['atr_at_entry']-col_t['atr_at_flip']:+.3f}  "
              f"d_entry={nt_t['entry_price']-col_t['entry_price']:+.3f}")

    # ATR distribution stats for all matched
    nt_idx = nt.set_index(["flip_min", "direction"])
    col_idx = col_q4.set_index(["flip_min", "direction"])
    common = nt_idx.index.intersection(col_idx.index)
    nt_m = nt_idx.loc[common]
    col_m = col_idx.loc[common]

    d_atr = nt_m["atr_at_entry"].values - col_m["atr_at_flip"].values
    d_entry = nt_m["entry_price"].values - col_m["entry_price"].values

    import numpy as np
    print(f"\n  ATR diff (NT - collector):")
    print(f"    mean={np.mean(d_atr):+.3f} std={np.std(d_atr):.3f} "
          f"max={np.max(np.abs(d_atr)):.3f}")
    print(f"  Entry price diff (NT - collector):")
    print(f"    mean={np.mean(d_entry):+.3f} std={np.std(d_entry):.3f} "
          f"max={np.max(np.abs(d_entry)):.3f}")

    print(f"\n{'=' * 72}")


if __name__ == "__main__":
    main()
