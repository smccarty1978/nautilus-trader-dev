"""NT strategy for the Fable 5 pre-flip D10 reversal study (policies P0-P4B).

Timing model (see SPEC.md):
- 1m regime flips are known at the flip bar CLOSE (1m bar processed at
  ts_init == close time). The regime engine is an exact port of
  regime_sequence_chop_context/reproduce_regimes.py (EMA3/9 sticky on H/L/C,
  Wilder ATR14) and is seeded fresh from the first 1m bar fed to the engine
  (runner feeds from Jan 1, matching the atlas construction).
- A W4 checkpoint score at observation_time=T is causally available once the
  last 1s bar with OPEN <= T has completed. Checkpoints are dispatched by a
  sorted pointer sweep: while processing the 1s bar with ts_event == E
  (ts_init == E+1s), every not-yet-dispatched checkpoint with obs <= E fires.
  For obs == E that is the classic T+1s availability; for obs on a quiet
  second (no bar at obs — common in ETH) it is the first bar boundary after
  obs, which is also the first executable moment. An exact-key lookup would
  silently drop ~40% of ETH checkpoints (completion-audit CRITICAL).
- Decisions submit 1-lot FOK market orders which fill IMMEDIATELY at the
  decision boundary against the just-completed 1s bar's close — the event
  loop's actual executable price (verified by test_fill_fixture.py).
- Stops are resting GTC stop-market reduce-only orders (event-loop handled).
  NT fills a stop at its trigger price even when the bar gaps through it;
  analyze.py conservatively reprices those fills to the fill bar's open.

Policies:
  P0  : flip entry -> next opposite flip exit (always-in after warmup).
  P1  : old-regime D10 entry -> stop only until confirmation -> flip exit.
  P2  : flip entry -> own-regime first D10 or next opposite flip exit.
  P3  : old-regime D10 entry -> stop until confirmation -> confirmed-regime
        first D10 or next opposite flip exit. Stop active whole trade.
  P4A : placebo entries with P1 exits.  P4B: placebo entries with P3 exits.

Flip rollovers (P0/P2): market fills are instantaneous at the decision
boundary (fixture-verified), so the rollover entry is submitted inside the
exit-fill callback — it fills at the same boundary price/timestamp as the
exit, and no entry can ever precede its paired exit.

Runtime parity: every observed 1m flip is logged (flip_log) and analyze.py
fail-fast compares the runtime flip stream (catalog-fed) against the offline
regime table (raw-fed) — the two data sources are byte-identical on smoke
checks, and this gate turns any silent divergence into a hard failure.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import ClientOrderId, InstrumentId
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.trading.strategy import Strategy

NS_PER_S = 1_000_000_000
TICK = 0.25


def tick_round(v: float) -> float:
    return round(v / TICK) * TICK


class RegimeEngine:
    """Exact port of regime_sequence_chop_context RegimeEngine."""
    ALPHA3 = 0.5
    ALPHA9 = 0.2
    ATR_P = 14

    def __init__(self) -> None:
        self.ema3_h = self.ema9_h = self.ema3_l = self.ema9_l = None
        self.prev_c = None
        self.atr_warmup: list[float] = []
        self.atr: Optional[float] = None
        self.regime = 0

    def update(self, h: float, l: float, c: float) -> int:
        if self.ema3_h is None:
            self.ema3_h = self.ema9_h = h
            self.ema3_l = self.ema9_l = l
        else:
            self.ema3_h = self.ALPHA3 * h + (1 - self.ALPHA3) * self.ema3_h
            self.ema9_h = self.ALPHA9 * h + (1 - self.ALPHA9) * self.ema9_h
            self.ema3_l = self.ALPHA3 * l + (1 - self.ALPHA3) * self.ema3_l
            self.ema9_l = self.ALPHA9 * l + (1 - self.ALPHA9) * self.ema9_l
        tr = h - l if self.prev_c is None else max(
            h - l, abs(h - self.prev_c), abs(l - self.prev_c))
        self.prev_c = c
        if self.atr is None:
            self.atr_warmup.append(tr)
            if len(self.atr_warmup) == self.ATR_P:
                self.atr = sum(self.atr_warmup) / self.ATR_P
                self.atr_warmup = []
        else:
            self.atr = (self.atr * (self.ATR_P - 1) + tr) / self.ATR_P
        new = self.regime
        if c > self.ema3_h and c > self.ema9_h:
            new = 1
        elif c < self.ema3_l and c < self.ema9_l:
            new = -1
        if new != 0 and new != self.regime:
            self.regime = new
        return self.regime


class D10ReversalConfig(StrategyConfig, frozen=True):
    instrument_id: str = "NQ.XCME"
    bar_type_1s: str = "NQ.XCME-1-SECOND-LAST-EXTERNAL"
    bar_type_1m: str = "NQ.XCME-1-MINUTE-LAST-EXTERNAL"
    year: int = 2025
    policy: str = "P0"           # P0/P1/P2/P3/P4A/P4B
    stop_atr: float = 0.0        # 0 = no stop (P0/P2)
    threshold: float = 0.0
    trade_start_ns: int = 0
    trade_end_ns: int = 0
    score_path: str = ""
    placebo_path: str = ""       # only for P4A/P4B


class D10ReversalStrategy(Strategy):
    def __init__(self, config: D10ReversalConfig):
        super().__init__(config)
        self._cfg = config
        self._inst_id = InstrumentId.from_str(config.instrument_id)
        self._engine = RegimeEngine()

        self._pre_flip_policy = config.policy in ("P1", "P3", "P4A", "P4B")
        self._flip_entry_policy = config.policy in ("P0", "P2")
        self._d10_exit_policy = config.policy in ("P2", "P3", "P4B")
        self._placebo = config.policy in ("P4A", "P4B")
        if self._pre_flip_policy and config.stop_atr <= 0:
            raise ValueError("pre-flip policies require a stop")

        self._scores: dict[int, dict] = {}
        self._placebo_events: dict[int, dict] = {}
        # sorted dispatch queues (obs-ordered) + pointers
        self._score_obs: list[int] = []
        self._score_ptr = 0
        self._plc_obs: list[int] = []
        self._plc_ptr = 0

        # runtime regime state
        self._regime_dir = 0
        self._regime_start: Optional[int] = None
        self._regime_start_is_flip = False
        self._regime_seen_d10 = False
        self._attempted_regimes: set[int] = set()

        # trade / order state
        self._trade: Optional[dict] = None       # active (filled) trade
        self._pending_rollover_dir = 0           # P0/P2 flip rollover
        self._entry_order_id: Optional[str] = None
        self._pending_entry_meta: Optional[dict] = None
        self._exit_order_id: Optional[str] = None
        self._exit_reason_pending: Optional[str] = None
        self._exit_meta_pending: Optional[dict] = None
        self._exit_retry = False
        self._stop_order_id: Optional[str] = None
        self._last_1s_close: Optional[float] = None
        self._last_1s_ts_init: int = 0
        self._n_trades = 0

        self.trades: list[dict] = []
        self.flip_log: list[dict] = []
        self.entry_timing_log: list[dict] = []
        self.same_ts_log: list[dict] = []
        self.skip_log: list[dict] = []
        self.mismatch_count = 0
        self.lookup_hits = 0

    # ------------------------------------------------------------------ setup
    def on_start(self):
        self._bt_1s = BarType.from_str(self._cfg.bar_type_1s)
        self._bt_1m = BarType.from_str(self._cfg.bar_type_1m)
        self.subscribe_bars(self._bt_1s)
        self.subscribe_bars(self._bt_1m)

        df = pd.read_parquet(self._cfg.score_path)
        df = df[(df["year"] == self._cfg.year) & df["score_valid"]
                & df["w4_score"].notna()]
        for r in df.itertuples():
            self._scores[int(r.observation_time)] = {
                "direction": int(r.direction),
                "regime_start_ns": int(r.regime_start_ns),
                "score": float(r.w4_score),
                "atr": float(r.atr),
            }
        self._score_obs = sorted(self._scores)
        self.log.info(f"Loaded {len(self._scores):,} score checkpoints")

        if self._placebo:
            pf = pd.read_parquet(self._cfg.placebo_path)
            pf = pf[pf["year"] == self._cfg.year]
            for r in pf.itertuples():
                self._placebo_events[int(r.d10_obs_time)] = {
                    "regime_start_ns": int(r.regime_start_ns),
                    "old_direction": int(r.old_direction),
                    "entry_dir": int(r.entry_dir),
                    "atr": float(r.atr_at_d10),
                    "score": float(r.score),
                    "placebo_of": str(r.placebo_of),
                }
            self._plc_obs = sorted(self._placebo_events)
            self.log.info(f"Loaded {len(self._placebo_events):,} placebo events")

    # -------------------------------------------------------------- main loop
    def on_bar(self, bar: Bar):
        if bar.bar_type == self._bt_1s:
            self._on_1s(bar)
        elif bar.bar_type == self._bt_1m:
            self._on_1m(bar)

    def _on_1s(self, bar: Bar):
        obs = bar.ts_event  # score with observation_time == ts_event now available
        proc = bar.ts_init
        self._last_1s_close = float(bar.close)
        self._last_1s_ts_init = proc

        # excursion tracking (fill bar included: fills happen at this bar's
        # open, before on_bar is delivered)
        t = self._trade
        if t is not None and t.get("entry_px") is not None:
            atr = t["atr_entry"]
            d = t["entry_dir"]
            h, l = float(bar.high), float(bar.low)
            fav = (h - t["entry_px"]) / atr if d == 1 else (t["entry_px"] - l) / atr
            adv = (t["entry_px"] - l) / atr if d == 1 else (h - t["entry_px"]) / atr
            key = "post" if t["confirmed"] else "pre"
            t[f"{key}flip_mfe_atr"] = max(t[f"{key}flip_mfe_atr"], fav)
            t[f"{key}flip_mae_atr"] = max(t[f"{key}flip_mae_atr"], adv)

        # retry a failed exit FOK
        if self._exit_retry and self._trade is not None \
                and self._exit_order_id is None:
            self._exit_retry = False
            self._submit_exit(self._exit_reason_pending, self._exit_meta_pending)

        # ---- score / placebo triggers (sorted pointer sweep) ----
        # dispatch every checkpoint whose observation_time <= this bar's
        # ts_event: its last underlying bar has now completed, and this is
        # the first executable boundary at/after its availability time
        if self._placebo:
            while self._plc_ptr < len(self._plc_obs) \
                    and self._plc_obs[self._plc_ptr] <= obs:
                t_obs = self._plc_obs[self._plc_ptr]
                self._plc_ptr += 1
                self._handle_placebo_trigger(t_obs, proc,
                                             self._placebo_events[t_obs])
            if self._cfg.policy == "P4B":
                while self._score_ptr < len(self._score_obs) \
                        and self._score_obs[self._score_ptr] <= obs:
                    t_obs = self._score_obs[self._score_ptr]
                    self._score_ptr += 1
                    row = self._scores[t_obs]
                    if row["score"] >= self._cfg.threshold:
                        self._handle_d10_observation(t_obs, proc, row,
                                                     entry_ok=False)
            return

        while self._score_ptr < len(self._score_obs) \
                and self._score_obs[self._score_ptr] <= obs:
            t_obs = self._score_obs[self._score_ptr]
            self._score_ptr += 1
            self.lookup_hits += 1
            row = self._scores[t_obs]
            if row["score"] >= self._cfg.threshold:
                self._handle_d10_observation(t_obs, proc, row,
                                             entry_ok=self._pre_flip_policy)

    def _handle_d10_observation(self, obs: int, proc: int, row: dict,
                                entry_ok: bool):
        """First-crossing bookkeeping + entry/exit dispatch for a >=thr score."""
        is_current = row["regime_start_ns"] == self._regime_start
        was_first = False
        if is_current:
            was_first = not self._regime_seen_d10
            self._regime_seen_d10 = True

        # ---- exit relevance: confirmed-regime FIRST D10 (P2/P3/P4B) ----
        t = self._trade
        if (self._d10_exit_policy and t is not None and t["confirmed"]
                and t.get("entry_px") is not None
                and row["regime_start_ns"] == t["confirmed_regime_start"]):
            if not t.get("confirmed_regime_d10_seen", False):
                t["confirmed_regime_d10_seen"] = True
                if self._exit_order_id is not None or self._exit_retry:
                    self.same_ts_log.append({
                        "case": "d10_while_exit_in_flight", "obs": obs,
                        "proc": proc, "trade_id": t["trade_id"],
                        "score": row["score"], "chosen": "prior_exit",
                    })
                else:
                    self._submit_exit("d10_exit", {
                        "d10_exit_obs": obs,
                        "d10_exit_regime_start": row["regime_start_ns"],
                        "d10_exit_score": row["score"],
                    })
            return

        # ---- entry relevance: current-regime first D10 crossing (P1/P3) ----
        if not entry_ok:
            return
        if not is_current:
            if row["direction"] == self._regime_dir:
                self.mismatch_count += 1
            else:
                # old-regime checkpoint processed after its flip: the flip was
                # causally known first -> never a pre-flip entry
                self.same_ts_log.append({
                    "case": "d10_obs_after_flip", "obs": obs, "proc": proc,
                    "trade_id": None, "score": row["score"],
                    "chosen": "flip_first_no_entry",
                })
            return
        if not was_first:
            return
        self._try_enter(
            obs=obs, proc=proc, entry_dir=-self._regime_dir,
            origin_start=self._regime_start, origin_dir=self._regime_dir,
            atr=row["atr"], score=row["score"], placebo_of=None)

    def _handle_placebo_trigger(self, obs: int, proc: int, ev: dict):
        if ev["regime_start_ns"] != self._regime_start:
            # quiet-second donor dispatched after its regime already flipped:
            # benign staleness, skipped (NOT an identity mismatch)
            self.skip_log.append({"obs": obs, "reason": "placebo_regime_mismatch"})
            return
        self._try_enter(
            obs=obs, proc=proc, entry_dir=ev["entry_dir"],
            origin_start=ev["regime_start_ns"], origin_dir=ev["old_direction"],
            atr=ev["atr"], score=ev["score"], placebo_of=ev["placebo_of"])

    # ----------------------------------------------------------------- entries
    def _build_entry_meta(self, kind: str, placebo_of: Optional[str], obs: int,
                          proc: int, entry_dir: int, origin_start: int,
                          origin_dir: int, atr: float, score: float,
                          pre_flip: bool) -> dict:
        return {
            "kind": kind, "placebo_of": placebo_of,
            "signal_obs": obs, "submit_proc_ts": proc,
            "entry_dir": entry_dir,
            "origin_regime_start": origin_start,
            "origin_regime_dir": origin_dir,
            "atr_entry": atr, "signal_score": score,
            "pre_flip": pre_flip,
        }

    def _try_enter(self, obs: int, proc: int, entry_dir: int,
                   origin_start: int, origin_dir: int, atr: float,
                   score: float, placebo_of: Optional[str]):
        if not (self._cfg.trade_start_ns <= proc < self._cfg.trade_end_ns):
            self.skip_log.append({"obs": obs, "reason": "outside_window"})
            return
        if origin_start in self._attempted_regimes:
            self.skip_log.append({"obs": obs, "reason": "regime_attempt_used"})
            return
        if (self._trade is not None or self._entry_order_id is not None
                or self._exit_order_id is not None or self._exit_retry):
            self.skip_log.append({"obs": obs, "reason": "busy"})
            return
        if atr is None or not np.isfinite(atr) or atr <= 0:
            self.skip_log.append({"obs": obs, "reason": "bad_atr"})
            return
        self._attempted_regimes.add(origin_start)
        side = OrderSide.BUY if entry_dir == 1 else OrderSide.SELL
        order = self.order_factory.market(
            instrument_id=self._inst_id, order_side=side,
            quantity=Quantity.from_int(1), time_in_force=TimeInForce.FOK)
        self._entry_order_id = order.client_order_id.value
        self._pending_entry_meta = self._build_entry_meta(
            "placebo" if placebo_of else "real", placebo_of, obs, proc,
            entry_dir, origin_start, origin_dir, atr, score, pre_flip=True)
        self.submit_order(order)

    def _enter_on_flip(self, flip_ts: int, new_dir: int):
        """P0/P2 entry at the observed flip (fills instantly at the boundary
        price). For rollovers this is called from _close_trade, strictly
        AFTER the paired exit fill — the trade slot is guaranteed free."""
        if not (self._cfg.trade_start_ns <= flip_ts < self._cfg.trade_end_ns):
            return
        if self._entry_order_id is not None:
            self.skip_log.append({"obs": flip_ts, "reason": "entry_in_flight"})
            return
        if (self._trade is not None or self._exit_order_id is not None
                or self._exit_retry):
            self.skip_log.append({"obs": flip_ts, "reason": "busy_at_flip"})
            return
        if self._engine.atr is None or self._engine.atr <= 0:
            self.skip_log.append({"obs": flip_ts, "reason": "warmup"})
            return
        side = OrderSide.BUY if new_dir == 1 else OrderSide.SELL
        order = self.order_factory.market(
            instrument_id=self._inst_id, order_side=side,
            quantity=Quantity.from_int(1), time_in_force=TimeInForce.FOK)
        self._entry_order_id = order.client_order_id.value
        self._pending_entry_meta = self._build_entry_meta(
            "real", None, flip_ts, flip_ts, new_dir, flip_ts, new_dir,
            float(self._engine.atr), np.nan, pre_flip=False)
        self.submit_order(order)

    # -------------------------------------------------------------------- 1m
    def _on_1m(self, bar: Bar):
        prev = self._regime_dir
        new = self._engine.update(float(bar.high), float(bar.low),
                                  float(bar.close))
        flip = prev != 0 and new != 0 and new != prev
        self._regime_dir = new
        if not flip:
            if prev == 0 and new != 0:
                # initial regime out of warmup: not flip-born, no atlas keys
                self._regime_start = bar.ts_init
                self._regime_start_is_flip = False
                self._regime_seen_d10 = False
            return

        flip_ts = bar.ts_init  # flip known at close
        self._regime_start = flip_ts
        self._regime_start_is_flip = True
        self._regime_seen_d10 = False
        self._pending_rollover_dir = 0  # any unconsumed rollover is stale
        self.flip_log.append({"flip_ts": flip_ts, "direction": new,
                              "last_1s_ts_init": self._last_1s_ts_init})

        t = self._trade
        # audit: score checkpoint exactly at the flip timestamp (belongs to the
        # regime that just ended; flip is causally known 1s before the score)
        if not self._placebo:
            row = self._scores.get(flip_ts)
            if row is not None and row["score"] >= self._cfg.threshold \
                    and row["regime_start_ns"] != flip_ts:
                self.same_ts_log.append({
                    "case": "d10_obs_equals_flip_ts", "obs": flip_ts,
                    "proc": flip_ts, "trade_id": t["trade_id"] if t else None,
                    "score": row["score"], "chosen": "flip_first",
                })

        if t is not None and t.get("entry_px") is not None:
            if not t["confirmed"] and new == t["entry_dir"]:
                # anticipated flip confirms the pre-flip trade; the
                # executable price a flip entry would get at this boundary is
                # the last processed 1s close (fixture-verified fill model)
                t["confirmed"] = True
                t["confirm_flip_ts"] = flip_ts
                t["confirmed_regime_start"] = flip_ts
                t["confirmed_regime_d10_seen"] = False
                t["confirm_px"] = self._last_1s_close
                t["confirm_px_ts"] = flip_ts
                # empirical check of the 1s-before-1m dispatch assumption:
                # 0 means the 1s bar ending at the flip boundary was already
                # processed (analyze.py gates on this)
                t["confirm_px_lag_s"] = (flip_ts - self._last_1s_ts_init) / 1e9
            elif t["confirmed"] and new == -t["entry_dir"]:
                # opposite flip ends the confirmed regime -> natural exit;
                # the rollover entry is submitted only once the exit FILLS
                # (instant fills make it the same boundary price)
                if self._exit_order_id is None and not self._exit_retry:
                    self._submit_exit("opposite_regime_flip_exit",
                                      {"exit_flip_ts": flip_ts})
                    if self._flip_entry_policy:
                        self._pending_rollover_dir = new
            elif not t["confirmed"] and new == -t["entry_dir"]:
                self.log.error(f"Impossible flip sequence at {flip_ts}")
        elif t is None and self._flip_entry_policy:
            self._enter_on_flip(flip_ts, new)

    # ------------------------------------------------------------------ exits
    def _submit_exit(self, reason: str, meta: Optional[dict]):
        t = self._trade
        if t is None or t.get("entry_px") is None:
            return
        if self._exit_order_id is not None:
            return
        # cancel resting stop first: the exit decision is made causally at a
        # completed-bar boundary and fills at the next bar open, ahead of any
        # intrabar stop trigger of that bar
        self._cancel_stop()
        side = OrderSide.SELL if t["entry_dir"] == 1 else OrderSide.BUY
        order = self.order_factory.market(
            instrument_id=self._inst_id, order_side=side,
            quantity=Quantity.from_int(1),
            time_in_force=TimeInForce.FOK, reduce_only=True)
        self._exit_order_id = order.client_order_id.value
        self._exit_reason_pending = reason
        self._exit_meta_pending = meta or {}
        t.setdefault("exit_decision_ts", self.clock.timestamp_ns())
        self.submit_order(order)

    def _cancel_stop(self):
        if self._stop_order_id is None:
            return
        o = self.cache.order(ClientOrderId(self._stop_order_id))
        if o is not None and not o.is_closed:
            self.cancel_order(o)
        self._stop_order_id = None

    # ------------------------------------------------------------ order events
    def on_order_filled(self, event):
        cid = event.client_order_id.value
        px = float(event.last_px)

        if cid == self._entry_order_id:
            meta = self._pending_entry_meta
            self._entry_order_id = None
            self._pending_entry_meta = None
            self._n_trades += 1
            t = {
                "trade_id": f"{self._cfg.policy}_{self._cfg.year}_"
                            f"{self._n_trades}",
                "policy": self._cfg.policy,
                "stop_mult": self._cfg.stop_atr,
                "year": self._cfg.year,
                **meta,
                "entry_fill_ts": int(event.ts_event),
                "entry_px": px,
                "confirmed": not meta["pre_flip"],
                "confirm_flip_ts": None if meta["pre_flip"]
                                   else meta["signal_obs"],
                "confirmed_regime_start": None if meta["pre_flip"]
                                          else meta["origin_regime_start"],
                "confirmed_regime_d10_seen": False,
                "confirm_px": None if meta["pre_flip"] else px,
                "confirm_px_ts": None if meta["pre_flip"]
                                 else int(event.ts_event),
                "preflip_mfe_atr": 0.0, "preflip_mae_atr": 0.0,
                "postflip_mfe_atr": 0.0, "postflip_mae_atr": 0.0,
                "stop_px": None,
                "exit_reason": None, "exit_px": None, "exit_fill_ts": None,
            }
            self.entry_timing_log.append({
                "trade_id": t["trade_id"], "signal_obs": meta["signal_obs"],
                "submit_proc_ts": meta["submit_proc_ts"],
                "entry_fill_ts": int(event.ts_event), "entry_px": px,
                "pre_flip": meta["pre_flip"],
            })
            assert self._trade is None, \
                "entry filled while another trade is open (state desync)"
            self._trade = t
            if self._cfg.stop_atr > 0 and meta["pre_flip"]:
                stop_px = tick_round(
                    px - meta["entry_dir"] * self._cfg.stop_atr
                    * meta["atr_entry"])
                side = OrderSide.SELL if meta["entry_dir"] == 1 else OrderSide.BUY
                so = self.order_factory.stop_market(
                    instrument_id=self._inst_id, order_side=side,
                    quantity=Quantity.from_int(1),
                    trigger_price=Price(stop_px, 2),
                    time_in_force=TimeInForce.GTC, reduce_only=True)
                self._stop_order_id = so.client_order_id.value
                t["stop_px"] = stop_px
                self.submit_order(so)
            return

        if cid == self._stop_order_id:
            self._stop_order_id = None
            t = self._trade
            if t is None:
                return
            reason = ("stop_after_flip" if t["confirmed"]
                      else "stop_before_flip")
            if self._exit_order_id is not None:
                self.same_ts_log.append({
                    "case": "stop_filled_with_exit_in_flight",
                    "obs": int(event.ts_event), "proc": int(event.ts_event),
                    "trade_id": t["trade_id"], "score": np.nan,
                    "chosen": "stop",
                })
            self._close_trade(reason, px, int(event.ts_event), {})
            return

        if cid == self._exit_order_id:
            self._exit_order_id = None
            reason = self._exit_reason_pending
            meta = self._exit_meta_pending or {}
            self._exit_reason_pending = None
            self._exit_meta_pending = None
            if self._trade is None:
                return
            self._close_trade(reason, px, int(event.ts_event), meta)
            return

    def _close_trade(self, reason: str, px: float, ts: int, meta: dict):
        t = self._trade
        t["exit_reason"] = reason
        t["exit_px"] = px
        t["exit_fill_ts"] = ts
        t.update(meta)
        t["pnl_pts"] = (px - t["entry_px"]) * t["entry_dir"]
        self._cancel_stop()
        self.trades.append(t)
        self._trade = None
        self._exit_retry = False
        self._exit_reason_pending = None
        self._exit_meta_pending = None
        # P0/P2 rollover: enter the new regime now that the exit has filled;
        # fills are instantaneous so this lands at the same boundary price
        if (self._flip_entry_policy and self._pending_rollover_dir != 0
                and reason == "opposite_regime_flip_exit"):
            d = self._pending_rollover_dir
            self._pending_rollover_dir = 0
            if self._regime_start is not None:
                self._enter_on_flip(self._regime_start, d)
        else:
            self._pending_rollover_dir = 0

    def _entry_failed(self, cid: str) -> bool:
        if cid == self._entry_order_id:
            self._entry_order_id = None
            self.skip_log.append({
                "obs": self._pending_entry_meta["signal_obs"]
                if self._pending_entry_meta else None,
                "reason": "entry_fok_failed"})
            self._pending_entry_meta = None
            return True
        return False

    def _exit_failed(self, cid: str) -> bool:
        if cid == self._exit_order_id:
            self._exit_order_id = None
            if self._trade is not None and self._trade.get("exit_reason") is None:
                self._exit_retry = True  # retry next 1s bar
            else:
                self._exit_reason_pending = None
                self._exit_meta_pending = None
            return True
        return False

    def on_order_rejected(self, event):
        cid = event.client_order_id.value
        if self._entry_failed(cid) or self._exit_failed(cid):
            return
        if cid == self._stop_order_id:
            self._stop_order_id = None
            self.log.error("Stop order rejected — trade unprotected")

    def on_order_canceled(self, event):
        cid = event.client_order_id.value
        if self._entry_failed(cid) or self._exit_failed(cid):
            return
        if cid == self._stop_order_id:
            self._stop_order_id = None

    def on_order_expired(self, event):
        self.on_order_canceled(event)

    def on_order_denied(self, event):
        cid = event.client_order_id.value
        if self._entry_failed(cid) or self._exit_failed(cid):
            return

    # ------------------------------------------------------------------- stop
    def on_stop(self):
        t = self._trade
        if t is not None and t.get("entry_px") is not None:
            t["exit_reason"] = "data_end_censored"
            t["exit_px"] = np.nan
            t["exit_fill_ts"] = None
            t["pnl_pts"] = np.nan
            self.trades.append(t)
        self._trade = None
        self.log.info(
            f"{self._cfg.policy} {self._cfg.year}: {len(self.trades)} trades, "
            f"{self.mismatch_count} regime mismatches, "
            f"{self.lookup_hits:,} score lookups")
