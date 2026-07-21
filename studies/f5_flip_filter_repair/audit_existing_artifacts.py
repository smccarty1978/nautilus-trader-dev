"""Phase 0: Inventory and schema-audit every artifact from the prior
regime_sequence_chop_context study that this repair study reads or repairs.
Read-only: does not modify the source study.
"""
import json
from pathlib import Path
import pandas as pd

SRC = Path("studies/regime_sequence_chop_context/results")
OUT = Path("studies/f5_flip_filter_repair/results")
OUT.mkdir(parents=True, exist_ok=True)

REQUIRED = [
    "flip_validation_policy_grid.parquet",
    "flip_policy_episode_results.parquet",
    "flip_policy_metrics.parquet",
    "flip_runner_retention.parquet",
    "flip_segment_results.parquet",
    "flip_validation_metrics_F1.parquet",
    "flip_validation_metrics_F2.parquet",
    "baseline_population_metrics.parquet",
    "baseline_reproduction_audit.json",
    "control_results.parquet",
    "data_coverage.parquet",
    "execution_audit.parquet",
    "flip_feature_deciles.parquet",
    "flip_frozen_policy.json",
    "flip_model_manifest_F1.json",
    "flip_model_manifest_F2.json",
    "flip_monthly_results.parquet",
    "flip_context_atlas.parquet",       # cached feature table + F2 score inputs
    "median_center_features.parquet",
    "regime_sequence_features.parquet",
    "provenance_audit.json",
]


def run_audit():
    inventory = {}
    schema_rows = []
    for name in REQUIRED:
        p = SRC / name
        entry = {"path": str(p), "exists": p.exists()}
        if p.exists():
            entry["size_bytes"] = p.stat().st_size
            if name.endswith(".parquet"):
                try:
                    df = pd.read_parquet(p)
                    entry["rows"] = len(df)
                    entry["n_cols"] = df.shape[1]
                    for c in df.columns:
                        schema_rows.append({
                            "artifact": name,
                            "column": c,
                            "dtype": str(df[c].dtype),
                            "n_null": int(df[c].isna().sum()) if len(df) else 0,
                            "n_rows": len(df),
                        })
                except Exception as e:
                    entry["read_error"] = str(e)
            elif name.endswith(".json"):
                try:
                    with open(p) as f:
                        obj = json.load(f)
                    entry["top_level_keys"] = list(obj.keys()) if isinstance(obj, dict) else "list"
                except Exception as e:
                    entry["read_error"] = str(e)
        inventory[name] = entry

    missing = [k for k, v in inventory.items() if not v["exists"]]
    with open(OUT / "artifact_inventory.json", "w") as f:
        json.dump({
            "source_study": str(SRC),
            "required_count": len(REQUIRED),
            "found_count": len(REQUIRED) - len(missing),
            "missing": missing,
            "artifacts": inventory,
        }, f, indent=2, default=str)

    pd.DataFrame(schema_rows).to_parquet(OUT / "artifact_schema_audit.parquet", index=False)
    print(f"Artifact inventory: {len(REQUIRED)-len(missing)}/{len(REQUIRED)} found. Missing: {missing}")
    return inventory


if __name__ == "__main__":
    import os, sys
    PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
    os.chdir(PROJECT_ROOT)
    run_audit()
