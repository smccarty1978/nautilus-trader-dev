"""Exact short-prefix versus long-prefix Phase B boundary comparison."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pyarrow.compute as pc
import pyarrow as pa
import pyarrow.parquet as pq

from .run_phase_a_collect import atomic_json
from .run_phase_a_collect import sha256_file


def validate_pair(short_dir: Path, long_dir: Path) -> dict:
    if short_dir.resolve() == long_dir.resolve():
        raise RuntimeError("short and long boundary directories must be distinct")
    short_manifest = json.loads(
        (short_dir / "manifest.json").read_text(encoding="utf-8")
    )
    long_manifest = json.loads(
        (long_dir / "manifest.json").read_text(encoding="utf-8")
    )
    if short_manifest.get("warmup_days") != 4 or long_manifest.get("warmup_days") != 30:
        raise RuntimeError("boundary pair must be exact 4-day versus 30-day warmup")
    if short_manifest.get("status") != "scores_complete_labels_provisional":
        raise RuntimeError("short boundary artifact is not provisional-complete")
    if long_manifest.get("status") != "scores_complete_labels_provisional":
        raise RuntimeError("long boundary artifact is not provisional-complete")
    if (short_manifest["start"], short_manifest["end"]) != (
        long_manifest["start"], long_manifest["end"]
    ):
        raise RuntimeError("boundary output intervals differ")
    for key in ("config_sha256", "catalog_identity", "runtime_identity"):
        if short_manifest[key] != long_manifest[key]:
            raise RuntimeError(f"boundary provenance mismatch: {key}")
    for directory, manifest in (
        (short_dir, short_manifest), (long_dir, long_manifest)
    ):
        for name, key in (
            ("canonical_model_scores.parquet", "canonical_model_scores_sha256"),
            ("confirmed_flips.parquet", "confirmed_flips_sha256"),
            ("missing_dispatch.parquet", "missing_dispatch_sha256"),
        ):
            if sha256_file(directory / name) != manifest[key]:
                raise RuntimeError(f"boundary artifact hash mismatch: {directory/name}")
    from datetime import datetime
    short_prefix_start_ns = int(
        datetime.fromisoformat(short_manifest["load_start"]).timestamp() * 1e9
    )
    long_flips = sorted(
        pq.read_table(long_dir / "confirmed_flips.parquet")
        .column("confirm_flip_ns").to_pylist()
    )
    before = [value for value in long_flips if value <= short_prefix_start_ns]
    after = [value for value in long_flips if value > short_prefix_start_ns]
    active_across_short_prefix_start = bool(before and after)
    short = pq.read_table(short_dir / "canonical_model_scores.parquet")
    long = pq.read_table(long_dir / "canonical_model_scores.parquet")
    if short.schema != long.schema:
        raise RuntimeError("boundary schemas differ")
    short = short.sort_by([("checkpoint_decision_ns", "ascending")])
    long = long.sort_by([("checkpoint_decision_ns", "ascending")])
    short_keys = short.column("checkpoint_decision_ns").to_pylist()
    long_keys = long.column("checkpoint_decision_ns").to_pylist()
    if short_keys != long_keys:
        raise RuntimeError(
            f"boundary key mismatch: short={len(short_keys)} long={len(long_keys)}"
        )
    mismatches = {}
    for name in short.column_names:
        if name not in long.column_names:
            mismatches[name] = "missing_long_column"
            continue
        left, right = short.column(name), long.column(name)
        if left.equals(right):
            continue
        equal = pc.equal(left, right)
        both_null = pc.and_(pc.is_null(left), pc.is_null(right))
        ok = pc.or_(equal, both_null)
        if pa.types.is_floating(left.type):
            ok = pc.or_(ok, pc.and_(pc.is_nan(left), pc.is_nan(right)))
        ok = pc.fill_null(ok, False)
        count = len(ok) - pc.sum(pc.cast(ok, "int64")).as_py()
        if count:
            mismatches[name] = int(count)
    result = {
        "short_dir": str(short_dir),
        "long_dir": str(long_dir),
        "row_count": len(short),
        "column_count": len(short.column_names),
        "mismatches": mismatches,
        "active_regime_evidence": {
            "short_prefix_start_ns": short_prefix_start_ns,
            "last_long_prefix_flip_before_or_at": before[-1] if before else None,
            "first_long_prefix_flip_after": after[0] if after else None,
            "active_across_short_prefix_start": active_across_short_prefix_start,
        },
        "status": "pass" if not mismatches else "fail",
    }
    if mismatches:
        raise RuntimeError(json.dumps(result))
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--pairs-json", required=True)
    p.add_argument("--output", required=True)
    a = p.parse_args()
    pairs = json.loads(Path(a.pairs_json).read_text(encoding="utf-8"))
    results = [validate_pair(Path(x["short"]), Path(x["long"])) for x in pairs]
    payload = {
        "status": "pass",
        "pair_count": len(results),
        "total_rows": sum(x["row_count"] for x in results),
        "pairs": results,
    }
    atomic_json(payload, Path(a.output))
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
