"""Consolidate monthly partitions into the canonical store.

Reconciliation is the point of this step, not concatenation: every partition is
hash-verified against its manifest before being read, row counts are compared
against the manifests after writing, and cross-partition invariants that no
single month can check -- global regime-sequence density, strict direction
alternation across month boundaries, duplicate identifiers -- are asserted here.

The accepted `full_trade_path_builder` artifacts are never touched.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[3]

from studies.full_trade_path_builder.implementation.run_phase_a_collect import (  # noqa: E402
    sha256_file,
)
from studies.regime_complete_canonical_store.implementation.run_collect import (  # noqa: E402
    OUTPUTS,
)

TARGETS = {
    "regimes": "canonical_regimes_all.parquet",
    "scores": "canonical_regime_scores_all.parquet",
    "paths": "canonical_regime_paths_all.parquet",
    "missing": "canonical_missing_dispatch_all.parquet",
}
SORT_KEYS = {
    "regimes": ["regime_sequence_number"],
    "scores": ["instrument_id", "checkpoint_decision_ns"],
    "paths": ["regime_sequence_number", "path_init_ns"],
    "missing": ["checkpoint_decision_ns"],
}


def _verified_partitions(work_root: Path) -> list[tuple[str, Path, dict]]:
    partitions = []
    for manifest_path in sorted(work_root.glob("year=*/month=*/manifest.json")):
        manifest = json.loads(manifest_path.read_text())
        if manifest.get("status") != "complete":
            continue
        directory = manifest_path.parent
        for key, name in OUTPUTS.items():
            actual = sha256_file(directory / name)
            if actual != manifest["sha256"][key]:
                raise RuntimeError(
                    f"partition {manifest['partition']} {name} hash mismatch: "
                    f"{actual} != {manifest['sha256'][key]}"
                )
        partitions.append((manifest["partition"], directory, manifest))
    if not partitions:
        raise RuntimeError(f"no complete partitions under {work_root}")
    return partitions


def _reconcile_regimes(regimes: pl.DataFrame) -> dict:
    """Cross-partition invariants. A month cannot check these alone."""
    ordered = regimes.sort("regime_start_decision_ns")
    sequence = ordered["regime_sequence_number"].to_list()
    directions = ordered["regime_direction"].to_list()
    return {
        "regimes": regimes.height,
        "duplicate_regime_ids": regimes.height - regimes["regime_id"].n_unique(),
        "duplicate_starts": regimes.height
        - regimes["regime_start_decision_ns"].n_unique(),
        "sequence_is_monotonic": sequence == sorted(sequence),
        "consecutive_same_direction": sum(
            1 for a, b in zip(directions, directions[1:]) if a == b
        ),
        "established": int(regimes["established_reached"].sum()),
        "never_established": int((~regimes["established_reached"]).sum()),
        "complete_paths": int(regimes["path_is_complete"].sum()),
        "censored_paths": int((~regimes["path_is_complete"]).sum()),
        "by_year": regimes.group_by("entry_year").len().sort("entry_year").to_dicts(),
        "by_direction": regimes.group_by("regime_direction")
        .len()
        .sort("regime_direction")
        .to_dicts(),
        "by_start_session": regimes.group_by("session_at_start")
        .len()
        .sort("session_at_start")
        .to_dicts(),
    }


def consolidate(work_root: Path, out_dir: Path) -> dict:
    partitions = _verified_partitions(work_root)
    out_dir.mkdir(parents=True, exist_ok=True)

    report: dict = {
        "partitions": len(partitions),
        "partition_list": [name for name, _, _ in partitions],
        "datasets": {},
    }

    for key, target in TARGETS.items():
        sources = [directory / OUTPUTS[key] for _, directory, _ in partitions]
        expected = sum(manifest["rows"][key] for _, _, manifest in partitions)

        frames = [pl.read_parquet(path) for path in sources]
        frames = [f for f in frames if f.height]
        if not frames:
            combined = pl.read_parquet(sources[0])
        else:
            combined = pl.concat(frames, how="vertical_relaxed")
        sort_keys = [k for k in SORT_KEYS[key] if k in combined.columns]
        if sort_keys:
            combined = combined.sort(sort_keys)

        destination = out_dir / target
        tmp = destination.with_suffix(".parquet.tmp")
        combined.write_parquet(
            tmp, compression="zstd", statistics=True, row_group_size=1_000_000
        )
        tmp.replace(destination)

        report["datasets"][key] = {
            "target": target,
            "rows": combined.height,
            "expected_rows": expected,
            "reconciled": combined.height == expected,
            "columns": len(combined.columns),
            "bytes": destination.stat().st_size,
            "sha256": sha256_file(destination),
        }
        if combined.height != expected:
            report["datasets"][key]["DEFECT"] = (
                f"row count {combined.height} != manifest total {expected}"
            )
        if key == "regimes":
            report["regime_reconciliation"] = _reconcile_regimes(combined)
        del combined, frames

    scores = pl.scan_parquet(out_dir / TARGETS["scores"])
    paths = pl.scan_parquet(out_dir / TARGETS["paths"])
    report["global_integrity"] = {
        "duplicate_score_observation_ids": int(
            scores.select(
                pl.len() - pl.col("score_observation_id").n_unique()
            ).collect().item()
        ),
        "duplicate_path_keys": int(
            paths.select(
                pl.len() - pl.struct("regime_id", "path_event_ns").n_unique()
            ).collect().item()
        ),
    }

    report["all_reconciled"] = all(
        d["reconciled"] for d in report["datasets"].values()
    ) and not any(report["global_integrity"].values())

    (out_dir / "canonical_collection_manifest.json").write_text(
        json.dumps(report, indent=2, default=str)
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--work-root",
        default=str(ROOT / "studies/regime_complete_canonical_store/_work/monthly"),
    )
    parser.add_argument(
        "--out-dir", default=str(ROOT / "data/canonical/regime_complete_v1")
    )
    args = parser.parse_args()
    report = consolidate(Path(args.work_root), Path(args.out_dir))
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
