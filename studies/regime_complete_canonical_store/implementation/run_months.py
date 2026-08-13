"""Phase 3 supervisor: resumable partitioned build over 2021-2025.

Each month runs in its own subprocess. That is not an optimization: NautilusTrader
initializes a Rust logger once per process and panics on the second
`BacktestEngine` in the same interpreter, so an in-process loop cannot build more
than one partition. The accepted Phase B build uses the same pattern.

Each month is an independent, idempotent unit. A failed month is recorded and
skipped rather than aborting the build, and rerunning the supervisor retries only
what is missing -- no full restart after one bad partition. Progress is written
after every month so the run survives a kill.

`--shard-index` / `--shard-count` partition the month list so several supervisors
can run concurrently without coordinating.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

from studies.full_trade_path_builder.implementation.run_phase_a_collect import (  # noqa: E402
    sha256_file,
)
from studies.regime_complete_canonical_store.implementation.run_collect import (  # noqa: E402
    OUTPUTS,
)

SEALED_YEARS = (2021, 2022, 2023, 2024, 2025)
COLLECT_MODULE = "studies.regime_complete_canonical_store.implementation.run_collect"


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


def validated(output_dir: Path, start: datetime, end: datetime) -> dict | None:
    """Return the manifest only if the partition is complete and intact."""
    manifest_path = output_dir / "manifest.json"
    if not manifest_path.exists():
        return None
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("status") != "complete":
        return None
    if manifest["start"] != start.isoformat() or manifest["end"] != end.isoformat():
        raise RuntimeError(f"partition window mismatch: {output_dir}")
    for key, name in OUTPUTS.items():
        if sha256_file(output_dir / name) != manifest["sha256"][key]:
            raise RuntimeError(f"partition hash mismatch: {output_dir / name}")
    return manifest


def run(
    work_root: Path, years, progress_path: Path, retry_failed: bool,
    shard_index: int, shard_count: int, timeout_seconds: int,
) -> dict:
    if not 0 <= shard_index < shard_count:
        raise SystemExit("invalid shard assignment")
    work_root.mkdir(parents=True, exist_ok=True)
    progress = (
        json.loads(progress_path.read_text())
        if progress_path.exists()
        else {"partitions": {}}
    )
    started = time.time()

    for ordinal, (start, end) in enumerate(month_windows(years)):
        if ordinal % shard_count != shard_index:
            continue
        key = f"{start:%Y-%m}"
        output_dir = work_root / f"year={start:%Y}" / f"month={start:%m}"

        existing = validated(output_dir, start, end)
        if existing is not None:
            progress["partitions"][key] = {
                "status": "complete",
                "rows": existing["rows"],
                "sha256": existing["sha256"],
                "runtime_seconds": existing["runtime_seconds"],
                "warmup_flips_skipped": existing["warmup_flips_skipped"],
            }
            _save(progress, progress_path)
            continue

        prior = progress["partitions"].get(key)
        if prior and prior.get("status") == "failed" and not retry_failed:
            continue

        t0 = time.time()
        command = [
            sys.executable, "-m", COLLECT_MODULE,
            "--start", start.isoformat(),
            "--end", end.isoformat(),
            "--output-dir", str(output_dir),
            "--overwrite",
        ]
        try:
            completed = subprocess.run(
                command, capture_output=True, text=True, timeout=timeout_seconds
            )
            manifest = validated(output_dir, start, end)
            if completed.returncode != 0 or manifest is None:
                progress["partitions"][key] = {
                    "status": "failed",
                    "returncode": completed.returncode,
                    "stderr_tail": (completed.stderr or "")[-2000:],
                    "runtime_seconds": time.time() - t0,
                }
            else:
                progress["partitions"][key] = {
                    "status": "complete",
                    "rows": manifest["rows"],
                    "sha256": manifest["sha256"],
                    "runtime_seconds": manifest["runtime_seconds"],
                    "warmup_flips_skipped": manifest["warmup_flips_skipped"],
                }
        except subprocess.TimeoutExpired:
            progress["partitions"][key] = {
                "status": "failed",
                "error": f"timeout after {timeout_seconds}s",
                "runtime_seconds": time.time() - t0,
            }

        _save(progress, progress_path)
        done = sum(
            1 for p in progress["partitions"].values() if p["status"] == "complete"
        )
        print(
            f"{key}: {progress['partitions'][key]['status']}  "
            f"({done} complete, {time.time() - started:.0f}s elapsed)",
            flush=True,
        )

    return _summarize(progress, progress_path, started)


def _save(progress: dict, path: Path) -> None:
    progress["updated_at"] = datetime.now(timezone.utc).isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(progress, indent=2))
    tmp.replace(path)


def _summarize(progress: dict, path: Path, started: float) -> dict:
    complete = [p for p in progress["partitions"].values() if p["status"] == "complete"]
    failed = {k: v for k, v in progress["partitions"].items() if v["status"] == "failed"}
    progress["summary"] = {
        "partitions_complete": len(complete),
        "partitions_failed": len(failed),
        "failed_partitions": sorted(failed),
        "total_rows": {
            key: sum(p["rows"][key] for p in complete)
            for key in ("regimes", "scores", "paths", "missing")
        },
        "total_warmup_flips_skipped": sum(
            p.get("warmup_flips_skipped", 0) for p in complete
        ),
        "total_runtime_seconds": time.time() - started,
    }
    _save(progress, path)
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
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--timeout-seconds", type=int, default=3600)
    args = parser.parse_args()

    if any(year not in SEALED_YEARS for year in args.years):
        raise SystemExit(
            f"years must be within {SEALED_YEARS}; 2026 is reserved for runtime OOS"
        )

    progress = run(
        Path(args.work_root), args.years, Path(args.progress), args.retry_failed,
        args.shard_index, args.shard_count, args.timeout_seconds,
    )
    print(json.dumps(progress["summary"], indent=2))


if __name__ == "__main__":
    main()
