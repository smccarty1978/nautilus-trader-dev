"""Phases 12-14: price-only diagnostics, placebo controls, side/year stability.

These run only after Phases 1-11 are frozen, and they remain RESEARCH
DIAGNOSTICS. No threshold outside the SPEC 5 grids may be searched, reported or
recommended: the study exists to find out whether failed recovery contains
economic information, not to manufacture another exit rule.
"""
from __future__ import annotations

import zlib

import numpy as np
import polars as pl

from .common import (
    ACCEPTED, ARM_FRESH, FAILED_STATES, HORIZONS_S, RECOVERY_LEVELS,
    RETRACEMENTS, RUNGS, RUNNER_TIERS, SEED, YEARS, is_underpowered,
    trade_clustered_ci,
)
from .phases import ALL, _primary, _stop_live, econ_block

ANY_RUNG = "ANY"


def _rule_id(X, D, lvl: str, T: int) -> str:
    x = "ANY" if X == ANY_RUNG else str(X).replace(".", "_")
    return f"X{x}_D{str(D).replace('.', '_')}_{lvl}_T{T}"


# ============================================================ Phase 12


def _triggers(live: pl.DataFrame, X, D: float, lvl: str, T: int) -> pl.DataFrame:
    """The triggered set for one frozen rule, FIRST TRIGGER PER TRADE.

    For a single-rung rule a trade has at most one arm in the cell, so the
    trigger is trivially first. For the ANY-rung rule a trade may arm at several
    rungs; only the EARLIEST decision timestamp is kept, because a live rule
    would have exited there and the later triggers never happen. Sorting by
    `decision_ts` before the unique() makes that explicit rather than relying on
    row order.
    """
    s = live.filter((pl.col("horizon_s") == T)
                    & (pl.col("retracement_d") == D)
                    & pl.col(f"failed_{lvl}_by_h"))
    if X != ANY_RUNG:
        s = s.filter(pl.col("rung_atr") == X)
    return (s.sort(["regime_id", "decision_ts", "rung_atr"])
             .unique(subset=["regime_id"], keep="first", maintain_order=True))


def price_only_diagnostics(states: pl.DataFrame) -> pl.DataFrame:
    """Simple candidate diagnostics implied directly by the recovery map.

    Denominators are ORIGINAL ENTRIES (8,950), so a rule that fires rarely cannot
    look large by shrinking its own population -- the defect that made a +246 ATR
    early-exit result evaporate against a count-matched control.
    """
    live = _stop_live(states)
    rows = []
    for D in RETRACEMENTS:
        for lvl in RECOVERY_LEVELS:
            for T in HORIZONS_S:
                for X in (*RUNGS, ANY_RUNG):
                    trig = _triggers(live, X, D, lvl, T)
                    base = {"rule_id": _rule_id(X, D, lvl, T),
                            "rung_atr": str(X), "retracement_d": D,
                            "recovery_level": lvl, "horizon_s": T,
                            "side": ALL, "entry_year": ALL}
                    rows.append(_rule_block(trig, base))
                    # Phase 14 breakouts on the same rule, same computation.
                    for side in ("LONG", "SHORT"):
                        rows.append(_rule_block(
                            trig.filter(pl.col("side") == side),
                            {**base, "side": side}))
                    for y in YEARS:
                        rows.append(_rule_block(
                            trig.filter(pl.col("entry_year") == y),
                            {**base, "entry_year": str(y)}))
    return pl.DataFrame(rows, infer_schema_length=None)


def _rule_block(trig: pl.DataFrame, key: dict) -> dict:
    n = trig.height
    row = {**key, "n_triggered_trades": n}
    if n == 0:
        return {**row, "reason": "EMPTY_CELL", "underpowered": True}
    cme = trig["cme_mark_nat"].to_numpy().astype(float)
    tr = trig["regime_id"].to_numpy()
    lo, hi = trade_clustered_ci(cme, tr)
    row.update({
        "underpowered": is_underpowered(n),
        "exit_return_atr": float(trig["exit_now_mark_atr"].mean()),
        "continuation_return_atr": float(trig["continue_nat_atr"].mean()),
        # Sign convention: delta is EXIT minus CONTINUE, so a POSITIVE delta
        # means exiting beat holding. `cme_mark_nat` is continue-minus-exit, the
        # predecessor's convention, so the two are exact negatives of each other
        # and both are emitted to stop a sign flip from surviving review.
        "delta_atr": float(-cme.mean()),
        "cme_mark_mean": float(cme.mean()),
        "ci95_lo": (None if lo is None else -hi),
        "ci95_hi": (None if hi is None else -lo),
        "delta_per_entry_atr": float(-cme.sum() / ACCEPTED["entries"]),
        "pct_of_entries": 100.0 * n / ACCEPTED["entries"],
        "reason": None,
    })
    for tier in RUNNER_TIERS:
        tg = str(tier).replace(".", "_")
        mem = trig.filter(pl.col(f"runner_{tg}_member"))
        row[f"n_runners_ge{tg}"] = mem.height
        row[f"pct_runners_ge{tg}_intercepted_of_triggered"] = (
            100.0 * float(mem[f"runner_{tg}_intercepted"].sum()) / mem.height
            if mem.height else None)
    row["n_winners_intercepted"] = int(trig["eventual_winner"].sum())
    row["n_losers_intercepted"] = int((~trig["eventual_winner"]).sum())
    return row


# ============================================================ Phase 13


def _matched(base: dict, cid: str, pop: pl.DataFrame, col: str, k: int,
             rule_mean: float) -> dict:
    """A count-matched control row, plus the full-population value beside it.

    The subsample is drawn from a generator seeded on the cell coordinates, so it
    is reproducible and cannot be re-rolled against an unfavourable comparison.
    """
    kk = min(k, pop.height)
    # crc32, not hash(): Python randomises string hashing per process, so a
    # hash-seeded control would draw a different subsample on every run and the
    # comparison would not be reproducible.
    rng = np.random.default_rng(
        (SEED + zlib.crc32(f"{cid}|{base['rule_id']}".encode())) % (2 ** 32))
    pick = rng.choice(pop.height, size=kk, replace=False)
    sel = pop[np.sort(pick).tolist()]
    cm = float(sel[col].mean())
    return {**base, "control_id": cid, "control_n": kk,
            "control_cme_mean": cm,
            "control_cme_mean_full_population": float(pop[col].mean()),
            "control_n_full_population": pop.height,
            "rule_minus_control": rule_mean - cm,
            "control_beats_rule": bool(cm <= rule_mean)}


def placebo_controls(arms: pl.DataFrame, states: pl.DataFrame) -> pl.DataFrame:
    """Every candidate rule against the six mandatory controls.

    A failed-recovery state must add information beyond "the trade has been open
    longer" or "the trade is currently in drawdown". Each control selects the
    SAME NUMBER of arms from the SAME armed population at the SAME horizon and
    exits at the same decision bar, so the only difference between rule and
    control is which arms get picked.

    RETRACEMENT_ONLY is the decisive one: it exits at the arm itself with no
    recovery condition attached. If it matches the rule, the recovery condition
    is decoration and the answer is R4.
    """
    live = _stop_live(states)
    fresh = _primary(arms)          # same SPEC 6.4 exclusion as every other table
    rows = []
    for state, lvl, horizons in FAILED_STATES:
        for T in horizons:
            for D in RETRACEMENTS:
                pop = live.filter((pl.col("horizon_s") == T)
                                  & (pl.col("retracement_d") == D))
                trig = _triggers(live, ANY_RUNG, D, lvl, T)
                k = trig.height
                if k == 0 or pop.height == 0:
                    continue
                rule_mean = float(trig["cme_mark_nat"].mean())
                lo, hi = trade_clustered_ci(trig["cme_mark_nat"].to_numpy(),
                                            trig["regime_id"].to_numpy())
                base = {"rule_id": _rule_id(ANY_RUNG, D, lvl, T),
                        "state": state, "recovery_level": lvl, "horizon_s": T,
                        "retracement_d": D, "n_armed_pop": pop.height,
                        "rule_n_triggered": k, "rule_cme_mean": rule_mean,
                        "rule_ci95_lo": lo, "rule_ci95_hi": hi}

                # De-duplicate the control population the same way the rule is
                # de-duplicated, so "top k" means the same thing on both sides.
                uniq = (pop.sort(["regime_id", "decision_ts", "rung_atr"])
                        .unique(subset=["regime_id"], keep="first",
                                maintain_order=True)
                        .with_columns(
                            dd_now=pl.col("run_mfe_atr") - pl.col("ret_from_entry_atr"),
                            age_confirm=pl.col("decision_ts") - pl.col("confirm_ns"),
                            age_rung=pl.col("decision_ts") - pl.col("rung_ts")))
                if uniq.height == 0:
                    continue
                kk = min(k, uniq.height)

                controls = {
                    # "The trade has been open longer."
                    "TIME_SINCE_CONFIRM_ONLY": uniq.sort("age_confirm", descending=True),
                    "TIME_SINCE_RUNG_ONLY": uniq.sort("age_rung", descending=True),
                    # "The trade is currently in drawdown."
                    "DRAWDOWN_FROM_HWM_ONLY": uniq.sort("dd_now", descending=True),
                    "CURRENT_RETURN_ONLY": uniq.sort("ret_from_entry_atr"),
                }
                for cid, ordered in controls.items():
                    sel = ordered.head(kk)
                    cm = float(sel["cme_mark_nat"].mean())
                    rows.append({**base, "control_id": cid,
                                 "control_n": sel.height,
                                 "control_cme_mean": cm,
                                 "rule_minus_control": rule_mean - cm,
                                 "control_beats_rule": bool(cm <= rule_mean)})

                # RETRACEMENT_ONLY -- exit at the arm bar, no recovery condition.
                # This control has NO ranking variable by construction (that is
                # the point: it is the retracement alone), so count-matching to k
                # is a seeded random subsample rather than a "top k". The
                # full-population value is emitted alongside it, because "what if
                # you always exited at the arm" is the question the R4 branch
                # actually turns on and a k-subsample only estimates it.
                arm_pop = (fresh.filter((pl.col("retracement_d") == D)
                                        & pl.col("arm_stop_live_reachable"))
                           .sort(["regime_id", "arm_ts"])
                           .unique(subset=["regime_id"], keep="first",
                                   maintain_order=True))
                if arm_pop.height:
                    rows.append(_matched(base, "RETRACEMENT_ONLY", arm_pop,
                                         "cme_mark_nat_at_arm", k, rule_mean))

                # RANDOM_TIMING -- length-blind grid offsets, drawn in the walk.
                rp = fresh.filter((pl.col("retracement_d") == D)
                                  & pl.col("arm_stop_live_reachable")
                                  & pl.col("placebo_cme_mean_fired").is_not_null())
                if rp.height:
                    row = _matched(base, "RANDOM_TIMING", rp,
                                   "placebo_cme_mean_fired", k, rule_mean)
                    row["control_fire_rate"] = float(rp["placebo_fire_rate"].mean())
                    rows.append(row)
    return pl.DataFrame(rows, infer_schema_length=None)


# ============================================================ Phase 14


def by_side(states: pl.DataFrame) -> pl.DataFrame:
    """Every failed-recovery state split LONG / SHORT, with an inversion flag.

    The predecessor found substantial LONG/SHORT inversion, so this breakout is
    mandatory. Opposite signs are a major warning; identical magnitude is not
    required.
    """
    live = _stop_live(states)
    rows = []
    for state, lvl, horizons in FAILED_STATES:
        for T in horizons:
            at_t = live.filter(pl.col("horizon_s") == T)
            per = {}
            for side in ("LONG", "SHORT"):
                trig = at_t.filter((pl.col("side") == side)
                                   & pl.col(f"failed_{lvl}_by_h"))
                blk = econ_block(trig, {"state": state, "recovery_level": lvl,
                                        "horizon_s": T, "rung_atr": ALL,
                                        "retracement_d": ALL, "side": side},
                                 pop_armed=at_t.filter(
                                     pl.col("side") == side).height)
                per[side] = blk.get("cme_mark_mean")
                rows.append(blk)
            a, b = per.get("LONG"), per.get("SHORT")
            inv = bool(a is not None and b is not None and a * b < 0)
            for r in rows[-2:]:
                r["sign_inverted"] = inv
    return pl.DataFrame(rows, infer_schema_length=None)


def by_year(states: pl.DataFrame) -> pl.DataFrame:
    """Every failed-recovery state split 2021-2025, with a consistency count."""
    live = _stop_live(states)
    rows = []
    for state, lvl, horizons in FAILED_STATES:
        for T in horizons:
            at_t = live.filter(pl.col("horizon_s") == T)
            block = []
            for y in YEARS:
                trig = at_t.filter((pl.col("entry_year") == y)
                                   & pl.col(f"failed_{lvl}_by_h"))
                block.append(econ_block(
                    trig, {"state": state, "recovery_level": lvl, "horizon_s": T,
                           "rung_atr": ALL, "retracement_d": ALL,
                           "entry_year": str(y)},
                    pop_armed=at_t.filter(pl.col("entry_year") == y).height))
            vals = [r.get("cme_mark_mean") for r in block
                    if r.get("cme_mark_mean") is not None]
            n_neg = sum(1 for v in vals if v < 0)
            for r in block:
                r["years_with_data"] = len(vals)
                r["years_cme_negative"] = n_neg
                r["years_consistent"] = max(n_neg, len(vals) - n_neg)
            rows.extend(block)
    return pl.DataFrame(rows, infer_schema_length=None)
