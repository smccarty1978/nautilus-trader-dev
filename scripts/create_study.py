"""Deprecated compatibility shim; use :mod:`research_workflow.study_factory`."""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from research_workflow.study_factory import *  # noqa: E402,F401,F403

if __name__ == "__main__":
    from research_workflow.study_factory import main

    raise SystemExit(main())
