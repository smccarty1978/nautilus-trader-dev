"""CODEX 5.X causal completed-regime history for open-stamped 1s bars."""
from __future__ import annotations

import numpy as np
import pandas as pd


def build_completed_regimes(df_1m: pd.DataFrame,
                            df_1s: pd.DataFrame) -> pd.DataFrame:
    """Extract completed regimes using exact half-open [start,end) bars."""
    minute = df_1m.copy()
    minute["prev_regime"] = minute["regime"].shift(1).fillna(0).astype(int)
    flips = minute[
        (minute["regime"] != 0)
        & (minute["prev_regime"] != 0)
        & (minute["regime"] != minute["prev_regime"])
    ]
    one_second = df_1s.copy()
    if isinstance(one_second.index, pd.DatetimeIndex):
        one_second.index = one_second.index.view(np.int64)
    if not one_second.index.is_monotonic_increasing or not one_second.index.is_unique:
        raise RuntimeError("1s ts_event index must be strictly increasing and unique")
    index = one_second.index.to_numpy(dtype=np.int64, copy=False)

    records: list[dict] = []
    flip_rows = list(flips.itertuples())
    for i in range(len(flip_rows) - 1):
        first, second = flip_rows[i], flip_rows[i + 1]
        direction = int(first.regime)
        start, end = int(first.close_ts), int(second.close_ts)
        left = int(np.searchsorted(index, start, side="left"))
        right = int(np.searchsorted(index, end, side="left"))
        bars = one_second.iloc[left:right]
        if bars.empty:
            continue
        start_price = float(bars.iloc[0]["open"])
        end_price = float(bars.iloc[-1]["close"])
        closes = bars["close"].to_numpy(dtype=float)
        highs = bars["high"].to_numpy(dtype=float)
        lows = bars["low"].to_numpy(dtype=float)
        volumes = bars["volume"].to_numpy(dtype=float)
        mfe = float(np.max(highs - start_price) if direction == 1
                    else np.max(start_price - lows))
        mae = float(np.max(start_price - lows) if direction == 1
                    else np.max(highs - start_price))
        total_abs_move = float(np.abs(np.diff(closes)).sum())
        net_aligned = direction * (end_price - start_price)
        fav_extremes = 0
        adv_extremes = 0
        if direction == 1:
            running_fav, running_adv = -np.inf, np.inf
            for value in highs:
                if value > running_fav:
                    running_fav = value
                    fav_extremes += 1
            for value in lows:
                if value < running_adv:
                    running_adv = value
                    adv_extremes += 1
        else:
            running_fav, running_adv = np.inf, -np.inf
            for value in lows:
                if value < running_fav:
                    running_fav = value
                    fav_extremes += 1
            for value in highs:
                if value > running_adv:
                    running_adv = value
                    adv_extremes += 1
        records.append({
            "regime_index": i, "direction": direction,
            "start_time": start, "end_time": end,
            "duration": (end - start) / 1e9,
            "start_price": start_price, "end_price": end_price,
            "net_aligned_move": net_aligned, "MFE": mfe, "MAE": mae,
            "range": float(highs.max() - lows.min()),
            "directional_efficiency": (
                net_aligned / total_abs_move if total_abs_move > 0 else 0.0
            ),
            "volume": float(volumes.sum()),
            "regime_center": float(np.median(closes)),
            "fav_extremes": fav_extremes, "adv_extremes": adv_extremes,
        })
    return pd.DataFrame(records)
