from collections import deque
from typing import Dict, List, Optional
import numpy as np

class ArrivalVelocityTracker:
    """Tracks micro-velocity, acceleration, and jerk on 1-second price streams."""

    def __init__(self, maxlen: int = 60):
        self.prices = deque(maxlen=maxlen)

    def update(self, price: float) -> None:
        self.prices.append(price)

    def calculate(self, atr: float) -> Dict[str, float]:
        p = list(self.prices)
        n = len(p)

        if n < 30 or atr <= 0:
            return {
                'arrival_vel_5s': 0.0, 'arrival_vel_10s': 0.0, 'arrival_vel_20s': 0.0,
                'arrival_vel_30s': 0.0, 'arrival_accel_5s': 0.0, 'arrival_accel_10s': 0.0,
                'arrival_jerk': 0.0, 'max_vel_30s': 0.0, 'vel_ratio_5_20': 0.0,
                'is_decelerating': 0.0,
            }

        vel_5s = (p[-1] - p[-6]) / (5 * atr) if n >= 6 else 0.0
        vel_10s = (p[-1] - p[-11]) / (10 * atr) if n >= 11 else 0.0
        vel_20s = (p[-1] - p[-21]) / (20 * atr) if n >= 21 else 0.0
        vel_30s = (p[-1] - p[-30]) / (30 * atr) if n >= 30 else 0.0

        accel_5s = vel_5s - vel_10s
        accel_10s = vel_10s - vel_20s

        max_vel = 0.0
        for i in range(5, min(30, n)):
            v = abs(p[-i+4] - p[-i-1]) / (5 * atr) if i + 1 <= n else 0.0
            max_vel = max(max_vel, abs(v))

        return {
            'arrival_vel_5s': vel_5s,
            'arrival_vel_10s': vel_10s,
            'arrival_vel_20s': vel_20s,
            'arrival_vel_30s': vel_30s,
            'arrival_accel_5s': accel_5s,
            'arrival_accel_10s': accel_10s,
            'arrival_jerk': accel_5s - accel_10s,
            'max_vel_30s': max_vel,
            'vel_ratio_5_20': vel_5s / vel_20s if abs(vel_20s) > 0.001 else 0.0,
            'is_decelerating': 1.0 if accel_5s > 0.0 else 0.0,
        }
