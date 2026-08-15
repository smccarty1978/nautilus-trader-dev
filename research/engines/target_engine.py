"""Target Contract Compilation Engine.
=====================================
Validates and generates the target contract JSON for a study.
"""

from __future__ import annotations

from typing import Any, Dict
from research.schemas.study_spec import TargetSpec


def compile_target_contract(target_spec: TargetSpec) -> Dict[str, Any]:
    """Compiles the authoritative target contract dictionary."""
    contract = {
        "target_type": target_spec.type,
        "event": target_spec.event or "regime_flip",
        "direction": target_spec.direction,
        "horizon_seconds": target_spec.horizon_seconds,
        "confirmation": target_spec.confirmation or {
            "mode": "bar_close",
            "confirmation_bars": 1,
        },
        "censoring_policy": {
            "session_end_censoring": True,
            "max_horizon_seconds": target_spec.horizon_seconds or 300,
        },
    }
    return contract
