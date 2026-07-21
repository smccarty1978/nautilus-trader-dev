"""Keltner Channel indicator for 3-minute bars."""
from __future__ import annotations
from typing import Optional


class KeltnerChannel:
    """Keltner Channel indicator computing EMA basis and Wilder ATR bands."""

    def __init__(self, ema_period: int = 20, atr_period: int = 20, multiplier: float = 1.5):
        self.ema_period = ema_period
        self.atr_period = atr_period
        self.multiplier = multiplier

        self.alpha_ema = 2.0 / (ema_period + 1)
        self.ema: Optional[float] = None
        self.atr: Optional[float] = None
        self.prev_close: Optional[float] = None
        self.tr_warmup: list[float] = []

    def update(self, high: float, low: float, close: float) -> None:
        # 1. Update EMA basis
        if self.ema is None:
            self.ema = close
        else:
            self.ema = self.alpha_ema * close + (1.0 - self.alpha_ema) * self.ema

        # 2. Compute True Range
        if self.prev_close is None:
            tr = high - low
        else:
            tr = max(high - low, abs(high - self.prev_close), abs(low - self.prev_close))
        self.prev_close = close

        # 3. Update Wilder ATR
        if self.atr is None:
            self.tr_warmup.append(tr)
            if len(self.tr_warmup) == self.atr_period:
                self.atr = sum(self.tr_warmup) / self.atr_period
        else:
            self.atr = (self.atr * (self.atr_period - 1) + tr) / self.atr_period

    @property
    def is_warmed_up(self) -> bool:
        return self.ema is not None and self.atr is not None

    @property
    def basis(self) -> Optional[float]:
        return self.ema

    @property
    def upper(self) -> Optional[float]:
        if self.ema is not None and self.atr is not None:
            return self.ema + self.multiplier * self.atr
        return None

    @property
    def lower(self) -> Optional[float]:
        if self.ema is not None and self.atr is not None:
            return self.ema - self.multiplier * self.atr
        return None
