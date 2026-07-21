"""F2_CONFIRMED population: bar+1 HH/LL + momentum confirmed entries,
NO 30-second delay (the delayed-activation convention used by
rank_filter_oos_validation / f5_flip_filter_repair is a deprecated
artifact from those studies and is explicitly NOT used here).

Entry anchor (per audit/population_definition.md):
  1. 1m regime flip
  2. bar+1 HH/LL confirmation (long: bar+1 high > flip bar high;
     short: bar+1 low < flip bar low)
  3. bar+1 directional close (long: close > open; short: close < open)
  4. entry scheduled immediately after bar+1 confirmation
     (entry_delay_ns=0 -- no 30s delay)
  5. next available executable 1s-open fill
  6. pending entry canceled if the opposite flip occurs before the
     executable fill (handled by the shared base class)

The confirmation predicate itself is IDENTICAL to the HH/LL + momentum
check in collectors/collector_v2/strategy.py._evaluate_bar1_check
(same math, re-derived here rather than imported because that class
also carries collector_v2-specific feature/microstructure logic this
study does not need -- reusing the predicate's logic, not its cached
outputs).
"""

from __future__ import annotations

from studies._shared_exit_mgmt.base_strategy import (
    ExitManagementBaseConfig, ExitManagementBaseStrategy,
)


class F2ConfirmedConfig(ExitManagementBaseConfig, frozen=True):
    pass


class F2ConfirmedStrategy(ExitManagementBaseStrategy):

    def _check_pending_confirmation(self, bar_data, decision_ts,
                                        bar_ts_event):
        if self._pending_flip is None:
            return
        if bar_ts_event <= self._pending_flip["flip_ts_event"]:
            # Defensive only: given _check_pending_confirmation always
            # runs before this same call's _on_regime_flip (see base
            # class), _pending_flip can never hold the current bar's
            # own data here, so this guard is not expected to fire in
            # practice. Kept as a safety net against future refactors.
            return
        d = self._pending_flip["direction"]
        bar_h = float(bar_data["high"]); bar_l = float(bar_data["low"])
        bar_o = float(bar_data["open"]); bar_c = float(bar_data["close"])
        if d == 1:
            hhll_ok = bar_h > self._pending_flip["flip_h"]
            momentum_ok = bar_c > bar_o
        else:
            hhll_ok = bar_l < self._pending_flip["flip_l"]
            momentum_ok = bar_c < bar_o
        confirmed = bool(hhll_ok and momentum_ok)
        if confirmed:
            s_1m = self._registry.get("1m")
            atr_at_signal = (s_1m.atr if s_1m is not None
                                else float("nan"))
            self._schedule_entry(
                direction=d,
                decision_ts=decision_ts,
                atr_at_signal=atr_at_signal,
                regime_start_ts=int(self._pending_flip["flip_ts_init"]),
            )
        self._pending_flip = None  # confirmation check done either way

    def _on_regime_flip(self, new_regime, bar_data, decision_ts,
                            bar_ts_event, in_rth):
        if not in_rth:
            return
        self._diag["rth_flips"] += 1
        self._pending_flip = {
            "flip_ts_event": int(bar_ts_event),
            "flip_ts_init": int(bar_data["ts_init"]),
            "flip_h": float(bar_data["high"]),
            "flip_l": float(bar_data["low"]),
            "flip_c": float(bar_data["close"]),
            "direction": int(new_regime),
        }
