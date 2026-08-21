"""Collect the frozen 48-month structural feature grid with a progress card."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from studies.Codex_structural_regime_geometry_maturity.implementation.paths import COLLECTION_ROOT

ROOT = Path(__file__).resolve().parents[3]
OUT = COLLECTION_ROOT
PROGRESS = ROOT / "studies/Codex_structural_regime_geometry_maturity/_work/collection_progress.json"


def _months():
    for year in range(2021, 2025):
        for month in range(1, 13):
            start = datetime(year, month, 1, tzinfo=timezone.utc)
            end = datetime(year + (month == 12), 1 if month == 12 else month + 1, 1, tzinfo=timezone.utc)
            yield start, end


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-index", type=int, default=0)
    parser.add_argument("--end-index", type=int, default=48)
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    months = list(_months())[args.start_index:args.end_index]
    if not months: raise ValueError("empty collection slice")
    # The corrected collection is a sealed lineage, not a user-selectable
    # scratch location.  All downstream consumers import the same constant.
    output_root = OUT
    progress_path = output_root.parent / f"{output_root.name}_progress.json"
    output_root.mkdir(parents=True, exist_ok=True); completed = []
    for i, (start, end) in enumerate(months, args.start_index + 1):
        key = f"{start:%Y-%m}"; print(f"[{i}/48] {key}", flush=True)
        # Heartbeat before launching a child as well as after it completes. This
        # makes the bounded supervisor distinguish a live month from a genuine
        # parent-process stall without treating buffered child stdout as progress.
        progress_path.write_text(json.dumps({"status": "running", "completed": completed,
                                        "current": key, "expected_partitions": 48}, indent=2))
        # NautilusTrader's Rust logger is process-global; every partition gets a
        # fresh child process, matching the accepted canonical-store supervisor.
        subprocess.run([sys.executable, "-m",
                        "studies.Codex_structural_regime_geometry_maturity.implementation.run_collect",
                        "--start", start.isoformat(), "--end", end.isoformat(),
                        "--output-dir", str(output_root / key)], check=True)
        manifest = json.loads((output_root / key / "manifest.json").read_text())
        completed.append({"partition": key, "rows": manifest["rows"], "resumed": manifest["resumed"]})
        progress_path.write_text(json.dumps({"status": "running", "completed": completed,
                                        "current": key, "expected_partitions": 48}, indent=2))
    progress_path.write_text(json.dumps({"status": "complete", "completed": completed,
                                    "expected_partitions": 48}, indent=2))


if __name__ == "__main__": main()
