"""ALL_FLIPS population: enter on every completed 1m regime flip.

Entry anchor (per audit/population_definition.md):
  1. 1m regime flip bar closes (decision_ts = that bar's ts_init)
  2. signal is known immediately -- no confirmation wait
  3. entry scheduled immediately (entry_delay_ns=0)
  4. entry filled at next available executable 1s-open

No population-specific mechanics live here beyond "which flips are
eligible" (all of them, in RTH) -- fill timing, MFE/MAE anchoring, and
opposing-flip exit all come from the shared base class.
"""

from __future__ import annotations

from studies._shared_exit_mgmt.base_strategy import (
    ExitManagementBaseConfig, ExitManagementBaseStrategy,
)


class AllFlipsConfig(ExitManagementBaseConfig, frozen=True):
    pass


class AllFlipsStrategy(ExitManagementBaseStrategy):
    """No confirmation gating: every RTH regime flip is a candidate
    entry. Inherits the base class's no-op `_check_pending_confirmation`."""

    def _on_regime_flip(self, new_regime, bar_data, decision_ts,
                            bar_ts_event, in_rth):
        if not in_rth:
            return
        self._diag["rth_flips"] += 1
        s_1m = self._registry.get("1m")
        atr_at_signal = s_1m.atr if s_1m is not None else float("nan")
        self._schedule_entry(
            direction=int(new_regime),
            decision_ts=decision_ts,
            atr_at_signal=atr_at_signal,
            regime_start_ts=int(bar_data["ts_init"]),
        )
