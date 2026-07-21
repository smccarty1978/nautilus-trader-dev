"""Live-style pre-flip T-1 NT strategy.

Computes all 20 model features incrementally from streaming 1s bars,
scores a frozen LightGBM model at each 1m bucket close, and trades.

This is a deployable-path validation: NO precomputed candidates, NO
precomputed schedule, NO offline trade matching. Every quantity the
strategy uses is derived on the fly from bars that have *closed at or
before* the current 1m boundary (the causality boundary).

Execution model (bar_execution=True):
  - Market orders fill at the NEXT 1s bar's OPEN price.
  - Entries are decided at a 1m bucket close; the order is submitted on
    that same 1s bar (the last 1s bar of the minute) so it fills at the
    open of the first 1s bar of the next minute.

Timeframe state:
  - Buckets for 5s/15s/30s/1m/3m/5m via epoch-floor binning.
  - A bucket CLOSES only when the first 1s bar of the *next* bucket
    arrives -- never on a wall clock. The just-closed bucket is then
    folded into that timeframe's EMA / ATR / regime state.

Causality:
  - Feature computation runs inside the 1m bucket-close handler.
  - It uses each timeframe's *latest fully closed* bucket only.
  - The in-progress bucket (the minute we are entering) is never read.
"""
from __future__ import annotations

import json
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

import lightgbm as lgb
import numpy as np

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Quantity
from nautilus_trader.trading.strategy import Strategy

NS_PER_S = 1_000_000_000
NQ_MULT = 20.0
COMMISSION_PER_SIDE = 2.5

# EMA smoothing factors (adjust=False recursive EMA).
ALPHA_EMA3 = 0.5   # span-3:  2/(3+1)
ALPHA_EMA9 = 0.2   # span-9:  2/(9+1)

# Timeframe periods (seconds).
TF_SECONDS = {"5s": 5, "15s": 15, "30s": 30, "1m": 60, "3m": 180, "5m": 300}

ATR_PERIOD = 14


def _ema_update(prev, x, alpha):
    """Recursive EMA with adjust=False. First value seeds ema = x."""
    if prev is None:
        return x
    return alpha * x + (1.0 - alpha) * prev


class TimeframeState:
    """Incrementally maintains EMA/ATR/regime for a single timeframe.

    Fed one *closed* bucket at a time. O(1) per bucket.
    """

    def __init__(self, period_s: int):
        self.period_ns = period_s * NS_PER_S
        # Current open (in-progress) bucket aggregation.
        self._cur_bin = None          # epoch-floor ns of in-progress bucket
        self._o = self._h = self._l = self._c = None
        self._v = 0.0
        # Indicator state (reflects the LATEST CLOSED bucket).
        self.ema3_h = None
        self.ema9_h = None
        self.ema3_l = None
        self.ema9_l = None
        self.close = None             # close of latest closed bucket
        self.atr = None               # Wilder ATR-14, None until warm
        self.regime = 0               # sticky regime: +1 / -1 / 0
        self.n_closed = 0             # number of closed buckets seen
        # ATR machinery.
        self._prev_close = None       # close of the bucket before latest
        self._tr_seed = []            # first 14 TRs for the seed mean
        # Did the regime just flip on the most recent closed bucket?
        self.regime_flipped = False

    def add_1s_bar(self, ts_event_ns, o, h, l, c, v):
        """Feed a 1s bar. Returns the just-closed bucket dict, or None.

        Bucket-close rule: a bucket closes only when the first 1s bar of
        the *next* bucket arrives.
        """
        b = (ts_event_ns // self.period_ns) * self.period_ns
        closed = None
        if self._cur_bin is None:
            self._cur_bin = b
        elif b != self._cur_bin:
            # The in-progress bucket is now complete -> close it.
            closed = {
                "ts_event": self._cur_bin,
                "open": self._o, "high": self._h,
                "low": self._l, "close": self._c,
                "volume": self._v,
            }
            self._fold_closed_bucket(closed)
            self._cur_bin = b
            self._o = self._h = self._l = self._c = None
            self._v = 0.0

        # Accumulate this 1s bar into the (now) in-progress bucket.
        if self._o is None:
            self._o, self._h, self._l, self._c = o, h, l, c
        else:
            self._h = max(self._h, h)
            self._l = min(self._l, l)
            self._c = c
        self._v += v
        return closed

    def _fold_closed_bucket(self, bk):
        """Update EMA / ATR / regime from one freshly-closed bucket."""
        h, l, c = bk["high"], bk["low"], bk["close"]

        # --- Wilder ATR-14 ---
        if self._prev_close is None:
            tr = h - l
        else:
            tr = max(h - l, abs(h - self._prev_close),
                     abs(l - self._prev_close))
        if self.atr is None:
            self._tr_seed.append(tr)
            if len(self._tr_seed) == ATR_PERIOD:
                # Seed at the 14th bucket = mean of first 14 TRs.
                self.atr = sum(self._tr_seed) / ATR_PERIOD
        else:
            self.atr = (self.atr * (ATR_PERIOD - 1) + tr) / ATR_PERIOD
        self._prev_close = c

        # --- EMAs of high / low ---
        self.ema3_h = _ema_update(self.ema3_h, h, ALPHA_EMA3)
        self.ema9_h = _ema_update(self.ema9_h, h, ALPHA_EMA9)
        self.ema3_l = _ema_update(self.ema3_l, l, ALPHA_EMA3)
        self.ema9_l = _ema_update(self.ema9_l, l, ALPHA_EMA9)
        self.close = c

        # --- Sticky regime ---
        prev_regime = self.regime
        if c > self.ema3_h and c > self.ema9_h:
            self.regime = 1
        elif c < self.ema3_l and c < self.ema9_l:
            self.regime = -1
        # else: carry previous (sticky)
        self.regime_flipped = self.regime != prev_regime
        self.n_closed += 1

    @property
    def atr_warm(self) -> bool:
        return self.atr is not None and self.atr > 0


class PreFlipLiveConfig(StrategyConfig, frozen=True):
    instrument_id: str = "NQ.XCME"
    bar_type_1s: str = "NQ.XCME-1-SECOND-LAST-EXTERNAL"
    model_path: str = ""
    feature_list_path: str = ""
    thresholds_path: str = ""
    position_size: int = 1
    max_hold_s: int = 600
    # When set, every eligible candidate's on-stream features are
    # logged to this parquet path on_stop (for rolling-model training).
    # Logging is independent of position state and does not affect
    # trading. Set to "" to disable.
    feature_log_path: str = ""
    # When set, ROLLING mode: load a directory of monthly models
    # (manifest.json + model_<YYYY-MM>.txt). The model + thresholds in
    # force at each 1m decision are the ones for that decision's month.
    # Overrides model_path/thresholds_path. Set to "" for static mode.
    rolling_dir: str = ""


class PreFlipLiveStrategy(Strategy):
    """Computes 20 features live, scores a frozen LGBM model, trades."""

    def __init__(self, config: PreFlipLiveConfig):
        super().__init__(config)
        self._cfg = config
        self._inst_id = InstrumentId.from_str(config.instrument_id)

        # --- Frozen artifacts ---
        with open(config.feature_list_path) as f:
            self._feature_list = json.load(f)

        self._rolling_mode = bool(config.rolling_dir)
        if self._rolling_mode:
            # ROLLING mode: load all monthly models keyed by 'YYYY-MM'.
            from pathlib import Path as _P
            rd = _P(config.rolling_dir)
            manifest = json.loads((rd / "manifest.json").read_text())
            self._rolling = {}
            for ym, info in manifest.items():
                self._rolling[ym] = (
                    lgb.Booster(model_file=str(rd / info["model"])),
                    float(info["entry_top10"]),
                    float(info["rescore_top50"]))
            # Active model/thresholds — set per 1m close in rolling mode.
            self._model = None
            self._entry_thr = None
            self._rescore_thr = None
        else:
            self._rolling = None
            self._model = lgb.Booster(model_file=config.model_path)
            with open(config.thresholds_path) as f:
                th = json.load(f)
            self._entry_thr = float(th["entry_top10"])
            self._rescore_thr = float(th["rescore_top50"])

        # --- Timeframe states ---
        self._tf = {k: TimeframeState(v) for k, v in TF_SECONDS.items()}

        # --- 1m current-regime maturity (reset on every 1m flip) ---
        self._regime_start_close = None
        self._run_max_h = None
        self._run_min_l = None
        self._cum_abs_range = 0.0

        # --- Rolling 1s buffer for volume windows + session VWAP ---
        # Each entry: dict with ts, o,h,l,c,v + precomputed aggregates.
        self._buf_1s = deque()         # ~24h capacity (trimmed by time)
        self._buf_max_ns = 25 * 3600 * NS_PER_S

        # --- Session VWAP accumulators (reset at 17:00 CT) ---
        self._sess_date = None         # session date key (CT-17h .date())
        self._sess_p_vol = 0.0
        self._sess_p2_vol = 0.0
        self._sess_vol = 0.0
        self._sess_signed_vol = 0.0
        self._sess_cum_vol = 0.0       # cum_vol_session feature source

        # --- Order / position bookkeeping (single position) ---
        self._open_trade = None        # dict for the live trade, or None
        self._pending_entry_cid = None  # entry order awaiting fill
        self._pending_exit_cid = None   # exit order awaiting fill
        self.all_trades: list[dict] = []
        self._feature_log: list[dict] = []

        self._diag = {
            "1m_buckets": 0,
            "candidates_eligible": 0,
            "candidates_scored": 0,
            "entries_submitted": 0,
            "entries_filled": 0,
            "exits_submitted": 0,
            "exits_filled": 0,
            "exit_regime_flip": 0,
            "exit_rescore": 0,
            "exit_max_hold": 0,
            "va_confirmed": 0,
            "va_noflip": 0,
        }

    def on_start(self):
        self._bt_1s = BarType.from_str(self._cfg.bar_type_1s)
        self.subscribe_bars(self._bt_1s)
        # Audit C2: in rolling mode the model/thresholds are None until
        # the first trained month's bar arrives — don't log them here.
        if self._rolling_mode:
            self.log.info(
                f"Rolling mode: {len(self._rolling)} monthly models "
                f"loaded.")
        else:
            self.log.info(
                f"Loaded model ({self._model.num_feature()} features), "
                f"entry_thr={self._entry_thr:.4f} "
                f"rescore_thr={self._rescore_thr:.4f}")

    # ------------------------------------------------------------------
    # Bar handling
    # ------------------------------------------------------------------
    def on_bar(self, bar: Bar):
        if bar.bar_type != self._bt_1s:
            return
        ts = bar.ts_event
        o = float(bar.open)
        h = float(bar.high)
        l = float(bar.low)
        c = float(bar.close)
        v = float(bar.volume)

        # --- 1) Feed every timeframe; detect 1m bucket close ---
        # add_1s_bar returns the just-closed bucket BEFORE accumulating
        # this bar, so timeframe EMA/ATR/regime never see this bar.
        closed_1m = None
        for name, tf in self._tf.items():
            closed = tf.add_1s_bar(ts, o, h, l, c, v)
            if closed is not None and name == "1m":
                closed_1m = closed
                # 1m regime maturity folds the just-closed 1m bar.
                self._update_1m_maturity(tf, closed)

        # --- 2) On a 1m bucket close, run the decision logic.
        # Causality boundary: this runs BEFORE the triggering 1s bar
        # (the first second of the new minute, ts_event = close_ts) is
        # ingested into the volume buffer / session VWAP. So all
        # volume-based features stay strictly on the [.., T) boundary,
        # consistent with the volume-window convention.
        if closed_1m is not None:
            self._diag["1m_buckets"] += 1
            self._on_1m_close(closed_1m, current_bar=bar)

        # --- 3) Session VWAP rollover + 1s buffer maintenance ---
        # Done last so the triggering bar joins the buffer/VWAP only
        # after the decision for the minute it closed.
        self._maybe_roll_session(ts)
        self._ingest_1s_bar(ts, o, h, l, c, v)

    # ------------------------------------------------------------------
    # 1s buffer + session VWAP
    # ------------------------------------------------------------------
    def _maybe_roll_session(self, ts_event_ns: int):
        """Reset VWAP accumulators at each 17:00 CT session boundary.

        CME session date = (Chicago time - 17h).date(). When the session
        date key changes, a new session has begun.
        """
        # Chicago = UTC + offset. Use the timestamp's CT wall time.
        ct = _to_ct(ts_event_ns)
        sess_dt = (ct - timedelta(hours=17)).date()
        if self._sess_date is None or sess_dt != self._sess_date:
            self._sess_date = sess_dt
            self._sess_p_vol = 0.0
            self._sess_p2_vol = 0.0
            self._sess_vol = 0.0
            self._sess_signed_vol = 0.0
            self._sess_cum_vol = 0.0

    def _ingest_1s_bar(self, ts, o, h, l, c, v):
        bar_dir = 0
        if c > o:
            bar_dir = 1
        elif c < o:
            bar_dir = -1
        bull_vol = v if bar_dir > 0 else 0.0
        bear_vol = v if bar_dir < 0 else 0.0
        typical = (h + l + c) / 3.0
        p_vol = typical * v
        p2_vol = typical * typical * v

        # Audit W1: volume-window scan assumes a chronologically
        # monotone buffer. Enforce it so a future routing change can't
        # silently under-count volume features.
        assert not self._buf_1s or ts >= self._buf_1s[-1]["ts"], (
            "1s buffer received out-of-order bar")
        self._buf_1s.append({
            "ts": ts, "v": v, "bull": bull_vol, "bear": bear_vol,
        })
        # Trim buffer to ~24h.
        cutoff = ts - self._buf_max_ns
        while self._buf_1s and self._buf_1s[0]["ts"] < cutoff:
            self._buf_1s.popleft()

        # Session VWAP accumulators.
        self._sess_p_vol += p_vol
        self._sess_p2_vol += p2_vol
        self._sess_vol += v
        self._sess_signed_vol += bar_dir * v
        self._sess_cum_vol += v

    def _volume_window(self, t_ns: int, window_s: int):
        """Sum bull/bear/total of 1s bars with ts_event in [T-W, T).

        T is the 1m bucket close time. The window EXCLUDES bars at exactly
        T (none exist yet) and includes everything back W seconds.
        """
        lo = t_ns - window_s * NS_PER_S
        bull = bear = total = 0.0
        # Iterate from the most recent bar backwards (newest at right).
        for rec in reversed(self._buf_1s):
            if rec["ts"] < lo:
                break
            if rec["ts"] >= t_ns:
                continue
            bull += rec["bull"]
            bear += rec["bear"]
            total += rec["v"]
        return bull, bear, total

    # ------------------------------------------------------------------
    # 1m current-regime maturity
    # ------------------------------------------------------------------
    def _update_1m_maturity(self, tf_1m: TimeframeState, closed_1m: dict):
        """Maintain run_max/min, cum_abs_range; reset on a 1m regime flip.

        Called right after the 1m timeframe folds the closed bucket, so
        tf_1m.regime / .regime_flipped already reflect that bucket.
        """
        h, l, c = closed_1m["high"], closed_1m["low"], closed_1m["close"]
        if self._regime_start_close is None or tf_1m.regime_flipped:
            # New regime epoch starts at this bar.
            self._regime_start_close = c
            self._run_max_h = h
            self._run_min_l = l
            self._cum_abs_range = abs(h - l)
        else:
            self._run_max_h = max(self._run_max_h, h)
            self._run_min_l = min(self._run_min_l, l)
            self._cum_abs_range += abs(h - l)

    # ------------------------------------------------------------------
    # Decision logic at 1m bucket close
    # ------------------------------------------------------------------
    def _on_1m_close(self, closed_1m: dict, current_bar: Bar):
        """Runs at every 1m bucket close (causality boundary).

        closed_1m is the minute that just completed. All timeframe states
        now reflect their latest CLOSED buckets <= this 1m close time.
        """
        close_ts = closed_1m["ts_event"] + TF_SECONDS["1m"] * NS_PER_S

        # --- ROLLING mode: install this month's model + thresholds ---
        if self._rolling_mode:
            ct = _to_ct(close_ts)
            ym = f"{ct.year}-{ct.month:02d}"
            entry = self._rolling.get(ym)
            if entry is None:
                # No model for this month (pre-deployment warmup) —
                # skip the decision entirely. No open trades exist in
                # these months.
                return
            self._model, self._entry_thr, self._rescore_thr = entry

        # --- Feature logging (independent of trading / position) ---
        if self._cfg.feature_log_path:
            self._log_candidates(closed_1m, close_ts)

        # --- A) Manage an open trade (exit logic) ---
        if self._open_trade is not None:
            self._manage_open_trade(closed_1m, close_ts, current_bar)

        # --- B) Consider a new entry (only if fully flat & idle) ---
        if (self._open_trade is None
                and self._pending_entry_cid is None
                and self._pending_exit_cid is None):
            self._consider_entry(closed_1m, close_ts, current_bar)

    def _candidate_eval(self, closed_1m: dict, close_ts: int, d: int):
        """Evaluate candidate eligibility + features + score for dir d.

        Returns (eligible: bool, score: float|None, feats: dict|None).
        """
        tf1m = self._tf["1m"]

        # --- RTH + ATR-warmth gate ---
        ct = _to_ct(close_ts)
        ct_minute_of_day = ct.hour * 60 + ct.minute
        rth = 510 <= ct_minute_of_day < 900
        all_atr_warm = all(tf.atr_warm for tf in self._tf.values())
        atr_1m = tf1m.atr
        atr1m_ok = atr_1m is not None and np.isfinite(atr_1m) and atr_1m > 0
        if not (rth and atr1m_ok and all_atr_warm):
            return False, None, None

        # --- regime_1m must differ from candidate direction ---
        if tf1m.regime == d:
            return False, None, None

        # --- dist_to_1m_flip_threshold (needed for prox_ok + feat 1) ---
        c1m = tf1m.close
        if d == 1:
            dist_flip = (max(tf1m.ema3_h, tf1m.ema9_h) - c1m) / atr_1m
        else:
            dist_flip = (c1m - min(tf1m.ema3_l, tf1m.ema9_l)) / atr_1m

        faster_aligned = (self._tf["5s"].regime == d
                          or self._tf["15s"].regime == d
                          or self._tf["30s"].regime == d)
        prox_ok = 0.0 <= dist_flip <= 0.50
        if not (faster_aligned or prox_ok):
            return False, None, None

        # Eligible -> build the 20-feature vector and score.
        feats = self._build_features(closed_1m, close_ts, d, dist_flip)
        vec = np.array([[feats[name] for name in self._feature_list]],
                       dtype=np.float64)
        score = float(self._model.predict(vec)[0])
        return True, score, feats

    def _build_features(self, closed_1m, close_ts, d, dist_flip):
        """Compute the 20 model features for candidate direction d.

        All distance features use each timeframe's latest CLOSED bucket.
        """
        tf = self._tf
        tf1m = tf["1m"]
        atr_1m = tf1m.atr
        c1m = tf1m.close

        def dist(tf_name, ema_attr):
            t = tf[tf_name]
            return (t.close - getattr(t, ema_attr)) / t.atr

        # current_regime_max_mae_atr
        r = tf1m.regime
        if r == 1:
            mae = (self._regime_start_close - self._run_min_l) / atr_1m
        elif r == -1:
            mae = (self._run_max_h - self._regime_start_close) / atr_1m
        else:
            mae = 0.0

        # current_regime_efficiency (NOT atr-normalized)
        if self._cum_abs_range > 0:
            eff = abs(c1m - self._regime_start_close) / self._cum_abs_range
        else:
            eff = 0.0

        # Volume windows.
        bull_60, bear_60, tot_60 = self._volume_window(close_ts, 60)
        bull_300, bear_300, tot_300 = self._volume_window(close_ts, 300)
        bull_900, bear_900, tot_900 = self._volume_window(close_ts, 900)

        vol_imb_1m = ((bull_60 - bear_60) / tot_60 * d
                      if tot_60 > 0 else 0.0)
        vol_imb_5m = ((bull_300 - bear_300) / tot_300 * d
                      if tot_300 > 0 else 0.0)
        vol_delta_15m = bull_900 - bear_900

        # Clock features (CT).
        ct = _to_ct(close_ts)
        minute_ct = ct.minute
        minutes_since_rth = ct.hour * 60 + ct.minute - 510

        # Session VWAP.
        if self._sess_vol > 0:
            vwap = self._sess_p_vol / self._sess_vol
            var = self._sess_p2_vol / self._sess_vol - vwap * vwap
            vwap_sigma = np.sqrt(max(var, 0.0))
        else:
            vwap = c1m
            vwap_sigma = 0.0
        vwap_low_2sd = (c1m - (vwap - 2.0 * vwap_sigma)) / atr_1m
        vwap_up_2sd = (c1m - (vwap + 2.0 * vwap_sigma)) / atr_1m

        return {
            "dist_to_1m_flip_threshold_atr_dir": dist_flip,
            "dist_close_to_ema3_h_3m_atr": dist("3m", "ema3_h"),
            "current_regime_max_mae_atr": mae,
            "dist_close_to_ema9_h_30s_atr": dist("30s", "ema9_h"),
            "dist_close_to_ema3_h_5m_atr": dist("5m", "ema3_h"),
            "current_regime_efficiency": eff,
            "vol_total_1m": tot_60,
            "vol_delta_15m": vol_delta_15m,
            "vol_imbalance_dir_1m": vol_imb_1m,
            "minute_ct": float(minute_ct),
            "dist_close_to_ema9_h_5s_atr": dist("5s", "ema9_h"),
            "dist_close_to_ema3_l_3m_atr": dist("3m", "ema3_l"),
            "minutes_since_rth_open": float(minutes_since_rth),
            "dist_close_to_ema3_l_5m_atr": dist("5m", "ema3_l"),
            "dist_close_to_ema3_l_5s_atr": dist("5s", "ema3_l"),
            "cum_vol_session": self._sess_cum_vol,
            "dist_close_to_vwap_lower_2sd_atr": vwap_low_2sd,
            "dist_close_to_vwap_upper_2sd_atr": vwap_up_2sd,
            "vol_imbalance_dir_5m": vol_imb_5m,
            "dist_close_to_ema3_h_1m_atr": dist("1m", "ema3_h"),
        }

    # ------------------------------------------------------------------
    # Feature logging (rolling-model training data collection)
    # ------------------------------------------------------------------
    def _log_candidates(self, closed_1m, close_ts):
        """Log on-stream features for every eligible candidate at this
        1m close, both directions, regardless of position state. Used
        to build the rolling-model training set. Pure data capture —
        does not influence trading.
        """
        for d in (1, -1):
            eligible, score, feats = self._candidate_eval(
                closed_1m, close_ts, d)
            if not eligible:
                continue
            row = {"close_ts_ns": int(close_ts), "direction": int(d),
                   "p_score": float(score)}
            row.update({k: float(v) for k, v in feats.items()})
            self._feature_log.append(row)

    # ------------------------------------------------------------------
    # Entry
    # ------------------------------------------------------------------
    def _consider_entry(self, closed_1m, close_ts, current_bar):
        for d in (1, -1):
            eligible, score, feats = self._candidate_eval(
                closed_1m, close_ts, d)
            if not eligible:
                continue
            self._diag["candidates_eligible"] += 1
            self._diag["candidates_scored"] += 1
            if score >= self._entry_thr:
                self._submit_entry(d, score, closed_1m, close_ts)
                return  # single-position: take the first qualifying dir

    def _submit_entry(self, d, score, closed_1m, close_ts):
        side = OrderSide.BUY if d == 1 else OrderSide.SELL
        order = self.order_factory.market(
            instrument_id=self._inst_id,
            order_side=side,
            quantity=Quantity.from_int(self._cfg.position_size),
            time_in_force=TimeInForce.FOK,
        )
        cid = order.client_order_id.value
        self._pending_entry_cid = cid
        # entry_ts = the T-1 bar's CLOSE (decision time = close_ts).
        self._open_trade = {
            "direction": d,
            "p_score": score,
            # entry_ts = the T-1 bar's CLOSE (decision time).
            "entry_ts": close_ts,
            # The flip-bar (1m bar at entry+60s) and bar1 (entry+120s)
            # high/low get filled in as those minutes close.
            "flip_bar": None,
            "bar1": None,
            "is_va_confirm": None,    # resolved at bar1
            "entry_fill_price": None,
            "exit_fill_price": None,
            "exit_reason": None,
            "exit_filled": False,
            "exit_submitted": False,
            "exit_order_id": None,
        }
        self.submit_order(order)
        self._diag["entries_submitted"] += 1

    # ------------------------------------------------------------------
    # Open-trade management (V_A confirmation + exit)
    # ------------------------------------------------------------------
    def _manage_open_trade(self, closed_1m, close_ts, current_bar):
        trade = self._open_trade
        # Only manage once the entry has actually filled.
        if trade["entry_fill_price"] is None:
            return
        if trade["exit_submitted"]:
            return

        entry_ts = trade["entry_ts"]
        elapsed = close_ts - entry_ts  # ns since decision time

        # Record the post-entry 1m bars by their bucket-open time.
        # flip_bar = 1m bar opening at entry_ts (close = entry+60s);
        # bar1     = 1m bar opening at entry_ts+60s (close = entry+120s).
        # Match on bucket-open so a missing minute (data gap) cannot
        # silently shift the assignment.
        bk_open = closed_1m["ts_event"]
        if bk_open == entry_ts and trade["flip_bar"] is None:
            trade["flip_bar"] = closed_1m
        elif (bk_open == entry_ts + 60 * NS_PER_S
                and trade["bar1"] is None):
            trade["bar1"] = closed_1m
            self._resolve_va_confirmation(trade)
        elif (trade["is_va_confirm"] is None
                and elapsed > 120 * NS_PER_S):
            # bar1's minute was skipped by a data gap -> resolve now
            # (defensive; _resolve handles a missing bar1 as no-flip).
            self._resolve_va_confirmation(trade)

        d = trade["direction"]
        tf1m = self._tf["1m"]

        # --- V_A confirmed -> hold to regime flip out ---
        if trade["is_va_confirm"] is True:
            if tf1m.regime != d and tf1m.regime != 0:
                self._submit_exit(trade, "regime_flip", close_ts)
                self._diag["exit_regime_flip"] += 1
            return

        # --- V_A NOT confirmed -> RESCORE exit ---
        if trade["is_va_confirm"] is False:
            # Max hold 600s from entry.
            if elapsed >= self._cfg.max_hold_s * NS_PER_S:
                trade["exit_score"] = float("nan")
                self._submit_exit(trade, "max_hold", close_ts)
                self._diag["exit_max_hold"] += 1
                return
            # Re-evaluate candidate eligibility in the trade direction.
            eligible, score, _ = self._candidate_eval(
                closed_1m, close_ts, d)
            if not eligible or score < self._rescore_thr:
                trade["exit_score"] = score
                self._submit_exit(trade, "rescore", close_ts)
                self._diag["exit_rescore"] += 1
            return

        # is_va_confirm still None: bar1 not reached yet -> keep holding.

    def _resolve_va_confirmation(self, trade):
        """At bar1 (entry+120s) decide V_A confirmation.

        flip_bar = 1m bar at entry+60s; bar1 = 1m bar at entry+120s.
        """
        d = trade["direction"]
        fb = trade["flip_bar"]
        b1 = trade["bar1"]
        if fb is None or b1 is None:
            # Defensive: a missing minute (data gap). Treat as no-flip.
            trade["is_va_confirm"] = False
            self._diag["va_noflip"] += 1
            return
        if d == 1:
            hhll_ok = b1["high"] > fb["high"]
            momentum_ok = b1["close"] > b1["open"]
        else:
            hhll_ok = b1["low"] < fb["low"]
            momentum_ok = b1["close"] < b1["open"]
        confirmed = hhll_ok and momentum_ok
        trade["is_va_confirm"] = confirmed
        if confirmed:
            self._diag["va_confirmed"] += 1
        else:
            self._diag["va_noflip"] += 1

    def _submit_exit(self, trade, reason, close_ts):
        trade["exit_ts"] = close_ts
        d = trade["direction"]
        exit_side = OrderSide.SELL if d == 1 else OrderSide.BUY
        order = self.order_factory.market(
            instrument_id=self._inst_id,
            order_side=exit_side,
            quantity=Quantity.from_int(self._cfg.position_size),
            time_in_force=TimeInForce.FOK,
            reduce_only=True,
        )
        eid = order.client_order_id.value
        trade["exit_order_id"] = eid
        trade["exit_submitted"] = True
        trade["exit_reason"] = reason
        self._pending_exit_cid = eid
        self.submit_order(order)
        self._diag["exits_submitted"] += 1

    # ------------------------------------------------------------------
    # Fill / reject handling
    # ------------------------------------------------------------------
    def on_order_filled(self, event):
        cid = event.client_order_id.value
        trade = self._open_trade
        if trade is None:
            return
        if cid == self._pending_entry_cid:
            trade["entry_fill_price"] = float(event.last_px)
            self._pending_entry_cid = None
            self._diag["entries_filled"] += 1
        elif cid == trade.get("exit_order_id"):
            trade["exit_fill_price"] = float(event.last_px)
            trade["exit_filled"] = True
            self._pending_exit_cid = None
            self._diag["exits_filled"] += 1
            self._finalize_trade(trade)

    def on_order_rejected(self, event):
        reason = getattr(event, "reason", str(event))
        self.log.warning(f"Order rejected: {reason}")
        cid = event.client_order_id.value
        trade = self._open_trade
        if trade is None:
            return
        # If an exit is rejected, retry on the next 1m close by clearing
        # the submitted flag; if an entry is rejected, abandon the trade.
        if cid == self._pending_entry_cid:
            self._pending_entry_cid = None
            self._open_trade = None
        elif cid == trade.get("exit_order_id"):
            self._pending_exit_cid = None
            trade["exit_submitted"] = False
            trade["exit_order_id"] = None

    def _finalize_trade(self, trade):
        """Record a completed trade and clear the position slot."""
        entry = trade["entry_fill_price"]
        exit_px = trade["exit_fill_price"]
        d = trade["direction"]
        pnl_pts = (exit_px - entry) * d
        gross = pnl_pts * NQ_MULT
        net = gross - 2.0 * COMMISSION_PER_SIDE
        self.all_trades.append({
            "entry_ts": trade["entry_ts"],
            "exit_ts": trade.get("exit_ts"),
            "entry_fill_price": entry,
            "exit_fill_price": exit_px,
            "direction": d,
            "p_score": trade["p_score"],
            "exit_score": trade.get("exit_score", float("nan")),
            "is_va_confirm": bool(trade["is_va_confirm"]),
            "exit_reason": trade["exit_reason"],
            "pnl_pts": pnl_pts,
            "gross_pnl": gross,
            "net_pnl": net,
        })
        self._open_trade = None

    def on_stop(self):
        self.log.info(f"Diag: {self._diag}")
        # Drop any trade that never fully resolved (left open at run end).
        if self._open_trade is not None:
            self.log.warning(
                "Run ended with an unresolved open trade; dropped.")
        # Dump the candidate feature log if collection was enabled.
        if self._cfg.feature_log_path and self._feature_log:
            import pandas as _pd
            from pathlib import Path as _Path
            p = _Path(self._cfg.feature_log_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            _pd.DataFrame(self._feature_log).to_parquet(p, index=False)
            self.log.info(
                f"Feature log: {len(self._feature_log):,} rows -> {p}")


# ----------------------------------------------------------------------
# Timezone helper
# ----------------------------------------------------------------------
# Chicago is UTC-6 (CST) or UTC-5 (CDT). We need correct CT wall time for
# RTH gating and the 17:00 session boundary. Use zoneinfo for DST.
try:
    from zoneinfo import ZoneInfo
    _CT = ZoneInfo("America/Chicago")

    def _to_ct(ts_event_ns: int) -> datetime:
        dt = datetime.fromtimestamp(ts_event_ns / NS_PER_S, tz=timezone.utc)
        return dt.astimezone(_CT)
except Exception:  # pragma: no cover
    import pytz
    _CT = pytz.timezone("America/Chicago")

    def _to_ct(ts_event_ns: int) -> datetime:
        dt = datetime.fromtimestamp(ts_event_ns / NS_PER_S, tz=timezone.utc)
        return dt.astimezone(_CT)
