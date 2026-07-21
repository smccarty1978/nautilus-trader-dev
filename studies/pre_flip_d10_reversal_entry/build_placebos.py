"""Outcome-blind, validation-frozen matched placebo events."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from common import RESULTS, WORK

SEED = 20260711


def qedges(s: pd.Series) -> list[float]:
    x = s.dropna().to_numpy(float)
    return [-np.inf, *np.unique(np.quantile(x, [.25, .5, .75])).tolist(), np.inf]


def main():
    scores = pd.read_parquet(WORK / "causal_scores.parquet")
    frozen = json.loads((WORK / "frozen_threshold.json").read_text())
    threshold = float(frozen["threshold"])
    dt = pd.to_datetime(scores.observation_time, unit="ns", utc=True).dt.tz_convert("America/Chicago")
    scores["year"] = dt.dt.year
    scores["month"] = dt.dt.month
    scores["session"] = np.where(((dt.dt.hour * 60 + dt.dt.minute) >= 510)
                                 & ((dt.dt.hour * 60 + dt.dt.minute) < 900), "RTH", "ETH")
    val = scores[(dt >= pd.Timestamp("2025-01-01", tz="America/Chicago"))
                 & (dt < pd.Timestamp("2025-03-01", tz="America/Chicago"))]
    edges = {c: qedges(val[c]) for c in ("atr", "current_mfe", "giveback")}
    edges["regime_age"] = [-np.inf, 60, 180, 600, np.inf]
    for c, e in edges.items():
        scores[c + "_bucket"] = pd.cut(scores[c], e, labels=False, include_lowest=True)

    scores = scores.sort_values("observation_time")
    scores["available_time"] = scores.observation_time.astype("int64") + 1_000_000_000
    scores["evaluation_year"] = np.select([
        scores.available_time.between(pd.Timestamp("2025-03-01",tz="UTC").value,pd.Timestamp("2025-12-31 23:59:59",tz="UTC").value),
        scores.available_time.between(pd.Timestamp("2026-01-01",tz="UTC").value,pd.Timestamp("2026-04-29 23:59:59",tz="UTC").value),
    ],[2025,2026],default=0)
    scores["above"] = scores.score_valid & (scores.score >= threshold)
    scores["previous_above"] = scores.groupby("regime_id").above.shift(fill_value=False)
    treated = scores[scores.above & ~scores.previous_above].groupby("regime_id", as_index=False, sort=False).head(1)
    treated=treated[treated.evaluation_year.isin([2025,2026])].copy()

    # Never-treated donor design intentionally conditions on later D10 treatment
    # status and noncensoring, but never on PnL, stop, or economic outcomes.
    coverage = pd.read_parquet(RESULTS / "regime_d10_coverage.parquet",
                               columns=["regime_id","ever_reached_D10","right_censored"])
    reached = set(coverage.loc[coverage.ever_reached_D10, "regime_id"])
    treated = treated[treated.regime_id.isin(reached)].copy()
    never = set(coverage.loc[~coverage.ever_reached_D10 & ~coverage.right_censored, "regime_id"])
    candidates = scores[scores.score_valid & ~scores.above & scores.regime_id.isin(never)
                        & scores.evaluation_year.isin([2025,2026])].copy()
    keys = ["evaluation_year", "month", "direction", "session", "regime_age_bucket", "atr_bucket",
            "current_mfe_bucket", "giveback_bucket"]
    rng = np.random.default_rng(SEED)
    used_regimes: set[str] = set()
    rows = []
    grouped = {k: g for k, g in candidates.groupby(keys, dropna=False, sort=False)}
    for t in treated.itertuples():
        key = tuple(getattr(t, k) for k in keys)
        pool = grouped.get(key)
        if pool is None:
            continue
        pool = pool[(pool.observation_time <= t.observation_time)
                    & ~pool.regime_id.isin(used_regimes)
                    & pool.regime_id.ne(t.regime_id)]
        if pool.empty:
            continue
        # Collapse to one nearest-age checkpoint per donor regime before
        # randomization so long regimes do not receive extra lottery tickets.
        pool = pool.assign(_dist=(pool.regime_age - t.regime_age).abs()).sort_values("_dist")
        pool = pool.groupby("regime_id", sort=False).head(1)
        pool = pool[pool._dist <= 30.0]
        if pool.empty:
            continue
        near = pool.nsmallest(min(20, len(pool)), "_dist")
        r = near.iloc[int(rng.integers(len(near)))].copy()
        used_regimes.add(r.regime_id)
        r["treated_regime_id"] = t.regime_id
        r["donor_regime_id"] = r.regime_id
        r["match_age_distance_s"] = r._dist
        r["threshold"] = threshold
        rows.append(r)
    out = pd.DataFrame(rows)
    if out.empty:
        raise RuntimeError("No valid matched placebo events; do not run policy matrix")
    if len(out):
        out["year"] = out.evaluation_year.astype(int)
        assert not out.treated_regime_id.eq(out.donor_regime_id).any()
        assert out.donor_regime_id.is_unique
        assert not out.donor_regime_id.isin(set(treated.regime_id)).any()
        if set(out.year.astype(int)) != {2025, 2026}:
            raise RuntimeError("Matched placebo coverage missing an evaluation year")
    out.to_parquet(WORK / "placebo_events.parquet", index=False)
    balance_rows = []
    if len(out):
        treated_by_id = treated.set_index("regime_id")
        for yr,g in out.groupby("year"):
          for c in ("regime_age", "atr", "current_mfe", "giveback"):
            tv = g.treated_regime_id.map(treated_by_id[c]).astype(float)
            dv = g[c].astype(float)
            pooled = np.sqrt((tv.var(ddof=1) + dv.var(ddof=1)) / 2)
            balance_rows.append({"year":int(yr),"feature": c, "treated_mean": tv.mean(),
                "donor_mean": dv.mean(), "standardized_mean_difference":
                (tv.mean() - dv.mean()) / pooled if pooled else 0.0})
    pd.DataFrame(balance_rows).to_parquet(WORK / "placebo_balance.parquet", index=False)
    summary=treated.groupby("evaluation_year").size().rename("treated_events").reset_index().rename(columns={"evaluation_year":"year"})
    matched=out.groupby("year").size().rename("matched_events").reset_index()
    summary=summary.merge(matched,on="year",how="left").fillna({"matched_events":0})
    summary["match_rate"]=summary.matched_events/summary.treated_events
    summary["seed"]=SEED;summary["outcome_columns_used"]=False
    summary["validation_frozen_bucket_edges"]=json.dumps(edges)
    summary.to_parquet(RESULTS / "matched_placebo_summary.parquet", index=False)
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
