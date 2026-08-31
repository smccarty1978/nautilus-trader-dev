"""Bounded March-2024 NT collection for the runtime-determinism parity validation.

Independent bounded window through the SAME governed path as the frozen full-year
2024 OOS run: research_workflow.partitioning.collect_partition -> run_collect_mode
-> NautilusTrader BacktestEngine + generic_collector.FlipPredictionCollector.

Warmup: the governed production mechanism is a fixed 5 calendar days
(resolve_catalog_plan / engine_builder default; there is no knob) -- identical to
what the full-year run used before 2024-01-01. Streamed window
[2024-02-24, 2024-04-01]; candidates emitted only for [2024-03-01, 2024-03-31].
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, r"C:\Users\Scott McCarty\Projects\Nautilus Trader")
from research_workflow.partitioning import PartitionSpec, collect_partition
from research_workflow.experiment import load_authorization

S = Path(r"C:\Users\Scott McCarty\Projects\Nautilus Trader\studies\clean_maturity_flip_model_180s_horizon").resolve()
auth = load_authorization(S)
oos = json.loads((S / "_work" / "oos_2024_partitioned_collect_result.json").read_text())["partitions"][0]["partition"]

spec = PartitionSpec(
    partition_id="oos-2024-03", period="oos",
    primary_start="2024-03-01", primary_end="2024-03-31",
    warmup_start="2024-02-24", warmup_end="2024-03-31",
    lookahead_start="2024-03-31", lookahead_end="2024-04-01",
    authorization_sha256=auth.authorization_sha256, source_identity="catalog-authority",
    feature_instance_sha256=oos["feature_instance_sha256"], contract_sha256=oos["contract_sha256"],
)

result = collect_partition(str(S), spec, execute=True)
out = S / "_work" / "march2024_bounded_collect_result.json"
out.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
run = result["run"]
print("MARCH_BOUNDED_COLLECT_DONE", json.dumps({
    "status": result["status"],
    "partition_provenance_sha256": spec.provenance_sha256,
    "candidates_count": run.get("candidates_count"),
    "observations_count": run.get("observations_count"),
    "wall_time_seconds": run.get("wall_time_seconds"),
    "run_id": run.get("run_id"),
    "output_artifacts": run.get("output_artifacts"),
}, indent=2, default=str))
