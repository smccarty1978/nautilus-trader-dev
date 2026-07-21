"""
2x2 Controlled Comparison: Entry Method × Exit Method

Isolates two independent questions:
  Q1: Is step-0 entry better than waiting for a later threshold crossing?
  Q2: Does dynamic confidence deterioration genuinely improve exits vs fixed 300s?

Four cells — all using identical 1s bar replay, no forward-label peeking:
  A: Step-0 entry (thr=Youden J)   + Fixed 300s exit
  B: Step-0 entry (thr=Youden J)   + Dynamic score exit
  C: First-crossing (thr=val-EV)   + Fixed 300s exit  [canonical / run_reconstruction]
  D: First-crossing (thr=val-EV)   + Dynamic score exit

Thresholds:
  Youden J  (cells A,B) = ridge_log_h300_thr from gate1_predictions.parquet (val AUC)
  val-EV    (cells C,D) = 0.5024 (percentile grid search, best val EV from run_reconstruction.py)

Stop fill convention (matches labels.py / oracle.py):
  Gap-through (bar.open crosses stop)       → fill at bar.open
  Intrabar touch (bar.low/high crosses stop) → fill at NEXT bar.open

Dynamic exit:
  At each subsequent 5s observation AFTER entry, if score < threshold:
    exit fills at the NEXT 1s bar open after that observation's timestamp.
  Stop takes precedence over dynamic exit within the same bar.

Same cleaned 6,669 test episodes as run_reconstruction.py
(boundary filter: discard obs where observation_time > episode_end_time).
"""
from __future__ import annotations

import math
import os
import sys
import time
from pathlib import Path
import glob as _glob

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

import numpy as np
import pandas as pd

from studies.rl_regime_feasibility.execution import (
    NQ_MULTIPLIER, CAT_STOP_ATR, NS_PER_S, COST_BASE,
)

CATALOG_PATH = "data/catalog/NQ_v0_2020_2026"
OUT_DIR      = Path("studies/rl_regime_feasibility/results")

_COMM     = COST_BASE.commission_rt_usd   # $5 RT base commission
_MULT     = float(NQ_MULTIPLIER)          # $20/point
_MAX_H_NS = int(300 * NS_PER_S)           # 300s max hold

# val-EV threshold (cells C, D): from run_reconstruction.py percentile grid
# search on validation set maximising EV/eligible-episode. Documented in
# results/audit_report.md "Threshold selected on validation: 0.5024"
THR_VAL_EV = 0.5024


def _decode_price(chunked_col) -> np.ndarray:
    parts = []
    for chunk in chunked_col.chunks:
        buf = chunk.buffers()[1]
        parts.append(np.frombuffer(buf, dtype="<i8"))
    return np.concatenate(parts).astype(np.float64) / 1e9


def _load_bars(snaps: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    import pyarrow.parquet as pq
    pq_files = sorted(_glob.glob(
        str(Path(CATALOG_PATH) / "data/bar/NQ.XCME-1-SECOND-LAST-EXTERNAL/*.parquet")
    ))
    if not pq_files:
        raise FileNotFoundError(f"No 1s parquet files found in {CATALOG_PATH}")

    obs_min = int(snaps["observation_time"].min())
    obs_max = int(snaps["observation_time"].max())
    ns_start = obs_min - 2 * 60 * NS_PER_S
    ns_end   = obs_max + _MAX_H_NS + 600 * NS_PER_S  # generous forward buffer

    tbl = pq.read_table(
        pq_files,
        columns=["ts_event", "open", "high", "low"],
        filters=[("ts_event", ">=", ns_start), ("ts_event", "<=", ns_end)],
    )
    ts = tbl["ts_event"].combine_chunks().to_numpy().astype(np.int64)
    op = _decode_price(tbl["open"])
    hi = _decode_price(tbl["high"])
    lo = _decode_price(tbl["low"])
    del tbl
    return ts, op, hi, lo


def _simulate_trade(
    entry_obs_ts: int,
    direction: int,
    stop_px: float,
    ep_end_ns: int,
    post_obs_ts: np.ndarray,
    post_obs_sc: np.ndarray,
    ts: np.ndarray,
    op: np.ndarray,
    hi: np.ndarray,
    lo: np.ndarray,
    exit_mode: str,
    threshold: float,
) -> tuple[float, str]:
    """
    Simulate one trade via exact 1s bar replay.

    entry_obs_ts  : observation_time where entry was triggered
                    (fills at OPEN of the 1s bar at/after this timestamp)
    post_obs_ts   : subsequent 5s observation times after entry (for dynamic exit)
    post_obs_sc   : model scores at post_obs_ts
    exit_mode     : 'fixed' | 'dynamic'

    Returns (pnl_usd, exit_type).
    """
    # Entry bar
    eidx = int(np.searchsorted(ts, entry_obs_ts, side='left'))
    if eidx >= len(ts):
        return -_COMM, 'censored'

    entry_ts = int(ts[eidx])
    entry_px = float(op[eidx])

    # Cap: min(ep_end, entry_ts + 300s). Stale ep_end (≤ entry_ts) uses 300s cap.
    if ep_end_ns > 0 and entry_ts < ep_end_ns < entry_ts + _MAX_H_NS:
        cap_ns = int(ep_end_ns)
    else:
        cap_ns = entry_ts + _MAX_H_NS

    fixed_exit_ns = entry_ts + _MAX_H_NS  # 300s target (may be beyond cap)

    # Build dynamic observation score map (ts_event → score, only within window)
    obs_sc_map: dict[int, float] = {}
    if exit_mode == 'dynamic':
        for obs_t, sc in zip(post_obs_ts, post_obs_sc):
            obs_t_i = int(obs_t)
            if entry_ts < obs_t_i <= cap_ns and not math.isnan(sc):
                obs_sc_map[obs_t_i] = float(sc)

    # Iterate 1s bars from entry+1 to cap+1 (extra bar for 'past cap' detection)
    cap_idx = int(np.searchsorted(ts, cap_ns, side='right'))
    end_idx = min(cap_idx + 2, len(ts))

    for bar_i in range(eidx + 1, end_idx):
        bar_ts = int(ts[bar_i])
        bar_o  = float(op[bar_i])
        bar_h  = float(hi[bar_i])
        bar_l  = float(lo[bar_i])

        # 1. Past window cap → exit at this bar's open
        if bar_ts > cap_ns:
            return direction * (bar_o - entry_px) * _MULT - _COMM, 'cap'

        # 2. Stop: gap-through (bar opens past stop) → fill at bar open
        if direction == 1 and bar_o <= stop_px:
            return direction * (bar_o - entry_px) * _MULT - _COMM, 'stop'
        if direction == -1 and bar_o >= stop_px:
            return direction * (bar_o - entry_px) * _MULT - _COMM, 'stop'

        # 3. Stop: intrabar touch → fill at NEXT bar open (matches labels.py convention)
        if direction == 1 and bar_l <= stop_px:
            ni   = bar_i + 1
            fill = float(op[ni]) if ni < len(ts) else stop_px
            return direction * (fill - entry_px) * _MULT - _COMM, 'stop'
        if direction == -1 and bar_h >= stop_px:
            ni   = bar_i + 1
            fill = float(op[ni]) if ni < len(ts) else stop_px
            return direction * (fill - entry_px) * _MULT - _COMM, 'stop'

        # 4. Dynamic exit: observation at this bar with score < threshold
        #    → exit fills at NEXT bar open (score is known at close of bar_ts)
        if exit_mode == 'dynamic' and bar_ts in obs_sc_map:
            if obs_sc_map[bar_ts] < threshold:
                ni      = bar_i + 1
                exit_px = float(op[ni]) if ni < len(ts) else bar_o
                return direction * (exit_px - entry_px) * _MULT - _COMM, 'dynamic'

        # 5. Fixed exit: first bar at/after 300s from entry
        if exit_mode == 'fixed' and bar_ts >= fixed_exit_ns:
            return direction * (bar_o - entry_px) * _MULT - _COMM, 'fixed'

    return -_COMM, 'censored'


def _run_cell(
    episodes: list,
    ts: np.ndarray,
    op: np.ndarray,
    hi: np.ndarray,
    lo: np.ndarray,
    entry_rule: str,
    threshold: float,
    exit_mode: str,
) -> dict:
    """Run one 2×2 cell across all episodes. Returns summary dict."""
    pnls: list[float] = []
    records: list[dict] = []

    for ep in episodes:
        obs_times = ep['obs_times']   # int64 array, sorted by step_index
        scores    = ep['scores']      # float64 array (may contain NaN)
        direction = ep['direction']
        stop_px   = ep['flip_close'] - direction * CAT_STOP_ATR * ep['atr']
        ep_end_ns = ep['ep_end_ns']

        # Determine entry observation index
        entry_idx: int | None = None
        if entry_rule == 'step0':
            s0 = scores[0]
            if not math.isnan(s0) and s0 >= threshold:
                entry_idx = 0
        else:  # 'first_crossing': any step
            for i, s in enumerate(scores):
                if not math.isnan(s) and s >= threshold:
                    entry_idx = i
                    break

        if entry_idx is None:
            pnls.append(0.0)
            continue

        pnl, exit_type = _simulate_trade(
            entry_obs_ts = int(obs_times[entry_idx]),
            direction    = direction,
            stop_px      = stop_px,
            ep_end_ns    = ep_end_ns,
            post_obs_ts  = obs_times[entry_idx + 1:],
            post_obs_sc  = scores[entry_idx + 1:],
            ts=ts, op=op, hi=hi, lo=lo,
            exit_mode    = exit_mode,
            threshold    = threshold,
        )

        pnls.append(pnl)
        records.append({
            'episode_id': ep['episode_id'],
            'pnl':        pnl,
            'exit_type':  exit_type,
            'entry_step': entry_idx,
        })

    pnl_arr = np.array(pnls, dtype=np.float64)
    traded   = len(records)
    n_eps    = len(pnls)

    np.random.seed(42)
    boot_means = [
        np.random.choice(pnl_arr, size=n_eps, replace=True).mean()
        for _ in range(1000)
    ]
    ci = (np.percentile(boot_means, 2.5), np.percentile(boot_means, 97.5))

    exit_counts = {}
    for r in records:
        et = r['exit_type']
        exit_counts[et] = exit_counts.get(et, 0) + 1

    return {
        'ev':         float(pnl_arr.mean()),
        'n_eps':      n_eps,
        'traded':     traded,
        'trade_rate': traded / n_eps,
        'total_pnl':  float(pnl_arr.sum()),
        'ci':         ci,
        'pnl_arr':    pnl_arr,
        'exit_counts': exit_counts,
        'records':    pd.DataFrame(records),
    }


def main() -> None:
    t0 = time.time()

    print("Loading features + predictions ...")
    snaps = pd.read_parquet(OUT_DIR / "feature_snapshots.parquet")
    preds = pd.read_parquet(OUT_DIR / "gate1_predictions.parquet")

    # Youden J threshold for ridge_log h300 (from gate1_predictions, val AUC)
    thr_youden = float(preds['ridge_log_h300_thr'].iloc[0])
    print(f"  Youden J threshold (ridge_log h300): {thr_youden:.6f}")
    print(f"  val-EV threshold   (ridge_log h300): {THR_VAL_EV:.4f}")

    # Merge predictions into snapshots
    df = snaps.merge(
        preds[["observation_time", "ridge_log_h300_prob"]],
        on="observation_time", how="left",
    )

    # Boundary filter (matches run_reconstruction.py exactly)
    valid = df["observation_time"] <= df["episode_end_time"]
    n_removed = int((~valid).sum())
    print(f"  Removed {n_removed:,} post-episode-end observations")
    df = df[valid].copy()

    test = df[df["period"] == "test"]

    # Build episode list (sorted observations per episode)
    print("Building episode index ...")
    episodes = []
    for ep_id, ep_df in test.groupby("episode_id", sort=False):
        ep_df = ep_df.sort_values("step_index")
        r0    = ep_df.iloc[0]
        ep_end_raw = r0["episode_end_time"]
        episodes.append({
            'episode_id': ep_id,
            'obs_times':  ep_df["observation_time"].to_numpy(dtype=np.int64),
            'scores':     ep_df["ridge_log_h300_prob"].to_numpy(dtype=np.float64),
            'direction':  int(r0["direction"]),
            'atr':        float(r0["atr_at_flip"]),
            'flip_close': float(r0["flip_close"]),
            'ep_end_ns':  int(ep_end_raw) if pd.notna(ep_end_raw) else 0,
        })
    print(f"  {len(episodes):,} test episodes")

    print("Loading 1s bars ...")
    ts, op, hi, lo = _load_bars(snaps)
    print(f"  {len(ts):,} bars loaded in {time.time()-t0:.1f}s\n")

    # 2x2 cell definitions
    cells = [
        ('A', 'step0',          thr_youden,  'fixed',   'Step-0, Youden J,   Fixed 300s'),
        ('B', 'step0',          thr_youden,  'dynamic', 'Step-0, Youden J,   Dynamic score exit'),
        ('C', 'first_crossing', THR_VAL_EV,  'fixed',   'First crossing, val-EV, Fixed 300s  [canonical]'),
        ('D', 'first_crossing', THR_VAL_EV,  'dynamic', 'First crossing, val-EV, Dynamic score exit'),
    ]

    print("=" * 80)
    print("  2x2 CONTROLLED COMPARISON  --  ridge_log_h300  --  test set 2025-03 to 2025-05")
    print("=" * 80)
    print(f"\n  {'Cell':<4} {'Threshold':>10} {'Exit':<9} {'EV/ep':>10} {'Trade%':>8} "
          f"{'Total PnL':>12} {'95% CI (bootstrap)':>26}")
    print("  " + "-" * 82)

    results = {}
    for cell_id, entry_rule, threshold, exit_mode, label in cells:
        t_cell = time.time()
        res    = _run_cell(episodes, ts, op, hi, lo, entry_rule, threshold, exit_mode)
        ci     = res['ci']
        elapsed = time.time() - t_cell
        print(f"  {cell_id}   {threshold:>10.4f} {exit_mode:<9} {res['ev']:>+10.2f} "
              f"{res['trade_rate']:>7.1%}  {res['total_pnl']:>+12,.0f}  "
              f"({ci[0]:>+8.2f}, {ci[1]:>+8.2f})  [{elapsed:.0f}s]")
        print(f"       {label}")
        ec = res['exit_counts']
        print(f"       exits: " + "  ".join(f"{k}={v}" for k, v in sorted(ec.items())))
        results[cell_id] = res

    print("\n" + "=" * 80)
    print("INTERPRETATION:")
    print(f"  A->B  (same step-0 entry, fixed vs dynamic exit):   "
          f"delta = {results['B']['ev'] - results['A']['ev']:+.2f}/ep")
    print(f"  C->D  (same first-X entry, fixed vs dynamic exit):  "
          f"delta = {results['D']['ev'] - results['C']['ev']:+.2f}/ep")
    print(f"  A->C  (same fixed exit, step-0 vs first-X entry):   "
          f"delta = {results['C']['ev'] - results['A']['ev']:+.2f}/ep")
    print(f"  B->D  (same dynamic exit, step-0 vs first-X entry): "
          f"delta = {results['D']['ev'] - results['B']['ev']:+.2f}/ep")
    print("=" * 80)
    print(f"Total elapsed: {time.time()-t0:.0f}s")

    # Save cell results
    rows = []
    for cell_id, entry_rule, threshold, exit_mode, label in cells:
        res = results[cell_id]
        rows.append({
            'cell':       cell_id,
            'label':      label,
            'entry_rule': entry_rule,
            'threshold':  threshold,
            'exit_mode':  exit_mode,
            'ev_per_ep':  res['ev'],
            'trade_rate': res['trade_rate'],
            'total_pnl':  res['total_pnl'],
            'n_eps':      res['n_eps'],
            'n_traded':   res['traded'],
            'ci_lo':      res['ci'][0],
            'ci_hi':      res['ci'][1],
        })
    out_path = OUT_DIR / "2x2_results.parquet"
    pd.DataFrame(rows).to_parquet(out_path, index=False)
    print(f"Saved {out_path}")


if __name__ == "__main__":
    main()
