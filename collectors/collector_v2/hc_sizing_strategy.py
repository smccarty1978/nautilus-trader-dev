"""HCSizingStrategy — NautilusTrader strategy that inherits from CollectorV2Strategy
and implements position sizing modulation at Bar 4 close based on hC walk-forward KNN predictions.
"""

from __future__ import annotations
import sys
import pandas as pd
import numpy as np
from pathlib import Path

# Setup paths
_repo_root = Path(__file__).parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Quantity
from nautilus_trader.trading.strategy import Strategy

from collectors.collector_v2.strategy import CollectorV2Strategy, CollectorV2Config

class HCSizingConfig(CollectorV2Config, frozen=True):
    sizing_policy: str = "baseline"       # "baseline" | "discrete" | "conservative" | "continuous"
    mapping_file_path: str = ""
    base_position_size: int = 2

class HCSizingStrategy(CollectorV2Strategy):
    def __init__(self, config: HCSizingConfig):
        super().__init__(config)
        self._cfg = config
        self._hc_map: dict[int, float] = {}
        
        # Load the precomputed hC mapping file
        if self._cfg.mapping_file_path:
            p = Path(self._cfg.mapping_file_path)
            if p.exists():
                df_map = pd.read_parquet(p)
                self._hc_map = dict(zip(df_map.regime_start_ts, df_map.hC))
                # Also log how many records loaded
                # We use print because log might not be fully configured in __init__
                print(f"Loaded {len(self._hc_map)} hC mapping records from {p}")
            else:
                print(f"WARNING: Mapping file {p} not found!")

    def _evaluate_bar1_check(self, bar_data, decision_ts, bar_ts_event):
        # Let the parent class run the evaluation and set self._pending_entry
        super()._evaluate_bar1_check(bar_data, decision_ts, bar_ts_event)
        
        # Add the regime start timestamp to the pending entry info
        if self._pending_entry is not None and self._pending_flip is not None:
            self._pending_entry["regime_start_ts"] = int(self._pending_flip["flip_ts_init"])

    def _submit_entry(self):
        regime_start_ts = self._pending_entry.get("regime_start_ts", 0)
        
        # Override parent entry order submission with GTC
        d = self._pending_entry["direction"]
        side = OrderSide.BUY if d == 1 else OrderSide.SELL
        qty = Quantity.from_int(self._cfg.position_size)
        order = self.order_factory.market(
            instrument_id=InstrumentId.from_str(self._cfg.instrument_id),
            order_side=side, quantity=qty,
            time_in_force=TimeInForce.GTC)
            
        self._trade = {
            "direction": int(d),
            "decision_event_id": int(self._pending_entry["decision_event_id"]),
            "decision_ts": int(self._pending_entry.get("decision_ts", 0)),
            "entry_order_id": order.client_order_id.value,
            "fill_price": None,
            "entry_ts": None,
            "exit_order_id": None,
            "exit_price": None,
            "exit_ts": None,
            "atr_at_signal": float(self._pending_entry.get("atr_at_signal", float("nan"))),
            "flip2conf_dir_efficiency_at_signal": float(self._pending_entry.get("flip2conf_dir_efficiency_at_signal", float("nan"))),
            "running_mfe": -1e9,
            "running_mae": -1e9,
            "t_running_mfe_ts": 0,
            "t_running_mae_ts": 0,
            "last_close_price": float("nan"),
            "last_close_ts": 0,
            "next_path_cp_ts": 0,
            "hhll_armed": False,
            "hhll_prev_30s_extreme": None,
            "hhll_stall_count_30s": 0,
            "hhll_protect_px": None,
            "hhll_protect_order_id": None,
            "hhll_mfe_at_arm": None,
            "exit_reason": None,
            "regime_start_ts": int(regime_start_ts),
            "size": int(self._cfg.position_size),
            "hC": float("nan"),
            "sizing_factor": 1.0,
            "sized": False,
            "cash_flows": [],
            "sizing_order_id": None,
            "sizing_price": float("nan"),
            "opp_regime_first_seen_ts": None,
            "opp_regime_exit_delay_bars": 0,
            "opp_regime_exit_submitted_count": 0,
            "opp_regime_exit_filled_count": 0,
        }
        self._pending_entry = None
        self.submit_order(order)

    def _on_1m_bucket_closed(self, decision_ts: int):
        # Run standard flip/confirmation logic
        super()._on_1m_bucket_closed(decision_ts)
        
        s_1m = self._registry.get("1m")
        if s_1m is None:
            return
            
        t = self._trade
        if t is not None:
            # State-Gated Opposing Regime Check & Audit Tracking
            current_regime = s_1m.regime
            if current_regime != 0 and current_regime != t["direction"]:
                if t["opp_regime_first_seen_ts"] is None:
                    t["opp_regime_first_seen_ts"] = int(decision_ts)
                else:
                    t["opp_regime_exit_delay_bars"] += 1
                
                # Submit exit order if not already pending
                if t.get("exit_order_id") is None:
                    self._submit_exit()
                    self._diag["regime_exits"] += 1
                    
        # Modulate size exactly at Bar 4 close (bars_in_regime == 5)
        if t is not None and not t.get("sized", False) and s_1m.bars_in_regime == 5:
            regime_start_ts = t.get("regime_start_ts", 0)
            hC = self._hc_map.get(regime_start_ts, float("nan"))
            
            if np.isnan(hC):
                # Fallback to 0.0 if not found
                hC = 0.0
                
            t["hC"] = hC
            
            # Compute sizing factor
            policy = self._cfg.sizing_policy
            if policy == "baseline":
                f = 1.0
            elif policy == "discrete":
                if hC >= 0.50:
                    f = 2.0
                elif hC >= 0.10:
                    f = 1.0
                else:
                    f = 0.5
            elif policy == "conservative":
                if hC >= 0.50:
                    f = 1.5
                elif hC >= 0.10:
                    f = 1.0
                else:
                    f = 0.5
            elif policy == "continuous":
                f = float(np.clip(0.5 + 3.75 * (hC - 0.1), 0.5, 2.0))
            else:
                raise ValueError(f"Unknown sizing policy: {policy}")
                
            t["sizing_factor"] = f
            
            base_size = self._cfg.base_position_size
            target_qty = int(round(base_size * f))
            current_qty = int(t["size"])
            diff = target_qty - current_qty
            
            if diff != 0:
                d = t["direction"]
                if d == 1:
                    side = OrderSide.BUY if diff > 0 else OrderSide.SELL
                else:
                    side = OrderSide.SELL if diff > 0 else OrderSide.BUY
                    
                sizing_qty = abs(diff)
                
                # Submit secondary sizing market order
                order = self.order_factory.market(
                    instrument_id=InstrumentId.from_str(self._cfg.instrument_id),
                    order_side=side,
                    quantity=Quantity.from_int(sizing_qty),
                    time_in_force=TimeInForce.GTC,
                    reduce_only=(diff < 0)
                )
                
                t["sizing_order_id"] = order.client_order_id.value
                t["sizing_order_qty"] = sizing_qty
                t["sizing_order_side"] = 1 if diff > 0 else -1
                
                try:
                    self.log.info(f"Submitting sizing order: {side} {sizing_qty} contracts (hC={hC:.3f}, factor={f:.2f}, target={target_qty})")
                except Exception:
                    pass
                self.submit_order(order)
            else:
                t["sized"] = True
                try:
                    self.log.info(f"Sizing logic checked: hC={hC:.3f}, factor={f:.2f}, size remains {current_qty}")
                except Exception:
                    pass

    def on_order_filled(self, event):
        cid = event.client_order_id.value
        if self._trade is None:
            super().on_order_filled(event)
            return
            
        if cid == self._trade.get("entry_order_id"):
            super().on_order_filled(event)
            d = self._trade["direction"]
            fill_price = float(event.last_px)
            fill_qty = int(event.last_qty)
            self._trade["cash_flows"].append((fill_qty, fill_price, -d))
            
        elif cid == self._trade.get("sizing_order_id"):
            fill_price = float(event.last_px)
            fill_qty = int(event.last_qty)
            self._trade["sizing_price"] = fill_price
            
            sizing_side = self._trade.get("sizing_order_side", 1) # 1 for add, -1 for reduce
            
            d = self._trade["direction"]
            self._trade["cash_flows"].append((fill_qty, fill_price, -d * sizing_side))
            self._trade["size"] += fill_qty * sizing_side
            
            self._trade.setdefault("sizing_filled_qty", 0)
            self._trade["sizing_filled_qty"] += fill_qty
            if self._trade["sizing_filled_qty"] >= self._trade.get("sizing_order_qty", 0):
                self._trade["sized"] = True
                try:
                    self.log.info(f"Sizing order fully filled: new size = {self._trade['size']}")
                except Exception:
                    pass
                
        elif cid == self._trade.get("exit_order_id"):
            d = self._trade["direction"]
            exit_price = float(event.last_px)
            fill_qty = int(event.last_qty)
            self._trade["cash_flows"].append((fill_qty, exit_price, d))
            
            self._trade.setdefault("exit_filled_qty", 0)
            self._trade["exit_filled_qty"] += fill_qty
            
            if self._trade["exit_filled_qty"] >= self._trade["size"]:
                self._trade["opp_regime_exit_filled_count"] = 1
                super().on_order_filled(event)
            
        else:
            super().on_order_filled(event)

    def on_order_rejected(self, event):
        if self._trade is None:
            super().on_order_rejected(event)
            return
        cid = event.client_order_id.value
        if cid == self._trade.get("sizing_order_id"):
            try: self.log.warning(f"sizing order rejected: {getattr(event, 'reason', '')}")
            except Exception: pass
            self._trade["sizing_order_id"] = None
            self._trade["sized"] = False
        else:
            super().on_order_rejected(event)

    def on_order_canceled(self, event):
        if self._trade is None:
            return
        cid = event.client_order_id.value
        if cid == self._trade.get("entry_order_id"):
            try: self.log.warning("entry cancelled — discarding trade state")
            except Exception: pass
            self._trade = None
        elif cid == self._trade.get("sizing_order_id"):
            try: self.log.warning("sizing order cancelled")
            except Exception: pass
            self._trade["sizing_order_id"] = None
            self._trade["sized"] = False
        elif cid == self._trade.get("exit_order_id"):
            try: self.log.warning("exit order cancelled — clearing exit_order_id to retry")
            except Exception: pass
            self._trade["exit_order_id"] = None

    def on_order_expired(self, event):
        if self._trade is None:
            return
        cid = event.client_order_id.value
        if cid == self._trade.get("entry_order_id"):
            try: self.log.warning("entry expired — discarding trade state")
            except Exception: pass
            self._trade = None
        elif cid == self._trade.get("sizing_order_id"):
            try: self.log.warning("sizing order expired")
            except Exception: pass
            self._trade["sizing_order_id"] = None
            self._trade["sized"] = False
        elif cid == self._trade.get("exit_order_id"):
            try: self.log.warning("exit order expired — clearing exit_order_id to retry")
            except Exception: pass
            self._trade["exit_order_id"] = None

    def _submit_exit(self):
        if self._trade is None:
            return
        if self._trade.get("exit_order_id") is not None:
            return
            
        d = self._trade["direction"]
        side = OrderSide.SELL if d == 1 else OrderSide.BUY
        
        filled = self._trade.get("exit_filled_qty", 0)
        remaining_qty = self._trade["size"] - filled
        if remaining_qty <= 0:
            return
            
        qty = Quantity.from_int(remaining_qty)
        order = self.order_factory.market(
            instrument_id=InstrumentId.from_str(self._cfg.instrument_id),
            order_side=side, quantity=qty,
            time_in_force=TimeInForce.GTC,
            reduce_only=True)
        self._trade["exit_order_id"] = order.client_order_id.value
        self._trade["exit_reason"] = "regime"
        
        # Track exit submission for audit
        self._trade["opp_regime_exit_submitted_count"] = self._trade.get("opp_regime_exit_submitted_count", 0) + 1
        
        self.submit_order(order)

    def _check_hhll_protect_trigger(self, bar, decision_ts: int):
        t = self._trade
        if t is None or not t.get("hhll_armed", False):
            return
        if t.get("exit_order_id") is not None:
            return  # already exiting
            
        protect_px = t.get("hhll_protect_px")
        if protect_px is None:
            return
            
        d = int(t["direction"])
        triggered = ((d == 1 and float(bar.low) <= protect_px)
                      or (d == -1 and float(bar.high) >= protect_px))
        if not triggered:
            return
            
        # Submit exit using remaining quantity
        side = OrderSide.SELL if d == 1 else OrderSide.BUY
        filled = self._trade.get("exit_filled_qty", 0)
        remaining_qty = self._trade["size"] - filled
        if remaining_qty <= 0:
            return
            
        qty = Quantity.from_int(remaining_qty)
        order = self.order_factory.market(
            instrument_id=InstrumentId.from_str(self._cfg.instrument_id),
            order_side=side, quantity=qty,
            time_in_force=TimeInForce.GTC,
            reduce_only=True)
        t["exit_order_id"] = order.client_order_id.value
        t["exit_reason"] = "hhll_protect"
        self._diag["hhll_exits"] += 1
        self.submit_order(order)

    def _finalize_trade(self):
        t = self._trade
        
        # Calculate cash flow PNL
        # cash_flows: list of (qty, price, sign)
        total_cf = sum(qty * price * sign for qty, price, sign in t["cash_flows"])
        gross = total_cf * self._cfg.multiplier
        
        # Scale commission and tick dollar by final sizing_factor
        cost = (self._cfg.commission_per_rt + self._cfg.tick_dollar) * t["sizing_factor"]
        net = gross - cost
        
        t["gross_pnl"] = gross
        t["net_pnl"] = net
        t["hold_s"] = (t["exit_ts"] - t["entry_ts"]) / 1e9
        t["session"] = (
            "RTH" if self._is_rth_minute(t["entry_ts"])
            else "ETH")
            
        try:
            self.log.info(f"Finalizing trade: hC={t['hC']:.3f}, factor={t['sizing_factor']:.2f}, size={t['size']}, gross=${gross:.2f}, net=${net:.2f}")
        except Exception:
            pass
            
        self._trades.append(dict(t))
        self._trade = None
