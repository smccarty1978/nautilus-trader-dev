"""CollectorV2Strategy — single NT strategy class with two modes.

Mode 1 (research logging):
  - emits FeatureSnapshot rows at candidate moments (regime flip,
    bar+1 confirmation check) and optionally on a fixed 30s
    checkpoint cadence
  - DOES NOT submit orders

Mode 2 (trading / backtest):
  - SAME feature/snapshot path as Mode 1 (snapshots emitted at
    same moments)
  - PLUS: when V_A confirmation passes and 5m alignment (if
    required) holds, submits a market entry; holds until causal
    opposing 1m regime flip; exits at next 1s bar after the flip
  - Records trades and links each trade back to the snapshot
    that triggered the entry decision via event_id

Key invariants:
  - decision_ts = bar.ts_init  (NEVER ts_event)
  - audit_provenance() runs before every snapshot.build()
  - on CausalityViolation: backtest raises (engine dies fail-fast);
    live mode would flatten + halt strategy (TODO when running live)

Reference strategy (V_A):
  - 1m HH/LL + momentum confirmation
  - Hold to opposing 1m regime flip (causal exit at flip bar's
    ts_init close, NT delivers exit on next 1s bar after that)
"""

from __future__ import annotations
from collections import deque
from dataclasses import asdict
from pathlib import Path
import sys
import numpy as np
import pandas as pd

# Repo root on path
_repo_root = Path(__file__).parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Quantity
from nautilus_trader.trading.strategy import Strategy

from utils.causality import CausalityViolation  # noqa: E402

from collectors.collector_v2.registry import (  # noqa: E402
    CompletedBarRegistry, SUPPORTED_TIMEFRAMES,
)
from collectors.collector_v2.aggregator import (  # noqa: E402
    TimeframeAggregator,
)
from collectors.collector_v2.regime_engine import (  # noqa: E402
    RegimeStateEngine,
)
from collectors.collector_v2.snapshot_builder import (  # noqa: E402
    FeatureSnapshotBuilder,
)


import pytz
CT = pytz.timezone("America/Chicago")
NQ_MULT = 20.0
COMMISSION = 5.0
TICK_COST = 5.0


class CollectorV2Config(StrategyConfig, frozen=True):
    instrument_id: str
    bar_type_1m: str
    bar_type_1s: str
    mode: str = "research"          # "research" | "trading"
    rth_only: bool = True
    rth_start_min: int = 510
    rth_end_min: int = 900
    position_size: int = 1
    require_5m_aligned: bool = False
    output_dir: str = ""
    # Optional: emit a snapshot on every 30s checkpoint as well as
    # on candidate moments. Default False.
    fixed_30s_snapshots: bool = False
    # Cost model — per-product. Defaults to NQ.
    multiplier: float = 20.0           # NQ=20, ES=50, YM=5
    tick_dollar: float = 5.0           # NQ=$5/tick, ES=$12.50, YM=$5
    commission_per_rt: float = 5.0     # round-trip commission
    # Microstructure gate: if > 0, require pre-entry flip2conf
    # directional efficiency >= this threshold at bar+1 confirmation.
    # Causal: computed from 1s bars in (flip_ts_init, decision_ts]
    # using the same _compute_micro_window helper that emits the
    # offline micro_pre snapshot — bit-perfect parity by construction.
    require_flip2conf_efficiency: float = 0.0
    # If True, emit a per-1s-bar trade tape during open trades.
    # Used for offline replay of mechanical exit rules without
    # re-running NT. Increases memory / output size proportional
    # to total open-trade-seconds across the run.
    emit_trade_tape: bool = False
    # HH/LL structural exit overlay (C_lock50_30s_5 family).
    # When enabled: track favorable HH/LL progression on completed
    # 30s buckets during open trade. After MFE >= min_mfe_atr AND
    # stall_buckets_30s consecutive 30s buckets without a new
    # favorable extreme, arm a STOP order at lock_pct * MFE-at-arm
    # above entry (long) or below entry (short). Fall through to
    # opposing 1m regime exit if not retraced.
    enable_hhll_exit: bool = False
    hhll_min_mfe_atr: float = 1.0
    hhll_stall_buckets_30s: int = 5
    hhll_lock_pct: float = 0.50
    # Live-tradable guardrails (CT minutes from midnight). 0 = off.
    # no_entry_after_min_ct: skip new V_A entries at/after this CT
    #   minute (e.g., 885 = 14:45 CT)
    # force_flat_at_min_ct: submit market exit on any open trade at/
    #   after this CT minute (e.g., 898 = 14:58 CT)
    no_entry_after_min_ct: int = 0
    force_flat_at_min_ct: int = 0
    # --- Added for studies/rank_filter_oos_validation NT validation ---
    # Entry-to-fill delay in nanoseconds, applied on top of decision_ts
    # (= bar+1 confirmation close). 0 (default) preserves all existing
    # callers' behavior exactly (immediate next-1s-open fill). Set to
    # 30_000_000_000 for the canonical 30-second delayed-activation
    # mechanic. Does not change confirmation, cancellation, or exit logic.
    entry_delay_ns: int = 0
    # Frozen, precomputed policy-filter skip set (decision_ts values, ns
    # since epoch UTC) for research-derived rank filters (e.g. R2/R4) whose
    # score/exemption features are computed upstream from cached research
    # tables, not recomputed inside the NT event loop (no retraining, no
    # new features -- this is a pass-through gate on an already-frozen
    # decision, applied at the same instant the decision is available:
    # confirmation-bar close). Empty tuple (default) = no filtering (R0).
    skip_decision_ts: tuple[int, ...] = ()


class CollectorV2Strategy(Strategy):

    def __init__(self, config: CollectorV2Config):
        super().__init__(config)
        self._cfg = config
        self._registry = CompletedBarRegistry()
        self._engines = {
            tf: RegimeStateEngine(tf, self._registry)
            for tf in SUPPORTED_TIMEFRAMES
        }
        self._aggregator = TimeframeAggregator(
            on_bucket_closed=self._on_bucket_closed,
            timeframes=SUPPORTED_TIMEFRAMES,
        )
        self._snapshot_builder = FeatureSnapshotBuilder(
            self._registry)

        # V_A state — track most recent 1m flip awaiting confirmation
        # {flip_ts_event, flip_ts_init, flip_h, flip_l, flip_c,
        #  direction}
        self._pending_flip: dict | None = None
        # Pending entry awaiting fill (after confirmation passes)
        # {fill_ts_target, direction, decision_event_id}
        self._pending_entry: dict | None = None
        # Open trade
        self._trade: dict | None = None

        # Frozen policy-filter skip set (see CollectorV2Config.skip_decision_ts).
        # Matched by NEAREST timestamp (not exact equality): the research
        # atlas's confirmation_ts is a clean calendar-minute boundary
        # (pandas resample), while NT's own decision_ts is the ts_init of
        # whichever real (possibly sparse) 1s bar actually triggered the
        # 1m-bucket close -- these differ by a few seconds in the common
        # case (confirmed empirically: median ~1-3s, matching the same
        # sparse-data-forward-fill pattern documented in this study's
        # Phase 1 delayed_entry_audit). A generous but bounded tolerance
        # avoids false negatives from this real, expected jitter while
        # still requiring a genuine nearby match (not an unrelated signal).
        self._skip_arr = np.array(
            sorted(int(x) for x in config.skip_decision_ts), dtype=np.int64)
        # BACKWARD-ONLY tolerance (fixed post lookahead-audit 2026-07-07):
        # only ever match decision_ts against a skip-list entry at or
        # before decision_ts. A bidirectional nearest-match could bind the
        # current decision to a skip-list entry from a LATER confirmation
        # event -- information that does not exist yet at decision_ts in a
        # live/causal system, i.e. a genuine look-ahead violation,
        # regardless of the full skip list being precomputed before the
        # backtest starts (what matters is whether the join at simulated
        # time T could be reproduced using only data <= T; a forward match
        # cannot). 20s (not the original 90s) is used because the observed
        # confirmation-timestamp jitter between the offline research atlas
        # and NT's real decision_ts is p95=8s, p99=19s (see
        # studies/rank_filter_oos_validation/results/delayed_entry_audit.parquet)
        # -- 20s comfortably covers that jitter while staying well below
        # the ~120s minimum natural spacing between distinct confirmation
        # events, avoiding accidental collision with an earlier, unrelated
        # signal.
        self._skip_match_tolerance_ns = 20_000_000_000  # 20s, backward-only

        # Outputs
        self._snapshots: list[dict] = []
        self._trades: list[dict] = []
        self._policy_skips: list[dict] = []       # confirmed signals the policy filter skipped
        self._pending_cancellations: list[dict] = []  # opposite flip before activation
        # 1s microstructure outputs (separate from FeatureSnapshot
        # to avoid bloating the dataclass with 50+ optional fields)
        self._micro_pre: list[dict] = []   # at bar1_check time
        self._micro_post: list[dict] = []  # at fill time

        # Buffer of recent closed 1s bars for microstructure feature
        # computation. Holds ~25 min so volume z-score against prior
        # 20m has headroom. Each entry: dict(ts_event, ts_init, o, h,
        # l, c, v).
        self._recent_1s_bars: deque = deque(maxlen=1500)
        # Per-1s-bar trade tape for offline mechanical exit replay.
        # One row per open-trade 1s bar. Causal: each row records
        # state ONLY for bars with ts_init >= entry_ts.
        self._trade_tape: list[dict] = []

        # Tracks last-seen 1m close in registry (for flip detection)
        self._last_seen_1m_close_ts: int = 0
        self._prev_1m_regime: int = 0
        # Holds the 1m bar event we received (ts_event indexed)
        # so we have access to bar OHLC in flip handler
        self._latest_1m_bar_data: dict | None = None

        # Diagnostics
        self._diag = {
            "1s_bars": 0,
            "1m_bars": 0,
            "buckets_closed_30s": 0,
            "buckets_closed_1m": 0,
            "buckets_closed_3m": 0,
            "buckets_closed_5m": 0,
            "rth_flips": 0,
            "bar1_checks": 0,
            "confirmations_passed_hhll_mom": 0,
            "rejected_5m_misaligned": 0,
            "rejected_low_flip2conf_efficiency": 0,
            "hhll_armed": 0,
            "hhll_exits": 0,
            "hhll_canceled": 0,
            "rejected_after_no_entry_cutoff": 0,
            "force_flat_exits": 0,
            "entries_filled": 0,
            "regime_exits": 0,
            "snapshots_emitted": 0,
            "rejected_by_policy_filter": 0,
            "pending_entry_canceled": 0,
        }

    # ---- Subscriptions ----
    def on_start(self):
        from nautilus_trader.model.data import BarType
        self.subscribe_bars(BarType.from_str(self._cfg.bar_type_1m))
        self.subscribe_bars(BarType.from_str(self._cfg.bar_type_1s))

    # ---- Bar dispatch ----
    def on_bar(self, bar):
        bt = str(bar.bar_type)
        if bt == self._cfg.bar_type_1s:
            self._on_1s_bar(bar)
        elif bt == self._cfg.bar_type_1m:
            self._on_1m_bar(bar)

    # ---- 1s bar: feed aggregator + react to bucket closes ----
    def _on_1s_bar(self, bar):
        self._diag["1s_bars"] += 1
        decision_ts = int(bar.ts_init)
        # Buffer the closed 1s bar for microstructure feature
        # computation. Causal: bar is already closed at ts_init so
        # any later read of this buffer respects source_close <=
        # decision_ts as long as the lookup uses ts_init <=
        # current decision_ts.
        self._recent_1s_bars.append({
            "ts_event": int(bar.ts_event),
            "ts_init": decision_ts,
            "o": float(bar.open),
            "h": float(bar.high),
            "l": float(bar.low),
            "c": float(bar.close),
            "v": (float(bar.volume)
                    if hasattr(bar, "volume") else 0.0),
        })
        # Feed aggregator with ts_event for bucket assignment.
        # The aggregator may close one or more buckets based on
        # ts_event; bucket close fires _on_bucket_closed which
        # updates the registry and engines.
        try:
            self._aggregator.on_1s_bar(
                int(bar.ts_event),
                float(bar.open), float(bar.high),
                float(bar.low), float(bar.close),
                float(bar.volume) if hasattr(bar, "volume") else 0.0,
            )
        except CausalityViolation as e:
            self._halt(f"CausalityViolation in aggregator: {e}")
            raise

        # Did the registry's 1m state advance? If so, this 1s bar
        # is the trigger that closed the 1m bucket — run V_A logic
        # with decision_ts = THIS 1s bar's ts_init.
        s_1m = self._registry.get("1m")
        if (s_1m is not None
                and s_1m.close_ts != self._last_seen_1m_close_ts):
            self._last_seen_1m_close_ts = s_1m.close_ts
            self._on_1m_bucket_closed(decision_ts)

        # While a trade is OPEN, update intra-trade running MFE/MAE
        # using THIS 1s bar (causal — 1s bar already closed at
        # decision_ts = bar.ts_init), and emit a path_checkpoint
        # snapshot every 30s post-entry.
        if self._trade is not None:
            self._update_open_trade(bar, decision_ts)
            # Live-tradable guardrail: force flat at cutoff CT min.
            # Bypass HH/LL — submit market exit immediately.
            if (self._cfg.force_flat_at_min_ct > 0
                    and self._trade is not None
                    and self._trade.get("entry_ts") is not None
                    and self._trade.get(
                        "exit_order_id") is None):
                ct = pd.Timestamp(int(decision_ts),
                                      tz="UTC").tz_convert(CT)
                min_ct = ct.hour * 60 + ct.minute
                if min_ct >= self._cfg.force_flat_at_min_ct:
                    d = self._trade["direction"]
                    side = (OrderSide.SELL if d == 1
                            else OrderSide.BUY)
                    qty = Quantity.from_int(
                        self._cfg.position_size)
                    order = self.order_factory.market(
                        instrument_id=InstrumentId.from_str(
                            self._cfg.instrument_id),
                        order_side=side, quantity=qty,
                        time_in_force=TimeInForce.FOK,
                        reduce_only=True)
                    self._trade["exit_order_id"] = (
                        order.client_order_id.value)
                    self._trade["exit_reason"] = "force_flat"
                    self._diag["force_flat_exits"] += 1
                    self.submit_order(order)
        # Cancel pending entry if past no-entry cutoff
        if (self._cfg.no_entry_after_min_ct > 0
                and self._pending_entry is not None):
            ct = pd.Timestamp(int(decision_ts),
                                  tz="UTC").tz_convert(CT)
            min_ct = ct.hour * 60 + ct.minute
            if min_ct >= self._cfg.no_entry_after_min_ct:
                self._pending_entry = None

        # Check pending entry AT BAR TS_INIT (NT delivery time).
        # Submit market order ~1s before fill_ts_target so it
        # fills at the target bar's open.
        if (self._pending_entry is not None
                and self._trade is None
                and decision_ts >= (
                    self._pending_entry["fill_ts_target"]
                    - 1_000_000_000)):
            self._submit_entry()

    # ---- Intra-trade running MFE/MAE + path checkpoints ----
    def _update_open_trade(self, bar, decision_ts):
        t = self._trade
        if t.get("entry_ts") is None or t.get("fill_price") is None:
            return  # haven't filled yet
        d = t["direction"]
        ep = t["fill_price"]
        h = float(bar.high); l = float(bar.low)
        c = float(bar.close)
        # Running MFE/MAE in price points (not ATR)
        if d == 1:
            mfe = h - ep
            mae = ep - l
        else:
            mfe = ep - l
            mae = h - ep
        if mfe > t.get("running_mfe", -1e9):
            t["running_mfe"] = mfe
            t["t_running_mfe_ts"] = decision_ts
        if mae > t.get("running_mae", -1e9):
            t["running_mae"] = mae
            t["t_running_mae_ts"] = decision_ts
        t["last_close_price"] = c
        t["last_close_ts"] = decision_ts

        # HH/LL structural exit overlay
        if self._cfg.enable_hhll_exit:
            if not t.get("hhll_armed", False):
                atr = t.get("atr_at_signal", 0.0) or 0.0
                if atr > 0:
                    mfe_atr = t["running_mfe"] / atr
                    stall = t.get("hhll_stall_count_30s", 0)
                    if (mfe_atr >= self._cfg.hhll_min_mfe_atr
                            and stall >= self._cfg.hhll_stall_buckets_30s):
                        self._arm_hhll_protection(decision_ts)
            # If armed, check whether THIS bar crossed the protect
            # level (fires market exit on cross — internal monitor)
            if t.get("hhll_armed", False):
                self._check_hhll_protect_trigger(bar, decision_ts)

        # Per-1s-bar tape for offline mechanical exit replay
        if self._cfg.emit_trade_tape:
            atr = t.get("atr_at_signal", 0.0) or 1.0
            elapsed = (decision_ts - t["entry_ts"]) / 1e9
            self._trade_tape.append({
                "decision_event_id": int(
                    t.get("decision_event_id", -1)),
                "ts_init": int(decision_ts),
                "elapsed_s": float(elapsed),
                "h": float(h), "l": float(l), "c": float(c),
                "mfe_pts": float(t["running_mfe"]),
                "mae_pts": float(t["running_mae"]),
                "pnl_pts": float((c - ep) * d),
                "atr_at_signal": float(atr),
                "direction": int(d),
                "entry_price": float(ep),
            })

        # Emit a path_checkpoint snapshot every 30s post-entry
        elapsed = decision_ts - t["entry_ts"]
        if elapsed < 30 * 1_000_000_000:
            return
        next_cp = t.get("next_path_cp_ts", 0)
        if decision_ts < next_cp:
            return
        # Time for a checkpoint
        atr = t.get("atr_at_signal", float("nan"))
        safe_atr = atr if atr and atr > 0 else 1.0
        cur_pnl = (c - ep) * d
        snap = self._snapshot_builder.build(
            decision_ts=decision_ts,
            bar_ts_event=int(bar.ts_event),
            kind="path_checkpoint",
            direction=int(d),
            trade_event_id=int(t.get("decision_event_id", -1)),
            trade_direction=int(d),
            trade_fill_price=float(ep),
            trade_fill_ts=int(t["entry_ts"]),
            trade_atr_at_signal=float(atr) if atr else float("nan"),
            elapsed_s=float(elapsed) / 1e9,
            cur_pnl_atr=float(cur_pnl / safe_atr),
            cur_mfe_atr=float(t["running_mfe"] / safe_atr),
            cur_mae_atr=float(t["running_mae"] / safe_atr),
            cur_giveback_atr=float(
                (t["running_mfe"] - cur_pnl) / safe_atr),
            cur_close_price=float(c),
        )
        if snap is not None:
            snap_d = snap.to_dict()
            snap_d["session"] = (
                "RTH" if self._is_rth_minute(int(bar.ts_event))
                else "ETH")
            self._snapshots.append(snap_d)
            self._diag["snapshots_emitted"] += 1
        # Schedule next checkpoint
        t["next_path_cp_ts"] = decision_ts + 30 * 1_000_000_000

    # ---- 1m bar: NT delivers the 1m bar event before the 1s bar
    # that triggers our aggregator's 1m bucket close. We use this
    # only to capture the bar's OHLC for downstream V_A use.
    def _on_1m_bar(self, bar):
        self._diag["1m_bars"] += 1
        self._latest_1m_bar_data = {
            "ts_event": int(bar.ts_event),
            "ts_init": int(bar.ts_init),
            "open": float(bar.open),
            "high": float(bar.high),
            "low": float(bar.low),
            "close": float(bar.close),
        }

    # ---- 1m bucket closed in registry → run V_A logic ----
    # Triggered from _on_1s_bar when the 1s bar that closed the
    # 1m bucket arrives. decision_ts = THAT 1s bar's ts_init.
    def _on_1m_bucket_closed(self, decision_ts: int):
        s_1m = self._registry.get("1m")
        if s_1m is None:
            return
        # The just-closed 1m bar's calendar close = s_1m.close_ts
        # The 1m bar OHLC came in via on_bar(1m). It should match
        # s_1m.close_ts == _latest_1m_bar_data["ts_init"].
        bar_data = self._latest_1m_bar_data
        if (bar_data is None
                or bar_data["ts_init"] != s_1m.close_ts):
            # Misalignment between the 1m bar event and aggregator
            # state. Could happen at warmup. Skip safely.
            return
        bar_ts_event = bar_data["ts_event"]

        # ---- (a) Bar+1 confirmation check ----
        if (self._pending_flip is not None
                and bar_ts_event > self._pending_flip[
                    "flip_ts_event"]):
            self._evaluate_bar1_check(bar_data, decision_ts,
                                          bar_ts_event)
            self._pending_flip = None  # done either way

        # ---- (b) Detect 1m regime flip on this just-closed bar ----
        new_regime = s_1m.regime
        flipped = (new_regime != 0 and self._prev_1m_regime != 0
                     and new_regime != self._prev_1m_regime)

        if flipped:
            in_rth = self._is_rth(bar_ts_event)
            # Exit on opposing flip if we're in a trade
            if self._trade is not None:
                if new_regime != self._trade["direction"]:
                    self._submit_exit()
                    self._diag["regime_exits"] += 1
            # Cancel pending entry if regime flipped against it
            if self._pending_entry is not None:
                if new_regime != self._pending_entry["direction"]:
                    self._pending_cancellations.append({
                        "decision_event_id": self._pending_entry.get("decision_event_id"),
                        "decision_ts": self._pending_entry.get("decision_ts"),
                        "fill_ts_target": self._pending_entry.get("fill_ts_target"),
                        "direction": self._pending_entry.get("direction"),
                        "opposite_flip_ts_event": int(bar_ts_event),
                        "status_chain": "signal confirmed -> entry scheduled -> "
                                        "opposite flip before activation -> "
                                        "pending entry canceled -> no trade",
                    })
                    self._diag["pending_entry_canceled"] += 1
                    self._pending_entry = None
            # If RTH, set pending flip awaiting bar+1 confirmation
            if in_rth:
                self._diag["rth_flips"] += 1
                self._pending_flip = {
                    "flip_ts_event": bar_ts_event,
                    "flip_ts_init": s_1m.close_ts,
                    "flip_h": bar_data["high"],
                    "flip_l": bar_data["low"],
                    "flip_c": bar_data["close"],
                    "direction": int(new_regime),
                }
                snap = self._snapshot_builder.build(
                    decision_ts=decision_ts,
                    bar_ts_event=bar_ts_event,
                    kind="regime_flip",
                    direction=int(new_regime),
                    flip_bar_h=bar_data["high"],
                    flip_bar_l=bar_data["low"],
                    flip_bar_c=bar_data["close"],
                    flip_direction=int(new_regime),
                )
                if snap is not None:
                    snap_d = snap.to_dict()
                    snap_d["session"] = (
                        "RTH" if self._is_rth_minute(bar_ts_event)
                        else "ETH")
                    self._snapshots.append(snap_d)
                    self._diag["snapshots_emitted"] += 1

        if new_regime != 0:
            self._prev_1m_regime = new_regime

    def _evaluate_bar1_check(self, bar_data, decision_ts,
                                 bar_ts_event):
        """V_A bar+1 confirmation check. Emit snapshot regardless;
        if confirmed (and 5m aligned in trading mode), schedule
        entry."""
        self._diag["bar1_checks"] += 1
        d = self._pending_flip["direction"]
        bar_h = float(bar_data["high"]); bar_l = float(bar_data["low"])
        bar_o = float(bar_data["open"]); bar_c = float(bar_data["close"])
        if d == 1:
            hhll_ok = bar_h > self._pending_flip["flip_h"]
            momentum_ok = bar_c > bar_o
        else:
            hhll_ok = bar_l < self._pending_flip["flip_l"]
            momentum_ok = bar_c < bar_o
        confirmed = bool(hhll_ok and momentum_ok)
        if confirmed:
            self._diag["confirmations_passed_hhll_mom"] += 1

        # Emit snapshot for the bar+1 check regardless of outcome
        snap = self._snapshot_builder.build(
            decision_ts=decision_ts,
            bar_ts_event=bar_ts_event,
            kind="bar1_check",
            direction=int(d),
            flip_bar_h=self._pending_flip["flip_h"],
            flip_bar_l=self._pending_flip["flip_l"],
            flip_bar_c=self._pending_flip["flip_c"],
            flip_direction=int(d),
            bar1_h=bar_h, bar1_l=bar_l,
            bar1_o=bar_o, bar1_c=bar_c,
            hhll_ok=hhll_ok, momentum_ok=momentum_ok,
            confirmed=confirmed,
        )
        if snap is None:
            return
        snap_d = snap.to_dict()
        snap_d["session"] = (
            "RTH" if self._is_rth_minute(bar_ts_event)
            else "ETH")
        self._snapshots.append(snap_d)
        self._diag["snapshots_emitted"] += 1

        # Compute pre-entry 1s microstructure features. Causal: all
        # source 1s bars have ts_init <= decision_ts. We use
        # registry's atr_1m as the normalizer (already audited).
        s_1m_state = self._registry.get("1m")
        atr_1m_at_signal = (s_1m_state.atr if s_1m_state
                              else float("nan"))
        flip_init_ts = self._pending_flip["flip_ts_init"]
        micro_row: dict = {
            "decision_event_id": int(snap.event_id),
            "decision_ts": int(decision_ts),
            "bar_ts_event": int(bar_ts_event),
            "direction": int(d),
            "atr_1m_at_signal": float(atr_1m_at_signal)
                if atr_1m_at_signal else float("nan"),
            "session": snap_d["session"],
            "confirmed": bool(confirmed),
        }
        # Three trailing windows
        for w_s in (15, 30, 60):
            feats = self._compute_micro_window(
                d, decision_ts,
                decision_ts - w_s * 1_000_000_000,
                atr_1m_at_signal, prefix=f"w{w_s}s_")
            micro_row.update(feats)
        # Flip → confirmation window (60s)
        feats_f2c = self._compute_micro_window(
            d, decision_ts, flip_init_ts,
            atr_1m_at_signal, prefix="flip2conf_")
        micro_row.update(feats_f2c)
        # Confirmation-bar internal microstructure (the bar+1 itself,
        # which is the 60s ending at decision_ts)
        feats_b1 = self._compute_micro_window(
            d, decision_ts,
            decision_ts - 60 * 1_000_000_000,
            atr_1m_at_signal, prefix="bar1_internal_")
        micro_row.update(feats_b1)
        # Where in bar1 did the HH/LL extreme occur, and giveback
        # from extreme to close
        bar1_bars = [b for b in self._recent_1s_bars
                       if (decision_ts - 60_000_000_000
                           < b["ts_init"] <= decision_ts)]
        if bar1_bars and atr_1m_at_signal and atr_1m_at_signal > 0:
            if d == 1:
                ext_idx = max(range(len(bar1_bars)),
                               key=lambda i: bar1_bars[i]["h"])
                ext_price = bar1_bars[ext_idx]["h"]
            else:
                ext_idx = min(range(len(bar1_bars)),
                               key=lambda i: bar1_bars[i]["l"])
                ext_price = bar1_bars[ext_idx]["l"]
            close_price = bar1_bars[-1]["c"]
            micro_row["bar1_extreme_pos_pct"] = (
                ext_idx / max(1, len(bar1_bars) - 1))
            micro_row["bar1_giveback_from_ext_atr"] = (
                (ext_price - close_price) * d
                / atr_1m_at_signal)
        else:
            micro_row["bar1_extreme_pos_pct"] = float("nan")
            micro_row["bar1_giveback_from_ext_atr"] = float("nan")
        self._micro_pre.append(micro_row)

        # Trading mode: if confirmed (and optionally 5m aligned),
        # schedule entry
        if not confirmed:
            return
        if self._cfg.mode != "trading":
            return
        # Frozen research-derived rank-filter gate (e.g. R2/R4). The
        # score/exemption decision was computed upstream (cached research
        # table) at this same instant (decision_ts = confirmation-bar
        # close) and is not recomputed here -- this is a pass-through skip
        # gate on an already-frozen decision, not a new model or feature.
        if self._is_policy_skip(int(decision_ts)):
            self._policy_skips.append({
                "decision_event_id": int(snap.event_id),
                "decision_ts": int(decision_ts),
                "direction": int(d),
            })
            self._diag["rejected_by_policy_filter"] += 1
            return
        # Live-tradable guardrail: skip new entries past cutoff
        if self._cfg.no_entry_after_min_ct > 0:
            ct = pd.Timestamp(int(decision_ts),
                                  tz="UTC").tz_convert(CT)
            min_ct = ct.hour * 60 + ct.minute
            if min_ct >= self._cfg.no_entry_after_min_ct:
                self._diag[
                    "rejected_after_no_entry_cutoff"] += 1
                return
        # 5m alignment gate (optional)
        if self._cfg.require_5m_aligned:
            s_5m = self._registry.get("5m")
            if s_5m is None or s_5m.regime != d:
                self._diag["rejected_5m_misaligned"] += 1
                # Mark snapshot as not-trade by appending a "rejected"
                # tag. Snapshot is already in list; we don't mutate.
                return
        # Microstructure gate (optional). Reads the same value
        # that was just appended to micro_pre — by construction the
        # offline parquet and the runtime gate use identical inputs.
        f2c_eff = micro_row.get(
            "flip2conf_dir_efficiency", float("nan"))
        if self._cfg.require_flip2conf_efficiency > 0:
            if (f2c_eff is None
                    or (isinstance(f2c_eff, float)
                        and f2c_eff != f2c_eff)   # NaN check
                    or f2c_eff
                        < self._cfg.require_flip2conf_efficiency):
                self._diag[
                    "rejected_low_flip2conf_efficiency"] += 1
                return
        # Schedule entry: fill at OPEN of the 1s bar at/after
        # fill_ts_target. bar+1 ts_init = decision_ts (= bar1_close + 1s).
        # cfg.entry_delay_ns defaults to 0 (immediate next-1s-open fill,
        # the project's current no-delay canonical); set to 30s for the
        # rank_filter_oos_validation study's canonical delayed-activation
        # mechanic. The "submit 1s before target" check in _on_1s_bar
        # handles either case identically.
        s_1m = self._registry.get("1m")
        atr_at_signal = (s_1m.atr if s_1m is not None
                            else float("nan"))
        fill_ts_target = decision_ts + int(self._cfg.entry_delay_ns)
        self._pending_entry = {
            "fill_ts_target": int(fill_ts_target),
            "direction": int(d),
            "decision_event_id": int(snap.event_id),
            "atr_at_signal": float(atr_at_signal),
            "decision_ts": int(decision_ts),
            "flip2conf_dir_efficiency_at_signal": (
                float(f2c_eff)
                if (f2c_eff is not None
                    and not (isinstance(f2c_eff, float)
                                 and f2c_eff != f2c_eff))
                else float("nan")),
        }

    # ---- Aggregator callback (per-bucket close) ----
    def _on_bucket_closed(self, tf, completed):
        # Update engine for this TF; engine writes to registry
        try:
            self._engines[tf].on_bar_closed(completed)
        except Exception as e:
            self._halt(f"engine.on_bar_closed({tf}) raised: {e}")
            raise
        self._diag[f"buckets_closed_{tf}"] += 1

        # HH/LL progression: track completed 30s buckets while a
        # trade is open. Causal — `completed` is the just-closed
        # bucket, all source bars have ts_init <= bucket close.
        if (tf == "30s" and self._cfg.enable_hhll_exit
                and self._trade is not None
                and self._trade.get("entry_ts") is not None
                and not self._trade.get("hhll_armed", False)):
            t = self._trade
            d = int(t["direction"])
            # Only count buckets that close STRICTLY AFTER entry
            if int(completed.close_ts) <= int(t["entry_ts"]):
                return
            bucket_extreme = (float(completed.high) if d == 1
                                 else float(completed.low))
            prior = t.get("hhll_prev_30s_extreme")
            if prior is None:
                # First completed bucket post-entry — initialize
                t["hhll_prev_30s_extreme"] = bucket_extreme
                t["hhll_stall_count_30s"] = 0
                return
            if d == 1:
                new_ext = bucket_extreme > prior
            else:
                new_ext = bucket_extreme < prior
            if new_ext:
                t["hhll_prev_30s_extreme"] = bucket_extreme
                t["hhll_stall_count_30s"] = 0
            else:
                t["hhll_stall_count_30s"] = (
                    t.get("hhll_stall_count_30s", 0) + 1)

    # ---- Microstructure window features over buffered 1s bars ----
    def _compute_micro_window(
        self, direction: int, end_ts: int, start_ts: int,
        atr: float, prefix: str = "",
    ) -> dict:
        """Compute 1s microstructure features over the half-open
        window (start_ts, end_ts] using `_recent_1s_bars`.

        Causality: caller MUST guarantee end_ts <= current
        decision_ts. All buffered bars have ts_init <= the most
        recently appended bar; we only read bars with
        start_ts < ts_init <= end_ts."""
        bars = [b for b in self._recent_1s_bars
                  if start_ts < b["ts_init"] <= end_ts]
        n = len(bars)
        out: dict = {f"{prefix}n_bars": n}
        if n == 0 or not (atr and atr > 0):
            return out

        deltas = [b["c"] - b["o"] for b in bars]
        sgn = [d * direction for d in deltas]   # signed in trade dir
        vols = [b["v"] for b in bars]

        # Net & total move
        net = (bars[-1]["c"] - bars[0]["o"]) * direction
        total_abs = sum(abs(d) for d in deltas)
        out[f"{prefix}net_move_atr"] = net / atr
        out[f"{prefix}total_abs_move_atr"] = total_abs / atr
        out[f"{prefix}efficiency"] = (
            abs(net) / total_abs if total_abs > 0 else 0.0)
        out[f"{prefix}dir_efficiency"] = (
            net / total_abs if total_abs > 0 else 0.0)

        # Direction counts
        n_fav = sum(1 for s in sgn if s > 0)
        n_adv = sum(1 for s in sgn if s < 0)
        out[f"{prefix}pct_favorable"] = n_fav / n
        out[f"{prefix}pct_adverse"] = n_adv / n
        out[f"{prefix}fav_seconds"] = n_fav
        out[f"{prefix}adv_seconds"] = n_adv

        # Max consecutive runs
        max_fav = max_adv = cf = ca = 0
        for s in sgn:
            if s > 0:
                cf += 1; ca = 0
            elif s < 0:
                ca += 1; cf = 0
            else:
                cf = ca = 0
            if cf > max_fav: max_fav = cf
            if ca > max_adv: max_adv = ca
        out[f"{prefix}max_consec_fav_s"] = max_fav
        out[f"{prefix}max_consec_adv_s"] = max_adv

        # Sign flips
        flips = 0; prev = 0
        for s in sgn:
            if s == 0: continue
            cur = 1 if s > 0 else -1
            if prev != 0 and cur != prev:
                flips += 1
            prev = cur
        out[f"{prefix}sign_flip_count"] = flips
        out[f"{prefix}sign_flip_rate"] = flips / max(1, n - 1)

        # Range / chop
        hi = max(b["h"] for b in bars)
        lo = min(b["l"] for b in bars)
        rng = hi - lo
        out[f"{prefix}range_atr"] = rng / atr
        out[f"{prefix}range_over_net_abs"] = (
            rng / max(abs(net), 1e-9))

        # Counter-moves (adverse 1s deltas)
        adv_vals = [-s for s in sgn if s < 0]   # positive magnitudes
        if adv_vals:
            out[f"{prefix}largest_counter_move_atr"] = (
                max(adv_vals) / atr)
            out[f"{prefix}avg_counter_move_atr"] = (
                sum(adv_vals) / len(adv_vals) / atr)
        else:
            out[f"{prefix}largest_counter_move_atr"] = 0.0
            out[f"{prefix}avg_counter_move_atr"] = 0.0

        # Velocity / returns per second
        out[f"{prefix}avg_1s_return_atr"] = (
            sum(sgn) / n / atr)
        sgn_sorted = sorted(sgn)
        out[f"{prefix}median_1s_return_atr"] = (
            sgn_sorted[n // 2] / atr)
        out[f"{prefix}max_fav_1s_return_atr"] = max(sgn) / atr
        out[f"{prefix}max_adv_1s_return_atr"] = min(sgn) / atr

        # First-half vs second-half acceleration
        if n >= 4:
            half = n // 2
            fh = sum(sgn[:half]) / half
            sh = sum(sgn[half:]) / (n - half)
            out[f"{prefix}accel_first_to_second"] = (sh - fh) / atr
        else:
            out[f"{prefix}accel_first_to_second"] = float("nan")

        # Final 5s / final 10s momentum (subset of bars)
        for tail in (5, 10):
            if n >= tail:
                tail_sum = sum(sgn[-tail:])
                out[f"{prefix}final_{tail}s_momentum_atr"] = (
                    tail_sum / atr)
            else:
                out[f"{prefix}final_{tail}s_momentum_atr"] = (
                    float("nan"))

        # Volume features
        total_vol = sum(vols)
        fav_vol = sum(b["v"] for b, s in zip(bars, sgn) if s > 0)
        adv_vol = sum(b["v"] for b, s in zip(bars, sgn) if s < 0)
        out[f"{prefix}total_volume"] = total_vol
        out[f"{prefix}volume_per_s"] = total_vol / n
        out[f"{prefix}fav_volume"] = fav_vol
        out[f"{prefix}adv_volume"] = adv_vol
        out[f"{prefix}dir_vol_imbalance"] = (
            (fav_vol - adv_vol) / total_vol
            if total_vol > 0 else 0.0)
        out[f"{prefix}price_per_unit_vol"] = (
            abs(net) / total_vol if total_vol > 0 else 0.0)

        # Volume z-score: window per-second vol vs prior 20m baseline
        prior_start = end_ts - 20 * 60 * 1_000_000_000
        prior_bars = [b for b in self._recent_1s_bars
                       if (prior_start < b["ts_init"]
                           <= start_ts)]
        if len(prior_bars) >= 60:
            prior_vols = [b["v"] for b in prior_bars]
            mu = sum(prior_vols) / len(prior_vols)
            var = (sum((v - mu) ** 2 for v in prior_vols)
                   / len(prior_vols))
            sd = var ** 0.5
            window_per_s = total_vol / n
            out[f"{prefix}vol_z_vs_prior_20m"] = (
                (window_per_s - mu) / sd if sd > 0
                else 0.0)
        else:
            out[f"{prefix}vol_z_vs_prior_20m"] = float("nan")

        # Volume spike count: 1s bars with v > mu + 2*sd vs prior 20m
        if len(prior_bars) >= 60:
            spike_thr = mu + 2.0 * sd
            out[f"{prefix}volume_spike_count"] = sum(
                1 for v in vols if v > spike_thr)
        else:
            out[f"{prefix}volume_spike_count"] = float("nan")

        return out

    # ---- Order management ----
    def _submit_entry(self):
        d = self._pending_entry["direction"]
        side = OrderSide.BUY if d == 1 else OrderSide.SELL
        qty = Quantity.from_int(self._cfg.position_size)
        order = self.order_factory.market(
            instrument_id=InstrumentId.from_str(
                self._cfg.instrument_id),
            order_side=side, quantity=qty,
            time_in_force=TimeInForce.FOK)
        self._trade = {
            "direction": int(d),
            "decision_event_id": int(
                self._pending_entry["decision_event_id"]),
            "decision_ts": int(
                self._pending_entry.get("decision_ts", 0)),
            "entry_order_id": order.client_order_id.value,
            "fill_price": None,
            "entry_ts": None,
            "exit_order_id": None,
            "exit_price": None,
            "exit_ts": None,
            "atr_at_signal": float(
                self._pending_entry.get("atr_at_signal",
                                            float("nan"))),
            "flip2conf_dir_efficiency_at_signal": float(
                self._pending_entry.get(
                    "flip2conf_dir_efficiency_at_signal",
                    float("nan"))),
            "running_mfe": -1e9,
            "running_mae": -1e9,
            "t_running_mfe_ts": 0,
            "t_running_mae_ts": 0,
            "last_close_price": float("nan"),
            "last_close_ts": 0,
            "next_path_cp_ts": 0,  # set after entry fill
            # HH/LL exit overlay state (only used when enabled)
            "hhll_armed": False,
            "hhll_prev_30s_extreme": None,
            "hhll_stall_count_30s": 0,
            "hhll_protect_px": None,
            "hhll_protect_order_id": None,
            "hhll_mfe_at_arm": None,
            "exit_reason": None,
        }
        self._pending_entry = None
        self.submit_order(order)

    def _submit_exit(self):
        if self._trade is None:
            return
        if self._trade.get("exit_order_id") is not None:
            return
        # HH/LL protection is monitored internally — no external
        # stop order to cancel. The internal armed state is reset
        # automatically when the trade finalizes.
        d = self._trade["direction"]
        side = OrderSide.SELL if d == 1 else OrderSide.BUY
        qty = Quantity.from_int(self._cfg.position_size)
        order = self.order_factory.market(
            instrument_id=InstrumentId.from_str(
                self._cfg.instrument_id),
            order_side=side, quantity=qty,
            time_in_force=TimeInForce.FOK,
            reduce_only=True)
        self._trade["exit_order_id"] = order.client_order_id.value
        self._trade["exit_reason"] = "regime"
        self.submit_order(order)

    def _arm_hhll_protection(self, decision_ts: int = 0):
        """Record protect_px; do NOT submit a STOP order. The level
        is monitored internally per 1s bar in
        `_check_hhll_protect_trigger`, which fires a MARKET exit on
        crossing. This avoids NT's "trigger in the market" stop
        rejections in fast-moving regimes and matches the tape-
        replay semantics exactly."""
        t = self._trade
        if t is None: return
        if t.get("hhll_armed", False): return
        d = int(t["direction"])
        ep = float(t["fill_price"])
        mfe_pts = float(t["running_mfe"])
        protect_offset = self._cfg.hhll_lock_pct * mfe_pts
        tick = 0.25
        raw_protect = ep + protect_offset * d
        # Round to nearest tick (snap conservatively closer to entry)
        if d == 1:
            protect_px = (int(raw_protect / tick)) * tick
        else:
            protect_px = (-(int(-raw_protect / tick))) * tick
        t["hhll_armed"] = True
        t["hhll_arm_ts"] = int(decision_ts)
        t["hhll_mfe_at_arm"] = mfe_pts
        t["hhll_protect_px"] = float(protect_px)
        # No order submitted — internal monitor only
        self._diag["hhll_armed"] += 1

    def _check_hhll_protect_trigger(self, bar, decision_ts: int):
        """Per-1s-bar check: if armed AND this bar's high/low
        crossed the protect_px in the unfavorable direction,
        submit a MARKET exit. NT fills at the next tick."""
        t = self._trade
        if t is None or not t.get("hhll_armed", False):
            return
        if t.get("exit_order_id") is not None:
            return  # already exiting
        protect_px = t.get("hhll_protect_px")
        if protect_px is None: return
        d = int(t["direction"])
        # For long: trigger when low <= protect_px
        # For short: trigger when high >= protect_px
        triggered = ((d == 1 and float(bar.low) <= protect_px)
                      or (d == -1
                          and float(bar.high) >= protect_px))
        if not triggered:
            return
        # Submit market exit, mark as hhll exit reason
        side = OrderSide.SELL if d == 1 else OrderSide.BUY
        qty = Quantity.from_int(self._cfg.position_size)
        order = self.order_factory.market(
            instrument_id=InstrumentId.from_str(
                self._cfg.instrument_id),
            order_side=side, quantity=qty,
            time_in_force=TimeInForce.FOK,
            reduce_only=True)
        t["exit_order_id"] = order.client_order_id.value
        t["exit_reason"] = "hhll_protect"
        self._diag["hhll_exits"] += 1
        self.submit_order(order)

    def on_order_filled(self, event):
        cid = event.client_order_id.value
        if self._trade is None:
            return
        if cid == self._trade.get("entry_order_id"):
            self._trade["fill_price"] = float(event.last_px)
            self._trade["entry_ts"] = int(event.ts_event)
            # First path checkpoint at entry + 30s
            self._trade["next_path_cp_ts"] = (
                int(event.ts_event) + 30 * 1_000_000_000)
            # Seed running extremes at the fill price
            self._trade["running_mfe"] = 0.0
            self._trade["running_mae"] = 0.0
            self._diag["entries_filled"] += 1
            # Mark the source snapshot as "became_trade=True"
            ev_id = self._trade["decision_event_id"]
            for s in reversed(self._snapshots):
                if s.get("event_id") == ev_id:
                    s["became_trade"] = True
                    break
            # Conf-to-fill microstructure: 1s bars in
            # (decision_ts, entry_ts]. ~30s window in V_A baseline.
            d = self._trade["direction"]
            atr = self._trade["atr_at_signal"]
            decision_ts_t = self._trade["decision_ts"]
            entry_ts_t = self._trade["entry_ts"]
            feats_c2f = self._compute_micro_window(
                d, entry_ts_t, decision_ts_t, atr,
                prefix="conf2fill_")
            mp = {
                "decision_event_id": int(ev_id),
                "fill_ts": int(entry_ts_t),
                "fill_price": float(event.last_px),
                "direction": int(d),
                "atr_at_signal": float(atr) if atr else float("nan"),
            }
            mp.update(feats_c2f)
            self._micro_post.append(mp)
        elif cid == self._trade.get("exit_order_id"):
            self._trade["exit_price"] = float(event.last_px)
            self._trade["exit_ts"] = int(event.ts_event)
            if self._trade.get("exit_reason") is None:
                self._trade["exit_reason"] = "regime"
            self._finalize_trade()
        elif cid == self._trade.get("hhll_protect_order_id"):
            # HH/LL stop filled — treat as exit
            self._trade["exit_price"] = float(event.last_px)
            self._trade["exit_ts"] = int(event.ts_event)
            self._trade["exit_reason"] = "hhll_protect"
            self._diag["hhll_exits"] += 1
            self._finalize_trade()

    def on_order_rejected(self, event):
        """If an entry order is rejected (no market, etc), discard
        the in-flight trade so subsequent regime flips don't try to
        close a phantom position. Increments rejection diag counter."""
        if self._trade is None:
            return
        cid = event.client_order_id.value
        if cid == self._trade.get("entry_order_id"):
            try: self.log.warning(
                f"entry rejected — discarding trade state: "
                f"{getattr(event, 'reason', '')}")
            except Exception: pass
            self._diag.setdefault("entries_rejected", 0)
            self._diag["entries_rejected"] += 1
            self._trade = None
        elif cid == self._trade.get("exit_order_id"):
            try: self.log.warning(
                f"exit rejected — clearing exit_order_id to retry: "
                f"{getattr(event, 'reason', '')}")
            except Exception: pass
            self._diag.setdefault("exits_rejected", 0)
            self._diag["exits_rejected"] += 1
            self._trade["exit_order_id"] = None
        elif cid == self._trade.get("hhll_protect_order_id"):
            try: self.log.warning(
                f"hhll stop rejected: "
                f"{getattr(event, 'reason', '')}")
            except Exception: pass
            self._diag.setdefault("hhll_rejected", 0)
            self._diag["hhll_rejected"] += 1
            # Clear so we don't try to cancel a non-existent order
            self._trade["hhll_protect_order_id"] = None
            self._trade["hhll_armed"] = False

    def _finalize_trade(self):
        t = self._trade
        d = t["direction"]
        ep = t["fill_price"]; ex = t["exit_price"]
        gross = (ex - ep) * d * self._cfg.multiplier
        cost = self._cfg.commission_per_rt + self._cfg.tick_dollar
        net = gross - cost
        t["gross_pnl"] = gross
        t["net_pnl"] = net
        t["hold_s"] = (t["exit_ts"] - t["entry_ts"]) / 1e9
        # Tag entry session for downstream split (RTH/ETH)
        t["session"] = (
            "RTH" if self._is_rth_minute(t["entry_ts"])
            else "ETH")
        self._trades.append(dict(t))
        self._trade = None

    def _is_rth_minute(self, ts_ns: int) -> bool:
        """Helper: RTH classification regardless of cfg.rth_only."""
        ct = pd.Timestamp(ts_ns, tz="UTC").tz_convert(CT)
        m = ct.hour * 60 + ct.minute
        return self._cfg.rth_start_min <= m < self._cfg.rth_end_min

    # ---- Halt / failure handling ----
    def _halt(self, reason: str):
        msg = f"COLLECTOR V2 HALT: {reason}"
        try:
            self.log.error(msg)
        except Exception:
            print(msg)
        # Write a failure report immediately
        if self._cfg.output_dir:
            try:
                Path(self._cfg.output_dir).mkdir(parents=True,
                                                    exist_ok=True)
                with open(Path(self._cfg.output_dir)
                              / "FAILURE.txt", "w") as f:
                    f.write(msg + "\n")
                    f.write(f"snapshots_so_far: "
                              f"{len(self._snapshots)}\n")
                    f.write(f"trades_so_far: {len(self._trades)}\n")
            except Exception:
                pass

    # ---- Lifecycle ----
    def on_stop(self):
        super().on_stop()
        try:
            self.log.info(f"Diag: {self._diag}")
        except Exception:
            pass
        if self._cfg.output_dir:
            outp = Path(self._cfg.output_dir)
            outp.mkdir(parents=True, exist_ok=True)
            if self._snapshots:
                pd.DataFrame(self._snapshots).to_parquet(
                    outp / "snapshots.parquet", index=False)
            if self._trades:
                pd.DataFrame(self._trades).to_parquet(
                    outp / "trades.parquet", index=False)
            if self._micro_pre:
                pd.DataFrame(self._micro_pre).to_parquet(
                    outp / "micro_pre.parquet", index=False)
            if self._micro_post:
                pd.DataFrame(self._micro_post).to_parquet(
                    outp / "micro_post.parquet", index=False)
            if self._trade_tape:
                pd.DataFrame(self._trade_tape).to_parquet(
                    outp / "trade_tape.parquet", index=False)
            if self._policy_skips:
                pd.DataFrame(self._policy_skips).to_parquet(
                    outp / "policy_skips.parquet", index=False)
            if self._pending_cancellations:
                pd.DataFrame(self._pending_cancellations).to_parquet(
                    outp / "pending_cancellations.parquet", index=False)
            # Also write diag for parity tooling
            import json
            self._diag["micro_pre_rows"] = len(self._micro_pre)
            self._diag["micro_post_rows"] = len(self._micro_post)
            self._diag["trade_tape_rows"] = len(self._trade_tape)
            with open(outp / "diag.json", "w") as f:
                json.dump(self._diag, f, indent=2)

    # ---- Helpers ----
    def _is_rth(self, ts_ns: int) -> bool:
        if not self._cfg.rth_only:
            return True
        ct = pd.Timestamp(ts_ns, tz="UTC").tz_convert(CT)
        m = ct.hour * 60 + ct.minute
        return self._cfg.rth_start_min <= m < self._cfg.rth_end_min

    def _is_policy_skip(self, decision_ts: int) -> bool:
        """BACKWARD-ONLY nearest-timestamp match (see __init__ note) against
        the frozen research-derived skip set -- never matches a skip-list
        entry that is later than decision_ts (would be a look-ahead
        violation; fixed after lookahead-auditor review 2026-07-07).
        Empty set (R0) always returns False."""
        if len(self._skip_arr) == 0:
            return False
        # side="right" - 1 gives the largest index i such that
        # skip_arr[i] <= decision_ts (i.e. the nearest entry AT OR BEFORE
        # decision_ts). Never consider the forward neighbor.
        i = int(np.searchsorted(self._skip_arr, decision_ts, side="right")) - 1
        if i < 0:
            return False
        gap = decision_ts - int(self._skip_arr[i])
        return 0 <= gap <= self._skip_match_tolerance_ns
