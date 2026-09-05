"""Research Supervisor V1 (WORKFLOW.md section O): a thin, deterministic, file-state orchestrator above
the governed controller. It derives each study's position from artifacts, launches fresh disposable AI
worker processes (one provider per supervisor run) or detached controller jobs, waits cheaply, and
escalates only typed intervention states. It never replaces, wraps or duplicates
:mod:`research_workflow.governed_controller_v2`.

Modules: ``state`` (machine-local persisted state), ``derive`` (artifact -> typed state), ``packets``
(pointer packets + result cards with staleness binding), ``providers`` (worker launch adapters),
``procs`` (detached spawn / pid / kill), ``resources`` (main-merge lock + machine-wide slots),
``core`` (the tick loop), ``cli`` (``research supervise ...``).
"""
from research_workflow.supervisor.core import Supervisor, SupervisorError  # noqa: F401

__all__ = ["Supervisor", "SupervisorError"]
