"""Population Contract Compilation Engine.
=========================================
Validates and generates the population contract JSON for a study.
"""

from __future__ import annotations

from typing import Any, Dict
from research.schemas.study_spec import PopulationSpec, InstrumentSpec


def compile_population_contract(
    pop_spec: PopulationSpec,
    inst_spec: InstrumentSpec,
) -> Dict[str, Any]:
    """Compiles the authoritative population contract dictionary."""
    qual = pop_spec.qualification or {}
    cadence = qual.get("cadence_seconds") if isinstance(qual, dict) else None
    chk_freq = f"{cadence}s" if cadence else "1m_bar_close"

    contract = {
        "instrument": {
            "symbol": inst_spec.symbol,
            "venue": inst_spec.venue,
        },
        "population_type": pop_spec.type,
        "prevailing_regime": pop_spec.prevailing_regime,
        "session": pop_spec.session,
        "qualification": qual,
        "causal_checkpoint": {
            "checkpoint_frequency": chk_freq,
            "observation_timing": "interval_close",
        },
    }
    return contract
