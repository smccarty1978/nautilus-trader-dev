"""
Orchestrate the exit optimal stopping study end-to-end.

Runs all phases sequentially, halts on failure.
"""

import subprocess
import sys
from pathlib import Path
import time

STUDY_DIR = Path("studies/rl_regime_feasibility/exit_optimal_stopping")
PYTHON    = sys.executable

PHASES = [
    ("Phase 0: Entry populations",   STUDY_DIR / "build_entry_population.py"),
    ("Phase 1: Exit atlas",          STUDY_DIR / "build_exit_atlas.py"),
    ("Phase 2-3: Exit features",     STUDY_DIR / "build_exit_features.py"),
    ("Phase 4: Exit targets",        STUDY_DIR / "build_exit_targets.py"),
    ("Phase 5-6: Train models",      STUDY_DIR / "train_models.py"),
    ("Phase 7-9: Replay",            STUDY_DIR / "run_replay.py"),
    ("Phase 11: Controls",           STUDY_DIR / "run_controls.py"),
    ("Final report",                 STUDY_DIR / "generate_report.py"),
]


def run_phase(name: str, script: Path) -> bool:
    print(f"\n{'='*70}")
    print(f"STARTING: {name}")
    print(f"{'='*70}")
    t0 = time.time()
    result = subprocess.run(
        [PYTHON, str(script)],
        cwd=Path("C:/Users/Scott McCarty/Projects/Nautilus Trader"),
        capture_output=False,
    )
    elapsed = time.time() - t0
    if result.returncode != 0:
        print(f"\n{'!'*70}")
        print(f"FAILED: {name} (exit code {result.returncode})")
        print(f"{'!'*70}")
        return False
    print(f"\nCOMPLETE: {name} ({elapsed:.1f}s)")
    return True


def main():
    print("=" * 70)
    print("EXIT OPTIMAL STOPPING STUDY — FULL PIPELINE")
    print("=" * 70)
    t_start = time.time()

    for name, script in PHASES:
        if not run_phase(name, script):
            print(f"\nAborting at: {name}")
            sys.exit(1)

    elapsed = time.time() - t_start
    print(f"\n{'='*70}")
    print(f"ALL PHASES COMPLETE ({elapsed:.1f}s)")
    print(f"Results in: {STUDY_DIR / 'results/'}")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
