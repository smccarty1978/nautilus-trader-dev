from __future__ import annotations

import os
import sys
from collections import deque
from pathlib import Path
import numpy as np
import pandas as pd

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import ClientOrderId, InstrumentId
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.trading.strategy import Strategy

PROJECT_ROOT = Path("c:/Users/Scott McCarty/Projects/Nautilus Trader")
sys.path.insert(0, str(PROJECT_ROOT))

# Import baseline strategy components
from backtests.baseline_flip_parity.strategy import BaselineFlipParityStrategy, BaselineFlipParityConfig, _tick_round

NS_PER_S = 1_000_000_000
NQ_MULT = 20.0
COMM_RT = 5.0

class W4ExitConfig(BaselineFlipParityConfig, frozen=True):
    policy: str = "B0"  # "B0", "B1", "B2", "B3", "B4", "B5"
    theta: float = 0.62
    N: int = 10         # persistence ticks (N * 5s)

class W4ExitStrategy(BaselineFlipParityStrategy):
    def __init__(self, config: W4ExitConfig):
        super().__init__(config)
        self._cfg = config
        
        # State machine
        self._warning_state = "NORMAL" # "NORMAL", "QUALIFIED", "ACTION_TAKEN"
        self._warn_streak = 0
        self._last_5s_ts = -1
        self._last_flip_ts = None
        self._tight_stop = None
        self._running_mae = 0.0
        
        self.parity_logs = []
        self._pred_dict = {}
        
    def on_start(self):
        super().on_start()
        
        # Load predictions
        pred_path = PROJECT_ROOT / "studies/regime_sequence_signal_audit/results/weakness_checkpoint_predictions.parquet"
        if pred_path.exists():
            df = pd.read_parquet(pred_path)
            dt = pd.to_datetime(df["observation_time"], unit="ns", utc=True)
            df = df[dt.dt.year == self._cfg.year]
            
            # Map (direction, regime_start_time, observation_time)
            for row in df.itertuples():
                key = (int(row.direction), int(row.regime_start_time), int(row.observation_time))
                self._pred_dict[key] = {
                    "w4_prob": float(row.w4_prob),
                    "regime_age": float(row.regime_age),
                    "current_pnl": float(row.current_pnl),
                    "giveback": float(row.giveback),
                    "median_center_5m": float(row.median_center_5m) if hasattr(row, "median_center_5m") else 0.0
                }
            print(f"Loaded {len(self._pred_dict)} weakness predictions for year {self._cfg.year}.")
        else:
            print(f"Warning: {pred_path} not found.")

    def on_order_filled(self, event):
        # Reset warning state machine synchronously on the fill that flattens the
        # position. `_record_trade` (base class, called from within
        # super().on_order_filled) already nulls `self._entry_px` before this
        # method returns, so an on_bar-time check of `self._entry_px is not None`
        # can never observe a just-closed trade — that check is dead code and the
        # state machine would otherwise never reset between trades. Resetting here
        # (right after the base class applies the fill) is the first point where
        # `portfolio.is_flat` reliably reflects a completed close.
        super().on_order_filled(event)
        if self.portfolio.is_flat(self._inst_id):
            self._warning_state = "NORMAL"
            self._warn_streak = 0
            self._running_mae = 0.0
            self._tight_stop = None
            self._partial_exit_order_id = None
            self._partial_exit_reason = None

    def on_bar(self, bar: Bar):
        # 1-second bar handling
        if bar.bar_type == self._bt_1s:
            c = float(bar.close)
            h = float(bar.high)
            l = float(bar.low)
            ts = bar.ts_init  # Correct timestamp convention A1
            
            # Run base class stop loss / order management
            super().on_bar(bar)
            
            if self._entry_px is not None and not self.portfolio.is_flat(self._inst_id):
                # Update running MFE/MAE
                if self._entry_dir == 1:
                    mfe = (h - self._entry_px) / self._entry_atr
                    mae = (self._entry_px - l) / self._entry_atr
                else:
                    mfe = (self._entry_px - l) / self._entry_atr
                    mae = (h - self._entry_px) / self._entry_atr
                self._running_mfe = max(self._running_mfe, mfe)
                self._running_mae = max(self._running_mae, mae)
                
                # Check custom stop triggers for B3 policy
                if self._warning_state == "QUALIFIED" and self._cfg.policy == "B3":
                    if self._tight_stop is not None:
                        if (self._entry_dir == 1 and l <= self._tight_stop) or (self._entry_dir == -1 and h >= self._tight_stop):
                            self._exit_all_market("W4_B3_exit")
                            self._warning_state = "ACTION_TAKEN"
                            return
                            
                # Check 5-second checkpoint boundary (Warning 2 gap protection)
                ts_sec = ts // 1_000_000_000
                if (ts_sec // 5) > self._last_5s_ts:
                    self._last_5s_ts = ts_sec // 5
                    self._process_5s_checkpoint(ts, c)

        # 1-minute bar handling
        elif bar.bar_type == self._bt_1m:
            prev_regime = self._regime_state.regime
            super().on_bar(bar)
            new_regime = self._regime_state.regime
            
            # Record exact flip timestamp dynamically (Warning 3 resolution)
            if prev_regime != 0 and new_regime != 0 and prev_regime != new_regime:
                self._last_flip_ts = bar.ts_init

    def _process_5s_checkpoint(self, ts: int, close: float):
        # Resolve exact flip timestamp causally
        if self._last_flip_ts is not None:
            flip_ts = self._last_flip_ts
        else:
            flip_ts = self._entry_ts - 60 * NS_PER_S
            
        key = (self._entry_dir, flip_ts, ts)
        pred_data = self._pred_dict.get(key)
        
        if pred_data is None:
            return
            
        w4_prob = pred_data["w4_prob"]
        
        # Calculate runtime features for parity check
        runtime_regime_age = (ts - flip_ts) / 1e9
        runtime_current_pnl = self._entry_dir * (close - self._entry_px) / self._entry_atr
        runtime_giveback = self._running_mfe - runtime_current_pnl
        
        self.parity_logs.append({
            "observation_time": ts,
            "direction": self._entry_dir,
            "regime_start_time": flip_ts,
            "offline_w4_prob": w4_prob,
            "offline_regime_age": pred_data["regime_age"],
            "runtime_regime_age": runtime_regime_age,
            "offline_current_pnl": pred_data["current_pnl"],
            "runtime_current_pnl": runtime_current_pnl,
            "offline_giveback": pred_data["giveback"],
            "runtime_giveback": runtime_giveback
        })
        
        # Warning State Machine
        if self._warning_state == "NORMAL":
            if w4_prob >= self._cfg.theta:
                self._warn_streak += 1
            else:
                self._warn_streak = 0

            if self._warn_streak >= self._cfg.N:
                self._warning_state = "QUALIFIED"
                self._warn_close = close

                if self._cfg.policy == "B3":
                    # Lock in tight stop loss level
                    self._tight_stop = close - self._entry_dir * 0.50 * self._entry_atr
                else:
                    # B1/B4 fire immediately on qualification
                    self._fire_immediate_exit(close)

        elif self._warning_state == "QUALIFIED":
            # B1/B4 retry: a prior immediate-exit attempt was rejected/canceled/
            # expired (see _is_exit_action_order / on_order_rejected etc.), which
            # reverts state from ACTION_TAKEN back to QUALIFIED so we retry here.
            if self._cfg.policy in ("B1", "B4"):
                self._fire_immediate_exit(close)
            # Deferred confirmation actions
            elif self._cfg.policy == "B2":
                peak_px = self._entry_px + self._entry_dir * self._running_mfe * self._entry_atr
                ret = self._entry_dir * (peak_px - close)
                if ret >= 0.25 * self._entry_atr:
                    self._exit_all_market("W4_B2_exit")
                    self._warning_state = "ACTION_TAKEN"
            elif self._cfg.policy == "B5":
                median_center = pred_data["median_center_5m"]
                if self._entry_dir * (median_center - close) < 0:
                    self._exit_all_market("W4_B5_exit")
                    self._warning_state = "ACTION_TAKEN"

    def _fire_immediate_exit(self, close: float):
        """B1: full exit. B4: scale out half the position (requires entry_qty=2);
        remainder rides on the existing SL/target/regime-flip/max-hold exits.
        Guarded by _exit_all_market/_exit_partial_market against an exit already
        in flight, so calling this again while one is pending is a harmless no-op.
        """
        if self._cfg.policy == "B1":
            self._exit_all_market("W4_B1_exit")
            self._warning_state = "ACTION_TAKEN"
        elif self._cfg.policy == "B4":
            half_qty = self._remaining_qty // 2
            if half_qty < 1:
                self.log.warning(
                    f"B4 partial exit skipped: remaining_qty={self._remaining_qty} "
                    f"(policy B4 requires entry_qty=2)"
                )
                return
            self._exit_partial_market(half_qty, "W4_B4_partial_exit")
            self._warning_state = "ACTION_TAKEN"

    def _is_exit_action_order(self, cid: str) -> bool:
        # Must be checked BEFORE the base class handler runs, since it clears
        # _exit_order_id/_partial_exit_order_id/_exit_order_ids on
        # rejection/cancel/expiry. In practice only the scalar ids are ever
        # populated by _fire_immediate_exit (B4's partial exit always resolves
        # to a single 1-lot order; only a base-class-triggered exit like
        # max_hold can populate _exit_order_ids at remaining_qty>1, and that
        # path is independent of the warning state machine) — checked here too
        # defensively in case that assumption ever changes.
        return (
            cid == self._exit_order_id
            or cid == self._partial_exit_order_id
            or bool(self._exit_order_ids and cid in self._exit_order_ids)
        )

    def on_order_rejected(self, event):
        cid = event.client_order_id.value
        was_exit_action = self._is_exit_action_order(cid)
        super().on_order_rejected(event)
        if was_exit_action and self._warning_state == "ACTION_TAKEN":
            self._warning_state = "QUALIFIED"

    def on_order_canceled(self, event):
        cid = event.client_order_id.value
        was_exit_action = self._is_exit_action_order(cid)
        super().on_order_canceled(event)
        if was_exit_action and self._warning_state == "ACTION_TAKEN":
            self._warning_state = "QUALIFIED"

    def on_order_expired(self, event):
        cid = event.client_order_id.value
        was_exit_action = self._is_exit_action_order(cid)
        super().on_order_expired(event)
        if was_exit_action and self._warning_state == "ACTION_TAKEN":
            self._warning_state = "QUALIFIED"

    def on_stop(self):
        # Save parity verification logs
        if self.parity_logs:
            df_p = pd.DataFrame(self.parity_logs)
            out_p = PROJECT_ROOT / f"backtests/results/w4_parity_{self._cfg.year}_{self._cfg.policy}.parquet"
            out_p.parent.mkdir(parents=True, exist_ok=True)
            df_p.to_parquet(out_p, index=False)
            print(f"Parity log written to {out_p}")
