"""Phase 3 supervisor: resumable partitioned build over 2021-2025.

Each month is an independent, idempotent unit. A failed month is recorded and
skipped rather than aborting the build, and rerunning the supervisor retries
only what is missing -- no full restart after one bad partition.

Progress is written after every month so the run survives a kill.
"""
from __future__ import annotations

import argparse
import json
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

from studies.regime_complete_canonical_store.implementation.run_collect import (  # noqa: E402
    collect,
)

SEALED_YEARS = (2021, 2022, 2023, 2024, 2025)


def month_windows(years) -> list[tuple[datetime, datetime]]:
    windows = []
    for year in years:
        for month in range(1, 13):
            start = datetime(year, month, 1, tzinfo=timezone.utc)
            end = (
                datetime(year + 1, 1, 1, tzinfo=timezone.utc)
                if month == 12
                else datetime(year, month + 1, 1, tzinfo=timezone.utc)
            )
            windows.append((start, end))
    return windows


def run(work_root: Path, years, progress_path: Path, retry_failed: bool) -> dict:
    work_root.mkdir(parents=True, exist_ok=True)
    progress = (
        json.loads(progress_path.read_text())
        if progress_path.exists()
        else {"partitions": {}}
    )
    started = time.time()

    for start, end in month_windows(years):
        key = f"{start:%Y-%m}"
        prior = progress["partitions"].get(key)
        if prior and prior.get("status") == "complete":
            continue
        if prior and prior.get("status") == "failed" and not retry_failed:
            continue

        output_dir = work_root / f"year={start:%Y}" / f"month={start:%m}"
        t0 = time.time()
        try:
            manifest = collect(start, end, output_dir)
            progress["partitions"][key] = {
                "status": "complete",
                "rows": manifest["rows"],
                "sha256": manifest["sha256"],
                "runtime_seconds": manifest["runtime_seconds"],
                "resumed": manifest["resumed"],
                "warmup_flips_skipped": manifest["warmup_flips_skipped"],
            }
        except Exception as exc:  # noqa: BLE001 - one bad month must not stop the build
            progress["partitions"][key] = {
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc()[-2000:],
                "runtime_seconds": time.time() - t0,
            }
        progress["updated_at"] = datetime.now(timezone.utc).isoformat()
        progress_path.parent.mkdir(parents=True, exist_ok=True)
        progress_path.write_text(json.dumps(progress, indent=2))
        done = sum(
            1 for p in progress["partitions"].values() if p["status"] == "complete"
        )
        print(
            f"{key}: {progress['partitions'][key]['status']}  "
            f"({done} complete, {time.time() - started:.0f}s elapsed)",
            flush=True,
        )

    complete = [p for p in progress["partitions"].values() if p["status"] == "complete"]
    failed = {
        k: v for k, v in progress["partitions"].items() if v["status"] == "failed"
    }
    progress["summary"] = {
        "partitions_complete": len(complete),
        "partitions_failed": len(failed),
        "failed_partitions": sorted(failed),
        "total_rows": {
            key: sum(p["rows"][key] for p in complete)
            for key in ("regimes", "scores", "paths", "missing")
        },
        "total_runtime_seconds": time.time() - started,
    }
    progress_path.write_text(json.dumps(progress, indent=2))
    return progress


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--work-root",
        default=str(ROOT / "studies/regime_complete_canonical_store/_work/monthly"),
    )
    parser.add_argument("--years", nargs="*", type=int, default=list(SEALED_YEARS))
    parser.add_argument(
        "--progress",
        default=str(
            ROOT / "studies/regime_complete_canonical_store/_work/build_progress.json"
        ),
    )
    parser.add_argument("--retry-failed", action="store_true")
    args = parser.parse_args()

    if any(year not in SEALED_YEARS for year in args.years):
        raise SystemExit(
            f"years must be within {SEALED_YEARS}; 2026 is reserved for runtime OOS"
        )

    progress = run(
        Path(args.work_root), args.years, Path(args.progress), args.retry_failed
    )
    print(json.dumps(progress["summary"], indent=2))


if __name__ == "__main__":
    main()
