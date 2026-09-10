"""DEPRECATED operator entry point -- superseded by the governed controller.

    python scripts/research.py study run --study studies/<id> --through <stage>

This shim refuses to run and prints a compact card.  The V1 capability-reconciliation
leaf it used to wrap (``scripts/_legacy_reconcile_study_capabilities.py``) was removed on
2026-09-10: it re-ran the feature-bundle materializer, wrote ``verified`` straight into the
authority bundle and re-pointed ``active.json`` -- the second door to ``verified`` that only
a sealed authorizing study could open, which is the loop THE REHEARSAL hit.  The workflow
engine still binds ``reconcile`` as its capability leaf; it now returns a typed terminal
state instead of running a ceremony.  A missing feature definition is promoted by its own
golden evidence (``research feature verify|promote <name>``), never by a study-side step.
"""
from __future__ import annotations
import json, sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

CAPABILITY_RECONCILIATION_RETIRED = "CAPABILITY_RECONCILIATION_RETIRED"


def reconcile(study: Path) -> dict:
    """Workflow-engine capability leaf: a typed refusal, never a ceremony.

    Returned as ``TRUE_CAPABILITY_GAP`` so ``WorkflowEngine.advance`` surfaces it as a terminal
    blocked state (it is one of the states the engine returns without writing
    ``capability_reconciliation.json``).  It performs no I/O.
    """
    return {"state": "TRUE_CAPABILITY_GAP", "error": CAPABILITY_RECONCILIATION_RETIRED,
            "study": str(study),
            "detail": ("study-side capability reconciliation no longer exists; a feature definition is "
                       "promoted by golden evidence: python scripts/research.py feature verify <name> && "
                       "python scripts/research.py feature promote <name>; other capability gaps are "
                       "typed by the compiler (research cap search/describe)")}


def main() -> int:
    print(json.dumps({"STATUS": "DEPRECATED", "entry_point": __file__.replace("\\", "/").rsplit("/", 1)[-1],
                      "use": "python scripts/research.py study run --study studies/<id> --through <stage>",
                      "reason": "one governed controller is the sole operator surface (platform-v2 item 04)"}))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
