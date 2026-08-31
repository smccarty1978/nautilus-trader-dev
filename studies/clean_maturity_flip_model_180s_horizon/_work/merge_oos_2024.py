"""Reconcile + merge the 2024 OOS partition (single year) into one OOS frame.

Uses only research_workflow.partitioning.reconcile_partitions /
merge_partition_outputs. Writes:
  artifacts/oos_candidates_merged.parquet
  artifacts/oos_observations_merged.parquet
  artifacts/oos_collection_manifest.json
  artifacts/oos_partition_merge.json
"""
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, r"C:\Users\Scott McCarty\Projects\Nautilus Trader")
from research_workflow import partitioning

STUDY_PATH = Path(r"C:\Users\Scott McCarty\Projects\Nautilus Trader\studies\clean_maturity_flip_model_180s_horizon")
RESULT_PATH = STUDY_PATH / "_work" / "oos_2024_partitioned_collect_result.json"
KEY = ["observation_ts", "regime_start_ns", "checkpoint_index"]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    result = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
    partitions, cframes, oframes = [], [], []
    for entry in result["partitions"]:
        partitions.append(entry["partition"])
        run = entry["run"]
        cframes.append(pd.read_parquet(Path(run["output_artifacts"]["candidates_parquet"])))
        oframes.append(pd.read_parquet(Path(run["output_artifacts"]["observations_parquet"])))

    reconciliation = partitioning.reconcile_partitions(partitions)
    if not reconciliation["passed"]:
        print("RECONCILIATION_FAILED", json.dumps(reconciliation)); sys.exit(1)

    merged_c = partitioning.merge_partition_outputs(cframes, partitions)
    merged_o = partitioning.merge_partition_outputs(oframes, partitions)

    art = STUDY_PATH / "artifacts"
    c_out = art / "oos_candidates_merged.parquet"
    o_out = art / "oos_observations_merged.parquet"
    merged_c.to_parquet(c_out, index=False)
    merged_o.to_parquet(o_out, index=False)
    c_sha, o_sha = sha256_file(c_out), sha256_file(o_out)

    auth = json.loads((art / "experiment_authorization.json").read_text(encoding="utf-8"))
    fz = json.loads((art / "train_experiment_freeze.json").read_text(encoding="utf-8"))

    dup_c = int(merged_c.duplicated([k for k in KEY if k in merged_c.columns]).sum())
    dup_o = int(merged_o.duplicated([k for k in KEY if k in merged_o.columns]).sum())
    disp = {str(k): int(v) for k, v in merged_o["disposition"].value_counts().to_dict().items()} \
        if "disposition" in merged_o.columns else {}

    # OOS pristineness proof: no observation, and no forward-looking resolution
    # timestamp, may fall outside calendar 2024.
    yr = pd.to_datetime(merged_o["observation_ts"], unit="ns", utc=True).dt.year
    fwd_cols = [c for c in ("flip_ts", "horizon_end_ts", "session_close_ts", "resolved_at_ts") if c in merged_o.columns]
    fwd_years = {}
    for c in fwd_cols:
        s = pd.to_numeric(merged_o[c], errors="coerce").dropna()
        if len(s):
            fwd_years[c] = [int(pd.Timestamp(int(s.min()), unit="ns", tz="UTC").year),
                            int(pd.Timestamp(int(s.max()), unit="ns", tz="UTC").year)]
    pristine = bool((yr == 2024).all()) and all(v == [2024, 2024] or v[0] >= 2024 for v in fwd_years.values())

    merge_payload = {
        "schema_version": 1,
        "study_id": "clean_maturity_flip_model_180s_horizon",
        "period": "oos",
        "partition_ids": [p["partition_id"] for p in partitions],
        "authorization_sha256": auth["authorization_sha256"],
        "train_freeze_sha256": fz["freeze_sha256"],
        "feature_instance_hashes": [p["feature_instance_sha256"] for p in partitions],
        "contract_hashes": [p["contract_sha256"] for p in partitions],
        "candidate_rows": int(len(merged_c)),
        "observation_rows": int(len(merged_o)),
        "duplicate_candidate_keys": dup_c,
        "duplicate_observation_keys": dup_o,
        "disposition_counts": disp,
        "observation_year_counts": {str(k): int(v) for k, v in yr.value_counts().sort_index().to_dict().items()},
        "forward_timestamp_year_ranges": fwd_years,
        "oos_pristine_2024_only": pristine,
        "candidate_columns": list(merged_c.columns),
        "observation_columns": list(merged_o.columns),
        "reconciliation_passed": reconciliation["passed"],
        "merge_sha256": hashlib.sha256((c_sha + o_sha).encode("utf-8")).hexdigest(),
    }
    (art / "oos_partition_merge.json").write_text(json.dumps(merge_payload, indent=2), encoding="utf-8")
    (art / "oos_collection_manifest.json").write_text(json.dumps({
        "schema_version": 1, "period": "oos",
        "candidate_rows": int(len(merged_c)), "observation_rows": int(len(merged_o)),
        "candidate_sha256": c_sha, "observation_sha256": o_sha,
        "authorization_sha256": auth["authorization_sha256"],
        "train_freeze_sha256": fz["freeze_sha256"],
    }, indent=2), encoding="utf-8")

    print("OOS_MERGE_DONE", json.dumps({
        "candidate_rows": len(merged_c), "observation_rows": len(merged_o),
        "reconciliation_passed": reconciliation["passed"],
        "dup_c": dup_c, "dup_o": dup_o, "disposition": disp,
        "oos_pristine_2024_only": pristine, "forward_year_ranges": fwd_years,
    }))


if __name__ == "__main__":
    main()
