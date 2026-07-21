from typing import Any, Dict, List, Optional


class ResearchTradeState:
    """Represents the lifecycle and execution geometry of a single research trade."""

    def __init__(self, trade_id: str, entry_time: int, entry_px: float, direction: int, qty: float, atr: float):
        self.trade_id = trade_id
        self.entry_time = entry_time
        self.entry_px = entry_px
        self.direction = direction  # 1 for Long, -1 for Short
        self.qty = qty
        self.atr_at_entry = atr

        self.sl_px: Optional[float] = None
        self.pt_px: Optional[float] = None
        self.is_open = True
        
        # Pending exit flag to enforce next-bar open fill (H4 rule)
        self.pending_exit = False
        self.exit_time: Optional[int] = None
        self.exit_px: Optional[float] = None
        self.exit_reason: Optional[str] = None
        self.pnl = 0.0

    def trigger_exit(self, reason: str) -> None:
        """Flags the trade to be closed at the next bar's open price."""
        if self.is_open and not self.pending_exit:
            self.pending_exit = True
            self.exit_reason = reason

    def fill_exit(self, exit_time: int, open_px: float) -> None:
        """Executes the exit at the next-bar open price (H4 rule)."""
        if self.is_open and self.pending_exit:
            self.exit_px = open_px
            self.exit_time = exit_time
            self.is_open = False
            self.pending_exit = False
            
            # PnL calculation
            price_diff = self.exit_px - self.entry_px
            self.pnl = price_diff * self.direction * self.qty


class ThresholdEvaluator:
    """Evaluates entry triggers and exit conditions for a specific policy/threshold variant."""

    def __init__(self, name: str, threshold: float, sl_atr_mult: float, pt_atr_mult: float):
        self.name = name
        self.threshold = threshold
        self.sl_atr_mult = sl_atr_mult
        self.pt_atr_mult = pt_atr_mult
        
        self.active_trades: List[ResearchTradeState] = []
        self.trade_history: List[ResearchTradeState] = []
        self.trade_counter = 0

    def on_candidate(self, ts_event: int, price: float, atr: float, score: float, direction: int) -> None:
        """Evaluates entry score against threshold."""
        # Only enter if score exceeds threshold and no active trade in this evaluator
        if score >= self.threshold and not any(t.is_open for t in self.active_trades):
            self.trade_counter += 1
            trade_id = f"{self.name}-{self.trade_counter:04d}"
            
            trade = ResearchTradeState(
                trade_id=trade_id,
                entry_time=ts_event,
                entry_px=price,
                direction=direction,
                qty=1.0,
                atr=atr
            )
            
            # Set stops
            trade.sl_px = price - (direction * self.sl_atr_mult * atr)
            trade.pt_px = price + (direction * self.pt_atr_mult * atr)
            
            self.active_trades.append(trade)

    def on_bar_1s(self, ts_event: int, open_px: float, high: float, low: float, close: float) -> None:
        """Checks stops and fills exits on 1s bars using high/low for detection and next open for fills."""
        # 1. Fill any pending exits from the previous bar (H4 rule: next-bar open fill)
        for trade in self.active_trades:
            if trade.pending_exit:
                trade.fill_exit(ts_event, open_px)

        # Remove completed trades from active list
        closed = [t for t in self.active_trades if not t.is_open]
        for t in closed:
            self.active_trades.remove(t)
            self.trade_history.append(t)

        # 2. Check stops and targets using high/low (H1 rule: no close-only detection)
        for trade in self.active_trades:
            if trade.pending_exit:
                continue

            if trade.direction == 1:  # Long
                # Stop loss breached
                if trade.sl_px is not None and low <= trade.sl_px:
                    trade.trigger_exit("SL")
                # Profit target breached
                elif trade.pt_px is not None and high >= trade.pt_px:
                    trade.trigger_exit("PT")
            else:  # Short
                # Stop loss breached
                if trade.sl_px is not None and high >= trade.sl_px:
                    trade.trigger_exit("SL")
                # Profit target breached
                elif trade.pt_px is not None and low <= trade.pt_px:
                    trade.trigger_exit("PT")

    def get_serialized_state(self) -> Dict[str, Any]:
        """Returns serializable state for daily checkpointer."""
        return {
            "trade_counter": self.trade_counter,
            "active_trades": [
                {
                    "trade_id": t.trade_id,
                    "entry_time": t.entry_time,
                    "entry_px": t.entry_px,
                    "direction": t.direction,
                    "qty": t.qty,
                    "atr_at_entry": t.atr_at_entry,
                    "sl_px": t.sl_px,
                    "pt_px": t.pt_px,
                    "pending_exit": t.pending_exit,
                    "exit_reason": t.exit_reason,
                    "is_open": t.is_open
                }
                for t in self.active_trades
            ],
            "trade_history": [
                {
                    "trade_id": t.trade_id,
                    "entry_time": t.entry_time,
                    "entry_px": t.entry_px,
                    "direction": t.direction,
                    "qty": t.qty,
                    "atr_at_entry": t.atr_at_entry,
                    "sl_px": t.sl_px,
                    "pt_px": t.pt_px,
                    "exit_time": t.exit_time,
                    "exit_px": t.exit_px,
                    "exit_reason": t.exit_reason,
                    "pnl": t.pnl,
                    "is_open": t.is_open
                }
                for t in self.trade_history
            ]
        }

    def load_serialized_state(self, state: Dict[str, Any]) -> None:
        """Loads serialized state from checkpointer."""
        self.trade_counter = state["trade_counter"]
        
        self.active_trades = []
        for t_data in state["active_trades"]:
            t = ResearchTradeState(
                trade_id=t_data["trade_id"],
                entry_time=t_data["entry_time"],
                entry_px=t_data["entry_px"],
                direction=t_data["direction"],
                qty=t_data["qty"],
                atr=t_data["atr_at_entry"]
            )
            t.sl_px = t_data["sl_px"]
            t.pt_px = t_data["pt_px"]
            t.pending_exit = t_data["pending_exit"]
            t.exit_reason = t_data["exit_reason"]
            t.is_open = t_data["is_open"]
            self.active_trades.append(t)

        self.trade_history = []
        for t_data in state["trade_history"]:
            t = ResearchTradeState(
                trade_id=t_data["trade_id"],
                entry_time=t_data["entry_time"],
                entry_px=t_data["entry_px"],
                direction=t_data["direction"],
                qty=t_data["qty"],
                atr=t_data["atr_at_entry"]
            )
            t.sl_px = t_data["sl_px"]
            t.pt_px = t_data["pt_px"]
            t.exit_time = t_data["exit_time"]
            t.exit_px = t_data["exit_px"]
            t.exit_reason = t_data["exit_reason"]
            t.pnl = t_data["pnl"]
            t.is_open = t_data["is_open"]
            self.trade_history.append(t)
