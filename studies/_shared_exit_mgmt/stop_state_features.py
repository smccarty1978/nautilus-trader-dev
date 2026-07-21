"""Phase 4 support: causal state features for the conditional
recovery-MAE stop tables -- weakness decile, persistence bucket, and
score path. All computed from information available AT the checkpoint
(the model's own prediction and this trade's own PAST checkpoints
only) -- these are live-decision-eligible features, unlike
recovery_dynamics.py's forward-looking labels.

Population-agnostic: takes a pre-scored atlas (with a
`pred_weakness_prob` and `decile` column already attached by the
caller) and adds `persistence_bucket` and `score_path` per trade.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

WEAK_DECILE_THRESHOLD = 5  # D5-D10 = "weak territory" per study spec
PERSISTENCE_BUCKETS = ["first_touch", "10s", "20s", "30s"]
SCORE_PATH_LOOKBACK_S = 10.0
SCORE_PATH_EPS = 0.01


def _persistence_bucket(elapsed_s: float) -> str:
    if elapsed_s < 10.0:
        return "first_touch"
    if elapsed_s < 20.0:
        return "10s"
    if elapsed_s < 30.0:
        return "20s"
    return "30s"


def _state_features_one_trade(g: pd.DataFrame) -> pd.DataFrame:
    g = g.sort_values("checkpoint_ts")
    sort_order = g.index
    g = g.reset_index(drop=True)
    n = len(g)
    decile = g["decile"].to_numpy()
    prob = g["pred_weakness_prob"].to_numpy(dtype=float)
    ts = g["checkpoint_ts"].to_numpy(dtype=np.int64)

    is_weak = decile >= WEAK_DECILE_THRESHOLD
    persistence_bucket = np.full(n, "", dtype=object)
    score_path = np.full(n, "flat", dtype=object)

    weak_entry_ts = None
    lookback_i = 0  # two-pointer for the 10s-ago lookup
    for i in range(n):
        if is_weak[i]:
            if weak_entry_ts is None:
                weak_entry_ts = ts[i]
            elapsed_s = (ts[i] - weak_entry_ts) / 1e9
            persistence_bucket[i] = _persistence_bucket(elapsed_s)
        else:
            weak_entry_ts = None
            persistence_bucket[i] = ""

        target_ts = ts[i] - int(SCORE_PATH_LOOKBACK_S * 1e9)
        while lookback_i < i and ts[lookback_i] < target_ts:
            lookback_i += 1
        if ts[lookback_i] <= ts[i] and lookback_i < i:
            prior_prob = prob[lookback_i]
            if prob[i] > prior_prob + SCORE_PATH_EPS:
                score_path[i] = "rising"
            elif prob[i] < prior_prob - SCORE_PATH_EPS:
                score_path[i] = "improving"
            else:
                score_path[i] = "flat"
        else:
            score_path[i] = "flat"  # not enough history yet

    return pd.DataFrame({
        "persistence_bucket": pd.Categorical(persistence_bucket),
        "score_path": pd.Categorical(score_path),
    }, index=sort_order)


def add_state_features(atlas: pd.DataFrame) -> pd.DataFrame:
    """Adds persistence_bucket/score_path columns to atlas (assigned
    back by index -- avoids holding a second full-atlas-sized copy)."""
    pieces = []
    for _, g in atlas.groupby("trade_id", sort=False):
        pieces.append(_state_features_one_trade(g))
    new_cols = pd.concat(pieces)
    atlas["persistence_bucket"] = new_cols["persistence_bucket"].astype(str)
    atlas["score_path"] = new_cols["score_path"].astype(str)
    return atlas
