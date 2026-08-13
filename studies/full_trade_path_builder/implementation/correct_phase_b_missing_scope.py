"""One-time provenance-preserving correction of Phase B missing diagnostics."""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from .run_phase_a_collect import atomic_json, sha256_file

NS = 1_000_000_000


def filter_partition_rows(rows: list[dict], start_ns: int, end_ns: int) -> list[dict]:
    return [
        row for row in rows
        if start_ns <= row["checkpoint_decision_ns"] < end_ns
    ]


def filter_partition_table(
    table: pa.Table, start_ns: int, end_ns: int
) -> pa.Table:
    timestamps = table["checkpoint_decision_ns"].to_numpy()
    return table.filter(pa.array((timestamps >= start_ns) & (timestamps < end_ns)))


def write_staged_table(table: pa.Table, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    pq.write_table(table, tmp, compression="zstd")
    os.replace(tmp, path)


def prepared_install_action(
    current_hash: str, source_hash: str, target_hash: str, staged_exists: bool
) -> str:
    if current_hash == target_hash:
        return "target_installed"
    if current_hash == source_hash and staged_exists:
        return "install_staged"
    raise RuntimeError("unrecognized or unrecoverable prepared correction state")


def correct(root: Path) -> dict:
    manifests = sorted(root.glob("year=*/month=*/manifest.json"))
    if len(manifests) != 60:
        raise RuntimeError(f"expected 60 Phase B manifests, found {len(manifests)}")
    code_hash = sha256_file(Path(__file__))
    total_before = total_after = 0
    corrected = 0
    for manifest_path in manifests:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("status") != "complete":
            raise RuntimeError(f"partition is not globally complete: {manifest_path}")
        missing_path = manifest_path.with_name("missing_dispatch.parquet")
        staged_path = manifest_path.with_name("missing_dispatch.corrected.parquet")
        state = manifest.get("missing_scope_correction_status")
        current_hash = sha256_file(missing_path)

        if state == "complete":
            if current_hash != manifest.get("missing_dispatch_sha256"):
                raise RuntimeError(f"completed correction hash mismatch: {missing_path}")
            total_before += manifest["missing_dispatch_pre_correction_rows"]
            total_after += manifest["n_missing"]
            corrected += int(manifest["missing_scope_rows_removed"] > 0)
            continue

        if state == "prepared":
            if manifest.get("missing_scope_correction_code_sha256") != code_hash:
                raise RuntimeError(f"prepared by different correction code: {manifest_path}")
            source_hash = manifest["missing_dispatch_pre_correction_sha256"]
            target_hash = manifest["missing_dispatch_corrected_sha256"]
            action = prepared_install_action(
                current_hash, source_hash, target_hash, staged_path.exists()
            )
            if action == "install_staged":
                if not staged_path.exists() or sha256_file(staged_path) != target_hash:
                    raise RuntimeError(f"prepared staging artifact unavailable: {staged_path}")
                os.replace(staged_path, missing_path)
                current_hash = sha256_file(missing_path)
            if current_hash != target_hash:
                raise RuntimeError(f"unrecognized prepared correction state: {missing_path}")
        elif state is None:
            if current_hash != manifest["missing_dispatch_sha256"]:
                raise RuntimeError(f"pre-correction hash mismatch: {missing_path}")
            start_ns = int(datetime.fromisoformat(manifest["start"]).timestamp() * NS)
            end_ns = int(datetime.fromisoformat(manifest["end"]).timestamp() * NS)
            source = pq.read_table(missing_path)
            filtered = filter_partition_table(source, start_ns, end_ns)
            write_staged_table(filtered, staged_path)
            target_hash = sha256_file(staged_path)
            manifest["missing_scope_correction_status"] = "prepared"
            manifest["missing_dispatch_pre_correction_sha256"] = current_hash
            manifest["missing_dispatch_pre_correction_rows"] = len(source)
            manifest["missing_dispatch_corrected_sha256"] = target_hash
            manifest["missing_dispatch_corrected_rows"] = len(filtered)
            manifest["missing_scope_correction_code_sha256"] = code_hash
            atomic_json(manifest, manifest_path)
            os.replace(staged_path, missing_path)
            current_hash = sha256_file(missing_path)
            if current_hash != target_hash:
                raise RuntimeError(f"post-replacement hash mismatch: {missing_path}")
        else:
            raise RuntimeError(f"unknown correction state {state!r}: {manifest_path}")

        before = manifest["missing_dispatch_pre_correction_rows"]
        after = manifest["missing_dispatch_corrected_rows"]
        total_before += before
        total_after += after
        corrected += int(before != after)
        manifest["n_missing"] = after
        manifest["missing_dispatch_sha256"] = current_hash
        manifest["missing_scope"] = "[partition_start,partition_end)"
        manifest["missing_scope_rows_removed"] = before - after
        manifest["missing_scope_correction_status"] = "complete"
        atomic_json(manifest, manifest_path)
    result = {
        "status": "complete",
        "partition_count": len(manifests),
        "partitions_rewritten": corrected,
        "rows_before": total_before,
        "rows_after": total_after,
        "rows_removed": total_before - total_after,
        "correction_code_sha256": code_hash,
    }
    atomic_json(result, root / "missing_scope_correction_manifest.json")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--partition-root", required=True)
    args = parser.parse_args()
    print(json.dumps(correct(Path(args.partition_root)), indent=2))


if __name__ == "__main__":
    main()
