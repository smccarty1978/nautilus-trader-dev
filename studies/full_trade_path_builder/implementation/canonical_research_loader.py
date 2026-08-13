"""Lazy loader for consolidated canonical research populations."""
from __future__ import annotations

from pathlib import Path

import polars as pl


REQUIRED = {
    "observations": {"checkpoint_decision_ns", "model_id", "trade_direction"},
    "trade_summaries": {
        "checkpoint_decision_ns",
        "model_id",
        "trade_direction",
        "trade_id",
    },
    "trade_paths": {
        "timestamp_close_ns",
        "model_id",
        "trade_direction",
        "trade_id",
    },
}


def scan_canonical_research_population(
    path: str,
    start: str | None = None,
    end: str | None = None,
    model_ids: list[str] | None = None,
    directions: list[str] | None = None,
) -> pl.LazyFrame:
    """Return a filtered lazy scan over one consolidated canonical artifact."""
    target = Path(path)
    name = target.name
    if "observations" in name:
        grain, timestamp = "observations", "checkpoint_decision_ns"
    elif "summaries" in name:
        grain, timestamp = "trade_summaries", "checkpoint_decision_ns"
    elif "paths" in name:
        grain, timestamp = "trade_paths", "timestamp_close_ns"
    else:
        raise ValueError(f"cannot identify canonical row grain from filename: {name}")
    frame = pl.scan_parquet(target)
    missing = REQUIRED[grain] - set(frame.collect_schema().names())
    if missing:
        raise ValueError(f"canonical {grain} artifact is missing columns: {sorted(missing)}")
    if start is not None:
        start_ns = int(pl.Series([start]).str.to_datetime(time_zone="UTC").dt.epoch("ns")[0])
        frame = frame.filter(pl.col(timestamp) >= start_ns)
    if end is not None:
        end_ns = int(pl.Series([end]).str.to_datetime(time_zone="UTC").dt.epoch("ns")[0])
        frame = frame.filter(pl.col(timestamp) < end_ns)
    if model_ids:
        frame = frame.filter(pl.col("model_id").is_in(model_ids))
    if directions:
        frame = frame.filter(
            pl.col("trade_direction").cast(pl.String).is_in(directions)
            | (
                pl.col("trade_direction_name").is_in(directions)
                if "trade_direction_name" in frame.collect_schema()
                else pl.lit(False)
            )
        )
    return frame


# Example:
# scan = scan_canonical_research_population(
#     "consolidated/canonical_trade_summaries_all.parquet",
#     start="2025-01-01T00:00:00Z",
#     end="2026-01-01T00:00:00Z",
#     directions=["LONG"],
# )
# result = scan.collect(engine="streaming")
