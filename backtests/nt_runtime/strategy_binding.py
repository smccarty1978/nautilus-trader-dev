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
        "order_handling": "virtual",
    },
    "w4_exit_strategy": {
        "module_path": "strategies.w4_exit_strategy",
        "class_name": "W4ExitStrategy",
        "config_class_name": "W4ExitConfig",
        "supported_modes": ["backtest"],
        "order_handling": "simulated_orders",
    },
}


def _registry_entry_for_class_path(module_path: str, class_name: str) -> Optional[str]:
    """Returns the registry key whose (module, class) matches, else None."""
    for key, entry in STRATEGY_REGISTRY.items():
        if entry["module_path"] == module_path and entry["class_name"] == class_name:
            return key
    return None


def registered_order_handling(binding_id: str) -> Optional[str]:
    """Declared output contract for a registered strategy, if it declares one."""
    entry = STRATEGY_REGISTRY.get(binding_id)
    return entry.get("order_handling") if entry else None


def resolve_strategy_binding(
    binding_or_class: str,
    study_type: str = "flip_prediction",
    mode: str = "collect",
    allow_unregistered: Optional[bool] = None,
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
    allow_unregistered : bool, optional
        Whether an arbitrary dotted class path may be imported. Defaults to
        ``False`` for ``mode='backtest'`` and ``True`` otherwise.

        Rationale: in collect mode the strategy identity comes from a *compiled and
        sealed* study contract, which is itself the authorization, and study-local
        collectors legitimately live under ``studies.<name>.implementation``. The
        standalone backtest harness has no such contract, so an arbitrary import
        string there would execute code that nothing has authorized. Backtest mode
        is therefore registry-only.

    Returns
    -------
    StrategyBinding
        Resolved classes and metadata.
    """
    if allow_unregistered is None:
        allow_unregistered = mode != "backtest"

    # 1. Dotted Python class path (e.g. 'strategies.flip_prediction_collector.FlipPredictionCollector')
    if "." in binding_or_class:
        mod_name_probe, _, cls_name_probe = binding_or_class.rpartition(".")
        matched_key = _registry_entry_for_class_path(mod_name_probe, cls_name_probe)
        if matched_key is not None:
            # Fully-qualified path of a registered strategy: resolve through the registry
            # so mode support and config binding are enforced identically.
            return resolve_strategy_binding(
                matched_key, study_type=study_type, mode=mode, allow_unregistered=allow_unregistered
            )
        if not allow_unregistered:
            raise UnregisteredStrategyBindingError(
                f"UNREGISTERED_STRATEGY_IMPORT_BLOCKED: '{binding_or_class}' is not a registered "
                f"strategy and arbitrary import paths are not permitted in mode '{mode}'. "
                f"Register it in STRATEGY_REGISTRY (backtests/nt_runtime/strategy_binding.py) or "
                f"use one of: {sorted(k for k, v in STRATEGY_REGISTRY.items() if mode in v.get('supported_modes', []))}."
            )
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
