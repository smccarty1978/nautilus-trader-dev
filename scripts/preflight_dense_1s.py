#!/usr/bin/env python3
"""Run deterministic preflight for the standalone dense 1-second utility."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "data" / "canonical" / "audit"
SURFACE = (
    ROOT / "scripts" / "build_dense_1s.py",
    ROOT / "scripts" / "tests" / "test_build_dense_1s.py",
    ROOT / "data" / "canonical" / "config" / "deliverables_contract.json",
)


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def composite(records: dict[str, str]) -> str:
    payload = "".join(f"{path}:{value}\n" for path, value in sorted(records.items()))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def run(command: list[str]) -> dict[str, object]:
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    return {"command": command, "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}


def main() -> int:
    AUDIT.mkdir(parents=True, exist_ok=True)
    lint_path = AUDIT / "causal_lint.json"
    checks = [
        run([sys.executable, "scripts/causal_lint.py", "--path", "scripts/build_dense_1s.py", "scripts/tests/test_build_dense_1s.py", "--json", str(lint_path)]),
        run([sys.executable, "-m", "py_compile", "scripts/build_dense_1s.py", "scripts/preflight_dense_1s.py"]),
        run([sys.executable, "-m", "pytest", "scripts/tests/test_build_dense_1s.py", "-q"]),
    ]
    records = {str(path.relative_to(ROOT)).replace("\\", "/"): digest(path) for path in SURFACE}
    execution_composite = composite(records)
    clear = all(check["returncode"] == 0 for check in checks)
    preflight = {
        "kind": "standalone_dense_1s_preflight",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "status": "CLEAR" if clear else "BLOCKED",
        "checks": checks,
        "surface_files": records,
        "execution_composite_sha256": execution_composite,
        "source_inputs_read": False,
        "canonical_output_written": False,
    }
    (AUDIT / "preflight.json").write_text(json.dumps(preflight, indent=2) + "\n", encoding="utf-8")
    packet = {
        "execution_composite_sha256": execution_composite,
        "surface_files": records,
        "deliverables_contract": "data/canonical/config/deliverables_contract.json",
        "preflight": "data/canonical/audit/preflight.json",
        "status": preflight["status"],
    }
    (AUDIT / "audit_packet.json").write_text(json.dumps(packet, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": preflight["status"], "execution_composite_sha256": execution_composite}, indent=2))
    return 0 if clear else 1


if __name__ == "__main__":
    raise SystemExit(main())
