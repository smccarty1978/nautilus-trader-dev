"""Random + boundary parity sampler.

For a population of trades, sample:
  - 100 random trades (uniformly across the year)
  - 20 trades whose decision_ts falls within ±2s of an HTF bar
    boundary (close-of-bucket transitions). These stress the
    causality lookup logic.
  - 20 trades whose decision_ts falls within ±60s of a session
    boundary (RTH open 14:30 UTC, RTH close 21:00 UTC for 2024
    America/Chicago — adjust for DST or use the explicit minute
    bounds).

For each sampled trade, the caller is expected to compute the same
features in offline AND NT and assert exact (or tolerance) equality.

This module just builds the samples and labels them. Comparison is
the caller's responsibility (use parity_smoke.compare_smoke_runs
for the heavy lifting).
"""

from __future__ import annotations
import numpy as np
import pandas as pd
import pytz

CT = pytz.timezone("America/Chicago")


def sample_trades_for_parity(
    trades_df: pd.DataFrame,
    *,
    decision_ts_col: str = "decision_ts",
    n_random: int = 100,
    n_htf_boundary: int = 20,
    n_session_boundary: int = 20,
    htf_bucket_size_ns: int = 5 * 60 * 1_000_000_000,  # 5m default
    htf_boundary_window_ns: int = 2 * 1_000_000_000,    # ±2s
    session_boundary_window_ns: int = 60 * 1_000_000_000,  # ±60s
    rng_seed: int = 42,
) -> pd.DataFrame:
    """Returns a sampled subset with column `parity_sample_kind` in
    {"random", "htf_boundary", "session_boundary"}. Same trade may
    appear in multiple categories — kept as separate rows for
    clarity.
    """
    rng = np.random.default_rng(rng_seed)
    n = len(trades_df)
    if n == 0:
        return pd.DataFrame()

    out_rows = []

    # Random sample
    n_pick = min(n_random, n)
    rand_idx = rng.choice(n, size=n_pick, replace=False)
    rs = trades_df.iloc[rand_idx].copy()
    rs["parity_sample_kind"] = "random"
    out_rows.append(rs)

    # HTF-boundary sample
    ts = trades_df[decision_ts_col].values.astype("int64")
    # Distance from nearest HTF bucket close
    # bucket close at multiples of htf_bucket_size_ns (UTC epoch)
    mod = ts % htf_bucket_size_ns
    # Distance to previous boundary = mod; to next = bucket_size - mod
    dist_prev = mod
    dist_next = htf_bucket_size_ns - mod
    nearest_dist = np.minimum(dist_prev, dist_next)
    htf_mask = nearest_dist <= htf_boundary_window_ns
    htf_indices = np.where(htf_mask)[0]
    if len(htf_indices):
        n_pick = min(n_htf_boundary, len(htf_indices))
        pick = rng.choice(htf_indices, size=n_pick, replace=False)
        bs = trades_df.iloc[pick].copy()
        bs["parity_sample_kind"] = "htf_boundary"
        bs["distance_to_htf_bucket_close_ns"] = nearest_dist[pick]
        out_rows.append(bs)

    # Session boundary sample (RTH open / close in CT)
    # Use minute_of_day in CT — compute on the fly
    ts_dt_ct = pd.to_datetime(ts, unit="ns",
                                  utc=True).tz_convert(CT)
    minute = ts_dt_ct.hour * 60 + ts_dt_ct.minute
    # RTH open = 510 (08:30), close = 900 (15:00)
    dist_open_min = np.abs(minute - 510)
    dist_close_min = np.abs(minute - 900)
    nearest_session_min = np.minimum(dist_open_min, dist_close_min)
    sess_mask = (nearest_session_min * 60 * 1_000_000_000
                    <= session_boundary_window_ns)
    sess_indices = np.where(sess_mask)[0]
    if len(sess_indices):
        n_pick = min(n_session_boundary, len(sess_indices))
        pick = rng.choice(sess_indices, size=n_pick, replace=False)
        ss = trades_df.iloc[pick].copy()
        ss["parity_sample_kind"] = "session_boundary"
        ss["minutes_from_session_boundary"] = (
            nearest_session_min[pick])
        out_rows.append(ss)

    return pd.concat(out_rows, ignore_index=True) if out_rows \
        else pd.DataFrame()
