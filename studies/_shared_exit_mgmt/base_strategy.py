"""ExitManagementBaseStrategy -- population-agnostic NT entry/exit mechanics.

Shared by studies/all_flips_exit_management and
studies/f2_confirmed_exit_management. Provides ONLY infrastructure that
carries no assumption about which flips get traded:

  - regime-flip detection (via collectors.collector_v2 registry /
    aggregator / regime_engine -- the same causal, provenance-audited
    MTF state machine already used and audited elsewhere in this repo)
  - causal pending-entry scheduling + fill at the next executable 1s
    bar open (entry_delay_ns configurable; both current studies use 0)
  - cancellation of a pending entry if the opposite flip occurs before
    activation
  - baseline exit at the next opposing regime flip
  - fill-anchored (NOT flip-close-anchored) running MFE/MAE tracking,
    per the project's fill-anchoring rule
  - per-1s-bar causal checkpoint emission during open trades (1s
    cadence, matching the project's rule that 30s+ cadence checkpoints
    miss brief touches -- see be_simulation_path_checkpoint_inflation)
  - a pluggable stop-policy hook for Phase 5/6 (no-op by default)

Population-specific behavior (which flips are eligible for entry, any
confirmation predicate) is supplied ENTIRELY by subclasses via
`_check_pending_confirmation()` and `_on_regime_flip()`. This class
embeds no opinion on that question -- it does not know what "F2" or
"all flips" means.

Causality invariants (mirrors collectors/collector_v2/strategy.py,
already lookahead-audited):
  - decision_ts = bar.ts_init, never ts_event
  - all MFE/MAE/checkpoint state updates use only bars with
    ts_init <= current decision_ts
  - registry.audit_provenance() (via CompletedBarRegistry) enforces
    close_ts <= decision_ts for every stored timeframe
  - entries are pending-scheduled and submitted ~1s before the target
    fill time so NT's bar_execution engine fills at the target bar's
    OPEN -- never at the decision bar's own close
"""

from __future__ import annotations
from pathlib import Path
import sys
import json

import pandas as pd
import pytz

_repo_root = Path(__file__).parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Quantity
from nautilus_trader.trading.strategy import Strategy

from collectors.collector_v2.registry import (  # noqa: E402
    CompletedBarRegistry, SUPPORTED_TIMEFRAMES,
)
from collectors.collector_v2.aggregator import (  # noqa: E402
    TimeframeAggregator,
)
from collectors.collector_v2.regime_engine import (  # noqa: E402
    RegimeStateEngine,
)

from studies._shared_exit_mgmt.mfe_mae import (  # noqa: E402
    update_running_extremes, bar_pnl_mfe_mae, giveback_atr, to_atr,
)

CT = pytz.timezone("America/Chicago")


class ExitManagementBaseConfig(StrategyConfig, frozen=True):
    instrument_id: str
    bar_type_1m: str
    bar_type_1s: str
    rth_only: bool = True
    rth_start_min: int = 510   # 08:30 CT
    rth_end_min: int = 900     # 15:00 CT
    position_size: int = 1
    output_dir: str = ""
    # Entry-to-fill delay in nanoseconds, applied on top of decision_ts
    # (the instant the population's entry condition is satisfied).
    # BOTH all_flips_exit_management and f2_confirmed_exit_management
    # use 0 (immediate next-1s-open fill) -- the 30s delayed-activation
    # convention used in prior studies (rank_filter_oos_validation) is
    # explicitly NOT used here per the study spec. Kept as a config
    # field (not hardcoded) only so the causal "submit ~1s before
    # target" mechanism is identical in shape to the already-audited
    # collector_v2 implementation; do not set it to a nonzero value in
    # either of these two studies.
    entry_delay_ns: int = 0
    # Cost model, project-standard defaults (NQ).
    multiplier: float = 20.0
    tick_dollar: float = 5.0
    commission_per_rt: float = 5.0


class ExitManagementBaseStrategy(Strategy):
    """Abstract-ish base. Subclasses MUST implement:
      - _check_pending_confirmation(bar_data, decision_ts, bar_ts_event)
      - _on_regime_flip(new_regime, bar_data, decision_ts, bar_ts_event, in_rth)
    and may override:
      - _maybe_stop_policy_exit(bar, decision_ts)  (Phase 5/6 hook)
    """

    def __init__(self, config: ExitManagementBaseConfig):
        super().__init__(config)
        self._cfg = config
        self._registry = CompletedBarRegistry()
        self._engines = {
            tf: RegimeStateEngine(tf, self._registry)
            for tf in SUPPORTED_TIMEFRAMES
        }
        self._aggregator = TimeframeAggregator(
            on_bucket_closed=self._on_bucket_closed,
            timeframes=SUPPORTED_TIMEFRAMES,
        )

        # Regime-flip bookkeeping
        self._prev_1m_regime: int = 0
        self._last_seen_1m_close_ts: int = 0
        self._latest_1m_bar_data: dict | None = None
        self._current_regime_start_ts: int | None = None

        # Pending flip awaiting subclass-defined confirmation (slot
        # only -- base class never sets or reads its contents).
        self._pending_flip: dict | None = None
        # Pending entry awaiting fill: {fill_ts_target, direction,
        # decision_ts, atr_at_signal, regime_start_ts}
        self._pending_entry: dict | None = None
        # Open trade state
        self._trade: dict | None = None

        self._trade_id_counter: int = 0
        self._trades: list[dict] = []
        self._checkpoints: list[dict] = []
        self._pending_cancellations: list[dict] = []

        self._diag = {
            "1s_bars": 0, "1m_bars": 0,
            "rth_flips": 0,
            "entries_scheduled": 0,
            "entries_filled": 0,
            "entries_rejected": 0,
            "pending_entry_canceled": 0,
            "regime_exits": 0,
            "exits_rejected": 0,
            "checkpoints_emitted": 0,
        }

    # ---- Subscriptions ----
    def on_start(self):
        from nautilus_trader.model.data import BarType
        self.subscribe_bars(BarType.from_str(self._cfg.bar_type_1m))
        self.subscribe_bars(BarType.from_str(self._cfg.bar_type_1s))

    # ---- Bar dispatch ----
    def on_bar(self, bar):
        bt = str(bar.bar_type)
        if bt == self._cfg.bar_type_1s:
            self._on_1s_bar(bar)
        elif bt == self._cfg.bar_type_1m:
            self._on_1m_bar(bar)

    def _on_1s_bar(self, bar):
        self._diag["1s_bars"] += 1
        decision_ts = int(bar.ts_init)

        try:
            self._aggregator.on_1s_bar(
                int(bar.ts_event),
                float(bar.open), float(bar.high),
                float(bar.low), float(bar.close),
                float(bar.volume) if hasattr(bar, "volume") else 0.0,
            )
        except Exception as e:
            self._halt(f"aggregator error: {e}")
            raise

        s_1m = self._registry.get("1m")
        if (s_1m is not None
                and s_1m.close_ts != self._last_seen_1m_close_ts):
            self._last_seen_1m_close_ts = s_1m.close_ts
            self._on_1m_bucket_closed(decision_ts)

        if self._trade is not None:
            self._update_open_trade(bar, decision_ts)
            # Retry an exit that was previously rejected. exit_reason
            # is set (and stays set) the instant _submit_exit is first
            # called; exit_order_id is cleared to None on rejection
            # (on_order_rejected) without clearing exit_reason. Without
            # this retry the trade would stay open indefinitely (only
            # the *next* opposing flip would try again), producing an
            # orphaned block of checkpoints with no terminal trade row.
            if (self._trade.get("exit_reason") is not None
                    and self._trade.get("exit_order_id") is None):
                self._submit_exit(reason=self._trade["exit_reason"])

        # Submit pending entry ~1s before its target fill time, so
        # NT's bar_execution engine fills at the target bar's open.
        if (self._pending_entry is not None
                and self._trade is None
                and decision_ts >= (
                    self._pending_entry["fill_ts_target"]
                    - 1_000_000_000)):
            self._submit_entry()

    def _on_1m_bar(self, bar):
        self._diag["1m_bars"] += 1
        new_ts_init = int(bar.ts_init)
        if (self._latest_1m_bar_data is not None
                and new_ts_init <= self._latest_1m_bar_data["ts_init"]):
            raise ValueError(
                f"Out-of-order/non-monotonic 1m bar: prev ts_init="
                f"{self._latest_1m_bar_data['ts_init']}, "
                f"new ts_init={new_ts_init}")
        self._latest_1m_bar_data = {
            "ts_event": int(bar.ts_event),
            "ts_init": int(bar.ts_init),
            "open": float(bar.open),
            "high": float(bar.high),
            "low": float(bar.low),
            "close": float(bar.close),
        }

    def _on_1m_bucket_closed(self, decision_ts: int):
        s_1m = self._registry.get("1m")
        if s_1m is None:
            return
        bar_data = self._latest_1m_bar_data
        if bar_data is None or bar_data["ts_init"] != s_1m.close_ts:
            return  # warmup misalignment -- skip safely
        bar_ts_event = bar_data["ts_event"]

        # Subclass-defined confirmation check (population-specific;
        # e.g. F2's bar+1 HH/LL + momentum). No-op for populations
        # that trade every flip immediately.
        self._check_pending_confirmation(bar_data, decision_ts,
                                             bar_ts_event)

        new_regime = s_1m.regime
        flipped = (new_regime != 0 and self._prev_1m_regime != 0
                     and new_regime != self._prev_1m_regime)

        if flipped:
            # RTH classification MUST use the flip bar's CLOSE time
            # (ts_init), never its OPEN time (ts_event) -- CLAUDE.md
            # A1/F1 rule. Fixed 2026-07-11 pre-execution audit: this
            # bar carries an open-time ts_event that can precede the
            # RTH boundary while the bar's actual close (the instant
            # the flip is known) falls inside it, or vice versa.
            in_rth = self._is_rth(bar_data["ts_init"])
            if self._trade is not None:
                if new_regime != self._trade["direction"]:
                    self._submit_exit(reason="opposite_flip")
                    self._diag["regime_exits"] += 1
            if self._pending_entry is not None:
                if new_regime != self._pending_entry["direction"]:
                    self._pending_cancellations.append({
                        "decision_ts": self._pending_entry.get("decision_ts"),
                        "fill_ts_target": self._pending_entry.get("fill_ts_target"),
                        "direction": self._pending_entry.get("direction"),
                        "opposite_flip_ts_event": int(bar_ts_event),
                    })
                    self._diag["pending_entry_canceled"] += 1
                    self._pending_entry = None
            self._current_regime_start_ts = int(s_1m.close_ts)
            self._on_regime_flip(new_regime, bar_data, decision_ts,
                                    bar_ts_event, in_rth)

        if new_regime != 0:
            self._prev_1m_regime = new_regime

    def _on_bucket_closed(self, tf, completed):
        try:
            self._engines[tf].on_bar_closed(completed)
        except Exception as e:
            self._halt(f"engine.on_bar_closed({tf}) raised: {e}")
            raise

    # ---- Subclass hooks (must override) ----
    def _check_pending_confirmation(self, bar_data, decision_ts,
                                        bar_ts_event):
        """Default: no confirmation gating. Override for populations
        that require a delayed confirmation check (e.g. F2's bar+1
        HH/LL + momentum) using the `_pending_flip` slot."""
        return

    def _on_regime_flip(self, new_regime, bar_data, decision_ts,
                            bar_ts_event, in_rth):
        raise NotImplementedError(
            "Subclasses must define entry eligibility on regime flip.")

    # ---- Entry scheduling (population-agnostic mechanics) ----
    def _schedule_entry(self, direction: int, decision_ts: int,
                            atr_at_signal: float, regime_start_ts: int):
        # Reject entries before ATR warmup completes (Wilder ATR(14)
        # is None until 14 completed 1m bars have contributed a true
        # range -- RegimeStateEngine.on_bar_closed). Without this gate,
        # _update_open_trade's safe_atr=1.0 fallback would silently
        # compute every *_atr_from_entry checkpoint field in raw price
        # points instead of ATR units for these trades, with no
        # column distinguishing them from correctly-normalized rows.
        if atr_at_signal is None or atr_at_signal != atr_at_signal:
            self._diag["entries_rejected_atr_not_warmed"] = (
                self._diag.get("entries_rejected_atr_not_warmed", 0) + 1)
            return
        fill_ts_target = decision_ts + int(self._cfg.entry_delay_ns)
        self._pending_entry = {
            "fill_ts_target": int(fill_ts_target),
            "direction": int(direction),
            "decision_ts": int(decision_ts),
            "atr_at_signal": float(atr_at_signal)
                if atr_at_signal == atr_at_signal else float("nan"),
            "regime_start_ts": int(regime_start_ts),
        }
        self._diag["entries_scheduled"] += 1

    def _submit_entry(self):
        d = self._pending_entry["direction"]
        side = OrderSide.BUY if d == 1 else OrderSide.SELL
        qty = Quantity.from_int(self._cfg.position_size)
        order = self.order_factory.market(
            instrument_id=InstrumentId.from_str(self._cfg.instrument_id),
            order_side=side, quantity=qty,
            time_in_force=TimeInForce.FOK)
        self._trade_id_counter += 1
        self._trade = {
            "trade_id": self._trade_id_counter,
            "direction": int(d),
            "decision_ts": int(self._pending_entry["decision_ts"]),
            "regime_start_ts": int(self._pending_entry["regime_start_ts"]),
            "entry_order_id": order.client_order_id.value,
            "fill_price": None,
            "entry_ts": None,
            "exit_order_id": None,
            "exit_price": None,
            "exit_ts": None,
            "exit_reason": None,
            "opposite_flip_ts": None,
            "atr_at_signal": float(self._pending_entry["atr_at_signal"]),
            "running_mfe": -1e18,
            "running_mae": -1e18,
        }
        self._pending_entry = None
        self.submit_order(order)

    def _submit_exit(self, reason: str):
        if self._trade is None:
            return
        if self._trade.get("exit_order_id") is not None:
            return
        d = self._trade["direction"]
        side = OrderSide.SELL if d == 1 else OrderSide.BUY
        qty = Quantity.from_int(self._cfg.position_size)
        order = self.order_factory.market(
            instrument_id=InstrumentId.from_str(self._cfg.instrument_id),
            order_side=side, quantity=qty,
            time_in_force=TimeInForce.FOK, reduce_only=True)
        self._trade["exit_order_id"] = order.client_order_id.value
        self._trade["exit_reason"] = reason
        # Set only on the FIRST submission (guarded), using the flip
        # bar's CLOSE time (ts_init), never its open (ts_event) --
        # CLAUDE.md A1/F1 rule, matching regime_start_ts's convention.
        # Without this guard, the exit-rejection retry path (which also
        # calls _submit_exit with the same reason) would overwrite this
        # with whatever _latest_1m_bar_data has become BY THE RETRY,
        # which can be a later bar than the actual triggering flip.
        if (reason == "opposite_flip"
                and self._trade.get("opposite_flip_ts") is None):
            self._trade["opposite_flip_ts"] = (
                self._latest_1m_bar_data["ts_init"]
                if self._latest_1m_bar_data else None)
        self.submit_order(order)

    # ---- Order events ----
    def on_order_filled(self, event):
        if self._trade is None:
            return
        cid = event.client_order_id.value
        if cid == self._trade.get("entry_order_id"):
            self._trade["fill_price"] = float(event.last_px)
            self._trade["entry_ts"] = int(event.ts_event)
            self._trade["running_mfe"] = 0.0
            self._trade["running_mae"] = 0.0
            self._diag["entries_filled"] += 1
        elif cid == self._trade.get("exit_order_id"):
            self._trade["exit_price"] = float(event.last_px)
            self._trade["exit_ts"] = int(event.ts_event)
            if self._trade.get("exit_reason") is None:
                self._trade["exit_reason"] = "unknown"
            self._finalize_trade()

    def on_order_rejected(self, event):
        if self._trade is None:
            return
        cid = event.client_order_id.value
        if cid == self._trade.get("entry_order_id"):
            self._diag["entries_rejected"] += 1
            self._trade = None
        elif cid == self._trade.get("exit_order_id"):
            self._diag["exits_rejected"] += 1
            self._trade["exit_order_id"] = None

    # ---- Intra-trade tracking (fill-anchored, causal) ----
    def _update_open_trade(self, bar, decision_ts):
        t = self._trade
        if t.get("entry_ts") is None or t.get("fill_price") is None:
            return  # not yet filled
        d = t["direction"]
        ep = t["fill_price"]
        h, l, c = float(bar.high), float(bar.low), float(bar.close)

        new_mfe, new_mae = update_running_extremes(
            t["running_mfe"], t["running_mae"], d, ep, h, l, c)
        t["running_mfe"] = new_mfe
        t["running_mae"] = new_mae

        contrib = bar_pnl_mfe_mae(d, ep, h, l, c)
        cur_pnl = contrib["pnl_close"]
        atr = t.get("atr_at_signal", float("nan"))
        safe_atr = atr if atr and atr == atr and atr > 0 else 1.0

        self._checkpoints.append({
            "trade_id": t["trade_id"],
            "direction": int(d),
            "entry_ts": int(t["entry_ts"]),
            "entry_px": float(ep),
            "checkpoint_ts": int(decision_ts),
            "checkpoint_price": float(c),
            "checkpoint_high": h,
            "checkpoint_low": l,
            "regime_start_ts": int(t["regime_start_ts"]),
            "atr_at_entry": float(atr) if atr == atr else float("nan"),
            "age_seconds": float(
                (decision_ts - t["entry_ts"]) / 1e9),
            "current_pnl_atr_from_entry": float(to_atr(cur_pnl, atr)),
            "mfe_atr_from_entry": float(to_atr(new_mfe, atr)),
            "mae_atr_from_entry": float(to_atr(new_mae, atr)),
            # giveback_atr_from_entry and distance_from_mfe_atr are the
            # same formula under two names required by the study spec's
            # atlas schema (Phase 1 lists both field names). Kept as
            # two columns deliberately, not a bug -- see mfe_mae.giveback_atr.
            "giveback_atr_from_entry": float(
                giveback_atr(new_mfe, cur_pnl, atr)),
            "distance_from_mfe_atr": float(
                giveback_atr(new_mfe, cur_pnl, atr)),
        })
        self._diag["checkpoints_emitted"] += 1

        # Phase 5/6 pluggable stop-policy hook (no-op by default)
        self._maybe_stop_policy_exit(bar, decision_ts)

    def _maybe_stop_policy_exit(self, bar, decision_ts):
        """Override in Phase 5/6 policy subclasses to submit an early
        market exit (reason='stop_policy') based on a causal, already-
        frozen weakness-score lookup. No-op for baseline (E0/A0/F0)."""
        return

    def _finalize_trade(self):
        t = self._trade
        d = t["direction"]
        ep, ex = t["fill_price"], t["exit_price"]
        gross = (ex - ep) * d * self._cfg.multiplier
        cost = self._cfg.commission_per_rt + self._cfg.tick_dollar
        net = gross - cost
        t["gross_pnl"] = gross
        t["net_pnl"] = net
        t["hold_s"] = (t["exit_ts"] - t["entry_ts"]) / 1e9
        t["session"] = ("RTH" if self._is_rth_minute(t["entry_ts"])
                           else "ETH")
        self._trades.append(dict(t))
        self._trade = None

    # ---- Helpers ----
    def _is_rth(self, ts_ns: int) -> bool:
        if not self._cfg.rth_only:
            return True
        ct = pd.Timestamp(ts_ns, tz="UTC").tz_convert(CT)
        m = ct.hour * 60 + ct.minute
        return self._cfg.rth_start_min <= m < self._cfg.rth_end_min

    def _is_rth_minute(self, ts_ns: int) -> bool:
        ct = pd.Timestamp(ts_ns, tz="UTC").tz_convert(CT)
        m = ct.hour * 60 + ct.minute
        return self._cfg.rth_start_min <= m < self._cfg.rth_end_min

    def _halt(self, reason: str):
        msg = f"EXIT-MGMT HALT: {reason}"
        try:
            self.log.error(msg)
        except Exception:
            print(msg)
        if self._cfg.output_dir:
            try:
                Path(self._cfg.output_dir).mkdir(parents=True, exist_ok=True)
                with open(Path(self._cfg.output_dir) / "FAILURE.txt", "w") as f:
                    f.write(msg + "\n")
                    f.write(f"trades_so_far: {len(self._trades)}\n")
                    f.write(f"checkpoints_so_far: {len(self._checkpoints)}\n")
            except Exception:
                pass

    # ---- Lifecycle ----
    def on_stop(self):
        super().on_stop()
        if self._trade is not None:
            # Should be rare given the exit-rejection retry above; if
            # it still happens, surface it loudly rather than silently
            # dropping the trade from trades.parquet.
            self._diag["trade_open_at_stop"] = 1
            self._diag["trade_open_at_stop_trade_id"] = self._trade.get(
                "trade_id")
        try:
            self.log.info(f"Diag: {self._diag}")
        except Exception:
            pass
        if self._cfg.output_dir:
            outp = Path(self._cfg.output_dir)
            outp.mkdir(parents=True, exist_ok=True)
            if self._trades:
                pd.DataFrame(self._trades).to_parquet(
                    outp / "trades.parquet", index=False)
            if self._checkpoints:
                pd.DataFrame(self._checkpoints).to_parquet(
                    outp / "checkpoints.parquet", index=False)
            if self._pending_cancellations:
                pd.DataFrame(self._pending_cancellations).to_parquet(
                    outp / "pending_cancellations.parquet", index=False)
            with open(outp / "diag.json", "w") as f:
                json.dump(self._diag, f, indent=2)
