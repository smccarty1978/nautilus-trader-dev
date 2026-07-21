"""Configuration for Regime Detection Indicator."""

from dataclasses import dataclass


@dataclass
class RegimeConfig:
    """Configuration for RegimeIndicators."""

    short_period: int = 3      # Fast EMA period
    long_period: int = 9       # Slow EMA period
    atr_period: int = 14       # ATR period
