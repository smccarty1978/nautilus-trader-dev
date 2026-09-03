"""Platform-v2 study grammar: six primitive kinds, one static compiler.

A study is a composition of registered primitives (stream, feature, tracker, trigger
graph, outcome, entry reference).  ``compile_study`` resolves the composition statically
-- datasets, instruments, timeframes, capabilities, dependencies, cadence, warmup,
availability, trigger/outcome dependencies, entry-reference semantics, chronology, the
model/validation plan and the scientific closure -- and returns either a
:class:`~research_workflow.grammar.plan.CompiledPlan` or a typed
:class:`~research_workflow.grammar.gaps.CapabilityGapReport`.  No catalog is ever
opened to answer whether a study can be represented.
"""
from research_workflow.grammar.gaps import CapabilityGap, CapabilityGapReport, GapKind
from research_workflow.grammar.plan import CompiledPlan
from research_workflow.grammar.compiler import CompileOutcome, compile_study, load_spec

__all__ = [
    "CapabilityGap", "CapabilityGapReport", "GapKind", "CompiledPlan",
    "CompileOutcome", "compile_study", "load_spec",
]
