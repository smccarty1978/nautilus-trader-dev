"""Chains the full post-NT analysis pipeline in order."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

PY = sys.executable
HERE = Path(__file__).resolve().parent

STEPS = [
    "parse_nt_results.py",
    "build_episode_status.py",
    "build_parity_audit.py",
    "compute_metrics.py",
    "compute_retention_tail.py",
    "compute_bootstrap.py",
    "compute_matched_random.py",
    "build_provenance_audit.py",
    "write_final_report.py",
]


def main():
    for step in STEPS:
        print(f"\n{'='*20} {step} {'='*20}", flush=True)
        result = subprocess.run([PY, str(HERE / step)], cwd=str(HERE.parent.parent))
        if result.returncode != 0:
            print(f"STEP FAILED: {step} (exit {result.returncode})")
            sys.exit(result.returncode)
    print("\nALL ANALYSIS STEPS COMPLETE")


if __name__ == "__main__":
    main()
