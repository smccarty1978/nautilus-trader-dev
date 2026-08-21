#!/usr/bin/env python3
"""Run lifecycle reconciliation (Finding H2).

Six of the ten ES acceptance runs were left at ``status: RUNNING`` with no
``status.json`` and no collection outputs. Nothing distinguished them from a run still in
flight, and nothing distinguished either from a successful run except the absence of a
file that a reader had to know to look for.

Terminal states after reconciliation:

``SUCCESS``            the run persisted its outputs and passed its own validation
``FAILED_VALIDATION``  outputs persisted, but feature-surface or reconciliation checks failed
``FAILED``             the run raised and recorded the error
``ABORTED``            interrupted (Ctrl-C / SIGINT)
``ABANDONED``          left at RUNNING by a process that no longer exists

``ABANDONED`` is assigned by this tool, never by the run itself -- a process that dies
cannot write its own epitaph. Liveness is decided by PID: a RUNNING manifest whose PID is
still alive is genuinely active and is left alone.

Historical run directories are **never deleted and never rewritten**. Reconciliation is
recorded in a sidecar ``lifecycle.json`` inside the run directory, so the original
``run_manifest.json`` stays exactly as the run left it.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]

TERMINAL_STATES = {"SUCCESS", "FAILED", "FAILED_VALIDATION", "ABORTED", "ABANDONED", "COMPLETED"}
LIFECYCLE_FILENAME = "lifecycle.json"


def _pid_alive(pid: Optional[int]) -> bool:
    """Is a process with this PID currently running?

    An unknown PID is reported as not alive: a run that recorded no PID cannot be shown
    to be active, and treating "unknown" as "still running" would keep abandoned runs
    permanently unresolvable.
    """
    if not pid:
        return False
    try:
        if os.name == "nt":
            import subprocess
            out = subprocess.run(
                ["tasklist", "/FI", f"PID eq {int(pid)}", "/NH"],
                capture_output=True, text=True,
            ).stdout
            return str(pid) in out
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, PermissionError):
        return False


def classify_run(run_dir: Path) -> Dict[str, Any]:
    """Determines the current lifecycle state of one run directory."""
    manifest_p = run_dir / "run_manifest.json"
    status_p = run_dir / "status.json"

    record: Dict[str, Any] = {
        "run_id": run_dir.name,
        "run_dir": str(run_dir),
        "has_manifest": manifest_p.is_file(),
        "has_status": status_p.is_file(),
    }

    manifest: Dict[str, Any] = {}
    if manifest_p.is_file():
        try:
            manifest = json.loads(manifest_p.read_text(encoding="utf-8"))
        except ValueError:
            record["state"] = "CORRUPT"
            record["reason"] = "run_manifest.json is not valid JSON"
            return record

    status: Dict[str, Any] = {}
    if status_p.is_file():
        try:
            status = json.loads(status_p.read_text(encoding="utf-8"))
        except ValueError:
            record["state"] = "CORRUPT"
            record["reason"] = "status.json is not valid JSON"
            return record

    record["study_id"] = manifest.get("study_id")
    manifest_status = manifest.get("status")
    record["manifest_status"] = manifest_status
    record["status_status"] = status.get("status")

    # A run that recorded its own terminal state is already resolved.
    if status.get("status") in TERMINAL_STATES:
        record["state"] = status["status"]
        record["reason"] = "run recorded its own terminal status"
        return record
    if manifest_status in TERMINAL_STATES:
        record["state"] = manifest_status
        record["reason"] = "manifest recorded a terminal status"
        return record

    if manifest_status == "RUNNING":
        pid = manifest.get("pid")
        if _pid_alive(pid):
            record["state"] = "RUNNING"
            record["reason"] = f"process {pid} is still alive"
        else:
            record["state"] = "ABANDONED"
            record["reason"] = (
                f"manifest says RUNNING but "
                + (f"process {pid} is not alive" if pid else "no pid was recorded")
                + "; no terminal status was ever written"
            )
        return record

    record["state"] = "UNKNOWN"
    record["reason"] = f"unrecognised manifest status {manifest_status!r}"
    return record


def reconcile_runs(
    runs_dir: Optional[Path] = None,
    study_id: Optional[str] = None,
    write: bool = True,
) -> Dict[str, Any]:
    """Classifies every run directory and records the verdict in a sidecar."""
    runs_dir = runs_dir or (REPO_ROOT / "runs")
    if not runs_dir.is_dir():
        return {"runs_dir": str(runs_dir), "runs": [], "counts": {}}

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    records: List[Dict[str, Any]] = []

    for d in sorted(p for p in runs_dir.iterdir() if p.is_dir()):
        if study_id and study_id not in d.name:
            continue
        rec = classify_run(d)
        rec["reconciled_at_utc"] = now
        records.append(rec)

        if write and rec["state"] != "RUNNING":
            # Sidecar only. The original run_manifest.json is left byte-identical so the
            # forensic record of what the run itself claimed survives reconciliation.
            (d / LIFECYCLE_FILENAME).write_text(
                json.dumps({
                    "lifecycle_version": 1,
                    "run_id": rec["run_id"],
                    "terminal_state": rec["state"],
                    "reason": rec["reason"],
                    "reconciled_at_utc": now,
                    "reconciled_by": "scripts/reconcile_runs.py",
                    "note": (
                        "Sidecar verdict. run_manifest.json is preserved exactly as the run "
                        "left it; this file records the state the run could not record itself."
                    ),
                }, indent=2),
                encoding="utf-8",
            )

    counts: Dict[str, int] = {}
    for r in records:
        counts[r["state"]] = counts.get(r["state"], 0) + 1

    return {"runs_dir": str(runs_dir), "runs": records, "counts": counts}


def main() -> int:
    ap = argparse.ArgumentParser(description="Reconcile run directory lifecycle states")
    ap.add_argument("--runs-dir", type=str, default=None)
    ap.add_argument("--study", type=str, default=None, help="Only runs whose id contains this")
    ap.add_argument("--dry-run", action="store_true", help="Classify without writing sidecars")
    ap.add_argument("--json", type=str, help="Write the full report here")
    args = ap.parse_args()

    report = reconcile_runs(
        Path(args.runs_dir) if args.runs_dir else None,
        study_id=args.study,
        write=not args.dry_run,
    )

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("=" * 60)
    print(f"RUN LIFECYCLE RECONCILIATION: {report['runs_dir']}")
    for state, n in sorted(report["counts"].items()):
        print(f"  {state:<20} {n}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
