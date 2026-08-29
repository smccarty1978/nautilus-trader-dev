"""Governed partitioned TRAIN collection for clean_maturity_flip_model_180s_horizon.

Runs one collector invocation per authorized TRAIN year (2021, 2022, 2023) through
research_workflow.collection.collect_period_partitioned (which itself delegates to
research_workflow.partitioning.collect_partition -> generic_collector.py). No custom
collection logic here -- this script only invokes the canonical library entrypoint and
prints a JSON status line per partition so run_bounded_study.py has progress to watch.
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
        period="train",
        years=[2021, 2022, 2023],
        execute=True,
    )
    out_path = STUDY_PATH / "_work" / "train_partitioned_collect_result.json"
    out_path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print("PARTITIONED_COLLECT_DONE", json.dumps({"status": result.get("status"), "partition_count": result.get("partition_count")}))


if __name__ == "__main__":
    main()
