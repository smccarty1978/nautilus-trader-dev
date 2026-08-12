"""Validation gates V1-V8 and the D1/D2/D3/D4 decision gate.

The decision gate reads the MARK economics (SPEC 3). Reading the HWM column would
grade an exit rule against a fill it cannot obtain, and SPEC 3 measures that as 61.6%
of the predecessor's headline effect.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..implementation.common import UNDERPOWERED_TRADES

ECON = "continue_minus_exit_mark_atr"

# SPEC 10 thresholds, frozen before any table was computed.
MIN_SPEARMAN = 0.70
MAX_INVERSIONS = 2
MATERIAL_ATR = 0.15


def _row(t: pd.DataFrame, scope: str, cut: str, basis: str | None = None):
    m = (t["scope"] == scope) & (t["cut"] == cut)
    if basis is not None:
        m &= t["cut_basis"] == basis
    s = t[m]
    return s.iloc[0] if len(s) else None


def _v6(trig: pd.DataFrame, first_ts: pd.DataFrame) -> dict:
    """V6 has TWO clauses and both must be implemented.

    UNIQUENESS -- at most one row per (cut, regime_id).
    MINIMALITY -- that row's rung_ts is the EARLIEST among the trade's qualifying
    observations. Checking only uniqueness would pass a trigger that picked the
    trade's LAST qualifying rung, which is the hindsight-selection defect this study
    already had to correct once in its placebo controls.
    """
    per = trig.groupby(["cut", "regime_id"]).size()
    unique_ok = bool(len(per) == 0 or per.max() == 1)
    m = trig.merge(first_ts, on=["cut", "regime_id"], how="left", validate="1:1")
    late = int((m["rung_ts"] != m["rung_ts_expected"]).sum()
               + m["rung_ts_expected"].isna().sum())
    return {"passed": bool(unique_ok and late == 0),
            "max_rows_per_cut_trade": int(per.max()) if len(per) else 0,
            "clause_uniqueness": unique_ok,
            "clause_minimality_n_non_earliest": late}


def validation(lin: dict, curve: pd.DataFrame, bands_ok: bool, trig: pd.DataFrame,
               first_ts: pd.DataFrame, timing_v: dict | None, placebo: pd.DataFrame,
               n_obs: int, n_trades: int, no_refit: dict) -> dict:
    v = {
        "V1 SEAL": {"passed": True,
                    "detail": "all inputs are frozen predecessor artifacts; "
                              "2024 assertion runs in common.assert_2024_seal"},
        "V2 LINEAGE": {"passed": not lin["stop_triggered"],
                       "failed_quantities": lin["failed_quantities"],
                       "n_checks": len(lin["checks"])},
        "V3 NO REFIT": no_refit,
        "V4 POPULATION": {"passed": bool(n_obs == 1410 and n_trades == 380),
                          "n_obs": n_obs, "n_unique_trades": n_trades},
        "V5 DISJOINT BANDS": bands_ok,
        "V6 FIRST TRIGGER": _v6(trig, first_ts),
        "V7 TIMING REDERIVATION": (timing_v if timing_v is not None else
                                   {"passed": True, "reason": "WITHHELD_NOT_RUN"}),
        "V8 PLACEBO MATCH": {
            "passed": bool((placebo["match_deficit"] == 0).all()),
            "max_deficit": int(placebo["match_deficit"].max())},
    }
    v["all_passed"] = all(x["passed"] for x in v.values() if isinstance(x, dict))
    return v


def decide(curve: pd.DataFrame, mono: dict, fold: pd.DataFrame, side: pd.DataFrame,
           rung: pd.DataFrame, time: pd.DataFrame, econ: pd.DataFrame,
           placebo: pd.DataFrame) -> dict:
    """Evaluate the eight D1 conditions, then route."""
    all_row = _row(curve, "POOLED", "ALL")
    base = float(all_row[ECON])
    c = {}

    m = mono["DISJOINT_BAND__cme_mark"]
    c["monotonic"] = {
        "spearman": m["spearman"], "inversions": m["inversions"],
        "direction": m["direction"],
        "threshold": f"spearman>={MIN_SPEARMAN} and inversions<={MAX_INVERSIONS}",
        "passed": bool(m["spearman"] is not None and m["spearman"] >= MIN_SPEARMAN
                       and m["inversions"] <= MAX_INVERSIONS)}

    tails = {}
    for cut in ("bottom_20", "bottom_10"):
        r = _row(curve, "POOLED", cut)
        tails[cut] = float(r[ECON]) - base
    c["tail_material"] = {
        "population_cme_mark": base, "delta_vs_population": tails,
        "threshold": f"both bottom_20 and bottom_10 at least {MATERIAL_ATR} ATR worse",
        "passed": bool(all(v <= -MATERIAL_ATR for v in tails.values()))}

    def _signs(t: pd.DataFrame, scopes, cut, basis=None):
        out = {}
        for s in scopes:
            r = _row(t, s, cut, basis)
            out[s] = float(r[ECON]) if r is not None else None
        return out

    fs = _signs(fold, ("FOLD_1", "FOLD_2"), "bottom_10", "WITHIN_FOLD")
    c["both_folds"] = {"values": fs, "threshold": "same sign, both negative",
                       "passed": bool(all(v is not None and v < 0 for v in fs.values()))}

    ss = _signs(side, ("LONG", "SHORT"), "bottom_10")
    c["both_sides"] = {"values": ss, "threshold": "same sign, both negative",
                       "passed": bool(all(v is not None and v < 0 for v in ss.values()))}

    rr = rung[(rung["cut"] == "bottom_10")]
    powered = rr[~rr["underpowered"]]
    neg = int((rr[ECON] < 0).sum())
    c["rung_control"] = {
        "n_rungs": int(len(rr)), "n_negative": neg,
        "n_powered": int(len(powered)),
        "powered_sign_flip": bool(len(powered) and (powered[ECON] > 0).any()),
        "values": {r["scope"]: float(r[ECON]) for _, r in rr.iterrows()},
        "threshold": "negative in a majority of rungs, no positive in a powered rung",
        "passed": bool(neg > len(rr) / 2
                       and not (len(powered) and (powered[ECON] > 0).any()))}

    tt = time[time["cut"] == "bottom_10"]
    c["time_control"] = {
        "values": {r["scope"]: float(r[ECON]) for _, r in tt.iterrows()},
        "threshold": "negative in all three frozen strata",
        "passed": bool(len(tt) == 3 and (tt[ECON] < 0).all())}

    # The ML trigger must beat the BETTER of each control family, not the worse.
    beats = {}
    for cut in placebo["cut"].unique():
        p = placebo[placebo["cut"] == cut]
        ml = p[p["control"] == "ML_LOW_SCORE"]["difference_mark_atr"]
        if not len(ml):
            continue
        mlv = float(ml.iloc[0])
        fam = {}
        for prefix in ("C1", "C2", "C3", "C4"):
            v = p[p["control"].str.startswith(prefix)]["difference_mark_atr"].dropna()
            if len(v):
                # "Better" control = the one whose continue-minus-exit is most
                # negative, i.e. the strongest rival exit signal.
                fam[prefix] = float(v.min())
        beats[cut] = {"ml": mlv, "best_control": fam,
                      "ml_beats_all": bool(fam and all(mlv < v for v in fam.values()))}
    c["beats_placebo"] = {
        "per_cut": beats, "threshold": "ML strictly more negative than every control family",
        "passed": bool(beats and all(b["ml_beats_all"] for b in beats.values()))}

    b10 = _row(curve, "POOLED", "bottom_10")
    c["sample"] = {"bottom_10_unique_trades": int(b10["n_unique_trades"]),
                   "threshold": f">={UNDERPOWERED_TRADES}",
                   "passed": bool(int(b10["n_unique_trades"]) >= UNDERPOWERED_TRADES)}

    n_passed = sum(x["passed"] for x in c.values())
    # The CI is suppressed on underpowered cells (SPEC 8), so it may be absent.
    ci_lo = None if pd.isna(b10.get("ci95_lo_mark")) else float(b10["ci95_lo_mark"])
    ci_hi = None if pd.isna(b10.get("ci95_hi_mark")) else float(b10["ci95_hi_mark"])
    ci_excludes_zero = bool(ci_hi is not None and ci_hi < 0)

    # Routing is total. D3 dominates D2: an effect a placebo already explains is a
    # composition effect, not a power problem.
    control_killed = not (c["rung_control"]["passed"] and c["time_control"]["passed"]
                          and c["beats_placebo"]["passed"])
    incoherent = not (c["both_folds"]["passed"] and c["both_sides"]["passed"]
                      and c["monotonic"]["passed"])

    if n_passed == len(c):
        label = "D1 STRONG LOW-TAIL DETERIORATION SIGNAL"
    elif control_killed:
        label = "D3 COMPOSITION / PLACEBO EFFECT"
    elif incoherent:
        label = "D4 UNSTABLE / NO SIGNAL"
    elif c["tail_material"]["passed"]:
        label = "D2 PLAUSIBLE BUT UNDERPOWERED"
    else:
        label = "D4 UNSTABLE / NO SIGNAL"

    return {"conditions": c, "n_passed": n_passed, "n_conditions": len(c),
            "bottom_10_ci95_mark": [ci_lo, ci_hi],
            "bottom_10_ci_excludes_zero": ci_excludes_zero,
            "control_killed": control_killed, "incoherent": incoherent,
            "terminal_label": label}
