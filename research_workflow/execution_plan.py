"""Compiled, study-scoped execution plans for the generic NT collector.

The plan is deliberately small: it binds the already-resolved provider methods and
output surface once during strategy construction.  It is not a second resolver or a
study-specific collector; the compiler/runtime simply selects the groups required by
the declared FeatureInstances.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Tuple


@dataclass(frozen=True)
class CompiledExecutionPlan:
    """Immutable callback groups and output layout for one compiled study."""

    feature_aliases: Tuple[str, ...]
    compact_surface: bool
    update_1s_callbacks: Tuple[Callable[[int, float, float, float], None], ...]
    update_1m_callbacks: Tuple[Callable[..., None], ...]
    checkpoint_callbacks: Tuple[Callable[..., dict], ...]
    calculate_velocity_at_checkpoint: bool
    calculate_ema_at_checkpoint: bool

    @classmethod
    def for_collector(cls, collector, aliases: Tuple[str, ...]) -> "CompiledExecutionPlan":
        """Compile the declared surface into fixed callback groups.

        Provider output names are inspected once here.  In particular, a declared
        instance whose provider has no output binding is retained as a null column
        (the historical contract) without paying for an unused calculation at every
        checkpoint.
        """
        compact = bool(aliases) and set(aliases).issubset(collector._compact_supported)
        if not compact:
            return cls(aliases, False, (), (), (), False, False)

        # These are the only providers needed by the current compact V2 surface.
        update_1s = (
            collector.structural_geometry_tracker.on_1s,
            collector.rolling_productivity_tracker.on_completed_1s,
        )
        # 1m regime/aggregation routing remains in the collector's fixed 1m
        # callback; it is initialized once and does not perform feature discovery.
        update_1m: Tuple[Callable[..., None], ...] = ()

        # The legacy velocity tracker exposes arrival_vel_* / arrival_accel_* names,
        # while this study's canonical aliases are arrival_velocity/arrival_acceleration.
        # Preserve the proven null compatibility surface and avoid an unused snapshot.
        velocity_outputs = {"arrival_vel_5s", "arrival_vel_10s", "arrival_vel_20s",
                            "arrival_vel_30s", "arrival_accel_5s", "arrival_accel_10s"}
        calculate_velocity = bool(set(aliases) & velocity_outputs)
        calculate_ema = "ema_slope_short" in aliases or "ema_slope_long" in aliases
        return cls(aliases, True, update_1s, update_1m, (), calculate_velocity, calculate_ema)
