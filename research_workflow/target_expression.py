"""Compiled target-contract -> executable Boolean target expression tree.

A target contract with no ``conditions`` (a plain ``flip`` target) or exactly one
condition compiles to a bare :class:`PrimitiveTarget` and behaves precisely as it always
has.  A contract with two or more ``conditions`` plus ``condition_logic`` compiles to an
:class:`And` / :class:`Or` node over per-condition :class:`PrimitiveTarget` leaves.

Composition semantics (researcher-authorized 2026-08-28, "AUTHORIZE COMPOSITE TARGET
CENSORING SEMANTICS"):

    A composite target is RESOLVED only when **every** required child target is itself
    resolved.  Composition is MONOTONE and NEVER Boolean-short-circuits.

    * If any child is CENSORED / AMBIGUOUS / otherwise unresolved, the composite is
      unresolved -> ``CENSORED``, carrying the worst child censor reason under the
      framework's existing monotone severity ordering
      (:func:`research_workflow.forward_outcomes.contracts.worst_status`, extended here to
      the target-runtime censor-reason vocabulary).
    * Only when every child carries a 0/1 label does AND/OR Boolean logic run
      (``AND`` = all children True, ``OR`` = any child True).

    Explicitly NOT allowed (would hide an unobservable required child and weaken target
    provenance):

        AND(False, CENSORED) -> NEGATIVE
        OR (True,  CENSORED) -> POSITIVE

Unknown / unsupported composition fails closed: an unknown ``condition_logic`` raises at
compile time; a condition ``kind`` with no executable runtime (``excursion`` / ``return``)
is represented in the tree but raises when the runtime is resolved
(:class:`research_workflow.target_runtime.CompositeTargetRuntime`).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from research_workflow.forward_outcomes.contracts import OutcomeStatus, worst_status

NS = 1_000_000_000

POSITIVE, NEGATIVE, CENSORED, PENDING = "POSITIVE", "NEGATIVE", "CENSORED", "PENDING"

# Censoring composition identity written into every composite target contract so the
# compiled contract, the runtime, the replay oracle and the audits all name the same rule.
CENSORING_COMPOSITION = "monotone_worst_status"

_KIND_TO_PRIMITIVE = {
    "flip": "flip_within_horizon",
    "ordered_barrier": "ordered_barrier",
    # Represented in the tree for provenance, but NOT runtime-executable: no TargetRuntime
    # evaluates an end-of-window excursion/return threshold.  CompositeTargetRuntime fails
    # closed on these.
    "excursion": "excursion",
    "return": "return",
}

_RUNTIME_EXECUTABLE_PRIMITIVES = frozenset({"flip_within_horizon", "ordered_barrier"})


class TargetExpressionError(RuntimeError):
    """A target contract cannot be compiled into an executable Boolean expression."""


@dataclass(frozen=True)
class TargetResult:
    """One terminal (or interim) target evaluation.

    ``label`` is ``None`` for anything that is not a settled 0/1 outcome (``CENSORED``,
    ``PENDING``).
    """

    disposition: str
    label: int | None
    resolved_at_ts: int | None = None
    censor_reason: str | None = None


# --- monotone censor-reason severity ----------------------------------------------------
# Anchored to forward_outcomes.contracts._STATUS_SEVERITY (RESOLVED < CENSORED_SESSION <
# CENSORED_HORIZON < CENSORED_DATA_END < MISSING_DATA) and extended to the concrete censor
# reasons the flip / ordered-barrier runtimes emit.  A reason not listed here is treated
# as maximally severe so it is always surfaced rather than silently outranked.
# The ordering below IS forward_outcomes' monotone ordering: RESOLVED(0) is "no
# censoring", the session/horizon/data-end tiers mirror CENSORED_SESSION(1) <
# CENSORED_HORIZON(2) < CENSORED_DATA_END(3), MISSING_DATA(4) stays strictly worst.
assert worst_status(
    [OutcomeStatus.CENSORED_SESSION, OutcomeStatus.CENSORED_DATA_END]
) is OutcomeStatus.CENSORED_DATA_END
_CENSOR_SEVERITY: dict[str | None, int] = {
    None: 0,
    "SESSION_END": 1,
    "CENSORED_SESSION": 1,
    "HORIZON": 2,
    "CENSORED_HORIZON": 2,
    "GAP": 3,
    "DATA_END": 3,
    "CENSORED_DATA_END": 3,
    "AMBIGUOUS_SAME_BAR_TOUCH": 4,
    "AMBIGUOUS_FIRST_TOUCH": 4,
    "FROZEN_ATR_NONPOSITIVE": 5,
    "UNRESOLVED_CHILD": 5,
    "MISSING_DATA": 6,
}


def worst_censor_reason(reasons: Sequence[str | None]) -> str | None:
    """The most severe censor reason among ``reasons`` (``worst_status`` for the target
    censor vocabulary).  ``None`` iff every reason is ``None``."""
    worst: str | None = None
    worst_sev = 0
    for r in reasons:
        sev = _CENSOR_SEVERITY.get(r, max(_CENSOR_SEVERITY.values()))
        if sev > worst_sev:
            worst, worst_sev = r, sev
    return worst


def _is_resolved(result: TargetResult) -> bool:
    return result.label is not None and result.disposition in (POSITIVE, NEGATIVE)


# --- expression nodes -----------------------------------------------------------------
@dataclass(frozen=True)
class PrimitiveTarget:
    """A single condition: one primitive target evaluated by one ``TargetRuntime``."""

    condition_id: str
    primitive: str
    params: Mapping[str, Any] = field(default_factory=dict)

    node_kind = "primitive"

    def leaves(self) -> tuple["PrimitiveTarget", ...]:
        return (self,)

    def condition_ids(self) -> tuple[str, ...]:
        return (self.condition_id,)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node": "primitive",
            "condition_id": self.condition_id,
            "primitive": self.primitive,
            "params": {k: self.params[k] for k in sorted(self.params)},
        }

    def canonical(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))

    def evaluate(self, child_results: Mapping[str, TargetResult]) -> TargetResult:
        try:
            return child_results[self.condition_id]
        except KeyError as exc:  # fail closed - a missing child is never "resolved"
            raise TargetExpressionError(
                f"COMPOSITE_CHILD_RESULT_MISSING: no result for condition "
                f"{self.condition_id!r}"
            ) from exc


@dataclass(frozen=True)
class _BoolNode:
    children: tuple["TargetExpression", ...]
    logic: str  # "AND" | "OR"

    def leaves(self) -> tuple[PrimitiveTarget, ...]:
        out: list[PrimitiveTarget] = []
        for c in self.children:
            out.extend(c.leaves())
        return tuple(out)

    def condition_ids(self) -> tuple[str, ...]:
        return tuple(cid for c in self.children for cid in c.condition_ids())

    def to_dict(self) -> dict[str, Any]:
        return {
            "node": self.logic.lower(),
            "logic": self.logic,
            "censoring_composition": CENSORING_COMPOSITION,
            "no_short_circuit": True,
            "children": [c.to_dict() for c in self.children],
        }

    def canonical(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))

    def evaluate(self, child_results: Mapping[str, TargetResult]) -> TargetResult:
        results = [c.evaluate(child_results) for c in self.children]

        # 1. Monotone censoring first: the composite is RESOLVED only when EVERY child is.
        unresolved = [r for r in results if not _is_resolved(r)]
        if unresolved:
            if any(r.disposition == PENDING for r in unresolved):
                return TargetResult(PENDING, None)
            reasons = [
                (r.censor_reason if r.censor_reason is not None else "UNRESOLVED_CHILD")
                for r in unresolved
            ]
            at = max(
                (r.resolved_at_ts for r in results if r.resolved_at_ts is not None),
                default=None,
            )
            return TargetResult(CENSORED, None, at, worst_censor_reason(reasons))

        # 2. Every child resolved -> Boolean composition.
        labels = [int(r.label) for r in results]
        composed = all(labels) if self.logic == "AND" else any(labels)
        at = max((r.resolved_at_ts for r in results if r.resolved_at_ts is not None), default=None)
        return TargetResult(POSITIVE if composed else NEGATIVE, 1 if composed else 0, at)


class And(_BoolNode):
    def __init__(self, children: Sequence["TargetExpression"]):
        super().__init__(tuple(children), "AND")

    node_kind = "and"


class Or(_BoolNode):
    def __init__(self, children: Sequence["TargetExpression"]):
        super().__init__(tuple(children), "OR")

    node_kind = "or"


TargetExpression = PrimitiveTarget | And | Or


# --- compilation --------------------------------------------------------------------
def _min_max_gap_seconds(contract: Mapping[str, Any]) -> int | None:
    gaps = [
        fo.get("max_gap_seconds")
        for fo in (contract.get("required_forward_outcomes") or [])
        if fo.get("max_gap_seconds") is not None
    ]
    return min(int(g) for g in gaps) if gaps else None


def _flip_params(condition: Mapping[str, Any], contract: Mapping[str, Any]) -> dict[str, Any]:
    horizon = condition.get("horizon_seconds") or contract.get("horizon_seconds")
    if horizon is None:
        raise TargetExpressionError(
            f"FLIP_CONDITION_HORIZON_MISSING: condition {condition.get('id')!r} declares "
            f"no horizon_seconds and the contract carries none"
        )
    return {
        "horizon_seconds": int(horizon),
        # "opposite" is the only flip direction any composite here declares; kept as a
        # role string so the runtime resolves it against the live prevailing direction.
        "target_direction_role": str(condition.get("direction") or contract.get("direction") or "opposite"),
        # The flip is observable only over a contiguous tape: the same max_gap the
        # forward outcome declares bounds the flip window too (matches the ordered-barrier
        # child and the replay oracle).
        "max_gap_seconds": _min_max_gap_seconds(contract),
    }


def _ordered_barrier_params(
    condition: Mapping[str, Any], contract: Mapping[str, Any]
) -> dict[str, Any]:
    fo_id = condition.get("forward_outcome_id")
    barrier_id = condition.get("barrier_id")
    fos = contract.get("required_forward_outcomes") or []
    fo = next((f for f in fos if f.get("id") == fo_id), None)
    if fo is None:
        raise TargetExpressionError(
            f"ORDERED_BARRIER_FORWARD_OUTCOME_MISSING: condition {condition.get('id')!r} "
            f"references forward_outcome_id {fo_id!r}"
        )
    barrier = next(
        (b for b in (fo.get("ordered_barriers") or []) if b.get("id") == barrier_id), None
    )
    if barrier is None:
        raise TargetExpressionError(
            f"ORDERED_BARRIER_MISSING: condition {condition.get('id')!r} references "
            f"barrier_id {barrier_id!r}"
        )
    return {
        "forward_outcome_id": str(fo_id),
        "barrier_id": str(barrier_id),
        "favorable_atr": float(barrier["favorable_atr"]),
        "adverse_atr": float(barrier["adverse_atr"]),
        "horizon_seconds": int(barrier["horizon_seconds"]),
        "entry_reference": str(fo.get("entry_reference", "next_bar_open")),
        "session_end_censoring": bool(fo.get("session_end_censoring", False)),
        "max_gap_seconds": (
            int(fo["max_gap_seconds"]) if fo.get("max_gap_seconds") is not None else None
        ),
    }


def _threshold_params(condition: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "metric": condition.get("metric"),
        "comparator": condition.get("comparator"),
        "threshold": condition.get("threshold"),
        "forward_outcome_id": condition.get("forward_outcome_id"),
    }


def _leaf_for_condition(
    condition: Mapping[str, Any], contract: Mapping[str, Any]
) -> PrimitiveTarget:
    kind = condition.get("kind")
    primitive = _KIND_TO_PRIMITIVE.get(str(kind))
    if primitive is None:
        raise TargetExpressionError(f"UNKNOWN_TARGET_CONDITION_KIND: {kind!r}")
    if primitive == "flip_within_horizon":
        params = _flip_params(condition, contract)
    elif primitive == "ordered_barrier":
        params = _ordered_barrier_params(condition, contract)
    else:
        params = _threshold_params(condition)
    return PrimitiveTarget(str(condition["id"]), primitive, params)


def compile_target_expression(contract: Mapping[str, Any]) -> TargetExpression:
    """Build the executable Boolean target expression from a compiled target contract.

    * no ``conditions`` -> single ``PrimitiveTarget`` on ``contract["primitive"]``
      (or ``flip_within_horizon`` when unset -- a legacy pre-``primitive`` contract).
    * one condition -> single ``PrimitiveTarget`` for that condition.
    * >= 2 conditions -> ``And`` / ``Or`` per ``condition_logic`` (fail closed otherwise).
    """
    conditions = list(contract.get("conditions") or [])

    if not conditions:
        primitive = contract.get("primitive") or "flip_within_horizon"
        params: dict[str, Any] = {}
        if primitive == "flip_within_horizon" and contract.get("horizon_seconds") is not None:
            params = {
                "horizon_seconds": int(contract["horizon_seconds"]),
                "target_direction_role": str(contract.get("direction") or "opposite"),
            }
        elif primitive == "ordered_barrier":
            fos = contract.get("required_forward_outcomes") or []
            barriers = [b for f in fos for b in (f.get("ordered_barriers") or [])]
            if barriers:
                fo = fos[0]
                b = barriers[0]
                params = {
                    "forward_outcome_id": str(fo.get("id")),
                    "barrier_id": str(b["id"]),
                    "favorable_atr": float(b["favorable_atr"]),
                    "adverse_atr": float(b["adverse_atr"]),
                    "horizon_seconds": int(b["horizon_seconds"]),
                    "entry_reference": str(fo.get("entry_reference", "next_bar_open")),
                    "session_end_censoring": bool(fo.get("session_end_censoring", False)),
                    "max_gap_seconds": (
                        int(fo["max_gap_seconds"])
                        if fo.get("max_gap_seconds") is not None else None
                    ),
                }
        return PrimitiveTarget("__root__", primitive, params)

    if len(conditions) == 1:
        return _leaf_for_condition(conditions[0], contract)

    logic = contract.get("condition_logic")
    children = [_leaf_for_condition(c, contract) for c in conditions]
    if logic == "AND":
        return And(children)
    if logic == "OR":
        return Or(children)
    raise TargetExpressionError(
        f"UNKNOWN_CONDITION_LOGIC: {logic!r} (a composite target needs 'AND' or 'OR')"
    )


def serialize_expression(contract: Mapping[str, Any]) -> dict[str, Any]:
    """The canonical ``target_expression`` blob embedded in a compiled target contract."""
    return compile_target_expression(contract).to_dict()


def compose_child_results(
    expression: TargetExpression, child_results: Mapping[str, TargetResult]
) -> TargetResult:
    """Public entry point for both the runtime and the replay oracle."""
    return expression.evaluate(child_results)


def runtime_executable(expression: TargetExpression) -> None:
    """Raise :class:`TargetExpressionError` if any leaf has no executable runtime."""
    for leaf in expression.leaves():
        if leaf.primitive not in _RUNTIME_EXECUTABLE_PRIMITIVES:
            raise TargetExpressionError(
                f"UNSUPPORTED_COMPOSITE_CONDITION: condition {leaf.condition_id!r} kind "
                f"maps to primitive {leaf.primitive!r}, which no TargetRuntime executes"
            )


__all__ = [
    "TargetExpressionError",
    "TargetResult",
    "PrimitiveTarget",
    "And",
    "Or",
    "TargetExpression",
    "CENSORING_COMPOSITION",
    "POSITIVE",
    "NEGATIVE",
    "CENSORED",
    "PENDING",
    "NS",
    "compile_target_expression",
    "serialize_expression",
    "compose_child_results",
    "runtime_executable",
    "worst_censor_reason",
]
