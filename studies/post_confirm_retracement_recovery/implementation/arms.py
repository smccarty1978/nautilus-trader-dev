"""Retracement arms, frozen recovery anchors, and post-arm state — one walk per trade.

Three boundaries govern this module and each is enforced structurally rather
than by convention:

    ARM       the arm index ``a`` is a function of ``bar_lo[:a+1]`` and
              ``hwm_prev[:a+1]`` alone. ``hwm_prev[k] = run_mfe[k-1]`` is the
              running favorable extreme through the PREVIOUS COMPLETED bar, so a
              bar's own high can never lift the reference above its own low. Using
              ``run_mfe[k]`` would manufacture arms that never causally happened.

    ANCHOR    ``HWM_ARM`` and ``MARK_ARM`` are captured AT ``a`` and never move.
              Every recovery target is a frozen affine function of those two
              numbers. A later high-water mark does not raise the bar the trade
              has to clear -- that is the whole point of the study, and it is also
              the defect that would make "recovery" mechanically unreachable for
              exactly the healthiest paths.

    LABEL     every recovery event, horizon state and economic quantity reads a
              suffix slice that literally begins at ``a+1`` (or ``j+1``). There is
              no expression below that can read the arm bar as a forward quantity.

The window is the ACCEPTED ``Window`` from ``top10_fast_confirm_runner_path``,
wrapped rather than re-derived. A second window implementation could silently be
looking at a different set of bars from the geometry that motivated the study,
which is precisely how a spurious edge gets manufactured.
"""
from __future__ import annotations

import numpy as np

from studies.model_driven_entry_exit_discovery.implementation.engine import (
    COST_POINTS, FLAT_POINTS,
)
from studies.top10_fast_confirm_runner_path.implementation.engine import (
    prepare, runner_bucket,
)

from .common import (
    ALREADY_AT_D, ARM_FRESH, HORIZONS_S, NO_ARM, NS, N_PLACEBO, PATH_UNC,
    PLACEBO_OFFSETS_S, PROGRESS_LOOKBACKS_S, RECOVERY_FRACTION, RECOVERY_LEVELS,
    RETRACEMENTS, RUNGS, RUNNER_TIERS, first,
)


class RecoveryTrade:
    """One measurable confirmed trade: arm surfaces, recovery geometry, states."""

    __slots__ = ("w", "meta", "hwm_prev", "n", "nat_ret", "unc_ret", "fill_ret",
                 "arm_tbl", "tier_idx", "_rung_cache")

    def __init__(self, w, meta: dict):
        self.w = w
        self.meta = meta
        self.n = int(w.ts.size)
        self.nat_ret = float(w.realise(w.nat_i, w.nat_fill_next))
        self.unc_ret = float(w.realise(w.unc_i, False))
        # High-water mark through the PREVIOUS completed bar. Index 0 is the
        # pre-trade state and is -inf, so bar 0 can never be "retraced" against a
        # level that did not exist yet.
        self.hwm_prev = np.concatenate(([-np.inf], w.run_mfe[:-1]))
        self.fill_ret = self._fill_returns()
        self._rung_cache: dict[float, int] = {}

        # One breach surface per retracement depth. The HWM-relative trigger is a
        # function of the PATH alone -- it does not depend on which rung armed the
        # observation -- so four surfaces serve all 24 (rung x D) cells. That is
        # also why there is exactly one implementation of the trigger rather than
        # twenty-four chances to get it subtly different.
        live = np.arange(self.n) <= w.unc_i
        self.arm_tbl = {D: self._next_hit((w.bar_lo <= self.hwm_prev - D) & live)
                        for D in RETRACEMENTS}
        self.tier_idx = {T: first(w.bar_hi[:w.unc_i + 1] >= T) for T in RUNNER_TIERS}

    # ------------------------------------------------------------- primitives

    def _fill_returns(self) -> np.ndarray:
        """Vectorised ``Window.realise(i, fill_next=True)`` for every bar.

        Asserted equal to ``w.realise(i, True)`` bar-for-bar in validate.py (gate
        V10), so there is exactly ONE fill convention in this study and it is the
        accepted one: a trigger on bar ``i`` is priced at bar ``i+1``'s OPEN. The
        trigger price is never credited.
        """
        w = self.w
        i = np.arange(self.n)
        f = w.start + i + 1
        ok = (f < w.sess_end) & (f < w.market.n)
        p = np.where(ok, w.market.open_[np.clip(f, 0, w.market.n - 1)],
                     w.market.close[w.start + i])
        pts = (p - w.px) * w.d
        return np.where(np.abs(pts) < FLAT_POINTS, 0.0, pts / w.atr)

    def _next_hit(self, breach: np.ndarray) -> np.ndarray:
        """``out[k]`` = first index >= k where ``breach`` holds, else ``n``."""
        n = self.n
        idx = np.where(breach, np.arange(n), n)
        out = np.empty(n + 1, dtype=np.int64)
        out[:n] = np.minimum.accumulate(idx[::-1])[::-1]
        out[n] = n
        return out

    def _first_after(self, lo_excl: int, mask_from_lo: np.ndarray) -> int:
        """First absolute index > ``lo_excl`` satisfying a suffix mask, else -1."""
        rel = first(mask_from_lo)
        return -1 if rel < 0 else lo_excl + 1 + rel

    # ---------------------------------------------------------------- Phase 1

    def rung_index(self, X: float) -> int:
        """First bar at which the trade has earned X ATR, POST_CONFIRM basis.

        CLAMPED to the confirmation bar rather than demanding a fresh touch: at
        confirmation the running MFE is already causally known, so a live rule
        arms immediately. Requiring a re-touch would select on a retracement --
        the exact variable under study (accepted ratchet SPEC D2).
        """
        if X in self._rung_cache:
            return self._rung_cache[X]
        w = self.w
        r = first(w.bar_hi[:w.unc_i + 1] >= X)
        out = -1 if r < 0 else max(r, w.ci)
        self._rung_cache[X] = out
        return out

    def arm(self, X: float, D: float) -> dict | None:
        """The first retracement of depth D after rung X. ``None`` if X unreached.

        Returns a row for EVERY trade that reached the rung, including those that
        never retrace (``NO_ARM``) and those already at depth when the rung was
        recorded (``ALREADY_AT_D``). Omitting either would silently change the
        denominator of "% of rung trades retracing".
        """
        w = self.w
        r = self.rung_index(X)
        if r < 0:
            return None

        # The already-at-depth trap (SPEC 6.3). A POST_CONFIRM rung is clamped to
        # the confirmation bar, so at rung 1.0 the trade may already have banked
        # far more than X and already be D below that high-water mark. Its
        # time-to-arm is zero BY CONSTRUCTION, not by evidence, and its recovery
        # clock would start from a state the trade never freshly entered. The
        # analogous ALREADY_MET rows inflated a probability ladder by 21.9 points
        # in the accepted ratchet study.
        dd_at_rung = float(w.run_mfe[r] - w.mark[r])
        already = bool(dd_at_rung >= D or w.bar_lo[r] <= self.hwm_prev[r] - D)

        a = int(self.arm_tbl[D][min(r + 1, self.n)])
        if a >= self.n or a > w.unc_i:
            a = -1

        stratum = (ALREADY_AT_D if already else
                   (ARM_FRESH if a >= 0 else NO_ARM))

        row = {
            **self.meta,
            "rung_atr": X,
            "retracement_d": D,
            "rung_idx": int(r),
            "rung_ts": int(w.ts[r]),
            "hwm_at_rung_atr": float(w.run_mfe[r]),
            "mark_at_rung_atr": float(w.mark[r]),
            "dd_at_rung_atr": dd_at_rung,
            "secs_confirm_to_rung": float((int(w.ts[r]) - w.confirm_ns) / NS),
            "rung_stop_live_reachable": bool(r <= w.nat_i),
            "stratum": stratum,
            "arm_idx": int(a),
        }
        if a < 0:
            row.update({
                "arm_ts": None, "secs_rung_to_arm": None,
                "hwm_arm_atr": None, "mark_arm_atr": None, "dd_atr": None,
                "dd_lt_d": None, "arm_closed_at_hwm": None,
                "arm_stop_live_reachable": False,
                "secs_arm_to_nat_terminal": None,
                "secs_arm_to_unc_terminal": None,
                "exit_at_arm_mark_atr": None,
                "cme_mark_nat_at_arm": None,
            })
            return row

        # ---- FROZEN ANCHORS. Captured here, never updated (gate V5). --------
        hwm_arm = float(self.hwm_prev[a])
        mark_arm = float(w.mark[a])
        dd = hwm_arm - mark_arm
        row.update({
            "arm_ts": int(w.ts[a]),
            "secs_rung_to_arm": float((int(w.ts[a]) - int(w.ts[r])) / NS),
            "hwm_arm_atr": hwm_arm,
            "mark_arm_atr": mark_arm,
            "dd_atr": dd,
            # The trigger is intrabar and the anchor is the close, so the realised
            # depth is an OBSERVED quantity and need not equal D. Both cases are
            # reportable rather than assumed away.
            "dd_lt_d": bool(dd < D),
            "arm_closed_at_hwm": bool(dd <= 0.0),
            "arm_stop_live_reachable": bool(a <= w.nat_i),
            "secs_arm_to_nat_terminal": float(
                (int(w.ts[w.nat_i]) - int(w.ts[a])) / NS),
            "secs_arm_to_unc_terminal": float(
                (int(w.ts[w.unc_i]) - int(w.ts[a])) / NS),
            # Phase 13 control RETRACEMENT_ONLY: exit at the arm itself, with no
            # recovery condition attached. This is the DECISIVE control -- it
            # operationalises "the retracement itself is not sufficient". Priced
            # at bar a+1's OPEN like every other exit in this study.
            "exit_at_arm_mark_atr": float(self.fill_ret[a]),
            "cme_mark_nat_at_arm": float(self.nat_ret - self.fill_ret[a]),
        })
        return row

    # --------------------------------------------------------------- Phase 13

    def placebo_draws(self, arm_row: dict, rng: np.random.Generator) -> dict:
        """Length-blind random-timing control: `N_PLACEBO` draws from a GRID.

        The offset is drawn from a frozen second-grid, NEVER from the trade's
        realised lifetime. A uniform draw over the realised lifetime is itself
        look-ahead -- it cannot be made without knowing how long the trade lived
        -- and that defect has twice destroyed a headline in this repository
        (+0.618 ATR/trade collapsing to +0.011 once the placebo was made
        length-blind). When a drawn offset lands past the stop-live terminal the
        control simply does not fire, which is exactly what a live rule
        experiences, and keeps the control's denominator equal to the rule's.
        """
        w = self.w
        a = int(arm_row["arm_idx"])
        if a < 0:
            return {"placebo_n_fired": 0, "placebo_cme_mean_fired": None,
                    "placebo_fire_rate": None}
        offsets = rng.choice(np.array(PLACEBO_OFFSETS_S), size=N_PLACEBO)
        idx = np.searchsorted(w.ts, int(w.ts[a]) + offsets.astype(np.int64) * NS,
                              side="left")
        fired = (idx < self.n) & (idx <= w.nat_i)
        if not fired.any():
            return {"placebo_n_fired": 0, "placebo_cme_mean_fired": None,
                    "placebo_fire_rate": 0.0}
        cme = self.nat_ret - self.fill_ret[idx[fired]]
        return {"placebo_n_fired": int(fired.sum()),
                "placebo_cme_mean_fired": float(cme.mean()),
                "placebo_fire_rate": float(fired.mean())}

    # -------------------------------------------------------------- Phase 2/3

    def recovery_targets(self, hwm_arm: float, mark_arm: float,
                         dd: float) -> dict[str, float]:
        """The five frozen targets, anchored to the arm and invariant thereafter."""
        t = {lvl: mark_arm + f * dd for lvl, f in RECOVERY_FRACTION.items()}
        t["R100"] = hwm_arm          # reclaim: touch the old high
        t["NEW_HWM"] = hwm_arm       # exceed: strictly above (see `recovery`)
        return t

    def recovery(self, arm_row: dict) -> dict:
        """First bar in ``(a, unc_i]`` reaching each frozen recovery target.

        Detection is on the intrabar HIGH, symmetrically with the intrabar-low
        arm. Scanning starts at ``a+1``: the arm bar cannot recover itself.
        """
        w = self.w
        a = int(arm_row["arm_idx"])
        out: dict = {}
        if a < 0:
            for lvl in RECOVERY_LEVELS:
                out[f"{lvl}_idx"] = -1
                out[f"{lvl}_secs"] = None
            return out

        hwm_arm = float(arm_row["hwm_arm_atr"])
        mark_arm = float(arm_row["mark_arm_atr"])
        dd = float(arm_row["dd_atr"])
        targets = self.recovery_targets(hwm_arm, mark_arm, dd)
        suffix = w.bar_hi[a + 1:w.unc_i + 1]

        for lvl in RECOVERY_LEVELS:
            tgt = targets[lvl]
            # NEW_HWM is a STRICT exceedance; R100 is a touch. On a 0.25-tick
            # grid these are genuinely different events -- retesting the old high
            # versus setting a new one -- so both are carried.
            mask = (suffix > tgt) if lvl == "NEW_HWM" else (suffix >= tgt)
            k = self._first_after(a, mask) if suffix.size else -1
            out[f"{lvl}_idx"] = int(k)
            out[f"{lvl}_secs"] = (float((int(w.ts[k]) - int(w.ts[a])) / NS)
                                  if k >= 0 else None)
            out[f"{lvl}_target_atr"] = float(tgt)
        return out

    # ---------------------------------------------------------------- Phase 5

    def adverse_before_recovery(self, arm_row: dict, rec: dict) -> dict:
        """Max additional adverse excursion from MARK_ARM, before each recovery.

        Measured over ``(a, k]`` where ``k`` is the recovery bar. When recovery
        never occurs the excursion is measured to the unconstrained terminal and
        flagged CENSORED -- reported apart, never pooled with the recoverers,
        because "how much room did a recovering runner need" and "how far did a
        failing trade fall" are two different questions.
        """
        w = self.w
        a = int(arm_row["arm_idx"])
        out: dict = {}
        if a < 0:
            for lvl in RECOVERY_LEVELS:
                out[f"add_adverse_{lvl}_atr"] = None
                out[f"add_adverse_{lvl}_censored"] = None
            return out
        mark_arm = float(arm_row["mark_arm_atr"])
        for lvl in RECOVERY_LEVELS:
            k = int(rec[f"{lvl}_idx"])
            censored = k < 0
            end = w.unc_i if censored else k
            seg = w.bar_lo[a + 1:end + 1]
            out[f"add_adverse_{lvl}_atr"] = (
                float(max(0.0, mark_arm - seg.min())) if seg.size else 0.0)
            out[f"add_adverse_{lvl}_censored"] = bool(censored)
        return out

    # -------------------------------------------------------------- Phase 6/7

    def horizon_states(self, arm_row: dict, rec: dict) -> list[dict]:
        """Causal state at each frozen horizon after the arm, plus economics.

        Every field is computed from a slice bounded above by ``j``, the first bar
        at or after ``arm_ts + T``. The retrospective outcome fields carried
        alongside are LABELS ONLY and are enumerated in ``RETROSPECTIVE`` so the
        contract checker can verify none of them is read as state.
        """
        w = self.w
        a = int(arm_row["arm_idx"])
        if a < 0:
            return []
        hwm_arm = float(arm_row["hwm_arm_atr"])
        mark_arm = float(arm_row["mark_arm_atr"])
        dd = float(arm_row["dd_atr"])
        arm_ts = int(w.ts[a])

        # Identity, cell coordinates and frozen anchors, plus the RETROSPECTIVE
        # outcome labels the economics phases group by. The retrospective fields
        # are enumerated in RETROSPECTIVE below and are LABELS ONLY -- none of
        # them may be read as a state variable.
        key = {k: arm_row[k] for k in (
            "regime_id", "entry_year", "side", "direction", "entry_atr",
            "cost_atr", "confirm_ns", "terminal_label",
            "rung_atr", "retracement_d", "stratum", "rung_ts", "arm_idx",
            "arm_ts", "hwm_arm_atr", "mark_arm_atr", "dd_atr",
            "arm_closed_at_hwm", "arm_stop_live_reachable",
            "nat_kind", "unc_kind", "nat_terminal_return_atr",
            "unc_terminal_return_atr", "baseline_net_atr", "eventual_winner",
            "eventual_max_mfe_atr", "runner_bucket")}
        # The panel is the UNCONSTRAINED path by definition (SPEC §4, manifest
        # item 9): the state fields below ignore the stop. Economics tables
        # relabel their own rows PATH_STOP after filtering to the stop-live
        # subset. A row without this label cannot be read safely.
        key["path"] = PATH_UNC

        states = []
        for T in HORIZONS_S:
            j = first(w.ts >= arm_ts + int(T) * NS)
            alive = j >= 0
            if j < 0:
                j = w.unc_i          # carried terminal state, flagged not alive
            st = {
                **key,
                "horizon_s": int(T),
                "alive": bool(alive),
                "alive_stop_live": bool(alive and j <= w.nat_i),
                "decision_idx": int(j),
                "decision_ts": int(w.ts[j]),
                "secs_arm_to_decision": float((int(w.ts[j]) - arm_ts) / NS),

                # ---- Phase 6 recovery state -----------------------------
                "frac_dd_recovered": (float((w.mark[j] - mark_arm) / dd)
                                      if dd > 0 else None),
                "ret_from_entry_atr": float(w.mark[j]),
                "dist_below_hwm_arm_atr": float(hwm_arm - w.mark[j]),
                "run_mfe_atr": float(w.run_mfe[j]),
                "run_mae_atr": float(w.run_mae[j]),
            }
            seg_hi = w.bar_hi[a + 1:j + 1]
            seg_lo = w.bar_lo[a + 1:j + 1]
            st["made_new_hwm"] = bool(seg_hi.size and seg_hi.max() > hwm_arm)
            st["n_new_favourable_extremes"] = int(w.new_ext[a + 1:j + 1].sum())
            st["additional_adverse_atr"] = (
                float(max(0.0, mark_arm - seg_lo.min())) if seg_lo.size else 0.0)

            for W in PROGRESS_LOOKBACKS_S:
                jw = max(first(w.ts >= int(w.ts[j]) - W * NS), 0)
                st[f"prog_favourable_{W}s_atr"] = float(w.run_mfe[j] - w.run_mfe[jw])
                st[f"prog_adverse_{W}s_atr"] = float(w.run_mae[j] - w.run_mae[jw])
                st[f"prog_mark_{W}s_atr"] = float(w.mark[j] - w.mark[jw])
                # The trailing window may reach back before the arm. Every such
                # bar is causal past, so it is read rather than nulled, but the
                # flag keeps the two regimes distinguishable in analysis.
                st[f"prog_{W}s_spans_pre_arm"] = bool(jw <= a)

            # ---- Phase 7 failed-recovery labels, from (a, j] only ---------
            for lvl in RECOVERY_LEVELS:
                k = int(rec[f"{lvl}_idx"])
                st[f"recovered_{lvl}_by_h"] = bool(0 <= k <= j)
                st[f"failed_{lvl}_by_h"] = not bool(0 <= k <= j)

            # ---- Phase 8/11 economics. EXIT NOW is executable, always. ----
            # The mark is priced at bar j+1's OPEN. The HWM is descriptive state
            # and is emitted for contrast only: pricing an exit at the high-water
            # mark cost the predecessor 61.6% of its headline and its CI stopped
            # excluding zero.
            exit_mark = float(self.fill_ret[j])
            st["exit_now_mark_atr"] = exit_mark
            st["exit_now_hwm_atr_CONTRAST_ONLY"] = float(w.run_mfe[j])
            st["continue_nat_atr"] = float(self.nat_ret)
            st["continue_unc_atr"] = float(self.unc_ret)
            st["cme_mark_nat"] = float(self.nat_ret - exit_mark)
            st["cme_mark_unc"] = float(self.unc_ret - exit_mark)

            for name, end in (("stop", w.nat_i), ("unc", w.unc_i)):
                hi = w.bar_hi[j + 1:end + 1]
                lo = w.bar_lo[j + 1:end + 1]
                st[f"remaining_mfe_{name}_atr"] = (
                    float(max(0.0, hi.max() - w.mark[j])) if hi.size else 0.0)
                st[f"remaining_mae_{name}_atr"] = (
                    float(max(0.0, w.mark[j] - lo.min())) if lo.size else 0.0)

            # ---- Phase 9 interception, relative to accepted management ----
            for T2 in RUNNER_TIERS:
                ti = self.tier_idx[T2]
                # A runner the BASELINE never captured cannot be destroyed by a
                # rule. Membership therefore requires the tier touch to fall
                # while accepted management was still live.
                member = ti >= 0 and ti <= w.nat_i
                st[f"runner_{str(T2).replace('.', '_')}_member"] = bool(member)
                st[f"runner_{str(T2).replace('.', '_')}_intercepted"] = (
                    bool(member and j < ti))
            states.append(st)
        return states


# --------------------------------------------------------------------- labels
# Every retrospective field carried on a state row. None of these may be read as
# a state variable; the contract checker verifies the list against the panel.
RETROSPECTIVE: tuple[str, ...] = (
    "eventual_max_mfe_atr", "runner_bucket", "nat_terminal_return_atr",
    "unc_terminal_return_atr", "nat_kind", "unc_kind", "terminal_label",
    "baseline_net_atr", "continue_nat_atr", "continue_unc_atr",
    "cme_mark_nat", "cme_mark_unc",
    "remaining_mfe_stop_atr", "remaining_mae_stop_atr",
    "remaining_mfe_unc_atr", "remaining_mae_unc_atr",
    *[f"runner_{str(T).replace('.', '_')}_intercepted" for T in RUNNER_TIERS],
)


def trade_meta(w, tr: dict) -> dict:
    """Per-trade constants and RETROSPECTIVE labels. Never arming inputs."""
    nat_ret = float(w.realise(w.nat_i, w.nat_fill_next))
    unc_ret = float(w.realise(w.unc_i, False))
    ev = float(w.run_mfe[w.unc_i])
    cost = COST_POINTS / float(w.atr)
    return {
        "regime_id": tr["regime_id"],
        "entry_year": int(tr["entry_year"]),
        "side": tr["side"],
        "direction": int(tr["direction"]),
        "entry_ns": int(tr["entry_ns"]),
        "entry_atr": float(w.atr),
        "confirm_ns": int(w.confirm_ns),
        "terminal_label": tr["terminal_label"],
        "cost_atr": float(cost),
        "nat_kind": w.nat_kind,
        "nat_terminal_ns": int(w.ts[w.nat_i]),
        "nat_terminal_return_atr": nat_ret,
        "unc_kind": w.unc_kind,
        "unc_terminal_ns": int(w.ts[w.unc_i]),
        "unc_terminal_return_atr": unc_ret,
        "baseline_net_atr": float(nat_ret - cost),
        # Eventual outcome of ACCEPTED MANAGEMENT -- the baseline every rule in
        # this study is compared against, so winner/loser is defined on it.
        "eventual_winner": bool(nat_ret - cost > 0),
        "eventual_max_mfe_atr": ev,
        "runner_bucket": runner_bucket(ev),
    }


def build_trade(market, regimes, tr: dict) -> RecoveryTrade | None:
    w = prepare(market, regimes, tr)
    if w is None:
        return None
    return RecoveryTrade(w, trade_meta(w, tr))


def walk(rt: RecoveryTrade,
         rng: np.random.Generator) -> tuple[list[dict], list[dict]]:
    """All 24 (rung x D) cells for one trade: arm rows and horizon states.

    The placebo offsets are drawn from a generator seeded ONCE for the whole
    study, so the control is reproducible bit-for-bit and is never re-rolled
    against a result that came back unfavourable.
    """
    arms, states = [], []
    for X in RUNGS:
        for D in RETRACEMENTS:
            row = rt.arm(X, D)
            if row is None:
                continue            # rung never reached: not a member of the cell
            rec = rt.recovery(row)
            row.update({k: v for k, v in rec.items() if not k.endswith("_idx")})
            row.update({f"idx_{k[:-4]}": v for k, v in rec.items()
                        if k.endswith("_idx")})
            row.update(rt.adverse_before_recovery(row, rec))
            row.update(rt.placebo_draws(row, rng))
            arms.append(row)
            if row["stratum"] == ARM_FRESH:
                states.extend(rt.horizon_states(row, rec))
    return arms, states
