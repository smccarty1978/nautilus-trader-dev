"""Prove every production month prefix observes a confirmed flip before output."""
from __future__ import annotations

import bisect
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pyarrow.parquet as pq

from .run_phase_a_collect import atomic_json

ROOT = Path(__file__).resolve().parents[3]


def main():
    flip_times = set()
    paths = sorted(
        (ROOT / "studies/full_trade_path_builder/_work/phase_a_monthly")
        .glob("year=*/month=*/flips.parquet")
    )
    if len(paths) != 60:
        raise RuntimeError("accepted Phase A flip ledger must contain 60 partitions")
    for path in paths:
        flip_times.update(
            pq.read_table(path, columns=["confirm_flip_ns"]).column(0).to_pylist()
        )
    ordered = sorted(flip_times)
    ct = ZoneInfo("America/Chicago")
    rows, failures = [], []
    for year in range(2021, 2026):
        for month in range(1, 13):
            output_start = datetime(year, month, 1, tzinfo=ct).astimezone(timezone.utc)
            prefix_start = output_start - timedelta(days=4)
            out_ns = int(output_start.timestamp() * 1e9)
            prefix_ns = int(prefix_start.timestamp() * 1e9)
            index = bisect.bisect_right(ordered, prefix_ns)
            first = ordered[index] if index < len(ordered) else None
            covered = first is not None and first <= out_ns
            row = {
                "year": year, "month": month,
                "prefix_start_ns": prefix_ns, "output_start_ns": out_ns,
                "first_confirmed_flip_after_prefix_ns": first,
                "flip_observed_before_output": covered,
            }
            rows.append(row)
            if not covered:
                failures.append(row)
    payload = {
        "status": "pass" if not failures else "fail",
        "phase_a_partition_count": len(paths),
        "unique_flip_count": len(ordered),
        "boundaries_checked": len(rows),
        "failures": failures,
        "boundaries": rows,
    }
    output = ROOT / "studies/full_trade_path_builder/results/phase_b_prefix_flip_coverage.json"
    atomic_json(payload, output)
    print(json.dumps(payload, indent=2))
    if failures:
        raise RuntimeError("one or more month prefixes lack a pre-output confirmed flip")


if __name__ == "__main__":
    main()
