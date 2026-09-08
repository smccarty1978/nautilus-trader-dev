"""Golden analysis-op resolution snapshot: the proof that the registration-boundary split changed nothing.

Captures, for every registered analysis operation, the three things a consumer can observe:
the implementation ``run_op`` dispatches to, the extra frames the compiler proves are bound,
and whether the op receives machine-local resolution context.  Generated from the tree
(``python -m research.analysis.tests.golden_analysis_ops``) and compared by
``research/analysis/tests/test_analysis_op_boundary.py``.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

GOLDEN_PATH = Path(__file__).resolve().parent / "golden" / "analysis_ops.json"


def build() -> Dict[str, Any]:
    from research.analysis import ops as ops_api

    snapshot: Dict[str, Any] = {"schema_version": 1, "ops": {}}
    for op in sorted(ops_api.known_ops()):
        fn = ops_api.op_implementation(op)
        snapshot["ops"][op] = {
            "implementation": f"{fn.__module__}.{fn.__qualname__}",
            "inputs": list(ops_api.op_inputs(op)),
            "needs_context": op in ops_api.context_ops(),
        }
    snapshot["known_ops"] = sorted(ops_api.known_ops())
    try:
        ops_api.run_op("analysis.not.an.op", None)
        snapshot["unknown_op_error"] = None
    except Exception as exc:                       # noqa: BLE001 - the refusal IS the contract
        snapshot["unknown_op_error"] = f"{type(exc).__name__}: {exc}"
    return snapshot


def main() -> int:
    GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN_PATH.write_text(json.dumps(build(), indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {GOLDEN_PATH} ({GOLDEN_PATH.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
