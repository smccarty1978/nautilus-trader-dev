"""1m Confirmed Flip Collector — Entry at bar+1 close after HH confirmation.

Only enters when bar+1 makes a higher high (bullish) or lower low (bearish)
than the flip bar. Entry price = bar+1 close. Tracks full HH/HL/LH/LL
classification on every subsequent bar. Records all exit trigger points
simultaneously (HH1/2/3 stall, first LL, 2x LL, first LH, first LH+LL,
HL break, regime exit).

Skipped flips (bar+1 did not make HH) are recorded separately with
counterfactual regime PnL.

All computation in NT event loop. No lookahead.
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

NQ_MULT = 20.0
COMMISSION = 5.0
CT = pytz.timezone("America/Chicago")


def _safe_div(a, b, default=0.0):
    return a / b if b != 0 else default


# =========================================================================
# PathTracker — 1s MFE/MAE from entry
# =========================================================================

class PathTracker:
    MFE_LEVELS = [0.25, 0.50, 0.75, 1.00, 1.25, 1.50, 2.00]
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
        self.mfe_ms = {}
        self.mae_ms = {}
        self.snaps = {}
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
        self.mfe_ms = {}
        self.mae_ms = {}
        self.snaps = {}
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
            if lv not in self.mfe_ms and self.peak_mfe >= lv:
                self.mfe_ms[lv] = self.bar_count
        for lv in self.MAE_LEVELS:
            if lv not in self.mae_ms and self.peak_mae >= lv:
                self.mae_ms[lv] = self.bar_count
        elapsed = (bar.ts_event - self.entry_ts) / 1e9
        for s in self.TIME_SNAPSHOTS:
            if s not in self._snap_set and elapsed >= s:
                self.snaps[s] = (self.peak_mfe, self.peak_mae)
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
            lb[f"bars_to_{int(lv*100):03d}_mfe"] = self.mfe_ms.get(lv)
        for lv in self.MAE_LEVELS:
            lb[f"bars_to_{int(lv*100):03d}_mae"] = self.mae_ms.get(lv)
        for s in self.TIME_SNAPSHOTS:
            m, a = self.snaps.get(s, (None, None))
            lb[f"mfe_at_{s}s"] = m
            lb[f"mae_at_{s}s"] = a
        return lb


# =========================================================================
# Config
# =========================================================================

class ConfirmedFlipConfig(StrategyConfig, frozen=True):
    instrument_id: str = "NQ.XCME"
    bar_type_1m: str = "NQ.XCME-1-MINUTE-LAST-EXTERNAL"
    bar_type_1s: str = "NQ.XCME-1-SECOND-LAST-EXTERNAL"


# =========================================================================
# Collector
# =========================================================================

class ConfirmedFlipCollector(Strategy):
    """Enter bar+1 close after HH confirmation. Track full HH/HL/LH/LL
    classification on every subsequent bar. Record all exit trigger points.
    """

    def __init__(self, config: ConfirmedFlipConfig):
        super().__init__(config)
        self._inst_id = InstrumentId.from_str(config.instrument_id)

        self.regime = RegimeIndicatorsV2()
        self._1m_count = 0
        self._warmup = False
        self._regime = 0
        self._regime_start_bar = 0

        self._vol_buf = deque(maxlen=20)
        self._ema3_buf = deque(maxlen=6)

        # State: FLAT, AWAITING_BAR1 (flip happened, waiting for bar+1), IN_POSITION
        self._state = "FLAT"
        self._flip_pending = None  # stored after flip, used at bar+1 close
        self._trade = None
        self._path = PathTracker()

        # Per-bar classifier state (for bar+2 onward)
        self._prev_high = 0.0
        self._prev_low = 0.0
        self._consec_no_hh = 0
        self._consec_lh = 0
        self._consec_ll = 0
        self._consec_hl = 0
        self._hh_count = 0
        self._hl_count = 0
        self._lh_count = 0
        self._ll_count = 0
        self._bar_count_1m = 0
        self._max_consec_no_hh = 0
        self._max_consec_hl = 0
        self._max_consec_ll = 0

        # Exit trigger points — dict per threshold: {bar, price, pnl_pts, ts}
        self._exits = {}

        # Results
        self._results = []
        self._skipped = []
        self._counter = 0
        self._diag = {
            "flips": 0, "entries": 0, "skipped": 0, "trades": 0,
        }

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
        if self._state == "IN_POSITION":
            self._path.update(bar)

    # ---- 1m: regime, flip, bar+1 confirm, HH/HL/LH/LL tracking ----

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

        if not self._warmup:
            self._warmup = (
                self.regime.is_warmed_up and self._1m_count >= 60)
            if not self._warmup:
                self._regime = new_r
                if self._regime != 0:
                    self._regime_start_bar = self._1m_count
                return

        # ---- Step 1: Bar+1 confirmation (if AWAITING_BAR1) ----
        if self._state == "AWAITING_BAR1":
            self._check_bar1(bar, atr)

        # ---- Step 2: HH/HL/LH/LL tracking (if IN_POSITION) ----
        elif self._state == "IN_POSITION":
            self._classify_bar(bar)

        # ---- Step 3: Regime flip detection ----
        if (new_r != self._regime and self._regime != 0 and new_r != 0):
            self._diag["flips"] += 1

            # If in position, close it at this bar's close
            if self._state == "IN_POSITION":
                self._close_trade(bar, "regime_flip")

            # If AWAITING_BAR1 but regime flipped already, cancel
            if self._state == "AWAITING_BAR1":
                self._skipped.append({
                    **self._flip_pending,
                    "reason": "regime_flipped_before_bar1",
                    "bar1_made_hh": 0,
                })
                self._flip_pending = None
                self._state = "FLAT"

            # Record new flip, will check bar+1 at NEXT _on_1m
            self._flip_pending = self._build_flip_info(
                bar, new_r, atr, high, low, open_, close, vol)
            self._state = "AWAITING_BAR1"
            self._regime_start_bar = self._1m_count

        self._regime = new_r

    def _build_flip_info(self, bar, direction, atr, h, l, o, c, vol):
        dt_ct = pd.Timestamp(
            bar.ts_event, unit="ns", tz="UTC").astimezone(CT)
        ct_min = dt_ct.hour * 60 + dt_ct.minute
        bar_range = h - l
        vol_avg = (np.mean(list(self._vol_buf))
                   if self._vol_buf else 1.0)
        eh3 = self.regime.short_ema_high.value
        el3 = self.regime.short_ema_low.value
        ema3_c = (self.regime.short_ema_close.value
                  if self.regime.short_ema_close.initialized
                  else float("nan"))
        ema9_c = self.regime.long_ema_close.value

        return {
            "flip_time": pd.Timestamp(bar.ts_event, unit="ns", tz="UTC"),
            "flip_ts_ns": bar.ts_event,
            "direction": direction,
            "flip_bar_high": h,
            "flip_bar_low": l,
            "flip_bar_open": o,
            "flip_bar_close": c,
            "flip_bar_range": bar_range,
            "flip_bar_range_atr": bar_range / atr if atr > 0 else 0,
            "flip_bar_body_pct": (
                abs(c - o) / bar_range if bar_range > 0 else 0),
            "flip_bar_close_location": (
                (c - l) / bar_range if bar_range > 0 else 0.5),
            "flip_bar_volume": vol,
            "flip_bar_vol_vs_20avg": _safe_div(vol, vol_avg),
            "prior_regime_duration_bars": (
                self._1m_count - self._regime_start_bar),
            "atr_at_flip": atr,
            "atr_relative": (
                atr / self.regime.atr_long.value
                if (self.regime.atr_long.initialized
                    and self.regime.atr_long.value > 0) else 1.0),
            "ema3_slope": (
                (self._ema3_buf[-1] - self._ema3_buf[-6]) / atr
                if len(self._ema3_buf) >= 6 else float("nan")),
            "ema_spread": _safe_div(eh3 - el3, atr),
            "ema3_ema9_spread": _safe_div(ema3_c - ema9_c, atr)
            if not np.isnan(ema3_c) else float("nan"),
            "date": str(dt_ct.date()),
            "year": dt_ct.year,
            "hour_ct": dt_ct.hour,
            "is_rth": 1 if 510 <= ct_min < 900 else 0,
            "session": "RTH" if 510 <= ct_min < 900 else "ETH",
        }

    def _check_bar1(self, bar, atr):
        """Bar+1 confirmation — decide to enter or skip."""
        fp = self._flip_pending
        high = float(bar.high)
        low = float(bar.low)
        close = float(bar.close)
        d = fp["direction"]

        if d == 1:
            made_hh = high > fp["flip_bar_high"]
            hh_amount = (high - fp["flip_bar_high"]) / fp["atr_at_flip"]
        else:
            made_hh = low < fp["flip_bar_low"]
            hh_amount = (fp["flip_bar_low"] - low) / fp["atr_at_flip"]

        bar1_data = {
            "bar1_high": high,
            "bar1_low": low,
            "bar1_close": close,
            "bar1_range_atr": (high - low) / fp["atr_at_flip"]
            if fp["atr_at_flip"] > 0 else 0,
            "bar1_body_pct": (
                abs(close - float(bar.open)) / (high - low)
                if (high - low) > 0 else 0),
            "bar1_hh_amount_atr": hh_amount,
            "bar1_made_hh": 1 if made_hh else 0,
        }

        if not made_hh:
            # Record skipped flip with counterfactual regime info
            self._skipped.append({
                **fp,
                **bar1_data,
                "reason": "bar1_no_hh",
            })
            self._diag["skipped"] += 1
            self._flip_pending = None
            self._state = "FLAT"
            return

        # CONFIRMED — enter at bar+1 close
        self._counter += 1
        self._trade = {
            "trade_id": self._counter,
            "entry_price": close,
            "entry_ts": bar.ts_event,
            "entry_time": pd.Timestamp(bar.ts_event, unit="ns", tz="UTC"),
            **fp,
            **bar1_data,
        }

        # Initialize HH/HL/LH/LL tracking state — use bar+1 high/low as base
        if d == 1:
            self._prev_high = high
            self._prev_low = low
        else:
            self._prev_high = high
            self._prev_low = low

        self._consec_no_hh = 0
        self._consec_lh = 0
        self._consec_ll = 0
        self._consec_hl = 0
        self._hh_count = 0
        self._hl_count = 0
        self._lh_count = 0
        self._ll_count = 0
        self._bar_count_1m = 0
        self._max_consec_no_hh = 0
        self._max_consec_hl = 0
        self._max_consec_ll = 0
        self._exits = {}

        # Start path tracker from bar+1 close
        self._path.start(close, d, fp["atr_at_flip"], bar.ts_event)

        self._state = "IN_POSITION"
        self._diag["entries"] += 1
        self._flip_pending = None

    def _classify_bar(self, bar):
        """Classify each bar after entry using direction-aware semantics.

        For bullish trades:
          - continuation = HH (higher high)
          - reversal = LL (lower low)
          - structure_break = LH (lower high)
          - structure_intact = HL (higher low)

        For bearish trades (mirrored):
          - continuation = LL (lower low)
          - reversal = HH (higher high)
          - structure_break = HL (higher low)
          - structure_intact = LH (lower high)

        Exit triggers use unified semantic names:
          - trend_stall_1/2/3 = 1/2/3 consecutive bars without continuation
          - first_reverse = first bar making reversal extreme
          - second_reverse = 2 consecutive reverse bars
          - first_struct_break = first structure-break bar
          - first_reverse_struct = bar with BOTH reverse and struct_break
          - struct_fail = first reverse after 2+ consecutive structure_intact
        """
        if not self._trade:
            return

        high = float(bar.high)
        low = float(bar.low)
        close = float(bar.close)
        ts = bar.ts_event
        d = self._trade["direction"]

        self._bar_count_1m += 1

        # Raw conditions
        is_higher_high = high > self._prev_high
        is_lower_low = low < self._prev_low
        is_higher_low = low > self._prev_low
        is_lower_high = high < self._prev_high

        # Direction-aware semantic classification
        if d == 1:  # bullish
            is_continuation = is_higher_high
            is_reversal = is_lower_low
            is_struct_break = is_lower_high
            is_struct_intact = is_higher_low
        else:  # bearish
            is_continuation = is_lower_low
            is_reversal = is_higher_high
            is_struct_break = is_higher_low
            is_struct_intact = is_lower_high

        # Update continuation tracking (HH for bull, LL for bear)
        if is_continuation:
            self._hh_count += 1  # reusing var name = continuation count
            self._consec_no_hh = 0
            self._consec_lh = 0
            if d == 1:
                self._prev_high = high
            else:
                self._prev_low = low
        else:
            self._consec_no_hh += 1
            if is_struct_break:
                self._lh_count += 1
                self._consec_lh += 1

        # Update reversal/struct_intact tracking
        if is_struct_intact:
            self._hl_count += 1
            self._consec_hl += 1
            self._consec_ll = 0
            # Update the running intact extreme
            if d == 1:
                self._prev_low = low
            else:
                self._prev_high = high
        elif is_reversal:
            self._ll_count += 1
            self._consec_ll += 1
            self._consec_hl = 0
            # Update running reversal extreme
            if d == 1:
                self._prev_low = low
            else:
                self._prev_high = high
        else:
            # Flat — reset both
            self._consec_hl = 0
            self._consec_ll = 0

        self._max_consec_no_hh = max(
            self._max_consec_no_hh, self._consec_no_hh)
        self._max_consec_hl = max(self._max_consec_hl, self._consec_hl)
        self._max_consec_ll = max(self._max_consec_ll, self._consec_ll)

        # Record exit triggers (first occurrence only)
        ep = self._trade["entry_price"]
        pnl_pts = (close - ep) * d

        triggers = []

        # Trend stall exits
        if self._consec_no_hh == 1:
            triggers.append("hh1_stall")
        if self._consec_no_hh == 2:
            triggers.append("hh2_stall")
        if self._consec_no_hh == 3:
            triggers.append("hh3_stall")

        # Reversal exits
        if is_reversal:
            triggers.append("first_ll")
        if self._consec_ll == 2:
            triggers.append("second_ll")

        # Structure break exits
        if is_struct_break:
            triggers.append("first_lh")

        # Combo: reversal AND structure break on same bar
        if is_reversal and is_struct_break:
            triggers.append("first_lh_ll")

        # Struct fail: first reversal after 2+ consecutive struct_intact
        if is_reversal and self._max_consec_hl >= 2:
            triggers.append("hl_break")

        for name in triggers:
            if name not in self._exits:
                self._exits[name] = {
                    "bar": self._bar_count_1m,
                    "price": close,
                    "pnl_pts": pnl_pts,
                    "pnl_dollars": pnl_pts * NQ_MULT - COMMISSION,
                    "time": pd.Timestamp(ts, unit="ns", tz="UTC"),
                }

    def _close_trade(self, exit_bar, reason):
        if self._trade is None:
            self._state = "FLAT"
            return

        t = self._trade
        exit_price = float(exit_bar.close)
        exit_ts = exit_bar.ts_event
        ep = t["entry_price"]
        d = t["direction"]
        pnl_pts = (exit_price - ep) * d
        pnl_dollars = pnl_pts * NQ_MULT - COMMISSION
        dur_s = (exit_ts - t["entry_ts"]) / 1e9

        t.update({
            "exit_time": pd.Timestamp(exit_ts, unit="ns", tz="UTC"),
            "exit_price": exit_price,
            "exit_reason_baseline": reason,
            "regime_pnl_pts": pnl_pts,
            "regime_pnl_dollars": pnl_dollars,
            "regime_duration_bars": self._bar_count_1m,
            "regime_duration_seconds": dur_s,
            "total_hh_count": self._hh_count,
            "total_hl_count": self._hl_count,
            "total_lh_count": self._lh_count,
            "total_ll_count": self._ll_count,
            "max_consecutive_no_hh": self._max_consec_no_hh,
            "max_consecutive_hl": self._max_consec_hl,
            "max_consecutive_ll": self._max_consec_ll,
        })

        # Record all exit trigger points
        for name in ["hh1_stall", "hh2_stall", "hh3_stall",
                     "first_ll", "second_ll", "first_lh",
                     "first_lh_ll", "hl_break"]:
            if name in self._exits:
                ex = self._exits[name]
                t[f"{name}_bar"] = ex["bar"]
                t[f"{name}_price"] = ex["price"]
                t[f"{name}_pnl_pts"] = ex["pnl_pts"]
                t[f"{name}_pnl_dollars"] = ex["pnl_dollars"]
                t[f"{name}_time"] = ex["time"]
            else:
                t[f"{name}_bar"] = None
                t[f"{name}_price"] = None
                t[f"{name}_pnl_pts"] = None
                t[f"{name}_pnl_dollars"] = None
                t[f"{name}_time"] = None

        # Path labels
        t.update(self._path.get_labels())

        self._results.append(t)
        self._diag["trades"] += 1
        self._trade = None
        self._state = "FLAT"

    def on_stop(self):
        if self._state == "IN_POSITION" and self._trade:
            # Fake close at last known state
            t = self._trade
            t.update({
                "exit_time": t.get("entry_time"),
                "exit_price": t.get("entry_price", 0),
                "exit_reason_baseline": "end_of_data",
                "regime_pnl_pts": 0,
                "regime_pnl_dollars": -COMMISSION,
                "regime_duration_bars": self._bar_count_1m,
                "regime_duration_seconds": 0,
                "total_hh_count": self._hh_count,
                "total_hl_count": self._hl_count,
                "total_lh_count": self._lh_count,
                "total_ll_count": self._ll_count,
                "max_consecutive_no_hh": self._max_consec_no_hh,
                "max_consecutive_hl": self._max_consec_hl,
                "max_consecutive_ll": self._max_consec_ll,
            })
            for name in ["hh1_stall", "hh2_stall", "hh3_stall",
                         "first_ll", "second_ll", "first_lh",
                         "first_lh_ll", "hl_break"]:
                if name in self._exits:
                    ex = self._exits[name]
                    for k, v in [("bar", ex["bar"]), ("price", ex["price"]),
                                 ("pnl_pts", ex["pnl_pts"]),
                                 ("pnl_dollars", ex["pnl_dollars"]),
                                 ("time", ex["time"])]:
                        t[f"{name}_{k}"] = v
                else:
                    for k in ["bar", "price", "pnl_pts",
                              "pnl_dollars", "time"]:
                        t[f"{name}_{k}"] = None
            t.update(self._path.get_labels())
            self._results.append(t)

        print(f"\n=== CONFIRMED FLIP COLLECTION COMPLETE ===")
        print(f"1m bars: {self._1m_count:,}")
        print(f"Total flips: {self._diag['flips']:,}")
        print(f"Entries (bar+1 HH confirmed): {self._diag['entries']:,}")
        print(f"Skipped (no bar+1 HH): {self._diag['skipped']:,}")
        print(f"Completed trades: {self._diag['trades']:,}")
