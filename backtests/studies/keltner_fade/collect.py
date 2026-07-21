"""Collector strategy for the Keltner Extension Fade Study."""
from __future__ import annotations
from collections import deque
from dataclasses import asdict
from pathlib import Path
import sys
import pandas as pd
import pytz

# Repo root on path
_repo_root = Path(__file__).parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Quantity
from nautilus_trader.trading.strategy import Strategy

from utils.causality import CausalityViolation
from collectors.collector_v2.registry import CompletedBarRegistry, CompletedBarState
from collectors.collector_v2.aggregator import TimeframeAggregator
from collectors.collector_v2.regime_engine import RegimeStateEngine
from studies.keltner_fade.keltner import KeltnerChannel

CT = pytz.timezone("America/Chicago")


class KeltnerFadeConfig(StrategyConfig, frozen=True):
    instrument_id: str
    bar_type_30s: str
    bar_type_3m: str
    bar_type_1s: str
    variant: str = "A"                   # "A" | "B"
    stop_type: str = "band_atr"           # "band_atr" | "rr"
    stop_atr_mult: float = 0.5            # Stop offset beyond band in ATR units (Variant A)
    stop_rr_ratio: float = 0.5            # Stop offset ratio of entry-to-target distance (Variant A)
    target_offset_atr: float = 0.5        # Offset from basis towards entry
    v_b_filter1_threshold: float = 0.5    # Outer half threshold (Variant B)
    v_b_filter2_n: int = 6                # Lookback 30s bars for touch check (Variant B)
    v_b_filter2_x_atr: float = 0.25       # Band extension offset (Variant B)
    disaster_stop_atr_mult: float = 2.5   # Disaster backstop ATR mult from entry (Variant B)
    output_dir: str = ""
    position_size: int = 1
    multiplier: float = 20.0              # NQ point multiplier
    tick_dollar: float = 5.0              # NQ tick value
    commission_per_rt: float = 5.0        # Round-trip commission
    rth_only: bool = False                # Evaluate all regimes/hours
    active_hours: tuple[int, ...] | None = None # Hours to restrict entries (Chicago Time)
    start_date_utc: str = ""              # Start date for trading (warmup ignored)
    disable_target: bool = False          # Disable profit target exits


class KeltnerFadeStrategy(Strategy):
    """Event-driven collector strategy evaluating Keltner Extension Fades."""

    def __init__(self, config: KeltnerFadeConfig):
        super().__init__(config)
        self._cfg = config
        self._instrument_id = InstrumentId.from_str(config.instrument_id)
        self._registry = CompletedBarRegistry()
        self._moose_engine = RegimeStateEngine("30s", self._registry)
        self._keltner = KeltnerChannel(ema_period=20, atr_period=20, multiplier=1.5)
        self._start_trading_ns = pd.Timestamp(config.start_date_utc, tz="UTC").value if config.start_date_utc else 0

        self._aggregator = TimeframeAggregator(
            on_bucket_closed=self._on_bucket_closed,
            timeframes=("3m", "30s"),
        )

        # State tracking
        self._last_seen_30s_close_ts = 0
        self._prev_30s_regime = 0
        self._lookback_30s = deque(maxlen=20)  # Buffer of recent 30s bar structures

        self._last_keltner_basis = None
        self._last_keltner_upper = None
        self._last_keltner_lower = None
        self._last_keltner_atr = None
        
        self._keltner_basis_history = deque(maxlen=6)
        self._last_keltner_slope = 0.0

        self._trade = None
        self._trades = []

        # Diagnostics
        self._diag = {
            "1s_bars": 0,
            "30s_bars": 0,
            "3m_bars": 0,
            "entries_submitted": 0,
            "entries_filled": 0,
            "exits_submitted": 0,
            "exits_filled": 0,
            "target_hits": 0,
            "stop_hits": 0,
            "disaster_stop_hits": 0,
            "regime_flip_exits": 0,
            "lookback_touch_hits": 0,
        }

    def on_start(self):
        from nautilus_trader.model.data import BarType
        self.subscribe_bars(BarType.from_str(self._cfg.bar_type_1s))

    def on_bar(self, bar):
        bt = str(bar.bar_type)
        if bt == self._cfg.bar_type_1s:
            self._on_1s_bar(bar)

    def _on_1s_bar(self, bar):
        self._diag["1s_bars"] += 1
        decision_ts = int(bar.ts_init)

        # 1. Feed aggregator
        self._aggregator.on_1s_bar(
            int(bar.ts_event),
            float(bar.open), float(bar.high),
            float(bar.low), float(bar.close),
            float(bar.volume) if hasattr(bar, "volume") else 0.0,
        )

        # 2. Check if a 30s bar has closed
        s_30s = self._registry.get("30s")
        if s_30s is not None and s_30s.close_ts != self._last_seen_30s_close_ts:
            self._last_seen_30s_close_ts = s_30s.close_ts
            self._on_30s_bar_closed(s_30s, decision_ts)

        # 3. Monitor active open position on each 1s bar
        if self._trade is not None and self._trade.get("entry_ts") is not None:
            self._monitor_open_trade(bar, decision_ts)

    def _on_bucket_closed(self, tf: str, completed):
        if tf == "30s":
            # Update Moose Regime Engine
            self._moose_engine.on_bar_closed(completed)
            self._diag["30s_bars"] += 1

            # Buffer historical bar structure with active Keltner bands
            self._lookback_30s.append({
                "high": completed.high,
                "low": completed.low,
                "close": completed.close,
                "upper": self._last_keltner_upper,
                "lower": self._last_keltner_lower,
                "atr": self._last_keltner_atr,
            })

        elif tf == "3m":
            # Update Keltner Channel
            self._keltner.update(completed.high, completed.low, completed.close)
            self._diag["3m_bars"] += 1

            if self._keltner.is_warmed_up:
                self._last_keltner_basis = self._keltner.basis
                self._last_keltner_upper = self._keltner.upper
                self._last_keltner_lower = self._keltner.lower
                self._last_keltner_atr = self._keltner.atr
                
                self._keltner_basis_history.append(self._keltner.basis)
                if len(self._keltner_basis_history) >= 2:
                    y_series = list(self._keltner_basis_history)
                    L = len(y_series)
                    x_mean = (L - 1) / 2.0
                    y_mean = sum(y_series) / L
                    num = sum((i - x_mean) * (y - y_mean) for i, y in enumerate(y_series))
                    den = sum((i - x_mean) ** 2 for i in range(L))
                    raw_slope = num / den if den > 0 else 0.0
                    atr = self._last_keltner_atr
                    self._last_keltner_slope = raw_slope / atr if atr and atr > 0 else 0.0

    def _on_30s_bar_closed(self, s_30s, decision_ts: int):
        new_regime = s_30s.regime
        prev_regime = self._prev_30s_regime
        self._prev_30s_regime = new_regime

        # 1. Exit on opposing regime flip for Variant B
        if self._cfg.variant == "B" and self._trade is not None:
            if new_regime != 0 and prev_regime != 0 and new_regime != prev_regime:
                d = self._trade["direction"]
                if new_regime == -d:
                    self._submit_exit(reason="regime_flip")
                    self._diag["regime_flip_exits"] += 1
                    return

        # 2. Check entry conditions if flat
        if self._trade is None and self.portfolio.is_flat(self._instrument_id):
            self._check_entry_trigger(s_30s, prev_regime, decision_ts)

    def _check_filter2(self, direction: int) -> bool:
        N = self._cfg.v_b_filter2_n
        X_atr = self._cfg.v_b_filter2_x_atr
        # Slice last N 30s bars
        buffer_slice = list(self._lookback_30s)[-N:] if len(self._lookback_30s) >= N else list(self._lookback_30s)
        if not buffer_slice:
            return False

        for bar in buffer_slice:
            upper = bar["upper"]
            lower = bar["lower"]
            atr = bar["atr"]
            if upper is None or lower is None or atr is None:
                continue
            if direction == -1:  # short candidate: check upper touch
                if bar["high"] >= upper - X_atr * atr:
                    return True
            else:  # long candidate: check lower touch
                if bar["low"] <= lower + X_atr * atr:
                    return True
        return False

    def _check_entry_trigger(self, s_30s, prev_regime: int, decision_ts: int):
        # Only trade on/after start_date_utc
        if self._start_trading_ns > 0 and decision_ts < self._start_trading_ns:
            return

        # RTH filter
        if self._cfg.rth_only and not self._is_rth_minute(decision_ts):
            return

        # Active hours filter
        if self._cfg.active_hours is not None:
            ct = pd.Timestamp(decision_ts, unit="ns", tz="UTC").tz_convert(CT)
            if ct.hour not in self._cfg.active_hours:
                return

        if self._last_keltner_basis is None:
            return  # Keltner indicator not warmed up yet

        close = s_30s.close
        basis = self._last_keltner_basis
        upper = self._last_keltner_upper
        lower = self._last_keltner_lower
        atr = self._last_keltner_atr

        direction = 0  # 1 for Long, -1 for Short
        target_px = 0.0
        stop_px = None
        disaster_stop_px = None

        if self._cfg.variant == "A":
            # Straight fade trigger: Close beyond Keltner band
            if close > upper:
                direction = -1
            elif close < lower:
                direction = 1

            if direction != 0:
                # Calculate target (basis offset toward entry side)
                target_offset = self._cfg.target_offset_atr * atr
                if direction == 1:
                    target_px = basis - target_offset
                else:
                    target_px = basis + target_offset

                # Calculate stop price (anchored to close to prevent invalid/instant stop-out on gaps/extensions)
                if self._cfg.stop_type == "band_atr":
                    if direction == 1:
                        stop_px = close - self._cfg.stop_atr_mult * atr
                    else:
                        stop_px = close + self._cfg.stop_atr_mult * atr
                elif self._cfg.stop_type == "rr":
                    dist = abs(target_px - close)
                    if direction == 1:
                        stop_px = close - self._cfg.stop_rr_ratio * dist
                    else:
                        stop_px = close + self._cfg.stop_rr_ratio * dist

        elif self._cfg.variant == "B":
            # Regime flip trigger: 30s regime flip away from relevant band
            new_regime = s_30s.regime
            is_flip = (new_regime != 0 and prev_regime != 0 and new_regime != prev_regime)
            
            if is_flip:
                if new_regime == -1:  # Bear flip -> Short candidate
                    # Filter 1: Not too deep (outer 50% of basis-to-upper band)
                    f1_ok = close >= basis + self._cfg.v_b_filter1_threshold * (upper - basis)
                    # Filter 2: Recent touch check
                    f2_ok = self._check_filter2(direction=-1)
                    if f1_ok and f2_ok:
                        direction = -1
                        self._diag["lookback_touch_hits"] += 1
                elif new_regime == 1:  # Bull flip -> Long candidate
                    # Filter 1: Not too deep
                    f1_ok = close <= basis - self._cfg.v_b_filter1_threshold * (basis - lower)
                    # Filter 2: Recent touch check
                    f2_ok = self._check_filter2(direction=1)
                    if f1_ok and f2_ok:
                        direction = 1
                        self._diag["lookback_touch_hits"] += 1

            if direction != 0:
                target_offset = self._cfg.target_offset_atr * atr
                if direction == 1:
                    target_px = basis - target_offset
                    disaster_stop_px = close - self._cfg.disaster_stop_atr_mult * atr
                else:
                    target_px = basis + target_offset
                    disaster_stop_px = close + self._cfg.disaster_stop_atr_mult * atr

        if direction != 0:
            self._submit_entry(
                direction=direction,
                target_px=target_px,
                stop_px=stop_px,
                disaster_stop_px=disaster_stop_px,
                bars_in_regime=int(s_30s.bars_in_regime),
                regime_at_entry=int(s_30s.regime)
            )

    def _submit_entry(self, direction: int, target_px: float, stop_px: float | None, disaster_stop_px: float | None, bars_in_regime: int, regime_at_entry: int):
        side = OrderSide.BUY if direction == 1 else OrderSide.SELL
        qty = Quantity.from_int(self._cfg.position_size)
        order = self.order_factory.market(
            instrument_id=InstrumentId.from_str(self._cfg.instrument_id),
            order_side=side, quantity=qty,
            time_in_force=TimeInForce.FOK
        )
        self._trade = {
            "direction": direction,
            "entry_order_id": order.client_order_id.value,
            "fill_price": None,
            "entry_ts": None,
            "exit_order_id": None,
            "exit_price": None,
            "exit_ts": None,
            "atr_at_entry": self._last_keltner_atr,
            "basis_at_entry": self._last_keltner_basis,
            "target_px": target_px,
            "stop_px": stop_px,
            "disaster_stop_px": disaster_stop_px,
            "bars_in_regime_at_entry": bars_in_regime,
            "regime_at_entry": regime_at_entry,
            "running_mfe": -1e9,
            "running_mae": -1e9,
            "exit_reason": None,
            "basis_to_extension_px": self._last_keltner_upper - self._last_keltner_basis if self._last_keltner_upper is not None and self._last_keltner_basis is not None else None,
            "extension_to_extension_px": self._last_keltner_upper - self._last_keltner_lower if self._last_keltner_upper is not None and self._last_keltner_lower is not None else None,
            "keltner_slope_atr": self._last_keltner_slope,
        }
        self._diag["entries_submitted"] += 1
        self.submit_order(order)

    def _submit_exit(self, reason: str):
        if self._trade is None or self._trade.get("exit_order_id") is not None:
            return
        d = self._trade["direction"]
        side = OrderSide.SELL if d == 1 else OrderSide.BUY
        qty = Quantity.from_int(self._cfg.position_size)
        order = self.order_factory.market(
            instrument_id=InstrumentId.from_str(self._cfg.instrument_id),
            order_side=side, quantity=qty,
            time_in_force=TimeInForce.FOK,
            reduce_only=True
        )
        self._trade["exit_order_id"] = order.client_order_id.value
        self._trade["exit_reason"] = reason
        self._diag["exits_submitted"] += 1
        self.submit_order(order)

    def _monitor_open_trade(self, bar, decision_ts: int):
        t = self._trade
        d = t["direction"]
        ep = t["fill_price"]
        h = float(bar.high)
        l = float(bar.low)

        # 1. Update dynamic target tracking moving 3m basis
        basis = self._last_keltner_basis
        atr = self._last_keltner_atr
        if basis is not None and atr is not None:
            target_offset = self._cfg.target_offset_atr * atr
            if d == 1:
                t["target_px"] = basis - target_offset
            else:
                t["target_px"] = basis + target_offset

        target_px = t["target_px"]
        stop_px = t["stop_px"]
        disaster_stop_px = t["disaster_stop_px"]

        # 2. Update running extremes
        if d == 1:
            mfe = h - ep
            mae = ep - l
        else:
            mfe = ep - l
            mae = h - ep

        t["running_mfe"] = max(t["running_mfe"], mfe)
        t["running_mae"] = max(t["running_mae"], mae)

        # 3. Check touch resolution
        target_hit = False
        stop_hit = False
        disaster_hit = False

        if d == 1:
            if not self._cfg.disable_target and h >= target_px:
                target_hit = True
            if stop_px is not None and l <= stop_px:
                stop_hit = True
            if disaster_stop_px is not None and l <= disaster_stop_px:
                disaster_hit = True
        else:
            if not self._cfg.disable_target and l <= target_px:
                target_hit = True
            if stop_px is not None and h >= stop_px:
                stop_hit = True
            if disaster_stop_px is not None and h >= disaster_stop_px:
                disaster_hit = True

        # Resolve exits (prioritizing stops over target in same bar for conservativeness)
        if disaster_hit:
            self._submit_exit(reason="disaster_stop")
            self._diag["disaster_stop_hits"] += 1
        elif stop_hit:
            self._submit_exit(reason="stop")
            self._diag["stop_hits"] += 1
        elif target_hit:
            self._submit_exit(reason="target")
            self._diag["target_hits"] += 1

    def on_order_filled(self, event):
        cid = event.client_order_id.value
        if self._trade is None:
            return

        if cid == self._trade.get("entry_order_id"):
            ep = float(event.last_px)
            d = self._trade["direction"]
            self._trade["fill_price"] = ep
            self._trade["entry_ts"] = int(event.ts_event)
            self._trade["running_mfe"] = 0.0
            self._trade["running_mae"] = 0.0
            self._diag["entries_filled"] += 1
            
            # Recalculate static stops anchored to actual fill price
            atr = self._last_keltner_atr
            basis = self._last_keltner_basis
            if atr is not None and basis is not None:
                if self._cfg.variant == "A":
                    target_offset = self._cfg.target_offset_atr * atr
                    target_px_at_fill = basis - target_offset if d == 1 else basis + target_offset
                    dist = abs(target_px_at_fill - ep)
                    
                    if self._cfg.stop_type == "rr":
                        if d == 1:
                            self._trade["stop_px"] = ep - self._cfg.stop_rr_ratio * dist
                        else:
                            self._trade["stop_px"] = ep + self._cfg.stop_rr_ratio * dist
                    elif self._cfg.stop_type == "band_atr":
                        if d == 1:
                            self._trade["stop_px"] = ep - self._cfg.stop_atr_mult * atr
                        else:
                            self._trade["stop_px"] = ep + self._cfg.stop_atr_mult * atr
                elif self._cfg.variant == "B":
                    if d == 1:
                        self._trade["disaster_stop_px"] = ep - self._cfg.disaster_stop_atr_mult * atr
                    else:
                        self._trade["disaster_stop_px"] = ep + self._cfg.disaster_stop_atr_mult * atr
        elif cid == self._trade.get("exit_order_id"):
            self._trade["exit_price"] = float(event.last_px)
            self._trade["exit_ts"] = int(event.ts_event)
            self._diag["exits_filled"] += 1
            self._finalize_trade()

    def on_order_rejected(self, event):
        if self._trade is None:
            return
        cid = event.client_order_id.value
        if cid == self._trade.get("entry_order_id"):
            self._trade = None
        elif cid == self._trade.get("exit_order_id"):
            self._trade["exit_order_id"] = None

    def on_order_canceled(self, event):
        if self._trade is None:
            return
        cid = event.client_order_id.value
        if cid == self._trade.get("entry_order_id"):
            self._trade = None
        elif cid == self._trade.get("exit_order_id"):
            self._trade["exit_order_id"] = None

    def _finalize_trade(self):
        t = self._trade
        d = t["direction"]
        ep = t["fill_price"]
        ex = t["exit_price"]
        
        gross = (ex - ep) * d * self._cfg.multiplier
        cost = self._cfg.commission_per_rt + self._cfg.tick_dollar
        net = gross - cost
        
        t["gross_pnl"] = gross
        t["net_pnl"] = net
        t["hold_s"] = (t["exit_ts"] - t["entry_ts"]) / 1e9
        t["session"] = "RTH" if self._is_rth_minute(t["entry_ts"]) else "ETH"
        t["year"] = pd.Timestamp(t["entry_ts"], unit="ns", tz="UTC").year

        # Normalize MAE and MFE by entry ATR
        atr = t["atr_at_entry"]
        t["mae_atr"] = t["running_mae"] / atr if atr and atr > 0 else float("nan")
        t["mfe_atr"] = t["running_mfe"] / atr if atr and atr > 0 else float("nan")

        self._trades.append(dict(t))
        self._trade = None

    def _is_rth_minute(self, ts_ns: int) -> bool:
        ct = pd.Timestamp(ts_ns, tz="UTC").tz_convert(CT)
        m = ct.hour * 60 + ct.minute
        return 510 <= m < 900

    def on_stop(self):
        super().on_stop()
        if self._cfg.output_dir:
            outp = Path(self._cfg.output_dir)
            outp.mkdir(parents=True, exist_ok=True)
            if self._trades:
                pd.DataFrame(self._trades).to_parquet(outp / "trades.parquet", index=False)
            import json
            with open(outp / "diag.json", "w") as f:
                json.dump(self._diag, f, indent=2)
