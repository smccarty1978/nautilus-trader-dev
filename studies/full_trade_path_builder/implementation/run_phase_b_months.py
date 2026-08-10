"""Sequential, restart-safe Phase B monthly score build followed by global labels."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .finalize_phase_b_labels import finalize
from .run_phase_a_collect import SEALED_BOUNDARY, sha256_file
from .run_phase_b_collect import ROOT, runtime_identity


def next_month(year, month):
    return (year + 1, 1) if month == 12 else (year, month + 1)


def validated(out: Path, start: str, end: str, config_hash: str, identity: dict):
    path = out / "manifest.json"
    if not path.exists():
        return None
    m = json.loads(path.read_text(encoding="utf-8"))
    if m.get("status") not in ("scores_complete_labels_provisional", "complete"):
        return None
    if m["start"] != start or m["end"] != end:
        raise RuntimeError(f"partition window mismatch: {out}")
    if m.get("warmup_days") != 4:
        raise RuntimeError(f"noncanonical warmup partition: {out}")
    if m.get("config_sha256") != config_hash:
        raise RuntimeError(f"stale config partition: {out}")
    if m.get("runtime_identity") != identity:
        raise RuntimeError(f"mixed runtime partition: {out}")
    for name, key in (
        ("canonical_model_scores.parquet", "canonical_model_scores_sha256"),
        ("confirmed_flips.parquet", "confirmed_flips_sha256"),
        ("missing_dispatch.parquet", "missing_dispatch_sha256"),
    ):
        if sha256_file(out / name) != m[key]:
            raise RuntimeError(f"partition hash mismatch: {out/name}")
    return m


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output-root", required=True)
    p.add_argument("--progress-file", required=True)
    p.add_argument("--shard-index", type=int, default=0)
    p.add_argument("--shard-count", type=int, default=1)
    p.add_argument("--finalize", action="store_true")
    a = p.parse_args()
    root, progress = Path(a.output_root), Path(a.progress_file)
    ct = ZoneInfo("America/Chicago")
    config_hash = sha256_file(
        ROOT / "studies/full_trade_path_builder/config/phase_b.yaml"
    )
    identity = runtime_identity()
    if not (0 <= a.shard_index < a.shard_count):
        raise RuntimeError("invalid shard assignment")
    completed = []
    ordinal = 0
    for year in range(2021, 2026):
        for month in range(1, 13):
            assigned = ordinal % a.shard_count == a.shard_index
            ordinal += 1
            if not assigned:
                continue
            ny, nm = next_month(year, month)
            start = datetime(year, month, 1, tzinfo=ct).astimezone(timezone.utc).isoformat()
            end_dt = (
                SEALED_BOUNDARY
                if (year, month) == (2025, 12)
                else datetime(ny, nm, 1, tzinfo=ct).astimezone(timezone.utc)
            )
            end = end_dt.isoformat()
            out = root / f"year={year}" / f"month={month:02d}"
            m = validated(out, start, end, config_hash, identity)
            if m is None:
                cmd = [
                    sys.executable, "-m",
                    "studies.full_trade_path_builder.implementation.run_phase_b_collect",
                    "--start", start, "--end", end, "--output-dir", str(out),
                    "--warmup-days", "4",
                ]
                proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                while (m := validated(out, start, end, config_hash, identity)) is None:
                    if proc.poll() is not None:
                        raise subprocess.CalledProcessError(proc.returncode, cmd)
                    time.sleep(1)
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.terminate()
                    proc.wait(timeout=10)
            completed.append({"year": year, "month": month, "rows": m["n_rows"]})
            progress.parent.mkdir(parents=True, exist_ok=True)
            progress.write_text(json.dumps({
                "status": "building_scores", "months_completed": len(completed),
                "last_completed": f"{year}-{month:02d}",
                "rows_completed": sum(x["rows"] for x in completed),
            }, indent=2), encoding="utf-8")
    result = {
        "status": "score_shard_complete",
        "shard_index": a.shard_index,
        "shard_count": a.shard_count,
        "months_completed": len(completed),
        "rows_completed": sum(x["rows"] for x in completed),
    }
    if a.finalize:
        if a.shard_count != 1:
            raise RuntimeError("sharded workers may not finalize independently")
        result = finalize(root)
    progress.write_text(json.dumps(result, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
