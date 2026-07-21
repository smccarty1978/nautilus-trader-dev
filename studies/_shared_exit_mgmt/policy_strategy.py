"""Phase 6 NT wiring for the Phase 5 stop-policy grid.

`StopPolicyMixin` overrides `_maybe_stop_policy_exit` (a no-op stub in
ExitManagementBaseStrategy, audited as a forward-looking item in the
2026-07-11 pre-execution audit -- this IS that "when populated, needs
its own causal pass" moment).

CAUSALITY:
  - The model, decile edges, and conditional recovery-MAE table are
    ALL frozen artifacts (Phase 3/4, train+validation only). Nothing
    here retrains or refits anything.
  - The W0 features scored here are read from the SAME dict
    `_update_open_trade` already populates every 1s bar (bit-identical
    to the offline Phase 3/4 pipeline) -- no separate recomputation
    that could silently diverge from the trained model's training
    distribution.
  - persistence_bucket/score_path are recomputed live, causally, using
    only this trade's own PAST checkpoints (a small rolling history
    kept on the trade dict) -- mirrors
    studies/_shared_exit_mgmt/stop_state_features.py's offline logic
    exactly, so live and offline state-feature definitions match.
  - The internal stop level is monitored per-1s-bar (never a resting
    broker order) and fires a MARKET exit on cross, exactly matching
    the existing, already-reasoned HH/LL protection pattern in
    collectors/collector_v2/strategy.py (avoids NT "trigger in the
    market" stop rejections).
"""
from __future__ import annotations
from collections import deque

from studies._shared_exit_mgmt.w0_features import W0_FEATURES
from studies._shared_exit_mgmt.stop_policy import (
    StopPolicyEngine, StopPolicyConfig, STATE_NONE, STATE_ARMED,
    STATE_TIGHTENED, STATE_TERMINAL, next_policy_state, decile_for_state,
)
from studies._shared_exit_mgmt.stop_state_features import (
    WEAK_DECILE_THRESHOLD, SCORE_PATH_LOOKBACK_S, SCORE_PATH_EPS,
    _persistence_bucket,
)

TICK = 0.25


class StopPolicyMixin:
    """Mix in BEFORE a population strategy class, e.g.:
        class AllFlipsPolicyStrategy(StopPolicyMixin, AllFlipsStrategy): ...
    Requires the concrete strategy's config to carry `policy_engine`
    and `policy_cfg` attributes (set by the caller after construction,
    since they are not simple StrategyConfig-serializable objects)."""

    def _init_policy_state(self, t: dict):
        t["policy_state"] = STATE_NONE
        t["policy_stop_price"] = None
        t["policy_weak_entry_ts"] = None
        t["policy_prob_history"] = deque(maxlen=64)  # (ts, prob)
        t["policy_direct_exit_done"] = False

    def _submit_entry(self):
        super()._submit_entry()
        if self._trade is not None:
            self._init_policy_state(self._trade)

    def _finalize_trade(self):
        # policy_prob_history is a `deque` -- internal bookkeeping only,
        # never meant to be a trades.parquet column. Base class's
        # _finalize_trade does `self._trades.append(dict(t))`, which
        # would otherwise carry the deque through to a pyarrow write
        # and fail (deques aren't Arrow-serializable). Strip
        # non-serializable/internal-only policy_* scratch state here;
        # the scalar policy_* fields (state, stop_price, etc.) are
        # fine and are kept as useful diagnostic columns.
        if self._trade is not None:
            self._trade.pop("policy_prob_history", None)
        super()._finalize_trade()

    def _maybe_stop_policy_exit(self, bar, decision_ts):
        engine: StopPolicyEngine | None = getattr(self, "policy_engine", None)
        cfg: StopPolicyConfig | None = getattr(self, "policy_cfg", None)
        if engine is None or cfg is None:
            return  # E0 -- baseline, no stop policy
        t = self._trade
        if "policy_state" not in t:
            self._init_policy_state(t)
        # Guard on exit_reason (not just exit_order_id): a rejected
        # exit clears exit_order_id back to None but leaves exit_reason
        # set, and the base class's own retry path re-submits with
        # THAT original reason on the very next 1s bar. If this method
        # checked exit_order_id alone, it could call _submit_exit with
        # a different reason first (this method runs before the retry
        # check in _on_1s_bar) and silently relabel the trade's true
        # exit cause (flagged as a forward-looking risk in the
        # 2026-07-11 pre-execution audit; fixed here before first use).
        if t.get("exit_order_id") is not None or t.get("exit_reason") is not None:
            return  # already exiting (filled, in-flight, or pending retry)

        # ---- Score using the SAME causal fields _update_open_trade
        # just computed (bit-identical to the offline training pipeline).
        d = t["direction"]
        ep = t["fill_price"]
        atr = t.get("atr_at_signal", float("nan"))
        safe_atr = atr if atr and atr == atr and atr > 0 else 1.0
        c = float(bar.close)
        cur_pnl = (c - ep) * d / safe_atr
        mfe_atr = t["running_mfe"] / safe_atr
        mae_atr = t["running_mae"] / safe_atr
        giveback_atr = mfe_atr - cur_pnl
        age_s = (decision_ts - t["entry_ts"]) / 1e9
        feature_row = {
            "current_pnl_atr_from_entry": cur_pnl,
            "mfe_atr_from_entry": mfe_atr,
            "mae_atr_from_entry": mae_atr,
            "giveback_atr_from_entry": giveback_atr,
            "distance_from_mfe_atr": giveback_atr,
            "age_seconds": age_s,
        }
        prob = engine.score(feature_row)
        decile = engine.decile_of(prob)

        # ---- Persistence bucket (live, causal -- mirrors
        # stop_state_features.py's offline definition exactly)
        is_weak = decile >= WEAK_DECILE_THRESHOLD
        if is_weak:
            if t["policy_weak_entry_ts"] is None:
                t["policy_weak_entry_ts"] = decision_ts
            elapsed_s = (decision_ts - t["policy_weak_entry_ts"]) / 1e9
            persistence_bucket = _persistence_bucket(elapsed_s)
        else:
            t["policy_weak_entry_ts"] = None
            persistence_bucket = ""

        # ---- Score path (live, causal -- 10s lookback via the
        # trade's own rolling prob history). Selection rule MUST match
        # stop_state_features.py's offline two-pointer convention
        # exactly (first element with ts >= target_ts, scanning from
        # the oldest end) -- fixed per the 2026-07-11 pre-execution
        # audit WARNING: the original live version selected the LAST
        # element <= target_ts instead, which only coincides with the
        # offline choice on gapless uniform 1s cadence and silently
        # diverges across any data gap.
        hist = t["policy_prob_history"]
        target_ts = decision_ts - int(SCORE_PATH_LOOKBACK_S * 1e9)
        prior_prob = None
        for ts_h, p_h in hist:
            if ts_h >= target_ts:
                prior_prob = p_h
                break
        if prior_prob is None:
            score_path = "flat"
        elif prob > prior_prob + SCORE_PATH_EPS:
            score_path = "rising"
        elif prob < prior_prob - SCORE_PATH_EPS:
            score_path = "improving"
        else:
            score_path = "flat"
        hist.append((decision_ts, prob))

        # ---- E1: direct exit at high weakness (no stop distance)
        if cfg.direct_exit_decile and decile >= cfg.direct_exit_decile:
            if not t["policy_direct_exit_done"]:
                t["policy_direct_exit_done"] = True
                self._submit_exit(reason="stop_policy_direct")
            return

        if not cfg.arm_decile:
            return  # E1-only config or disabled

        score_improved = score_path == "improving"
        new_mfe_this_bar = mfe_atr > t.get("policy_prev_mfe_atr", mfe_atr)
        t["policy_prev_mfe_atr"] = mfe_atr

        new_state = next_policy_state(
            cfg, t["policy_state"], decile, persistence_bucket,
            score_improved, new_mfe_this_bar)

        if new_state != t["policy_state"]:
            if new_state == STATE_NONE:
                if (cfg.reversible_with_floor
                        and t["policy_state"] != STATE_NONE):
                    # S7's one-level loosening can land on NONE (e.g.
                    # ARMED -> NONE). This is still a LOOSENING of an
                    # already-armed protective stop, not "never
                    # armed" -- it must floor-clamp, not remove the
                    # stop entirely (fixed per the 2026-07-11
                    # pre-execution re-audit CRITICAL finding: the
                    # original code routed this through the same
                    # branch as "genuinely never armed" and dropped
                    # the floor guarantee the module docstring
                    # promises).
                    floor_price = ep + d * cfg.protect_floor_atr * safe_atr
                    t["policy_stop_price"] = floor_price
                else:
                    # Genuinely never armed (current_state was already
                    # NONE) -- no stop to floor-clamp.
                    t["policy_stop_price"] = None
                t["policy_state"] = STATE_NONE
            else:
                target_decile = decile_for_state(cfg, new_state)
                mae_atr_budget = engine.lookup_recovery_mae(
                    target_decile, persistence_bucket or "first_touch",
                    score_path, cfg.percentile, cfg.anchor_mode)
                if mae_atr_budget is not None:
                    if cfg.anchor_mode == "checkpoint":
                        anchor_price = c
                    else:  # "mfe"
                        anchor_price = ep + d * t["running_mfe"]
                    raw_stop = anchor_price - d * mae_atr_budget * safe_atr
                    new_stop = (
                        (int(raw_stop / TICK)) * TICK if d == 1
                        else (-(int(-raw_stop / TICK))) * TICK)
                    cur_stop = t["policy_stop_price"]
                    tighter = (cur_stop is None or
                                  (d == 1 and new_stop > cur_stop) or
                                  (d == -1 and new_stop < cur_stop))
                    is_loosening = new_state < t["policy_state"]
                    if tighter or is_loosening:
                        # Loosening only reaches here via the
                        # reversible path (next_policy_state already
                        # enforces the one-level rule), so honor it
                        # directly -- floor-clamp it too.
                        if cfg.reversible_with_floor and is_loosening:
                            floor_price = ep + d * cfg.protect_floor_atr * safe_atr
                            if d == 1:
                                new_stop = max(new_stop, floor_price)
                            else:
                                new_stop = min(new_stop, floor_price)
                        t["policy_stop_price"] = new_stop
                        # Only advance policy_state on a SUCCESSFUL
                        # lookup that ALSO actually changed the stop
                        # (tighter, or a legitimate reversible
                        # loosening) -- fixed per the 2026-07-11
                        # pre-execution audit: (a) a missing table
                        # cell must not advance state while leaving
                        # the stop stale/None (original CRITICAL), and
                        # (b) a non-monotonic table budget (the new
                        # state's budget happening to be WIDER than
                        # the current stop) must not advance the state
                        # LABEL either, since that would desync
                        # "policy_state" from the actually-applied
                        # stop distance (user-confirmed fix: label
                        # only advances in lockstep with a real stop
                        # change). Not expected in practice given
                        # Phase 4's monotonic decile gradient, but not
                        # structurally guaranteed, so enforced here.
                        t["policy_state"] = new_state
                    else:
                        self._diag["policy_label_held_not_tighter"] = (
                            self._diag.get(
                                "policy_label_held_not_tighter", 0) + 1)
                else:
                    self._diag["policy_lookup_miss"] = (
                        self._diag.get("policy_lookup_miss", 0) + 1)

        # ---- Internal monitor: fire market exit on cross
        stop_price = t.get("policy_stop_price")
        if stop_price is not None:
            triggered = ((d == 1 and float(bar.low) <= stop_price)
                            or (d == -1 and float(bar.high) >= stop_price))
            if triggered:
                self._submit_exit(reason="stop_policy")
