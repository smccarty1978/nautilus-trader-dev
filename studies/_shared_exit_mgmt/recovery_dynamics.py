"""Phase 4 support: per-checkpoint recovery dynamics, computed fresh
from the Phase 1 atlas (population-agnostic -- operates on any atlas
produced by build_atlas.py).

These are DISTINCT from Phase 1's remaining_mfe_atr /
remaining_mae_before_next_mfe_atr (which are anchored to ENTRY and to
"next NEW high"). Phase 4 needs quantities anchored to the
CHECKPOINT'S OWN current level, and to "recovery to the PRIOR high"
(which may just retrace back up, not necessarily exceed it):

  - recovery_mae_from_checkpoint_atr[i]: worst drawdown, measured FROM
    this checkpoint's own current_pnl_atr_from_entry level, occurring
    before price first recovers back to >= that level (or NaN if it
    never recovers before trade end).
  - recovery_mae_from_mfe_atr[i]: worst GIVEBACK (measured from the
    already-achieved mfe_atr_from_entry[i]) occurring before price
    first recovers to >= mfe_atr_from_entry[i] (i.e. the deepest point
    of the pullback that is eventually round-tripped).
  - time_to_recovery_s[i]: seconds from this checkpoint to the first
    future checkpoint where pnl recovers to >= mfe_atr_from_entry[i].
    NaN if it never recovers (eventual_recovery_to_prior_mfe is False).
  - time_to_failure_s[i]: seconds from this checkpoint to the trade's
    terminal checkpoint, ONLY for rows that never recover (NaN
    otherwise) -- "how long did this weak state persist before the
    trade ended."

Like Phase 1's labels, these are strictly offline, post-hoc
computations over each trade's own already-closed path -- never fed
back as live features, per CLAUDE.md's ML label-construction rule.
"""
from __future__ import annotations
import numpy as np
import pandas as pd


def _recovery_dynamics_one_trade(g: pd.DataFrame) -> pd.DataFrame:
    orig_index = g.index
    g = g.sort_values("checkpoint_ts")
    sort_order = g.index  # preserve original atlas index, sorted by ts
    g = g.reset_index(drop=True)
    n = len(g)
    pnl = g["current_pnl_atr_from_entry"].to_numpy(dtype=float)
    mfe = g["mfe_atr_from_entry"].to_numpy(dtype=float)
    ts = g["checkpoint_ts"].to_numpy(dtype=np.int64)

    recovery_mae_from_checkpoint = np.full(n, np.nan)
    recovery_mae_from_mfe = np.full(n, np.nan)
    time_to_recovery_s = np.full(n, np.nan)
    time_to_failure_s = np.full(n, np.nan)

    last_ts = ts[-1]
    i = 0
    while i < n:
        # Plateau: rows sharing the same mfe threshold (recovery target).
        plateau_end = i
        while plateau_end + 1 < n and mfe[plateau_end + 1] == mfe[i]:
            plateau_end += 1
        threshold = mfe[i]

        # Single backward pass over [i, n) to find, for every position
        # k in this plateau, the first future index >= k+1 where
        # pnl >= threshold (recovery_idx), reused across the whole
        # plateau since the threshold is constant within it.
        recovery_idx_from = np.full(n - i, -1, dtype=np.int64)
        next_hit = -1
        for k in range(n - 1, i, -1):  # positions strictly after i (k>i)
            if pnl[k] >= threshold:
                next_hit = k
            recovery_idx_from[k - i] = next_hit

        for row in range(i, plateau_end + 1):
            rec_idx = recovery_idx_from[row - i] if row - i < len(recovery_idx_from) else -1
            if rec_idx > row:
                # Recovered: worst point in (row, rec_idx]
                window_pnl = pnl[row + 1: rec_idx + 1]
                recovery_mae_from_checkpoint[row] = max(
                    0.0, pnl[row] - window_pnl.min()) if len(window_pnl) else 0.0
                recovery_mae_from_mfe[row] = max(
                    0.0, threshold - window_pnl.min()) if len(window_pnl) else 0.0
                time_to_recovery_s[row] = (ts[rec_idx] - ts[row]) / 1e9
            else:
                # Never recovers before trade end
                time_to_failure_s[row] = (last_ts - ts[row]) / 1e9
        i = plateau_end + 1

    # Return ONLY the new columns, indexed by the ORIGINAL atlas index
    # (not a full copy of every existing column) -- keeps the per-trade
    # concat step's memory footprint to ~4 float32 columns instead of
    # the entire ~24-column atlas, which matters at 30M+ rows.
    return pd.DataFrame({
        "recovery_mae_from_checkpoint_atr": recovery_mae_from_checkpoint.astype("float32"),
        "recovery_mae_from_mfe_atr": recovery_mae_from_mfe.astype("float32"),
        "time_to_recovery_s": time_to_recovery_s.astype("float32"),
        "time_to_failure_s": time_to_failure_s.astype("float32"),
    }, index=sort_order)


def add_recovery_dynamics(atlas: pd.DataFrame) -> pd.DataFrame:
    """Adds 4 new float32 columns to atlas (assigned back by index --
    does not require holding a second full-atlas-sized copy)."""
    pieces = []
    for _, g in atlas.groupby("trade_id", sort=False):
        pieces.append(_recovery_dynamics_one_trade(g))
    new_cols = pd.concat(pieces)
    for c in new_cols.columns:
        atlas[c] = new_cols[c]
    return atlas
