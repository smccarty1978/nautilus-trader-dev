"""Phase 14: the eight-condition decision gate, machine-evaluated.

Every contiguous region on every frozen axis is scored against all eight SPEC §8
conditions. Nothing is chosen by eye, and a region that clears seven of eight is
recorded with the one it failed -- which is the only way the report can honestly
say *where* the structure stops rather than just that it does.

Conditions 6-8 exist because of the predecessor's specific failure mode: its
signal region was 40.5% trades the 1 ATR stop had already taken, and its
giveback rules cut 70% of the >=3 ATR tail. A region that is merely "where bad
trades are" is not a decision; it is a restatement of the outcome.
"""
from __future__ import annotations

import itertools
import json
from pathlib import Path

import numpy as np
import polars as pl

from .buckets import (
    DD_BUCKETS, MFE_BUCKETS, PROGRESS3_BUCKETS, PROGRESS5_BUCKETS,
    STALL4_BUCKETS, STALL_BUCKETS, with_buckets,
)

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "studies/post_confirm_forward_opportunity/results"

# SPEC §8 thresholds. Frozen before the tables were read.
CV_BAR = -0.10
GEOM_BAR = 0.45
COVER_OBS = 0.10
COVER_TRADES = 0.15
YEARS_REQUIRED = 4
ACTIONABLE_ALIVE = 0.60
ACTIONABLE_LEAD_S = 30.0
ALREADY_DEAD_MAX = 0.40
ALREADY_DEAD_WINDOW_S = 15.0
TAIL_SHARE_MAX = 0.35
TAIL_CV_FLOOR = -0.50

AXES = (("stall", "stall_bucket", [n for n, *_ in STALL_BUCKETS]),
        ("stall4", "stall4_bucket", [n for n, *_ in STALL4_BUCKETS]),
        ("progress60", "progress60_bucket", [n for n, *_ in PROGRESS5_BUCKETS]),
        ("progress3", "progress3_bucket", [n for n, *_ in PROGRESS3_BUCKETS]),
        ("mfe", "mfe_bucket", [n for n, *_ in MFE_BUCKETS]),
        ("drawdown", "dd_bucket", [n for n, *_ in DD_BUCKETS]))
CROSSES = (("progress3_x_stall4", "progress3_bucket", [n for n, *_ in PROGRESS3_BUCKETS],
            "stall4_bucket", [n for n, *_ in STALL4_BUCKETS]),
           ("mfe_x_stall4", "mfe_bucket", [n for n, *_ in MFE_BUCKETS],
            "stall4_bucket", [n for n, *_ in STALL4_BUCKETS]),
           ("drawdown_x_stall4", "dd_bucket", [n for n, *_ in DD_BUCKETS],
            "stall4_bucket", [n for n, *_ in STALL4_BUCKETS]))


def _runs(names: list[str]):
    """Every contiguous run except the whole axis (which is not a region)."""
    for i, j in itertools.combinations(range(len(names) + 1), 2):
        if j - i < len(names):
            yield names[i:j]


def candidate_regions():
    for axis, col, names in AXES:
        for run in _runs(names):
            yield {"axis": axis, "label": f"{axis}:{'+'.join(run)}",
                   "mask": [(col, run)]}
    for axis, c1, n1, c2, n2 in CROSSES:
        for a in n1:
            for run in _runs(n2):
                yield {"axis": axis,
                       "label": f"{axis}:{a} x {'+'.join(run)}",
                       "mask": [(c1, [a]), (c2, run)]}
        for b in n2:
            for run in _runs(n1):
                if len(run) == 1:
                    continue                      # already emitted as a cell
                yield {"axis": axis,
                       "label": f"{axis}:{'+'.join(run)} x {b}",
                       "mask": [(c1, run), (c2, [b])]}


def _mask(region) -> pl.Expr:
    e = pl.lit(True)
    for col, vals in region["mask"]:
        e = e & pl.col(col).is_in(vals)
    return e


def _trade_first_cv(sub: pl.DataFrame) -> pl.DataFrame:
    """One row per trade -- its FIRST observation inside the region (SPEC D8)."""
    return sub.sort("offset_s").group_by("regime_id", maintain_order=True).first()


def evaluate(region, live: pl.DataFrame, allobs: pl.DataFrame,
             n_live_obs: int, n_trades: int) -> dict:
    m = _mask(region)
    sub = live.filter(m)                 # stop-live-alive observations
    allsub = allobs.filter(m)            # every observation in the region
    r = {"region": region["label"], "axis": region["axis"],
         "n_obs": sub.height, "n_obs_all": allsub.height,
         "n_unique_trades": int(sub["regime_id"].n_unique()) if sub.height else 0}
    if sub.height < 50 or r["n_unique_trades"] < 20:
        r |= {f"c{i}_passed": False for i in range(1, 9)}
        r["passed"] = False
        r["n_conditions_passed"] = 0
        r["first_failure"] = "TOO_SMALL"
        return r

    tf = _trade_first_cv(sub)
    cv = sub["cv_stop_live_atr"].drop_nulls().to_numpy().astype(float)
    tf_cv = tf["cv_stop_live_atr"].drop_nulls().to_numpy().astype(float)

    # 1 economics
    r["c1_mean_cv"] = float(cv.mean())
    r["c1_mean_cv_trade_level"] = float(tf_cv.mean())
    r["c1_passed"] = bool(cv.mean() <= CV_BAR)

    # 2 forward barrier geometry
    p = float((sub["race_0_5_before_0_5"] == "FAVORABLE").mean())
    r["c2_p_up050_b_dn050"] = p
    r["c2_passed"] = bool(p <= GEOM_BAR)

    # 3 breadth
    r["c3_obs_share"] = sub.height / n_live_obs
    r["c3_trade_share"] = r["n_unique_trades"] / n_trades
    r["c3_passed"] = bool(r["c3_obs_share"] >= COVER_OBS
                          and r["c3_trade_share"] >= COVER_TRADES)

    # 4 year stability, trade level
    yr = [float(tf.filter(pl.col("entry_year") == y)["cv_stop_live_atr"].mean() or 0.0)
          if tf.filter(pl.col("entry_year") == y).height else None
          for y in range(2021, 2026)]
    n_neg = sum(1 for v in yr if v is not None and v < 0)
    r["c4_years_negative"] = n_neg
    r["c4_year_means"] = json.dumps([None if v is None else round(v, 4) for v in yr])
    r["c4_passed"] = bool(n_neg >= YEARS_REQUIRED)

    # 5 direction stability, trade level
    sd = {}
    for s in ("LONG", "SHORT"):
        f = tf.filter(pl.col("side") == s)
        sd[s] = float(f["cv_stop_live_atr"].mean()) if f.height else None
    r["c5_long_cv"], r["c5_short_cv"] = sd["LONG"], sd["SHORT"]
    r["c5_passed"] = bool(sd["LONG"] is not None and sd["SHORT"] is not None
                          and sd["LONG"] < 0 and sd["SHORT"] < 0)

    # 6 actionable: still inside the accepted contract, with lead time
    alive_share = float(allsub["alive_stop_live"].mean())
    lead = float(sub["secs_to_stop_live_terminal"].median())
    r["c6_alive_share"] = alive_share
    r["c6_median_lead_s"] = lead
    r["c6_passed"] = bool(alive_share >= ACTIONABLE_ALIVE
                          and lead >= ACTIONABLE_LEAD_S)

    # 7 not merely identifying trades that are about to end anyway
    dead = float((tf["secs_to_stop_live_terminal"] <= ALREADY_DEAD_WINDOW_S).mean())
    r["c7_pct_already_dead"] = dead
    r["c7_passed"] = bool(dead <= ALREADY_DEAD_MAX)

    # 8 the tail is not what the region is made of
    tail = tf.filter(pl.col("reached_3_0"))
    share = tail.height / max(tf.height, 1)
    tail_cv = float(tail["cv_stop_live_atr"].mean()) if tail.height else 0.0
    r["c8_tail_share"] = share
    r["c8_tail_mean_cv"] = tail_cv
    r["c8_passed"] = bool(share <= TAIL_SHARE_MAX and tail_cv > TAIL_CV_FLOOR)

    flags = [r[f"c{i}_passed"] for i in range(1, 9)]
    r["n_conditions_passed"] = int(sum(flags))
    r["passed"] = bool(all(flags))
    r["first_failure"] = next((f"c{i}" for i in range(1, 9)
                               if not r[f"c{i}_passed"]), None)
    return r


def main() -> None:
    od = with_buckets(pl.read_parquet(OUT / "observation_panel.parquet"))
    live = od.filter(pl.col("alive_stop_live"))
    n_live_obs, n_trades = live.height, int(od["regime_id"].n_unique())

    rows = [evaluate(reg, live, od, n_live_obs, n_trades)
            for reg in candidate_regions()]
    df = (pl.DataFrame(rows, infer_schema_length=None)
          .sort(["passed", "n_conditions_passed", "c1_mean_cv"],
                descending=[True, True, False]))
    df.write_parquet(OUT / "decision_gate.parquet")
    df.write_csv(OUT / "decision_gate.csv")

    # Manifest #15 specifies the long form `condition, value, threshold, passed`.
    # The wide table above carries the same content plus the per-region context
    # the report cites, so both are emitted rather than one being reshaped away.
    bars = {"c1": ("mean_cv_stop_live", CV_BAR, "<="),
            "c2": ("p_up050_before_dn050", GEOM_BAR, "<="),
            "c3": ("obs_share", COVER_OBS, ">="),
            "c4": ("years_negative", YEARS_REQUIRED, ">="),
            "c5": ("long_cv", 0.0, "< 0 both sides"),
            "c6": ("alive_share", ACTIONABLE_ALIVE, ">="),
            "c7": ("pct_already_dead", ALREADY_DEAD_MAX, "<="),
            "c8": ("tail_share", TAIL_SHARE_MAX, "<=")}
    long_rows = []
    for r in df.iter_rows(named=True):
        for c, (metric, bar, op) in bars.items():
            val = next((r[k] for k in r if k.startswith(f"{c}_")
                        and k != f"{c}_passed" and not k.endswith("_means")), None)
            long_rows.append({"region": r["region"], "axis": r["axis"],
                              "n_obs": r["n_obs"],
                              "n_unique_trades": r["n_unique_trades"],
                              "condition": c, "metric": metric,
                              "value": val, "threshold": bar, "operator": op,
                              "passed": r.get(f"{c}_passed")})
    lg = pl.DataFrame(long_rows, infer_schema_length=None)
    lg.write_parquet(OUT / "decision_gate_conditions.parquet")
    lg.write_csv(OUT / "decision_gate_conditions.csv")
    print(f"  decision_gate_conditions (long form): {lg.height:,} rows")

    opened = df.filter(pl.col("passed"))
    print(f"  regions evaluated: {df.height:,}")
    print(f"  regions passing all 8: {opened.height}")
    print("\n  best by conditions passed:")
    cols = ["region", "n_obs", "n_unique_trades", "n_conditions_passed",
            "first_failure", "c1_mean_cv", "c2_p_up050_b_dn050",
            "c3_obs_share", "c4_years_negative", "c8_tail_share"]
    print(df.select(cols).head(12).to_pandas().round(4).to_string())

    # How close does anything get on the two substantive conditions?
    near = df.filter(pl.col("n_obs") >= 50).sort("c1_mean_cv")
    print("\n  most negative continuation value found anywhere:")
    print(near.select(cols).head(6).to_pandas().round(4).to_string())
    print("\n  most unfavorable forward geometry found anywhere:")
    print(df.filter(pl.col("n_obs") >= 50).sort("c2_p_up050_b_dn050")
          .select(cols).head(6).to_pandas().round(4).to_string())

    (OUT / "gate_verdict.json").write_text(json.dumps({
        "regions_evaluated": df.height,
        "regions_passing_all_eight": opened.height,
        "gate_open": bool(opened.height > 0),
        "best_region": (opened.row(0, named=True)["region"]
                        if opened.height else None),
        "max_conditions_passed": int(df["n_conditions_passed"].max()),
        "most_negative_cv_region": near.row(0, named=True)["region"],
        "most_negative_cv": float(near["c1_mean_cv"][0]),
        "cv_bar": CV_BAR,
        "min_geometry_region": df.filter(pl.col("n_obs") >= 50)
            .sort("c2_p_up050_b_dn050").row(0, named=True)["region"],
        "min_geometry": float(df.filter(pl.col("n_obs") >= 50)
                              .sort("c2_p_up050_b_dn050")["c2_p_up050_b_dn050"][0]),
        "geometry_bar": GEOM_BAR,
        "failure_histogram": {k: int(v) for k, v in
                              df["first_failure"].value_counts().rows()},
    }, indent=2, default=str))
    print(f"\n  gate_open = {opened.height > 0}")


if __name__ == "__main__":
    main()
