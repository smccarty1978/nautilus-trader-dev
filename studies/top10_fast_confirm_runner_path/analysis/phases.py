"""Phases 0-11: aggregate the panels into the frozen deliverable tables.

Nothing here recomputes a path. Every number is an aggregation of
``trade_panel.parquet`` (one row per confirmed trade) or
``time_landmark_states.parquet`` (one row per fast trade x landmark), so a
descriptive table can never disagree with the causal walk that produced it.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl

from studies.model_driven_entry_exit_discovery.implementation.engine import NS
from ..implementation.engine import (
    ADD_MFE_LEVELS, GIVEBACK_LEVELS, KEY_LANDMARKS_S, LANDMARKS_S, RUNNER_TIERS,
    STALL_S, STATE_VARS,
)

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "studies/top10_fast_confirm_runner_path/results"
ARMED = ROOT / "studies/armed_fade_score_path_progression/results/armed_regime_score_paths.parquet"

COHORTS = ("FAST_0_60", "FAST_61_120", "SLOW_121_300", "VERY_SLOW_GT300")
ACCEPTED = {"entries": 8950, "confirmed": 4705, "stopped_before": 4245,
            "pool_per_entry": 0.899, "baseline_per_entry": -0.0742}
# SPEC 8: the frozen separation gate.
AUC_LIFT_BAR = 0.10
QUINTILES = 5


def _tag(x: float) -> str:
    return str(x).replace(".", "_")


def _stats(v: np.ndarray, name: str, group: str, extra: dict | None = None) -> dict:
    v = v[np.isfinite(v)]
    row = {"group": group, "metric": name, "n": int(v.size)}
    if v.size:
        row |= {"mean": float(v.mean()), "median": float(np.median(v)),
                "p25": float(np.percentile(v, 25)), "p75": float(np.percentile(v, 75)),
                "p90": float(np.percentile(v, 90))}
    else:
        row |= {"mean": None, "median": None, "p25": None, "p75": None, "p90": None}
    return row | (extra or {})


def auc(score: np.ndarray, label: np.ndarray) -> float | None:
    """Mann-Whitney AUC with tie correction. label 1 = positive class."""
    ok = np.isfinite(score)
    s, y = score[ok], label[ok]
    npos, nneg = int((y == 1).sum()), int((y == 0).sum())
    if npos == 0 or nneg == 0:
        return None
    order = np.argsort(s, kind="mergesort")
    ranks = np.empty(s.size, dtype=float)
    sr = s[order]
    i = 0
    while i < sr.size:
        j = i
        while j + 1 < sr.size and sr[j + 1] == sr[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return float((ranks[y == 1].sum() - npos * (npos + 1) / 2.0) / (npos * nneg))


# ---------------------------------------------------------------- phase 0/1

def reconciliation(td: pl.DataFrame) -> pl.DataFrame:
    armed = pl.read_parquet(ARMED).filter(pl.col("valid"))
    pre = armed.filter(pl.col("terminal_label_full") == "STOPPED_BEFORE_CONFIRM")
    n_entries = armed.height
    flip = td.filter(pl.col("natural_kind") == "OPPOSING_FLIP")
    pool = float(flip["natural_giveback_atr"].sum()) / n_entries
    base = (float(td["natural_net_atr"].sum())
            + float(pre["full_net_atr"].fill_null(0.0).sum())) / n_entries
    rows = [
        ("original_top10_entries", n_entries, ACCEPTED["entries"], 0.0),
        ("confirmed", 4705, ACCEPTED["confirmed"], 0.0),
        ("stopped_before_confirm", pre.height, ACCEPTED["stopped_before"], 0.0),
        ("measurable_confirmed_in_panel", td.height, 4656, 0.0),
        ("non_measurable_confirmed", 4705 - td.height, 49, 0.0),
        ("giveback_pool_per_entry", pool, ACCEPTED["pool_per_entry"], 0.005),
        ("baseline_net_per_entry", base, ACCEPTED["baseline_per_entry"], 0.005),
    ]
    return pl.DataFrame([
        {"quantity": q, "observed": float(o), "accepted": float(a),
         "delta": float(o) - float(a), "tolerance": tol,
         "passed": abs(float(o) - float(a)) <= tol}
        for q, o, a, tol in rows])


def cohorts_table(td: pl.DataFrame) -> pl.DataFrame:
    rows = []
    n_conf, n_entries = 4705, ACCEPTED["entries"]
    for c in COHORTS + ("FAST_CONFIRM_120", "SLOW_CONFIRM_GT120", "ALL_CONFIRMED"):
        if c == "FAST_CONFIRM_120":
            s = td.filter(pl.col("is_fast_confirm"))
        elif c == "SLOW_CONFIRM_GT120":
            s = td.filter(~pl.col("is_fast_confirm"))
        elif c == "ALL_CONFIRMED":
            s = td
        else:
            s = td.filter(pl.col("cohort") == c)
        r = {"cohort": c, "n": s.height,
             "pct_of_confirmed": 100.0 * s.height / n_conf,
             "pct_of_entries": 100.0 * s.height / n_entries,
             "n_long": s.filter(pl.col("side") == "LONG").height,
             "n_short": s.filter(pl.col("side") == "SHORT").height,
             "mean_natural_net_atr": float(s["natural_net_atr"].mean()) if s.height else None,
             "median_natural_net_atr": float(s["natural_net_atr"].median()) if s.height else None,
             "on_120s_boundary": int(s["on_120s_boundary"].sum())}
        for y in range(2021, 2026):
            r[f"n_{y}"] = s.filter(pl.col("entry_year") == y).height
        for T in RUNNER_TIERS:
            r[f"p_ge_{_tag(T)}"] = (float(s[f"reached_{_tag(T)}"].mean())
                                    if s.height else None)
        rows.append(r)
    return pl.DataFrame(rows)


# ------------------------------------------------------------ phases 2/3/4

CONFIRM_METRICS = ("seconds_to_confirm", "return_at_confirm_atr",
                   "mfe_to_confirm_atr", "mae_to_confirm_atr",
                   "capture_at_confirm")
POST_METRICS = ("additional_mfe_after_confirm_atr", "eventual_max_mfe_atr",
                "seconds_confirm_to_maxmfe", "seconds_confirm_to_unc_exit",
                "unc_return_atr", "unc_giveback_atr", "unc_capture",
                "frac_maxmfe_at_confirm", "natural_return_atr",
                "natural_giveback_atr", "natural_capture")


def _by_cohort(td: pl.DataFrame, metrics) -> pl.DataFrame:
    td = td.with_columns(
        capture_at_confirm=pl.when(pl.col("mfe_to_confirm_atr") >= 0.10)
        .then(pl.col("return_at_confirm_atr") / pl.col("mfe_to_confirm_atr"))
        .otherwise(None))
    rows = []
    for c in COHORTS + ("FAST_CONFIRM_120", "SLOW_CONFIRM_GT120", "ALL_CONFIRMED"):
        if c == "FAST_CONFIRM_120":
            s = td.filter(pl.col("is_fast_confirm"))
        elif c == "SLOW_CONFIRM_GT120":
            s = td.filter(~pl.col("is_fast_confirm"))
        elif c == "ALL_CONFIRMED":
            s = td
        else:
            s = td.filter(pl.col("cohort") == c)
        for m in metrics:
            rows.append(_stats(s[m].cast(pl.Float64).to_numpy().astype(float), m, c))
    return pl.DataFrame(rows)


def runner_buckets(fast: pl.DataFrame) -> pl.DataFrame:
    rows = []
    groups = [(b, fast.filter(pl.col("runner_bucket") == b))
              for b in ("R0", "R1", "R2", "R3")]
    groups += [(f"TIER_ge_{_tag(T)}", fast.filter(pl.col(f"reached_{_tag(T)}")))
               for T in RUNNER_TIERS]
    groups += [("ALL_FAST", fast)]
    for name, s in groups:
        if s.height == 0:
            rows.append({"bucket": name, "n": 0})
            continue
        rows.append({
            "bucket": name, "n": s.height, "pct": 100.0 * s.height / fast.height,
            "mean_eventual_max_mfe": float(s["eventual_max_mfe_atr"].mean()),
            "median_eventual_max_mfe": float(s["eventual_max_mfe_atr"].median()),
            "mean_mfe_at_confirm": float(s["mfe_to_confirm_atr"].mean()),
            "median_frac_maxmfe_at_confirm": float(s["frac_maxmfe_at_confirm"].median()),
            "mean_additional_mfe_after_confirm": float(
                s["additional_mfe_after_confirm_atr"].mean()),
            "mean_natural_return_atr": float(s["natural_return_atr"].mean()),
            "median_natural_return_atr": float(s["natural_return_atr"].median()),
            "mean_natural_net_atr": float(s["natural_net_atr"].mean()),
            "mean_natural_giveback_atr": float(s["natural_giveback_atr"].mean()),
            "median_natural_capture": (float(s["natural_capture"].median())
                                       if s["natural_capture"].drop_nulls().len() else None),
            "mean_unc_return_atr": float(s["unc_return_atr"].mean()),
            "mean_unc_giveback_atr": float(s["unc_giveback_atr"].mean()),
            "pct_stopped_after_confirm": 100.0 * s.filter(
                pl.col("natural_kind") == "STOP").height / s.height,
            "median_seconds_confirm_to_maxmfe": float(
                s["seconds_confirm_to_maxmfe"].median()),
        })
    return pl.DataFrame(rows, infer_schema_length=None)


# ---------------------------------------------------------------- phase 7/8

def giveback_geometry(fast: pl.DataFrame) -> pl.DataFrame:
    rows = []
    n = fast.height
    for lvl in GIVEBACK_LEVELS:
        t = f"gb{_tag(lvl)}"
        s = fast.filter(pl.col(f"{t}_reached"))
        r = {"level_atr": lvl, "n": s.height, "n_fast": n,
             "pct_reaching": 100.0 * s.height / n}
        if s.height:
            r |= {
                "median_secs_from_confirm": float(s[f"{t}_secs_from_confirm"].median()),
                "mean_mfe_at_event": float(s[f"{t}_mfe_at_event"].mean()),
                "median_mfe_at_event": float(s[f"{t}_mfe_at_event"].median()),
                "mean_eventual_max_mfe": float(s["eventual_max_mfe_atr"].mean()),
                "median_eventual_max_mfe": float(s["eventual_max_mfe_atr"].median()),
                "mean_remaining_mfe": float(s[f"{t}_remaining_mfe"].mean()),
                "median_remaining_mfe": float(s[f"{t}_remaining_mfe"].median()),
                "p_new_extreme": float(s[f"{t}_new_extreme_after"].mean()),
                "mean_natural_return_atr": float(s["natural_return_atr"].mean()),
            }
            for a in ADD_MFE_LEVELS:
                r[f"p_add_{_tag(a)}"] = float(s[f"{t}_added_{_tag(a)}"].mean())
            for T in RUNNER_TIERS:
                r[f"p_ge_{_tag(T)}"] = float(s[f"reached_{_tag(T)}"].mean())
        r["raw_pct_reaching"] = 100.0 * float(fast[f"gbraw{_tag(lvl)}_reached"].mean())
        r["definition"] = "ARMED: requires ext >= level (raw shown for contrast)"
        rows.append(r)
    # unconditional reference row
    ref = {"level_atr": None, "n": n, "n_fast": n, "pct_reaching": 100.0,
           "mean_eventual_max_mfe": float(fast["eventual_max_mfe_atr"].mean()),
           "median_eventual_max_mfe": float(fast["eventual_max_mfe_atr"].median()),
           "mean_natural_return_atr": float(fast["natural_return_atr"].mean())}
    for T in RUNNER_TIERS:
        ref[f"p_ge_{_tag(T)}"] = float(fast[f"reached_{_tag(T)}"].mean())
    rows.append(ref)
    return pl.DataFrame(rows, infer_schema_length=None)


def stall_geometry(fast: pl.DataFrame) -> pl.DataFrame:
    rows = []
    n = fast.height
    for W in STALL_S:
        t = f"st{W}"
        s = fast.filter(pl.col(f"{t}_reached"))
        r = {"stall_s": W, "n": s.height, "n_fast": n,
             "pct_reaching": 100.0 * s.height / n}
        if s.height:
            r |= {
                "median_secs_from_confirm": float(s[f"{t}_secs_from_confirm"].median()),
                "mean_ret": float(s[f"{t}_ret"].mean()),
                "median_ret": float(s[f"{t}_ret"].median()),
                "mean_mfe": float(s[f"{t}_mfe"].mean()),
                "median_mfe": float(s[f"{t}_mfe"].median()),
                "mean_dd": float(s[f"{t}_dd"].mean()),
                "median_dd": float(s[f"{t}_dd"].median()),
                "mean_additional_mfe": float(s[f"{t}_additional_mfe"].mean()),
                "median_additional_mfe": float(s[f"{t}_additional_mfe"].median()),
                "p_new_extreme": float(s[f"{t}_new_extreme_after"].mean()),
                "mean_natural_return_atr": float(s["natural_return_atr"].mean()),
            }
            for T in RUNNER_TIERS:
                r[f"p_ge_{_tag(T)}"] = float(s[f"reached_{_tag(T)}"].mean())
        r["raw_pct_reaching"] = 100.0 * float(fast[f"straw{W}_reached"].mean())
        r["definition"] = "ARMED: clock runs from a post-confirm new favorable extreme"
        rows.append(r)
    ref = {"stall_s": None, "n": n, "n_fast": n, "pct_reaching": 100.0,
           "mean_additional_mfe": float(fast["additional_mfe_after_confirm_atr"].mean()),
           "mean_natural_return_atr": float(fast["natural_return_atr"].mean())}
    for T in RUNNER_TIERS:
        ref[f"p_ge_{_tag(T)}"] = float(fast[f"reached_{_tag(T)}"].mean())
    rows.append(ref)
    return pl.DataFrame(rows, infer_schema_length=None)


# ------------------------------------------------------------- phases 6/9/11

def landmark_contrast(sd: pl.DataFrame) -> pl.DataFrame:
    """Phase 6: causal state by retrospective outcome class, at every landmark."""
    rows = []
    classes = {
        "GE_3": pl.col("eventual_max_mfe_atr") >= 3.0,
        "GE_2_5": pl.col("eventual_max_mfe_atr") >= 2.5,
        "LT_2": pl.col("eventual_max_mfe_atr") < 2.0,
        "ALL": pl.lit(True),
    }
    for L in LANDMARKS_S:
        base = sd.filter(pl.col("landmark_s") == L)
        for cname, expr in classes.items():
            for pop, p in (("constant", base), ("alive_only", base.filter(pl.col("alive")))):
                s = p.filter(expr)
                for v in STATE_VARS:
                    if v in ("made_new_extreme",):
                        arr = s[v].cast(pl.Float64).to_numpy().astype(float)
                    else:
                        arr = s[v].cast(pl.Float64).to_numpy().astype(float)
                    rows.append(_stats(arr, v, f"{cname}|{pop}",
                                       {"landmark_s": L, "outcome_class": cname,
                                        "population": pop,
                                        "pct_alive": 100.0 * float(base["alive"].mean())}))
    return pl.DataFrame(rows)


def discrimination(sd: pl.DataFrame) -> pl.DataFrame:
    """Phase 11: single-variable AUC, >=3 ATR runner vs <2 ATR outcome.

    Three populations. ``undetermined`` is the one that decides the gate:

    eventual MaxMFE >= running MFE at any landmark by construction, so a trade
    already showing ``run_mfe_entry >= 2.0`` CANNOT be in the ``<2 ATR`` class --
    it is a guaranteed positive. Scoring those trades measures the definition,
    not the path. They are 6.8 / 9.5 / 17.7% of the labelled set at 30/60/120 s
    and 100% of them are positives, exactly as the containment argument predicts.
    ``undetermined`` drops them, so every remaining trade could still finish in
    either class and the AUC is a genuine forecast.
    """
    rows = []
    for L in KEY_LANDMARKS_S:
        base = sd.filter(pl.col("landmark_s") == L)
        for pop, p in (("constant", base),
                       ("alive_only", base.filter(pl.col("alive"))),
                       ("undetermined", base.filter(pl.col("run_mfe_entry") < 2.0))):
            lab = p.filter((pl.col("eventual_max_mfe_atr") >= 3.0)
                           | (pl.col("eventual_max_mfe_atr") < 2.0))
            y = (lab["eventual_max_mfe_atr"] >= 3.0).cast(pl.Int8).to_numpy()
            for v in STATE_VARS:
                x = lab[v].cast(pl.Float64).to_numpy().astype(float)
                a = auc(x, y)
                if a is None:
                    continue
                # quintile monotonicity on the outcome rate
                ok = np.isfinite(x)
                mono, tbl = None, []
                if ok.sum() >= QUINTILES * 10:
                    q = np.quantile(x[ok], np.linspace(0, 1, QUINTILES + 1))
                    q[0], q[-1] = -np.inf, np.inf
                    idx = np.clip(np.digitize(x[ok], q[1:-1]), 0, QUINTILES - 1)
                    rate = [float(y[ok][idx == b].mean()) if (idx == b).any() else np.nan
                            for b in range(QUINTILES)]
                    tbl = rate
                    r = np.array(rate)
                    if np.isfinite(r).all():
                        d = np.diff(r)
                        mono = bool((d >= -1e-9).all() or (d <= 1e-9).all())
                # year consistency: same sign of (AUC - 0.5) in >= 4 of 5 years
                signs = []
                for yr in range(2021, 2026):
                    m = lab.filter(pl.col("entry_year") == yr)
                    ay = auc(m[v].cast(pl.Float64).to_numpy().astype(float),
                             (m["eventual_max_mfe_atr"] >= 3.0).cast(pl.Int8).to_numpy())
                    if ay is not None:
                        signs.append(np.sign(ay - 0.5))
                agree = max(signs.count(1.0), signs.count(-1.0)) if signs else 0
                rows.append({
                    "landmark_s": L, "variable": v, "population": pop,
                    "n_pos": int((y == 1).sum()), "n_neg": int((y == 0).sum()),
                    "n_finite": int(ok.sum()),
                    "auc": a, "auc_abs_lift": abs(a - 0.5),
                    "bucket_table_monotonic": mono,
                    # flattened: a nested column cannot be mirrored to CSV, and
                    # the quintile table is report-critical evidence
                    **{f"q{b + 1}_rate": (float(tbl[b]) if b < len(tbl) else None)
                       for b in range(QUINTILES)},
                    "years_consistent": int(agree),
                    "gate_open": bool(abs(a - 0.5) >= AUC_LIFT_BAR
                                      and mono is True and agree >= 4),
                })
    return pl.DataFrame(rows, infer_schema_length=None)


def progress_matrix(sd: pl.DataFrame, fast: pl.DataFrame) -> pl.DataFrame:
    """Phase 9: 3 x 3 progress x drawdown cells. Descriptive, not a policy."""
    rows = []
    nat = fast.select("regime_id", "natural_return_atr", "eventual_max_mfe_atr",
                      *[f"reached_{_tag(T)}" for T in RUNNER_TIERS])
    for L in KEY_LANDMARKS_S:
        base = (sd.filter(pl.col("landmark_s") == L)
                .join(nat, on="regime_id", how="left", suffix="_t"))
        prog = base["ret_since_confirm"].to_numpy()
        q1, q2 = np.quantile(prog, [1 / 3, 2 / 3])
        pbin = np.where(prog <= q1, "low", np.where(prog <= q2, "medium", "high"))
        dd = base["dd_from_run_max"].to_numpy()
        dbin = np.where(dd < 0.25, "<0.25", np.where(dd <= 0.50, "0.25-0.50", ">0.50"))
        base = base.with_columns(progress_bin=pl.Series(pbin), dd_bin=pl.Series(dbin))
        for pb in ("low", "medium", "high"):
            for db in ("<0.25", "0.25-0.50", ">0.50"):
                s = base.filter((pl.col("progress_bin") == pb) & (pl.col("dd_bin") == db))
                r = {"landmark_s": L, "progress_bin": pb, "dd_bin": db, "n": s.height,
                     "progress_q33": float(q1), "progress_q67": float(q2)}
                if s.height:
                    r |= {"mean_additional_mfe": float(
                              (s["eventual_max_mfe_atr"] - s["run_mfe_entry"]).mean()),
                          "median_additional_mfe": float(
                              (s["eventual_max_mfe_atr"] - s["run_mfe_entry"]).median()),
                          "mean_natural_return_atr": float(s["natural_return_atr"].mean()),
                          "pct_alive": 100.0 * float(s["alive"].mean())}
                    for T in RUNNER_TIERS:
                        r[f"p_ge_{_tag(T)}"] = float(s[f"reached_{_tag(T)}"].mean())
                rows.append(r)
    return pl.DataFrame(rows, infer_schema_length=None)


def model_context(sd: pl.DataFrame) -> pl.DataFrame:
    """Phase 10: raw causal new-regime score. EXPLORATORY_OUT_OF_DOMAIN."""
    p = OUT / "model_context_raw.parquet"
    if not p.exists():
        return pl.DataFrame()
    mc = (pl.read_parquet(p)
          .join(sd.select("regime_id", "landmark_s", "eventual_max_mfe_atr", "alive"),
                on=["regime_id", "landmark_s"], how="left"))
    rows = []
    for L in LANDMARKS_S:
        s = mc.filter(pl.col("landmark_s") == L)
        lab = s.filter((pl.col("eventual_max_mfe_atr") >= 3.0)
                       | (pl.col("eventual_max_mfe_atr") < 2.0))
        y = (lab["eventual_max_mfe_atr"] >= 3.0).cast(pl.Int8).to_numpy()
        for m in ("score", "delta_score_since_confirm"):
            r = _stats(s[m].cast(pl.Float64).to_numpy().astype(float), m, f"L{L}",
                       {"landmark_s": L,
                        "n_null": int(s[m].is_null().sum()),
                        "domain": "EXPLORATORY_OUT_OF_DOMAIN"})
            r["auc_ge3_vs_lt2"] = auc(lab[m].cast(pl.Float64).to_numpy().astype(float), y)
            r["auc_abs_lift"] = (abs(r["auc_ge3_vs_lt2"] - 0.5)
                                 if r["auc_ge3_vs_lt2"] is not None else None)
            rows.append(r)
        for m in ("p90_reached", "p80_reached"):
            r = _stats(s[m].cast(pl.Float64).to_numpy().astype(float), m, f"L{L}",
                       {"landmark_s": L, "n_null": int(s[m].is_null().sum()),
                        "domain": "EXPLORATORY_OUT_OF_DOMAIN"})
            r["auc_ge3_vs_lt2"] = auc(lab[m].cast(pl.Float64).to_numpy().astype(float), y)
            r["auc_abs_lift"] = (abs(r["auc_ge3_vs_lt2"] - 0.5)
                                 if r["auc_ge3_vs_lt2"] is not None else None)
            rows.append(r)
    return pl.DataFrame(rows, infer_schema_length=None)


# ------------------------------------------------------------------- driver

def cohort_test(td: pl.DataFrame) -> dict:
    """SPEC 8: is FAST_CONFIRM_120 an economically superior population?"""
    fast, slow = td.filter(pl.col("is_fast_confirm")), td.filter(~pl.col("is_fast_confirm"))
    years = []
    for y in range(2021, 2026):
        f, s = fast.filter(pl.col("entry_year") == y), slow.filter(pl.col("entry_year") == y)
        years.append({
            "year": y,
            "fast_net": float(f["natural_net_atr"].mean()),
            "slow_net": float(s["natural_net_atr"].mean()),
            "fast_p_ge3": float(f["reached_3_0"].mean()),
            "slow_p_ge3": float(s["reached_3_0"].mean()),
            "net_better": bool(f["natural_net_atr"].mean() > s["natural_net_atr"].mean()),
            "p_ge3_better": bool(f["reached_3_0"].mean() > s["reached_3_0"].mean()),
        })
    both = sum(1 for y in years if y["net_better"] and y["p_ge3_better"])
    return {
        "fast_n": fast.height, "slow_n": slow.height,
        "fast_mean_net_atr": float(fast["natural_net_atr"].mean()),
        "slow_mean_net_atr": float(slow["natural_net_atr"].mean()),
        "fast_p_ge3": float(fast["reached_3_0"].mean()),
        "slow_p_ge3": float(slow["reached_3_0"].mean()),
        "years_both_better": both,
        "passed": bool(both >= 4),
        "by_year": years,
    }


def main() -> None:
    td = pl.read_parquet(OUT / "trade_panel.parquet")
    sd = pl.read_parquet(OUT / "time_landmark_states.parquet")
    fast = td.filter(pl.col("is_fast_confirm"))

    tables = {
        "population_reconciliation": reconciliation(td),
        "confirm_speed_cohorts": cohorts_table(td),
        "confirmation_geometry": _by_cohort(td, CONFIRM_METRICS),
        "post_confirm_opportunity": _by_cohort(td, POST_METRICS),
        "runner_buckets": runner_buckets(fast),
        "giveback_geometry": giveback_geometry(fast),
        "stall_geometry": stall_geometry(fast),
        "landmark_contrast": landmark_contrast(sd),
        "progress_retracement_matrix": progress_matrix(sd, fast),
        "single_variable_discrimination": discrimination(sd),
        "model_context": model_context(sd),
    }
    for name, df in tables.items():
        if df.height == 0:
            print(f"  SKIP empty {name}")
            continue
        df.write_parquet(OUT / f"{name}.parquet")
        if name != "landmark_contrast":
            df.write_csv(OUT / f"{name}.csv")
        print(f"  {name}: {df.height} rows")
    tables["landmark_contrast"].write_csv(OUT / "landmark_contrast.csv")

    # Preserve any Phase-12 / close-out block already on disk. Writing
    # `phase12_ran: False` unconditionally silently reverted a completed Phase 12
    # whenever this module was re-run (contract-checker pass 1, BLOCKING).
    prior = {}
    if (OUT / "summary.json").exists():
        prior = json.loads((OUT / "summary.json").read_text())

    disc = tables["single_variable_discrimination"]
    # SPEC 8 as amended 2026-08-10: the gate is judged on `undetermined`, the
    # mechanical-containment control, not on `constant`. This TIGHTENS the frozen
    # criterion; it opens under both populations, so the amendment cannot have
    # manufactured the verdict.
    gate = disc.filter(pl.col("gate_open") & (pl.col("population") == "undetermined"))
    ct = cohort_test(td)
    summary = {
        "study": "top10_fast_confirm_runner_path",
        "fast_confirm_n": fast.height,
        "cohort_test": ct,
        "separation_gate": {
            "criterion": f"|AUC-0.5| >= {AUC_LIFT_BAR} AND quintile-monotonic "
                         f"AND same sign in >= 4 of 5 years, on the UNDETERMINED "
                         f"population (run_mfe < 2.0 at the landmark)",
            "n_variables_passing": gate.height,
            "open": bool(gate.height > 0),
            "n_passing_constant": disc.filter(
                pl.col("gate_open") & (pl.col("population") == "constant")).height,
            "best": (disc.filter(pl.col("population") == "undetermined")
                     .sort("auc_abs_lift", descending=True)
                     .head(5).select("landmark_s", "variable", "auc", "auc_abs_lift",
                                     "bucket_table_monotonic", "years_consistent")
                     .to_dicts()),
        },
        "phase12_ran": prior.get("phase12_ran", False),
    }
    for k in ("phase12", "report_answers", "final_classification"):
        if k in prior:
            summary[k] = prior[k]
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    print(f"\ncohort_test passed = {ct['passed']} "
          f"({ct['years_both_better']}/5 years)")
    print(f"separation gate open = {summary['separation_gate']['open']} "
          f"({gate.height} variables)")


if __name__ == "__main__":
    main()
