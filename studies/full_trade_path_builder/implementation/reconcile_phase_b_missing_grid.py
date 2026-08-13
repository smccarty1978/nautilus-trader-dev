"""Reconcile finalized Phase B missing diagnostics to the exact RTH grid."""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from .phase_b_grid import canonical_partition_bounds, expected_rth_grid_ns
from .run_phase_a_collect import atomic_json, sha256_file

NS = 1_000_000_000
SCHEMA = pa.schema(
    [
        ("checkpoint_decision_ns", pa.int64()),
        ("suppression_reason", pa.string()),
    ]
)


def write_staged(table: pa.Table, path: Path) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    pq.write_table(table, tmp, compression="zstd")
    os.replace(tmp, path)


def target_table(score_keys: set[int], start_ns: int, end_ns: int) -> pa.Table:
    expected = expected_rth_grid_ns(start_ns, end_ns)
    if not score_keys.issubset(set(expected)):
        raise RuntimeError("score key lies outside canonical RTH grid")
    missing = [timestamp_ns for timestamp_ns in expected if timestamp_ns not in score_keys]
    return pa.Table.from_arrays(
        [
            pa.array(missing, type=pa.int64()),
            pa.array(["missing_dispatch_bar"] * len(missing), type=pa.string()),
        ],
        schema=SCHEMA,
    )


def reconcile(root: Path) -> dict:
    manifests = sorted(root.glob("year=*/month=*/manifest.json"))
    if len(manifests) != 60:
        raise RuntimeError(f"expected 60 manifests, found {len(manifests)}")
    actual = {
        (
            int(path.parent.parent.name.removeprefix("year=")),
            int(path.parent.name.removeprefix("month=")),
        )
        for path in manifests
    }
    expected = {(year, month) for year in range(2021, 2026) for month in range(1, 13)}
    if actual != expected:
        raise RuntimeError(
            f"non-canonical partition set; missing={sorted(expected-actual)} "
            f"extra={sorted(actual-expected)}"
        )
    code_hash = sha256_file(Path(__file__))
    total_before = total_after = rewritten = 0
    for manifest_path in manifests:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("status") != "complete":
            raise RuntimeError(f"partition not complete: {manifest_path}")
        partition = manifest_path.parent
        year = int(partition.parent.name.removeprefix("year="))
        month = int(partition.name.removeprefix("month="))
        expected_start, expected_end = canonical_partition_bounds(year, month)
        if (
            manifest.get("start") != expected_start.isoformat()
            or manifest.get("end") != expected_end.isoformat()
        ):
            raise RuntimeError(f"non-canonical partition interval: {partition}")
        score_path = partition / "canonical_model_scores.parquet"
        missing_path = partition / "missing_dispatch.parquet"
        staged_path = partition / "missing_dispatch.grid.parquet"
        if sha256_file(score_path) != manifest["canonical_model_scores_sha256"]:
            raise RuntimeError(f"score hash mismatch: {score_path}")
        state = manifest.get("missing_grid_reconciliation_status")
        current_hash = sha256_file(missing_path)

        if state == "complete":
            if current_hash != manifest["missing_dispatch_sha256"]:
                raise RuntimeError(f"completed grid hash mismatch: {missing_path}")
            total_before += manifest["missing_grid_pre_reconciliation_rows"]
            total_after += manifest["n_missing"]
            rewritten += int(
                manifest["missing_grid_pre_reconciliation_sha256"]
                != manifest["missing_dispatch_sha256"]
            )
            continue

        if state == "prepared":
            if manifest["missing_grid_reconciliation_code_sha256"] != code_hash:
                raise RuntimeError(f"prepared by different code: {manifest_path}")
            source_hash = manifest["missing_grid_pre_reconciliation_sha256"]
            target_hash = manifest["missing_grid_reconciled_sha256"]
            if current_hash == target_hash:
                pass
            elif current_hash == source_hash:
                if not staged_path.exists() or sha256_file(staged_path) != target_hash:
                    raise RuntimeError(f"missing/invalid staged target: {staged_path}")
                os.replace(staged_path, missing_path)
                current_hash = sha256_file(missing_path)
            else:
                raise RuntimeError(f"unrecognized prepared state: {missing_path}")
        elif state is None:
            if current_hash != manifest["missing_dispatch_sha256"]:
                raise RuntimeError(f"source hash mismatch: {missing_path}")
            start_ns = int(expected_start.timestamp() * NS)
            end_ns = int(expected_end.timestamp() * NS)
            keys = set(
                pq.read_table(
                    score_path, columns=["checkpoint_decision_ns"]
                )["checkpoint_decision_ns"].to_pylist()
            )
            source_rows = pq.read_metadata(missing_path).num_rows
            target = target_table(keys, start_ns, end_ns)
            write_staged(target, staged_path)
            target_hash = sha256_file(staged_path)
            manifest["missing_grid_reconciliation_status"] = "prepared"
            manifest["missing_grid_reconciliation_code_sha256"] = code_hash
            manifest["missing_grid_pre_reconciliation_sha256"] = current_hash
            manifest["missing_grid_pre_reconciliation_rows"] = source_rows
            manifest["missing_grid_reconciled_sha256"] = target_hash
            manifest["missing_grid_reconciled_rows"] = len(target)
            atomic_json(manifest, manifest_path)
            os.replace(staged_path, missing_path)
            current_hash = sha256_file(missing_path)
            if current_hash != target_hash:
                raise RuntimeError(f"installed target hash mismatch: {missing_path}")
        else:
            raise RuntimeError(f"unknown reconciliation state {state!r}")

        before = manifest["missing_grid_pre_reconciliation_rows"]
        after = manifest["missing_grid_reconciled_rows"]
        total_before += before
        total_after += after
        rewritten += int(
            manifest["missing_grid_pre_reconciliation_sha256"] != current_hash
        )
        manifest["n_missing"] = after
        manifest["missing_dispatch_sha256"] = current_hash
        manifest["missing_grid_reconciliation_status"] = "complete"
        manifest["missing_grid_reconciliation_added_rows"] = after - before
        atomic_json(manifest, manifest_path)

    result = {
        "status": "complete",
        "partition_count": len(manifests),
        "partitions_rewritten": rewritten,
        "rows_before": total_before,
        "rows_after": total_after,
        "rows_added": total_after - total_before,
        "reconciliation_code_sha256": code_hash,
    }
    atomic_json(result, root / "missing_grid_reconciliation_manifest.json")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--partition-root", required=True)
    args = parser.parse_args()
    print(json.dumps(reconcile(Path(args.partition_root)), indent=2))


if __name__ == "__main__":
    main()
