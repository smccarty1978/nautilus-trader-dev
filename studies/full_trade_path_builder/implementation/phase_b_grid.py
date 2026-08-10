"""Frozen Phase B five-second RTH grid helpers."""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

NS = 1_000_000_000
STEP_NS = 5 * NS
CT = ZoneInfo("America/Chicago")
SEALED_BOUNDARY_UTC = datetime(2026, 1, 1, tzinfo=timezone.utc)


def is_rth_grid_ns(timestamp_ns: int) -> bool:
    local = datetime.fromtimestamp(timestamp_ns / NS, tz=timezone.utc).astimezone(CT)
    seconds = local.hour * 3600 + local.minute * 60 + local.second
    return 8 * 3600 + 30 * 60 <= seconds < 15 * 3600


def expected_rth_grid_ns(start_ns: int, end_ns: int) -> list[int]:
    first = ((start_ns + STEP_NS - 1) // STEP_NS) * STEP_NS
    return [
        timestamp_ns
        for timestamp_ns in range(first, end_ns, STEP_NS)
        if is_rth_grid_ns(timestamp_ns)
    ]


def canonical_partition_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    if year not in range(2021, 2026) or month not in range(1, 13):
        raise RuntimeError(f"non-canonical Phase B partition: {year}-{month:02d}")
    start = datetime(year, month, 1, tzinfo=CT).astimezone(timezone.utc)
    if (year, month) == (2025, 12):
        end = SEALED_BOUNDARY_UTC
    elif month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=CT).astimezone(timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=CT).astimezone(timezone.utc)
    return start, end
