"""1m Regime Flip Study — Flip Bar Size + HH/LL Trailing Exit.

Enter on EVERY 1m regime flip at bar+1 open. Track flip bar metrics,
HH/LL exit thresholds, and 1s MFE/MAE simultaneously. No filters at
collection time.

All computation inside NT event loop. No lookahead.
"""

import sys
import os
from pathlib import Path
from collections import deque

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd
import pytz

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.trading.strategy import Strategy

from indicators.regime.indicator_v2 import RegimeIndicatorsV2

NQ_MULTIPLIER = 20.0
COMMISSION = 5.0
CT = pytz.timezone("America/Chicago")


def _safe_div(a, b, default=0.0):
    return a / b if b != 0 else default


# =========================================================================
# PathTracker — 1s MFE/MAE
# =========================================================================

class PathTracker:
    MFE_LEVELS = [0.25, 0.50, 0.75, 1.00, 1.25, 1.50]
    MAE_LEVELS = [0.25, 0.50, 0.75, 1.00, 1.25]
    TIME_SNAPSHOTS = [30, 60, 120, 300, 600]

    def __init__(self):
        self._active = False
        self.entry_price = 0.0
        self.direction = 0
        self.atr = 0.0
        self.entry_ts = 0
        self.peak_mfe = 0.0
        self.peak_mae = 0.0
        self.mae_at_peak_mfe = 0.0
        self.mfe_at_peak_mae = 0.0
        self.bar_count = 0
        self.mfe_first = None
        self.mfe_milestones = {}
        self.mae_milestones = {}
        self.time_snapshots = {}
        self._snap_set = set()

    def start(self, ep, d, atr, ts):
        self._active = True
        self.entry_price = ep
        self.direction = d
        self.atr = atr
        self.entry_ts = ts
        self.peak_mfe = 0.0
        self.peak_mae = 0.0
        self.mae_at_peak_mfe = 0.0
        self.mfe_at_peak_mae = 0.0
        self.bar_count = 0
        self.mfe_first = None
        self.mfe_milestones = {}
        self.mae_milestones = {}
        self.time_snapshots = {}
        self._snap_set = set()

    def update(self, bar):
        if not self._active or self.atr <= 0:
            return
        h, l = float(bar.high), float(bar.low)
        self.bar_count += 1
        if self.direction == 1:
            mfe_c = (h - self.entry_price) / self.atr
            mae_c = (self.entry_price - l) / self.atr
        else:
            mfe_c = (self.entry_price - l) / self.atr
            mae_c = (h - self.entry_price) / self.atr
        if mfe_c > self.peak_mfe:
            self.peak_mfe = mfe_c
            self.mae_at_peak_mfe = self.peak_mae
        if mae_c > self.peak_mae:
            self.peak_mae = mae_c
            self.mfe_at_peak_mae = self.peak_mfe
        if self.mfe_first is None:
            if self.peak_mfe >= 0.25 and self.peak_mae < 0.25:
                self.mfe_first = 1
            elif self.peak_mae >= 0.25 and self.peak_mfe < 0.25:
                self.mfe_first = 0
            elif self.peak_mfe >= 0.25 and self.peak_mae >= 0.25:
                self.mfe_first = 0
        for lv in self.MFE_LEVELS:
            if lv not in self.mfe_milestones and self.peak_mfe >= lv:
                self.mfe_milestones[lv] = self.bar_count
        for lv in self.MAE_LEVELS:
            if lv not in self.mae_milestones and self.peak_mae >= lv:
                self.mae_milestones[lv] = self.bar_count
        elapsed = (bar.ts_event - self.entry_ts) / 1e9
        for s in self.TIME_SNAPSHOTS:
            if s not in self._snap_set and elapsed >= s:
                self.time_snapshots[s] = (self.peak_mfe, self.peak_mae)
                self._snap_set.add(s)

    def get_labels(self):
        lb = {
            "mfe_atr": self.peak_mfe, "mae_atr": self.peak_mae,
            "mae_at_peak_mfe": self.mae_at_peak_mfe,
            "mfe_at_peak_mae": self.mfe_at_peak_mae,
            "trade_duration_bars_1s": self.bar_count,
            "mfe_first": self.mfe_first if self.mfe_first is not None else 0,
            "immediate_fail": 1 if self.peak_mfe < 0.25 else 0,
        }
        for lv in self.MFE_LEVELS:
            lb[f"bars_to_{int(lv*100):03d}_mfe"] = self.mfe_milestones.get(lv)
        for lv in self.MAE_LEVELS:
            lb[f"bars_to_{int(lv*100):03d}_mae"] = self.mae_milestones.get(lv)
        for s in self.TIME_SNAPSHOTS:
            m, a = self.time_snapshots.get(s, (None, None))
            lb[f"mfe_at_{s}s"] = m
            lb[f"mae_at_{s}s"] = a
        return lb


# =========================================================================
# Config
# =========================================================================

class FlipStudyConfig(StrategyConfig, frozen=True):
    instrument_id: str = "NQ.XCME"
    bar_type_1m: str = "NQ.XCME-1-MINUTE-LAST-EXTERNAL"
    bar_type_1s: str = "NQ.XCME-1-SECOND-LAST-EXTERNAL"


# =========================================================================
# Collector
# =========================================================================

class FlipStudyCollector(Strategy):
    """Enter every regime flip at bar+1 open. Track flip bar metrics,
    HH/LL exits, and 1s MFE/MAE. One trade at a time (close+reverse)."""

    def __init__(self, config: FlipStudyConfig):
        super().__init__(config)
        self._inst_id = InstrumentId.from_str(config.instrument_id)

        self.regime = RegimeIndicatorsV2()
        self._1m_count = 0
        self._warmup = False
        self._regime = 0
        self._regime_start_bar = 0

        # Volume buffer for vol_vs_20avg
        self._vol_buf = deque(maxlen=20)
        # EMA slope buffer
        self._ema3_buf = deque(maxlen=6)

        # Flip pending entry
        self._flip_pending = None  # dict with flip bar info
        self._in_position = False

        # Current trade tracking
        self._trade = None
        self._path = PathTracker()

        # HH/LL tracking
        self._prev_extreme = 0.0  # prev_high (bull) or prev_low (bear)
        self._consec_no_hh = 0
        self._hh_count = 0
        self._max_consec_no_hh = 0
        self._bar_count_1m = 0
        self._hh_exits = {}  # threshold -> (bar, price, pnl_pts)

        # Results
        self._results = []
        self._trade_counter = 0
        self._diag = {"flips": 0, "trades": 0}

    def on_start(self):
        self._bt_1m = BarType.from_str(self.config.bar_type_1m)
        self._bt_1s = BarType.from_str(self.config.bar_type_1s)
        self.subscribe_bars(self._bt_1s)
        self.subscribe_bars(self._bt_1m)

    def on_bar(self, bar: Bar):
        if bar.bar_type == self._bt_1m:
            self._on_1m(bar)
        elif bar.bar_type == self._bt_1s:
            self._on_1s(bar)

    # ---- 1s: MFE/MAE tracking ----

    def _on_1s(self, bar: Bar):
        if self._in_position:
            self._path.update(bar)

    # ---- 1m: regime detection, entry, HH tracking ----

    def _on_1m(self, bar: Bar):
        self.regime.update(bar)
        self._1m_count += 1

        close = float(bar.close)
        high = float(bar.high)
        low = float(bar.low)
        open_ = float(bar.open)
        vol = float(bar.volume) if hasattr(bar, "volume") else 0.0

        atr = (self.regime.atr.value
               if self.regime.atr.initialized else 1e-9)

        self._vol_buf.append(vol)
        if self.regime.short_ema_close.initialized:
            self._ema3_buf.append(self.regime.short_ema_close.value)

        # Regime detection
        eh3 = self.regime.short_ema_high.value
        eh9 = self.regime.long_ema_high.value
        el3 = self.regime.short_ema_low.value
        el9 = self.regime.long_ema_low.value
        new_r = self._regime
        if close > eh3 and close > eh9:
            new_r = 1
        elif close < el3 and close < el9:
            new_r = -1

        # Warmup
        if not self._warmup:
            self._warmup = (
                self.regime.is_warmed_up
                and self._1m_count >= 60)
            if not self._warmup:
                self._regime = new_r
                if self._regime != 0:
                    self._regime_start_bar = self._1m_count
                return

        # ---- Handle pending entry (bar+1 open after flip) ----
        if self._flip_pending is not None:
            self._enter_trade(bar, atr)

        # ---- HH/LL tracking for current trade ----
        if self._in_position and self._trade is not None:
            self._update_hh(bar)

        # ---- Check for regime flip ----
        if (new_r != self._regime and self._regime != 0 and new_r != 0):
            self._diag["flips"] += 1

            # Close current trade if in position
            if self._in_position:
                self._close_trade(bar, atr)

            # Record flip info for bar+1 entry
            bar_range = high - low
            self._flip_pending = {
                "flip_time": pd.Timestamp(
                    bar.ts_event, unit="ns", tz="UTC"),
                "direction": new_r,
                "flip_bar_high": high,
                "flip_bar_low": low,
                "flip_bar_open": open_,
                "flip_bar_close": close,
                "flip_bar_volume": vol,
                "flip_bar_range": bar_range,
                "flip_bar_range_atr": bar_range / atr if atr > 0 else 0,
                "flip_bar_body": abs(close - open_),
                "flip_bar_body_pct": (
                    abs(close - open_) / bar_range
                    if bar_range > 0 else 0),
                "flip_bar_direction": 1 if close > open_ else -1,
                "flip_bar_close_location": (
                    (close - low) / bar_range if bar_range > 0 else 0.5),
                "flip_bar_upper_wick_pct": (
                    (high - max(open_, close)) / bar_range
                    if bar_range > 0 else 0),
                "flip_bar_lower_wick_pct": (
                    (min(open_, close) - low) / bar_range
                    if bar_range > 0 else 0),
                "flip_bar_vol_vs_20avg": _safe_div(
                    vol, np.mean(list(self._vol_buf)) if self._vol_buf else 1),
                "prior_regime_duration": (
                    self._1m_count - self._regime_start_bar),
                "atr_at_flip": atr,
                # EMA features at flip time
                "ema3_slope": (
                    (self._ema3_buf[-1] - self._ema3_buf[-6]) / atr
                    if len(self._ema3_buf) >= 6 else float("nan")),
                "ema_spread": _safe_div(eh3 - el3, atr),
                "ema3_ema9_spread": _safe_div(
                    self.regime.short_ema_close.value -
                    self.regime.long_ema_close.value, atr)
                if self.regime.short_ema_close.initialized else float("nan"),
            }

            self._regime_start_bar = self._1m_count

        self._regime = new_r

    # ---- Entry on bar+1 open ----

    def _enter_trade(self, bar, atr):
        fp = self._flip_pending
        self._flip_pending = None

        entry_price = float(bar.open)
        direction = fp["direction"]
        ts = bar.ts_event

        dt_ct = pd.Timestamp(ts, unit="ns", tz="UTC").astimezone(CT)
        ct_min = dt_ct.hour * 60 + dt_ct.minute

        self._trade_counter += 1

        self._trade = {
            "trade_id": self._trade_counter,
            "entry_price": entry_price,
            "entry_ts": ts,
            "entry_time": pd.Timestamp(ts, unit="ns", tz="UTC"),
            "direction": direction,
            "atr_at_entry": fp["atr_at_flip"],
            # Flip bar features
            "flip_time": fp["flip_time"],
            "flip_bar_range_atr": fp["flip_bar_range_atr"],
            "flip_bar_body_pct": fp["flip_bar_body_pct"],
            "flip_bar_direction": fp["flip_bar_direction"],
            "flip_bar_close_location": fp["flip_bar_close_location"],
            "flip_bar_upper_wick_pct": fp["flip_bar_upper_wick_pct"],
            "flip_bar_lower_wick_pct": fp["flip_bar_lower_wick_pct"],
            "flip_bar_volume": fp["flip_bar_volume"],
            "flip_bar_vol_vs_20avg": fp["flip_bar_vol_vs_20avg"],
            # Regime context
            "prior_regime_duration": fp["prior_regime_duration"],
            "ema3_slope": fp["ema3_slope"],
            "ema_spread": fp["ema_spread"],
            "ema3_ema9_spread": fp["ema3_ema9_spread"],
            "atr_14": fp["atr_at_flip"],
            # Time
            "hour_of_day": dt_ct.hour,
            "is_rth": 1 if 510 <= ct_min < 900 else 0,
            "minutes_since_rth_open": ct_min - 510,
            "session": "RTH" if 510 <= ct_min < 900 else "ETH",
            "date": str(dt_ct.date()),
            "year": dt_ct.year,
        }

        # Initialize HH/LL tracking
        if direction == 1:
            self._prev_extreme = fp["flip_bar_high"]
        else:
            self._prev_extreme = fp["flip_bar_low"]

        self._consec_no_hh = 0
        self._hh_count = 0
        self._max_consec_no_hh = 0
        self._bar_count_1m = 0
        self._hh_exits = {}

        # Start path tracker
        self._path.start(entry_price, direction, fp["atr_at_flip"], ts)
        self._in_position = True
        self._diag["trades"] += 1

        # Bar+1 is also the entry bar — do HH check on it
        self._update_hh(bar)

        # Record bar1 check
        bar1_high = float(bar.high)
        bar1_low = float(bar.low)
        if direction == 1:
            self._trade["bar1_made_hh"] = (
                1 if bar1_high > fp["flip_bar_high"] else 0)
        else:
            self._trade["bar1_made_hh"] = (
                1 if bar1_low < fp["flip_bar_low"] else 0)

        bar1_pnl_pts = (float(bar.close) - entry_price) * direction
        self._trade["bar1_close_pnl_pts"] = bar1_pnl_pts
        self._trade["bar1_close_pnl_dollars"] = (
            bar1_pnl_pts * NQ_MULTIPLIER - COMMISSION)
        self._trade["bar1_range_atr"] = (
            (float(bar.high) - float(bar.low)) / fp["atr_at_flip"]
            if fp["atr_at_flip"] > 0 else 0)

    # ---- HH/LL update ----

    def _update_hh(self, bar):
        d = self._trade["direction"]
        self._bar_count_1m += 1

        if d == 1:
            current = float(bar.high)
            made_new = current > self._prev_extreme
        else:
            current = float(bar.low)
            made_new = current < self._prev_extreme

        if made_new:
            self._prev_extreme = current
            self._consec_no_hh = 0
            self._hh_count += 1
        else:
            self._consec_no_hh += 1

        self._max_consec_no_hh = max(
            self._max_consec_no_hh, self._consec_no_hh)

        # Record exit thresholds
        ep = self._trade["entry_price"]
        exit_price = float(bar.close)
        pnl_pts = (exit_price - ep) * d

        for thresh in [1, 2, 3]:
            if (thresh not in self._hh_exits
                    and self._consec_no_hh >= thresh):
                self._hh_exits[thresh] = {
                    "bar": self._bar_count_1m,
                    "price": exit_price,
                    "pnl_pts": pnl_pts,
                    "time": pd.Timestamp(
                        bar.ts_event, unit="ns", tz="UTC"),
                }

    # ---- Close trade ----

    def _close_trade(self, exit_bar, atr):
        if self._trade is None:
            self._in_position = False
            return

        t = self._trade
        ep = t["entry_price"]
        d = t["direction"]
        exit_price = float(exit_bar.close)
        exit_ts = exit_bar.ts_event

        regime_pnl_pts = (exit_price - ep) * d
        regime_pnl_dollars = regime_pnl_pts * NQ_MULTIPLIER - COMMISSION
        dur_bars = self._bar_count_1m
        dur_s = (exit_ts - t["entry_ts"]) / 1e9

        # Regime exit labels
        t["exit_time"] = pd.Timestamp(exit_ts, unit="ns", tz="UTC")
        t["exit_price"] = exit_price
        t["regime_pnl_pts"] = regime_pnl_pts
        t["regime_pnl_dollars"] = regime_pnl_dollars
        t["regime_duration_bars"] = dur_bars
        t["regime_duration_seconds"] = dur_s

        # HH exit labels
        for thresh in [1, 2, 3]:
            key = f"hh_exit_{thresh}"
            if thresh in self._hh_exits:
                ex = self._hh_exits[thresh]
                t[f"{key}_bar"] = ex["bar"]
                t[f"{key}_price"] = ex["price"]
                t[f"{key}_pnl_pts"] = ex["pnl_pts"]
                t[f"{key}_pnl_dollars"] = (
                    ex["pnl_pts"] * NQ_MULTIPLIER - COMMISSION)
                t[f"{key}_time"] = ex["time"]
            else:
                # HH every bar — never triggered
                t[f"{key}_bar"] = None
                t[f"{key}_price"] = None
                t[f"{key}_pnl_pts"] = None
                t[f"{key}_pnl_dollars"] = None
                t[f"{key}_time"] = None

        t["total_hh_count"] = self._hh_count
        t["max_consecutive_no_hh"] = self._max_consec_no_hh

        # Combined strategy labels
        bar1_hh = t.get("bar1_made_hh", 0)
        bar1_pnl = t.get("bar1_close_pnl_dollars", 0)
        for thresh in [1, 2, 3]:
            hh_pnl = t.get(f"hh_exit_{thresh}_pnl_dollars")
            if bar1_hh == 0:
                combined = bar1_pnl
            else:
                combined = hh_pnl if hh_pnl is not None else regime_pnl_dollars
            t[f"combined_bar1_hh{thresh}_pnl_dollars"] = combined

        # Path labels
        path_labels = self._path.get_labels()
        t.update(path_labels)

        self._results.append(t)
        self._trade = None
        self._in_position = False

    # ---- Cleanup ----

    def on_stop(self):
        if self._in_position and self._trade is not None:
            # Use last known state
            self._trade["exit_time"] = self._trade.get("entry_time")
            self._trade["exit_price"] = self._trade.get("entry_price", 0)
            self._trade["regime_pnl_pts"] = 0
            self._trade["regime_pnl_dollars"] = -COMMISSION
            self._trade["regime_duration_bars"] = self._bar_count_1m
            self._trade["regime_duration_seconds"] = 0
            for thresh in [1, 2, 3]:
                key = f"hh_exit_{thresh}"
                if thresh in self._hh_exits:
                    ex = self._hh_exits[thresh]
                    self._trade[f"{key}_bar"] = ex["bar"]
                    self._trade[f"{key}_price"] = ex["price"]
                    self._trade[f"{key}_pnl_pts"] = ex["pnl_pts"]
                    self._trade[f"{key}_pnl_dollars"] = (
                        ex["pnl_pts"] * NQ_MULTIPLIER - COMMISSION)
                    self._trade[f"{key}_time"] = ex["time"]
                else:
                    for sfx in ["bar", "price", "pnl_pts",
                                "pnl_dollars", "time"]:
                        self._trade[f"{key}_{sfx}"] = None
            self._trade["total_hh_count"] = self._hh_count
            self._trade["max_consecutive_no_hh"] = self._max_consec_no_hh
            for thresh in [1, 2, 3]:
                self._trade[f"combined_bar1_hh{thresh}_pnl_dollars"] = (
                    -COMMISSION)
            self._trade.update(self._path.get_labels())
            self._results.append(self._trade)

        n = len(self._results)
        print(f"\n=== REGIME FLIP STUDY COMPLETE ===")
        print(f"1m bars: {self._1m_count:,}")
        print(f"Flips: {self._diag['flips']:,}")
        print(f"Trades: {n:,}")
