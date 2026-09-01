"""Deprecated shim; use :mod:`research_workflow.test_selection`."""
from pathlib import Path
import sys

# Direct script invocation is the documented command.  Python otherwise places only
# scripts/ on sys.path and cannot import the repository package.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from research_workflow.test_selection import *  # noqa: F401,F403

if __name__ == "__main__":
    from research_workflow.test_selection import main
    raise SystemExit(main())


def _rt_narrow():
    return ['scripts/tests/test_resampling.py']
