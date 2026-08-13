"""Phases 0-13: aggregate the panels into the frozen deliverable tables.

Nothing here recomputes a path. Every number is an aggregation of
`observation_panel.parquet` (trade x offset), `trade_panel.parquet` (per trade),
`harvest_panel.parquet` (trade x rung) or `placebo_panel.parquet` (per trade).

Two disciplines are enforced in every table, because both have previously been
the difference between a real finding and an artefact:

* `n_obs` AND `n_unique_trades`, always. 140,929 observations come from 4,656
  trades; a table that reports only the first invites a p-value nobody should
  believe.
* Year / direction stability is computed at TRADE level -- one observation per
  trade per bucket, the first entry into that bucket -- never by slicing the
  pooled observation panel.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl

from studies.model_driven_entry_exit_discovery.implementation.engine import NS
from ..implementation.engine import (
    ADV_LEVELS, DENSE_OFFSETS_S, FAV_LEVELS, HARVEST_RUNGS, RACE_PAIRS,
    RUNNER_TIERS, SPARSE_OFFSETS_S, tag,
)
from .buckets import (
    DD_BUCKETS, MFE_BUCKETS, PROGRESS3_BUCKETS, PROGRESS5_BUCKETS,
    STALL4_BUCKETS, STALL_BUCKETS, bootstrap_ci, grouped, metric_block,
    race_exprs, slices, with_buckets,
)

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "studies/post_confirm_forward_opportunity/results"
STORE = ROOT / "data/canonical/regime_complete_v1"
ARMED = ROOT / "studies/armed_fade_score_path_progression/results/armed_regime_score_paths.parquet"

ACCEPTED = {"entries": 8950, "confirmed": 4705, "stopped_before": 4245,
            "measurable": 4656, "non_measurable": 49,
            "pool_per_entry": 0.898, "baseline_per_entry": -0.0765}


def _write(df: pl.DataFrame, name: str, csv: bool = True) -> None:
    df.write_parquet(OUT / f"{name}.parquet")
    if csv:
        df.write_csv(OUT / f"{name}.csv")
    print(f"  {name}: {df.height:,} rows", flush=True)


# ------------------------------------------------------------------ phase 0

def reconciliation(td: pl.DataFrame) -> pl.DataFrame:
    armed = pl.read_parquet(ARMED).filter(pl.col("valid"))
    pre = armed.filter(pl.col("terminal_label_full") == "STOPPED_BEFORE_CONFIRM")
    n = armed.height
    flip = td.filter(pl.col("natural_kind") == "OPPOSING_FLIP")
    pool = float(flip["trade_nat_giveback_atr"].sum()) / n
    base = (float(td["trade_nat_net_atr"].sum())
            + float(pre["full_net_atr"].fill_null(0.0).sum())) / n
    rows = [
        ("original_top10_entries", n, ACCEPTED["entries"], 0.0),
        ("confirmed", 4705, ACCEPTED["confirmed"], 0.0),
        ("stopped_before_confirm", pre.height, ACCEPTED["stopped_before"], 0.0),
        ("measurable_confirmed_in_panel", td.height, ACCEPTED["measurable"], 0.0),
        ("non_measurable_confirmed", 4705 - td.height, ACCEPTED["non_measurable"], 0.0),
        ("giveback_pool_per_entry", pool, ACCEPTED["pool_per_entry"], 0.005),
        ("baseline_net_per_entry", base, ACCEPTED["baseline_per_entry"], 0.005),
    ]
    return pl.DataFrame([
        {"quantity": q, "observed": float(o), "accepted": float(a),
         "delta": float(o) - float(a), "tolerance": t,
         "passed": abs(float(o) - float(a)) <= t}
        for q, o, a, t in rows])


# ------------------------------------------------------------------ phase 1

def attrition(od: pl.DataFrame, n_trades: int) -> pl.DataFrame:
    """Constant denominator. Never let a late offset silently re-define 100%."""
    g = (od.group_by("offset_s").agg(
            alive=pl.len(),
            alive_stop_live=pl.col("alive_stop_live").sum(),
            median_state_mfe=pl.col("running_mfe_from_entry_atr").median(),
            median_fwd_mfe=pl.col("forward_mfe_atr").median(),
            median_fwd_mae=pl.col("forward_mae_atr").median(),
            mean_cv_stop_live=pl.col("cv_stop_live_atr").mean(),
            p_up050_b_dn050=(pl.col("race_0_5_before_0_5") == "FAVORABLE").mean(),
            label_p_ge3=pl.col("reached_3_0").mean())
         .sort("offset_s")
         .with_columns(eligible=pl.lit(n_trades),
                       terminal=pl.lit(n_trades) - pl.col("alive"),
                       attrition_pct=100.0 * (1 - pl.col("alive") / n_trades),
                       conditional_label=pl.lit("CONDITIONAL_ON_STILL_ALIVE")))
    return g.select("offset_s", "eligible", "alive", "terminal", "attrition_pct",
                    "alive_stop_live", "conditional_label",
                    *[c for c in g.columns if c.startswith(("median_", "mean_", "p_",
                                                            "label_"))])


# --------------------------------------------------------------- phases 3-4

def barrier_races(od: pl.DataFrame) -> pl.DataFrame:
    rows = []
    for pop, sub0 in (("ALL", od),
                      ("STOP_LIVE_ALIVE", od.filter(pl.col("alive_stop_live")))):
        for kind, name, sub in slices(sub0):
            if sub.height == 0:
                continue
            for f, a in RACE_PAIRS:
                c = f"race_{tag(f)}_before_{tag(a)}"
                fav = (pl.col(c) == "FAVORABLE")
                unres = (pl.col(c) == "UNRESOLVED")
                r = sub.select(
                    n_obs=pl.len(),
                    n_unique_trades=pl.col("regime_id").n_unique(),
                    p_favorable=fav.mean(),
                    p_adverse=(pl.col(c) == "ADVERSE").mean(),
                    p_unresolved=unres.mean(),
                    p_ambiguous=pl.col(c + "_ambiguous").mean(),
                    p_favorable_optimistic=(fav | pl.col(c + "_ambiguous")).mean(),
                    p_favorable_of_resolved=fav.sum() / (~unres).sum(),
                    median_secs_to_up=pl.col(f"secs_to_up_{tag(f)}").median(),
                    median_secs_to_dn=pl.col(f"secs_to_dn_{tag(a)}").median(),
                ).to_dicts()[0]
                rows.append({"population": pop, "slice_kind": kind, "slice": name,
                             "pair": f"+{f:.2f}_before_-{a:.2f}",
                             "fav_atr": f, "adv_atr": a, **r})
    return pl.DataFrame(rows)


EXCURSION_METRICS = ("forward_mfe_atr", "forward_mae_atr",
                     "forward_net_to_nat_exit_atr", "forward_net_to_unc_exit_atr",
                     "time_to_forward_mfe_s", "time_to_forward_mae_s",
                     "cv_stop_live_atr", "cv_unconstrained_atr")


def forward_excursion(od: pl.DataFrame) -> pl.DataFrame:
    rows = []
    for pop, sub0 in (("ALL", od),
                      ("STOP_LIVE_ALIVE", od.filter(pl.col("alive_stop_live")))):
        for kind, name, sub in slices(sub0):
            if sub.height == 0:
                continue
            for m in EXCURSION_METRICS:
                v = sub[m].drop_nulls().to_numpy().astype(float)
                v = v[np.isfinite(v)]
                rows.append({
                    "population": pop, "slice_kind": kind, "slice": name,
                    "metric": m, "n_obs": int(v.size),
                    "n_unique_trades": int(sub["regime_id"].n_unique()),
                    "mean": float(v.mean()) if v.size else None,
                    "median": float(np.median(v)) if v.size else None,
                    "p25": float(np.percentile(v, 25)) if v.size else None,
                    "p75": float(np.percentile(v, 75)) if v.size else None,
                    "p90": float(np.percentile(v, 90)) if v.size else None,
                })
    return pl.DataFrame(rows)


# --------------------------------------------------------------- phases 5-9

def stall_continuation(od: pl.DataFrame) -> pl.DataFrame:
    base = grouped(od, ["stall_bucket"], [STALL_BUCKETS]).with_columns(
        armed_only=pl.lit(False))
    armed = grouped(od.filter(pl.col("stall_armed")), ["stall_bucket"],
                    [STALL_BUCKETS]).with_columns(armed_only=pl.lit(True))
    return pl.concat([base, armed], how="vertical_relaxed")


def progress_continuation(od: pl.DataFrame) -> pl.DataFrame:
    frames = []
    for var, col in (("mark_progress_last_60s", "progress60_bucket"),
                     ("mark_progress_last_30s", "progress30_bucket")):
        g = grouped(od.filter(pl.col(col).is_not_null()), [col], [PROGRESS5_BUCKETS])
        frames.append(g.rename({col: "progress_bucket"}).with_columns(
            progress_var=pl.lit(var)))
    return pl.concat(frames, how="vertical_relaxed")


def progress_stall_matrix(od: pl.DataFrame) -> pl.DataFrame:
    sub = od.filter(pl.col("progress3_bucket").is_not_null())
    return grouped(sub, ["progress3_bucket", "stall4_bucket"],
                   [PROGRESS3_BUCKETS, STALL4_BUCKETS])


def mfe_state_continuation(od: pl.DataFrame) -> pl.DataFrame:
    """Phase 8: does the SAME stall mean different things at +0.5 vs +3 ATR?"""
    return grouped(od, ["mfe_bucket", "stall4_bucket"],
                   [MFE_BUCKETS, STALL4_BUCKETS])


def drawdown_state_continuation(od: pl.DataFrame) -> pl.DataFrame:
    crossed = grouped(od, ["dd_bucket", "stall4_bucket"],
                      [DD_BUCKETS, STALL4_BUCKETS])
    plain = (grouped(od, ["dd_bucket"], [DD_BUCKETS])
             .with_columns(stall4_bucket=pl.lit("ALL"))
             .select(crossed.columns))
    return pl.concat([plain, crossed], how="vertical_relaxed", rechunk=True)


# -------------------------------------------------------------- phase 10

BUCKET_KINDS = (("stall", "stall_bucket", STALL_BUCKETS),
                ("stall4", "stall4_bucket", STALL4_BUCKETS),
                ("progress60", "progress60_bucket", PROGRESS5_BUCKETS),
                ("progress3", "progress3_bucket", PROGRESS3_BUCKETS),
                ("mfe", "mfe_bucket", MFE_BUCKETS),
                ("drawdown", "dd_bucket", DD_BUCKETS),
                ("progress3_x_stall4", ("progress3_bucket", "stall4_bucket"), None),
                ("offset", "offset_s", None))


def _trade_first(od: pl.DataFrame, cols: list[str]) -> pl.DataFrame:
    """SPEC D8: one observation per trade per bucket -- the FIRST entry into it.

    This is what makes a year or direction slice interpretable. Slicing the
    pooled observation panel instead would weight a trade that sat in a bucket
    for nine minutes 36x more heavily than one that passed through it once.
    """
    return (od.sort("offset_s")
            .group_by(["regime_id", *cols], maintain_order=True)
            .first())


def continuation_value(od: pl.DataFrame) -> pl.DataFrame:
    rows = []
    for basis, cv, sub0 in (
            ("STOP_LIVE", "cv_stop_live_atr", od.filter(pl.col("alive_stop_live"))),
            ("UNCONSTRAINED", "cv_unconstrained_atr", od)):
        for bk, cols, _spec in BUCKET_KINDS:
            cols_l = [cols] if isinstance(cols, str) else list(cols)
            base = sub0.filter(pl.all_horizontal(
                [pl.col(c).is_not_null() for c in cols_l]))
            tf = _trade_first(base, cols_l)
            for unit, frame in (("OBSERVATION", base), ("TRADE_FIRST", tf)):
                for kind, name, sub in slices(frame):
                    if sub.height == 0:
                        continue
                    for key, grp in sub.group_by(cols_l, maintain_order=True):
                        v = grp[cv].drop_nulls().to_numpy().astype(float)
                        v = v[np.isfinite(v)]
                        if v.size == 0:
                            continue
                        lo = hi = None
                        if unit == "TRADE_FIRST":
                            lo, hi = bootstrap_ci(v)
                        rows.append({
                            "basis": basis, "unit": unit, "bucket_kind": bk,
                            "bucket": " | ".join(str(k) for k in key),
                            "slice_kind": kind, "slice": name,
                            "n_obs": int(grp.height),
                            "n_unique_trades": int(grp["regime_id"].n_unique()),
                            "mean_cv": float(v.mean()),
                            "median_cv": float(np.median(v)),
                            "p25_cv": float(np.percentile(v, 25)),
                            "p75_cv": float(np.percentile(v, 75)),
                            "pct_cv_negative": float((v < 0).mean()),
                            "ci_lo": lo, "ci_hi": hi,
                            "mean_exit_now_fill": float(grp["exit_now_fill_atr"].mean()),
                            "mean_fwd_mfe": float(grp["forward_mfe_atr"].mean()),
                            "p_up050_b_dn050": float(
                                (grp["race_0_5_before_0_5"] == "FAVORABLE").mean()),
                            "label_p_ge3": float(grp["reached_3_0"].mean()),
                        })
    return pl.DataFrame(rows)


# -------------------------------------------------------------- phase 11

def placebo_diagnosis(pp: pl.DataFrame) -> pl.DataFrame:
    cols = ("random_exit_return_atr", "blind_exit_return_atr",
            "opposing_flip_return_atr", "opposing_flip_return_unc_atr",
            "max_mfe_atr", "nat_max_mfe_atr", "d_random_minus_flip",
            "d_blind_minus_flip", "d_maxmfe_minus_random", "d_maxmfe_minus_flip",
            "net_random_atr", "net_blind_atr", "net_flip_atr",
            "secs_maxmfe_to_unc_terminal", "secs_maxmfe_to_nat_terminal",
            "giveback_after_max_unc_atr", "giveback_after_max_nat_atr")
    rows = []
    groups = [("POOLED", "ALL", pp)]
    groups += [("SIDE", s, pp.filter(pl.col("side") == s)) for s in ("LONG", "SHORT")]
    groups += [("YEAR", str(y), pp.filter(pl.col("entry_year") == y))
               for y in range(2021, 2026)]
    groups += [("RUNNER", b, pp.filter(pl.col("runner_bucket") == b))
               for b in ("R0", "R1", "R2", "R3")]
    groups += [("TERMINAL", k, pp.filter(pl.col("natural_kind") == k))
               for k in ("STOP", "OPPOSING_FLIP", "SESSION")]
    for kind, name, sub in groups:
        if sub.height == 0:
            continue
        r = {"slice_kind": kind, "slice": name, "n_trades": sub.height}
        for c in cols:
            r[f"mean_{c}"] = float(sub[c].mean())
            r[f"median_{c}"] = float(sub[c].median())
        r["pct_random_beats_flip"] = float(
            (sub["random_exit_return_atr"] > sub["opposing_flip_return_atr"]).mean())
        r["pct_blind_beats_flip"] = float(
            (sub["blind_exit_return_atr"] > sub["opposing_flip_return_atr"]).mean())
        rows.append(r)
    return pl.DataFrame(rows)


# -------------------------------------------------------------- phase 12

def harvest_geometry(hd: pl.DataFrame) -> pl.DataFrame:
    n_trades = hd["regime_id"].n_unique()
    rows = []
    groups = [("POOLED", "ALL", hd)]
    groups += [("SIDE", s, hd.filter(pl.col("side") == s)) for s in ("LONG", "SHORT")]
    groups += [("YEAR", str(y), hd.filter(pl.col("entry_year") == y))
               for y in range(2021, 2026)]
    for kind, name, sub in groups:
        if sub.height == 0:
            continue
        denom = sub["regime_id"].n_unique()
        for R in HARVEST_RUNGS:
            g = sub.filter(pl.col("rung_atr") == R)
            ach = g.filter(pl.col("achieved"))
            r = {"slice_kind": kind, "slice": name, "rung_atr": R,
                 "n_trades": denom, "n_achieved": ach.height,
                 "pct_achieved": 100.0 * ach.height / max(denom, 1),
                 "pct_achieved_pre_confirm": (
                     100.0 * float(ach["achieved_pre_confirm"].mean())
                     if ach.height else None),
                 "pct_stop_live_reachable": (
                     100.0 * float(ach["stop_live_reachable"].mean())
                     if ach.height else None)}
            if ach.height:
                for step in ("0_5", "1_0"):
                    nxt = ach.filter(pl.col(f"next_{step}_reached"))
                    r[f"p_next_{step}"] = ach[f"next_{step}_reached"].mean()
                    r[f"secs_to_next_{step}_median"] = (
                        float(nxt[f"next_{step}_secs"].median()) if nxt.height else None)
                    for q, lbl in ((0.50, "median"), (0.75, "p75"), (0.90, "p90")):
                        r[f"mae_before_next_{step}_{lbl}"] = (
                            float(nxt[f"next_{step}_mae_before_atr"].quantile(q))
                            if nxt.height else None)
                r["mae_after_rung_to_terminal_median"] = float(
                    ach["mae_after_rung_to_terminal_atr"].median())
                for v in ("a", "b", "c"):
                    r[f"blended_net_variant_{v}"] = float(
                        ach[f"blended_net_variant_{v}_atr"].mean())
                    r[f"retained_return_variant_{v}"] = float(
                        ach[f"retained_return_variant_{v}_atr"].mean())
                r["harvest_unit_return"] = float(ach["harvest_unit_return_atr"].mean())
                r["full_size_net_atr"] = float(ach["full_size_net_atr"].mean())
                # per ORIGINAL entry, the denominator that decides anything
                r["delta_per_original_entry_variant_a"] = float(
                    (ach["blended_net_variant_a_atr"]
                     - ach["full_size_net_atr"]).sum()) / 8950
                r["delta_per_original_entry_variant_b"] = float(
                    (ach["blended_net_variant_b_atr"]
                     - ach["full_size_net_atr"]).sum()) / 8950
                r["delta_per_original_entry_variant_c"] = float(
                    (ach["blended_net_variant_c_atr"]
                     - ach["full_size_net_atr"]).sum()) / 8950
            rows.append(r)
    return pl.DataFrame(rows, infer_schema_length=None)


# -------------------------------------------------------------- phase 13

def model_additivity(od: pl.DataFrame) -> pl.DataFrame:
    """EXPLORATORY_OUT_OF_DOMAIN. Within a matched price-state cell only.

    The score stream is the raw causal new-regime model dispatch. Carry-forward
    reads a LEVEL at the observation; a crossing is never inferred from a carried
    value, and an observation with no dispatch at or before it stays null.
    """
    from studies.top10_fast_confirm_runner_path.implementation.build import (
        confirmed_population,
    )
    conf = confirmed_population().select("regime_id", "new_regime_id", "direction")
    sc = (pl.scan_parquet(STORE / "canonical_regime_scores_all.parquet")
          .filter(pl.col("session") == "RTH")
          .select("regime_id", "checkpoint_decision_ns",
                  "bullish_probability", "bearish_probability").collect()
          .join(conf, left_on="regime_id", right_on="new_regime_id", how="inner",
                suffix="_trade")
          .with_columns(score=pl.when(pl.col("direction") == 1)
                        .then(pl.col("bullish_probability"))
                        .otherwise(pl.col("bearish_probability")))
          .filter(pl.col("score").is_not_null())
          .select(regime_id="regime_id_trade",
                  checkpoint_decision_ns="checkpoint_decision_ns", score="score")
          .sort("checkpoint_decision_ns"))
    if sc.height == 0:
        return pl.DataFrame()

    keys = (od.select("regime_id", "obs_ns", "offset_s", "progress3_bucket",
                      "stall4_bucket", "race_0_5_before_0_5", "race_1_0_before_0_5",
                      "cv_stop_live_atr", "alive_stop_live", "entry_year", "side",
                      "forward_mfe_atr")
            .sort("obs_ns"))
    j = keys.join_asof(sc, left_on="obs_ns", right_on="checkpoint_decision_ns",
                       by="regime_id", strategy="backward")
    n_null = int(j["score"].is_null().sum())

    j = j.filter(pl.col("progress3_bucket").is_not_null()
                 & pl.col("stall4_bucket").is_not_null())
    # split at the WITHIN-CELL median, so the comparison is never a proxy for
    # which cell the observation is in
    j = j.with_columns(
        cell_median=pl.col("score").median().over(["progress3_bucket", "stall4_bucket"]))
    j = j.with_columns(score_half=pl.when(pl.col("score").is_null())
                       .then(pl.lit(None, dtype=pl.String))
                       .when(pl.col("score") <= pl.col("cell_median"))
                       .then(pl.lit("LOW")).otherwise(pl.lit("HIGH")))

    rows = []
    for kind, name, sub in slices(j):
        if sub.height == 0:
            continue
        for key, grp in sub.group_by(
                ["progress3_bucket", "stall4_bucket", "score_half"],
                maintain_order=True):
            rows.append({
                "slice_kind": kind, "slice": name,
                "progress3_bucket": key[0], "stall4_bucket": key[1],
                "score_half": key[2] if key[2] is not None else "NULL",
                "n_obs": grp.height,
                "n_unique_trades": grp["regime_id"].n_unique(),
                "median_score": float(grp["score"].median())
                if grp["score"].drop_nulls().len() else None,
                "p_up050_b_dn050": float(
                    (grp["race_0_5_before_0_5"] == "FAVORABLE").mean()),
                "p_up100_b_dn050": float(
                    (grp["race_1_0_before_0_5"] == "FAVORABLE").mean()),
                "mean_cv": float(grp["cv_stop_live_atr"].mean())
                if grp["cv_stop_live_atr"].drop_nulls().len() else None,
                "mean_fwd_mfe": float(grp["forward_mfe_atr"].mean()),
                "domain": "EXPLORATORY_OUT_OF_DOMAIN",
                "n_null_total": n_null,
            })
    return pl.DataFrame(rows, infer_schema_length=None)


# ------------------------------------------------------------------ driver

def main() -> None:
    td = pl.read_parquet(OUT / "trade_panel.parquet")
    od = with_buckets(pl.read_parquet(OUT / "observation_panel.parquet"))
    xd = with_buckets(pl.read_parquet(OUT / "extended_horizon.parquet"))
    hd = pl.read_parquet(OUT / "harvest_panel.parquet")
    pp = pl.read_parquet(OUT / "placebo_panel.parquet")
    od.write_parquet(OUT / "observation_panel.parquet")     # persist buckets

    print("phase 0-1 ...", flush=True)
    _write(reconciliation(td), "population_reconciliation")
    _write(attrition(od, td.height), "observation_attrition")
    print("phase 3-4 ...", flush=True)
    _write(barrier_races(od), "forward_barrier_races")
    _write(forward_excursion(od), "forward_excursion")
    print("phase 5-9 ...", flush=True)
    _write(stall_continuation(od), "stall_continuation")
    _write(progress_continuation(od), "progress_continuation")
    _write(progress_stall_matrix(od), "progress_stall_matrix")
    _write(mfe_state_continuation(od), "mfe_state_continuation")
    _write(drawdown_state_continuation(od), "drawdown_state_continuation")
    print("phase 10 ...", flush=True)
    _write(continuation_value(od), "exit_now_continuation_value")
    print("phase 11-12 ...", flush=True)
    _write(placebo_diagnosis(pp), "placebo_diagnosis")
    _write(harvest_geometry(hd), "harvest_geometry")
    print("phase 13 + extended ...", flush=True)
    ma = model_additivity(od)
    if ma.height:
        _write(ma, "model_additivity")
    ext = attrition(xd, td.height).with_columns(
        horizon=pl.lit("SPARSE_EXTENDED"),
        disclosure=pl.lit("SPEC D2 -- NOT pooled into any primary table"))
    _write(ext, "extended_horizon_summary")
    xd.write_parquet(OUT / "extended_horizon.parquet")
    xd.write_csv(OUT / "extended_horizon.csv")      # Manifest #13 CSV mirror
    print("done", flush=True)


if __name__ == "__main__":
    main()
