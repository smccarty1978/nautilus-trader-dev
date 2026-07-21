"""Pullback DNA Atlas Collector.

NT event-driven strategy that records the complete lifecycle of every
qualifying pullback within top-health regimes (hC >= 0.50, Healthy /
HH-HardStall, bar 8 complete).

Supports multiple pullbacks per regime. After an SL exit within a
regime, the strategy requires a new running-extreme peak before
resuming pullback detection, preventing immediate re-entry at a broken
structural low.

One observation per completed entry-to-exit cycle. The obs_log is the
output; post-processing (analyze.py) re-joins with 1s catalog bars to
build trajectory-level metrics and the transition atlas.

Usage:
    Via run_collector.py using BacktestEngine.
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
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Quantity
from nautilus_trader.trading.strategy import Strategy

from collectors.collector_v2.aggregator import TimeframeAggregator, _OpenBucket

# ── Constants (must match existing strategy exactly) ──────────────────────────
MULT        = 20.0
COMM        = 4.06
NS_PER_MIN  = 60_000_000_000
IS_STALL_P33 = 0.044
IS_STALL_P67 = 0.304

# Lifecycle checkpoints (ATR multiples from entry)
CHECKPOINTS = [0.25, 0.50, 1.00, 1.50, 2.00]
CK_KEYS     = [f"{int(c * 100):03d}" for c in CHECKPOINTS]   # 025, 050, 100, 150, 200


def _state_cat(hc_val: float, state_raw: str) -> str:
    """Exact copy from strategies/pullback_5s/strategy.py."""
    if state_raw == "Healthy":
        return "Healthy"
    if state_raw == "DETER":
        return "DETER"
    if state_raw in ("HardStall", "SoftStall"):
        if hc_val >= IS_STALL_P67:
            return "HH-HardStall"
        if hc_val >= IS_STALL_P33:
            return "MH-HardStall"
        return "LH-HardStall"
    return "Other"


# ── Regime engine (extended to expose EMA values) ─────────────────────────────

class _RegimeEngine:
    """Exact _LiteRegimeEngine logic plus EMA property access for context snapshots."""

    ALPHA3 = 2.0 / (3 + 1)
    ALPHA9 = 2.0 / (9 + 1)
    ATR_PERIOD = 14

    def __init__(self) -> None:
        self._ema3_h: Optional[float] = None
        self._ema9_h: Optional[float] = None
        self._ema3_l: Optional[float] = None
        self._ema9_l: Optional[float] = None
        self._prev_close: Optional[float] = None
        self._atr_warmup: list[float] = []
        self._atr: Optional[float] = None
        self.regime: int = 0
        self.bars_in_regime: int = 0

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def atr(self) -> Optional[float]:
        return self._atr

    @property
    def ema3_h(self) -> Optional[float]:
        return self._ema3_h

    @property
    def ema9_h(self) -> Optional[float]:
        return self._ema9_h

    @property
    def ema3_l(self) -> Optional[float]:
        return self._ema3_l

    @property
    def ema9_l(self) -> Optional[float]:
        return self._ema9_l

    # ── Update ────────────────────────────────────────────────────────────────

    def update(self, bucket: _OpenBucket) -> None:
        h, l, c = bucket.high, bucket.low, bucket.close

        # EMA3 / EMA9 of bar H and L
        if self._ema3_h is None:
            self._ema3_h = h;  self._ema9_h = h
            self._ema3_l = l;  self._ema9_l = l
        else:
            a3, a9 = self.ALPHA3, self.ALPHA9
            self._ema3_h = a3 * h + (1 - a3) * self._ema3_h
            self._ema9_h = a9 * h + (1 - a9) * self._ema9_h
            self._ema3_l = a3 * l + (1 - a3) * self._ema3_l
            self._ema9_l = a9 * l + (1 - a9) * self._ema9_l

        # Wilder ATR(14) — exact match to _LiteRegimeEngine
        tr = (h - l) if self._prev_close is None else max(
            h - l, abs(h - self._prev_close), abs(l - self._prev_close)
        )
        self._prev_close = c
        if self._atr is None:
            self._atr_warmup.append(tr)
            if len(self._atr_warmup) == self.ATR_PERIOD:
                self._atr = sum(self._atr_warmup) / self.ATR_PERIOD
                self._atr_warmup = []
        else:
            self._atr = (self._atr * (self.ATR_PERIOD - 1) + tr) / self.ATR_PERIOD

        # Regime detection (sticky — indeterminate does not change regime)
        new = self.regime
        if c > self._ema3_h and c > self._ema9_h:
            new = 1
        elif c < self._ema3_l and c < self._ema9_l:
            new = -1

        if new != 0 and new != self.regime:
            self.bars_in_regime = 1
            self.regime = new
        elif new != 0:
            self.bars_in_regime += 1


# ── Config ────────────────────────────────────────────────────────────────────

class PullbackDNAConfig(StrategyConfig, frozen=True):
    instrument_id: str = "NQ.XCME"
    bar_type_1s: str  = "NQ.XCME-1-SECOND-LAST-EXTERNAL"
    depth: float      = 0.25    # ATR pullback depth threshold to trigger entry
    hc_floor: float   = 0.50
    trade_size: int   = 1
    hc_mapping_path: str = (
        "collectors/collector_v2/results/combined_arch/hc_perbar_mapping.parquet"
    )


# ── Collector strategy ────────────────────────────────────────────────────────

class PullbackDNACollector(Strategy):
    """Records every qualifying pullback lifecycle for the DNA atlas.

    Multiple pullbacks per regime are allowed. After an SL exit,
    _need_new_peak = True until the running extreme is surpassed again.
    """

    def __init__(self, cfg: PullbackDNAConfig) -> None:
        super().__init__(cfg)
        self._cfg = cfg

    def on_start(self) -> None:
        self._inst_id = InstrumentId.from_str(self._cfg.instrument_id)

        # hC walk-forward mapping
        p = Path(self._cfg.hc_mapping_path)
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        df = pd.read_parquet(p)
        self._hc_map: dict[tuple, tuple] = {
            (int(r.regime_start_ts), int(r.bars_in_regime)): (r.hC, r.state)
            for r in df.itertuples(index=False)
        }

        self._eng  = _RegimeEngine()
        self._agg  = TimeframeAggregator(
            on_bucket_closed=self._on_bucket_closed,
            timeframes=("1m", "5s"),
        )
        self._atr_hist: deque = deque(maxlen=60)

        # ── Regime ────────────────────────────────────────────────────────────
        self._prev_regime: int = 0
        self._in_regime:   bool = False
        self._rs_ts:       int = 0
        self._dir:         int = 0
        self._atr_base:    float = 0.0
        self._hC_val:      float = float("nan")
        self._hC_vel:      float = float("nan")
        self._state_str:   str = ""
        self._run_ext:     float = 0.0
        self._peak_ts:     int = 0   # ts of last run_ext update

        # ── Per-regime pullback state ──────────────────────────────────────────
        self._watching:      bool = False
        self._pb_count:      int = 0         # completed pullbacks in this regime
        self._need_new_peak: bool = False    # True after SL exit, until new peak

        # ── Active pullback ────────────────────────────────────────────────────
        self._pb_active:           bool  = False
        self._pb_sl:               float = 0.0
        self._pb_start_ts:         int   = 0
        self._pb_depth_at_trigger: float = 0.0

        # ── Order / position ───────────────────────────────────────────────────
        self._entry_submitted: bool = False
        self._in_position:     bool = False
        self._exit_submitted:  bool = False
        self._entry_oid:       Optional[str] = None
        self._exit_oid:        Optional[str] = None
        self._entry_px:        float = 0.0
        self._entry_ts:        int   = 0
        self._sl_px:           float = 0.0
        self._exit_reason:     str   = ""

        # ── Active observation ─────────────────────────────────────────────────
        self._obs: Optional[dict] = None

        # ── Output ────────────────────────────────────────────────────────────
        self.obs_log: list[dict] = []

        self.subscribe_bars(BarType.from_str(self._cfg.bar_type_1s))

    # ── 1s bar handler ────────────────────────────────────────────────────────

    def on_bar(self, bar: Bar) -> None:
        # Feed aggregator with ts_init — matches capsule builder convention
        self._agg.on_1s_bar(
            int(bar.ts_init),
            float(bar.open), float(bar.high), float(bar.low),
            float(bar.close), float(bar.volume),
        )

        # Lifecycle tracking for the current open observation
        if not (self._in_position and self._obs is not None):
            return

        h   = float(bar.high)
        l   = float(bar.low)
        ts  = int(bar.ts_init)          # bar close time (NOTE-A: ts_init not ts_event)
        d   = self._obs["direction"]    # snapshot at entry fill; immune to dir flip (W-FLIP)
        atr = self._atr_base
        px  = self._entry_px
        obs = self._obs

        if atr <= 0:
            return

        # MFE / MAE from entry (in ATR units, using 1s bar extremes)
        mfe = (h - px) / atr if d == 1 else (px - l) / atr
        mae = (px - l) / atr if d == 1 else (h - px) / atr
        obs["max_mfe_atr"] = max(obs["max_mfe_atr"], mfe)
        obs["max_mae_atr"] = max(obs["max_mae_atr"], mae)

        # Checkpoint flags: first time MFE reaches each multiple
        for ck, key in zip(CHECKPOINTS, CK_KEYS):
            dk = f"did_{key}"
            if not obs[dk] and mfe >= ck:
                obs[dk] = True
                obs[f"ts_{key}"] = ts

        # Retracement events (only tracked after first reaching +0.50 ATR)
        if obs["did_050"]:
            if (d == 1 and l <= px) or (d == -1 and h >= px):
                obs["after_050_revisit_entry"] = True
            if (d == 1 and l <= self._sl_px) or (d == -1 and h >= self._sl_px):
                obs["after_050_revisit_sl"] = True

    # ── Aggregator callbacks ───────────────────────────────────────────────────

    def _on_bucket_closed(self, tf: str, bucket: _OpenBucket) -> None:
        if tf == "1m":
            self._on_1m_close(bucket)
        elif tf == "5s":
            self._on_5s_close(bucket)

    # ── 1m: regime engine + flip detection + bar-8 qualification ──────────────

    def _on_1m_close(self, bucket: _OpenBucket) -> None:
        prev = self._prev_regime
        self._eng.update(bucket)
        cur = self._eng.regime

        atr_now = self._eng.atr
        if atr_now and atr_now > 0:
            self._atr_hist.append(atr_now)

        flipped = (cur != prev and cur != 0 and prev != 0)

        if flipped:
            # Exit any open position before switching regime context
            if self._in_position or self._entry_submitted:
                self._submit_exit("regime_flip")

            # Seed new regime
            self._in_regime = True
            self._rs_ts     = bucket.close_ts
            self._dir       = cur
            cur_atr = atr_now if (atr_now and atr_now > 0) else 1.0
            roll    = sum(self._atr_hist) / len(self._atr_hist) if self._atr_hist else cur_atr
            self._atr_base  = max(cur_atr, 0.5 * roll)
            self._run_ext   = bucket.close
            self._peak_ts   = bucket.close_ts

            # Reset per-regime state
            self._watching       = False
            self._pb_count       = 0
            self._need_new_peak  = False
            self._pb_active      = False
            self._pb_sl          = 0.0
            self._hC_val         = float("nan")
            self._hC_vel         = float("nan")
            self._state_str      = ""

        elif cur != 0 and self._in_regime:
            # Keep run_ext current with 1m closes between pullbacks
            if cur == 1 and bucket.close > self._run_ext:
                self._run_ext = bucket.close
                self._peak_ts = bucket.close_ts
            elif cur == -1 and bucket.close < self._run_ext:
                self._run_ext = bucket.close
                self._peak_ts = bucket.close_ts

        # Bar-8 qualification (bars_in_regime == 9 → bar k=8 just closed)
        if (cur != 0 and not self._watching
                and not self._in_position and not self._entry_submitted
                and self._eng.bars_in_regime == 9
                and self._rs_ts > 0 and self._eng.atr is not None):
            e9 = self._hc_map.get((self._rs_ts, 9))
            if e9 is not None:
                hc9, state_raw = e9
                if not math.isnan(hc9) and hc9 >= self._cfg.hc_floor:
                    sc = _state_cat(hc9, state_raw)
                    if sc in ("Healthy", "HH-HardStall"):
                        # hC velocity: delta from bar 7 → bar 8
                        e7  = self._hc_map.get((self._rs_ts, 8))   # bars_in_regime=8 → k=7
                        vel = (hc9 - e7[0]) if (e7 and not math.isnan(e7[0])) else float("nan")
                        self._hC_val    = hc9
                        self._hC_vel    = vel
                        self._state_str = sc
                        self._watching  = True

        self._prev_regime = cur

    # ── 5s: run_ext tracking, pullback detection, SL monitoring ───────────────

    def _on_5s_close(self, bucket: _OpenBucket) -> None:
        if not self._in_regime and not self._in_position:
            return

        ts  = bucket.close_ts
        c   = bucket.close
        o   = bucket.open
        d   = self._dir
        atr = self._atr_base

        # Update running extreme (tracks regime high for long / low for short)
        if self._in_regime:
            if d == 1:
                if c > self._run_ext:
                    self._run_ext = c
                    self._peak_ts = ts
                    # New peak clears the post-SL wait flag
                    if self._need_new_peak:
                        self._need_new_peak = False
                        self._pb_active = False
                        self._pb_sl = 0.0
            elif d == -1:
                if c < self._run_ext:
                    self._run_ext = c
                    self._peak_ts = ts
                    if self._need_new_peak:
                        self._need_new_peak = False
                        self._pb_active = False
                        self._pb_sl = 0.0

        # SL close-based check for open position
        if self._in_position and not self._exit_submitted:
            if (d == 1 and c < self._sl_px) or (d == -1 and c > self._sl_px):
                self._submit_exit("sl")
                return

        # Skip pullback logic while in position / pending fill / not watching
        if not self._watching or self._in_position or self._entry_submitted:
            return
        if self._need_new_peak or atr <= 0:
            return

        # Pullback depth from current running extreme
        pb_depth = (self._run_ext - c) / atr if d == 1 else (c - self._run_ext) / atr

        if pb_depth > 0:
            # Accumulate structural SL (deepest 5s close during pullback)
            if not self._pb_active:
                self._pb_active   = True
                self._pb_sl       = c
                self._pb_start_ts = ts
            else:
                if (d == 1 and c < self._pb_sl) or (d == -1 and c > self._pb_sl):
                    self._pb_sl = c
        else:
            # At or above running extreme — reset pullback state
            self._pb_active   = False
            self._pb_sl       = 0.0
            self._pb_start_ts = 0

        # Entry trigger: up-close bar after depth threshold
        if (self._pb_active
                and pb_depth >= self._cfg.depth
                and ((d == 1 and c > o) or (d == -1 and c < o))):
            self._pb_depth_at_trigger = pb_depth
            self._submit_entry()

    # ── Order submission ──────────────────────────────────────────────────────

    def _submit_entry(self) -> None:
        if self._entry_submitted or self._in_position:
            return
        side = OrderSide.BUY if self._dir == 1 else OrderSide.SELL
        o = self.order_factory.market(
            instrument_id=self._inst_id,
            order_side=side,
            quantity=Quantity.from_int(self._cfg.trade_size),
            time_in_force=TimeInForce.GTC,
        )
        self._entry_oid       = o.client_order_id.value
        self._entry_submitted = True
        self.submit_order(o)

    def _submit_exit(self, reason: str) -> None:
        if self._exit_submitted:
            return
        if not (self._in_position or self._entry_submitted):
            return
        self._exit_reason    = reason
        self._exit_submitted = True
        side = OrderSide.SELL if self._dir == 1 else OrderSide.BUY
        o = self.order_factory.market(
            instrument_id=self._inst_id,
            order_side=side,
            quantity=Quantity.from_int(self._cfg.trade_size),
            time_in_force=TimeInForce.GTC,
            reduce_only=True,
        )
        self._exit_oid = o.client_order_id.value
        self.submit_order(o)

    # ── Fill events ───────────────────────────────────────────────────────────

    def on_order_filled(self, event) -> None:
        cid = event.client_order_id.value

        if cid == self._entry_oid:
            self._entry_px        = float(event.last_px)
            self._entry_ts        = int(event.ts_event)
            self._sl_px           = self._pb_sl
            self._in_position     = True
            self._entry_submitted = False

            # Build context snapshot at fill time
            atr = self._atr_base
            d   = self._dir
            e3  = self._eng.ema3_h if d == 1 else self._eng.ema3_l
            e9  = self._eng.ema9_h if d == 1 else self._eng.ema9_l
            ema3_dist = (d * (self._entry_px - e3) / atr
                         if (e3 is not None and atr > 0) else float("nan"))
            ema9_dist = (d * (self._entry_px - e9) / atr
                         if (e9 is not None and atr > 0) else float("nan"))
            sl_risk   = abs(self._entry_px - self._sl_px) / atr if atr > 0 else float("nan")
            bir       = (self._entry_ts - self._rs_ts) // NS_PER_MIN

            atr_pct = float("nan")
            if self._atr_hist:
                hist    = list(self._atr_hist)
                atr_pct = sum(1 for a in hist if a <= atr) / len(hist)

            self._pb_count += 1

            self._obs = {
                # Identity
                "regime_start_ts":  self._rs_ts,
                "pullback_id":      self._pb_count,
                "direction":        d,
                # Entry
                "entry_ts":         self._entry_ts,
                "entry_px":         self._entry_px,
                "sl_px":            self._sl_px,
                "atr_base":         atr,
                "hC":               self._hC_val,
                "hC_velocity":      self._hC_vel,
                "state":            self._state_str,
                "bars_into_regime": bir,
                "regime_age_s":     (self._entry_ts - self._rs_ts) / 1e9,
                "pb_depth_atr":     self._pb_depth_at_trigger,
                "pb_duration_s":    (self._entry_ts - self._pb_start_ts) / 1e9,
                "peak_px":          self._run_ext,
                "sl_risk_atr":      sl_risk,
                "ema3_dist_atr":    ema3_dist,
                "ema9_dist_atr":    ema9_dist,
                "atr_pct":          atr_pct,
                # Checkpoints (did_025, ts_025, did_050, ts_050, ...)
                **{f"did_{k}": False for k in CK_KEYS},
                **{f"ts_{k}":  None  for k in CK_KEYS},
                # Retracement flags (only set after did_050 = True)
                "after_050_revisit_entry": False,
                "after_050_revisit_sl":    False,
                # Excursion (updated on every 1s bar in on_bar)
                "max_mfe_atr": 0.0,
                "max_mae_atr": 0.0,
                # Exit (filled in on_order_filled exit branch)
                "exit_ts":     None,
                "exit_px":     None,
                "exit_reason": None,
                "hold_s":      None,
                "pnl":         None,
            }

        elif cid == self._exit_oid:
            exit_px = float(event.last_px)
            exit_ts = int(event.ts_event)
            hold_s  = (exit_ts - self._entry_ts) / 1e9

            if self._obs is not None:
                # Use obs["direction"] (entry direction), NOT self._dir: for regime_flip
                # exits self._dir is already updated to the NEW direction before fill.
                pnl = (exit_px - self._entry_px) * self._obs["direction"] * MULT - COMM
                self._obs.update({
                    "exit_ts":     exit_ts,
                    "exit_px":     exit_px,
                    "exit_reason": self._exit_reason,
                    "hold_s":      hold_s,
                    "pnl":         pnl,
                })
                self.obs_log.append(self._obs)
                self.log.info(
                    f"PB#{self._pb_count} dir={self._dir} "
                    f"rsn={self._exit_reason} pnl={pnl:.0f} "
                    f"mfe={self._obs['max_mfe_atr']:.2f}A "
                    f"mae={self._obs['max_mae_atr']:.2f}A "
                    f"hold={hold_s/60:.1f}min"
                )

            self._in_position    = False
            self._exit_submitted = False
            self._entry_oid      = None
            self._exit_oid       = None
            self._obs            = None
            self._pb_active      = False
            self._pb_sl          = 0.0

            # After SL: require a new running-extreme peak before next pullback
            if self._exit_reason == "sl":
                self._need_new_peak = True

    def on_order_rejected(self, event) -> None:
        self.log.warning(f"Order rejected: {event}")

    def on_stop(self) -> None:
        self.log.info(
            f"Collector done. observations={len(self.obs_log)} depth={self._cfg.depth}"
        )
