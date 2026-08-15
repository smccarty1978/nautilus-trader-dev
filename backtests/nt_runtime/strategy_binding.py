"""Strategy Binding Registry & Resolver for NautilusTrader Execution.
=====================================================================
Resolves registered strategy classes and configurations safely.
"""

from __future__ import annotations

import importlib
import inspect
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Type


class UnregisteredStrategyBindingError(ValueError):
    """Raised when a study requests an unregistered or unsupported strategy binding."""
    pass


@dataclass(frozen=True)
class StrategyBinding:
    binding_id: str
    module_path: str
    class_name: str
    config_class_name: str
    strategy_cls: Type[Any]
    config_cls: Type[Any]
    supported_modes: List[str]


STRATEGY_REGISTRY: Dict[str, Dict[str, Any]] = {
    "flip_prediction_collector": {
        "module_path": "strategies.flip_prediction_collector",
        "class_name": "FlipPredictionCollector",
        "config_class_name": "FlipPredictionCollectorConfig",
        "supported_modes": ["collect"],
    },
    "score_fanning_strategy": {
        "module_path": "strategies.score_fanning_strategy",
        "class_name": "ScoreFanningStrategy",
        "config_class_name": "ScoreFanningConfig",
        "supported_modes": ["collect", "backtest"],
    },
}


def resolve_strategy_binding(
    binding_or_class: str,
    study_type: str = "flip_prediction",
    mode: str = "collect",
) -> StrategyBinding:
    """Resolves Strategy and StrategyConfig classes for NT execution generically.

    Parameters
    ----------
    binding_or_class : str
        Registered binding key (e.g. 'flip_prediction_collector') or full class path.
    study_type : str
        Study type ('flip_prediction', 'bespoke', or custom).
    mode : str
        Requested execution mode ('collect', 'parity', 'backtest').

    Returns
    -------
    StrategyBinding
        Resolved classes and metadata.
    """
    # 1. Dotted Python class path (e.g. 'strategies.flip_prediction_collector.FlipPredictionCollector')
    if "." in binding_or_class:
        mod_name, cls_name = binding_or_class.rsplit(".", 1)
        try:
            mod = importlib.import_module(mod_name)
            strategy_cls = getattr(mod, cls_name)
        except Exception as e:
            raise UnregisteredStrategyBindingError(
                f"STRATEGY_BINDING_UNRESOLVED: Failed to import strategy class '{binding_or_class}': {e}"
            ) from e

        cfg_cls_name = f"{cls_name}Config"
        config_cls = getattr(mod, cfg_cls_name, None)

        return StrategyBinding(
            binding_id=cls_name,
            module_path=mod_name,
            class_name=cls_name,
            config_class_name=cfg_cls_name if config_cls else "",
            strategy_cls=strategy_cls,
            config_cls=config_cls,
            supported_modes=["collect", "parity", "backtest"],
        )

    # 2. Lookup in registered bindings
    if binding_or_class in STRATEGY_REGISTRY:
        entry = STRATEGY_REGISTRY[binding_or_class]
        if mode not in entry.get("supported_modes", ["collect", "backtest"]):
            raise UnregisteredStrategyBindingError(
                f"Strategy binding '{binding_or_class}' does not support mode '{mode}' "
                f"(supported: {entry.get('supported_modes')})"
            )
        mod = importlib.import_module(entry["module_path"])
        strategy_cls = getattr(mod, entry["class_name"])
        config_cls = getattr(mod, entry["config_class_name"])

        return StrategyBinding(
            binding_id=binding_or_class,
            module_path=entry["module_path"],
            class_name=entry["class_name"],
            config_class_name=entry["config_class_name"],
            strategy_cls=strategy_cls,
            config_cls=config_cls,
            supported_modes=entry.get("supported_modes", ["collect", "backtest"]),
        )

    raise UnregisteredStrategyBindingError(
        f"UNREGISTERED_STRATEGY: Strategy binding '{binding_or_class}' cannot be resolved. "
        f"Provide a fully-qualified Python path (e.g. 'strategies.my_strategy.MyStrategy') or registered key."
    )
