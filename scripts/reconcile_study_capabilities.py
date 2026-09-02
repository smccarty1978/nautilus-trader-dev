"""DEPRECATED operator entry point -- superseded by the governed controller.

    python scripts/research.py study run --study studies/<id> --through <stage>

This shim refuses to run and prints a compact card; the module it wrapped is retained
only for sealed studies whose execution closure names it.
"""
from __future__ import annotations
import json, sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
try:  # The workflow engine's deterministic 'reconcile' leaf still lives in the retained module.
    from scripts._legacy_reconcile_study_capabilities import reconcile  # noqa: F401
except Exception:  # the shim must always print its card
    reconcile = None  # type: ignore[assignment]

def main() -> int:
    print(json.dumps({"STATUS": "DEPRECATED", "entry_point": __file__.replace("\\", "/").rsplit("/", 1)[-1],
                      "use": "python scripts/research.py study run --study studies/<id> --through <stage>",
                      "reason": "one governed controller is the sole operator surface (platform-v2 item 04)"}))
    return 2

if __name__ == "__main__":
    raise SystemExit(main())
