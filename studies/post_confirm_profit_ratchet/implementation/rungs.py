"""Rung events, next-rung transitions, and protective-stop survival, per trade.

One boundary governs every function here, and it is enforced structurally rather
than by convention:

    ARM    the rung index ``r`` is a function of ``bar_hi[:r+1]`` alone.
    LABEL  every transition, excursion and policy outcome reads ``(r..unc_i]``,
           from suffix slices that literally begin at ``r+1``.

Two things in this module are load-bearing and easy to get subtly wrong, so both
are stated where they are implemented:

*   The high-water reference for a stop on bar ``k`` is ``run_mfe[k-1]`` -- the
    running favorable extreme through the PREVIOUS COMPLETED bar. That is causal
    (a stop cannot ratchet on a bar that has not closed) and it is adverse (a bar
    that both sets a new high and breaches the old level counts as stopped).
    Using ``run_mfe[k]`` would let a bar's own high lift the stop above its own
    low -- a same-bar look-ahead that manufactures survival.

*   The window ``(r, t]`` INCLUDES the target bar ``t``. If that bar's low also
    breaches the stop, intra-second ordering is unknowable from OHLC and the
    economic reading is "stopped". The optimistic bound, over ``(r, t)``, is
    carried alongside and is never a substitute.

The correspondence between the two is exact and is asserted in validate.py:
a high-water ratchet of distance D survives to t iff ``mae_from_hwm < D``; a
static floor at ``X - D`` survives iff ``retrace_below_rung < D``. The Phase 5
frontier is therefore the empirical CDF of the Phase 2 statistic, not a second,
independently-fallible computation of the same thing.
"""
from __future__ import annotations

import numpy as np

from studies.model_driven_entry_exit_discovery.implementation.engine import (
    COST_POINTS, FLAT_POINTS, NS,
)
from studies.top10_fast_confirm_runner_path.implementation.engine import (
    STOP_ATR, prepare, runner_bucket,
)

# ---- frozen grids (SPEC D2, D7, D9). None of these is optimisable. --------
RUNGS = (1.0, 1.5, 2.0, 2.5, 3.0, 4.0)
STEPS = (0.50, 1.00)
STOP_DISTANCES = (0.25, 0.375, 0.50, 0.625, 0.75, 1.00, 1.25)
RUNNER_TIERS = (2.0, 2.5, 3.0, 4.0, 5.0)
# Fixed elapsed windows for the duration-matched comparison (SPEC D12).
HORIZONS_S = (15, 30, 60, 120, 300)
ARCHITECTURES = ("STATIC", "HWM", "LADDER_STATIC")

# Placebo arming grid, inherited verbatim from the predecessor's dense grid so
# the length-blind control draws from a support that is already audited.
DENSE_OFFSETS_S = tuple(range(15, 601, 15))
N_PLACEBO = 20
SEED = 20260811

BASIS_POST, BASIS_ENTRY = "POST_CONFIRM", "FROM_ENTRY"
ARM_FRESH, ARM_AT_CONFIRM = "ARM_FRESH", "ARM_AT_CONFIRM"
SUCCESS, FAIL, ALREADY_MET = "SUCCESS", "FAIL", "ALREADY_MET"


def tag(x: float) -> str:
    return str(x).replace(".", "_")


def _first(mask: np.ndarray) -> int:
    hit = np.flatnonzero(mask)
    return int(hit[0]) if hit.size else -1


class RatchetTrade:
    """One measurable confirmed trade: rung events, transitions, policy exits.

    Wraps the accepted ``Window`` from the predecessor rather than re-deriving a
    window. A policy that built its own window could silently be looking at a
    different set of bars from the descriptive geometry that motivated it, which
    is precisely how a spurious edge gets manufactured.
    """

    __slots__ = ("w", "meta", "hwm_prev", "n", "nat_ret", "unc_ret", "tables",
                 "tier_idx", "fill_ret")

    def __init__(self, w, meta: dict):
        self.w = w
        self.meta = meta
        self.n = w.ts.size
        self.nat_ret = w.realise(w.nat_i, w.nat_fill_next)
        self.unc_ret = w.realise(w.unc_i, False)
        # High-water mark through the PREVIOUS completed bar. hwm_prev[0] is the
        # pre-trade state and is -inf so bar 0 can never be "stopped" by a level
        # that did not exist yet.
        self.hwm_prev = np.concatenate(([-np.inf], w.run_mfe[:-1]))
        self.fill_ret = self._fill_returns()

    def _fill_returns(self) -> np.ndarray:
        """Vectorised ``Window.realise(i, fill_next=True)`` for every bar.

        The placebo contract needs ~23M fill evaluations; doing them one call at
        a time is not merely slow, it is a second implementation of the fill
        convention that could drift from the one the baseline uses. This array is
        asserted equal to ``w.realise(i, True)`` bar-for-bar in validate.py, so
        there is exactly one fill convention in the study and it is the accepted
        one: a trigger on bar i is priced at bar i+1's OPEN (H4).
        """
        w = self.w
        i = np.arange(self.n)
        f = w.start + i + 1
        ok = (f < w.sess_end) & (f < w.market.n)
        p = np.where(ok, w.market.open_[np.clip(f, 0, w.market.n - 1)],
                     w.market.close[w.start + i])
        pts = (p - w.px) * w.d
        return np.where(np.abs(pts) < FLAT_POINTS, 0.0, pts / w.atr)

    # ------------------------------------------------------------- Phase 1
    def rung_index(self, X: float, basis: str) -> int:
        """First bar at which the trade has earned X ATR, on the given basis.

        ``bar_hi[k] >= X`` and ``run_mfe[k] >= X`` pick the same first bar, since
        run_mfe is a cummax of max(bar_hi, 0) and X > 0. The POST_CONFIRM basis
        CLAMPS to the confirmation bar instead of demanding a fresh touch: at
        confirmation the running MFE is already causally known, so a live rule
        arms immediately. Requiring a re-touch would select on a retracement --
        the exact variable under study (SPEC D2).
        """
        w = self.w
        r = _first(w.bar_hi[:w.unc_i + 1] >= X)
        if r < 0:
            return -1
        return r if basis == BASIS_ENTRY else max(r, w.ci)

    def rung_event(self, X: float, basis: str) -> dict | None:
        w = self.w
        r = self.rung_index(X, basis)
        if r < 0:
            return None
        r_entry = _first(w.bar_hi[:w.unc_i + 1] >= X)
        return {
            **self.meta,
            "rung_atr": X,
            "basis": basis,
            "stratum": ARM_FRESH if r_entry >= w.ci else ARM_AT_CONFIRM,
            "rung_idx": int(r),
            "rung_ts": int(w.ts[r]),
            "rung_entry_idx": int(r_entry),
            "secs_confirm_to_rung": float((int(w.ts[r]) - w.confirm_ns) / NS),
            # What the trade has actually banked at the arming bar. For a clamped
            # ARM_AT_CONFIRM event this can be far above X, which is exactly the
            # asymmetry Phase 7 exists to measure.
            "hwm_at_arm_atr": float(w.run_mfe[r]),
            "rung_overshoot_atr": float(w.run_mfe[r] - X),
            "mark_at_arm_atr": float(w.mark[r]),
            "stop_live_reachable": bool(r <= w.nat_i),
            "secs_arm_to_nat_terminal": float(
                (int(w.ts[w.nat_i]) - int(w.ts[r])) / NS),
            "secs_arm_to_unc_terminal": float(
                (int(w.ts[w.unc_i]) - int(w.ts[r])) / NS),
        }

    # ----------------------------------------------------------- Phase 2/3
    def transition(self, ev: dict, step: float) -> dict:
        """SUCCESS/FAIL for target X+step, with both adverse-excursion measures.

        Everything below indexes from ``r+1``. There is no expression in this
        method that can read bar ``r`` or earlier as a forward quantity.
        """
        w = self.w
        r, unc = ev["rung_idx"], w.unc_i
        X = ev["rung_atr"]
        Y = X + step
        out = {"step_atr": step, "target_atr": Y}

        suffix_hi = w.bar_hi[r + 1:unc + 1]
        t_rel = _first(suffix_hi >= Y) if suffix_hi.size else -1
        t = (r + 1 + t_rel) if t_rel >= 0 else unc
        ok = t_rel >= 0

        # The predecessor's ladder asked exactly one question -- "does a bar
        # STRICTLY AFTER the rung bar reach X+step" -- and its accepted
        # P(next +0.50) values are that statistic. It is carried unconditionally
        # so SPEC gate 3 can reproduce the accepted ladder from the FROM_ENTRY
        # basis, independent of how this study classifies the row.
        out["lineage_next_reached"] = bool(ok)

        # The already-met trap (SPEC D2): an arming whose banked MFE ALREADY
        # exceeds the target -- the norm for a clamped ARM_AT_CONFIRM event, rare
        # for a fresh one. Its required adverse excursion is zero by
        # construction, not by evidence, so it is classified apart and excluded
        # from every distribution downstream. A running extremum mechanically
        # contains an eventual extremum; leaving these rows in a transition
        # distribution is how that inflates a result.
        if w.run_mfe[r] >= Y:
            out |= {"outcome": ALREADY_MET, "target_idx": -1, "secs_to_target": None,
                    "retrace_below_rung_atr": None, "mae_from_hwm_atr": None,
                    "retrace_below_rung_optimistic_atr": None,
                    "mae_from_hwm_optimistic_atr": None,
                    "collision_at_target": False, "fail_terminal_kind": None}
            out |= self._failure_geometry(r, unc, X)
            return out

        adv = self._adverse(r, t, X)
        # The optimistic bound excludes the target bar's own low (SPEC D5). When
        # the target is touched on the very next bar the optimistic window is
        # EMPTY and the bound is 0.0 -- which `_adverse` already returns via its
        # `t <= r` guard. Special-casing that back onto `adv` would make the
        # bound a literal substitute for the adverse number on exactly the
        # subset where the two differ most, and would zero `collision_at_target`
        # for the single-bar transitions most likely to have collided.
        opt = self._adverse(r, t - 1, X) if ok else adv
        out |= {
            "outcome": SUCCESS if ok else FAIL,
            "target_idx": int(t) if ok else -1,
            "secs_to_target": (float((int(w.ts[t]) - int(w.ts[r])) / NS)
                               if ok else None),
            "retrace_below_rung_atr": adv[0],
            "mae_from_hwm_atr": adv[1],
            "retrace_below_rung_optimistic_atr": opt[0],
            "mae_from_hwm_optimistic_atr": opt[1],
            "collision_at_target": bool(ok and adv != opt),
            "fail_terminal_kind": None if ok else w.unc_kind,
        }
        out |= self._failure_geometry(r, unc, X)
        return out

    def _adverse(self, r: int, t: int, X: float) -> tuple[float, float]:
        """The two SPEC D4 measures over the half-open-left window ``(r, t]``."""
        w = self.w
        if t <= r:
            return 0.0, 0.0
        lo = w.bar_lo[r + 1:t + 1]
        hwm = self.hwm_prev[r + 1:t + 1]
        return float(X - lo.min()), float(np.max(hwm - lo))

    def _failure_geometry(self, r: int, unc: int, X: float) -> dict:
        """Phase 3: how the path deteriorates from the rung to the terminal.

        Computed for every rung event, not only failures, so that the failure
        table and the success table are the same measurement on two populations
        -- a matched comparison rather than two differently-built statistics.
        """
        w = self.w
        if r >= unc:
            return {**{f"mae_from_hwm_h{H}s_atr": 0.0 for H in HORIZONS_S},
                    **{f"censored_h{H}s": True for H in HORIZONS_S},
                    "max_additional_mfe_after_rung_atr": 0.0,
                    "mae_from_hwm_to_terminal_atr": 0.0,
                    "retrace_below_rung_to_terminal_atr": 0.0,
                    "giveback_hwm_to_terminal_atr": float(w.run_mfe[unc] - self.unc_ret),
                    "secs_rung_to_terminal": 0.0,
                    "another_favorable_extreme_after_rung": False,
                    "unc_terminal_return_from_rung_atr": 0.0}
        hi = w.bar_hi[r + 1:unc + 1]
        lo = w.bar_lo[r + 1:unc + 1]
        hwm = self.hwm_prev[r + 1:unc + 1]
        # FIXED-HORIZON drawdowns, measured identically for SUCCESS and FAIL.
        # The whole-window statistic cannot compare the two classes: a SUCCESS
        # window ends at the target (median ~50 s) and a FAIL window runs to the
        # terminal (median ~300 s), so a longer window mechanically contains a
        # larger maximum and any AUC over them is measuring duration. These
        # columns put both classes on the SAME elapsed window (SPEC D12).
        horiz = {}
        ts_suf = w.ts[r + 1:unc + 1]
        for H in HORIZONS_S:
            end = _first(ts_suf > int(w.ts[r]) + H * NS)
            k = (end if end >= 0 else lo.size)
            horiz[f"mae_from_hwm_h{H}s_atr"] = (
                float(np.max(hwm[:k] - lo[:k])) if k > 0 else 0.0)
            # Censored means the path ENDED before H elapsed -- a timestamp
            # question, not a bar-count one. Comparing `k` (bars) against `H`
            # (seconds) would only coincide if the 1s path had exactly one bar
            # per second with no gaps, which is not guaranteed across a session.
            horiz[f"censored_h{H}s"] = bool(
                k == 0 or int(ts_suf[k - 1]) < int(w.ts[r]) + H * NS)
        return {**horiz,
            "max_additional_mfe_after_rung_atr": float(max(hi.max(), w.run_mfe[r])
                                                       - w.run_mfe[r]),
            "mae_from_hwm_to_terminal_atr": float(np.max(hwm - lo)),
            "retrace_below_rung_to_terminal_atr": float(X - lo.min()),
            "giveback_hwm_to_terminal_atr": float(w.run_mfe[unc] - self.unc_ret),
            "secs_rung_to_terminal": float(
                (int(w.ts[unc]) - int(w.ts[r])) / NS),
            "another_favorable_extreme_after_rung": bool(hi.max() > w.run_mfe[r]),
            "unc_terminal_return_from_rung_atr": float(self.unc_ret - w.mark[r]),
        }

    # ------------------------------------------------------------- Phase 5/6
    #
    # The placebo contract (SPEC D8) needs 20 length-blind draws plus 20
    # lifetime-uniform draws for every (rung, D, architecture) cell, which is
    # ~1.9M policy evaluations. Re-scanning the path for each would be both slow
    # and a second chance to get the boundary wrong, so each distinct stop
    # SURFACE is scanned once per trade into a "first breach at or after bar k"
    # table. Every arming -- real or placebo -- is then the same O(1) lookup
    # against the same table, which is why a placebo cannot accidentally be
    # evaluated on a different rule from the policy it controls.

    def _next_hit(self, breach: np.ndarray) -> np.ndarray:
        """`out[k]` = first index >= k where `breach` is true, else n (sentinel).

        `breach` is defined over the whole window; the caller always enters at
        `r+1`, so the observation bar can never return itself.
        """
        n = self.n
        idx = np.where(breach, np.arange(n), n)
        out = np.empty(n + 1, dtype=np.int64)
        out[:n] = np.minimum.accumulate(idx[::-1])[::-1]
        out[n] = n
        return out

    def build_exit_tables(self) -> None:
        """One breach surface per (architecture, level) pair. Built once."""
        w = self.w
        lo, hwm = w.bar_lo, self.hwm_prev
        live = np.arange(self.n) <= w.unc_i          # never trigger past terminal
        self.tables = {}

        for X in RUNGS:
            for D in STOP_DISTANCES:
                self.tables[("STATIC", X, D)] = self._next_hit(
                    (lo <= X - D) & live)

        # A high-water ratchet does not depend on which rung armed it -- the
        # level is a function of the path alone -- so one surface serves every
        # rung. That is also why LADDER_HWM is identically HWM (SPEC D7) and is
        # asserted rather than reported.
        rungs = np.array(RUNGS)
        for D in STOP_DISTANCES:
            self.tables[("HWM", None, D)] = self._next_hit((lo <= hwm - D) & live)
            # Highest frozen rung already earned as of the PREVIOUS bar. -inf
            # before the first rung, so the ladder floor cannot bind early.
            k = np.searchsorted(rungs, hwm, side="right") - 1
            floor = np.where(k >= 0, rungs[np.clip(k, 0, rungs.size - 1)] - D,
                             -np.inf)
            self.tables[("LADDER_STATIC", None, D)] = self._next_hit(
                (lo <= floor) & live)

        # First bar reaching each runner tier, for the D9 survival test.
        self.tier_idx = {}
        for T in RUNNER_TIERS:
            self.tier_idx[T] = _first(w.bar_hi[:w.unc_i + 1] >= T)

    def exit_index(self, r: int, D: float, arch: str, X: float) -> int:
        """First trigger bar strictly after `r`; -1 if the stop never fires.

        The TRIGGER bar is returned, never the fill bar. Pricing happens in
        ``policy`` via ``realise(i, fill_next=True)``, so the trigger level is
        never credited (checklist H4).
        """
        key = ("STATIC", X, D) if arch == "STATIC" else (arch, None, D)
        e = int(self.tables[key][min(r + 1, self.n)])
        return -1 if e >= self.n or e > self.w.unc_i else e

    def policy(self, r: int, D: float, arch: str, X: float) -> dict:
        """Realised outcome of arming `arch` at bar `r`, inside the accepted contract.

        The effective stop is ``max(-1.00, architecture level)`` and never
        loosens. Every level on the frozen grid is >= 1.0 - 1.25 = -0.25 ATR, so
        an armed architecture always dominates the initial 1.00 ATR stop; before
        arming, that stop is the only one. The policy terminal is therefore the
        first of {architecture trigger, opposing flip, 15:00 CT} -- which is what
        ``unc_i`` already encodes once the tighter stop is in force.
        """
        w = self.w
        if r > w.nat_i:
            # The rung arrived only after the accepted 1 ATR stop had already
            # closed the trade. Descriptively valid, economically inert.
            return {"participated": False, "policy_return_atr": float(self.nat_ret),
                    "policy_exit_kind": "NOT_REACHABLE", "policy_exit_idx": int(w.nat_i),
                    "policy_exit_ns": int(w.ts[w.nat_i])}
        e = self.exit_index(r, D, arch, X)
        if e < 0:
            return {"participated": True, "policy_return_atr": float(self.unc_ret),
                    "policy_exit_kind": w.unc_kind, "policy_exit_idx": int(w.unc_i),
                    "policy_exit_ns": int(w.ts[w.unc_i])}
        return {"participated": True, "policy_return_atr": float(w.realise(e, True)),
                "policy_exit_kind": "RATCHET", "policy_exit_idx": int(e),
                "policy_exit_ns": int(w.ts[e])}

    def returns_for_armings(self, arms: np.ndarray, D: float, arch: str,
                            X: float) -> np.ndarray:
        """Realised return for each arming bar in `arms`, same rule as `policy`.

        An arming index of -1 means "the rule never armed on this trade" and
        yields the untouched baseline -- which is what a live rule experiences
        when its trigger simply does not occur, and is the only treatment that
        keeps a placebo's denominator equal to the policy's.
        """
        key = ("STATIC", X, D) if arch == "STATIC" else (arch, None, D)
        tbl = self.tables[key]
        armed = arms >= 0
        lookup = np.where(armed, np.minimum(arms + 1, self.n), self.n)
        e = tbl[lookup]
        hit = armed & (e < self.n) & (e <= self.w.unc_i)
        return np.where(hit, self.fill_ret[np.clip(e, 0, self.n - 1)],
                        np.where(armed, self.unc_ret, self.nat_ret))

    # --------------------------------------------------------- Phase 6 tail
    def runner_survived(self, exit_idx: int, T: float) -> bool | None:
        """Was the trade still open when its path first touched T ATR of MFE?

        None when the path never reaches T -- the trade is not a member of that
        tier and must be counted as neither surviving nor destroyed.
        """
        k = self.tier_idx[T]
        if k < 0:
            return None
        return bool(exit_idx < 0 or k <= exit_idx)


def trade_meta(w, tr: dict) -> dict:
    """Per-trade constants and RETROSPECTIVE labels. Never arming inputs."""
    nat_ret = w.realise(w.nat_i, w.nat_fill_next)
    unc_ret = w.realise(w.unc_i, False)
    ev = float(w.run_mfe[w.unc_i])
    return {
        "regime_id": tr["regime_id"],
        "entry_year": tr["entry_year"],
        "side": tr["side"],
        "direction": int(tr["direction"]),
        "entry_ns": int(tr["entry_ns"]),
        "entry_price": float(w.px),
        "entry_atr": float(w.atr),
        "confirm_ns": int(w.confirm_ns),
        "terminal_label": tr["terminal_label"],
        "nat_kind": w.nat_kind,
        "nat_terminal_ns": int(w.ts[w.nat_i]),
        "nat_terminal_return_atr": float(nat_ret),
        "unc_kind": w.unc_kind,
        "unc_terminal_ns": int(w.ts[w.unc_i]),
        "unc_terminal_return_atr": float(unc_ret),
        "baseline_return_atr": float(nat_ret),
        "baseline_net_atr": float(nat_ret - COST_POINTS / w.atr),
        "nat_max_mfe_atr": float(w.run_mfe[w.nat_i]),
        "nat_giveback_atr": float(w.run_mfe[w.nat_i] - nat_ret),
        "eventual_max_mfe_atr": ev,
        "runner_bucket": runner_bucket(ev),
        "cost_atr": float(COST_POINTS / w.atr),
    }


def build_trade(market, regimes, tr: dict) -> RatchetTrade | None:
    w = prepare(market, regimes, tr)
    if w is None:
        return None
    return RatchetTrade(w, trade_meta(w, tr))
