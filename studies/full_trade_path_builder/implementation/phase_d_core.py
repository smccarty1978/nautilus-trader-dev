"""Frozen factual endpoint construction for Phase D."""
from __future__ import annotations

import bisect


def build_trade_plans(
    selections: list[dict], flips: list[dict], sealed_boundary_ns: int
) -> list[dict]:
    by_direction = {
        direction: sorted(
            {
                int(row["confirm_flip_ns"])
                for row in flips
                if int(row["new_direction"]) == direction
            }
        )
        for direction in (-1, 1)
    }
    plans = []
    for selection in selections:
        row = dict(selection)
        direction = int(row["trade_direction"])
        confirm_ns = row.get("confirm_flip_ns")
        fallback_ns = None
        if confirm_ns is not None:
            candidates = by_direction[-direction]
            index = bisect.bisect_right(candidates, int(confirm_ns))
            if index < len(candidates):
                fallback_ns = candidates[index]
        row["fallback_exit_flip_ns"] = fallback_ns
        row["fallback_exit_flip_direction"] = (
            -direction if fallback_ns is not None else None
        )
        row["planned_path_end_ns"] = (
            int(fallback_ns) if fallback_ns is not None else sealed_boundary_ns
        )
        row["planned_right_censored"] = fallback_ns is None
        plans.append(row)
    return plans
