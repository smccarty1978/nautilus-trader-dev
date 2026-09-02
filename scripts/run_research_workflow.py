"""DEPRECATED operator entry point -- superseded by the governed controller.

    python scripts/research.py study run --study studies/<id> --through <stage>

This shim refuses to run and prints a compact card; the module it wrapped is retained
only for sealed studies whose execution closure names it.
"""
from __future__ import annotations
import json, sys

def main() -> int:
    print(json.dumps({"STATUS": "DEPRECATED", "entry_point": __file__.replace("\\", "/").rsplit("/", 1)[-1],
                      "use": "python scripts/research.py study run --study studies/<id> --through <stage>",
                      "reason": "one governed controller is the sole operator surface (platform-v2 item 04)"}))
    return 2

if __name__ == "__main__":
    raise SystemExit(main())
