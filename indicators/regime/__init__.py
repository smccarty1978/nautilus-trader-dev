"""Regime Detection Indicator package."""

from indicators.regime.config import RegimeConfig
from indicators.regime.indicator import RegimeIndicators, Regime5m
from indicators.regime.indicator_v2 import RegimeIndicatorsV2

__all__ = [
    "RegimeConfig",
    "RegimeIndicators",
    "RegimeIndicatorsV2",
    "Regime5m",
]
