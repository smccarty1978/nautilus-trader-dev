from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

STUDY = Path(__file__).resolve().parent
ROOT = STUDY.parents[1]
CFG = yaml.safe_load((STUDY / "config.yaml").read_text())

command = [
    sys.executable,
    str(ROOT / "scripts" / "run_bounded_study.py"),
    "--cmd", f'"{sys.executable}" "{STUDY / "implementation" / "build_population.py"}"',
    "--timeout", str(CFG["bounded_timeout_seconds"]),
    "--out-status", str(STUDY / "results" / "bounded_run_status.json"),
]
raise SystemExit(subprocess.call(command, cwd=ROOT))
