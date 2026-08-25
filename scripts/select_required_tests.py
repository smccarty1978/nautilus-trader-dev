"""Deprecated shim; use :mod:`research_workflow.test_selection`."""
from research_workflow.test_selection import *  # noqa: F401,F403

if __name__ == "__main__":
    from research_workflow.test_selection import main
    raise SystemExit(main())


def _rt_narrow():
    return ['scripts/tests/test_resampling.py']
