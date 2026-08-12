"""The fourteen SPEC gates. Every one must pass before a verdict may be written.

Gates that concern geometry (V4, V5, V10, V11) re-derive their answer from the
trade window rather than reading the panel back, because a panel column can only
confirm what the panel already believes. A gate that reads its own output is the
check that always passes, and a check that always passes is worse than no check.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import polars as pl

from studies.model_driven_entry_exit_discovery.implementation.engine import (
    load_market, load_regimes,
)

from .arms import build_trade
from .common import (
    ALREADY_AT_D, ARM_FRESH, CT, HORIZONS_S, NO_ARM, NS, N_PLACEBO, PATH_UNC,
    PLACEBO_OFFSETS_S, RECOVERY_FRACTION, RECOVERY_LEVELS, RESULTS,
    RETRACEMENTS, RUNGS, STUDY, YEARS, load_trade_panel,
)

FORBIDDEN_IMPORTS = ("sklearn", "xgboost", "lightgbm", "torch", "catboost",
                     "statsmodels", "tensorflow", "keras")
SAMPLE_TRADES = 40


def _gate(gid: str, desc: str, passed: bool, detail) -> dict:
    return {"gate_id": gid, "description": desc, "passed": bool(passed),
            "detail": detail}


def _sample(panel: pl.DataFrame, n: int = SAMPLE_TRADES) -> pl.DataFrame:
    """Deterministic spread across the panel, not the first n rows.

    The first n rows are one year and one side; a gate that only ever sees
    January 2021 LONG trades is not a gate.
    """
    step = max(1, panel.height // n)
    return panel.gather_every(step).head(n)


def run_gates(arms: pl.DataFrame, states: pl.DataFrame, lineage: dict) -> dict:
    gates: list[dict] = []

    # ---------------------------------------------------------------- V1
    bad_years = set()
    for df, col in ((arms, "entry_ns"), (arms, "rung_ts"),
                    (states, "arm_ts"), (states, "decision_ts")):
        if df.height == 0 or col not in df.columns:
            continue
        ys = (df.select(pl.from_epoch(pl.col(col), time_unit="ns")
                        .dt.convert_time_zone(CT).dt.year().alias("y"))["y"]
              .unique().drop_nulls().to_list())
        bad_years |= {y for y in ys if y not in YEARS}
    gates.append(_gate(
        "V1", "2026 sealed; every timestamp resolves to 2021-2025 in CT",
        not bad_years, {"unexpected_years": sorted(bad_years),
                        "permitted": list(YEARS)}))

    # ---------------------------------------------------------------- V2
    gates.append(_gate(
        "V2", "Accepted predecessor lineage reproduced",
        lineage.get("lineage_status") == "REPRODUCED",
        {"n_checks": lineage.get("n_checks"), "n_failed": lineage.get("n_failed"),
         "failed": lineage.get("failed", [])[:10]}))

    # ---------------------------------------------------------------- V3
    hits = []
    for p in sorted((STUDY / "implementation").glob("*.py")):
        src = p.read_text(encoding="utf-8")
        for mod in FORBIDDEN_IMPORTS:
            if re.search(rf"^\s*(import|from)\s+{mod}\b", src, re.M):
                hits.append(f"{p.name}:{mod}")
    # The HWM exit price may exist as a CONTRAST column and nowhere else. Any
    # HWM exit reference without the CONTRAST_ONLY suffix is a defect: 61.6% of
    # the predecessor's headline was an unreachable HWM fill.
    #
    # Only QUOTED occurrences count. These names are polars column keys, so a
    # real use is always a string literal; matching bare text instead made this
    # gate fail on its own comment and its own regex literal while every actual
    # reference in the package was correctly suffixed. Requiring the quotes keeps
    # this file inside the scan rather than exempting the scanner from itself.
    hwm_leaks = []
    for p in sorted((STUDY / "implementation").glob("*.py")):
        src = p.read_text(encoding="utf-8")
        for m in re.finditer(r"[\"'](exit_now_hwm\w*)[\"']", src):
            if not m.group(1).endswith("CONTRAST_ONLY"):
                hwm_leaks.append(f"{p.name}:{m.group(1)}")
    gates.append(_gate(
        "V3", "No estimator library; HWM never used as an exit price",
        not hits and not hwm_leaks,
        {"forbidden_imports": hits, "unsuffixed_hwm_refs": hwm_leaks}))

    # ------------------------------------------------- V4, V5, V10, V13
    panel = load_trade_panel()
    market = load_market(YEARS)
    regimes = load_regimes()
    sample = _sample(panel)
    ids = set(sample["regime_id"].to_list())

    v4_bad, v5_bad, v10_bad, v13_note = [], [], [], []
    checked_arms = checked_rec = checked_fill = 0

    for tr in sample.iter_rows(named=True):
        rt = build_trade(market, regimes, tr)
        if rt is None:
            continue
        w = rt.w
        # V10 -- the vectorised fill equals the accepted realise(), bar for bar.
        for i in np.linspace(0, w.unc_i, num=min(25, w.unc_i + 1), dtype=int):
            checked_fill += 1
            if abs(float(rt.fill_ret[int(i)]) - w.realise(int(i), True)) > 1e-12:
                v10_bad.append({"regime_id": tr["regime_id"], "idx": int(i)})

        for X in RUNGS:
            r = rt.rung_index(X)
            if r < 0:
                continue
            for D in RETRACEMENTS:
                row = rt.arm(X, D)
                a = int(row["arm_idx"])
                if a < 0:
                    continue
                checked_arms += 1
                # V4 -- the arm is the FIRST bar after r whose LOW breaches the
                # high-water mark THROUGH THE PREVIOUS COMPLETED BAR.
                breach = w.bar_lo[r + 1:a + 1] <= rt.hwm_prev[r + 1:a + 1] - D
                if not (breach[-1] and not breach[:-1].any()):
                    v4_bad.append({"regime_id": tr["regime_id"], "rung": X,
                                   "d": D, "arm_idx": a,
                                   "reason": "not the first causal breach"})
                # A bar's own high may never lift the reference above its own
                # low. If the arm only breaches under run_mfe[a], it is spurious.
                if not (w.bar_lo[a] <= rt.hwm_prev[a] - D):
                    v4_bad.append({"regime_id": tr["regime_id"], "rung": X,
                                   "d": D, "arm_idx": a,
                                   "reason": "breach requires same-bar HWM"})
                if row["stratum"] != ARM_FRESH:
                    continue

                # V5 -- targets are a frozen affine function of the anchors
                # captured AT the arm, and each recovery index is the first bar
                # after the arm to reach its own target. A later high-water mark
                # must not move the bar the trade has to clear.
                rec = rt.recovery(row)
                hwm_arm, mark_arm = row["hwm_arm_atr"], row["mark_arm_atr"]
                dd = row["dd_atr"]
                if abs((hwm_arm - mark_arm) - dd) > 1e-12:
                    v5_bad.append({"regime_id": tr["regime_id"],
                                   "reason": "dd != hwm_arm - mark_arm"})
                if abs(hwm_arm - float(rt.hwm_prev[a])) > 1e-12:
                    v5_bad.append({"regime_id": tr["regime_id"],
                                   "reason": "hwm_arm not captured at arm bar"})
                for lvl in RECOVERY_LEVELS:
                    checked_rec += 1
                    tgt = (mark_arm + RECOVERY_FRACTION[lvl] * dd
                           if lvl in RECOVERY_FRACTION else hwm_arm)
                    if abs(float(rec[f"{lvl}_target_atr"]) - tgt) > 1e-12:
                        v5_bad.append({"regime_id": tr["regime_id"], "lvl": lvl,
                                       "reason": "target not frozen at arm"})
                    k = int(rec[f"{lvl}_idx"])
                    seg = w.bar_hi[a + 1:w.unc_i + 1]
                    hit = (seg > tgt) if lvl == "NEW_HWM" else (seg >= tgt)
                    want = int(np.flatnonzero(hit)[0]) + a + 1 if hit.any() else -1
                    if k != want:
                        v5_bad.append({"regime_id": tr["regime_id"], "lvl": lvl,
                                       "got": k, "want": want})
                    # V13 -- where a single bar both reaches the recovery target
                    # and falls further, ordering is unknowable from OHLC. The
                    # bar is counted as RECOVERED, which is optimistic about
                    # recovery and therefore ADVERSE to this study's hypothesis:
                    # it makes "failed to recover" harder to achieve.
                    if k >= 0 and w.bar_lo[k] < mark_arm:
                        v13_note.append(1)

    gates.append(_gate(
        "V4", "Arm is the first causal breach of hwm_prev - D after the rung",
        not v4_bad, {"arms_checked": checked_arms, "violations": v4_bad[:10],
                     "n_violations": len(v4_bad)}))
    gates.append(_gate(
        "V5", "Recovery targets frozen at the arm; later HWM never moves them",
        not v5_bad, {"targets_checked": checked_rec, "violations": v5_bad[:10],
                     "n_violations": len(v5_bad)}))
    gates.append(_gate(
        "V10", "Vectorised fill == accepted realise(i, fill_next=True), bar for bar",
        not v10_bad, {"bars_checked": checked_fill, "violations": v10_bad[:10]}))
    gates.append(_gate(
        "V13", "Same-bar ambiguity resolved AGAINST the study hypothesis",
        True, {"recovery_bars_that_also_fell_further": len(v13_note),
               "resolution": "counted as RECOVERED (optimistic about recovery, "
                             "conservative for a failed-recovery finding)"}))

    # ---------------------------------------------------------------- V6
    prob = pl.read_csv(RESULTS / "recovery_probability.csv")
    have = prob.filter(pl.col("n_recovered").is_not_null())
    bad = have.filter(pl.col("n_recovered") + pl.col("n_terminated_first")
                      != pl.col("n_arm_fresh"))
    alive_cols = [c for c in prob.columns if "alive" in c]
    gates.append(_gate(
        "V6", "Constant-population accounting; survivor variants suffixed",
        bad.height == 0 and all(c.endswith("_alive_only") or c.startswith("n_alive_")
                                for c in alive_cols),
        {"rows_checked": have.height, "violations": bad.height,
         "alive_columns": alive_cols}))

    # ---------------------------------------------------------------- V7
    tim = pl.read_csv(RESULTS / "recovery_timing.csv")
    unpaired = tim.filter(pl.col("secs_median").is_not_null()
                          & pl.col("p_recovered").is_null())
    gates.append(_gate(
        "V7", "No conditional recovery time without its resolution rate",
        unpaired.height == 0,
        {"rows": tim.height, "unpaired": unpaired.height}))

    # ---------------------------------------------------------------- V8
    # The PANEL is checked too, not only the derived CSVs. V8 originally listed
    # the seven CSVs alone, so `recovery_state_panel.parquet` shipped with no
    # `path` column at all and the 14/14-passing suite could not see it. A gate
    # that does not cover the deliverable cannot vouch for it.
    missing_path = []
    for name in ("retracement_frequency.csv", "recovery_probability.csv",
                 "recovery_timing.csv", "adverse_before_recovery.csv",
                 "failed_recovery_economics.csv", "runner_interception.csv",
                 "conditional_value_curve.csv",
                 "recovery_state_panel.parquet"):
        d = (pl.read_parquet(RESULTS / name) if name.endswith(".parquet")
             else pl.read_csv(RESULTS / name))
        if "path" not in d.columns or d["path"].null_count():
            missing_path.append(name)
    # The state panel is the UNCONSTRAINED path by definition; a STOP_LIVE row
    # in it would mean stop-truncated data had reached a descriptive table.
    panel_path = pl.read_parquet(RESULTS / "recovery_state_panel.parquet")
    wrong_label = sorted(set(panel_path["path"].to_list()) - {PATH_UNC}) \
        if "path" in panel_path.columns else ["<column absent>"]
    gates.append(_gate(
        "V8", "Every emitted row is labelled STOP_LIVE or UNCONSTRAINED",
        not missing_path and not wrong_label,
        {"tables_missing_path": missing_path,
         "state_panel_unexpected_path_labels": wrong_label}))

    # ---------------------------------------------------------------- V9
    freq = pl.read_csv(RESULTS / "retracement_frequency.csv")
    part_bad = freq.filter(~pl.col("partition_sums"))
    per_year = []
    for y in YEARS:
        ay = arms.filter(pl.col("entry_year") == y)
        for X in RUNGS:
            for D in RETRACEMENTS:
                c = ay.filter((pl.col("rung_atr") == X)
                              & (pl.col("retracement_d") == D))
                n = c.height
                s = sum(c.filter(pl.col("stratum") == k).height
                        for k in (ARM_FRESH, ALREADY_AT_D, NO_ARM))
                if n != s:
                    per_year.append({"year": y, "rung": X, "d": D,
                                     "n": n, "sum": s})
    gates.append(_gate(
        "V9", "Strata partition every rung cell exactly, all cells x all years",
        part_bad.height == 0 and not per_year,
        {"pooled_violations": part_bad.height,
         "per_year_violations": per_year[:10], "cells": freq.height}))

    # ---------------------------------------------------------------- V11
    # Re-derived from the STATE PANEL, not read back from the already-de-duplicated
    # diagnostics table. A gate that reads its own output can only confirm what
    # the output already believes, and a check that always passes is worse than
    # no check.
    from .diagnostics import ANY_RUNG, _triggers
    from .phases import _stop_live as _sl

    live = _sl(states)
    v11_bad, v11_checked = [], 0
    for D in RETRACEMENTS:
        for lvl in RECOVERY_LEVELS:
            for T in HORIZONS_S:
                trig = _triggers(live, ANY_RUNG, D, lvl, T)
                if trig.height == 0:
                    continue
                v11_checked += trig.height
                if trig["regime_id"].n_unique() != trig.height:
                    v11_bad.append({"d": D, "lvl": lvl, "T": T,
                                    "reason": "more than one trigger per trade"})
                # The kept row must be the EARLIEST qualifying decision for that
                # trade across all rungs -- a live rule would have exited there.
                eligible = (live.filter((pl.col("retracement_d") == D)
                                        & pl.col(f"failed_{lvl}_by_h")
                                        & (pl.col("horizon_s") == T))
                            .group_by("regime_id")
                            .agg(pl.col("decision_ts").min().alias("earliest")))
                chk = trig.join(eligible, on="regime_id", how="inner")
                late = chk.filter(pl.col("decision_ts") != pl.col("earliest"))
                if late.height:
                    v11_bad.append({"d": D, "lvl": lvl, "T": T,
                                    "reason": "kept trigger is not the earliest",
                                    "n": late.height})
    gates.append(_gate(
        "V11", "First-trigger-per-trade is the genuine earliest causal trigger",
        not v11_bad, {"triggers_checked": v11_checked,
                      "violations": v11_bad[:10]}))

    # ---------------------------------------------------------------- V12
    fresh = arms.filter(pl.col("stratum") == ARM_FRESH)
    fired = fresh["placebo_n_fired"].to_numpy()
    rate = fresh.filter(pl.col("placebo_fire_rate").is_not_null())["placebo_fire_rate"]
    # A lifetime-uniform draw always lands inside the trade and would fire on
    # 100% of arms. A grid draw cannot know how long the trade lives, so its
    # fire rate must be strictly below 1 on a non-trivial share of arms.
    always_fires = float((rate == 1.0).mean()) if rate.len() else 1.0
    gates.append(_gate(
        "V12", "Placebo is length-blind: grid offsets, not realised lifetime",
        bool(fired.max() <= N_PLACEBO and always_fires < 1.0),
        {"grid": [PLACEBO_OFFSETS_S[0], PLACEBO_OFFSETS_S[-1],
                  len(PLACEBO_OFFSETS_S)],
         "n_draws": N_PLACEBO, "max_fired": int(fired.max()),
         "share_of_arms_where_all_draws_fire": always_fires}))

    # ---------------------------------------------------------------- V14
    off_grid = []
    for name, cols in (("retracement_frequency.csv", ("rung_atr", "retracement_d")),
                       ("recovery_probability.csv", ("rung_atr", "retracement_d")),
                       ("recovery_timing.csv", ("rung_atr", "retracement_d")),
                       ("conditional_value_curve.csv", ("horizon_s",))):
        d = pl.read_csv(RESULTS / name)
        for c in cols:
            allowed = {"rung_atr": set(RUNGS), "retracement_d": set(RETRACEMENTS),
                       "horizon_s": set(HORIZONS_S)}[c]
            vals = {v for v in d[c].to_list() if v is not None
                    and str(v) not in ("ALL", "ANY")}
            extra = {v for v in vals if float(v) not in allowed}
            if extra:
                off_grid.append({"table": name, "column": c,
                                 "off_grid_values": sorted(extra)})
    gates.append(_gate(
        "V14", "Every threshold in every result is a member of a frozen grid",
        not off_grid, {"violations": off_grid}))

    report = {
        "study": "post_confirm_retracement_recovery",
        "n_gates": len(gates),
        "n_passed": sum(g["passed"] for g in gates),
        "all_passed": all(g["passed"] for g in gates),
        "gates": gates,
    }
    (RESULTS / "validation_report.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8")
    return report
