"""Typed capability gaps: what the compiler returns instead of a plan.

A gap is a *classification*, not a stack trace.  The kinds are deliberately few:

* ``MISSING_CAPABILITY``          -- the composition names a primitive nobody registered
* ``INVALID_PARAMETERIZATION``    -- a registered primitive was given parameters it rejects
* ``AMBIGUOUS_TEMPORAL_SEMANTICS``-- two readings of *when* a value is available
* ``UNAVAILABLE_STREAM``          -- the dataset cannot provide the instrument/timeframe
* ``UNSUPPORTED_COMPOSITION``     -- every part exists but they cannot be composed this way
* ``SEMANTIC_DECISION_REQUIRED``  -- a researcher must decide (chronology double-use,
                                     same-timestamp opt-in, unproven policy)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class GapKind(str, Enum):
    MISSING_CAPABILITY = "MISSING_CAPABILITY"
    INVALID_PARAMETERIZATION = "INVALID_PARAMETERIZATION"
    AMBIGUOUS_TEMPORAL_SEMANTICS = "AMBIGUOUS_TEMPORAL_SEMANTICS"
    UNAVAILABLE_STREAM = "UNAVAILABLE_STREAM"
    UNSUPPORTED_COMPOSITION = "UNSUPPORTED_COMPOSITION"
    SEMANTIC_DECISION_REQUIRED = "SEMANTIC_DECISION_REQUIRED"


@dataclass(frozen=True)
class CapabilityGap:
    kind: GapKind
    where: str                      # spec path, e.g. "context.regime_5s" or "triggers.states.WATCH.enter_when"
    message: str
    detail: Dict[str, Any] = field(default_factory=dict)
    closest: Optional[str] = None   # nearest registered primitive, when one exists

    def to_dict(self) -> Dict[str, Any]:
        return {"kind": self.kind.value, "where": self.where, "message": self.message,
                "detail": dict(self.detail), "closest": self.closest}


@dataclass
class CapabilityGapReport:
    study_id: str
    gaps: List[CapabilityGap] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.gaps

    def add(self, kind: GapKind, where: str, message: str, **detail: Any) -> None:
        closest = detail.pop("closest", None)
        self.gaps.append(CapabilityGap(kind, where, message, dict(detail), closest))

    def kinds(self) -> List[str]:
        return sorted({g.kind.value for g in self.gaps})

    def to_dict(self) -> Dict[str, Any]:
        return {"STATUS": "CAPABILITY_GAP", "study_id": self.study_id, "kinds": self.kinds(),
                "count": len(self.gaps), "gaps": [g.to_dict() for g in self.gaps]}


class CompileError(RuntimeError):
    """Raised only for malformed input the compiler cannot classify as a gap."""


__all__ = ["GapKind", "CapabilityGap", "CapabilityGapReport", "CompileError"]
