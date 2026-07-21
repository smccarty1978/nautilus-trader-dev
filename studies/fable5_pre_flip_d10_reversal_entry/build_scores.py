"""Score every 2025/2026 checkpoint with the frozen W4 model (causal stream).

Output: _work/causal_scores.parquet — one row per atlas checkpoint in
2025/2026 with the frozen score. Feature values are the atlas's own causal
checkpoint features (identical convention to training — no train/serve skew
is introduced because serving reuses the same feature pipeline rows).

Score availability convention (see SPEC.md): the score at observation_time=T
is computed from 1s bars opening <= T (includes the close of bar [T, T+1))
and is therefore causally available at wall clock T + 1s. Consumers key on
that availability rule; this file just carries observation_time.

regime_start_ns is reconstructed as observation_time - round(regime_age)*1e9
in integer nanoseconds (regime_age is an exact multiple of the checkpoint
step, so this is exact — unlike the float-noise regime_start_time in the
upstream predictions file).
"""
from __future__ import annotations

import pickle
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from studies.fable5_pre_flip_d10_reversal_entry.common import (
    ATLAS_PATH, ECON_WINDOWS, NS_PER_S, WORK, is_rth,
)

NAN_GATE = "aligned_price_minus_center_5m"


def main() -> None:
    t0 = time.time()
    with open(WORK / "w4_fable5.pkl", "rb") as f:
        bundle = pickle.load(f)
    model, feats = bundle["model"], bundle["features"]

    cols = list(dict.fromkeys(
        feats + [NAN_GATE, "observation_time", "direction", "regime_age",
                 "atr", "close", "current_pnl", "current_mfe", "current_mae",
                 "giveback", "period"]
    ))
    print("Loading 2025/2026 checkpoint rows (val+test+secondary_oos)...")
    df = pd.read_parquet(
        ATLAS_PATH, columns=cols,
        filters=[("period", "in", ["val", "test", "secondary_oos"])],
    )
    print(f"  {len(df):,} rows ({time.time()-t0:.0f}s)")

    # Rows failing the upstream NaN gate exist in the atlas but were never
    # scoreable by the trained model — keep them with score = NaN so the
    # coverage report can count them as score-unavailable, not silently drop.
    valid = df[NAN_GATE].notna().to_numpy()
    scores = np.full(len(df), np.nan)
    X = df.loc[valid, feats].to_numpy()
    print(f"  scoring {valid.sum():,} valid rows...")
    # chunk to bound memory
    out = np.empty(len(X))
    step = 500_000
    for i in range(0, len(X), step):
        out[i:i + step] = model.predict_proba(X[i:i + step])[:, 1]
    scores[valid] = out

    obs = df["observation_time"].to_numpy(dtype=np.int64)
    age_s = np.rint(df["regime_age"].to_numpy()).astype(np.int64)
    res = pd.DataFrame({
        "observation_time": obs,
        "direction": df["direction"].to_numpy(dtype=np.int8),
        "regime_start_ns": obs - age_s * NS_PER_S,
        "regime_age": df["regime_age"].to_numpy(),
        "atr": df["atr"].to_numpy(),
        "close": df["close"].to_numpy(),
        "current_pnl": df["current_pnl"].to_numpy(),
        "current_mfe": df["current_mfe"].to_numpy(),
        "current_mae": df["current_mae"].to_numpy(),
        "giveback": df["giveback"].to_numpy(),
        "period": df["period"].to_numpy(),
        "score_valid": valid,
        "w4_score": scores,
    })
    res["year"] = pd.to_datetime(res["observation_time"], unit="ns", utc=True).dt.year
    res["rth"] = is_rth(res["observation_time"].to_numpy())
    # Persist the economics-window flag so every consumer (events, placebos)
    # shares one definition — donors from the Jan-Feb 2025 threshold
    # calibration window must never enter the placebo pool.
    econ = np.zeros(len(res), dtype=bool)
    for yr, (s, e) in ECON_WINDOWS.items():
        m = ((res["year"] == yr)
             & (res["observation_time"] >= s.value)
             & (res["observation_time"] < e.value))
        econ |= m.to_numpy()
    res["in_econ_window"] = econ
    res = res.sort_values(["regime_start_ns", "observation_time"], kind="stable")
    res.to_parquet(WORK / "causal_scores.parquet", index=False)
    print(f"Wrote {len(res):,} score rows -> _work/causal_scores.parquet "
          f"({time.time()-t0:.0f}s total)")


if __name__ == "__main__":
    main()
