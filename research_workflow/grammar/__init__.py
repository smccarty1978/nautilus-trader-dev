"""Platform-v2 study grammar: six primitive kinds, one static compiler.

A study is a composition of registered primitives (stream, feature, tracker, trigger
graph, outcome, entry reference).  ``compile_study`` resolves the composition statically
-- datasets, instruments, timeframes, capabilities, dependencies, cadence, warmup,
availability, trigger/outcome dependencies, entry-reference semantics, chronology, the
model/validation plan and the scientific closure -- and returns either a
:class:`~research_workflow.grammar.plan.CompiledPlan` or a typed
:class:`~research_workflow.grammar.gaps.CapabilityGapReport`.  No catalog is ever
opened to answer whether a study can be represented.

The compiler is NOT re-exported here.  The replay host imports
``research_workflow.grammar.predicates`` and ``research_workflow.grammar.spec`` at run time;
an eager ``from .compiler import ...`` here made the whole compiler -- and everything it
imports -- execute on the replay path as a package side effect, which is what put
compile-time modules into the partition-reuse key (chore/collection_latency, 2026-09-06).
Import ``compile_study`` / ``load_spec`` / ``CompileOutcome`` from
``research_workflow.grammar.compiler`` directly.
"""
from research_workflow.grammar.gaps import CapabilityGap, CapabilityGapReport, GapKind
from research_workflow.grammar.plan import CompiledPlan

__all__ = ["CapabilityGap", "CapabilityGapReport", "GapKind", "CompiledPlan"]
