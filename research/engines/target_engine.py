"""Target Contract Compilation Engine.
=====================================
Validates and generates the target contract JSON for a study.
"""

from __future__ import annotations

from typing import Any, Dict, List
from research.schemas.study_spec import RequiredForwardOutcomeSpec, TargetSpec


def _compile_forward_outcome_spec(spec: RequiredForwardOutcomeSpec) -> Dict[str, Any]:
    """Constructs a REAL ``forward_outcomes.contracts.ForwardOutcomeSpec`` from the
    declared ``RequiredForwardOutcomeSpec`` and returns its generated schema.

    This is reuse, not approximation: a malformed horizon/censoring combination fails
    here via that dataclass's own ``__post_init__`` invariants, and the returned
    ``generated_outcome_columns`` are the real output of ``build_outcome_columns`` --
    exactly what ``causal_audit``'s ``composite_target_label_only`` check verifies
    against ``forward_outcomes.guard.OUTCOME_COLUMN_PATTERNS``.
    """
    from research_workflow.forward_outcomes.contracts import (
        BarInclusion,
        ForwardOutcomeSpec,
        OrderedBarrierSpec,
        ReferencePrice,
        build_outcome_columns,
    )

    entry_reference_map = {
        "decision_close": ReferencePrice.DECISION_CLOSE,
        "next_bar_open": ReferencePrice.NEXT_BAR_OPEN,
        "confirmation_close": ReferencePrice.CONFIRMATION_CLOSE,
        "explicit": ReferencePrice.EXPLICIT,
    }
    bar_inclusion_map = {
        "fully_forward": BarInclusion.FULLY_FORWARD,
        "close_after_entry": BarInclusion.CLOSE_AFTER_ENTRY,
    }
    fo = ForwardOutcomeSpec(
        spec_id=spec.id,
        horizons_seconds=(spec.horizon_seconds,),
        max_tracking_seconds=spec.max_tracking_seconds or spec.horizon_seconds,
        excursion_units=tuple(spec.excursion_units),
        reference_price=entry_reference_map[spec.entry_reference],
        bar_inclusion=bar_inclusion_map[spec.bar_inclusion],
        session_end_censoring=spec.session_end_censoring,
        max_gap_seconds=spec.max_gap_seconds,
        atr_source=spec.atr_source,
        atr_frozen_at=spec.atr_frozen_at,
        ordered_barriers=tuple(
            OrderedBarrierSpec(
                barrier_id=b.id,
                favorable_atr=b.favorable_atr,
                adverse_atr=b.adverse_atr,
                horizon_seconds=b.horizon_seconds,
            )
            for b in (spec.ordered_barriers or [])
        ),
    )
    return {
        "id": spec.id,
        "spec_sha256": fo.spec_sha256,
        "entry_reference": spec.entry_reference,
        "horizon_seconds": spec.horizon_seconds,
        "max_tracking_seconds": fo.max_tracking_seconds,
        "excursion_units": list(fo.excursion_units),
        "bar_inclusion": spec.bar_inclusion,
        "session_end_censoring": spec.session_end_censoring,
        "max_gap_seconds": spec.max_gap_seconds,
        "atr_source": spec.atr_source,
        "atr_frozen_at": spec.atr_frozen_at,
        "ordered_barriers": [b.model_dump() for b in (spec.ordered_barriers or [])],
        "generated_outcome_columns": list(build_outcome_columns(fo)),
    }


def _compile_condition(condition: Any) -> Dict[str, Any]:
    body = condition.model_dump()
    return body


def resolve_effective_horizon(target_spec: TargetSpec) -> int | None:
    """The single authoritative horizon for the target.

    A ``flip`` target authors ``horizon_seconds`` directly.  A composite
    ordered-barrier target instead carries the horizon on its forward-outcome
    contract(s); surface that exact value here.  Fail closed when multiple
    forward outcomes imply conflicting horizons rather than pick one.
    """
    if target_spec.horizon_seconds is not None:
        return target_spec.horizon_seconds
    outcomes = target_spec.required_forward_outcomes or []
    horizons = {fo.horizon_seconds for fo in outcomes if fo.horizon_seconds is not None}
    if not horizons:
        return None
    if len(horizons) > 1:
        raise ValueError(
            f"TARGET_HORIZON_AMBIGUOUS: required forward outcomes imply conflicting "
            f"horizons {sorted(horizons)}; a composite target needs one authoritative horizon"
        )
    return next(iter(horizons))


def compile_target_contract(target_spec: TargetSpec) -> Dict[str, Any]:
    """Compiles the authoritative target contract dictionary.

    A target with no declared ``conditions`` compiles exactly as it always has --
    composite-target fields are additive, never required.
    """
    effective_horizon = resolve_effective_horizon(target_spec)
    contract = {
        # This is an execution primitive, not presentation metadata.  The collector
        # resolves it through research_workflow.target_runtime and never guesses from
        # a historical target_type string.
        "primitive": "ordered_barrier" if (
            target_spec.conditions or any((fo.ordered_barriers or []) for fo in (target_spec.required_forward_outcomes or []))
        ) else "flip_within_horizon",
        "target_type": target_spec.type,
        "event": target_spec.event or "regime_flip",
        "direction": target_spec.direction,
        "horizon_seconds": effective_horizon,
        "confirmation": target_spec.confirmation or {
            "mode": "bar_close",
            "confirmation_bars": 1,
        },
        "censoring_policy": {
            "session_end_censoring": True,
            "max_horizon_seconds": effective_horizon or 300,
        },
        "decision_reference": target_spec.decision_reference,
    }
    if target_spec.conditions:
        required_forward_outcomes: List[Dict[str, Any]] = [
            _compile_forward_outcome_spec(fo) for fo in (target_spec.required_forward_outcomes or [])
        ]
        contract["conditions"] = [_compile_condition(c) for c in target_spec.conditions]
        contract["condition_logic"] = target_spec.condition_logic
        contract["required_forward_outcomes"] = required_forward_outcomes
    return contract
