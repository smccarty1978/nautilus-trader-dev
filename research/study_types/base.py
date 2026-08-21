"""Base Study Type Compiler Interface.
=======================================
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
from research.schemas.study_spec import StudySpec


class FitDecision(str, Enum):
    STUDY_TYPE_MATCH = "STUDY_TYPE_MATCH"
    STUDY_TYPE_MATCH_WITH_EXTENSION = "STUDY_TYPE_MATCH_WITH_EXTENSION"
    BESPOKE_REQUIRED = "BESPOKE_REQUIRED"


@dataclass
class CompileResult:
    fit_decision: FitDecision
    study_id: str
    study_type: str
    spec_sha256: str
    contracts: Dict[str, Any]
    nt_strategy_class: str
    test_declarations: List[Dict[str, Any]]
    rendered_spec_md: str
    rendered_task_packet: Dict[str, Any]
    summary_card: str
    custom_code_allowed: bool = False
    errors: List[str] = field(default_factory=list)


class BaseStudyCompiler(ABC):
    """Abstract base class for study type compilers."""

    @abstractmethod
    def evaluate_fit(self, spec: StudySpec) -> FitDecision:
        """Evaluates whether the given StudySpec fits this canonical study type."""
        pass

    @abstractmethod
    def compile(self, spec: StudySpec) -> CompileResult:
        """Compiles the StudySpec into authoritative contracts and artifacts."""
        pass
