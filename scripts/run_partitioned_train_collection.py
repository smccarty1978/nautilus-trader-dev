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
        print(f"\n---> Collecting partition {p.partition_id}...")
        rec = collect_partition(STUDY_DIR, p, execute=True)
        collected_records.append(rec)
        run_info = rec["run"]
        run_dir = Path(run_info["run_dir"])
        print(f"     Finished {p.partition_id}. Run dir: {run_dir.name}")
        print(f"     Candidates: {run_info['candidates_count']}, Observations: {run_info['observations_count']}")

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

    # Persist merged TRAIN collection in study _work/ or runs/
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
