"""The thin governed runtime host (platform-v2).

HOST COORDINATES PRIMITIVES. HOST DOES NOT IMPLEMENT SCIENTIFIC PRIMITIVES.

The host owns event ordering by ``ts_init``, stream multiplexing with one
``visible_through_ns`` integer per stream, the same-timestamp rule, completed-bar
availability, generic timeframe bucket aggregation, provider dispatch by cadence,
warmup/null enforcement, trigger-state transitions, expiry/cooldown counters, outcome
arbitration and precedence, bounded pending state, columnar output buffering, sink
dispatch and the progress heartbeat.  Every scientific decision reaches it through an
interface whose implementation came from the compiled plan
(``research_workflow.grammar.plan.CompiledPlan``).

``scripts/lint_host.py`` enforces the boundary mechanically: no imports from
``features/``, ``indicators/``, ``collectors/`` or any study; no instrument, bar-type or
timezone literals; no unexplained numeric thresholds.
"""
from research_workflow.host.strategy import GovernedHostStrategy, GovernedHostStrategyConfig, HostCore

__all__ = ["GovernedHostStrategy", "GovernedHostStrategyConfig", "HostCore"]
