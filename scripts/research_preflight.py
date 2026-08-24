"""Deprecated shim; use :mod:`research_workflow.preflight`."""
from research_workflow.preflight import *  # noqa: F401,F403

if __name__ == "__main__":
    from research_workflow.preflight import main
    raise SystemExit(main())
