"""Every reported table. Aggregation only -- no path is recomputed here.

The one thing in this module that is not bookkeeping is `overlap()`. A SUCCESS
transition's adverse-excursion window ends at the target; a FAIL transition's runs
to the terminal, and is a median 240-330 s longer. A longer window mechanically
contains a larger maximum, so an AUC computed on the raw windows measures trade
duration and calls it separation. That is a defect this repository has already
been burned by, so three numbers are produced and the raw one is never quoted
alone:

    auc_raw_DURATION_CONFOUNDED  the naive comparison, named so it cannot be
                                 mistaken for evidence
    auc_horizon_matched          FAIL windows truncated to the matched SUCCESS
                                 time-to-target, by decile. THE PRIMARY NUMBER
    auc_frontier                 the separation a STOP can actually exploit,
                                 read off the Phase 5 survival curves, which
                                 evaluate both classes over their whole paths
                                 and are immune to the confound
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl

from studies.post_confirm_profit_ratchet.implementation.rungs import (
    ARCHITECTURES, BASIS_ENTRY, BASIS_POST, HORIZONS_S, RUNGS, RUNNER_TIERS, SEED,
    STEPS,
    STOP_DISTANCES, tag,
)

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "studies/post_confirm_profit_ratchet/results"
ARMED = ROOT / "studies/armed_fade_score_path_progression/results/armed_regime_score_paths.parquet"

N_ENTRIES = 8950
N_CONFIRMED = 4705
POOL_PER_ENTRY = 0.8980826455229006
BOOT = 1000
MIN_N = 20                      # below this a quantile is emitted as null


def _write(df: pl.DataFrame, name: str, csv: bool = True) -> None:
    df.write_parquet(OUT / f"{name}.parquet")
    if csv:
        df.write_csv(OUT / f"{name}.csv")
    print(f"  {name}: {df.height:,} rows", flush=True)


def slices(d: pl.DataFrame) -> list[tuple[str, str, pl.DataFrame]]:
    out = [("POOLED", "ALL", d)]
    out += [("SIDE", s, d.filter(pl.col("side") == s)) for s in ("LONG", "SHORT")]
    out += [("YEAR", str(y), d.filter(pl.col("entry_year") == y))
            for y in range(2021, 2026)]
    if "stratum" in d.columns:
        out += [("STRATUM", s, d.filter(pl.col("stratum") == s))
                for s in ("ARM_FRESH", "ARM_AT_CONFIRM")]
    return out


def qstats(g: pl.DataFrame, col: str) -> dict:
    """Mean and the SPEC-mandated percentile ladder. Null below MIN_N, never
    interpolated across a slice boundary."""
    pcts = (25, 50, 75, 80, 85, 90, 95, 99)
    v = g[col].drop_nulls()
    if v.len() == 0:
        return {"n": 0, "mean": None, **{f"p{p}": None for p in pcts}}
    small = v.len() < MIN_N
    return {"n": v.len(), "mean": float(v.mean()),
            **{f"p{p}": (None if small else float(v.quantile(p / 100)))
               for p in pcts}}


# ------------------------------------------------------------------ phase 0

def reconciliation(td: pl.DataFrame, xd: pl.DataFrame) -> pl.DataFrame:
    from studies.post_confirm_profit_ratchet.implementation.build import (
        ACCEPTED_LADDER,
    )
    armed = pl.read_parquet(ARMED).filter(pl.col("valid"))
    pre = armed.filter(pl.col("terminal_label_full") == "STOPPED_BEFORE_CONFIRM")
    n = armed.height
    pool = float(td.filter(pl.col("nat_kind") == "OPPOSING_FLIP")
                 ["nat_giveback_atr"].sum()) / n
    base = (float(td["baseline_net_atr"].sum())
            + float(pre["full_net_atr"].fill_null(0.0).sum())) / n
    rows = [("original_top10_entries", n, 8950, 0.0),
            ("confirmed", N_CONFIRMED, 4705, 0.0),
            ("stopped_before_confirm", pre.height, 4245, 0.0),
            ("measurable_confirmed_in_panel", td.height, 4656, 0.0),
            ("non_measurable_confirmed", N_CONFIRMED - td.height, 49, 0.0),
            ("giveback_pool_per_entry", pool, 0.89808, 0.005),
            ("baseline_net_per_entry", base, -0.07653, 0.005)]
    lad = (xd.filter((pl.col("basis") == BASIS_ENTRY) & (pl.col("step_atr") == 0.50))
           .group_by("rung_atr").agg(pl.col("lineage_next_reached").mean().alias("p")))
    for r in lad.sort("rung_atr").iter_rows(named=True):
        X = float(r["rung_atr"])
        rows.append((f"p_next_050_from_entry_rung_{tag(X)}", float(r["p"]),
                     ACCEPTED_LADDER[X], 0.002))
    return pl.DataFrame([{"quantity": q, "observed": float(o), "accepted": float(a),
                          "delta": float(o) - float(a), "tolerance": t,
                          "passed": abs(float(o) - float(a)) <= t}
                         for q, o, a, t in rows])


# ------------------------------------------------------------------ phase 1

def rung_achievement(ed: pl.DataFrame, n_meas: int) -> pl.DataFrame:
    rows = []
    for basis in (BASIS_POST, BASIS_ENTRY):
        b = ed.filter(pl.col("basis") == basis)
        for kind, name, sub in slices(b):
            for X in RUNGS:
                g = sub.filter(pl.col("rung_atr") == X)
                den = sub["regime_id"].n_unique() or 1
                rows.append({
                    "basis": basis, "slice_kind": kind, "slice": name,
                    "rung_atr": X, "n_achieving": g.height,
                    "empty_cell": g.height == 0,
                    "pct_of_measurable_confirmed": 100.0 * g.height / n_meas,
                    "pct_of_original_8950": 100.0 * g.height / N_ENTRIES,
                    "pct_of_slice_trades": 100.0 * g.height / den,
                    "pct_arm_fresh": (float((g["stratum"] == "ARM_FRESH").mean() * 100)
                                      if g.height else None),
                    "pct_stop_live_reachable": (float(g["stop_live_reachable"].mean() * 100)
                                                if g.height else None),
                    "median_overshoot_atr": (float(g["rung_overshoot_atr"].median())
                                             if g.height else None),
                    "median_secs_confirm_to_rung": (float(g["secs_confirm_to_rung"].median())
                                                    if g.height else None),
                })
    return pl.DataFrame(rows)


# ------------------------------------------------------------------ phase 2

def success_mae(xd: pl.DataFrame) -> pl.DataFrame:
    p = xd.filter(pl.col("basis") == BASIS_POST)
    rows = []
    for step in STEPS:
        s = p.filter((pl.col("step_atr") == step) & (pl.col("outcome") == "SUCCESS"))
        for kind, name, sub in slices(s):
            for X in RUNGS:
                g = sub.filter(pl.col("rung_atr") == X)
                for col, label in (("mae_from_hwm_atr", "MAE_FROM_HIGH_WATER"),
                                   ("retrace_below_rung_atr", "RETRACE_BELOW_RUNG"),
                                   ("mae_from_hwm_optimistic_atr",
                                    "MAE_FROM_HIGH_WATER_OPTIMISTIC"),
                                   ("secs_to_target", "SECS_TO_TARGET")):
                    rows.append({"step_atr": step, "slice_kind": kind, "slice": name,
                                 "rung_atr": X, "measure": label,
                                 "n_unique_trades": g["regime_id"].n_unique(),
                                 **qstats(g, col)})
    return pl.DataFrame(rows)


# ------------------------------------------------------------------ phase 3

FAIL_COLS = ("max_additional_mfe_after_rung_atr", "mae_from_hwm_to_terminal_atr",
             "retrace_below_rung_to_terminal_atr", "giveback_hwm_to_terminal_atr",
             "secs_rung_to_terminal", "unc_terminal_return_from_rung_atr")


def failure_geometry(xd: pl.DataFrame) -> pl.DataFrame:
    p = xd.filter((pl.col("basis") == BASIS_POST) & (pl.col("step_atr") == 0.50))
    rows = []
    for outcome in ("FAIL", "SUCCESS"):
        s = p.filter(pl.col("outcome") == outcome)
        for kind, name, sub in slices(s):
            for X in RUNGS:
                g = sub.filter(pl.col("rung_atr") == X)
                base = {"population": outcome, "slice_kind": kind, "slice": name,
                        "rung_atr": X, "n": g.height,
                        "n_unique_trades": g["regime_id"].n_unique(),
                        "pct_another_favorable_extreme": (
                            float(g["another_favorable_extreme_after_rung"].mean() * 100)
                            if g.height else None),
                        "pct_terminal_session_close": (
                            float((g["unc_kind"] == "SESSION").mean() * 100)
                            if g.height else None),
                        "pct_terminal_opposing_flip": (
                            float((g["unc_kind"] == "OPPOSING_FLIP").mean() * 100)
                            if g.height else None),
                        "median_nat_terminal_return_atr": (
                            float(g["nat_terminal_return_atr"].median())
                            if g.height else None),
                        "pct_stopped_by_1atr_stop": (
                            float((g["nat_kind"] == "STOP").mean() * 100)
                            if g.height else None)}
                for c in FAIL_COLS:
                    q = qstats(g, c)
                    base[f"{c}__mean"] = q["mean"]
                    base[f"{c}__p50"] = q["p50"]
                    base[f"{c}__p75"] = q["p75"]
                    base[f"{c}__p90"] = q["p90"]
                rows.append(base)
    return pl.DataFrame(rows)


# ------------------------------------------------------------------ phase 4

def _auc(pos: np.ndarray, neg: np.ndarray) -> float | None:
    """Mann-Whitney AUC: P(a FAIL has larger adverse excursion than a SUCCESS)."""
    if pos.size < MIN_N or neg.size < MIN_N:
        return None
    a = np.concatenate([pos, neg])
    r = np.empty(a.size, dtype=float)
    order = np.argsort(a, kind="mergesort")
    sa = a[order]
    i = 0
    while i < sa.size:                      # average ranks over ties
        j = i
        while j + 1 < sa.size and sa[j + 1] == sa[i]:
            j += 1
        r[order[i:j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return float((r[:pos.size].sum() - pos.size * (pos.size + 1) / 2.0)
                 / (pos.size * neg.size))


def overlap(xd: pl.DataFrame, frontier: pl.DataFrame) -> pl.DataFrame:
    p = xd.filter(pl.col("basis") == BASIS_POST)
    rows = []
    for step in STEPS:
        s = p.filter(pl.col("step_atr") == step)
        for kind, name, sub in slices(s):
            for X in RUNGS:
                g = sub.filter(pl.col("rung_atr") == X)
                suc = g.filter(pl.col("outcome") == "SUCCESS")
                fail = g.filter(pl.col("outcome") == "FAIL")
                if suc.height == 0 or fail.height == 0:
                    continue
                sv = suc["mae_from_hwm_atr"].drop_nulls().to_numpy()
                # RAW: the FAIL window runs to the terminal, the SUCCESS window
                # stops at the target. Duration-confounded by construction.
                fv = fail["mae_from_hwm_to_terminal_atr"].drop_nulls().to_numpy()

                # HORIZON-MATCHED: BOTH classes measured over the SAME elapsed
                # window after their own rung, at each fixed horizon. This is the
                # only comparison that is not answering "which class lived
                # longer". Reported at every horizon; the one nearest the SUCCESS
                # cohort's median time-to-target is the headline.
                tau = float(suc["secs_to_target"].median())
                h_aucs = {}
                for H in HORIZONS_S:
                    c = f"mae_from_hwm_h{H}s_atr"
                    h_aucs[f"auc_matched_h{H}s"] = _auc(
                        fail[c].drop_nulls().to_numpy(),
                        suc[c].drop_nulls().to_numpy())
                near = min(HORIZONS_S, key=lambda H: abs(H - tau))
                fmv = fail[f"mae_from_hwm_h{near}s_atr"].drop_nulls().to_numpy()
                smv = suc[f"mae_from_hwm_h{near}s_atr"].drop_nulls().to_numpy()

                # FRONTIER: the separation a stop can exploit. Read off the
                # survival curves, which score both classes over whole paths.
                fr = frontier.filter((pl.col("rung_atr") == X)
                                     & (pl.col("step_atr") == step)
                                     & (pl.col("architecture") == "HWM")
                                     & (pl.col("slice_kind") == kind)
                                     & (pl.col("slice") == name))
                gap = None
                if fr.height:
                    gap = float((fr["pct_fail_stopped"] / 100.0
                                 - (1 - fr["pct_success_surviving"] / 100.0)).max())
                rows.append({
                    "step_atr": step, "slice_kind": kind, "slice": name,
                    "rung_atr": X, "n_success": suc.height, "n_fail": fail.height,
                    "median_success_secs_to_target": tau,
                    "matched_horizon_s": float(near),
                    "success_median": float(np.median(sv)),
                    "fail_median": float(np.median(fv)),
                    "median_diff": float(np.median(fv) - np.median(sv)),
                    "p75_diff": float(np.quantile(fv, .75) - np.quantile(sv, .75)),
                    "p90_diff": float(np.quantile(fv, .90) - np.quantile(sv, .90)),
                    "auc_raw_DURATION_CONFOUNDED": _auc(fv, sv),
                    "auc_horizon_matched": _auc(fmv, smv) if fmv.size else None,
                    "matched_success_median": (float(np.median(smv))
                                               if smv.size else None),
                    "matched_fail_median": (float(np.median(fmv))
                                            if fmv.size else None),
                    **h_aucs,
                    "auc_frontier_max_gap": gap,
                })
    return pl.DataFrame(rows)


# ------------------------------------------------------------------ phase 5

def survival_frontier(xd: pl.DataFrame, cd: pl.DataFrame) -> pl.DataFrame:
    """Did the stop survive to the target, and what did it do to the failures?

    Survival is read from the SIMULATED exit index, not from the Phase 2
    statistic, so the two are independent computations of the same quantity and
    can be cross-checked (SPEC gate 7). The adverse convention is `e <= t` counts
    as stopped: a trigger on the target bar itself is a same-bar collision and
    intra-second ordering is unknowable from OHLC.
    """
    tr = (xd.filter(pl.col("basis") == BASIS_POST)
          .select("regime_id", "entry_year", "side", "rung_atr", "step_atr",
                  "outcome", "target_idx", "mae_from_hwm_atr",
                  "retrace_below_rung_atr", "mae_from_hwm_to_terminal_atr",
                  "giveback_hwm_to_terminal_atr", "secs_rung_to_terminal"))
    ec = cd.filter(pl.col("achieved")).select(
        "regime_id", "rung_atr", "stop_d", "architecture", "participated",
        "policy_exit_idx", "policy_exit_kind", "policy_return_atr",
        "baseline_return_atr", "delta_atr", "secs_exit_before_baseline",
        "unc_exit_idx", "unc_stopped")
    j = tr.join(ec, on=["regime_id", "rung_atr"], how="inner")
    # SURVIVAL AND STOP RATE READ THE UNCONSTRAINED TRIGGER (SPEC D1).
    # Reading `policy_exit_idx` here would silently count every rung reached
    # after the accepted 1 ATR stop had already closed the trade as a stop that
    # "survived" -- it never armed. That is the stop-live track leaking into a
    # descriptive phase, it biases survival upward by up to 2.5 pp, and it feeds
    # decision-gate conditions 1 and 2. The ECONOMIC columns below stay on the
    # stop-live track, which is where they belong.
    j = j.with_columns(
        stopped_before_target=(pl.col("unc_stopped")
                               & (pl.col("unc_exit_idx") <= pl.col("target_idx"))
                               & (pl.col("target_idx") >= 0)),
        stopped_at_all=pl.col("unc_stopped"),
        stopped_at_all_stop_live=(pl.col("policy_exit_kind") == "RATCHET"))
    rows = []
    for kind, name, sub in slices(j):
        for step in STEPS:
            s = sub.filter(pl.col("step_atr") == step)
            for X in RUNGS:
                for D in STOP_DISTANCES:
                    for arch in ARCHITECTURES:
                        g = s.filter((pl.col("rung_atr") == X)
                                     & (pl.col("stop_d") == D)
                                     & (pl.col("architecture") == arch))
                        suc = g.filter(pl.col("outcome") == "SUCCESS")
                        fail = g.filter(pl.col("outcome") == "FAIL")
                        # economic columns come from the STOP-LIVE track
                        st = fail.filter(pl.col("stopped_at_all_stop_live"))
                        col = ("mae_from_hwm_atr" if arch == "HWM"
                               else "retrace_below_rung_atr")
                        cdf = (float((suc[col] < D).mean() * 100)
                               if suc.height else None)
                        rows.append({
                            "slice_kind": kind, "slice": name, "rung_atr": X,
                            "stop_d": D, "architecture": arch, "step_atr": step,
                            "n_success": suc.height, "n_fail": fail.height,
                            "empty_cell": g.height == 0,
                            "pct_success_surviving": (
                                float((~suc["stopped_before_target"]).mean() * 100)
                                if suc.height else None),
                            "pct_success_surviving_cdf_check": cdf,
                            "pct_fail_stopped": (float(fail["stopped_at_all"].mean() * 100)
                                                 if fail.height else None),
                            "pct_fail_stopped_stop_live": (
                                float(fail["stopped_at_all_stop_live"].mean() * 100)
                                if fail.height else None),
                            "giveback_prevented_mean": (float(st["delta_atr"].mean())
                                                        if st.height else None),
                            "giveback_prevented_median": (float(st["delta_atr"].median())
                                                          if st.height else None),
                            "realized_return_if_stopped_mean": (
                                float(st["policy_return_atr"].mean()) if st.height else None),
                            "realized_return_if_stopped_median": (
                                float(st["policy_return_atr"].median()) if st.height else None),
                            "secs_stop_before_baseline_terminal_median": (
                                float(st["secs_exit_before_baseline"].median())
                                if st.height else None),
                        })
    return pl.DataFrame(rows)


def preservation_frontier(fr: pl.DataFrame) -> pl.DataFrame:
    """Smallest grid D reaching 85/90/95% success preservation, and its cost."""
    p = fr.filter((pl.col("slice_kind") == "POOLED") & (pl.col("n_success") > 0))
    rows = []
    for step in STEPS:
        for X in RUNGS:
            for arch in ARCHITECTURES:
                g = (p.filter((pl.col("step_atr") == step) & (pl.col("rung_atr") == X)
                              & (pl.col("architecture") == arch))
                     .sort("stop_d"))
                row = {"step_atr": step, "rung_atr": X, "architecture": arch,
                       "max_survival_on_grid": float(g["pct_success_surviving"].max()),
                       "survival_at_widest_D": float(
                           g.filter(pl.col("stop_d") == max(STOP_DISTANCES))
                           ["pct_success_surviving"][0])}
                for target in (85.0, 90.0, 95.0):
                    hit = g.filter(pl.col("pct_success_surviving") >= target)
                    row[f"D_for_{int(target)}pct"] = (float(hit["stop_d"][0])
                                                      if hit.height else None)
                    row[f"fail_stop_rate_at_{int(target)}pct"] = (
                        float(hit["pct_fail_stopped"][0]) if hit.height else None)
                    row[f"giveback_prevented_at_{int(target)}pct"] = (
                        float(hit["giveback_prevented_mean"][0])
                        if hit.height and hit["giveback_prevented_mean"][0] is not None
                        else None)
                rows.append(row)
    return pl.DataFrame(rows)


# ---------------------------------------------------------------- phase 6/7

def ratchet_summary(cd: pl.DataFrame, pre_net: float) -> pl.DataFrame:
    """Economics per cell, per slice, with both causal placebos and a CI.

    The bootstrap resamples TRADES, not rows: a trade contributing to six rung
    populations must move as one unit or the interval is too tight by roughly the
    square root of the number of rungs it reached.
    """
    rng = np.random.default_rng(SEED)
    ids = cd["regime_id"].unique().sort()
    pos = {r: i for i, r in enumerate(ids.to_list())}
    n_tr = len(pos)
    boot_idx = rng.integers(0, n_tr, size=(BOOT, n_tr))

    rows = []
    for kind, name, sub in slices(cd):
        keep = set(sub["regime_id"].unique().to_list())
        mask = np.zeros(n_tr, dtype=bool)
        for r in keep:
            mask[pos[r]] = True
        for X in RUNGS:
            for D in STOP_DISTANCES:
                for arch in ARCHITECTURES:
                    g = sub.filter((pl.col("rung_atr") == X) & (pl.col("stop_d") == D)
                                   & (pl.col("architecture") == arch))
                    ach = g.filter(pl.col("achieved"))
                    part = g.filter(pl.col("participated"))
                    # per-trade delta vector over the FULL trade universe: a
                    # non-achiever contributes 0, which is what keeps the 8,950
                    # denominator honest.
                    vec = np.zeros(n_tr)
                    vb = np.zeros(n_tr)
                    vu = np.zeros(n_tr)
                    vq = np.zeros(n_tr)
                    pol = np.zeros(n_tr)
                    for r in g.select("regime_id", "delta_atr", "d_blind", "d_uncond",
                                      "d_uniform", "policy_return_atr", "cost_atr"
                                      ).iter_rows():
                        i = pos[r[0]]
                        vec[i], vb[i], vu[i], vq[i] = r[1], r[2], r[3], r[4]
                        pol[i] = r[5] - r[6]
                    sel = vec * mask
                    d_entry = sel.sum() / N_ENTRIES
                    b_entry = (vb * mask).sum() / N_ENTRIES
                    u_entry = (vu * mask).sum() / N_ENTRIES
                    q_entry = (vq * mask).sum() / N_ENTRIES
                    draws = sel[boot_idx].sum(axis=1) / N_ENTRIES
                    rows.append({
                        "slice_kind": kind, "slice": name, "rung_atr": X,
                        "stop_d": D, "architecture": arch,
                        "n_achieving": ach.height,
                        "n_participating": part.height,
                        "empty_cell": ach.height == 0,
                        "pct_stop_live_reachable": (
                            float(ach["stop_live_reachable"].mean() * 100)
                            if ach.height else None),
                        "delta_per_achieving_trade": (float(ach["delta_atr"].mean())
                                                      if ach.height else None),
                        "delta_per_confirmed_trade": float(sel.sum()) / N_CONFIRMED,
                        "delta_per_original_entry": float(d_entry),
                        "pct_giveback_pool_recovered": 100.0 * d_entry / POOL_PER_ENTRY,
                        # Absolute net includes the 4,245 trades stopped before
                        # they ever confirmed. A cell can improve the delta and
                        # still leave the strategy net-negative; this column is
                        # mandatory so that fact can never be hidden (SPEC 8).
                        "absolute_net_per_original_entry": float(
                            ((pol * mask).sum() + pre_net) / N_ENTRIES)
                        if kind == "POOLED" else None,
                        "delta_P_BLIND": float(b_entry),
                        "delta_P_UNCOND": float(u_entry),
                        "delta_P_UNIFORM_FUTURE_INFO": float(q_entry),
                        "edge_over_blind": float(d_entry - b_entry),
                        "edge_over_uncond": float(d_entry - u_entry),
                        "beats_blind": bool(d_entry > b_entry),
                        "beats_uncond": bool(d_entry > u_entry),
                        "ci_lo": float(np.quantile(draws, 0.025)),
                        "ci_hi": float(np.quantile(draws, 0.975)),
                    })
    return pl.DataFrame(rows)


def runner_destruction(cd: pl.DataFrame) -> pl.DataFrame:
    rows = []
    for kind, name, sub in slices(cd.filter(pl.col("achieved"))):
        for X in RUNGS:
            for D in STOP_DISTANCES:
                for arch in ARCHITECTURES:
                    g = sub.filter((pl.col("rung_atr") == X) & (pl.col("stop_d") == D)
                                   & (pl.col("architecture") == arch))
                    for T in RUNNER_TIERS:
                        col = f"runner_survived_{tag(T)}"
                        m = g.filter(pl.col(col).is_not_null())
                        if m.height == 0:
                            rows.append({"slice_kind": kind, "slice": name,
                                         "rung_atr": X, "stop_d": D,
                                         "architecture": arch, "tier_atr": T,
                                         "n_tier": 0, "empty_cell": True})
                            continue
                        cut = m.filter(pl.col("delta_atr") < 0)
                        bs = float(m["baseline_return_atr"].sum())
                        rows.append({
                            "slice_kind": kind, "slice": name, "rung_atr": X,
                            "stop_d": D, "architecture": arch, "tier_atr": T,
                            "n_tier": m.height, "empty_cell": False,
                            "runner_survival_pct": float(m[col].mean() * 100),
                            "runner_cut_pct": float(cut.height / m.height * 100),
                            "runner_delta_mean_atr": float(m["delta_atr"].mean()),
                            "runner_pnl_retained": (float(m["policy_return_atr"].sum() / bs)
                                                    if abs(bs) > 1e-9 else None),
                            "runner_baseline_mean_atr": float(m["baseline_return_atr"].mean()),
                            "runner_policy_mean_atr": float(m["policy_return_atr"].mean()),
                        })
    return pl.DataFrame(rows)


def static_vs_ratchet(rs: pl.DataFrame) -> pl.DataFrame:
    p = rs.filter(pl.col("slice_kind") == "POOLED")
    wide = (p.select("rung_atr", "stop_d", "architecture", "delta_per_original_entry",
                     "pct_giveback_pool_recovered", "edge_over_blind")
            .pivot(on="architecture", index=["rung_atr", "stop_d"],
                   values=["delta_per_original_entry", "pct_giveback_pool_recovered",
                           "edge_over_blind"]))
    return wide.sort("rung_atr", "stop_d")


# ------------------------------------------------------------------ master

def master(rs: pl.DataFrame, fr: pl.DataFrame, rd: pl.DataFrame) -> pl.DataFrame:
    p = rs.filter(pl.col("slice_kind") == "POOLED")
    f = fr.filter((pl.col("slice_kind") == "POOLED") & (pl.col("step_atr") == 0.50))
    r3 = rd.filter((pl.col("slice_kind") == "POOLED") & (pl.col("tier_atr") == 3.0))
    yr = rs.filter(pl.col("slice_kind") == "YEAR")
    sd = rs.filter(pl.col("slice_kind") == "SIDE")

    yrs = (yr.group_by("rung_atr", "stop_d", "architecture")
           .agg((pl.col("delta_per_original_entry") >= 0).sum().alias("years_positive_of_5")))
    sds = (sd.group_by("rung_atr", "stop_d", "architecture")
           .agg((pl.col("delta_per_original_entry") > 0).all().alias("both_sides_positive"),
                pl.col("delta_per_original_entry").min().alias("worst_side_delta")))

    m = (p.select("rung_atr", "stop_d", "architecture", "n_achieving",
                  # explicit zero-count flag: SPEC 7 requires an empty cell to be
                  # RETAINED and flagged, never dropped. Carried as its own
                  # column rather than left implicit in n_achieving == 0, so the
                  # completeness contract is checkable without inference.
                  "empty_cell",
                  "delta_per_original_entry", "pct_giveback_pool_recovered",
                  "absolute_net_per_original_entry", "edge_over_blind",
                  "edge_over_uncond", "ci_lo", "ci_hi")
         .join(f.select("rung_atr", "stop_d", "architecture",
                        pl.col("pct_success_surviving").alias("success_050_survival"),
                        pl.col("pct_fail_stopped").alias("failure_stop_rate"),
                        pl.col("giveback_prevented_mean").alias("giveback_prevented")),
               on=["rung_atr", "stop_d", "architecture"], how="left")
         .join(r3.select("rung_atr", "stop_d", "architecture",
                         pl.col("runner_survival_pct").alias("runner_survival_3atr"),
                         pl.col("runner_pnl_retained").alias("runner_pnl_retained_3atr")),
               on=["rung_atr", "stop_d", "architecture"], how="left")
         .join(yrs, on=["rung_atr", "stop_d", "architecture"], how="left")
         .join(sds, on=["rung_atr", "stop_d", "architecture"], how="left"))
    # Sorted CONCEPTUALLY -- by rung, then stop distance, then architecture.
    # Never by performance: ranking 126 cells on the sample that produced them is
    # selection, and the study is explicitly forbidden from doing it.
    return m.sort("rung_atr", "stop_d", "architecture")


def stability(rs: pl.DataFrame) -> pl.DataFrame:
    return (rs.filter(pl.col("slice_kind").is_in(["YEAR", "SIDE"]))
            .select("slice_kind", "slice", "rung_atr", "stop_d", "architecture",
                    "n_achieving", "delta_per_original_entry",
                    "delta_per_achieving_trade", "pct_giveback_pool_recovered",
                    "edge_over_blind", "edge_over_uncond")
            .sort("rung_atr", "stop_d", "architecture", "slice_kind", "slice"))


# ------------------------------------------------------------------- gate

def decision_gate(m: pl.DataFrame, rd: pl.DataFrame, rs: pl.DataFrame) -> pl.DataFrame:
    unif = (rs.filter(pl.col("slice_kind") == "POOLED")
            .select("rung_atr", "stop_d", "architecture", "delta_P_UNIFORM_FUTURE_INFO",
                    "pct_stop_live_reachable"))
    m = m.join(unif, on=["rung_atr", "stop_d", "architecture"], how="left")
    rows = []
    for c in m.iter_rows(named=True):
        cell = f"rung_{tag(c['rung_atr'])}__D_{tag(c['stop_d'])}__{c['architecture']}"
        conds = [
            ("1_PRESERVATION", c["success_050_survival"], ">= 90",
             (c["success_050_survival"] or 0) >= 90.0),
            ("2_GIVEBACK", c["giveback_prevented"], ">= 0.50 and fail_stop >= 25%",
             (c["giveback_prevented"] or -9) >= 0.50
             and (c["failure_stop_rate"] or 0) >= 25.0),
            ("3_ECONOMICS", c["delta_per_original_entry"], "> 0, beats both placebos, CI_lo > 0",
             c["delta_per_original_entry"] > 0 and (c["edge_over_blind"] or -9) > 0
             and (c["edge_over_uncond"] or -9) > 0 and c["ci_lo"] > 0),
            ("4_YEAR", c["years_positive_of_5"], ">= 4 of 5",
             (c["years_positive_of_5"] or 0) >= 4),
            ("5_DIRECTION", c["worst_side_delta"], "both > 0, worst >= -0.02",
             bool(c["both_sides_positive"]) and (c["worst_side_delta"] or -9) >= -0.02),
            ("6_TAIL", c["runner_survival_3atr"], ">= 80% and pnl_retained >= 0.90",
             (c["runner_survival_3atr"] or 0) >= 80.0
             and (c["runner_pnl_retained_3atr"] or 0) >= 0.90),
            ("7_NOT_ARTIFACT", c["pct_stop_live_reachable"],
             "beats P_UNIFORM or it is <=0; >= 60% stop-live reachable",
             (c["delta_per_original_entry"] > (c["delta_P_UNIFORM_FUTURE_INFO"] or 0)
              or (c["delta_P_UNIFORM_FUTURE_INFO"] or 0) <= 0)
             and (c["pct_stop_live_reachable"] or 0) >= 60.0),
        ]
        for nm, val, thr, ok in conds:
            rows.append({"cell": cell, "rung_atr": c["rung_atr"],
                         "stop_d": c["stop_d"], "architecture": c["architecture"],
                         "condition": nm, "value": (float(val) if val is not None else None),
                         "threshold": thr, "passed": bool(ok)})
    return pl.DataFrame(rows)


def main() -> None:
    td = pl.read_parquet(OUT / "trade_panel.parquet")
    ed = pl.read_parquet(OUT / "rung_events.parquet")
    xd = pl.read_parquet(OUT / "rung_transitions.parquet")
    cd = pl.read_parquet(OUT / "ratchet_economics.parquet")
    armed = pl.read_parquet(ARMED).filter(pl.col("valid"))
    pre_net = float(armed.filter(pl.col("terminal_label_full") == "STOPPED_BEFORE_CONFIRM")
                    ["full_net_atr"].fill_null(0.0).sum())

    _write(reconciliation(td, xd), "population_reconciliation")
    _write(rung_achievement(ed, td.height), "rung_achievement")
    _write(success_mae(xd), "success_mae_distribution")
    _write(failure_geometry(xd), "failure_geometry")
    fr = survival_frontier(xd, cd)
    _write(fr, "stop_survival_frontier")
    _write(preservation_frontier(fr), "preservation_frontier")
    _write(overlap(xd, fr), "overlap")
    rs = ratchet_summary(cd, pre_net)
    _write(rs, "ratchet_summary")
    rd = runner_destruction(cd)
    _write(rd, "runner_destruction")
    _write(static_vs_ratchet(rs), "static_vs_ratchet")
    m = master(rs, fr, rd)
    _write(m, "master_tradeoff")
    _write(stability(rs), "stability")
    g = decision_gate(m, rd, rs)
    _write(g, "decision_gate")

    opened = (g.group_by("cell").agg(pl.col("passed").all().alias("all_passed"))
              .filter(pl.col("all_passed")))
    (OUT / "gate_verdict.json").write_text(json.dumps({
        "gate_open": opened.height > 0,
        "n_cells_evaluated": m.height,
        "n_cells_passing_all_7": opened.height,
        "passing_cells": opened["cell"].to_list(),
        "condition_pass_counts": g.group_by("condition")
        .agg(pl.col("passed").sum().alias("n_cells_passing")).sort("condition").to_dicts(),
    }, indent=2, default=str))
    print(f"\n  gate_open = {opened.height > 0}  "
          f"({opened.height}/{m.height} cells pass all 7)")


if __name__ == "__main__":
    main()
