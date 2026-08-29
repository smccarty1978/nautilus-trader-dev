"""Reconcile the 3 TRAIN year partitions and merge them into one TRAIN frame.

Uses only research_workflow.partitioning.reconcile_partitions and
merge_partition_outputs (canonical library functions) -- no bespoke merge logic.
Writes:
  artifacts/train_candidates_merged.parquet
  artifacts/train_observations_merged.parquet
  artifacts/train_collection_manifest.json
  artifacts/train_partition_merge.json
"""
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, r"C:\Users\Scott McCarty\Projects\Nautilus Trader")

from research_workflow import partitioning

STUDY_PATH = Path(r"C:\Users\Scott McCarty\Projects\Nautilus Trader\studies\clean_maturity_flip_model_180s_horizon")

RESULT_PATH = STUDY_PATH / "_work" / "train_partitioned_collect_result.json"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    result = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
    partitions = []
    candidate_frames = []
    observation_frames = []
    candidate_paths = []
    observation_paths = []

    for entry in result["partitions"]:
        spec = entry["partition"]
        run = entry["run"]
        partitions.append(spec)
        cand_path = Path(run["output_artifacts"]["candidates_parquet"])
        obs_path = Path(run["output_artifacts"]["observations_parquet"])
        candidate_paths.append(cand_path)
        observation_paths.append(obs_path)
        candidate_frames.append(pd.read_parquet(cand_path))
        observation_frames.append(pd.read_parquet(obs_path))

    reconciliation = partitioning.reconcile_partitions(partitions)
    if not reconciliation["passed"]:
        print("RECONCILIATION_FAILED", json.dumps(reconciliation))
        sys.exit(1)

    merged_candidates = partitioning.merge_partition_outputs(candidate_frames, partitions)
    merged_observations = partitioning.merge_partition_outputs(observation_frames, partitions)

    artifacts_dir = STUDY_PATH / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    cand_out = artifacts_dir / "train_candidates_merged.parquet"
    obs_out = artifacts_dir / "train_observations_merged.parquet"
    merged_candidates.to_parquet(cand_out, index=False)
    merged_observations.to_parquet(obs_out, index=False)

    candidate_sha256 = sha256_file(cand_out)
    observation_sha256 = sha256_file(obs_out)

    auth_path = STUDY_PATH / "artifacts" / "experiment_authorization.json"
    auth = json.loads(auth_path.read_text(encoding="utf-8"))

    # duplicate key check counts (should be 0 -- merge_partition_outputs already
    # raises PartitionError on any overlap, so getting here means 0)
    key_columns = ["observation_ts", "regime_start_ns", "checkpoint_index"]
    dup_candidates = int(merged_candidates.duplicated([c for c in key_columns if c in merged_candidates.columns]).sum())
    dup_observations = int(merged_observations.duplicated([c for c in key_columns if c in merged_observations.columns]).sum())

    disposition_counts = {}
    if "disposition" in merged_observations.columns:
        disposition_counts = merged_observations["disposition"].value_counts().to_dict()
        disposition_counts = {str(k): int(v) for k, v in disposition_counts.items()}

    merge_payload = {
        "schema_version": 1,
        "study_id": "clean_maturity_flip_model_180s_horizon",
        "period": "train",
        "partition_ids": [p["partition_id"] for p in partitions],
        "authorization_sha256": auth["authorization_sha256"],
        "feature_instance_hashes": [p["feature_instance_sha256"] for p in partitions],
        "contract_hashes": [p["contract_sha256"] for p in partitions],
        "candidate_rows": int(len(merged_candidates)),
        "observation_rows": int(len(merged_observations)),
        "duplicate_candidate_keys": dup_candidates,
        "duplicate_observation_keys": dup_observations,
        "disposition_counts": disposition_counts,
        "candidate_columns": list(merged_candidates.columns),
        "observation_columns": list(merged_observations.columns),
        "candidate_dtypes": {c: str(merged_candidates[c].dtype) for c in merged_candidates.columns},
        "observation_dtypes": {c: str(merged_observations[c].dtype) for c in merged_observations.columns},
        "reconciliation_passed": reconciliation["passed"],
        "merge_sha256": hashlib.sha256((candidate_sha256 + observation_sha256).encode("utf-8")).hexdigest(),
    }
    (artifacts_dir / "train_partition_merge.json").write_text(
        json.dumps(merge_payload, indent=2), encoding="utf-8"
    )

    manifest_payload = {
        "schema_version": 1,
        "period": "train",
        "candidate_rows": int(len(merged_candidates)),
        "observation_rows": int(len(merged_observations)),
        "candidate_sha256": candidate_sha256,
        "observation_sha256": observation_sha256,
        "authorization_sha256": auth["authorization_sha256"],
    }
    (artifacts_dir / "train_collection_manifest.json").write_text(
        json.dumps(manifest_payload, indent=2), encoding="utf-8"
    )

    print("MERGE_DONE", json.dumps({
        "candidate_rows": len(merged_candidates),
        "observation_rows": len(merged_observations),
        "reconciliation_passed": reconciliation["passed"],
        "dup_candidates": dup_candidates,
        "dup_observations": dup_observations,
    }))


if __name__ == "__main__":
    main()
