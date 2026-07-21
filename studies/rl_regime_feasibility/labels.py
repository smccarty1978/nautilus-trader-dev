"""Offline label computation for RL regime feasibility study.

For each observation in feature_snapshots.parquet, simulates a trade that
enters at the next 1s bar open after observation_time and computes:

Fixed-horizon labels (6 horizons: 5s, 15s, 30s, 60s, 120s, 300s):
  pnl_H_base / _1t / _2t       realized PnL in $ for each cost scenario
  stopped_before_H              True if catastrophic stop hit before horizon
  exit_type_H                   "stop" | "horizon" | "censored"

Regime-capped labels:
  pnl_regime_base / _1t / _2t  PnL if exit at min(episode_end, horizon=300s)
  exit_type_regime              "stop" | "regime_flip" | "timeout" | "censored"

All labels use 1s bar OHLC from the catalog for intrabar stop detection.
Stop price = flip_close ± 1.50 * atr_at_flip (catastrophic stop).
Entry fills at opens[entry_idx]; stop fills at bar.open or stop_price.

Cost scenarios: base ($5 RT), +1T ($10 RT), +2T ($15 RT).

Output: results/forward_labels.parquet (same row count as feature_snapshots)
"""
from __future__ import annotations

import math
import os
import sys
import time
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

import numpy as np
import pandas as pd

from studies.rl_regime_feasibility.execution import (
    NQ_MULTIPLIER, NQ_TICK_SIZE, CAT_STOP_ATR, ALL_SCENARIOS, NS_PER_S,
)

CATALOG_PATH = "data/catalog/NQ_v0_2020_2026"
OUT_DIR      = Path("studies/rl_regime_feasibility/results")
SNAP_FILE    = OUT_DIR / "feature_snapshots.parquet"
OUT_FILE     = OUT_DIR / "forward_labels.parquet"

HORIZONS_S   = [5, 15, 30, 60, 120, 300]
HORIZONS_NS  = [h * NS_PER_S for h in HORIZONS_S]


# ── Entry / stop simulation (vectorized over a price array) ──────────────────

def _find_stop(
    direction: int,
    eff_stop: float,
    opens: np.ndarray,
    highs: np.ndarray,
    lows:  np.ndarray,
) -> tuple[int | None, float | None]:
    """Vectorized stop detection. Returns (bar_idx, exit_price) or (None, None)."""
    if direction == 1:
        gap_mask   = opens <= eff_stop
        touch_mask = lows  <= eff_stop
    else:
        gap_mask   = opens >= eff_stop
        touch_mask = highs >= eff_stop

    combined = gap_mask | touch_mask
    if not combined.any():
        return None, None

    bar_i = int(combined.argmax())  # index of first True

    if gap_mask[bar_i]:
        return bar_i, float(opens[bar_i])
    else:
        # Intrabar touch: NT bar_execution fills at next bar's open
        next_i = bar_i + 1
        exit_px = float(opens[next_i]) if next_i < len(opens) else eff_stop
        return bar_i, exit_px


def _sim_trade(
    direction: int,
    entry_px: float,
    stop_px: float,
    opens:  np.ndarray,
    highs:  np.ndarray,
    lows:   np.ndarray,
    ts_arr: np.ndarray,
    entry_ts: int,
    ep_end_ns: int,
    scenario_slip_entry: float,
    scenario_slip_stop: float,
) -> dict:
    """Simulate trade for all horizons plus regime-capped exit."""
    eff_entry = entry_px + direction * scenario_slip_entry
    eff_stop  = stop_px  - direction * scenario_slip_stop

    stop_idx, stop_px_fill = _find_stop(direction, eff_stop, opens, highs, lows)
    max_bars = len(opens)
    result   = {}

    for h_s, h_ns in zip(HORIZONS_S, HORIZONS_NS):
        h_idx = int(np.searchsorted(ts_arr, entry_ts + h_ns, side="left"))

        if stop_idx is not None and stop_idx < h_idx:
            exit_px, exit_type = stop_px_fill, "stop"
        elif h_idx >= max_bars:
            exit_px, exit_type = None, "censored"
        else:
            exit_px, exit_type = float(opens[h_idx]), "horizon"

        pnl = (direction * (exit_px - eff_entry) * NQ_MULTIPLIER - _BASE_COMM_RT
               if exit_px is not None else float("nan"))
        result[f"pnl_{h_s}s"]      = pnl
        result[f"stopped_{h_s}s"]  = (exit_type == "stop")
        result[f"exit_type_{h_s}s"] = exit_type

    # Regime-capped: exit at min(episode_end, 300s horizon)
    max_h_ns = HORIZONS_NS[-1]
    if ep_end_ns > 0 and ep_end_ns < entry_ts + max_h_ns:
        cap_ts, cap_reason = ep_end_ns, "regime_flip"
    else:
        cap_ts, cap_reason = entry_ts + max_h_ns, "timeout"

    cap_idx = int(np.searchsorted(ts_arr, cap_ts, side="left"))

    if stop_idx is not None and stop_idx < cap_idx:
        exit_px_r, exit_type_r = stop_px_fill, "stop"
    elif cap_idx >= max_bars:
        exit_px_r, exit_type_r = None, "censored"
    else:
        exit_px_r, exit_type_r = float(opens[cap_idx]), cap_reason

    pnl_r = (direction * (exit_px_r - eff_entry) * NQ_MULTIPLIER - _BASE_COMM_RT
             if exit_px_r is not None else float("nan"))
    result["pnl_regime"]       = pnl_r
    result["exit_type_regime"] = exit_type_r

    return result


_BASE_COMM_RT = 5.0   # flat $5 RT commission; slippage embedded in effective prices


# ── Main ─────────────────────────────────────────────────────────────────────

def compute_labels() -> None:
    print("Loading feature snapshots ...")
    df = pd.read_parquet(SNAP_FILE)
    print(f"  {len(df):,} observations")

    print("Loading 1s bars from catalog parquet (direct read, study window only) ...")
    import pyarrow.parquet as pq
    import glob as _glob
    t0 = time.time()
    pq_files = sorted(_glob.glob(
        str(Path(CATALOG_PATH) / "data/bar/NQ.XCME-1-SECOND-LAST-EXTERNAL/*.parquet")
    ))
    if not pq_files:
        raise FileNotFoundError(f"No 1s bar parquet files found in {CATALOG_PATH}")
    # Filter to study window + 24h buffer past end (for forward sim windows)
    ns_start = int(df["observation_time"].min()) - 2 * 60 * NS_PER_S  # 2-min before first obs
    ns_end   = int(df["observation_time"].max()) + (HORIZONS_NS[-1] + 3600) * 1  # 1h past last horizon
    tbl = pq.read_table(
        pq_files,
        columns=["ts_event", "open", "high", "low"],
        filters=[("ts_event", ">=", ns_start), ("ts_event", "<=", ns_end)],
    )
    print(f"  {len(tbl):,} bars in {time.time()-t0:.1f}s")

    print("Building numpy arrays ...")

    def _decode_price(chunked_col: "pyarrow.ChunkedArray") -> np.ndarray:
        """Decode NT fixed_size_binary[8] price column (little-endian int64 / 1e9)."""
        parts = []
        for chunk in chunked_col.chunks:
            buf = chunk.buffers()[1]
            parts.append(np.frombuffer(buf, dtype="<i8"))
        return np.concatenate(parts).astype(np.float64) / 1e9

    ts_arr = tbl["ts_event"].combine_chunks().to_numpy().astype(np.int64)
    op_arr = _decode_price(tbl["open"])
    hi_arr = _decode_price(tbl["high"])
    lo_arr = _decode_price(tbl["low"])
    del tbl

    # Extract columns as numpy arrays for fast row access (50x faster than iterrows)
    obs_ts_arr   = df["observation_time"].to_numpy(dtype=np.int64)
    dir_arr      = df["direction"].to_numpy(dtype=np.int64)
    atr_arr      = df["atr_at_flip"].to_numpy(dtype=np.float64)
    flipcl_arr   = df["flip_close"].to_numpy(dtype=np.float64)
    ep_end_arr   = df["episode_end_time"].fillna(0).to_numpy(dtype=np.int64)

    rows_out = []
    total    = len(obs_ts_arr)
    t_log    = time.time()
    print(f"Computing labels for {total:,} observations ...")

    max_fwd_ns = HORIZONS_NS[-1] + 600 * NS_PER_S  # 300s horizon + 10min buffer

    for i in range(total):
        obs_ts    = obs_ts_arr[i]
        direction = int(dir_arr[i])
        atr       = atr_arr[i]
        flip_cl   = flipcl_arr[i]
        ep_end    = int(ep_end_arr[i])

        stop_pts = CAT_STOP_ATR * atr
        stop_px  = flip_cl - direction * stop_pts  # long: below flip_cl; short: above

        entry_idx = int(np.searchsorted(ts_arr, obs_ts, side="left"))
        if entry_idx >= len(ts_arr):
            rows_out.append(_nan_row())
            continue

        entry_ts = ts_arr[entry_idx]
        entry_px = op_arr[entry_idx]

        end_ns  = entry_ts + max_fwd_ns
        end_idx = int(np.searchsorted(ts_arr, end_ns, side="right"))
        fwd_ts  = ts_arr[entry_idx + 1: end_idx + 1]
        fwd_op  = op_arr[entry_idx + 1: end_idx + 1]
        fwd_hi  = hi_arr[entry_idx + 1: end_idx + 1]
        fwd_lo  = lo_arr[entry_idx + 1: end_idx + 1]

        label_row: dict = {
            "observation_time": obs_ts,
            "entry_ts":   entry_ts,
            "entry_px":   entry_px,
            "stop_px":    stop_px,
        }

        for sc in ALL_SCENARIOS:
            lbl = _sim_trade(
                direction=direction,
                entry_px=entry_px,
                stop_px=stop_px,
                opens=fwd_op,
                highs=fwd_hi,
                lows=fwd_lo,
                ts_arr=fwd_ts,
                entry_ts=entry_ts,
                ep_end_ns=ep_end,
                scenario_slip_entry=sc.slippage_entry_pts,
                scenario_slip_stop=sc.slippage_stop_pts,
            )
            sn = sc.name
            for k, v in lbl.items():
                label_row[f"{sn}__{k}"] = v

        rows_out.append(label_row)

        if i > 0 and (i % 50000 == 0 or (time.time() - t_log) > 30):
            pct = 100.0 * i / total
            elapsed = time.time() - t0
            rate = i / elapsed
            eta = (total - i) / rate if rate > 0 else 0
            print(f"  {i:,}/{total:,} ({pct:.1f}%) | {elapsed:.0f}s elapsed | ETA {eta:.0f}s")
            t_log = time.time()

    out_df = pd.DataFrame(rows_out)
    out_df.to_parquet(OUT_FILE, index=False)
    print(f"\n  saved {len(out_df):,} rows → {OUT_FILE}")


def _nan_row() -> dict:
    row = {"observation_time": 0, "entry_ts": 0, "entry_px": float("nan"), "stop_px": float("nan")}
    for sc in ALL_SCENARIOS:
        for h in HORIZONS_S:
            row[f"{sc.name}__pnl_{h}s"]       = float("nan")
            row[f"{sc.name}__stopped_{h}s"]    = None
            row[f"{sc.name}__exit_type_{h}s"]  = "censored"
        row[f"{sc.name}__pnl_regime"]       = float("nan")
        row[f"{sc.name}__exit_type_regime"]  = "censored"
    return row


if __name__ == "__main__":
    compute_labels()
