"""Indicator Registry - Central registry for all custom indicators."""

from typing import Dict, Type
from nautilus_trader.indicators.base.indicator import Indicator

# Registry of available indicators
INDICATOR_REGISTRY: Dict[str, Type[Indicator]] = {}


def register_indicator(name: str):
    """Decorator to register an indicator class."""
    def decorator(cls: Type[Indicator]):
        INDICATOR_REGISTRY[name] = cls
        return cls
    return decorator


def get_indicator(name: str) -> Type[Indicator]:
    """Get an indicator class by name."""
    if name not in INDICATOR_REGISTRY:
        raise KeyError(f"Indicator '{name}' not found in registry. Available: {list(INDICATOR_REGISTRY.keys())}")
    return INDICATOR_REGISTRY[name]


def list_indicators() -> list[str]:
    """List all registered indicator names."""
    return list(INDICATOR_REGISTRY.keys())
