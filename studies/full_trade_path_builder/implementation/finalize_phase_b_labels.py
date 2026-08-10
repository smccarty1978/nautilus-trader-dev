"""Globally finalize Phase B next-flip labels after all monthly score partitions exist."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pyarrow.parquet as pq

from studies.full_trade_path_builder.implementation.run_phase_a_collect import (
    SEALED_BOUNDARY, atomic_json, atomic_parquet, sha256_file,
)
from studies.full_trade_path_builder.implementation.run_phase_b_collect import (
    NS,
    ROOT,
    add_labels,
    runtime_identity,
)


def finalize(root: Path) -> dict:
    partitions = sorted(root.glob("year=*/month=*"))
    expected = {
        (year, month) for year in range(2021, 2026) for month in range(1, 13)
    }
    actual = {
        (int(p.parent.name.split("=")[1]), int(p.name.split("=")[1]))
        for p in partitions
    }
    if actual != expected or len(partitions) != 60:
        raise RuntimeError(
            f"global finalization requires exact 60-month 2021-2025 set; "
            f"missing={sorted(expected-actual)} extra={sorted(actual-expected)}"
        )
    config_hash = sha256_file(
        ROOT / "studies/full_trade_path_builder/config/phase_b.yaml"
    )
    expected_runtime_identity = runtime_identity()
    flip_by_key: dict[tuple[int, int], dict] = {}
    for partition in partitions:
        manifest = json.loads((partition / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("status") != "scores_complete_labels_provisional":
            raise RuntimeError(f"partition is not in provisional state: {partition}")
        if int(manifest.get("warmup_days", -1)) != 4:
            raise RuntimeError(
                f"non-canonical warmup in {partition}: "
                f"{manifest.get('warmup_days')!r}; expected 4"
            )
        if manifest.get("config_sha256") != config_hash:
            raise RuntimeError(
                f"stale config hash in {partition}: "
                f"{manifest.get('config_sha256')!r}; expected {config_hash}"
            )
        if manifest.get("runtime_identity") != expected_runtime_identity:
            raise RuntimeError(f"mixed or stale runtime identity in {partition}")
        year, month = int(partition.parent.name[5:]), int(partition.name[6:])
        ct = ZoneInfo("America/Chicago")
        start = datetime(year, month, 1, tzinfo=ct).astimezone(timezone.utc)
        end = (
            SEALED_BOUNDARY
            if (year, month) == (2025, 12)
            else (
                datetime(year + 1, 1, 1, tzinfo=ct)
                if month == 12
                else datetime(year, month + 1, 1, tzinfo=ct)
            ).astimezone(timezone.utc)
        )
        if manifest["start"] != start.isoformat() or manifest["end"] != end.isoformat():
            raise RuntimeError(f"partition interval mismatch: {partition}")
        for name, field in (
            ("canonical_model_scores.parquet", "canonical_model_scores_sha256"),
            ("confirmed_flips.parquet", "confirmed_flips_sha256"),
            ("missing_dispatch.parquet", "missing_dispatch_sha256"),
        ):
            if sha256_file(partition / name) != manifest[field]:
                raise RuntimeError(f"partition hash mismatch: {partition / name}")
        for row in pq.read_table(partition / "confirmed_flips.parquet").to_pylist():
            flip_by_key[(row["confirm_flip_ns"], row["new_direction"])] = row
    flips = sorted(flip_by_key.values(), key=lambda row: row["confirm_flip_ns"])
    flip_ledger_hash = hashlib.sha256(
        json.dumps(flips, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    finalizer_code_hash = sha256_file(Path(__file__))
    bull = [r["confirm_flip_ns"] for r in flips if r["new_direction"] == 1]
    bear = [r["confirm_flip_ns"] for r in flips if r["new_direction"] == -1]
    observation_end = int(SEALED_BOUNDARY.timestamp() * NS)
    total = 0
    for partition in partitions:
        path = partition / "canonical_model_scores.parquet"
        rows = pq.read_table(path).to_pylist()
        labeled = [add_labels(row, bull, bear, observation_end) for row in rows]
        atomic_parquet(labeled, path)
        manifest_path = partition / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["canonical_model_scores_sha256"] = sha256_file(path)
        manifest["labels_finalized_globally"] = True
        manifest["status"] = "complete"
        manifest["global_flip_count"] = len(flips)
        manifest["global_flip_ledger_sha256"] = flip_ledger_hash
        manifest["label_finalizer_code_sha256"] = finalizer_code_hash
        manifest["global_observation_end_ns"] = observation_end
        atomic_json(manifest, manifest_path)
        total += len(labeled)
    result = {
        "status": "complete",
        "partition_count": len(partitions),
        "row_count": total,
        "unique_flip_count": len(flips),
        "global_flip_ledger_sha256": flip_ledger_hash,
        "label_finalizer_code_sha256": finalizer_code_hash,
        "observation_end_ns": observation_end,
    }
    atomic_json(result, root / "global_label_manifest.json")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--partition-root", required=True)
    args = parser.parse_args()
    print(json.dumps(finalize(Path(args.partition_root)), indent=2))


if __name__ == "__main__":
    main()
