"""Governed 2024 OOS collection for clean_maturity_flip_model_180s_horizon.

Single authorized OOS year (2024). Delegates entirely to the canonical library
entrypoint research_workflow.collection.collect_period_partitioned(period="oos"),
which enforces assert_oos_open() (aggregate TRAIN freeze must be present and its
lineage current) and binds the runtime authorization to the frozen train_freeze
sha256. No custom collection logic.
"""
import json
import sys
from pathlib import Path

STUDY_PATH = Path(r"C:\Users\Scott McCarty\Projects\Nautilus Trader\studies\clean_maturity_flip_model_180s_horizon")
sys.path.insert(0, r"C:\Users\Scott McCarty\Projects\Nautilus Trader")

from research_workflow import collection


def main():
    result = collection.collect_period_partitioned(
        str(STUDY_PATH),
        period="oos",
        years=[2024],
        execute=True,
    )
    out_path = STUDY_PATH / "_work" / "oos_2024_partitioned_collect_result.json"
    out_path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print("OOS_PARTITIONED_COLLECT_DONE", json.dumps({
        "status": result.get("status"),
        "partition_count": result.get("partition_count"),
    }))


if __name__ == "__main__":
    main()
