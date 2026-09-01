"""Governed Partitioned TRAIN Collection Script.
=============================================
Runs partitioned collection for 2021, 2022, and 2023 through research_workflow.partitioning.
"""

from __future__ import annotations

import json
from pathlib import Path
import pandas as pd

from research_workflow.partitioning import (
    build_year_partitions,
    collect_partition,
    reconcile_partitions,
    merge_partition_outputs,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
STUDY_DIR = REPO_ROOT / "studies" / "regime_transition_target_before_stop_v1"


def find_completed_partition_run(partition) -> tuple[Path, dict] | None:
    runs_dir = STUDY_DIR / "runs"
    if not runs_dir.exists():
        return None
    for run_path in sorted(runs_dir.glob(f"*_{STUDY_DIR.name}_full")):
        man_path = run_path / "run_manifest.json"
        status_path = run_path / "status.json"
        cands_path = run_path / "collection" / "candidates.parquet"
        obs_path = run_path / "collection" / "observations.parquet"
        if man_path.exists() and status_path.exists() and cands_path.exists() and obs_path.exists():
            man = json.loads(man_path.read_text(encoding="utf-8"))
            status = json.loads(status_path.read_text(encoding="utf-8"))
            if (
                man.get("dates", {}).get("start") == partition.primary_start
                and status.get("status") == "SUCCESS"
            ):
                return run_path, status
    return None


def main():
    print("============================================================")
    print("STARTING GOVERNED PARTITIONED TRAIN COLLECTION (2021-2023)")
    print("============================================================")

    partitions = build_year_partitions(STUDY_DIR, "train")
    print(f"Built {len(partitions)} TRAIN year partitions:")
    for p in partitions:
        print(f"  Partition: {p.partition_id} ({p.primary_start} to {p.primary_end})")

    collected_records = []
    candidates_frames = []
    observations_frames = []

    for p in partitions:
        print(f"\n---> Checking partition {p.partition_id}...")
        existing = find_completed_partition_run(p)
        if existing is not None:
            run_dir, status_data = existing
            print(f"     Reusing existing completed run for {p.partition_id}: {run_dir.name}")
            rec = {
                "status": "COLLECTED",
                "partition": p.to_dict(),
                "provenance_sha256": p.provenance_sha256,
                "run": {
                    "run_id": run_dir.name,
                    "run_dir": str(run_dir),
                    "candidates_count": status_data.get("candidates_count"),
                    "observations_count": status_data.get("observations_count"),
                }
            }
        else:
            print(f"     Executing collection for {p.partition_id}...")
            rec = collect_partition(STUDY_DIR, p, execute=True)
            run_info = rec["run"]
            run_id = run_info.get("run_id")
            run_dir = Path(run_info.get("run_dir") or (STUDY_DIR / "runs" / run_id))
            print(f"     Finished {p.partition_id}. Run dir: {run_dir.name}")
            print(f"     Candidates: {run_info.get('candidates_count')}, Observations: {run_info.get('observations_count')}")

        collected_records.append(rec)
        run_dir = Path(rec["run"].get("run_dir") or (STUDY_DIR / "runs" / rec["run"]["run_id"]))
        c_df = pd.read_parquet(run_dir / "collection" / "candidates.parquet")
        o_df = pd.read_parquet(run_dir / "collection" / "observations.parquet")
        candidates_frames.append(c_df)
        observations_frames.append(o_df)

    print("\n============================================================")
    print("RECONCILING AND MERGING PARTITIONS")
    print("============================================================")
    reconciled = reconcile_partitions(collected_records)
    print(f"Reconciliation: {'PASS' if reconciled['passed'] else 'FAIL'}")
    if not reconciled["passed"]:
        print(f"Findings: {reconciled['findings']}")
        raise RuntimeError("PARTITION_RECONCILIATION_FAILED")

    merged_candidates = merge_partition_outputs(candidates_frames, partitions)
    merged_observations = merge_partition_outputs(observations_frames, partitions)

    print(f"Merged Candidates shape: {merged_candidates.shape}")
    print(f"Merged Observations shape: {merged_observations.shape}")

    # Persist merged TRAIN collection in study _work/
    out_dir = STUDY_DIR / "_work" / "train_merged_collection"
    out_dir.mkdir(parents=True, exist_ok=True)
    merged_candidates.to_parquet(out_dir / "candidates.parquet")
    merged_observations.to_parquet(out_dir / "observations.parquet")

    summary = {
        "status": "PASS",
        "partitions": [p.to_dict() for p in partitions],
        "total_candidates": len(merged_candidates),
        "total_observations": len(merged_observations),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"Successfully saved merged TRAIN collection to: {out_dir}")


if __name__ == "__main__":
    main()
