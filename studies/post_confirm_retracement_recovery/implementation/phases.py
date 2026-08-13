"""Phases 1, 3-6, 8-11: every descriptive and economic table, from the two panels.

Nothing here recomputes a path. Each function GROUPS `arm_panel` or
`recovery_state_panel`, so no table can disagree with the causal walk.

Two accounting disciplines are load-bearing and are enforced in `validate.py`:

*   CONSTANT POPULATION (gate V6). The denominator of every headline recovery
    probability is all ARM_FRESH arms in the cell. A trade that terminates before
    recovering is a FAILURE TO RECOVER, never a removal from the denominator.
    Survivor-conditioned variants carry the `_alive_only` suffix and may not
    carry a verdict -- conditioning on survival to the horizon is how a
    recovery-probability table gets talked into looking like a signal.

*   PAIRED CONDITIONALS (gate V7). A conditional recovery time is never emitted
    without its resolution rate on the same row. "Median 12 s to recover" means
    something entirely different at P(recover)=0.9 than at P(recover)=0.15.
"""
from __future__ import annotations

import numpy as np
import polars as pl

from .common import (
    ACCEPTED, ALREADY_AT_D, ARM_FRESH, CURVE_MAX_S, FAILED_STATES, HORIZONS_S,
    NO_ARM, PATH_STOP, PATH_UNC, RECOVERY_LEVELS, RETRACEMENTS, RUNGS,
    RUNNER_TIERS, is_underpowered, quantiles, trade_clustered_ci,
)

ALL = "ALL"


def _cells() -> list[tuple[float, float]]:
    return [(X, D) for X in RUNGS for D in RETRACEMENTS]


def _primary(arms: pl.DataFrame) -> pl.DataFrame:
    """The primary arm population: ARM_FRESH minus the trivially-recovered arms.

    SPEC 6.4. An `ARM_CLOSED_AT_HWM` arm spiked through the breach level intrabar
    and closed back at or above its own high-water mark, so `DD <= 0` and the
    R25/R50/R75 targets sit BELOW the arm bar's own close. The next bar
    "recovers" by construction, not by evidence, which would pull every recovery
    probability up and every recovery time down -- the same failure family as the
    predecessor's ALREADY_MET rows, which inflated a ladder by 21.9 points.

    The arms are counted on every table they are removed from, never dropped
    silently, and the panel itself retains them so the exclusion stays auditable.
    """
    return arms.filter((pl.col("stratum") == ARM_FRESH)
                       & ~pl.col("arm_closed_at_hwm").fill_null(False))


def _cell(arms: pl.DataFrame, X: float, D: float) -> pl.DataFrame:
    return _primary(arms).filter((pl.col("rung_atr") == X)
                                 & (pl.col("retracement_d") == D))


def _n_excluded(arms: pl.DataFrame, X: float, D: float) -> int:
    """ARM_FRESH arms removed from the cell by the SPEC 6.4 exclusion."""
    return arms.filter((pl.col("rung_atr") == X)
                       & (pl.col("retracement_d") == D)
                       & (pl.col("stratum") == ARM_FRESH)
                       & pl.col("arm_closed_at_hwm").fill_null(False)).height


def _q(vals: np.ndarray, n_trades: int, prefix: str = "") -> dict:
    qd = quantiles(vals, n_trades)
    return {f"{prefix}median": qd["p50"], f"{prefix}p25": qd["p25"],
            f"{prefix}p75": qd["p75"], f"{prefix}p90": qd["p90"]}


# ============================================================ Phase 1


def retracement_frequency(arms: pl.DataFrame) -> pl.DataFrame:
    """How normal is each retracement depth after each degree of progress?

    The denominator is every trade that reached the rung, including those that
    never retrace. `pct_retracing_any` counts a trade as retracing if it is D
    below its high-water mark at the rung bar OR at any bar after it;
    `pct_retracing_fresh` counts only the genuine post-rung transitions that
    every downstream table is built on.
    """
    rows = []
    for X, D in _cells():
        c = arms.filter((pl.col("rung_atr") == X) & (pl.col("retracement_d") == D))
        n_rung = c.height
        fresh = c.filter(pl.col("stratum") == ARM_FRESH)
        n_fresh = fresh.height
        n_already = c.filter(pl.col("stratum") == ALREADY_AT_D).height
        n_none = c.filter(pl.col("stratum") == NO_ARM).height
        row = {
            "rung_atr": X, "retracement_d": D, "path": PATH_UNC,
            "n_rung_trades": n_rung, "n_arm_fresh": n_fresh,
            "n_already_at_d": n_already, "n_no_arm": n_none,
            "partition_sums": bool(n_fresh + n_already + n_none == n_rung),
        }
        if n_rung == 0:
            rows.append({**row, "reason": "EMPTY_CELL"})
            continue
        row["pct_retracing_any"] = 100.0 * (n_fresh + n_already) / n_rung
        row["pct_retracing_fresh"] = 100.0 * n_fresh / n_rung
        if n_fresh == 0:
            rows.append({**row, "reason": "EMPTY_CELL"})
            continue

        n_tr = fresh["regime_id"].n_unique()
        secs = fresh["secs_rung_to_arm"].to_numpy()
        dd = fresh["dd_atr"].to_numpy()
        row.update(_q(secs, n_tr, "secs_rung_to_arm_"))
        row.update({
            "n_unique_trades": int(n_tr),
            "underpowered": is_underpowered(n_tr),
            "n_arm_closed_at_hwm": int(fresh["arm_closed_at_hwm"].sum()),
            "pct_dd_lt_d": 100.0 * float(fresh["dd_lt_d"].mean()),
            "dd_median": float(np.median(dd)),
            "dd_p25": float(np.quantile(dd, 0.25)),
            "dd_p75": float(np.quantile(dd, 0.75)),
            "mark_at_arm_atr_median": float(np.median(
                fresh["mark_arm_atr"].to_numpy())),
            "hwm_at_arm_atr_median": float(np.median(
                fresh["hwm_arm_atr"].to_numpy())),
            "pct_stop_live_reachable": 100.0 * float(
                fresh["arm_stop_live_reachable"].mean()),
            "reason": None,
        })
        rows.append(row)
    return pl.DataFrame(rows, infer_schema_length=None)


# ============================================================ Phase 3


def recovery_probability(arms: pl.DataFrame) -> pl.DataFrame:
    """P(recover) at each frozen level, constant-population and by horizon.

    `p_recover_before_terminal` is the headline: the fraction of ARM_FRESH arms
    that ever reach the frozen target before the unconstrained terminal. The
    horizon columns are the same statistic truncated, over the SAME denominator.
    """
    rows = []
    for X, D in _cells():
        fresh = _cell(arms, X, D)
        n = fresh.height
        n_excl = _n_excluded(arms, X, D)
        for lvl in RECOVERY_LEVELS:
            row = {"rung_atr": X, "retracement_d": D, "path": PATH_UNC,
                   "recovery_level": lvl, "n_arm_fresh": n,
                   "n_arm_closed_at_hwm_excluded": n_excl}
            if n == 0:
                rows.append({**row, "reason": "EMPTY_CELL"})
                continue
            secs = fresh[f"{lvl}_secs"].to_numpy().astype(float)
            life = fresh["secs_arm_to_unc_terminal"].to_numpy().astype(float)
            recovered = ~np.isnan(secs)
            n_tr = int(fresh["regime_id"].n_unique())
            row.update({
                "n_unique_trades": n_tr,
                "underpowered": is_underpowered(n_tr),
                "n_recovered": int(recovered.sum()),
                "n_terminated_first": int((~recovered).sum()),
                "p_recover_before_terminal": float(recovered.mean()),
            })
            for T in HORIZONS_S:
                by_t = recovered & (secs <= T)
                row[f"p_recover_{T}"] = float(by_t.mean())
                # Survivor-conditioned variant: at-risk means the path still runs
                # to T, or recovery already resolved inside it. SECONDARY ONLY.
                at_risk = (life >= T) | by_t
                row[f"n_alive_{T}"] = int(at_risk.sum())
                row[f"p_recover_{T}_alive_only"] = (
                    float(by_t[at_risk].mean()) if at_risk.any() else None)
            row["reason"] = None
            rows.append(row)
    return pl.DataFrame(rows, infer_schema_length=None)


# ============================================================ Phase 4


def recovery_timing(arms: pl.DataFrame) -> pl.DataFrame:
    """Time to recovery among trades that actually recover, PAIRED with the rate.

    Gate V7 forbids emitting the conditional median without `p_recovered` on the
    same row.
    """
    rows = []
    for X, D in _cells():
        fresh = _cell(arms, X, D)
        n = fresh.height
        n_excl = _n_excluded(arms, X, D)
        for lvl in RECOVERY_LEVELS:
            row = {"rung_atr": X, "retracement_d": D, "path": PATH_UNC,
                   "recovery_level": lvl, "n_arm_fresh": n,
                   "n_arm_closed_at_hwm_excluded": n_excl}
            if n == 0:
                rows.append({**row, "reason": "EMPTY_CELL"})
                continue
            secs = fresh[f"{lvl}_secs"].to_numpy().astype(float)
            rec = fresh.filter(pl.col(f"{lvl}_secs").is_not_null())
            n_rec = rec.height
            n_tr = int(rec["regime_id"].n_unique()) if n_rec else 0
            row.update({
                "n_recovered": n_rec,
                "n_unique_trades": n_tr,
                "p_recovered": float((~np.isnan(secs)).mean()),
                "underpowered": is_underpowered(n_tr),
            })
            row.update(_q(secs[~np.isnan(secs)], n_tr, "secs_"))
            row["reason"] = None
            rows.append(row)
    return pl.DataFrame(rows, infer_schema_length=None)


# ============================================================ Phase 5


def adverse_before_recovery(arms: pl.DataFrame) -> pl.DataFrame:
    """How much extra room does a recovering runner need after the retracement?

    Measured from MARK_ARM over (arm, recovery]. Arms that never recover are
    CENSORED and are counted on the row but excluded from the distribution: "how
    far did a failing trade fall" is a different question and pooling the two
    would answer neither.
    """
    rows = []
    for X, D in _cells():
        fresh = _cell(arms, X, D)
        for lvl in RECOVERY_LEVELS:
            row = {"rung_atr": X, "retracement_d": D, "path": PATH_UNC,
                   "recovery_level": lvl, "n_arm_fresh": fresh.height,
                   "n_arm_closed_at_hwm_excluded": _n_excluded(arms, X, D)}
            if fresh.height == 0:
                rows.append({**row, "reason": "EMPTY_CELL"})
                continue
            rec = fresh.filter(~pl.col(f"add_adverse_{lvl}_censored"))
            cens = fresh.filter(pl.col(f"add_adverse_{lvl}_censored"))
            n_tr = int(rec["regime_id"].n_unique()) if rec.height else 0
            vals = rec[f"add_adverse_{lvl}_atr"].to_numpy().astype(float)
            row.update({
                "n_recovered": rec.height, "n_censored": cens.height,
                "n_unique_trades": n_tr, "underpowered": is_underpowered(n_tr),
            })
            qd = quantiles(vals, n_tr, qs=(0.50, 0.75, 0.90, 0.95))
            row.update({"median_add_adverse_atr": qd["p50"], "p75": qd["p75"],
                        "p90": qd["p90"], "p95": qd["p95"]})
            # The censored arms' fall to terminal, reported apart so the contrast
            # is visible without contaminating the recoverer distribution.
            cv = cens[f"add_adverse_{lvl}_atr"].to_numpy().astype(float)
            row["censored_median_fall_atr"] = (
                float(np.median(cv)) if cv.size else None)
            row["reason"] = None
            rows.append(row)
    return pl.DataFrame(rows, infer_schema_length=None)


# ============================================================ Phase 10


def recovery_curves(arms: pl.DataFrame) -> pl.DataFrame:
    """P(recovered by t) for t = 0..300 s, per cell and level.

    Constant denominator throughout, so the curve is a genuine cumulative
    incidence and its plateau is a real plateau rather than a survivor artefact.
    The purpose is to see whether a knee exists; no threshold may be read off it.
    """
    grid = np.arange(0, CURVE_MAX_S + 1, dtype=float)
    rows = []
    for X, D in _cells():
        fresh = _cell(arms, X, D)
        n = fresh.height
        if n == 0:
            continue
        for lvl in RECOVERY_LEVELS:
            secs = fresh[f"{lvl}_secs"].to_numpy().astype(float)
            s = secs[~np.isnan(secs)]
            s.sort()
            cum = np.searchsorted(s, grid, side="right") / n
            for t, p in zip(grid, cum):
                rows.append({"rung_atr": X, "retracement_d": D, "path": PATH_UNC,
                             "recovery_level": lvl, "secs_since_arm": int(t),
                             "p_recovered": float(p), "n_denominator": n})
    return pl.DataFrame(rows, infer_schema_length=None)


# ============================================================ economics core


def econ_block(s: pl.DataFrame, key: dict, *, pop_armed: int) -> dict:
    """The standard economics block for one triggered set of state rows.

    EXIT NOW is `exit_now_mark_atr` -- bar j+1's OPEN. The high-water mark is
    never an exit price: pricing at the HWM cost the predecessor 61.6% of its
    headline and its confidence interval stopped excluding zero. The HWM column
    is carried for CONTRAST ONLY and is barred from every verdict.
    """
    n = s.height
    row = {**key, "path": PATH_STOP, "n_obs": n}
    if n == 0:
        return {**row, "n_unique_trades": 0, "reason": "EMPTY_CELL",
                "underpowered": True}
    tr = s["regime_id"].to_numpy()
    n_tr = int(s["regime_id"].n_unique())
    cme = s["cme_mark_nat"].to_numpy().astype(float)
    lo, hi = trade_clustered_ci(cme, tr)
    row.update({
        "n_unique_trades": n_tr,
        "underpowered": is_underpowered(n_tr),
        "pct_of_entries": 100.0 * n_tr / ACCEPTED["entries"],
        "pct_of_confirmed": 100.0 * n_tr / ACCEPTED["measurable_confirmed"],
        "pct_of_armed": (100.0 * n / pop_armed) if pop_armed else None,
        "exit_now_mark_atr": float(s["exit_now_mark_atr"].mean()),
        "exit_now_hwm_atr_CONTRAST_ONLY": float(
            s["exit_now_hwm_atr_CONTRAST_ONLY"].mean()),
        "continue_atr": float(s["continue_nat_atr"].mean()),
        "cme_mark_mean": float(cme.mean()),
        "cme_mark_median": float(np.median(cme)),
        "ci95_lo": lo, "ci95_hi": hi,
        "ci_excludes_zero": (bool(lo is not None and (lo > 0 or hi < 0))),
        "remaining_mfe_atr": float(s["remaining_mfe_stop_atr"].mean()),
        "remaining_mae_atr": float(s["remaining_mae_stop_atr"].mean()),
        "final_return_atr": float(s["nat_terminal_return_atr"].mean()),
        "p_winner": float(s["eventual_winner"].mean()),
        "p_loser": float(1.0 - s["eventual_winner"].mean()),
        "p_mfe_ge3": float((s["eventual_max_mfe_atr"] >= 3.0).mean()),
        "p_mfe_ge4": float((s["eventual_max_mfe_atr"] >= 4.0).mean()),
        "reason": None,
    })
    return row


def _stop_live(states: pl.DataFrame) -> pl.DataFrame:
    """Phase 8/9/11 population: the decision bar is reachable under accepted mgmt.

    Applies the SAME `ARM_CLOSED_AT_HWM` exclusion as `_primary`, so the economic
    tables and the descriptive tables are computed on one population rather than
    two that differ by a stratum nobody remembers.
    """
    return states.filter(pl.col("arm_stop_live_reachable")
                         & pl.col("alive_stop_live")
                         & ~pl.col("arm_closed_at_hwm").fill_null(False))


# ============================================================ Phase 8


def failed_recovery_economics(states: pl.DataFrame) -> pl.DataFrame:
    """Continuation value at every frozen failed-recovery state.

    Emitted both POOLED over rungs and depths -- where the statistical power is
    -- and per (rung, D) cell, where the neighbouring-cell agreement test that
    separates a real transition from an isolated lucky cell has to be run.
    """
    live = _stop_live(states)
    rows = []
    for state, lvl, horizons in FAILED_STATES:
        for T in horizons:
            at_t = live.filter(pl.col("horizon_s") == T)
            trig_all = at_t.filter(pl.col(f"failed_{lvl}_by_h"))
            rows.append(econ_block(
                trig_all,
                {"state": state, "recovery_level": lvl, "horizon_s": T,
                 "rung_atr": ALL, "retracement_d": ALL},
                pop_armed=at_t.height))
            for X, D in _cells():
                cell = at_t.filter((pl.col("rung_atr") == X)
                                   & (pl.col("retracement_d") == D))
                rows.append(econ_block(
                    cell.filter(pl.col(f"failed_{lvl}_by_h")),
                    {"state": state, "recovery_level": lvl, "horizon_s": T,
                     "rung_atr": str(X), "retracement_d": str(D)},
                    pop_armed=cell.height))
    return pl.DataFrame(rows, infer_schema_length=None)


# ============================================================ Phase 9


def runner_interception(states: pl.DataFrame) -> pl.DataFrame:
    """What each state would destroy, relative to accepted management.

    A state is not useful merely because continuation value is negative. It must
    preferentially catch bad outcomes WITHOUT destroying a large share of major
    runners -- the failure mode that killed the giveback and P90 branches, where
    loss containment was exactly cancelled by runner destruction.

    Membership requires the tier touch to fall while accepted management was
    still live: a runner the baseline never captured cannot be destroyed.
    """
    live = _stop_live(states)
    rows = []
    for state, lvl, horizons in FAILED_STATES:
        for T in horizons:
            at_t = live.filter(pl.col("horizon_s") == T)
            trig = at_t.filter(pl.col(f"failed_{lvl}_by_h"))
            row = {"state": state, "recovery_level": lvl, "horizon_s": T,
                   "path": PATH_STOP, "n_armed": at_t.height,
                   "n_triggered": trig.height,
                   "n_unique_trades": int(trig["regime_id"].n_unique())
                   if trig.height else 0}
            for tier in RUNNER_TIERS:
                tg = str(tier).replace(".", "_")
                mem = at_t.filter(pl.col(f"runner_{tg}_member"))
                mem_t = trig.filter(pl.col(f"runner_{tg}_member"))
                row[f"n_runners_ge{tg}"] = mem.height
                row[f"pct_runners_ge{tg}_intercepted"] = (
                    100.0 * float(mem_t[f"runner_{tg}_intercepted"].sum()) / mem.height
                    if mem.height else None)
            for name, flag in (("winners", True), ("losers", False)):
                sub = at_t.filter(pl.col("eventual_winner") == flag)
                sub_t = trig.filter(pl.col("eventual_winner") == flag)
                row[f"n_{name}"] = sub.height
                row[f"pct_{name}_intercepted"] = (
                    100.0 * sub_t.height / sub.height if sub.height else None)
            pw, pl_ = row["pct_winners_intercepted"], row["pct_losers_intercepted"]
            row["loser_winner_ratio"] = (pl_ / pw) if (pw and pl_ is not None) else None
            rows.append(row)
    return pl.DataFrame(rows, infer_schema_length=None)


# ============================================================ Phase 11


def conditional_value_curve(states: pl.DataFrame) -> pl.DataFrame:
    """"If the trade has STILL failed to recover by t, what is continuation worth?"

    The transition this table exists to detect -- valuable, then ambiguous, then
    clearly negative as failure duration grows -- is NOT assumed to exist. The
    ordered horizons are emitted whatever they show.
    """
    live = _stop_live(states)
    rows = []
    for lvl in RECOVERY_LEVELS:
        for T in HORIZONS_S:
            at_t = live.filter(pl.col("horizon_s") == T)
            trig = at_t.filter(pl.col(f"failed_{lvl}_by_h"))
            base = econ_block(trig, {"recovery_level": lvl, "horizon_s": T,
                                     "rung_atr": ALL, "retracement_d": ALL},
                              pop_armed=at_t.height)
            tg = "3_0"
            mem = at_t.filter(pl.col(f"runner_{tg}_member"))
            mem_t = trig.filter(pl.col(f"runner_{tg}_member"))
            base["runner_survival_rate"] = (
                1.0 - float(mem_t[f"runner_{tg}_intercepted"].sum()) / mem.height
                if mem.height else None)
            # The complement: what the RECOVERED arms were worth at the same t.
            # Without it, a negative continuation value cannot be distinguished
            # from every arm at that horizon being worth the same.
            recov = at_t.filter(~pl.col(f"failed_{lvl}_by_h"))
            base["n_recovered_obs"] = recov.height
            base["cme_mark_mean_recovered"] = (
                float(recov["cme_mark_nat"].mean()) if recov.height else None)
            rows.append(base)
    return pl.DataFrame(rows, infer_schema_length=None)
