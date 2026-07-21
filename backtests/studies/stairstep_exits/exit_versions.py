"""Stair-step exit versions — per-(trade, version) state machines.

Each VersionTrade replays ONE exit-management version on one entry, fed 1s bars
(execution) and decision-clock bar closes (stop migration). It records IDEAL
fills (pre-slippage) + an exit_reason; the cost model (gross / primary / stress)
is applied later in analyze.py, so one replay yields all cost scenarios.

Fill rules (non-negotiable, built on utils/safe_replay):
  - Stop fills: replay_stop_on_bar_ohlc, at_or_worse_close (never a price that
    didn't trade). PT: resting LIMIT, fills exact when the 1s bar crosses it.
  - Stop migrations are RATCHET-ONLY (never loosen) and become active on the
    NEXT 1s bar (staged in _pending).
  - If a proposed stop is already crossed by the current 1s close → CLAMP to
    market-side (close ∓ 1 tick) or SKIP the update (per version). No phantom.
  - Within one 1s bar, if both the stop and PT are touchable, the STOP fills
    first (conservative).
  - Market exits (prove-it cut, regime flip) fill at the current 1s close
    (ideal); slippage added in analyze.
"""
from __future__ import annotations
from pathlib import Path
import sys

_repo_root = Path(__file__).parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from utils.safe_replay import (  # noqa: E402
    replay_stop_on_bar_ohlc, validate_stop_at_arm, round_protect_to_tick,
    OHLCConvention,
)

NS_PER_S = 1_000_000_000
LADDER_RUNGS = ((0.5, -0.25), (1.0, 0.0), (1.5, 0.5), (2.0, 1.0))  # mfe_atr -> stop_atr

# ---- version registry (spec dicts) ----
# kind flags: init_stop_atr, pt_atr, gate, ladder, trail, ma_invalid, clock, cat_stop
EXIT_VERSIONS = {
    "V0_regime":   dict(init_stop_atr=None, pt_atr=None, gate=False, ladder=False,
                        trail=None, clock=None, cat_stop=True),
    "BR10":        dict(init_stop_atr=-1.0, pt_atr=2.0, gate=False, ladder=False,
                        trail=None, clock=None, cat_stop=False),
    "BR15":        dict(init_stop_atr=-1.5, pt_atr=2.0, gate=False, ladder=False,
                        trail=None, clock=None, cat_stop=False),
    "V1_ladder":   dict(init_stop_atr=-0.75, pt_atr=None, gate=False, ladder=True,
                        trail=None, clock=None, cat_stop=False),
    "V2_gate_ladder": dict(init_stop_atr=-0.75, pt_atr=None, gate=True, ladder=True,
                           trail=None, clock=None, cat_stop=False),
    "V3_struct_1m": dict(init_stop_atr=-0.75, pt_atr=None, gate=True, ladder=False,
                         trail="structure", clock="1m", cat_stop=False),
    "V3_struct_5s": dict(init_stop_atr=-0.75, pt_atr=None, gate=True, ladder=False,
                         trail="structure", clock="5s", cat_stop=False),
    "V4D1_ma_1m":  dict(init_stop_atr=-0.75, pt_atr=None, gate=False, ladder=False,
                        trail="ma_stall", ma_invalid="clamp", clock="1m", cat_stop=False),
    "V4D1_ma_5s":  dict(init_stop_atr=-0.75, pt_atr=None, gate=False, ladder=False,
                        trail="ma_stall", ma_invalid="clamp", clock="5s", cat_stop=False),
    "V4D2_ma_1m":  dict(init_stop_atr=-0.75, pt_atr=None, gate=False, ladder=False,
                        trail="ma_stall", ma_invalid="skip", clock="1m", cat_stop=False),
    "V4D2_ma_5s":  dict(init_stop_atr=-0.75, pt_atr=None, gate=False, ladder=False,
                        trail="ma_stall", ma_invalid="skip", clock="5s", cat_stop=False),
    "V5_hybrid_1m": dict(init_stop_atr=-0.75, pt_atr=None, gate=True, ladder=False,
                         trail="hybrid", ma_invalid="clamp", clock="1m", cat_stop=False),
    "V5_hybrid_5s": dict(init_stop_atr=-0.75, pt_atr=None, gate=True, ladder=False,
                         trail="hybrid", ma_invalid="clamp", clock="5s", cat_stop=False),
}


def _round_to_tick(px, tick):
    return round(px / tick) * tick


class VersionTrade:
    """One exit version replayed on one entry."""

    def __init__(self, vid, spec, direction, entry_px, atr, entry_ts, tick,
                 cat_px=None):
        self.vid = vid
        self.spec = spec
        self.d = int(direction)
        self.ep = float(entry_px)
        self.atr = float(atr)
        self.entry_ts = int(entry_ts)
        self.tick = float(tick)

        self.stop = None
        self._pending = None        # (px, ts) staged stop -> active next 1s bar
        self.pt = None
        if spec.get("pt_atr") is not None:
            self.pt = _round_to_tick(self.ep + self.d * spec["pt_atr"] * self.atr,
                                     self.tick)

        self.passed_gate = not spec.get("gate", False)
        self._gate30 = False
        self._gate60 = False

        self.stall = 0
        self._best_fav = None       # best favorable clock-bar extreme (stall)

        self.running_mfe = -1e18
        self.running_mae = -1e18

        self.exited = False
        self.exit_ts = None
        self.exit_px = None         # IDEAL fill (pre-slippage)
        self.exit_reason = None
        self.cat_invalid_at_entry = False
        self.n_stop_migrations = 0

        # --- initial / catastrophic stop ---
        if spec.get("cat_stop") and cat_px is not None:
            self._set_initial_stop(float(cat_px))
        elif spec.get("init_stop_atr") is not None:
            self._set_initial_stop(self.ep + self.d * spec["init_stop_atr"] * self.atr)

    # ------------------------------------------------------------------
    def _set_initial_stop(self, raw_px):
        cand = round_protect_to_tick(raw_px, self.d, self.tick)
        valid, _ = validate_stop_at_arm(self.d, self.ep, cand)
        if valid:
            self.stop = cand
        else:
            # invalid at entry (already crossed) — skip the stop, hold to
            # regime, and flag it (e.g. cat-stop at flip-bar open already breached)
            self.cat_invalid_at_entry = True
            self.stop = None

    def _propose_stop(self, raw_px, cur_close, ts, mode="clamp"):
        """Ratchet-only stop migration with clamp/skip on invalid. Staged to
        activate on the NEXT 1s bar."""
        cand = round_protect_to_tick(raw_px, self.d, self.tick)
        if not self._is_tighter(cand):
            return
        valid, _ = validate_stop_at_arm(self.d, cur_close, cand)
        if not valid:
            if mode == "skip":
                return
            cand = round_protect_to_tick(cur_close - self.d * self.tick,
                                         self.d, self.tick)
            if not self._is_tighter(cand):
                return
            valid2, _ = validate_stop_at_arm(self.d, cur_close, cand)
            if not valid2:
                return
        # stage (active next bar); if multiple proposals in one bar keep tightest
        if self._pending is not None:
            prev = self._pending[0]
            if (self.d == 1 and cand <= prev) or (self.d == -1 and cand >= prev):
                return
        self._pending = (cand, ts)

    def _is_tighter(self, cand):
        if self.stop is None:
            return True
        if self.d == 1:
            return cand > self.stop
        return cand < self.stop

    def _exit(self, ts, px, reason):
        self.exited = True
        self.exit_ts = int(ts)
        self.exit_px = float(px)
        self.exit_reason = reason

    # ------------------------------------------------------------------
    def on_1s(self, ts, o, h, l, c, regime_1m, align5s):
        """Process one 1s bar (execution + time-based logic)."""
        if self.exited:
            return
        ts = int(ts)
        # promote staged stop (activates this bar = the bar AFTER it was set)
        if self._pending is not None:
            new_stop, _ = self._pending
            self._pending = None
            if self._is_tighter(new_stop):
                self.stop = new_stop
                self.n_stop_migrations += 1

        # update running MFE/MAE (points)
        if self.d == 1:
            mfe = h - self.ep; mae = self.ep - l
        else:
            mfe = self.ep - l; mae = h - self.ep
        if mfe > self.running_mfe:
            self.running_mfe = mfe
        if mae > self.running_mae:
            self.running_mae = mae

        # FILL CHECKS — stop first (conservative), then PT limit.
        # Hot-path stop trigger is inlined; the fill price is bit-identical to
        # safe_replay.replay_stop_on_bar_ohlc(at_or_worse_close) — verified in
        # test_stop_fill_parity(). The full safe_replay path + audit_replay_fills
        # gate validate every recorded fill is in-bar after the run.
        if self.stop is not None:
            if self.d == 1:
                if l <= self.stop:
                    self._exit(ts, min(self.stop, c), "stop"); return
            else:
                if h >= self.stop:
                    self._exit(ts, max(self.stop, c), "stop"); return
        if self.pt is not None:
            if (self.d == 1 and h >= self.pt) or (self.d == -1 and l <= self.pt):
                self._exit(ts, self.pt, "pt")
                return

        # prove-it gate (market exits)
        if not self.passed_gate:
            dt = (ts - self.entry_ts) / NS_PER_S
            net = self.d * (c - self.ep)
            if (not self._gate30) and dt >= 30:
                self._gate30 = True
                if net < 0 and align5s == -1:
                    self._exit(ts, c, "gate30")
                    return
            if (not self._gate60) and dt >= 60:
                self._gate60 = True
                if net < 0:
                    self._exit(ts, c, "gate60")
                    return
                self.passed_gate = True

        # MFE-based migrations (ladder / hybrid phase) — staged for next bar
        if self.spec.get("ladder"):
            self._ladder(ts, c)
        elif self.spec.get("trail") == "hybrid":
            self._hybrid_mfe(ts, c)

    def _ladder(self, ts, c):
        if not self.passed_gate:
            return
        mfe_atr = self.running_mfe / self.atr if self.atr > 0 else 0.0
        best = None
        for thr, lvl in LADDER_RUNGS:
            if mfe_atr >= thr:
                best = lvl
        if best is not None:
            self._propose_stop(self.ep + self.d * best * self.atr, c, ts, "clamp")

    def _hybrid_mfe(self, ts, c):
        # On gate pass, lift stop to at least -0.25 ATR.
        if self.passed_gate:
            self._propose_stop(self.ep + self.d * (-0.25) * self.atr, c, ts, "clamp")

    # ------------------------------------------------------------------
    def on_clock(self, ts, low3, high3, sma13, cur_close):
        """Process a decision-clock bar close (1m or 5s). low3/high3 = last-3
        completed clock-bar lows/highs (lists). Stop migrations staged."""
        if self.exited:
            return
        trail = self.spec.get("trail")
        if trail is None:
            return
        ts = int(ts)

        # stall = consecutive clock bars without a new favorable extreme
        cur_fav = high3[-1] if self.d == 1 else low3[-1]
        if self._best_fav is None or \
           (self.d == 1 and cur_fav > self._best_fav) or \
           (self.d == -1 and cur_fav < self._best_fav):
            self._best_fav = cur_fav
            self.stall = 0
        else:
            self.stall += 1

        mfe_atr = self.running_mfe / self.atr if self.atr > 0 else 0.0

        if trail == "structure":
            if self.passed_gate:
                ref = min(low3) if self.d == 1 else max(high3)
                self._propose_stop(ref - self.d * self.tick, cur_close, ts, "clamp")
        elif trail == "ma_stall":
            if self.stall >= 3 and sma13 is not None:
                self._propose_stop(sma13, cur_close, ts, self.spec["ma_invalid"])
        elif trail == "hybrid":
            if not self.passed_gate:
                return
            # MFE>=1.0 -> SMA13 protection (corrected clamp)
            if mfe_atr >= 1.0 and sma13 is not None:
                self._propose_stop(sma13, cur_close, ts, self.spec["ma_invalid"])
            # MFE>=2.0 -> also consider structure (last-3 low/high); ratchet keeps tighter
            if mfe_atr >= 2.0:
                ref = min(low3) if self.d == 1 else max(high3)
                self._propose_stop(ref - self.d * self.tick, cur_close, ts, "clamp")

    # ------------------------------------------------------------------
    def regime_exit(self, ts, px):
        """Opposite 1m regime flip -> market exit at the flip bar close."""
        if not self.exited:
            self._exit(ts, px, "regime")

    def force_exit(self, ts, px):
        if not self.exited:
            self._exit(ts, px, "end_of_data")

    def record(self):
        """Final per-trade outcome (ideal, pre-slippage)."""
        mfe = max(self.running_mfe, 0.0) if self.running_mfe > -1e16 else 0.0
        mae = max(self.running_mae, 0.0) if self.running_mae > -1e16 else 0.0
        return {
            "version": self.vid,
            "direction": self.d,
            "entry_ts": self.entry_ts,
            "entry_px": self.ep,
            "atr_at_entry": self.atr,
            "exit_ts": self.exit_ts,
            "exit_px_ideal": self.exit_px,
            "exit_reason": self.exit_reason,
            "max_mfe_pts": mfe,
            "max_mae_pts": mae,
            "hold_s": ((self.exit_ts - self.entry_ts) / NS_PER_S
                       if self.exit_ts is not None else None),
            "n_stop_migrations": self.n_stop_migrations,
            "cat_invalid_at_entry": self.cat_invalid_at_entry,
        }
