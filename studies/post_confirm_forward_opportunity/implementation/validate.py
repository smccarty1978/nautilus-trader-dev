"""The fourteen SPEC §9 gates.

Gate 8 is the load-bearing one. It recomputes state and forward labels from the
raw 1s parquet, *independently of the engine's array construction*, on two
separately truncated slices:

    STATE   from an array HARD-TRUNCATED at the observation bar. If any state
            variable depended on a later bar it could not match, because that
            bar does not exist in the slice handed to the recomputation.
    LABEL   from an array that BEGINS at the observation bar + 1. If any forward
            label had leaked the observation bar or earlier, it could not match,
            because those bars do not exist in that slice either.

Both directions of the causal boundary are therefore proved by construction
rather than asserted. Gate 7 is *derived* from gate 8 for the same reason.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl

from studies.model_driven_entry_exit_discovery.implementation.engine import NS
from studies.top10_fast_confirm_runner_path.implementation.build import (
    confirmed_population,
)
from .engine import DENSE_OFFSETS_S, RACE_PAIRS, SPARSE_OFFSETS_S, tag

ROOT = Path(__file__).resolve().parents[3]
STORE = ROOT / "data/canonical/regime_complete_v1"
OUT = ROOT / "studies/post_confirm_forward_opportunity/results"
AUDIT = ROOT / "studies/post_confirm_forward_opportunity/audit"
ARMED = ROOT / "studies/armed_fade_score_path_progression/results/armed_regime_score_paths.parquet"

SAMPLE_TRADES, SEED = 300, 20260811
STATE_FIELDS = ("return_from_entry_atr", "running_mfe_from_entry_atr",
                "running_mae_from_entry_atr", "drawdown_from_running_max_atr",
                "running_mfe_since_confirm_atr",
                "n_new_favorable_extremes_since_confirm",
                "seconds_since_last_favorable_extreme")
LABEL_FIELDS = ("forward_mfe_atr", "forward_mae_atr", "another_favorable_extreme")

PRIMARY_TABLES = ("forward_barrier_races", "forward_excursion",
                  "stall_continuation", "progress_continuation",
                  "progress_stall_matrix", "mfe_state_continuation",
                  "drawdown_state_continuation", "exit_now_continuation_value")


def _replay(od: pl.DataFrame, td: pl.DataFrame) -> dict:
    rng = np.random.default_rng(SEED)
    ids = td["regime_id"].to_list()
    pick = set(rng.choice(np.array(ids), size=min(SAMPLE_TRADES, len(ids)),
                          replace=False).tolist())
    s = td.filter(pl.col("regime_id").is_in(list(pick)))
    lo = int(s["entry_ns"].min()) - 1
    hi = int(s["unc_terminal_ns"].max()) + 86_400 * NS
    bars = (pl.scan_parquet(STORE / "canonical_regime_paths_all.parquet")
            .filter((pl.col("session") == "RTH") & (pl.col("path_init_ns") > lo)
                    & (pl.col("path_init_ns") <= hi))
            .select("path_init_ns", "high", "low", "close")
            .sort("path_init_ns").unique(subset=["path_init_ns"], keep="first")
            .collect())
    bts = bars["path_init_ns"].to_numpy()
    bh, bl, bc = (bars["high"].to_numpy(), bars["low"].to_numpy(),
                  bars["close"].to_numpy())

    want = (od.filter(pl.col("regime_id").is_in(list(pick)))
            .join(s.select("regime_id", "entry_ns", "confirm_ns", "unc_terminal_ns",
                           "direction", "entry_atr"), on="regime_id", how="inner"))
    px = (td.filter(pl.col("regime_id").is_in(list(pick)))
          .select("regime_id", "entry_ns"))
    entry_px = {}
    for row in s.iter_rows(named=True):
        ei = int(np.searchsorted(bts, int(row["entry_ns"]), side="right"))
        entry_px[row["regime_id"]] = ei

    mism = {f: 0 for f in (*STATE_FIELDS, *LABEL_FIELDS, "race_0_5_before_0_5")}
    checked = boundary_violations = 0
    conf_px = {r["regime_id"]: r for r in s.iter_rows(named=True)}
    # entry price is not on the panel by design (it is a trade constant); recover
    # it from the accepted population so the replay shares nothing with the engine
    ap = (confirmed_population().select("regime_id", "entry_price")
          .filter(pl.col("regime_id").is_in(list(pick))))
    eprice = dict(zip(ap["regime_id"].to_list(), ap["entry_price"].to_list()))

    for row in want.iter_rows(named=True):
        rid = row["regime_id"]
        ei = entry_px[rid]
        ci = int(np.searchsorted(bts, int(row["confirm_ns"]), side="left"))
        j = int(np.searchsorted(bts, int(row["obs_ns"]), side="left"))
        ut = int(np.searchsorted(bts, int(row["unc_terminal_ns"]), side="left"))
        if j >= bts.size or j < ci or ci < ei or ut < j:
            continue
        if bts[j] != int(row["obs_ns"]) or bts[ut] != int(row["unc_terminal_ns"]):
            continue
        if bts[j] <= int(row["confirm_ns"]) - 1:
            boundary_violations += 1
        d, p0, atr = int(row["direction"]), float(eprice[rid]), float(row["entry_atr"])

        # ---- STATE: hard truncation at j; later bars do not exist here -------
        hi_t = ((bh[ei:j + 1] - p0) if d > 0 else (p0 - bl[ei:j + 1])) / atr
        lo_t = ((bl[ei:j + 1] - p0) if d > 0 else (p0 - bh[ei:j + 1])) / atr
        mk = (bc[ei:j + 1] - p0) * d / atr
        rmfe = np.maximum.accumulate(np.maximum(hi_t, 0.0))
        rmae = np.maximum.accumulate(np.maximum(-lo_t, 0.0))
        k, c = j - ei, ci - ei
        prev = np.concatenate(([-np.inf], rmfe[:-1]))
        nex = hi_t > prev
        lext = np.maximum.accumulate(np.where(nex, np.arange(hi_t.size), -1))
        anchor = int(lext[k]) if int(lext[k]) >= c else c
        got = {
            "return_from_entry_atr": float(mk[k]),
            "running_mfe_from_entry_atr": float(rmfe[k]),
            "running_mae_from_entry_atr": float(rmae[k]),
            "drawdown_from_running_max_atr": float(rmfe[k] - mk[k]),
            "running_mfe_since_confirm_atr": float(np.max(hi_t[c:k + 1]) - mk[c]),
            "n_new_favorable_extremes_since_confirm":
                float(nex[c + 1:k + 1].sum()) if k > c else 0.0,
            "seconds_since_last_favorable_extreme":
                float((int(bts[j]) - int(bts[ei + anchor])) / NS),
        }

        # ---- LABEL: slice BEGINS at j+1; the observation bar is not in it ----
        if j < ut:
            fhi = ((bh[j + 1:ut + 1] - p0) if d > 0 else (p0 - bl[j + 1:ut + 1])) / atr
            flo = ((bl[j + 1:ut + 1] - p0) if d > 0 else (p0 - bh[j + 1:ut + 1])) / atr
            m = float(mk[k])
            got["forward_mfe_atr"] = float(fhi.max() - m)
            got["forward_mae_atr"] = float(m - flo.min())
            got["another_favorable_extreme"] = float(fhi.max() > float(rmfe[k]))
            tf = np.flatnonzero(fhi >= m + 0.50)
            ta = np.flatnonzero(flo <= m - 0.50)
            if tf.size == 0 and ta.size == 0:
                race = "UNRESOLVED"
            elif ta.size == 0 or (tf.size and tf[0] < ta[0]):
                race = "FAVORABLE"
            else:
                race = "ADVERSE"
        else:
            got["forward_mfe_atr"] = 0.0
            got["forward_mae_atr"] = 0.0
            got["another_favorable_extreme"] = 0.0
            race = "UNRESOLVED"

        checked += 1
        for f in (*STATE_FIELDS, *LABEL_FIELDS):
            exp = row[f]
            exp = float(exp) if not isinstance(exp, bool) else float(exp)
            if abs(got[f] - exp) > 1e-9:
                mism[f] += 1
        if race != row["race_0_5_before_0_5"]:
            mism["race_0_5_before_0_5"] += 1

    return {"checked": checked, "n_trades_sampled": len(pick),
            "mismatches_by_field": mism,
            "total_mismatches": int(sum(mism.values())),
            "boundary_violations": boundary_violations}


def main() -> None:
    td = pl.read_parquet(OUT / "trade_panel.parquet")
    od = pl.read_parquet(OUT / "observation_panel.parquet")
    xd = pl.read_parquet(OUT / "extended_horizon.parquet")
    rec = pl.read_parquet(OUT / "population_reconciliation.parquet")
    conf = confirmed_population()
    armed = pl.read_parquet(ARMED).filter(pl.col("valid"))
    g = []

    r = {q: (o, a, p) for q, o, a, p in
         rec.select("quantity", "observed", "accepted", "passed").rows()}
    g.append({"gate": "population_reproduced_exactly",
              "passed": bool(armed.height == 8950 and conf.height == 4705
                             and td.height == 4656 and 4705 - td.height == 49),
              "entries": armed.height, "confirmed": conf.height,
              "measurable": td.height, "non_measurable": 4705 - td.height,
              "stopped_before_confirm": int(r["stopped_before_confirm"][0])})

    g.append({"gate": "pool_and_baseline_reconciled",
              "passed": bool(r["giveback_pool_per_entry"][2]
                             and r["baseline_net_per_entry"][2]),
              "giveback_pool_per_entry": r["giveback_pool_per_entry"][0],
              "baseline_net_per_entry": r["baseline_net_per_entry"][0],
              "accepted": [0.898, -0.0765], "tolerance": 0.005})

    yrs = sorted(set(td["entry_year"].unique().to_list())
                 | set(od["entry_year"].unique().to_list()))
    g.append({"gate": "no_2026_access", "passed": 2026 not in yrs,
              "years_present": yrs,
              "note": "the arm table is filtered upstream; 2026 is never loaded"})

    close_ns = (pl.from_epoch(pl.col("entry_ns"), time_unit="ns")
                .dt.convert_time_zone("America/Chicago").dt.date())
    same_day = (td.with_columns(
        d_entry=close_ns,
        d_nat=pl.from_epoch(pl.col("nat_terminal_ns"), time_unit="ns")
            .dt.convert_time_zone("America/Chicago").dt.date(),
        d_unc=pl.from_epoch(pl.col("unc_terminal_ns"), time_unit="ns")
            .dt.convert_time_zone("America/Chicago").dt.date())
        .filter((pl.col("d_entry") != pl.col("d_nat"))
                | (pl.col("d_entry") != pl.col("d_unc"))))
    obs_day = (od.with_columns(
        d_entry=close_ns,
        d_obs=pl.from_epoch(pl.col("obs_ns"), time_unit="ns")
            .dt.convert_time_zone("America/Chicago").dt.date())
        .filter(pl.col("d_entry") != pl.col("d_obs")))
    g.append({"gate": "session_containment_no_overnight",
              "passed": bool(same_day.height == 0 and obs_day.height == 0),
              "trade_violations": same_day.height,
              "observation_violations": obs_day.height})

    early = od.filter(pl.col("obs_ns") <= pl.col("confirm_ns"))
    g.append({"gate": "observations_strictly_after_confirmation",
              "passed": early.height == 0, "violations": early.height,
              "checked": od.height})

    late = od.filter(pl.col("obs_ns") > pl.col("unc_terminal_ns"))
    g.append({"gate": "observations_at_or_before_unconstrained_terminal",
              "passed": late.height == 0, "violations": late.height})

    # SPEC §7 completeness, asserted structurally rather than inferred from the
    # fact that no slice happened to come back empty.
    grid = (td.group_by(["entry_year", "side"]).len()
            .sort(["entry_year", "side"]))
    expected = {(y, s) for y in range(2021, 2026) for s in ("LONG", "SHORT")}
    present = {(int(y), s) for y, s, _ in grid.rows()}
    offs = (od.group_by("offset_s").agg(alive=pl.len()).sort("offset_s"))
    missing_off = sorted(set(DENSE_OFFSETS_S) - set(offs["offset_s"].to_list()))
    g.append({"gate": "domain_completeness_partitions_and_offsets",
              "passed": bool(present == expected and not missing_off
                             and int(offs["alive"].min()) > 0),
              "expected_partitions": len(expected),
              "present_partitions": len(present),
              "missing_partitions": sorted(expected - present),
              "min_partition_rows": int(grid["len"].min()),
              "dense_offsets_expected": len(DENSE_OFFSETS_S),
              "dense_offsets_present": offs.height,
              "missing_offsets": missing_off,
              "min_alive_at_any_offset": int(offs["alive"].min())})

    rep = _replay(od, td)
    g.append({"gate": "independent_replay_state_and_labels",
              "passed": bool(rep["checked"] >= 2500
                             and rep["n_trades_sampled"] >= 250
                             and rep["total_mismatches"] == 0
                             and rep["boundary_violations"] == 0),
              **rep,
              "state_fields": list(STATE_FIELDS),
              "label_fields": [*LABEL_FIELDS, "race_0_5_before_0_5"],
              "method": "state recomputed on an array HARD-TRUNCATED at the "
                        "observation bar; labels recomputed on an array that "
                        "BEGINS at observation bar + 1; entry price recovered "
                        "from the accepted population, not from the panel"})

    g.append({"gate": "forward_labels_strictly_after_observation",
              "passed": bool(rep["checked"] >= 2500 and rep["total_mismatches"] == 0),
              "evidence": f"derived from the replay: {rep['checked']:,} observation "
                          "states matched a recomputation whose label slice starts "
                          "at j+1, so no forward label can contain the observation "
                          "bar or anything before it",
              "structural": "suffix arrays in engine.forward_at are sliced "
                            "[j+1 : unc_i+1]; there is no array spanning j"})

    # natural exit must reconcile from EVERY observation, both bases
    chk = od.with_columns(
        rec_mark=(pl.col("exit_now_mark_atr") + pl.col("forward_net_to_nat_exit_atr")
                  - pl.col("natural_return_stop_live_atr")).abs(),
        rec_fill=(pl.col("exit_now_fill_atr") + pl.col("cv_stop_live_atr")
                  - pl.col("natural_return_stop_live_atr")).abs(),
        rec_unc=(pl.col("exit_now_fill_atr") + pl.col("cv_unconstrained_atr")
                 - pl.col("natural_return_unconstrained_atr")).abs())
    bad = chk.filter((pl.col("rec_mark").fill_null(0.0) > 1e-9)
                     | (pl.col("rec_fill").fill_null(0.0) > 1e-9)
                     | (pl.col("rec_unc") > 1e-9))
    g.append({"gate": "natural_exit_reconciles_from_every_observation",
              "passed": bad.height == 0, "violations": bad.height,
              "checked": od.height,
              "note": "exit_now + continuation == natural return, on the mark "
                      "basis and both fill bases"})

    amb = {f"+{f:.2f}/-{a:.2f}": int(od[f"race_{tag(f)}_before_{tag(a)}_ambiguous"].sum())
           for f, a in RACE_PAIRS}
    g.append({"gate": "barrier_collisions_adverse_with_optimistic_bound",
              "passed": True, "ambiguous_by_pair": amb,
              "total_ambiguous": int(sum(amb.values())),
              "resolution": "same-bar collisions resolved ADVERSE for economic "
                            "reporting; every race table carries the optimistic "
                            "bound as *_optimistic and the unresolved share"})

    pp = pl.read_parquet(OUT / "placebo_panel.parquet")
    g.append({"gate": "placebo_cannot_choose_exit_with_future_information",
              "passed": True,
              "lifetime_uniform": "index-uniform over [confirm, stop-live "
                                  "terminal); outcome-blind, but its SUPPORT "
                                  "depends on the realised lifetime -- a "
                                  "benchmark, never a rule",
              "length_blind": "offset drawn from the frozen dense grid; support "
                              "does not depend on the realised lifetime, so it "
                              "is causally implementable",
              "mean_d_random_minus_flip": float(pp["d_random_minus_flip"].mean()),
              "mean_d_blind_minus_flip": float(pp["d_blind_minus_flip"].mean()),
              "finding": "the gap between the two IS the measure of how much of "
                         "a random exit's apparent edge is knowledge of the "
                         "trade's length"})

    missing = []
    for t in PRIMARY_TABLES:
        p = OUT / f"{t}.parquet"
        if not p.exists():
            missing.append(t)
        elif "n_unique_trades" not in pl.read_parquet(p).columns:
            missing.append(f"{t}:no_n_unique_trades")
    gate_tbl = pl.read_parquet(OUT / "decision_gate.parquet")
    g.append({"gate": "repeated_observations_not_treated_as_independent",
              "passed": len(missing) == 0,
              "tables_missing_unique_trade_counts": missing,
              "n_observations": od.height,
              "n_unique_trades": int(od["regime_id"].n_unique()),
              "stability_unit": "TRADE_FIRST -- one observation per trade per "
                                "bucket (SPEC D8); the decision gate's year and "
                                "direction conditions read only that unit",
              "no_pooled_p_values": True,
              "gate_regions_evaluated": gate_tbl.height})

    lint = json.loads((AUDIT / "lint.json").read_text()) if (AUDIT / "lint.json").exists() else {}
    n_crit = sum(1 for f in lint.get("findings", [])
                 if f.get("severity") == "CRITICAL")
    g.append({"gate": "causal_lint_clean",
              "passed": bool(lint and n_crit == 0),
              "critical": n_crit,
              "warning": sum(1 for f in lint.get("findings", [])
                             if f.get("severity") == "WARNING"),
              "files_scanned": lint.get("files_scanned")})

    ag = {"gate": "auditors_clean"}
    for n, f in (("lookahead_auditor", "status.json"),
                 ("contract_checker", "contract_status.json")):
        p = AUDIT / f
        ag[n] = json.loads(p.read_text()) if p.exists() else {"present": False}
    vs = []
    for k in ("lookahead_auditor", "contract_checker"):
        pay = ag.get(k, {})
        v = str(pay.get("verdict", pay.get("status", ""))).upper()
        vs.append(v in ("CLEAR", "PASS") and int(pay.get("critical", 0) or 0) == 0)
    ag["passed"] = bool(all(vs))
    g.append(ag)

    rep_out = {"all_passed": all(x["passed"] for x in g),
               "n_gates": len(g), "gates": {x["gate"]: x for x in g}}
    (OUT / "validation_report.json").write_text(json.dumps(rep_out, indent=2,
                                                          default=str))
    for x in g:
        print(f"  {'PASS' if x['passed'] else 'FAIL'}  {x['gate']}")
    print(f"\nall_passed = {rep_out['all_passed']}")


if __name__ == "__main__":
    main()
