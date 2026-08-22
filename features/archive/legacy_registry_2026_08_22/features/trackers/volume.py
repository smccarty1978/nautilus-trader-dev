from collections import deque
from typing import Dict, List, Optional
import numpy as np

class ArrivalVolumeTracker:
    """Tracks micro-volume dynamics, relative volume, trend, and price correlation on 1s bars."""

    def __init__(self, maxlen: int = 60):
        self.volumes = deque(maxlen=maxlen)
        self.opens = deque(maxlen=maxlen)
        self.closes = deque(maxlen=maxlen)

    def update(self, volume: float, open_px: float, close_px: float) -> None:
        self.volumes.append(volume)
        self.opens.append(open_px)
        self.closes.append(close_px)

    def calculate(self) -> Dict[str, float]:
        v = list(self.volumes)
        o = list(self.opens)
        c = list(self.closes)
        n = len(v)

        if n < 20:
            return {
                'rvol_1s': 1.0, 'rvol_5s': 1.0, 'rvol_10s': 1.0, 'vol_trend_10s': 1.0,
                'vol_spike': 0.0, 'vol_climax': 0.0, 'vol_accel': 0.0,
                'up_vol_ratio_10s': 0.5, 'down_vol_ratio_10s': 0.5, 'vol_price_corr_10s': 0.0,
            }

        vol_mean_10 = np.mean(v[-11:-1]) if n >= 11 else 1.0
        rvol_1s = v[-1] / vol_mean_10 if vol_mean_10 > 0 else 1.0

        sum_recent_5 = sum(v[-5:]) if n >= 5 else sum(v)
        sum_prior_5 = sum(v[-10:-5]) if n >= 10 else sum_recent_5
        rvol_5s = sum_recent_5 / sum_prior_5 if sum_prior_5 > 0 else 1.0

        sum_recent_10 = sum(v[-10:]) if n >= 10 else sum(v)
        sum_prior_10 = sum(v[-20:-10]) if n >= 20 else sum_recent_10
        rvol_10s = sum_recent_10 / sum_prior_10 if sum_prior_10 > 0 else 1.0

        mean_recent_5 = np.mean(v[-5:]) if n >= 5 else np.mean(v)
        mean_prior_5 = np.mean(v[-10:-5]) if n >= 10 else mean_recent_5
        vol_accel = mean_recent_5 / mean_prior_5 if mean_prior_5 > 0 else 1.0

        vol_std_10 = np.std(v[-11:-1]) if n >= 11 else 0.0
        vol_spike = (v[-1] - vol_mean_10) / vol_std_10 if vol_std_10 > 0 else 0.0

        up_vol = 0.0
        down_vol = 0.0
        for i in range(1, min(11, n + 1)):
            if c[-i] >= o[-i]:
                up_vol += v[-i]
            else:
                down_vol += v[-i]
        total_vol = up_vol + down_vol
        up_vol_ratio = up_vol / total_vol if total_vol > 0 else 0.5
        down_vol_ratio = down_vol / total_vol if total_vol > 0 else 0.5

        returns = [c[-i] - o[-i] for i in range(1, min(11, n + 1))]
        v_subset = list(v[-min(10, n):])
        if len(returns) > 1 and np.std(returns) > 0 and np.std(v_subset) > 0:
            corr = np.corrcoef(returns[::-1], v_subset)[0, 1]
            if np.isnan(corr):
                corr = 0.0
        else:
            corr = 0.0

        return {
            'rvol_1s': rvol_1s,
            'rvol_5s': rvol_5s,
            'rvol_10s': rvol_10s,
            'vol_trend_10s': 1.0 if rvol_5s > 1.2 else ( -1.0 if rvol_5s < 0.8 else 0.0 ),
            'vol_spike': vol_spike,
            'vol_climax': 1.0 if rvol_1s > 3.0 and vol_spike > 2.0 else 0.0,
            'vol_accel': vol_accel,
            'up_vol_ratio_10s': up_vol_ratio,
            'down_vol_ratio_10s': down_vol_ratio,
            'vol_price_corr_10s': corr,
        }
