"""Live NT strategy for the long TOP25 March-2025 runtime-parity smoke.

Everything -- regime detection, candidate declaration, feature computation,
scoring, triggering, and trade management -- happens inside the NT event loop
on streaming bars. No pandas joins, no precomputed schedules.

CAUSAL ORDERING (two DIFFERENT conventions; conflating them is a real, measured
1-second bug -- see SPEC.md):

  * regime for a 1s bar at ts_event=T  = the regime of the 1m bar that CLOSED
    at or before T (`close_ts <= T`). NT delivers the 1m bar whose ts_init==T
    before the 1s bar whose ts_event==T (its ts_init is T+1s), so simply
    updating the regime on 1m close and reading it on subsequent 1s bars gives
    exactly this convention. The 1s bars INSIDE the minute (ts_init <= T) are
    delivered first by `add_bars_causal_order`.
  * feature/checkpoint snap = last COMPLETED 1s bar STRICTLY before the
    observation instant. The candidate tracker enforces this by evaluating a
    checkpoint against `last_close` (the previous bar) before folding the
    current bar in.

Management contract (brief, deliberately simplified):
  entry  : accepted bullish-flip trigger -> BUY (long, counter-regime)
  stop   : fixed 1.25 x ATR, ATR frozen at the regime flip, never reset/trailed
  exit   : first of {stop hit, opposing (bullish) regime flip}
  NO timeout, NO profit target, NO trailing, NO stop reset, NO Policy A.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Quantity
from nautilus_trader.trading.strategy import Strategy

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]                       # repo root
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from studies.fable5_pre_flip_d10_reversal_entry.strategy import RegimeEngine  # noqa: E402

import common as C  # noqa: E402
from candidate_tracker_long import CandidateTrackerLong  # noqa: E402
from long_feature_engine import LongFeatureEngine  # noqa: E402
from model_runtime_long import LongModelRuntime  # noqa: E402

NS = 1_000_000_000
CHI = "America/Chicago"


def minute_of_day_chicago(ts_ns: int) -> int:
    t = pd.Timestamp(ts_ns, tz="UTC").tz_convert(CHI)
    return t.hour * 60 + t.minute


class LongParityConfig(StrategyConfig, frozen=True):
    instrument_id: str = "NQ.XCME"
    bar_type_1s: str = C.BAR_1S
    bar_type_1m: str = C.BAR_1M
    emit_start_ns: int = 0        # candidates only logged at/after this instant
    emit_end_ns: int = 0          # ... and strictly before this instant
    trigger_threshold: float = -1.0   # <0 disables Layer B (threshold-free run)
    stop_atr_mult: float = C.STOP_ATR_MULT
    qty: int = 1


class LongParityStrategy(Strategy):
    def __init__(self, config: LongParityConfig):
        super().__init__(config)
        self._cfg = config
        self._inst_id = InstrumentId.from_str(config.instrument_id)

        chk = C.verify_frozen_model_inputs()
        self.feature_order = chk["feature_order"]
        self._model = LongModelRuntime(
            C.MODEL_PATH, C.COEFFICIENTS_PATH, C.INTERCEPT_PATH,
            self.feature_order, C.EXPECTED_MODEL_SHA256, C.sha256_file)

        self._engine = RegimeEngine()
        # TWO session rules, deliberately: the candidate tracker decides/fills on
        # 08:30-15:15, the FEATURE path uses the offline attach's 08:30-15:00.
        self._features = LongFeatureEngine(
            self.feature_order,
            is_rth_ts=lambda ts: C.is_rth_feature_minute(minute_of_day_chicago(ts)))
        self._tracker = CandidateTrackerLong(self._on_candidate, C.is_rth_minute_of_day)

        self._regime_dir = 0
        self._atr_frozen: Optional[float] = None   # frozen at the active regime's flip
        self._regime_flip_ts: Optional[int] = None
        self._last_1s_close: Optional[float] = None
        self._last_1s_ts: Optional[int] = None
        # Running 1m ATR AS OF THE SNAP BAR (see _on_1s). Not the same object as
        # `_atr_frozen`, and not the engine's live value at the observation.
        self._center_atr_at_snap: Optional[float] = None

        # ledgers
        self.candidates: list[dict] = []
        self.triggers: list[dict] = []
        self.trades: list[dict] = []
        self.waterfall = {"raw": 0, "established": 0, "decision_rth": 0,
                          "fill_rth": 0, "valid_fill": 0, "eligible": 0}

        # open position state (one trade per regime)
        self._attempted_regimes: set[int] = set()
        self._open: Optional[dict] = None
        self.bars_1s = 0
        self.bars_1m = 0

    # ------------------------------------------------------------------
    def on_start(self):
        self._bt_1s = BarType.from_str(self._cfg.bar_type_1s)
        self._bt_1m = BarType.from_str(self._cfg.bar_type_1m)
        self.subscribe_bars(self._bt_1s)
        self.subscribe_bars(self._bt_1m)

    def on_bar(self, bar: Bar):
        if bar.bar_type == self._bt_1s:
            self._on_1s(bar)
        elif bar.bar_type == self._bt_1m:
            self._on_1m(bar)

    # ------------------------------------------------------------------
    def _on_1s(self, bar: Bar):
        self.bars_1s += 1
        ts = int(bar.ts_event)
        o, h, l, c = float(bar.open), float(bar.high), float(bar.low), float(bar.close)
        v = float(bar.volume)
        mod = minute_of_day_chicago(ts)

        atr = self._engine.atr if self._engine.atr else 0.0

        # Manage an open position first (the stop was placed strictly earlier,
        # so evaluating it against this bar's own range is legitimate).
        if self._open is not None:
            self._check_stop(ts, h, l)

        # ORDER IS CRITICAL. Checkpoints due at observation instants T <= ts are
        # emitted BEFORE this bar is folded into any tracker.
        #
        # After the previous bar (ts_prev) was processed, every checkpoint with
        # T <= ts_prev had already been emitted, so any T emitted now satisfies
        #     ts_prev < T <= ts
        # which makes ts_prev exactly the "last completed 1s bar STRICTLY before
        # the observation" -- the snap bar the offline replay uses
        # (`searchsorted(ts, obs, side='left') - 1`). Feature state at this
        # moment therefore includes bars up to and including ts_prev and
        # excludes ts. Updating the trackers first (an earlier version of this
        # file) let the bar AT/AFTER the observation leak into the features:
        # a real, measured look-ahead.
        self._tracker.on_1s_bar(ts_ns=ts, high=h, low=l, close=c, minute_of_day=mod)

        # Only NOW fold this bar into the trackers. update_1s also runs the
        # minute-bucket rollover (price levels, RTH/regime accumulators) at the
        # offline position in the loop -- see LongFeatureEngine.update_1s.
        self._features.update_1s(ts, o, h, l, c, v, self._regime_dir, atr)

        self._last_1s_close, self._last_1s_ts = c, ts
        # The offline atlas merged the running 1m ATR onto the 1s frame with
        # `close_ts <= t`, and the center features were read at the SNAP bar.
        # `self._engine.atr` read at the observation instant is one 1m bar
        # newer whenever the observation lands on a minute boundary -- which was
        # 100% of the aligned_price_minus_center_* mismatches (0% elsewhere).
        # Recording it here pins it to the bar, not to the observation.
        self._center_atr_at_snap = atr if atr else None

    # ------------------------------------------------------------------
    def _on_1m(self, bar: Bar):
        """REGIME DETECTION ONLY.

        The 1m bar drives the regime series (and nothing else) because that is
        the one thing the offline pipeline also took from 1m data. Price
        levels, RTH accumulators and the regime reset are driven from the 1s
        stream's own minute buckets inside LongFeatureEngine -- feeding them the
        catalog 1m bar here put them one bucket ahead of the offline replay and
        broke 9 of the 25 features. See common.minute_bucket_key.
        """
        self.bars_1m += 1
        close_ts = int(bar.ts_init)
        h, l, c = float(bar.high), float(bar.low), float(bar.close)

        prev_dir = self._regime_dir
        new_dir = self._engine.update(h, l, c)
        atr = self._engine.atr

        if new_dir != 0 and new_dir != prev_dir:
            # Regime flip confirmed at this 1m close.
            self._regime_dir = new_dir
            self._regime_flip_ts = close_ts
            self._atr_frozen = float(atr) if atr and atr > 0 else None
            self._features.declare_regime_start(close_ts)
            # Opposing-flip exit for any open long: a bullish flip ends it.
            if self._open is not None and new_dir == +1:
                self._close_trade(close_ts, c, "opposing_regime_flip")
            self._tracker.on_regime_flip(close_ts, new_dir, c,
                                         self._atr_frozen if self._atr_frozen else 0.0)
        else:
            self._regime_dir = new_dir

    # ------------------------------------------------------------------
    def _on_candidate(self, cand: dict):
        """Called for EVERY 5s grid point of an active bearish regime, eligible
        or not. Waterfall stages are counted separately -- never collapsed."""
        T = cand["observation_time_ns"]
        in_window = self._cfg.emit_start_ns <= T < self._cfg.emit_end_ns
        eligible = cand["final_candidate_eligible"]

        # EVERY waterfall stage is gated to the emit window, including `raw`.
        # Bars are loaded from the Feb warmup start, so ungated counters mix
        # warmup candidates into a total that is then printed next to the
        # March-only offline waterfall -- an earlier version did exactly that
        # and reported eligible=28,894 against offline's 15,234, which reads as
        # catastrophic population failure when the real gap is 2.25%.
        if not in_window:
            return

        self.waterfall["raw"] += 1
        if cand["established_regime_gate"]:
            self.waterfall["established"] += 1
        if cand.get("decision_rth"):
            self.waterfall["decision_rth"] += 1
        if cand.get("fill_rth"):
            self.waterfall["fill_rth"] += 1
        if cand.get("valid_fill"):
            self.waterfall["valid_fill"] += 1
        if eligible:
            self.waterfall["eligible"] += 1

        row = {
            "regime_id": cand["regime_start_ns"],
            "regime_start_ns": cand["regime_start_ns"],
            "regime_direction": cand["regime_direction"],
            "entry_direction": cand["entry_direction"],
            "flip_ts": cand["regime_start_ns"],
            "observation_ts": T,
            "checkpoint_index": cand["checkpoint_index"],
            "regime_age_seconds": cand["regime_age_s"],
            "decision_ts": T,
            "intended_fill_ts": cand.get("fill_ts_ns"),
            "decision_rth": cand.get("decision_rth"),
            "fill_rth": cand.get("fill_rth"),
            "valid_fill": cand.get("valid_fill"),
            "final_candidate_eligible": eligible,
            "rejection_reason": cand["rejection_reason"],
            "latest_source_ts_used": self._last_1s_ts,
            "running_mfe_atr": cand["running_mfe_atr"],
            "running_mae_atr": cand["running_mae_atr"],
            "current_pnl_atr": cand["current_pnl_atr"],
            "new_progress_windows": cand["new_progress_windows"],
            "retained_mfe_ratio": cand["retained_mfe_ratio"],
            "atr_at_entry": cand["atr_val"],
        }

        if eligible:
            # STRICT CAUSALITY INVARIANT: the newest source bar folded into any
            # feature must be strictly before the observation instant.
            if self._last_1s_ts is not None and not (self._last_1s_ts < T):
                raise RuntimeError(
                    f"CAUSALITY VIOLATION: latest_source_ts_used={self._last_1s_ts} "
                    f">= observation_time={T}")
            # snap bar = the last completed 1s bar strictly before T, which is
            # the previous bar (see the ordering note in _on_1s).
            snap_ts, ref_px = self._last_1s_ts, self._last_1s_close
            vec, null_mask, _ = self._features.ordered_vector(
                snap_ts, T, ref_px, cand["atr_val"], self._regime_dir,
                center_atr=(self._center_atr_at_snap or cand["atr_val"]))
            out = self._model.score_both(vec)
            row["score"] = out["probability_joblib"]
            row["score_explicit"] = out["probability"]
            row["logit"] = out["logit"]
            row["n_imputed"] = out["n_imputed"]
            row["reference_price"] = ref_px
            for f, val in zip(self.feature_order, vec):
                row[f"feat__{f}"] = val
            for f, contrib in zip(self.feature_order, out["contributions"]):
                row[f"contrib__{f}"] = float(contrib)
            self._maybe_trigger(row, cand)

        self.candidates.append(row)

    # ------------------------------------------------------------------
    def _maybe_trigger(self, row: dict, cand: dict):
        thr = self._cfg.trigger_threshold
        if thr < 0:
            return  # Layer A: threshold-free parity run
        rid = cand["regime_start_ns"]
        crossed = row["score"] >= thr
        if not crossed:
            return
        if rid in self._attempted_regimes:
            self.triggers.append({"regime_id": rid, "observation_ts": row["observation_ts"],
                                  "score": row["score"], "accepted": False,
                                  "rejection_reason": "duplicate_suppressed_one_per_regime"})
            return
        if self._open is not None:
            self.triggers.append({"regime_id": rid, "observation_ts": row["observation_ts"],
                                  "score": row["score"], "accepted": False,
                                  "rejection_reason": "position_already_open"})
            return
        self._attempted_regimes.add(rid)
        self.triggers.append({"regime_id": rid, "observation_ts": row["observation_ts"],
                              "score": row["score"], "accepted": True,
                              "rejection_reason": None})
        self._enter(row, cand)

    def _enter(self, row: dict, cand: dict):
        atr = float(cand["atr_val"])
        fill_px = float(self._last_1s_close)
        stop_px = fill_px - self._cfg.stop_atr_mult * atr   # LONG: stop below
        order = self.order_factory.market(
            instrument_id=self._inst_id, order_side=OrderSide.BUY,
            quantity=Quantity.from_int(self._cfg.qty), time_in_force=TimeInForce.FOK)
        self.submit_order(order)
        self._open = {
            "regime_id": cand["regime_start_ns"],
            "trigger_ts": row["observation_ts"],
            "order_submitted_ts": row["observation_ts"],
            "side": "BUY", "qty": self._cfg.qty,
            "fill_ts": self._last_1s_ts, "fill_px": fill_px,
            "atr_snapshot": atr, "stop_px": stop_px,
            "score": row["score"],
            "client_order_id": str(order.client_order_id),
        }

    def _check_stop(self, ts: int, high: float, low: float):
        if low <= self._open["stop_px"]:
            self._close_trade(ts, self._open["stop_px"], "fixed_stop")

    def _close_trade(self, ts: int, px: float, reason: str):
        t = dict(self._open)
        t.update({"exit_ts": ts, "exit_px": float(px), "exit_reason": reason,
                  "points": float(px) - t["fill_px"]})
        self.trades.append(t)
        self._open = None
        # Flatten in NT as well so the portfolio reflects the exit.
        try:
            self.close_all_positions(self._inst_id)
        except Exception:
            pass

    def on_stop(self):
        if self._open is not None and self._last_1s_ts is not None:
            self._close_trade(self._last_1s_ts, self._last_1s_close, "run_end_open")
