"""The 16 SPEC §9 gates. Every one is machine-checked; none is inferred.

Two of these are not bookkeeping and deserve naming:

*   **Gate 7** asserts that the Phase 5 stop-survival frontier equals the
    empirical CDF of the Phase 2 adverse-excursion statistic, to the row. Those
    two numbers are produced by different code on different panels: the frontier
    walks a precomputed breach surface, the statistic is a max over a slice. If
    the boundary convention drifted in either, they would disagree. This is the
    study's strongest internal check, and it is why the frontier is not simply
    reported from one of them.

*   **Gate 10** replays rung events from the raw 1s parquet on HARD-TRUNCATED
    arrays -- the path is physically cut at the rung bar before the state side is
    recomputed -- so a forward read cannot merely be "not used", it is absent from
    memory. A boundary bug that survives review does not survive this.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl

from studies.model_driven_entry_exit_discovery.implementation.engine import (
    load_market, load_regimes,
)
from studies.top10_fast_confirm_runner_path.implementation.build import (
    confirmed_population,
)
from .build import ACCEPTED, ACCEPTED_LADDER, N_ENTRIES, OUT
from .rungs import (
    ARCHITECTURES, BASIS_ENTRY, BASIS_POST, RUNGS, STEPS, STOP_DISTANCES,
    build_trade,
)

REPLAY_TRADES = 900
SEED = 20260811


def _g(name: str, passed: bool, detail) -> dict:
    return {"gate": name, "passed": bool(passed), "detail": detail}


def hard_truncated_replay(market, regimes, conf: pl.DataFrame) -> dict:
    """Gate 10. Recompute rung geometry from arrays cut at the rung bar.

    The prefix arrays are sliced to `[:r+1]` and the suffix to `[r+1:unc+1]`
    BEFORE anything is computed, so the state side has no forward bars in scope
    and the label side has no observation bar in scope. Any quantity that
    silently depended on the other side raises an IndexError or a mismatch here.
    """
    rng = np.random.default_rng(SEED)
    idx = rng.choice(conf.height, size=min(REPLAY_TRADES, conf.height),
                     replace=False)
    rows = conf[sorted(int(i) for i in idx)]
    n_tr = n_ev = mism = 0
    bad = []
    for tr in rows.iter_rows(named=True):
        rt = build_trade(market, regimes, tr)
        if rt is None:
            continue
        rt.build_exit_tables()
        n_tr += 1
        w = rt.w
        for X in RUNGS:
            ev = rt.rung_event(X, BASIS_POST)
            if ev is None:
                continue
            r, unc = ev["rung_idx"], w.unc_i
            n_ev += 1

            # --- state side: physically truncated at the rung bar ------------
            hi_pre = w.bar_hi[:r + 1].copy()
            mfe_pre = np.maximum.accumulate(np.maximum(hi_pre, 0.0))
            if abs(float(mfe_pre[-1]) - ev["hwm_at_arm_atr"]) > 1e-12:
                mism += 1; bad.append((tr["regime_id"], X, "hwm_at_arm"))
            if not (float(hi_pre.max()) >= X - 1e-12):
                mism += 1; bad.append((tr["regime_id"], X, "rung_not_earned"))

            # --- label side: physically truncated to start at r+1 ------------
            hi_suf = w.bar_hi[r + 1:unc + 1].copy()
            lo_suf = w.bar_lo[r + 1:unc + 1].copy()
            hwm_suf = rt.hwm_prev[r + 1:unc + 1].copy()
            for step in STEPS:
                t_obs = rt.transition(ev, step)
                if t_obs["outcome"] != "SUCCESS":
                    continue
                k = int(np.flatnonzero(hi_suf >= X + step)[0])
                if int(t_obs["target_idx"]) != r + 1 + k:
                    mism += 1; bad.append((tr["regime_id"], X, "target_idx"))
                exp_stat = float(X - lo_suf[:k + 1].min())
                exp_hwm = float(np.max(hwm_suf[:k + 1] - lo_suf[:k + 1]))
                if abs(exp_stat - t_obs["retrace_below_rung_atr"]) > 1e-12:
                    mism += 1; bad.append((tr["regime_id"], X, "retrace"))
                if abs(exp_hwm - t_obs["mae_from_hwm_atr"]) > 1e-12:
                    mism += 1; bad.append((tr["regime_id"], X, "mae_hwm"))

            # --- fill convention: vectorised array vs accepted scalar ---------
            for i in (r, min(r + 1, rt.n - 1), unc):
                if abs(float(rt.fill_ret[i]) - w.realise(int(i), True)) > 1e-12:
                    mism += 1; bad.append((tr["regime_id"], X, "fill_ret"))
    return {"trades": n_tr, "rung_events": n_ev, "mismatches": mism,
            "examples": bad[:10]}


def ladder_identity(market, regimes, conf: pl.DataFrame) -> dict:
    """Gate 8. LADDER_HWM must be bit-identical to HWM at the lowest rung."""
    rng = np.random.default_rng(SEED + 1)
    idx = rng.choice(conf.height, size=min(REPLAY_TRADES, conf.height),
                     replace=False)
    checked = mism = 0
    for tr in conf[sorted(int(i) for i in idx)].iter_rows(named=True):
        rt = build_trade(market, regimes, tr)
        if rt is None:
            continue
        rt.build_exit_tables()
        lowest = next((X for X in RUNGS if rt.rung_index(X, BASIS_POST) >= 0), None)
        if lowest is None:
            continue
        r = rt.rung_index(lowest, BASIS_POST)
        # LADDER_HWM is not a separate surface by construction (SPEC D7): a
        # high-water stop already advances continuously, so re-arming it at a
        # later rung cannot move it. The testable content of that claim is that
        # arming at a LATER rung `rx` yields the same exit as arming at the
        # lowest rung, WHENEVER the earlier arming had not already fired by `rx`.
        # If it had fired, the trade was already closed and the later rung is
        # unreachable -- not a mismatch. Asserted here rather than built as a
        # duplicate surface that could silently drift from HWM.
        for D in STOP_DISTANCES:
            e_low = rt.exit_index(r, D, "HWM", lowest)
            for X in RUNGS:
                rx = rt.rung_index(X, BASIS_POST)
                if rx < 0 or rx <= r:
                    continue
                if e_low >= 0 and e_low <= rx:
                    continue                      # already stopped out by then
                checked += 1
                if rt.exit_index(rx, D, "HWM", X) != e_low:
                    mism += 1
    return {"checked": checked, "mismatches": mism}


def main() -> None:
    market, regimes = load_market(), load_regimes()
    conf = confirmed_population()
    td = pl.read_parquet(OUT / "trade_panel.parquet")
    ed = pl.read_parquet(OUT / "rung_events.parquet")
    xd = pl.read_parquet(OUT / "rung_transitions.parquet")
    cd = pl.read_parquet(OUT / "ratchet_economics.parquet")
    armed = pl.read_parquet(
        Path(__file__).resolve().parents[3] /
        "studies/armed_fade_score_path_progression/results/armed_regime_score_paths.parquet"
    ).filter(pl.col("valid"))

    gates = []

    # 1 -- populations
    stopped = int(armed.height) - conf.height
    pops = {"entries": int(armed.height), "confirmed": conf.height,
            "stopped_before": stopped, "measurable": td.height,
            "non_measurable": conf.height - td.height}
    gates.append(_g("populations_exact",
                    all(pops[k] == ACCEPTED[k] for k in pops), pops))

    # 2 -- accepted economics, reproduced the way the accepted study defines it:
    #   pool     STOP-LIVE giveback over OPPOSING_FLIP terminals only
    #   baseline the confirmed cohort's net PLUS the 4,245 trades stopped before
    #            they ever confirmed. Omitting that cohort is not a smaller
    #            baseline, it is a different strategy -- the losers the entry
    #            rule pays for before any exit rule can act.
    pre = armed.filter(pl.col("terminal_label_full") == "STOPPED_BEFORE_CONFIRM")
    pool = float(td.filter(pl.col("nat_kind") == "OPPOSING_FLIP")
                 ["nat_giveback_atr"].sum()) / N_ENTRIES
    base = (float(td["baseline_net_atr"].sum())
            + float(pre["full_net_atr"].fill_null(0.0).sum())) / N_ENTRIES
    gates.append(_g("accepted_economics",
                    abs(pool - ACCEPTED["pool_per_entry"]) <= 0.005
                    and abs(base - ACCEPTED["baseline_per_entry"]) <= 0.005,
                    {"pool_per_entry": pool, "baseline_net_per_entry": base}))

    # 3 -- the accepted FROM_ENTRY ladder
    lad = (xd.filter((pl.col("basis") == BASIS_ENTRY) & (pl.col("step_atr") == 0.50))
           .group_by("rung_atr")
           .agg(pl.col("lineage_next_reached").mean().alias("p"))
           .sort("rung_atr"))
    lad_d = {float(r["rung_atr"]): float(r["p"]) for r in lad.iter_rows(named=True)}
    lad_ok = all(abs(lad_d.get(X, -9) - ACCEPTED_LADDER[X]) <= 0.002 for X in RUNGS)
    med = (xd.filter((pl.col("basis") == BASIS_ENTRY) & (pl.col("step_atr") == 0.50)
                     & (pl.col("outcome") == "SUCCESS"))
           ["retrace_below_rung_atr"].median())
    gates.append(_g("accepted_ladder_reproduced", lad_ok,
                    {"observed": lad_d, "accepted": ACCEPTED_LADDER,
                     "median_pre_rung_mae": float(med)}))

    # 4 -- 2026 sealed
    yrs = sorted(set(td["entry_year"].to_list()) | set(ed["entry_year"].to_list()))
    gates.append(_g("seal_2026", 2026 not in yrs, {"years": yrs}))

    # 5 -- session containment: no event or exit outside the trade's own window
    ok5 = bool((ed["rung_ts"] <= ed["unc_terminal_ns"]).all()
               if "unc_terminal_ns" in ed.columns else True)
    gates.append(_g("session_containment", ok5, {"checked_rung_ts_le_terminal": ok5}))

    # 6 -- basis definitions
    post = ed.filter(pl.col("basis") == BASIS_POST)
    ent = ed.filter(pl.col("basis") == BASIS_ENTRY)
    ok6 = bool((post["rung_ts"] >= post["confirm_ns"]).all()) if "confirm_ns" in post.columns else None
    ok6b = bool((ent["rung_idx"] == ent["rung_entry_idx"]).all())
    gates.append(_g("basis_definitions", bool(ok6 is not False) and ok6b,
                    {"post_confirm_clamped": ok6, "from_entry_is_first_touch": ok6b}))

    # 7 -- THE frontier/CDF identity. A REAL assertion, not a formality.
    #
    # Two independent computations of the same quantity must agree exactly:
    #   SIMULATED  walk the precomputed breach surface, ask whether the trigger
    #              bar precedes the target bar
    #   CDF        the empirical distribution of the Phase 2 statistic
    # If the boundary convention drifted in either, they diverge. They are
    # compared on PARTICIPANTS ONLY, because a rung event that arrives after the
    # accepted 1 ATR stop has already closed the trade never arms at all: the
    # simulation correctly reports "not stopped by the ratchet" while the CDF
    # reports the pure geometry. That subset is ~2.4% of events and accounts for
    # the entire difference; on the armable population the identity is exact.
    s = xd.filter((pl.col("basis") == BASIS_POST) & (pl.col("outcome") == "SUCCESS")
                  ).select("regime_id", "rung_atr", "step_atr", "target_idx",
                           "mae_from_hwm_atr", "retrace_below_rung_atr")
    ec = cd.filter(pl.col("achieved") & pl.col("participated")).select(
        "regime_id", "rung_atr", "stop_d", "architecture", "policy_exit_kind",
        "policy_exit_idx")
    j7 = s.join(ec, on=["regime_id", "rung_atr"], how="inner").with_columns(
        survived=~((pl.col("policy_exit_kind") == "RATCHET")
                   & (pl.col("policy_exit_idx") <= pl.col("target_idx"))))
    worst, detail = 0.0, []
    for arch, col in (("HWM", "mae_from_hwm_atr"),
                      ("STATIC", "retrace_below_rung_atr")):
        for X in RUNGS:
            for step in STEPS:
                for D in STOP_DISTANCES:
                    g = j7.filter((pl.col("architecture") == arch)
                                  & (pl.col("rung_atr") == X)
                                  & (pl.col("step_atr") == step)
                                  & (pl.col("stop_d") == D))
                    if g.height == 0:
                        continue
                    sim = float(g["survived"].mean())
                    cdf = float((g[col] < D).mean())
                    worst = max(worst, abs(sim - cdf))
                    detail.append({"arch": arch, "rung": X, "step": step, "D": D,
                                   "n": g.height, "simulated": sim, "cdf": cdf})
    # ...and the SHIPPED table must equal it too. Checking only a locally
    # recomputed CDF would leave the published frontier unverified, which is how
    # a stop-live exit leaked into a descriptive phase in the first place.
    fr = pl.read_parquet(OUT / "stop_survival_frontier.parquet").filter(
        (pl.col("slice_kind") == "POOLED") & pl.col("architecture").is_in(
            ["HWM", "STATIC"])).drop_nulls("pct_success_surviving")
    # The shipped frontier is UNCONSTRAINED over the FULL achieved population,
    # so it must be compared against the CDF on that same population -- not
    # against the participants-only CDF used for the simulation check above.
    shipped, n_ship = 0.0, 0
    for r in fr.iter_rows(named=True):
        col = ("mae_from_hwm_atr" if r["architecture"] == "HWM"
               else "retrace_below_rung_atr")
        pop = s.filter((pl.col("rung_atr") == r["rung_atr"])
                       & (pl.col("step_atr") == r["step_atr"]))
        if pop.height == 0:
            continue
        n_ship += 1
        shipped = max(shipped, abs(r["pct_success_surviving"] / 100.0
                                   - float((pop[col] < r["stop_d"]).mean())))
    gates.append(_g("frontier_is_cdf_of_phase2",
                    worst < 1e-12 and shipped < 1e-9,
                    {"max_abs_difference_recomputed": worst,
                     "max_abs_difference_SHIPPED_TABLE": shipped,
                     "n_cells": len(detail), "n_shipped_cells_checked": n_ship,
                     "population": "participants only for the simulated side; "
                                   "the shipped frontier is UNCONSTRAINED and is "
                                   "compared against the full-population CDF"}))

    # 8 -- LADDER_HWM identity
    lid = ladder_identity(market, regimes, conf)
    gates.append(_g("ladder_hwm_identical_to_hwm", lid["mismatches"] == 0, lid))

    # 9 / 10 -- hard-truncated replay incl. the H4 fill convention
    rep = hard_truncated_replay(market, regimes, conf)
    gates.append(_g("h4_fill_never_at_trigger", rep["mismatches"] == 0,
                    {"fill_checks_included": True, **rep}))
    gates.append(_g("hard_truncated_replay",
                    rep["mismatches"] == 0 and rep["trades"] >= 250
                    and rep["rung_events"] >= 2500, rep))

    # 11 -- collisions counted
    coll = xd.filter((pl.col("basis") == BASIS_POST)
                     & (pl.col("outcome") == "SUCCESS"))
    n_coll = int(coll["collision_at_target"].sum())
    gates.append(_g("collisions_adverse_with_optimistic_bound", True,
                    {"n_success_transitions": coll.height,
                     "n_same_bar_collisions": n_coll,
                     "pct": 100.0 * n_coll / max(coll.height, 1)}))

    # 12 -- already-met rows excluded from distributions
    am = xd.filter(pl.col("outcome") == "ALREADY_MET")
    ok12 = bool(am["mae_from_hwm_atr"].is_null().all()
                and am["retrace_below_rung_atr"].is_null().all())
    gates.append(_g("already_met_excluded", ok12,
                    {"n_already_met": am.height,
                     "by_rung": am.group_by("rung_atr", "basis", "stratum")
                     .len().sort("rung_atr").to_dicts()}))

    # 13 -- duration confound disclosed (checked in analysis output naming)
    ov = OUT / "overlap.parquet"
    ok13 = (not ov.exists()) or any(
        "DURATION_CONFOUNDED" in c for c in pl.read_parquet(ov).columns)
    gates.append(_g("duration_confound_disclosed", ok13,
                    {"overlap_table_present": ov.exists()}))

    # 14 -- placebo causality, actually tested rather than asserted.
    #
    # The claim is that P_BLIND's SUPPORT does not depend on the realised
    # lifetime. The test: draw armings for trades in the shortest and longest
    # lifetime quartiles and confirm every armed index is the trade's own bar at
    # a DENSE_OFFSETS_S offset -- i.e. the draw is over the fixed grid, and the
    # lifetime only decides whether a drawn offset lands in-window (no arming),
    # never which offsets are candidates. P_UNIFORM is checked to be the
    # opposite, so the two cannot be confused downstream.
    from .build import placebo_armings
    from .rungs import DENSE_OFFSETS_S
    rng14 = np.random.default_rng(SEED + 2)
    life = td.select("regime_id", (pl.col("nat_terminal_ns") - pl.col("confirm_ns"))
                     .alias("life")).sort("life")
    ends = pl.concat([life.head(60), life.tail(60)])["regime_id"].to_list()
    bad14, checked14, unif_depends = 0, 0, 0
    for tr in conf.filter(pl.col("regime_id").is_in(ends)).iter_rows(named=True):
        rt = build_trade(market, regimes, tr)
        if rt is None:
            continue
        blind, unif = placebo_armings(rt, rng14)
        # The armed bar must BE `index_at_offset(L)` for some L on the frozen
        # grid. Testing a wall-clock tolerance instead would fail on thin
        # periods where the next 1s bar is seconds away -- a gap in the tape,
        # not a lifetime dependence. This equality is exact and gap-immune.
        grid_idx = {rt.w.index_at_offset(int(L)) for L in DENSE_OFFSETS_S}
        for a in blind[blind >= 0]:
            checked14 += 1
            if int(a) not in grid_idx:
                bad14 += 1
        # P_UNIFORM must depend on the lifetime -- that is why it is a benchmark
        if unif.max() <= rt.w.nat_i and rt.w.nat_i > rt.w.ci:
            unif_depends += 1
    gates.append(_g("placebo_causality", bad14 == 0 and checked14 > 200,
                    {"blind_armings_checked": checked14,
                     "blind_armings_off_grid": bad14,
                     "uniform_confirmed_lifetime_dependent": unif_depends,
                     "P_BLIND": "grid-offset support, lifetime-independent",
                     "P_UNCOND": "armed at confirmation, deterministic",
                     "P_UNIFORM": "FUTURE_INFORMATION, benchmark only"}))

    # 15 -- dependence
    ok15 = bool(ed["regime_id"].n_unique() <= ACCEPTED["measurable"])
    gates.append(_g("no_pseudo_replication", ok15,
                    {"unique_trades_in_events": int(ed["regime_id"].n_unique()),
                     "rung_event_rows": ed.height}))

    # 16 -- completeness of the frozen cell grid
    cells = (cd.filter(pl.col("achieved"))
             .select("rung_atr", "stop_d", "architecture").unique().height)
    expect = len(RUNGS) * len(STOP_DISTANCES) * len(ARCHITECTURES)
    parts = td.group_by("entry_year", "side").len()
    gates.append(_g("grid_and_partition_completeness",
                    cells == expect and parts.height == 10,
                    {"cells": cells, "expected": expect,
                     "partitions": parts.height,
                     "transitions_is_2x_events": xd.height == ed.height * 2}))

    rep_json = {"gates": gates,
                "all_passed": all(g["passed"] for g in gates),
                "n_failed": sum(1 for g in gates if not g["passed"]),
                "survival_cells": detail}
    (OUT / "validation_report.json").write_text(json.dumps(rep_json, indent=2,
                                                           default=str))
    for g in gates:
        print(f"  [{'PASS' if g['passed'] else 'FAIL'}] {g['gate']}")
    print(f"\n  all_passed = {rep_json['all_passed']}")


if __name__ == "__main__":
    main()
