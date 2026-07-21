"""Clairvoyant oracle for Gate 2 benchmark.

The oracle knows the TRUE future price path up to min(episode_end, 300s).
It uses that knowledge to choose the optimal exit that maximises PnL.

Oracle entry convention (matches labels.py exactly):
  - Enters at the first 1s bar open on or after observation_time
  - Stop detection uses the same logic as labels.py:
      gap-through → fill at bar open
      intrabar touch → fill at next bar open

Oracle exit convention:
  - Not stopped: exits at the HIGH of the best bar (long) or LOW of the best bar (short)
    within the window [entry+1s, min(ep_end, entry+300s)]
  - Stopped: fill = labels.py stop fill (gap-open or next-bar-open)

This ensures oracle_pnl >= pnl_regime for every episode.

Outputs: results/oracle_summary.parquet
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

import numpy as np
import pandas as pd

from studies.rl_regime_feasibility.execution import (
    NQ_MULTIPLIER, CAT_STOP_ATR, NS_PER_S, COST_BASE,
)

CATALOG_PATH = "data/catalog/NQ_v0_2020_2026"
OUT_DIR   = Path("studies/rl_regime_feasibility/results")
SNAP_FILE = OUT_DIR / "feature_snapshots.parquet"
LBL_FILE  = OUT_DIR / "forward_labels.parquet"
OUT_FILE  = OUT_DIR / "oracle_summary.parquet"

_MAX_H_NS  = 300 * NS_PER_S    # 300s max horizon
_COMM      = COST_BASE.commission_rt_usd   # $5 RT


def _decode_price(chunked_col: "pyarrow.ChunkedArray") -> np.ndarray:
    """Decode NT fixed_size_binary[8] price column (little-endian int64 / 1e9)."""
    parts = []
    for chunk in chunked_col.chunks:
        buf = chunk.buffers()[1]
        parts.append(np.frombuffer(buf, dtype="<i8"))
    return np.concatenate(parts).astype(np.float64) / 1e9


def _find_stop(
    direction: int,
    eff_stop: float,
    opens: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
) -> tuple[int | None, float | None]:
    """Vectorized stop detection matching labels.py convention exactly.

    Returns (bar_idx, exit_price) or (None, None).
    Gap-through fills at bar open; intrabar touch fills at next bar open.
    """
    if direction == 1:
        gap_mask   = opens <= eff_stop
        touch_mask = lows  <= eff_stop
    else:
        gap_mask   = opens >= eff_stop
        touch_mask = highs >= eff_stop

    combined = gap_mask | touch_mask
    if not combined.any():
        return None, None

    bar_i = int(combined.argmax())
    if gap_mask[bar_i]:
        return bar_i, float(opens[bar_i])
    else:
        next_i = bar_i + 1
        exit_px = float(opens[next_i]) if next_i < len(opens) else eff_stop
        return bar_i, exit_px


def compute_oracle() -> pd.DataFrame:
    t0 = time.time()
    print("Loading snapshots ...")
    snaps = pd.read_parquet(SNAP_FILE)
    print(f"  {len(snaps):,} observations  ({len(snaps['episode_id'].unique()):,} episodes)")

    print("Loading 1s bars from catalog (direct parquet, study window) ...")
    import pyarrow.parquet as pq
    import glob as _glob
    pq_files = sorted(_glob.glob(str(Path(CATALOG_PATH) / "data/bar/NQ.XCME-1-SECOND-LAST-EXTERNAL/*.parquet")))
    if not pq_files:
        raise FileNotFoundError(f"No 1s parquet files in {CATALOG_PATH}")

    # Load bars covering the full study window plus generous forward buffer
    obs_min_ns = int(snaps["observation_time"].min())
    obs_max_ns = int(snaps["observation_time"].max())
    ns_start   = obs_min_ns - 2 * 60 * NS_PER_S
    ns_end     = obs_max_ns + (_MAX_H_NS + 600 * NS_PER_S)  # 300s + 10min buffer

    tbl = pq.read_table(
        pq_files,
        columns=["ts_event", "open", "high", "low"],
        filters=[("ts_event", ">=", ns_start), ("ts_event", "<=", ns_end)],
    )
    print(f"  {len(tbl):,} bars in {time.time()-t0:.1f}s")

    ts_arr = tbl["ts_event"].combine_chunks().to_numpy().astype(np.int64)
    op_arr = _decode_price(tbl["open"])
    hi_arr = _decode_price(tbl["high"])
    lo_arr = _decode_price(tbl["low"])
    del tbl

    # Take first observation per episode
    first_obs = (
        snaps.sort_values("step_index")
        .groupby("episode_id", sort=False)
        .first()
        .reset_index()
    )

    # Numpy arrays for fast access
    obs_ts_arr  = first_obs["observation_time"].to_numpy(dtype=np.int64)
    dir_arr     = first_obs["direction"].to_numpy(dtype=np.int64)
    atr_arr     = first_obs["atr_at_flip"].to_numpy(dtype=np.float64)
    flipcl_arr  = first_obs["flip_close"].to_numpy(dtype=np.float64)
    ep_end_arr  = first_obs["episode_end_time"].fillna(0).to_numpy(dtype=np.int64)
    period_arr  = first_obs["period"].to_numpy()
    ep_id_arr   = first_obs["episode_id"].to_numpy()

    total = len(obs_ts_arr)
    print(f"\nComputing oracle for {total:,} episodes ...")
    rows = []
    t_log = time.time()

    for i in range(total):
        obs_ts    = obs_ts_arr[i]
        direction = int(dir_arr[i])
        atr       = atr_arr[i]
        flip_cl   = flipcl_arr[i]
        ep_end    = int(ep_end_arr[i])

        stop_pts = CAT_STOP_ATR * atr
        stop_px  = flip_cl - direction * stop_pts

        # Entry bar: first bar at-or-after obs_ts
        eidx = int(np.searchsorted(ts_arr, obs_ts, side="left"))
        if eidx >= len(ts_arr):
            rows.append({
                "episode_id": ep_id_arr[i], "direction": direction,
                "atr_at_flip": atr, "entry_px": float("nan"), "stop_px": stop_px,
                "oracle_pnl": float("nan"), "hold_pnl": float("nan"),
                "oracle_exit_type": "censored", "period": period_arr[i],
            })
            continue

        entry_ts = ts_arr[eidx]
        entry_px = op_arr[eidx]

        # Cap: min(ep_end, entry_ts + 300s), but treat stale ep_end as no cap
        if ep_end > 0 and ep_end < entry_ts + _MAX_H_NS and ep_end > entry_ts:
            cap_ns = ep_end
        else:
            cap_ns = entry_ts + _MAX_H_NS

        cap_idx = int(np.searchsorted(ts_arr, cap_ns, side="left"))

        # Forward window (excludes entry bar itself)
        fwd_op = op_arr[eidx + 1: cap_idx + 1]
        fwd_hi = hi_arr[eidx + 1: cap_idx + 1]
        fwd_lo = lo_arr[eidx + 1: cap_idx + 1]
        fwd_ts = ts_arr[eidx + 1: cap_idx + 1]

        # Stop detection (same convention as labels.py)
        stop_idx, stop_fill = _find_stop(direction, stop_px, fwd_op, fwd_hi, fwd_lo)

        # Oracle exit
        if stop_idx is not None:
            oracle_pnl = direction * (stop_fill - entry_px) * NQ_MULTIPLIER - _COMM
            oracle_exit_type = "stop"
        elif len(fwd_op) == 0:
            oracle_pnl = -_COMM
            oracle_exit_type = "censored"
        else:
            # Find the best bar to exit (max favorable price in window)
            # Only scan up to stop bar if stopped (handled above)
            if direction == 1:
                best_i  = int(np.argmax(fwd_hi))
                exit_px = float(fwd_hi[best_i])
            else:
                best_i  = int(np.argmin(fwd_lo))
                exit_px = float(fwd_lo[best_i])
            oracle_pnl = direction * (exit_px - entry_px) * NQ_MULTIPLIER - _COMM
            oracle_exit_type = "oracle_peak"

        # Hold-to-episode-end baseline
        hold_exit_idx = min(cap_idx, len(op_arr) - 1)
        hold_pnl = (
            direction * (op_arr[hold_exit_idx] - entry_px) * NQ_MULTIPLIER - _COMM
            if hold_exit_idx > eidx and hold_exit_idx < len(op_arr) else float("nan")
        )

        rows.append({
            "episode_id":       ep_id_arr[i],
            "direction":        direction,
            "atr_at_flip":      atr,
            "entry_px":         entry_px,
            "stop_px":          stop_px,
            "oracle_pnl":       oracle_pnl,
            "hold_pnl":         hold_pnl,
            "oracle_exit_type": oracle_exit_type,
            "period":           period_arr[i],
        })

        if i > 0 and (i % 5000 == 0 or (time.time() - t_log) > 15):
            pct = 100.0 * i / total
            elapsed = time.time() - t0
            rate = i / elapsed
            eta = (total - i) / rate if rate > 0 else 0
            print(f"  {i:,}/{total:,} ({pct:.1f}%) | {elapsed:.0f}s | ETA {eta:.0f}s")
            t_log = time.time()

    out_df = pd.DataFrame(rows)
    out_df.to_parquet(OUT_FILE, index=False)
    print(f"\nOracle computed on {len(out_df):,} episodes -> {OUT_FILE}")

    for period in ["train", "val", "test"]:
        sub = out_df[out_df["period"] == period]
        if len(sub) == 0:
            continue
        valid = sub["oracle_pnl"].dropna()
        stop_pct = 100.0 * (sub["oracle_exit_type"] == "stop").mean()
        print(f"\n  [{period}]  n={len(sub):,}  oracle EV={valid.mean():+.1f}  "
              f"total={valid.sum():+,.0f}  "
              f"WR={100*(valid>0).mean():.1f}%  stop={stop_pct:.1f}%")
        hold_valid = sub["hold_pnl"].dropna()
        print(f"    hold EV={hold_valid.mean():+.1f}  total={hold_valid.sum():+,.0f}")

    return out_df


if __name__ == "__main__":
    compute_oracle()
