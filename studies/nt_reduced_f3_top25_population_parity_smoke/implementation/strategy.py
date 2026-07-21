"""NT event-driven strategy for the reduced-model (F3_top25_gbt_v1)
population-parity smoke study.

Wires together (all independently hand-tested/real-data-validated before
this file was written, per project pre-execution-test discipline):
  - RegimeEngine (reused verbatim from fable5_pre_flip_d10_reversal_entry) --
    live regime direction AND live ATR (self.atr).
  - CandidateTracker -- live established-regime candidate declaration.
  - ReducedFeatureEngine -- live 25-feature snapshot (OHLCVDeltaTracker +
    PriceLevelTracker, exact-match validated against real March 2025 data).
  - ModelRuntime -- persisted F3_top25_gbt_v1 scoring.
  - ThresholdPolicy -- frozen R5/R2.5 threshold application.
  - ParityLogger -- logs EVERY candidate, not just triggered/traded ones.
  - trade_state.FlipTradeState -- reused verbatim from the prior NT POC
    (fixed 1.25xATR stop, no timeout, opposing-flip exit).

Does NOT read stored offline scores, trigger flags, a precomputed
eligible-candidate schedule, or future information -- every candidate,
feature snapshot, score, and trigger decision is computed live, causally,
from the streamed 1s/1m bars only.
"""
from __future__ import annotations

import pickle
import sys
import time
from pathlib import Path
from typing import Optional

_ROOT = str(Path(__file__).resolve().parents[3])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
_POC = str(Path(_ROOT) / "studies" / "nt_pure_flip_trigger_poc_and_mirrored_long_model" / "phase2")
if _POC not in sys.path:
    sys.path.insert(0, _POC)

import numpy as np
import pandas as pd

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import ClientOrderId, InstrumentId
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.trading.strategy import Strategy

from studies.fable5_pre_flip_d10_reversal_entry.strategy import RegimeEngine, tick_round  # noqa: E402
from trade_state import (  # noqa: E402
    FlipTradeState, favorable_adverse_points, realized_favorable_atr, unrealized_pnl,
)
from candidate_tracker import CandidateTracker, is_rth_minute_of_day  # noqa: E402
from reduced_feature_engine import ReducedFeatureEngine  # noqa: E402
from model_runtime import ModelRuntime  # noqa: E402
from threshold_policy import ThresholdPolicy  # noqa: E402
from parity_logger import ParityLogger  # noqa: E402
import common as C  # noqa: E402

NS = 1_000_000_000


class ReducedModelSmokeConfig(StrategyConfig, frozen=True):
    instrument_id: str = "NQ.XCME"
    bar_type_1s: str = "NQ.XCME-1-SECOND-LAST-EXTERNAL"
    bar_type_1m: str = "NQ.XCME-1-MINUTE-LAST-EXTERNAL"
    variant_label: str = "R5"  # "R5" or "R2.5" -- which frozen threshold actually gates order submission
    model_path: str = ""
    feature_list_json_path: str = ""
    thresholds_path: str = ""
    stop_atr_mult: float = 1.25
    multiplier: float = 20.0
    cost_rt: float = 10.0
    rth_start_min: int = 8 * 60 + 30
    rth_end_min: int = 15 * 60
    log_only_month: str = ""  # e.g. "2025-03" -- restrict ParityLogger/trades to this month; "" = no restriction

    # Progress / checkpoint / resume (added for future long runs -- NOT yet
    # exercised end-to-end; see run_nt.py's own docstring for the caveat).
    checkpoint_dir: str = ""  # "" disables checkpointing entirely
    resume_state_path: str = ""  # "" = fresh start; otherwise path to a checkpoint .pkl to restore from
    total_days_estimate: int = 0  # for ETA display only; 0 = unknown, no ETA printed


def _minute_bucket_key(bar_ts: int) -> int:
    return (bar_ts - 1) // (60 * NS)


def _calendar_day_key(ts_ns: int) -> str:
    """UTC calendar-day boundary for progress/checkpoint granularity. Simpler
    and unambiguous compared to trading_day_key's 17:00 CT rollover -- good
    enough for progress reporting; does NOT change any causal/session logic
    elsewhere in this file."""
    return pd.Timestamp(ts_ns, unit="ns", tz="UTC").strftime("%Y-%m-%d")


class ReducedModelSmokeStrategy(Strategy):
    def __init__(self, config: ReducedModelSmokeConfig):
        super().__init__(config)
        self._cfg = config
        self._inst_id = InstrumentId.from_str(config.instrument_id)

        import json
        feat_list = json.loads(Path(config.feature_list_json_path).read_text())["F3_top25_gbt_v1"]["features"]
        self._model_runtime = ModelRuntime(Path(config.model_path), feat_list,
                                           C.EXPECTED_MODEL_SHA256, C.sha256_file)
        self._threshold_policy = ThresholdPolicy.from_frozen_file(Path(config.thresholds_path))
        self._feature_engine = ReducedFeatureEngine(feat_list)
        self._candidate_tracker = CandidateTracker(
            on_candidate=self._on_candidate, is_rth_fn=is_rth_minute_of_day)
        self._parity_logger = ParityLogger()
        self._engine = RegimeEngine()
        self._regime_dir = 0
        self._was_rth = False

        # 1s-bar buffering within the currently-forming minute, replayed into
        # feature_engine.accumulate_regime_rth once the confirming 1m bar
        # arrives (matches attach_features.py / CLAUDE.md invariant 4).
        self._current_minute: Optional[int] = None
        self._minute_o = self._minute_h = self._minute_l = None
        self._minute_buf: list[tuple[int, float, float, float, float]] = []
        self._prev_close: Optional[float] = None
        self._last_1m_close_ts: Optional[int] = None

        # one-trade-per-regime: regimes already attempted (order submitted),
        # regardless of subsequent position state.
        self._attempted_regimes: set[int] = set()

        self._trade: Optional[dict] = None
        self._state: Optional[FlipTradeState] = None
        self._entry_order_id: Optional[str] = None
        self._pending_meta: Optional[dict] = None
        self._exit_order_id: Optional[str] = None
        self._exit_reason_pending: Optional[str] = None
        self._exit_retry = False
        self._stop_order_id: Optional[str] = None
        self._n_trades = 0

        self.trades: list[dict] = []
        self.flips: list[dict] = []
        self.skips: list[dict] = []

        # -- progress / checkpoint / resume bookkeeping --
        self._wall_start = time.time()
        self._bars_processed_1s = 0
        self._bars_processed_1m = 0
        self._current_calendar_day: Optional[str] = None
        self._day_wall_start = self._wall_start
        self._completed_day_durations_s: list[float] = []
        self._n_days_completed = 0
        self._checkpoint_dir = Path(config.checkpoint_dir) if config.checkpoint_dir else None
        if self._checkpoint_dir:
            self._checkpoint_dir.mkdir(parents=True, exist_ok=True)

        if config.resume_state_path:
            self._restore_checkpoint(Path(config.resume_state_path))

    # ------------------------------------------------------------- setup
    def on_start(self):
        self._bt_1s = BarType.from_str(self._cfg.bar_type_1s)
        self._bt_1m = BarType.from_str(self._cfg.bar_type_1m)
        self.subscribe_bars(self._bt_1s)
        self.subscribe_bars(self._bt_1m)

    # ------------------------------------------------------------- bars
    def on_bar(self, bar: Bar):
        if bar.bar_type == self._bt_1s:
            self._on_1s(bar)
        elif bar.bar_type == self._bt_1m:
            self._on_1m(bar)

    def _in_rth(self, ts_ns: int) -> bool:
        t = pd.Timestamp(ts_ns, unit="ns", tz="UTC").tz_convert("America/Chicago")
        m = t.hour * 60 + t.minute
        return self._cfg.rth_start_min <= m < self._cfg.rth_end_min

    def _in_logged_month(self, ts_ns: int) -> bool:
        if not self._cfg.log_only_month:
            return True
        t = pd.Timestamp(ts_ns, unit="ns", tz="UTC")
        return t.strftime("%Y-%m") == self._cfg.log_only_month

    # ---------------------------------------- progress / checkpoint / resume
    def _maybe_report_and_checkpoint(self, ts: int) -> None:
        """Called once per 1s bar with that bar's day key. Detects a
        calendar-day boundary crossing, prints progress/throughput/ETA, and
        -- only when flat (no open trade; resuming mid-trade is not safe
        since NT's own order/position state is not part of the checkpoint)
        -- writes an atomic checkpoint."""
        day_key = _calendar_day_key(ts)
        if self._current_calendar_day is None:
            self._current_calendar_day = day_key
            return
        if day_key == self._current_calendar_day:
            return

        # Day boundary crossed.
        now = time.time()
        day_duration = now - self._day_wall_start
        self._completed_day_durations_s.append(day_duration)
        self._n_days_completed += 1
        self._day_wall_start = now
        finished_day = self._current_calendar_day
        self._current_calendar_day = day_key

        elapsed = now - self._wall_start
        avg_day_s = sum(self._completed_day_durations_s) / len(self._completed_day_durations_s)
        eta_str = "unknown"
        if self._cfg.total_days_estimate > 0:
            remaining_days = max(0, self._cfg.total_days_estimate - self._n_days_completed)
            eta_str = f"{remaining_days * avg_day_s / 60:.1f} min ({remaining_days} days left)"
        throughput_1s = self._bars_processed_1s / elapsed if elapsed > 0 else 0.0
        msg = (f"[{self._cfg.variant_label}] day {finished_day} complete "
              f"({self._n_days_completed} days done, {day_duration:.1f}s this day, "
              f"avg {avg_day_s:.1f}s/day) | elapsed={elapsed/60:.1f}min | "
              f"1s bars={self._bars_processed_1s:,} ({throughput_1s:.0f}/s) | "
              f"1m bars={self._bars_processed_1m:,} | "
              f"candidates={len(self._parity_logger.candidates):,} | trades={len(self.trades)} | "
              f"ETA={eta_str}")
        self.log.info(msg)
        print(msg)  # also to stdout -- self.log routing depends on LoggingConfig, print always visible

        is_flat = (self._trade is None and self._entry_order_id is None
                  and self._exit_order_id is None and not self._exit_retry)
        if self._checkpoint_dir is not None and is_flat:
            self._write_checkpoint(finished_day)

    def _write_checkpoint(self, last_completed_day: str) -> None:
        """Atomic: write to a temp path, then rename over the final path --
        never leaves a partially-written checkpoint that a resume could load."""
        state = {
            "last_completed_day": last_completed_day,
            "feature_engine": self._feature_engine, "candidate_tracker": self._candidate_tracker,
            "regime_engine": self._engine, "regime_dir": self._regime_dir, "was_rth": self._was_rth,
            "attempted_regimes": self._attempted_regimes, "n_trades": self._n_trades,
            "bars_processed_1s": self._bars_processed_1s, "bars_processed_1m": self._bars_processed_1m,
            "completed_day_durations_s": self._completed_day_durations_s,
            "n_days_completed": self._n_days_completed,
            "trades": self.trades, "flips": self.flips, "skips": self.skips,
            "candidates": self._parity_logger.candidates,
        }
        tmp_path = self._checkpoint_dir / f"checkpoint_{self._cfg.variant_label}.pkl.tmp"
        final_path = self._checkpoint_dir / f"checkpoint_{self._cfg.variant_label}.pkl"
        with open(tmp_path, "wb") as f:
            pickle.dump(state, f, protocol=pickle.HIGHEST_PROTOCOL)
        tmp_path.replace(final_path)  # atomic on the same filesystem
        manifest = {"last_completed_day": last_completed_day, "variant": self._cfg.variant_label,
                   "n_trades": len(self.trades), "n_candidates": len(self._parity_logger.candidates),
                   "checkpoint_path": str(final_path)}
        manifest_tmp = self._checkpoint_dir / f"checkpoint_{self._cfg.variant_label}_manifest.json.tmp"
        manifest_final = self._checkpoint_dir / f"checkpoint_{self._cfg.variant_label}_manifest.json"
        import json as _json
        manifest_tmp.write_text(_json.dumps(manifest, indent=2))
        manifest_tmp.replace(manifest_final)

    def _restore_checkpoint(self, path: Path) -> None:
        with open(path, "rb") as f:
            state = pickle.load(f)
        self._feature_engine = state["feature_engine"]
        self._candidate_tracker = state["candidate_tracker"]
        # Rebind both callbacks excluded by CandidateTracker.__getstate__
        # (bound methods of this Strategy are not picklable/portable).
        self._candidate_tracker._on_candidate = self._on_candidate
        self._candidate_tracker._is_rth_fn = is_rth_minute_of_day
        self._engine = state["regime_engine"]
        self._regime_dir = state["regime_dir"]
        self._was_rth = state["was_rth"]
        self._attempted_regimes = state["attempted_regimes"]
        self._n_trades = state["n_trades"]
        self._bars_processed_1s = state["bars_processed_1s"]
        self._bars_processed_1m = state["bars_processed_1m"]
        self._completed_day_durations_s = state["completed_day_durations_s"]
        self._n_days_completed = state["n_days_completed"]
        self.trades = state["trades"]
        self.flips = state["flips"]
        self.skips = state["skips"]
        self._parity_logger.candidates = state["candidates"]
        self.log.info(f"[{self._cfg.variant_label}] resumed from checkpoint: "
                      f"last_completed_day={state['last_completed_day']}, "
                      f"{len(self.trades)} trades, {len(self._parity_logger.candidates)} candidates so far")

    # ------------------------------------------------------------- 1s bars
    def _on_1s(self, bar: Bar):
        ts = int(bar.ts_init)
        o, h, l, c, v = float(bar.open), float(bar.high), float(bar.low), float(bar.close), float(bar.volume)
        self._bars_processed_1s += 1
        self._maybe_report_and_checkpoint(ts)

        # CRITICAL FIX (pre-execution audit): self._prev_close must reflect
        # THIS bar's own close BEFORE candidate_tracker.on_1s_bar() fires
        # below, because _on_candidate() is invoked SYNCHRONOUSLY from
        # within that call and reads self._prev_close as "current price" for
        # the live 25-feature snapshot. An earlier version set this at the
        # BOTTOM of _on_1s, making every candidate's reference_price stale
        # by one bar -- contradicting attach_features.py:259-260's `closes[i]`
        # (current bar, not previous) convention for feature computation.
        # Note this is intentionally DIFFERENT from CandidateTracker's own
        # internal `last_close` (the PRECEDING bar), which is correct for
        # the established-gate's current_pnl per build_weakness_atlas.py's
        # "last bar strictly before cp_ts" rule -- two distinct, both-correct
        # conventions for two different purposes, not a contradiction.
        self._prev_close = c

        b_est = self._feature_engine.update_1s(ts, o, h, l, c, v)

        mk = _minute_bucket_key(ts)
        if self._current_minute is None:
            self._current_minute = mk
            self._minute_o, self._minute_h, self._minute_l = o, h, l
            self._minute_buf = [(ts, h, l, v, b_est["bar_est_delta"])]
        elif mk == self._current_minute:
            self._minute_h = max(self._minute_h, h)
            self._minute_l = min(self._minute_l, l)
            self._minute_buf.append((ts, h, l, v, b_est["bar_est_delta"]))
        else:
            # A new minute's first 1s bar arrived without an intervening 1m
            # close event -- should not happen under add_bars_causal_order()
            # (1s always precedes its coincident 1m), but guard rather than
            # silently misattribute.
            self.log.warning(f"1s bar minute bucket advanced without 1m close: {ts}")
            self._current_minute = mk
            self._minute_o, self._minute_h, self._minute_l = o, h, l
            self._minute_buf = [(ts, h, l, v, b_est["bar_est_delta"])]

        # Trade excursion tracking (stop is a real resting stop_market order,
        # handled via on_order_filled -- not manually polled here).
        t, st = self._trade, self._state
        if t is not None and st is not None and not st.closed:
            self._track_excursion(t, st, bar, ts)
        if self._exit_retry and self._trade is not None and self._exit_order_id is None:
            self._exit_retry = False
            self._submit_exit(self._exit_reason_pending)

        # Candidate declaration: drives CandidateTracker with the bar just
        # closed. ATR is RegimeEngine.atr as of the most recent 1m close
        # (causally correct -- ATR only updates on 1m boundaries).
        minute_of_day = pd.Timestamp(ts, unit="ns", tz="UTC").tz_convert("America/Chicago")
        minute_of_day = minute_of_day.hour * 60 + minute_of_day.minute
        self._candidate_tracker.on_1s_bar(ts_ns=ts, high=h, low=l, close=c, minute_of_day=minute_of_day)

    # ------------------------------------------------------------- 1m bars
    def _on_1m(self, bar: Bar):
        ts = int(bar.ts_init)
        self._bars_processed_1m += 1
        # CRITICAL FIX (pre-execution audit): checking `self._minute_o is
        # None` only catches the very first bar of the loaded range --
        # self._minute_o is never reset to None afterward, so a genuine
        # MID-RUN gap (a minute with zero buffered 1s bars, e.g. a real
        # catalog gap -- this repo has documented catalog-gap history) would
        # silently reuse STALE OHLC from a previous, unrelated minute rather
        # than being caught. Compare self._current_minute (which minute the
        # buffered O/H/L actually belongs to) against THIS 1m bar's own
        # minute bucket. Only `update_1m`'s minute_o/h/l/prev_close inputs
        # actually depend on that buffer -- regime detection, ATR, flip
        # handling, and candidate declaration all use the 1m Bar's own
        # official OHLC (always trustworthy, from NT itself) and must NOT be
        # skipped just because the 1s-bar buffer is stale/missing.
        expected_minute = _minute_bucket_key(ts)
        buffer_matches_this_minute = (self._current_minute == expected_minute)
        if not buffer_matches_this_minute:
            self.log.warning(
                f"1m bar at {ts} (minute bucket {expected_minute}) has no matching "
                f"buffered 1s bars (buffer belongs to minute {self._current_minute}) -- "
                f"falling back to this bar's own official OHLC for update_1m only; "
                f"regime/candidate processing proceeds normally on the bar's own data")

        prev_regime = self._regime_dir
        new_regime = self._engine.update(float(bar.high), float(bar.low), float(bar.close))
        self._regime_dir = new_regime
        now_rth = self._in_rth(ts)

        # ORDER matches attach_features.py:222-246 EXACTLY (verified by
        # direct re-read after an earlier version of this file had this
        # backwards): reset regime FIRST on a flip, THEN RTH reset, THEN
        # accumulate this confirming minute's OWN buffered 1s bars -- so the
        # confirming minute's volume/delta attributes to whichever regime is
        # CONFIRMED as of this close (the NEW regime if a flip just
        # occurred), not the one that just ended.
        flip = prev_regime != 0 and new_regime != 0 and new_regime != prev_regime
        anchor = float(bar.open) if flip else None  # confirming minute's OWN open
        # Established-gate MFE/MAE excursion anchor -- NOT the same value as
        # `anchor` above. build_weakness_atlas.py:64-69 hard-asserts the
        # canonical established-gate anchor (`entry_open`) equals the raw 1s
        # bar's OPEN at the flip-confirmation instant (entry_ts_event ==
        # regime_start_ns == this 1m bar's ts_init/close time) -- i.e. the
        # confirming minute's CLOSE, not its open. Reusing `anchor` (the
        # minute's open, a full 60s earlier) here was a real bug found during
        # reconciliation: on a volatile confirming bar it let up to a
        # minute's worth of extra range leak into the MFE excursion,
        # registering regimes as "established" far earlier than the offline
        # reference (one regime: live established at T=125s vs offline's
        # true T=1030s, confirmed via raw-bar reconstruction). `anchor`
        # itself is unaffected and stays bar.open, matching the
        # separately-verified attach_features.py:175-194 feature convention.
        gate_anchor = float(bar.close) if flip else None
        if flip:
            self._feature_engine.reset_regime(ts, anchor)

        if now_rth and not self._was_rth:
            self._feature_engine.reset_rth(ts)
        elif not now_rth and self._was_rth:
            self._feature_engine.end_rth()
        self._was_rth = now_rth

        if buffer_matches_this_minute:
            for bts, bh, bl, bv, bd in self._minute_buf:
                self._feature_engine.accumulate_regime_rth(bts, bh, bl, bv, bd)
            minute_o, minute_h, minute_l = self._minute_o, self._minute_h, self._minute_l
        else:
            # No buffered 1s bars to accumulate for THIS minute (gap) --
            # accumulate_regime_rth is simply skipped for it (there is
            # nothing to attribute), and update_1m uses the bar's own
            # official open/high/low instead of stale buffered values.
            minute_o, minute_h, minute_l = float(bar.open), float(bar.high), float(bar.low)

        self._feature_engine.update_1m(ts, minute_o, minute_h, minute_l,
                                       self._prev_close if self._prev_close is not None else float(bar.open),
                                       now_rth)
        self._last_1m_close_ts = ts
        self._current_minute = None
        self._minute_buf = []

        if flip:
            self.flips.append({"flip_ts": ts, "direction": new_regime})
            self._candidate_tracker.on_regime_flip(ts, new_regime, gate_anchor, self._engine.atr)

            # Exit-side thesis tracking: entry_direction=-1 (short) theses a
            # bearish (-1) flip; the established-bullish (+1) regime that
            # just ENDED (prev_regime=+1 -> new_regime=-1) is what confirms
            # an OPEN short trade's thesis. The regime that just STARTED
            # (new_regime=+1, i.e. -1 -> +1) is the OPPOSING flip that exits
            # an already-thesis-confirmed short trade.
            t, st = self._trade, self._state
            if t is not None and st is not None and not st.closed:
                result = st.on_regime_update(new_regime, ts)
                if result == "opposing_flip_exit":
                    t["bullish_exit_flip_time"] = ts
                    if self._exit_order_id is None and not self._exit_retry:
                        self._submit_exit("opposing_flip_exit")
                elif st.bearish_flip_confirmed and t.get("bearish_flip_time") is None:
                    t["bearish_flip_time"] = ts

    # ------------------------------------------------------------- candidates
    def _on_candidate(self, c: dict) -> None:
        obs_ts = c["observation_time_ns"]
        regime_start_ns = c["regime_start_ns"]
        log_this = self._in_logged_month(obs_ts)
        established_regime_gate = c["established_regime_gate"]

        if not established_regime_gate:
            if log_this:
                self._parity_logger.log_candidate(
                    regime_start_ns=regime_start_ns, regime_direction=c["regime_direction"],
                    checkpoint_index=c["checkpoint_index"], observation_time_ns=obs_ts,
                    established_regime_gate=False, regime_age_s=c["regime_age_s"],
                    running_mfe_atr=c["running_mfe_atr"], running_mae_atr=c["running_mae_atr"],
                    current_pnl_atr=c["current_pnl_atr"], new_progress_windows=c["new_progress_windows"],
                    retained_mfe_ratio=c["retained_mfe_ratio"], decision_rth=None, fill_rth=None,
                    fill_ts=None, fill_px=None, atr_at_entry=None, valid_fill=None,
                    final_candidate_eligible=False, feature_values=None, null_mask=None,
                    score=None, r5_trigger=None, r2_5_trigger=None,
                    suppression_reason=c["suppression_reason"])
            return

        # decision_rth/fill_ts_ns/valid_fill are computed by CandidateTracker
        # itself now (fixed during reconciliation -- an earlier version
        # hardcoded fill_rth=None here and never actually computed it).
        decision_rth = c["decision_rth"]
        fill_ts_ns = c["fill_ts_ns"]
        valid_fill = c["valid_fill"]
        fill_dt_ct = pd.Timestamp(fill_ts_ns, unit="ns", tz="UTC").tz_convert("America/Chicago")
        fill_rth = is_rth_minute_of_day(fill_dt_ct.hour * 60 + fill_dt_ct.minute)

        # final_candidate_eligible, EXACT formula: established_regime_gate
        # AND decision_rth AND valid_fill (matches the offline reference's
        # own population definition -- entry_surface.py's established/RTH/
        # valid-fill funnel). fill_rth is computed and logged separately
        # (for the required attrition waterfall and as a disclosed
        # decision/fill RTH divergence diagnostic) but is NOT part of this
        # formula, per the reconciliation-gate fix's exact specification.
        final_candidate_eligible = bool(established_regime_gate and decision_rth and valid_fill)

        # Frozen at this regime's flip time (CandidateTracker's own atr_val,
        # never reassigned) -- NOT self._engine.atr, which keeps updating
        # live. Feeding a live-drifting ATR into the feature vector / stop
        # sizing here was a real bug found during reconciliation: it broke
        # feature/score/trade parity against the offline reference, which
        # freezes atr_at_entry per regime (entry_surface.py enforces this
        # with a hard nunique()==1 assertion upstream).
        atr = c["atr_val"]
        price_now = self._prev_close
        fill_px = price_now  # fill occurs at fill_ts_ns == the bar this checkpoint evaluated on
        vec, null_mask, any_null = self._feature_engine.ordered_vector(obs_ts, price_now, atr)
        score = None if any_null else self._model_runtime.score(vec)
        r5 = None if score is None else self._threshold_policy.r5_trigger(score)
        r2_5 = None if score is None else self._threshold_policy.r2_5_trigger(score)

        suppression = None
        active_trigger = r5 if self._cfg.variant_label == "R5" else r2_5
        if not final_candidate_eligible:
            suppression = "fails_rth_or_valid_fill_gate"
        elif score is None:
            suppression = "feature_unavailable"
        elif not active_trigger:
            suppression = None  # logged, simply below threshold -- not an error state
        elif regime_start_ns in self._attempted_regimes:
            suppression = "already_triggered_this_regime"
        elif self._trade is not None or self._entry_order_id is not None or self._exit_order_id is not None or self._exit_retry:
            suppression = "position_open_at_entry"

        if log_this:
            feat_dict = dict(zip(self._feature_engine.ordered_features, vec))
            self._parity_logger.log_candidate(
                regime_start_ns=regime_start_ns, regime_direction=c["regime_direction"],
                checkpoint_index=c["checkpoint_index"], observation_time_ns=obs_ts,
                established_regime_gate=True, regime_age_s=c["regime_age_s"],
                running_mfe_atr=c["running_mfe_atr"], running_mae_atr=c["running_mae_atr"],
                current_pnl_atr=c["current_pnl_atr"], new_progress_windows=c["new_progress_windows"],
                retained_mfe_ratio=c["retained_mfe_ratio"], decision_rth=decision_rth,
                fill_rth=fill_rth, fill_ts=fill_ts_ns, fill_px=fill_px, atr_at_entry=atr,
                valid_fill=valid_fill, final_candidate_eligible=final_candidate_eligible,
                feature_values=feat_dict, null_mask=null_mask, score=score, r5_trigger=r5, r2_5_trigger=r2_5,
                suppression_reason=suppression)

        if suppression is None and active_trigger:
            self._attempted_regimes.add(regime_start_ns)
            self._try_enter(regime_start_ns, obs_ts, atr)

    # ------------------------------------------------------------- orders
    def _try_enter(self, regime_start_ns: int, decision_ts: int, atr: float):
        if atr is None or not (atr > 0):
            self.skips.append({"signal_decision_ts": decision_ts, "reason": "bad_atr"})
            return
        side = OrderSide.SELL  # entry_direction = -1 always, this population
        order = self.order_factory.market(
            instrument_id=self._inst_id, order_side=side,
            quantity=Quantity.from_int(1), time_in_force=TimeInForce.FOK)
        self._entry_order_id = order.client_order_id.value
        self._pending_meta = {"regime_start_ns": regime_start_ns, "signal_decision_ts": decision_ts,
                              "atr": atr, "direction": -1}
        self.submit_order(order)

    def _submit_exit(self, reason: str):
        t = self._trade
        if t is None or self._exit_order_id is not None:
            return
        self._cancel_stop()
        side = OrderSide.BUY  # closing a short
        order = self.order_factory.market(
            instrument_id=self._inst_id, order_side=side,
            quantity=Quantity.from_int(1), time_in_force=TimeInForce.FOK, reduce_only=True)
        self._exit_order_id = order.client_order_id.value
        self._exit_reason_pending = reason
        self.submit_order(order)

    def _cancel_stop(self):
        if self._stop_order_id is None:
            return
        o = self.cache.order(ClientOrderId(self._stop_order_id))
        if o is not None and not o.is_closed:
            self.cancel_order(o)
        self._stop_order_id = None

    def on_order_filled(self, event):
        cid = event.client_order_id.value
        px = float(event.last_px)
        if cid == self._entry_order_id:
            self._on_entry_filled(px, int(event.ts_event))
        elif cid == self._stop_order_id:
            self._on_stop_filled(px, int(event.ts_event))
        elif cid == self._exit_order_id:
            self._on_exit_filled(px, int(event.ts_event))

    def _on_entry_filled(self, px: float, ts: int):
        meta = self._pending_meta
        self._entry_order_id = None
        self._pending_meta = None
        self._n_trades += 1
        atr = float(meta["atr"])
        direction = int(meta["direction"])
        state = FlipTradeState(entry_direction=direction, entry_px=px, atr=atr,
                               stop_atr_mult=self._cfg.stop_atr_mult)
        t = {
            "variant": self._cfg.variant_label, "trade_id": f"{self._cfg.variant_label}_{self._n_trades}",
            "regime_start_ns": int(meta["regime_start_ns"]),
            "entry_trigger_time": int(meta["signal_decision_ts"]), "entry_fill_time": int(ts),
            "entry_price": float(px), "atr_entry": atr, "fixed_stop_price": state.stop_px,
            "direction": direction, "bearish_flip_time": None, "bullish_exit_flip_time": None,
            "exit_fill_time": None, "exit_price": None, "exit_reason": None,
            "whole_trade_mfe_pts": 0.0, "whole_trade_mae_pts": 0.0,
        }
        assert self._trade is None, "entry filled with trade open (desync)"
        self._trade = t
        self._state = state

        side = OrderSide.BUY  # protective stop on a short is a BUY-stop above entry
        trig = tick_round(state.stop_px)
        so = self.order_factory.stop_market(
            instrument_id=self._inst_id, order_side=side,
            quantity=Quantity.from_int(1), trigger_price=Price(trig, 2),
            time_in_force=TimeInForce.GTC, reduce_only=True)
        self._stop_order_id = so.client_order_id.value
        self.submit_order(so)

    def _on_stop_filled(self, px: float, ts: int):
        self._stop_order_id = None
        st = self._state
        if st is None or st.closed:
            return
        reason = st.on_stop_touch()
        self._close(reason, px, ts)

    def _on_exit_filled(self, px: float, ts: int):
        self._exit_order_id = None
        reason = self._exit_reason_pending
        self._exit_reason_pending = None
        self._close(reason, px, ts)

    def _close(self, reason: str, px: float, ts: int):
        t, st = self._trade, self._state
        t["exit_reason"] = reason
        t["exit_price"] = float(px)
        t["exit_fill_time"] = int(ts)
        gross = (px - t["entry_price"]) * t["direction"] * self._cfg.multiplier
        t["gross_pnl"] = gross
        t["net_pnl"] = gross - self._cfg.cost_rt
        st.closed = True
        st.exit_reason = reason
        self._cancel_stop()
        self.trades.append(dict(t))
        self._trade = None
        self._state = None
        self._exit_retry = False

    def on_order_rejected(self, event):
        cid = event.client_order_id.value
        if cid == self._entry_order_id:
            self._entry_order_id = None
            self._pending_meta = None
            self.skips.append({"reason": "entry_fok_failed"})
        elif cid == self._exit_order_id:
            self._exit_order_id = None
            if self._trade is not None and self._trade.get("exit_reason") is None:
                self._exit_retry = True
        elif cid == self._stop_order_id:
            self._stop_order_id = None
            self.log.error(f"[{self._cfg.variant_label}] stop rejected -- trade unprotected")

    def on_order_denied(self, event):
        self.on_order_rejected(event)

    def on_order_canceled(self, event):
        cid = event.client_order_id.value
        if cid == self._stop_order_id:
            self._stop_order_id = None

    def on_order_expired(self, event):
        self.on_order_canceled(event)

    # ------------------------------------------------------------- helpers
    def _track_excursion(self, t: dict, st: FlipTradeState, bar: Bar, ts: int):
        ep, d = t["entry_price"], t["direction"]
        h, l = float(bar.high), float(bar.low)
        fav_pts, adv_pts = favorable_adverse_points(d, ep, h, l)
        t["whole_trade_mfe_pts"] = max(t["whole_trade_mfe_pts"], fav_pts)
        t["whole_trade_mae_pts"] = max(t["whole_trade_mae_pts"], adv_pts)

    def on_stop(self):
        self._cancel_stop()
        t = self._trade
        if t is not None:
            t["exit_reason"] = "end_of_data_exit"
            t["exit_price"] = np.nan
            t["exit_fill_time"] = None
            t["net_pnl"] = np.nan
            t["gross_pnl"] = np.nan
            self.trades.append(dict(t))
        self._trade = None
        self._state = None
        self.log.info(f"[{self._cfg.variant_label}] {len(self.trades)} trades, "
                      f"{len(self._parity_logger.candidates)} logged candidates")
