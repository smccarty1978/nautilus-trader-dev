"""PullbackV1Strategy — live-style 5s pullback on qualified 1m regimes.

Universe:  hC >= 0.50 at bar 8, state = Healthy or HH-HardStall.
Entry:     first 5s up-close after depth threshold → market order (fills next 1s bar).
PT:        GTC LIMIT at entry_px ± 0.5 * atr_base. Fills when bar HIGH (LOW for
           short) touches target. Mirrors offline study's intra-bar PT mechanic.
SL:        5s close below structural pullback low → cancel PT limit, market exit.
Flip:      1m opposite regime flip → cancel PT limit, market exit.
Position:  one per regime, no re-entries.
"""

from __future__ import annotations
import math
import sys
from collections import deque
from pathlib import Path
from typing import Optional

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import ClientOrderId, InstrumentId
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.trading.strategy import Strategy

from collectors.collector_v2.aggregator import TimeframeAggregator, _OpenBucket  # noqa: E402

MULT = 20.0   # NQ $/pt
COMM = 4.06   # $/RT 1-lot
NS_PER_MIN = 60_000_000_000

from utils.regime_engine import (
    LiteRegimeEngine as _LiteRegimeEngine,
    state_cat as _state_cat,
    IS_STALL_P33,
    IS_STALL_P67,
)


class PullbackV1Config(StrategyConfig, frozen=True):
    instrument_id: str = "NQ.XCME"
    bar_type_1s: str = "NQ.XCME-1-SECOND-LAST-EXTERNAL"
    depth: float = 0.25          # ATR depth threshold (0.25 / 0.50 / 0.75)
    hc_floor: float = 0.50       # minimum hC at bar 8 for universe
    trade_size: int = 1
    hc_mapping_path: str = (
        "collectors/collector_v2/results/combined_arch/hc_perbar_mapping.parquet"
    )


class PullbackV1Strategy(Strategy):
    """Live-style 5s pullback strategy.

    Subscribes to 1s bars only.  Aggregates to 1m (regime) and 5s
    (pullback detection) internally via TimeframeAggregator fed with
    bar.ts_init — matching the capsule builder's convention so that
    regime_start_ts values align with hc_perbar_mapping entries.
    """

    def __init__(self, config: PullbackV1Config) -> None:
        super().__init__(config)
        self._cfg = config
        self._inst_id = InstrumentId.from_str(config.instrument_id)

        # Pre-load hC mapping: (regime_start_ts, bars_in_regime) → (hC, state)
        hc_path = Path(config.hc_mapping_path)
        if not hc_path.is_absolute():
            hc_path = PROJECT_ROOT / hc_path
        df_hc = pd.read_parquet(hc_path)
        self._hc_dict: dict[tuple, tuple] = {
            (int(r.regime_start_ts), int(r.bars_in_regime)): (r.hC, r.state)
            for r in df_hc.itertuples(index=False)
        }

        # 1m regime engine
        self._eng = _LiteRegimeEngine()

        # Aggregator: 1m fires before 5s at same close_ts (macro-first ordering)
        self._agg = TimeframeAggregator(
            on_bucket_closed=self._on_bucket_closed,
            timeframes=("1m", "5s"),
        )

        # ATR rolling buffer for atr_base = max(cur_atr, 0.5 * mean(last60))
        self._atr_hist: deque = deque(maxlen=60)

        # ── Regime state ──────────────────────────────────────────────────────
        self._prev_regime: int = 0
        self._in_regime: bool = False   # True after first genuine flip
        self._rs_ts: int = 0            # regime_start_ts (flip bar close_ts)
        self._dir: int = 0              # +1 long / -1 short
        self._atr_base: float = 0.0     # ATR at flip time (smoothed)

        # ── Running extreme (max close for long, min close for short) ─────────
        self._run_ext: float = 0.0

        # ── Pullback detection ────────────────────────────────────────────────
        self._watching: bool = False    # True after bar-8 qualification
        self._pb_active: bool = False   # True after depth threshold reached
        self._pb_sl: float = 0.0        # structural SL level (deepest close for long,
        #                                 highest close for short)

        # ── Entry / exit tracking ─────────────────────────────────────────────
        self._entry_submitted: bool = False
        self._in_position: bool = False
        self._exit_submitted: bool = False
        self._entry_order_id: Optional[str] = None
        self._exit_order_id: Optional[str] = None
        self._pt_order_id: Optional[str] = None   # GTC LIMIT at +0.5 ATR
        self._pt05_px: float = 0.0
        self._entry_px: float = 0.0
        self._entry_ts: int = 0
        self._exit_reason: str = ""
        self._sl_px: float = 0.0

        # ── MAE / MFE tracking (in ATR units, from entry) ─────────────────────
        self._cur_mfe: float = 0.0
        self._cur_mae: float = 0.0
        self._recent_1s_bars: deque = deque(maxlen=120)

        # ── Trade log (post-run analysis) ─────────────────────────────────────
        self.trade_log: list[dict] = []

    # ── NT lifecycle ──────────────────────────────────────────────────────────

    def on_start(self) -> None:
        self._bt_1s = BarType.from_str(self._cfg.bar_type_1s)
        self.subscribe_bars(self._bt_1s)

    def on_bar(self, bar: Bar) -> None:
        if bar.bar_type != self._bt_1s:
            return

        # Buffer 1s bar for retroactive MFE/MAE seeding
        self._recent_1s_bars.append(bar)

        # Feed ts_init (not ts_event) — matches capsule builder so that
        # bucket close_ts values (= regime_start_ts) align with hC mapping.
        self._agg.on_1s_bar(
            int(bar.ts_init),
            float(bar.open), float(bar.high), float(bar.low), float(bar.close),
            float(bar.volume) if hasattr(bar, "volume") else 0.0,
        )

        # Update MFE/MAE on every 1s bar
        if self._in_position and not self._exit_submitted:
            atr = self._atr_base
            if atr > 0:
                h = float(bar.high)
                l = float(bar.low)
                if self._dir == 1:
                    self._cur_mfe = max(self._cur_mfe, (h - self._entry_px) / atr)
                    self._cur_mae = max(self._cur_mae, (self._entry_px - l) / atr)
                else:
                    self._cur_mfe = max(self._cur_mfe, (self._entry_px - l) / atr)
                    self._cur_mae = max(self._cur_mae, (h - self._entry_px) / atr)

    # ── Aggregator callbacks (macro-first: 1m before 5s at same close_ts) ────

    def _on_bucket_closed(self, tf: str, bucket: _OpenBucket) -> None:
        if tf == "1m":
            self._on_1m_close(bucket)
        elif tf == "5s":
            self._on_5s_close(bucket)

    # ── 1m bar: regime engine + flip detection + bar-8 qualification ──────────

    def _on_1m_close(self, bucket: _OpenBucket) -> None:
        prev_regime = self._prev_regime
        self._eng.update(bucket)
        cur_regime = self._eng.regime

        # Track ATR history (used for atr_base smoothing on flip)
        atr_now = self._eng.atr
        if atr_now is not None and atr_now > 0:
            self._atr_hist.append(atr_now)

        # Genuine flip: direction changed from a non-zero regime
        flipped = (cur_regime != prev_regime and cur_regime != 0 and prev_regime != 0)

        if flipped:
            # Exit any open / pending position on the OLD regime
            if self._in_position or self._entry_submitted:
                self._submit_exit("regime_flip")

            # Initialize new regime tracking
            self._in_regime = True
            self._rs_ts = bucket.close_ts
            self._dir = cur_regime

            cur_atr = atr_now if (atr_now is not None and atr_now > 0) else 1.0
            roll = (sum(self._atr_hist) / len(self._atr_hist)) if self._atr_hist else cur_atr
            self._atr_base = max(cur_atr, 0.5 * roll)

            self._run_ext = bucket.close  # seed from flip bar close
            self._watching = False
            self._pb_active = False
            self._pb_sl = 0.0

        elif cur_regime != 0 and self._in_regime:
            # Same regime — do NOT update self._run_ext here to avoid masking peak checks
            # in the subsequent _on_5s_close callback. _on_5s_close will handle it.
            pass

        # Bar-8 qualification check (bars_in_regime == 9 after bar k=8 closes)
        if (cur_regime != 0 and not self._watching and not self._in_position
                and not self._entry_submitted
                and self._eng.bars_in_regime == 9 and self._rs_ts > 0
                and self._eng.atr is not None):
            entry = self._hc_dict.get((self._rs_ts, 9))
            if entry is not None:
                hc_val, state_raw = entry
                if not math.isnan(hc_val) and hc_val >= self._cfg.hc_floor:
                    sc = _state_cat(hc_val, state_raw)
                    if sc in ("Healthy", "HH-HardStall"):
                        self._watching = True
                        self.log.info(
                            f"QUALIFIED rs={self._rs_ts} dir={self._dir} "
                            f"hC={hc_val:.3f} state={sc} atr={self._atr_base:.2f}"
                        )

        self._prev_regime = cur_regime

    # ── 5s bar: run_ext tracking, pullback detection, SL monitoring ───────────

    def _on_5s_close(self, bucket: _OpenBucket) -> None:
        if not self._in_regime and not self._in_position:
            return

        ts = bucket.close_ts
        c  = bucket.close
        o  = bucket.open
        h  = bucket.high
        l  = bucket.low
        dsign = self._dir
        atr   = self._atr_base

        # ── Detect new peak and update running extreme ────────────────────────
        # CRITICAL: check new_peak BEFORE updating _run_ext; otherwise the
        # comparison c > _run_ext is always False after the update.
        if self._in_regime:
            if dsign == 1:
                new_peak = c > self._run_ext
                if new_peak:
                    self._run_ext = c
            elif dsign == -1:
                new_peak = c < self._run_ext
                if new_peak:
                    self._run_ext = c
            else:
                new_peak = False
        else:
            new_peak = False

        # ── SL monitoring while in position ───────────────────────────────────
        if self._in_position and not self._exit_submitted:
            sl_hit = ((dsign == 1 and c < self._sl_px) or
                      (dsign == -1 and c > self._sl_px))
            if sl_hit:
                self._submit_exit("structure_break")
            return  # no new entries while in position

        if not self._watching:
            return

        # ── Pullback depth (from running extreme, which is now updated) ──────────
        if atr > 0:
            if dsign == 1:
                pb_depth = (self._run_ext - c) / atr
            else:
                pb_depth = (c - self._run_ext) / atr
        else:
            pb_depth = 0.0

        # New peak resets pullback state (but NOT an entered trade)
        if new_peak:
            self._pb_active = False
            self._pb_sl = 0.0
            return

        # ── Causal hC gate for activating a new pullback ──────────────────────
        # Computed only when we need to trigger a new pullback episode.
        if not self._pb_active and not self._entry_submitted:
            delta_ns = ts - self._rs_ts
            bir_closed = int(math.ceil(delta_ns / NS_PER_MIN)) + 1 if delta_ns > 0 else 1
            hc_now, _ = self._hc_dict.get((self._rs_ts, bir_closed), (float("nan"), ""))
            hc_valid = not math.isnan(hc_now)
        else:
            hc_valid = True  # already active, skip re-check

        # ── Activate pullback episode when depth threshold first reached ───────
        if not self._pb_active and not self._entry_submitted and hc_valid:
            if pb_depth >= self._cfg.depth:
                self._pb_active = True
                self._pb_sl = c  # structural SL starts at first qualifying close

        # ── Update structural SL level (deepest close during pullback) ────────
        if self._pb_active and not self._entry_submitted:
            if (dsign == 1 and c < self._pb_sl) or (dsign == -1 and c > self._pb_sl):
                self._pb_sl = c

        # ── First up-close confirmation → submit entry ─────────────────────────
        # Market order fills at next 1s bar's open ≈ open of next 5s window.
        # This matches the offline study's "enter at open of next bar."
        if self._pb_active and not self._entry_submitted:
            is_confirm = (dsign == 1 and c > o) or (dsign == -1 and c < o)
            if is_confirm:
                self._submit_entry()

    # ── Order helpers ─────────────────────────────────────────────────────────

    def _submit_entry(self) -> None:
        if self._entry_submitted or self._in_position:
            return
        self._entry_submitted = True

        side = OrderSide.BUY if self._dir == 1 else OrderSide.SELL
        order = self.order_factory.market(
            instrument_id=self._inst_id,
            order_side=side,
            quantity=Quantity.from_int(self._cfg.trade_size),
            time_in_force=TimeInForce.GTC,
        )
        self._entry_order_id = order.client_order_id.value
        self.submit_order(order)

    def _cancel_pt_limit(self) -> None:
        if self._pt_order_id is None:
            return
        pt_order = self.cache.order(ClientOrderId(self._pt_order_id))
        if pt_order is not None and pt_order.is_open:
            self.cancel_order(pt_order)
        self._pt_order_id = None

    def _submit_exit(self, reason: str) -> None:
        if self._exit_submitted:
            return
        if not (self._in_position or self._entry_submitted):
            return

        self._cancel_pt_limit()
        self._exit_reason = reason
        self._exit_submitted = True
        self._watching = False
        self._pb_active = False

        exit_side = OrderSide.SELL if self._dir == 1 else OrderSide.BUY
        order = self.order_factory.market(
            instrument_id=self._inst_id,
            order_side=exit_side,
            quantity=Quantity.from_int(self._cfg.trade_size),
            time_in_force=TimeInForce.GTC,
            reduce_only=True,
        )
        self._exit_order_id = order.client_order_id.value
        self.submit_order(order)

    # ── Fill events ───────────────────────────────────────────────────────────

    def on_order_filled(self, event) -> None:
        cid = event.client_order_id.value

        if cid == self._entry_order_id:
            self._entry_px = float(event.last_px)
            self._entry_ts = int(event.ts_event)
            self._sl_px = self._pb_sl
            self._in_position = True
            self._entry_submitted = False
            self._cur_mfe = 0.0
            self._cur_mae = 0.0
            
            # Retroactively replay buffered 1s bars since entry fill time
            atr = self._atr_base
            if atr > 0:
                for hist_bar in self._recent_1s_bars:
                    if int(hist_bar.ts_init) >= self._entry_ts:
                        h = float(hist_bar.high)
                        l = float(hist_bar.low)
                        if self._dir == 1:
                            self._cur_mfe = max(self._cur_mfe, (h - self._entry_px) / atr)
                            self._cur_mae = max(self._cur_mae, (self._entry_px - l) / atr)
                        else:
                            self._cur_mfe = max(self._cur_mfe, (self._entry_px - l) / atr)
                            self._cur_mae = max(self._cur_mae, (h - self._entry_px) / atr)

            # Submit GTC LIMIT at +0.5 ATR — mirrors offline study PT mechanic
            tick = 0.25
            pt_raw = self._entry_px + 0.5 * self._atr_base * self._dir
            self._pt05_px = round(pt_raw / tick) * tick
            pt_side = OrderSide.SELL if self._dir == 1 else OrderSide.BUY
            pt_order = self.order_factory.limit(
                instrument_id=self._inst_id,
                order_side=pt_side,
                quantity=Quantity.from_int(self._cfg.trade_size),
                price=Price(self._pt05_px, precision=2),
                time_in_force=TimeInForce.GTC,
                reduce_only=True,
            )
            self._pt_order_id = pt_order.client_order_id.value
            self.submit_order(pt_order)
            self.log.info(
                f"ENTRY dir={self._dir} px={self._entry_px:.2f} "
                f"sl={self._sl_px:.2f} pt={self._pt05_px:.2f} atr={self._atr_base:.2f}"
            )

        elif cid == self._pt_order_id:
            exit_px = float(event.last_px)
            exit_ts = int(event.ts_event)
            
            # Update MFE/MAE with final exit price
            atr = self._atr_base
            if atr > 0:
                if self._dir == 1:
                    self._cur_mfe = max(self._cur_mfe, (exit_px - self._entry_px) / atr)
                    self._cur_mae = max(self._cur_mae, (self._entry_px - exit_px) / atr)
                else:
                    self._cur_mfe = max(self._cur_mfe, (self._entry_px - exit_px) / atr)
                    self._cur_mae = max(self._cur_mae, (exit_px - self._entry_px) / atr)

            pnl = (exit_px - self._entry_px) * self._dir * MULT - COMM
            hold_s = (exit_ts - self._entry_ts) / 1e9
            self.trade_log.append({
                "regime_start_ts": self._rs_ts,
                "direction":  self._dir,
                "atr_base":   self._atr_base,
                "entry_ts":   self._entry_ts,
                "entry_px":   self._entry_px,
                "exit_ts":    exit_ts,
                "exit_px":    exit_px,
                "exit_reason": "pt05",
                "hold_s":     hold_s,
                "pnl":        pnl,
                "mfe_atr":    self._cur_mfe,
                "mae_atr":    self._cur_mae,
            })
            self._watching = False   # one trade per regime; no re-entry after PT
            self._in_position = False
            self._pt_order_id = None
            self._entry_order_id = None
            self._pb_active = False
            self._pb_sl = 0.0
            self.log.info(
                f"EXIT reason=pt05 px={exit_px:.2f} "
                f"pnl={pnl:.0f} hold={hold_s/60:.1f}min"
            )

        elif cid == self._exit_order_id:
            exit_px = float(event.last_px)
            exit_ts = int(event.ts_event)
            
            # Update MFE/MAE with final exit price
            atr = self._atr_base
            if atr > 0:
                if self._dir == 1:
                    self._cur_mfe = max(self._cur_mfe, (exit_px - self._entry_px) / atr)
                    self._cur_mae = max(self._cur_mae, (self._entry_px - exit_px) / atr)
                else:
                    self._cur_mfe = max(self._cur_mfe, (self._entry_px - exit_px) / atr)
                    self._cur_mae = max(self._cur_mae, (exit_px - self._entry_px) / atr)

            pnl = (exit_px - self._entry_px) * self._dir * MULT - COMM
            hold_s = (exit_ts - self._entry_ts) / 1e9
            self.trade_log.append({
                "regime_start_ts": self._rs_ts,
                "direction":  self._dir,
                "atr_base":   self._atr_base,
                "entry_ts":   self._entry_ts,
                "entry_px":   self._entry_px,
                "exit_ts":    exit_ts,
                "exit_px":    exit_px,
                "exit_reason": self._exit_reason,
                "hold_s":     hold_s,
                "pnl":        pnl,
                "mfe_atr":    self._cur_mfe,
                "mae_atr":    self._cur_mae,
            })
            self._in_position = False
            self._exit_submitted = False
            self._entry_order_id = None
            self._exit_order_id = None
            self._pb_active = False
            self._pb_sl = 0.0
            self.log.info(
                f"EXIT reason={self._exit_reason} px={exit_px:.2f} "
                f"pnl={pnl:.0f} hold={hold_s/60:.1f}min"
            )

    def on_order_rejected(self, event) -> None:
        self.log.warning(f"Order rejected: {event}")

    def on_stop(self) -> None:
        self.log.info(
            f"Strategy done. trades={len(self.trade_log)} "
            f"depth={self._cfg.depth}"
        )
