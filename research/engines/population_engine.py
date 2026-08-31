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
    # qualification is a typed PopulationQualificationSpec (RT-06); the compiled contract
    # keeps the historical dict shape, so dump only the set fields.
    qual = (
        pop_spec.qualification.model_dump(exclude_none=True, mode="json")
        if pop_spec.qualification is not None else {}
    )
    cadence = qual.get("cadence_seconds")
    if cadence:
        chk_freq = f"{cadence}s"
    else:
        # The canonical collector declares candidates on a fixed 5s grid measured from
        # the regime start, evaluated on completed 1s bars -- not at 1m bar close. The
        # previous default said "1m_bar_close", which described neither the cadence nor
        # the triggering stream and would mislead any reviewer checking observation
        # timing against the contract. Sourced from the collector's own constant so the
        # two cannot drift.
        from research_workflow.generic_collector import CANDIDATE_STEP_NS

        cadence = int(CANDIDATE_STEP_NS // 1_000_000_000)
        chk_freq = f"{cadence}s"

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
            "checkpoint_grid_origin": "regime_start_ns",
            "triggering_stream": "completed_1s_bar",
            "observation_timing": "interval_close",
        },
    }
    if pop_spec.episode_lifecycle is not None:
        contract["episode_lifecycle"] = pop_spec.episode_lifecycle.model_dump(mode="json")
    return contract
