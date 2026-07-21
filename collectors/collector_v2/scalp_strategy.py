"""Pullback continuation scalp v1 — short-horizon high-frequency.

Setup:
  1. WAITING — watch every 30s bucket close
  2. Impulse trigger: a 30s bar with body / atr_30s >= IMPULSE_BODY
  3. IMPULSE_SEEN — within next 30s, look for shallow pullback
     (1s close retraces by [PB_MIN, PB_MAX] of atr_30s in the
     direction OPPOSITE the impulse). If pullback exceeds PB_MAX
     or invalidates the impulse start, abort.
  4. PULLBACK_CONFIRMED — within next 30s, look for re-acceleration
     (1s close back through `impulse_close - REACCEL * atr_30s`
     in trade direction). On re-accel, submit market order.
  5. IN_TRADE — bracket: PT/SL = ATR(30s)-multiples from fill.
     Max hold = MAX_HOLD_S seconds. Intra-bar resolution: if the
     same 1s bar's high/low touches both PT and SL, conservative
     attribution = SL (worst case for parity with NT bar_execution).

Causality:
  - All state transitions driven by `decision_ts = bar.ts_init`.
  - Registry/aggregator from Collector V2; no MTF lookups outside
    registry. Provenance audited on every snapshot build.
  - Impulse / pullback / re-accel measured against ATR snapped at
    impulse-bar close — frozen reference, no drift.

Reuses Collector V2 infra:
  - CompletedBarRegistry, TimeframeAggregator, RegimeStateEngine,
    FeatureSnapshotBuilder (snapshots emitted at impulse / fill /
    exit events for downstream analysis)

Cost model: identical to V_A runs (commission $5 + tick $5 RT).
"""

from __future__ import annotations
from collections import deque
from pathlib import Path
import sys
import pandas as pd

_repo_root = Path(__file__).parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Quantity
from nautilus_trader.trading.strategy import Strategy

from utils.causality import CausalityViolation  # noqa: E402

from collectors.collector_v2.registry import (  # noqa: E402
    CompletedBarRegistry, SUPPORTED_TIMEFRAMES,
)
from collectors.collector_v2.aggregator import (  # noqa: E402
    TimeframeAggregator,
)
from collectors.collector_v2.regime_engine import (  # noqa: E402
    RegimeStateEngine,
)
from collectors.collector_v2.snapshot_builder import (  # noqa: E402
    FeatureSnapshotBuilder,
)

import pytz
CT = pytz.timezone("America/Chicago")


class ScalpV1Config(StrategyConfig, frozen=True):
    instrument_id: str
    bar_type_1m: str
    bar_type_1s: str
    rth_only: bool = True
    rth_start_min: int = 510
    rth_end_min: int = 900
    position_size: int = 1
    output_dir: str = ""
    multiplier: float = 20.0
    tick_dollar: float = 5.0
    commission_per_rt: float = 5.0
    # Setup parameters
    impulse_body_atr: float = 0.40    # min |body|/atr_30s to qualify
    pullback_min_atr: float = 0.15    # min retracement
    pullback_max_atr: float = 0.55    # max retracement
    reaccel_atr: float = 0.10         # depth back through impulse close
    pullback_window_s: int = 30       # max time to find pullback
    reaccel_window_s: int = 30        # max time to find re-accel
    cooldown_s: int = 0               # post-exit dead time
    # Bracket / exit
    pt_atr: float = 0.35
    sl_atr: float = 0.35
    max_hold_s: int = 60


# State machine constants
S_WAITING = 0
S_IMPULSE_SEEN = 1
S_PULLBACK_CONFIRMED = 2
S_IN_TRADE = 3


class ScalpV1Strategy(Strategy):

    def __init__(self, config: ScalpV1Config):
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
        self._snapshot_builder = FeatureSnapshotBuilder(
            self._registry)

        self._state = S_WAITING
        # Impulse details when in IMPULSE_SEEN/PULLBACK_CONFIRMED
        self._impulse: dict | None = None
        self._pullback_extreme: float | None = None
        self._pending_entry: dict | None = None
        self._trade: dict | None = None
        self._cooldown_until_ts: int = 0
        self._last_seen_30s_close_ts: int = 0
        self._last_seen_1s_ts: int = 0

        self._snapshots: list[dict] = []
        self._trades: list[dict] = []

        self._diag = {
            "1s_bars": 0,
            "30s_buckets": 0,
            "impulses_qualified": 0,
            "rth_impulses_qualified": 0,
            "pullback_confirmed": 0,
            "reaccel_entries": 0,
            "pullback_aborted_too_deep": 0,
            "pullback_aborted_timeout": 0,
            "reaccel_aborted_timeout": 0,
            "trades_completed": 0,
            "exits_pt": 0,
            "exits_sl": 0,
            "exits_max_hold": 0,
            "snapshots_emitted": 0,
        }

    def on_start(self):
        from nautilus_trader.model.data import BarType
        self.subscribe_bars(BarType.from_str(self._cfg.bar_type_1m))
        self.subscribe_bars(BarType.from_str(self._cfg.bar_type_1s))

    # ----- Bar dispatch -----
    def on_bar(self, bar):
        bt = str(bar.bar_type)
        if bt == self._cfg.bar_type_1s:
            self._on_1s_bar(bar)
        # 1m bars only feed the aggregator indirectly via 1s bucket
        # close; we don't act on them directly here.

    def _on_1s_bar(self, bar):
        self._diag["1s_bars"] += 1
        decision_ts = int(bar.ts_init)
        self._last_seen_1s_ts = decision_ts
        try:
            self._aggregator.on_1s_bar(
                int(bar.ts_event),
                float(bar.open), float(bar.high),
                float(bar.low), float(bar.close),
                float(bar.volume) if hasattr(bar, "volume") else 0.0,
            )
        except CausalityViolation as e:
            self._halt(f"CausalityViolation: {e}")
            raise

        # Did the 30s registry advance? If so, this 1s bar is the
        # trigger. Run impulse-detection logic with this 1s bar's
        # ts_init as decision_ts.
        s_30 = self._registry.get("30s")
        if (s_30 is not None
                and s_30.close_ts != self._last_seen_30s_close_ts):
            self._last_seen_30s_close_ts = s_30.close_ts
            self._on_30s_close(decision_ts)

        # Run open-trade and pending-state checks against this 1s bar
        if self._state == S_IN_TRADE:
            self._update_open_trade(bar, decision_ts)
        elif self._state == S_IMPULSE_SEEN:
            self._maybe_confirm_pullback(bar, decision_ts)
        elif self._state == S_PULLBACK_CONFIRMED:
            self._maybe_reaccel(bar, decision_ts)

    def _on_30s_close(self, decision_ts: int):
        s_30 = self._registry.get("30s")
        if s_30 is None or s_30.atr <= 0:
            return
        # Honor cooldown
        if decision_ts < self._cooldown_until_ts:
            return
        # Only WAITING state can accept new impulses
        if self._state != S_WAITING:
            return

        body = s_30.close - s_30.open
        body_atr = abs(body) / s_30.atr
        if body_atr < self._cfg.impulse_body_atr:
            return
        direction = 1 if body > 0 else -1
        self._diag["impulses_qualified"] += 1
        if not self._is_rth(s_30.open_ts):
            return
        self._diag["rth_impulses_qualified"] += 1
        # Stash impulse reference: close, h/l, atr, ts
        self._impulse = {
            "direction": direction,
            "impulse_close": float(s_30.close),
            "impulse_high": float(s_30.high),
            "impulse_low": float(s_30.low),
            "impulse_open": float(s_30.open),
            "atr": float(s_30.atr),
            "impulse_close_ts": int(s_30.close_ts),
            "decision_ts": decision_ts,
            "expires_ts": decision_ts + (
                self._cfg.pullback_window_s * 1_000_000_000),
        }
        self._pullback_extreme = float(s_30.close)
        self._state = S_IMPULSE_SEEN

    def _maybe_confirm_pullback(self, bar, decision_ts):
        imp = self._impulse
        if imp is None:
            self._state = S_WAITING; return
        # Timeout
        if decision_ts > imp["expires_ts"]:
            self._diag["pullback_aborted_timeout"] += 1
            self._reset_to_waiting()
            return
        d = imp["direction"]
        atr = imp["atr"]
        bar_l = float(bar.low); bar_h = float(bar.high)
        # Track the pullback extreme (worst-direction price since impulse)
        if d == 1:
            cur_extreme = min(self._pullback_extreme, bar_l)
        else:
            cur_extreme = max(self._pullback_extreme, bar_h)
        self._pullback_extreme = cur_extreme
        # Pullback magnitude in ATR (favorable to entry)
        if d == 1:
            pb = (imp["impulse_close"] - cur_extreme) / atr
        else:
            pb = (cur_extreme - imp["impulse_close"]) / atr
        if pb > self._cfg.pullback_max_atr:
            self._diag["pullback_aborted_too_deep"] += 1
            self._reset_to_waiting()
            return
        if pb >= self._cfg.pullback_min_atr:
            # Confirmed
            self._diag["pullback_confirmed"] += 1
            self._state = S_PULLBACK_CONFIRMED
            self._impulse["pb_extreme"] = float(cur_extreme)
            self._impulse["pb_extreme_ts"] = decision_ts
            self._impulse["reaccel_expires_ts"] = (
                decision_ts
                + self._cfg.reaccel_window_s * 1_000_000_000)

    def _maybe_reaccel(self, bar, decision_ts):
        imp = self._impulse
        if imp is None:
            self._state = S_WAITING; return
        if decision_ts > imp["reaccel_expires_ts"]:
            self._diag["reaccel_aborted_timeout"] += 1
            self._reset_to_waiting()
            return
        d = imp["direction"]
        atr = imp["atr"]
        bar_h = float(bar.high); bar_l = float(bar.low)
        bar_c = float(bar.close)
        # Re-accel: 1s bar close back through (impulse_close -
        # reaccel * atr) for long; symmetric for short.
        thr_long = imp["impulse_close"] - self._cfg.reaccel_atr * atr
        thr_short = imp["impulse_close"] + self._cfg.reaccel_atr * atr
        if d == 1 and bar_c >= thr_long:
            self._submit_entry(decision_ts, bar_c)
        elif d == -1 and bar_c <= thr_short:
            self._submit_entry(decision_ts, bar_c)

    def _submit_entry(self, decision_ts, ref_price):
        imp = self._impulse
        d = imp["direction"]
        side = OrderSide.BUY if d == 1 else OrderSide.SELL
        qty = Quantity.from_int(self._cfg.position_size)
        order = self.order_factory.market(
            instrument_id=InstrumentId.from_str(
                self._cfg.instrument_id),
            order_side=side, quantity=qty,
            time_in_force=TimeInForce.FOK)
        self._trade = {
            "direction": int(d),
            "decision_ts": int(decision_ts),
            "impulse_close_ts": int(imp["impulse_close_ts"]),
            "impulse_close_price": float(imp["impulse_close"]),
            "atr_at_signal": float(imp["atr"]),
            "pb_extreme": float(imp["pb_extreme"]),
            "entry_order_id": order.client_order_id.value,
            "fill_price": None,
            "entry_ts": None,
            "exit_order_id": None,
            "exit_price": None,
            "exit_ts": None,
            "exit_reason": None,
            "ref_price_at_submit": float(ref_price),
            "max_hold_until_ts": 0,
            "session": "RTH" if self._is_rth(decision_ts) else "ETH",
        }
        self._state = S_IN_TRADE
        self._diag["reaccel_entries"] += 1
        self.submit_order(order)

    def _update_open_trade(self, bar, decision_ts):
        t = self._trade
        if t is None or t.get("entry_ts") is None:
            # Pre-fill: just wait for fill event
            return
        d = t["direction"]
        ep = t["fill_price"]
        atr = t["atr_at_signal"]
        bar_h = float(bar.high); bar_l = float(bar.low)
        # Targets
        pt_dist = self._cfg.pt_atr * atr
        sl_dist = self._cfg.sl_atr * atr
        if d == 1:
            pt_px = ep + pt_dist
            sl_px = ep - sl_dist
            hit_pt = bar_h >= pt_px
            hit_sl = bar_l <= sl_px
        else:
            pt_px = ep - pt_dist
            sl_px = ep + sl_dist
            hit_pt = bar_l <= pt_px
            hit_sl = bar_h >= sl_px
        # Conservative attribution if both touch in one bar
        if hit_pt and hit_sl:
            self._exit_trade(decision_ts, sl_px, "sl_intra_both")
            return
        if hit_pt:
            self._exit_trade(decision_ts, pt_px, "pt")
            return
        if hit_sl:
            self._exit_trade(decision_ts, sl_px, "sl")
            return
        if decision_ts >= t["max_hold_until_ts"]:
            # Time stop — exit at this bar's close
            self._exit_trade(decision_ts, float(bar.close),
                                "max_hold")

    def _exit_trade(self, decision_ts, exit_px, reason):
        t = self._trade
        if t is None:
            return
        if t.get("exit_order_id") is not None:
            return
        d = t["direction"]
        ep = t["fill_price"]
        gross = (exit_px - ep) * d * self._cfg.multiplier
        cost = (self._cfg.commission_per_rt
                + self._cfg.tick_dollar)
        net = gross - cost
        t["exit_price"] = float(exit_px)
        t["exit_ts"] = int(decision_ts)
        t["exit_reason"] = reason
        t["gross_pnl"] = float(gross)
        t["net_pnl"] = float(net)
        t["hold_s"] = ((t["exit_ts"] - t["entry_ts"]) / 1e9
                          if t["entry_ts"] else 0.0)
        if reason == "pt":
            self._diag["exits_pt"] += 1
        elif reason in ("sl", "sl_intra_both"):
            self._diag["exits_sl"] += 1
        elif reason == "max_hold":
            self._diag["exits_max_hold"] += 1
        self._diag["trades_completed"] += 1
        self._trades.append(dict(t))
        self._cooldown_until_ts = (
            decision_ts + self._cfg.cooldown_s * 1_000_000_000)
        self._reset_to_waiting()

    def _reset_to_waiting(self):
        self._impulse = None
        self._pullback_extreme = None
        self._trade = None
        self._state = S_WAITING

    def on_order_filled(self, event):
        if self._trade is None:
            return
        cid = event.client_order_id.value
        if cid == self._trade.get("entry_order_id"):
            self._trade["fill_price"] = float(event.last_px)
            self._trade["entry_ts"] = int(event.ts_event)
            self._trade["max_hold_until_ts"] = (
                int(event.ts_event)
                + self._cfg.max_hold_s * 1_000_000_000)

    def _on_bucket_closed(self, tf, completed):
        try:
            self._engines[tf].on_bar_closed(completed)
        except Exception as e:
            self._halt(f"engine.on_bar_closed({tf}) raised: {e}")
            raise
        if tf == "30s":
            self._diag["30s_buckets"] += 1

    def _is_rth(self, ts_ns: int) -> bool:
        if not self._cfg.rth_only:
            return True
        ct = pd.Timestamp(ts_ns, tz="UTC").tz_convert(CT)
        m = ct.hour * 60 + ct.minute
        return self._cfg.rth_start_min <= m < self._cfg.rth_end_min

    def _halt(self, reason: str):
        msg = f"SCALP V1 HALT: {reason}"
        try: self.log.error(msg)
        except Exception: print(msg)
        if self._cfg.output_dir:
            try:
                Path(self._cfg.output_dir).mkdir(parents=True,
                                                    exist_ok=True)
                with open(Path(self._cfg.output_dir)
                              / "FAILURE.txt", "w") as f:
                    f.write(msg + "\n")
            except Exception: pass

    def on_stop(self):
        super().on_stop()
        try: self.log.info(f"Diag: {self._diag}")
        except Exception: pass
        if self._cfg.output_dir:
            outp = Path(self._cfg.output_dir)
            outp.mkdir(parents=True, exist_ok=True)
            if self._trades:
                pd.DataFrame(self._trades).to_parquet(
                    outp / "trades.parquet", index=False)
            import json
            with open(outp / "diag.json", "w") as f:
                json.dump(self._diag, f, indent=2)
            with open(outp / "config.json", "w") as f:
                json.dump({
                    "impulse_body_atr": self._cfg.impulse_body_atr,
                    "pullback_min_atr": self._cfg.pullback_min_atr,
                    "pullback_max_atr": self._cfg.pullback_max_atr,
                    "reaccel_atr": self._cfg.reaccel_atr,
                    "pullback_window_s": self._cfg.pullback_window_s,
                    "reaccel_window_s": self._cfg.reaccel_window_s,
                    "cooldown_s": self._cfg.cooldown_s,
                    "pt_atr": self._cfg.pt_atr,
                    "sl_atr": self._cfg.sl_atr,
                    "max_hold_s": self._cfg.max_hold_s,
                }, f, indent=2)
