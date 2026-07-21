"""Phase 2: old (flip-close-anchored) vs corrected (entry-fill-anchored)
skew audit.

The OLD reference is studies/regime_sequence_chop_context/results/
weakness_checkpoint_atlas.parquet (pandas-built, F1 = all-flips
population, 5s-cadence checkpoints keyed by `observation_time`,
PnL/MFE/MAE/giveback all computed from `flip_close`, per its
build_weakness_atlas.py -- confirmed by codebase survey 2026-07-11).
It is NOT NT-executable and is used HERE ONLY as a diagnostic
comparison target (per CLAUDE.md's allowance for pandas in "post-hoc
analysis of NT-generated results"), never as a training source and
never joined back into any live decision.

The two atlases are on different grids (old: 5s cadence, origin =
flip bar close, `regime_age` = seconds since flip; new: 1s cadence,
origin = actual NT fill, `age_seconds` = seconds since fill) so no
literal row-for-row join exists. This script:
  1. Computes entry_price_minus_flip_close_atr per NEW trade directly
     (no old-atlas dependency) -- the purest measure of the anchor
     correction itself.
  2. Matches each NEW trade to an OLD episode by (direction, flip
     bar's close timestamp) with a small tolerance, then compares
     PnL/MFE/giveback at the NEW checkpoint's nearest available OLD
     `observation_time` (backward-only, i.e. the latest old checkpoint
     at or before the new checkpoint's true elapsed time from flip).
"""
from __future__ import annotations
import sys
from pathlib import Path

_repo_root = Path(__file__).parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

import numpy as np
import pandas as pd

OLD_ATLAS_PATH = ("studies/regime_sequence_chop_context/results/"
                     "weakness_checkpoint_atlas.parquet")
OLD_ATLAS_COLS = [
    "observation_time", "direction", "regime_age", "current_pnl",
    "current_mfe", "current_mae", "giveback", "state_class",
]


def load_old_atlas_window(start_ns: int, end_ns: int) -> pd.DataFrame:
    df = pd.read_parquet(
        OLD_ATLAS_PATH, columns=OLD_ATLAS_COLS,
        filters=[("observation_time", ">=", start_ns),
                    ("observation_time", "<=", end_ns)])
    return df


def trade_level_from_atlas(atlas: pd.DataFrame) -> pd.DataFrame:
    """One row per trade_id, taking entry-level fields (constant within
    a trade) directly from the labeled atlas -- avoids any separate
    raw-trades.parquet reference and the id-offset mismatch that
    creates (atlas.trade_id is year-offset; raw trades.parquet is not)."""
    cols = ["trade_id", "direction", "entry_ts", "entry_px",
               "regime_start_ts", "atr_at_entry"]
    return atlas[cols].drop_duplicates("trade_id").reset_index(drop=True)


def entry_price_vs_flip_close(trade_level: pd.DataFrame,
                                   bars_1m: pd.DataFrame) -> pd.DataFrame:
    """entry_price_minus_flip_close_atr per trade -- purely a property
    of the NEW atlas's own entries; no old-atlas dependency.

    bars_1m must have columns: close_ts (ts_init, int64), close (float).
    """
    flip_close = bars_1m.set_index("close_ts")["close"]
    out = trade_level.copy()
    out["flip_close_px"] = out["regime_start_ts"].map(flip_close)
    out["entry_price_minus_flip_close_atr"] = (
        (out["entry_px"] - out["flip_close_px"]) * out["direction"]
        / out["atr_at_entry"].replace(0, np.nan))
    return out


def match_and_compare(trades: pd.DataFrame, old_atlas: pd.DataFrame,
                          checkpoints: pd.DataFrame,
                          tolerance_ns: int = 65_000_000_000,
                          match_mode: str = "backward") -> pd.DataFrame:
    """For each NEW trade, find the OLD EPISODE (same direction, same
    flip-anchor instant) within `tolerance_ns` of the trade's
    regime_start_ts, then compare fields at matched elapsed-time-since-
    flip, restricted to THAT episode's own rows only (never a
    same-regime_age row from an unrelated episode on a different day).

    match_mode:
      "backward" -- nearest OLD observation strictly AT OR BEFORE the
          new checkpoint's true elapsed time. Causally conservative
          (never uses a future old observation) but biases MFE/pnl
          comparisons DOWNWARD by construction (an earlier old
          checkpoint has had less time to accumulate MFE) -- report
          alongside "nearest" to separate real anchor skew from this
          artifact.
      "nearest" -- nearest OLD observation by absolute time distance
          (may be slightly after the new checkpoint's elapsed time,
          up to the old atlas's own 30s cadence). Not causally
          conservative, but unbiased for skew MEASUREMENT purposes
          (this is offline diagnostic comparison, not a live decision).
    """
    # NOTE on scale: a naive O(n_trades * n_old_rows) scan (an earlier
    # version of this function) is only viable on small samples (e.g.
    # a 2-week smoke test). At full multi-year scale (tens of
    # thousands of trades against millions of old-atlas rows) this
    # becomes O(10^11) and never finishes. This version uses
    # searchsorted for O(log n) episode lookup and a precomputed
    # trade_id -> row-index map for O(1) checkpoint access, giving
    # O(n_trades * log(n_old)) overall.
    rows = []
    old_by_dir = {d: g.sort_values("observation_time").reset_index(drop=True)
                     for d, g in old_atlas.groupby("direction")}
    # old_flip_ts is a non-decreasing "staircase" (constant within an
    # episode, jumps at the next episode) since observation_time is
    # sorted and regime_age resets to 30 at each new episode -- valid
    # input for searchsorted.
    old_flip_ts_by_dir = {
        d: (og["observation_time"] - (og["regime_age"] * 1e9).astype("int64")).values
        for d, og in old_by_dir.items()
    }

    cp_sorted = checkpoints.sort_values(["trade_id", "checkpoint_ts"])
    cp_ts = cp_sorted["checkpoint_ts"].to_numpy()
    cp_pnl = cp_sorted["current_pnl_atr_from_entry"].to_numpy()
    cp_mfe = cp_sorted["mfe_atr_from_entry"].to_numpy()
    cp_giveback = cp_sorted["giveback_atr_from_entry"].to_numpy()
    cp_label = cp_sorted["terminal_weakness_label"].to_numpy()
    cp_indices = cp_sorted.groupby("trade_id", sort=False).indices

    for _, tr in trades.iterrows():
        d = int(tr["direction"])
        if d not in old_by_dir:
            continue
        og = old_by_dir[d]
        old_flip_ts = old_flip_ts_by_dir[d]
        regime_start = int(tr["regime_start_ts"])
        pos = np.searchsorted(old_flip_ts, regime_start)
        candidates = [i for i in (pos - 1, pos) if 0 <= i < len(old_flip_ts)]
        if not candidates:
            continue
        best = min(candidates, key=lambda i: abs(int(old_flip_ts[i]) - regime_start))
        if abs(int(old_flip_ts[best]) - regime_start) > tolerance_ns:
            continue  # no matching old episode within tolerance

        # Episode row range via searchsorted on the staircase array
        # (never a different episode sharing a regime_age value on an
        # unrelated day).
        ep_start = np.searchsorted(old_flip_ts, old_flip_ts[best], side="left")
        ep_end = np.searchsorted(old_flip_ts, old_flip_ts[best], side="right")
        og_ep = og.iloc[ep_start:ep_end]
        og_elapsed = og_ep["regime_age"].values
        if len(og_elapsed) == 0:
            continue

        idxs = cp_indices.get(tr["trade_id"])
        if idxs is None or len(idxs) == 0:
            continue
        n = len(idxs)
        sample_positions = sorted(set(
            [0, n // 4, n // 2, (3 * n) // 4, n - 1]))
        for sp in sample_positions:
            row_i = idxs[sp]
            checkpoint_ts = int(cp_ts[row_i])
            elapsed_from_flip_s = (checkpoint_ts - regime_start) / 1e9
            if match_mode == "backward":
                mask = og_elapsed <= elapsed_from_flip_s
                if not mask.any():
                    continue
                match_i = int(np.where(mask)[0][-1])
            else:  # "nearest"
                match_i = int(np.argmin(np.abs(og_elapsed - elapsed_from_flip_s)))
            old_row = og_ep.iloc[match_i]
            rows.append({
                "trade_id": tr["trade_id"],
                "direction": d,
                "match_mode": match_mode,
                "checkpoint_ts": checkpoint_ts,
                "elapsed_from_flip_s": elapsed_from_flip_s,
                "old_regime_age_matched": old_row["regime_age"],
                "current_pnl_old_minus_corrected_atr": (
                    old_row["current_pnl"] - cp_pnl[row_i]),
                "mfe_old_minus_corrected_atr": (
                    old_row["current_mfe"] - cp_mfe[row_i]),
                "giveback_old_minus_corrected_atr": (
                    old_row["giveback"] - cp_giveback[row_i]),
                "old_state_class": old_row["state_class"],
                "new_terminal_label": cp_label[row_i],
            })
    return pd.DataFrame(rows)


def summarize_skew(matched: pd.DataFrame) -> dict:
    if len(matched) == 0:
        return {"n_matched": 0}
    out = {"n_matched": int(len(matched))}
    for col in ("current_pnl_old_minus_corrected_atr",
                   "mfe_old_minus_corrected_atr",
                   "giveback_old_minus_corrected_atr"):
        v = matched[col].dropna()
        out[f"{col}_median"] = float(v.median()) if len(v) else float("nan")
        out[f"{col}_p90"] = float(v.abs().quantile(0.9)) if len(v) else float("nan")
        out[f"{col}_max"] = float(v.abs().max()) if len(v) else float("nan")
    return out
