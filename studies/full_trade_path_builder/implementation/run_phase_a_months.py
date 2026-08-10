"""Sequential, restart-safe monthly Phase A collection."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def next_month(year: int, month: int) -> tuple[int, int]:
    return (year + 1, 1) if month == 12 else (year, month + 1)


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def validated_manifest(out: Path, start: str, end: str) -> dict | None:
    path = out / "manifest.json"
    if not path.exists():
        return None
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("status") != "complete":
        return None
    if manifest.get("start") != start or manifest.get("end") != end:
        raise RuntimeError(f"partition window mismatch: {out}")
    for name, key in (
        ("checkpoints.parquet", "checkpoints_sha256"),
        ("flips.parquet", "flips_sha256"),
        ("missing_dispatch.parquet", "missing_dispatch_sha256"),
    ):
        artifact = out / name
        if not artifact.exists() or file_hash(artifact) != manifest[key]:
            raise RuntimeError(f"partition artifact hash mismatch: {artifact}")
    return manifest


def run_month(cmd: list[str], out: Path, start: str, end: str) -> dict:
    existing = validated_manifest(out, start, end)
    if existing is not None:
        return existing
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    while True:
        manifest = validated_manifest(out, start, end)
        if manifest is not None:
            # NT occasionally retains a shutdown thread after all atomic
            # artifacts are complete. The monthly process is disposable;
            # the validated manifest is the authoritative completion signal.
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
            return manifest
        rc = proc.poll()
        if rc is not None:
            raise subprocess.CalledProcessError(rc, cmd)
        time.sleep(1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--progress-file", required=True)
    parser.add_argument("--first-year", type=int, default=2021)
    parser.add_argument("--last-year", type=int, default=2025)
    args = parser.parse_args()
    if args.last_year >= 2026:
        raise RuntimeError("sealed 2026 access prohibited")

    root, progress = Path(args.output_root), Path(args.progress_file)
    progress.parent.mkdir(parents=True, exist_ok=True)
    completed = []
    for year in range(args.first_year, args.last_year + 1):
        for month in range(1, 13):
            ny, nm = next_month(year, month)
            start = datetime(year, month, 1, tzinfo=timezone.utc).isoformat()
            end = datetime(ny, nm, 1, tzinfo=timezone.utc).isoformat()
            out = root / f"year={year}" / f"month={month:02d}"
            cmd = [
                sys.executable, "-m",
                "studies.full_trade_path_builder.implementation.run_phase_a_collect",
                "--start", start, "--end", end, "--output-dir", str(out),
            ]
            manifest = run_month(cmd, out, start, end)
            completed.append({
                "year": year, "month": month,
                "rows": manifest["n_checkpoints"],
                "sha256": manifest["checkpoints_sha256"],
            })
            progress.write_text(json.dumps({
                "status": "running",
                "last_completed": f"{year}-{month:02d}",
                "months_completed": len(completed),
                "rows_completed": sum(x["rows"] for x in completed),
            }, indent=2), encoding="utf-8")
    progress.write_text(json.dumps({
        "status": "complete", "months_completed": len(completed),
        "rows_completed": sum(x["rows"] for x in completed),
        "partitions": completed,
    }, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
