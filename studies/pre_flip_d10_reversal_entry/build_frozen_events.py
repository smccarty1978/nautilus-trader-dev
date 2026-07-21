"""Reproduce frozen W4 scores and causal D10 crossings.

This stage designs the policy population only. Final economics are produced by
`run_nt_policies.py` inside NautilusTrader's BacktestEngine.
"""
from __future__ import annotations

import json
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from sklearn.ensemble import HistGradientBoostingClassifier

from common import ATLAS, AUDIT, FLIP_ATLAS, MANIFEST, RESULTS, STUDY, WORK, read_manifest, sha256

MODEL = WORK / "w4_frozen.pkl"
FROZEN = WORK / "frozen_threshold.json"
SCORES = WORK / "causal_scores.parquet"


def _read(columns: list[str], periods: set[str] | None = None) -> pd.DataFrame:
    filters = [("period", "in", sorted(periods))] if periods else None
    return pd.read_parquet(ATLAS, columns=columns, filters=filters)


def fit_and_freeze() -> tuple[HistGradientBoostingClassifier, float, list[str]]:
    manifest = read_manifest()
    features = manifest["features"]
    label_cols = ["opp_flip_in_120s", "terminal_deterioration"]
    cols = ["observation_time", "period", *features, *label_cols]
    train = _read(cols, {"train"})
    train = train.dropna(subset=["aligned_price_minus_center_5m"])
    y = ((train.opp_flip_in_120s == 1) | (train.terminal_deterioration == 1)).astype("int8")
    model = HistGradientBoostingClassifier(
        max_iter=100, max_depth=5, learning_rate=0.05, random_state=42,
    ).fit(train[features].to_numpy(), y.to_numpy())
    with MODEL.open("wb") as f:
        pickle.dump(model, f, protocol=pickle.HIGHEST_PROTOCOL)
    del train, y

    val = _read(["observation_time", "period", *features], {"val"})
    valid = val.aligned_price_minus_center_5m.notna()
    prob = model.predict_proba(val.loc[valid, features].to_numpy())[:, 1]
    threshold = float(np.quantile(prob, 0.90))
    frozen = {
        "threshold": threshold,
        "threshold_type": "absolute_validation_frozen_score",
        "quantile": 0.90,
        "model": "W4 HistGradientBoostingClassifier",
        "model_seed": 42,
        "train_period": "2021-01-01..2024-12-31",
        "validation_period": "2025-01-01..2025-02-28",
        "validation_rows": int(valid.sum()),
        "features": features,
        "test_rank_used": False,
    }
    FROZEN.write_text(json.dumps(frozen, indent=2), encoding="utf-8")
    return model, threshold, features


def score_evaluation(model, threshold: float, features: list[str]) -> pd.DataFrame:
    cols = ["observation_time", "direction", "regime_age", "atr", "close",
            "current_mfe", "giveback", "period", *features]
    frames = []
    pf = pq.ParquetFile(ATLAS)
    for batch in pf.iter_batches(batch_size=200_000, columns=list(dict.fromkeys(cols))):
        d = batch.to_pandas()
        ts = pd.to_datetime(d.observation_time, unit="ns", utc=True)
        keep = ts.dt.year.isin([2025, 2026])
        d = d.loc[keep].copy()
        if d.empty:
            continue
        d["score_valid"] = d.aligned_price_minus_center_5m.notna()
        d["score"] = np.nan
        v = d.score_valid
        d.loc[v, "score"] = model.predict_proba(d.loc[v, features].to_numpy())[:, 1]
        d["regime_start_time"] = (
            d.observation_time.astype("int64")
            - (d.regime_age.astype("float64") * 1_000_000_000).round().astype("int64")
        )
        d["regime_id"] = (d.direction.astype("int8").astype(str) + ":" +
                          d.regime_start_time.astype(str))
        frames.append(d[["observation_time", "direction", "regime_age", "atr", "close",
                         "current_mfe", "giveback", "period", "score_valid", "score",
                         "regime_start_time", "regime_id"]])
    scores = pd.concat(frames, ignore_index=True).sort_values("observation_time")
    scores.to_parquet(SCORES, index=False)

    scores["above"] = scores.score_valid & (scores.score >= threshold)
    scores["previous_above"] = scores.groupby("regime_id", sort=False).above.shift(fill_value=False)
    crossings = scores[scores.above & ~scores.previous_above].copy()
    crossings["crossing_number"] = crossings.groupby("regime_id").cumcount() + 1
    crossings["is_first_crossing"] = crossings.crossing_number.eq(1)
    crossings["d10_threshold"] = threshold
    available=crossings.observation_time.astype("int64")+1_000_000_000
    crossings[available>=pd.Timestamp("2025-03-01",tz="UTC").value].to_parquet(
        RESULTS / "d10_entry_events.parquet", index=False)
    return scores


def build_coverage(scores: pd.DataFrame, threshold: float) -> None:
    rows = []
    for regime_id, g in scores.groupby("regime_id", sort=False):
        g = g.sort_values("observation_time")
        valid = g[g.score_valid]
        reached = valid[valid.score >= threshold]
        start = int(g.regime_start_time.iloc[0])
        # The next regime start is added below; the last observed checkpoint is
        # only a censoring bound, never used to create a score or trade signal.
        rows.append({
            "regime_id": regime_id, "direction": int(g.direction.iloc[0]),
            "regime_start_time": start,
            "last_checkpoint_time": int(g.observation_time.max()),
            "maximum_weakness_score": float(valid.score.max()) if len(valid) else np.nan,
            "D10_threshold": threshold,
            "ever_reached_D10": bool(len(reached)),
            "first_D10_time": int(reached.observation_time.iloc[0]) if len(reached) else pd.NA,
            "score_checkpoint_count": len(g), "valid_score_checkpoint_count": len(valid),
            "score_unavailable_reason": "" if len(valid) else "warmup_or_missing_features",
            "atr": float(g.atr.iloc[0]), "regime_mfe": float(g.current_mfe.max()),
        })
    cov = pd.DataFrame(rows).sort_values("regime_start_time").reset_index(drop=True)
    year = pd.to_datetime(cov.regime_start_time, unit="ns", utc=True).dt.year
    cov["year"] = year
    # F1 is the upstream all-flips population: observation_time is the actual
    # causal regime-flip time and opposing_flip_time is its actual NT-compatible
    # next opposing flip. Never infer an end from the next *scored* regime.
    flips = pd.read_parquet(FLIP_ATLAS,
        columns=["observation_time","opposing_flip_time","population","regime","atr"])
    flips = flips[flips.population.eq("F1")]
    dup = flips[flips.duplicated("observation_time", keep=False)]
    if len(dup) and (dup.groupby("observation_time").opposing_flip_time.nunique(dropna=False) > 1).any():
        raise RuntimeError("Conflicting duplicate F1 opposing-flip rows")
    flips = flips.drop_duplicates("observation_time")
    flips=flips[flips.observation_time>=pd.Timestamp("2025-01-01",tz="UTC").value].sort_values("observation_time").reset_index(drop=True)
    flips["_year"]=pd.to_datetime(flips.observation_time,unit="ns",utc=True).dt.year
    flips["_direction"]=0
    direction_map=cov.drop_duplicates("regime_start_time").set_index("regime_start_time").direction
    for yr,idx in flips.groupby("_year").groups.items():
        g=flips.loc[idx].sort_values("observation_time");known=g.observation_time.map(direction_map)
        anchors=np.flatnonzero(known.notna().to_numpy())
        if not len(anchors): raise RuntimeError(f"No direction anchor for F1 chain {yr}")
        a=int(anchors[0]);ad=int(known.iloc[a]);recon=np.array([ad*((-1)**(i-a)) for i in range(len(g))],dtype="int8")
        if not (recon[anchors]==known.iloc[anchors].astype(int).to_numpy()).all(): raise RuntimeError(f"F1 direction conflict {yr}")
        nxt=g.observation_time.shift(-1)
        if len(g)>1 and not (g.opposing_flip_time.iloc[:-1].notna().to_numpy()
                             & g.opposing_flip_time.iloc[:-1].eq(nxt.iloc[:-1]).to_numpy()).all():
            raise RuntimeError(f"F1 chain discontinuity {yr}")
        flips.loc[g.index,"_direction"]=recon
    eval_flips=flips[flips.observation_time>=pd.Timestamp("2025-03-01",tz="UTC").value]
    missing=eval_flips[~eval_flips.observation_time.isin(set(cov.regime_start_time))]
    if len(missing):
        add=pd.DataFrame({"regime_id":missing._direction.astype(int).astype(str)+":"+missing.observation_time.astype(str),
            "direction":missing._direction.astype(int),"regime_start_time":missing.observation_time.astype("int64"),
            "last_checkpoint_time":pd.array([pd.NA]*len(missing),dtype="Int64"),"maximum_weakness_score":np.nan,
            "D10_threshold":threshold,"ever_reached_D10":False,"first_D10_time":pd.array([pd.NA]*len(missing),dtype="Int64"),
            "score_checkpoint_count":0,"valid_score_checkpoint_count":0,"score_unavailable_reason":"regime_shorter_than_first_checkpoint_or_missing_features",
            "atr":missing.atr.astype(float),"regime_mfe":np.nan})
        cov=pd.concat([cov,add],ignore_index=True).sort_values("regime_start_time").reset_index(drop=True)
    cov["year"]=pd.to_datetime(cov.regime_start_time,unit="ns",utc=True).dt.year
    end_map = flips.set_index("observation_time").opposing_flip_time
    cov["regime_end_time"] = cov.regime_start_time.map(end_map).astype("Int64")
    end_year = pd.to_datetime(cov.regime_end_time, unit="ns", utc=True).dt.year
    cross_segment = cov.regime_end_time.notna() & end_year.ne(cov.year)
    cov.loc[cross_segment, "regime_end_time"] = pd.NA
    cov["right_censored"] = cov.regime_end_time.isna()
    cov["data_end_bound"] = cov.last_checkpoint_time.where(cov.right_censored, pd.NA).astype("Int64")
    cov["regime_duration_seconds"] = (cov.regime_end_time - cov.regime_start_time) / 1e9
    cov["regime_duration_bars"] = np.ceil(cov.regime_duration_seconds / 60).astype("Int64")
    cov["first_D10_available_time"] = (cov.first_D10_time + 1_000_000_000).astype("Int64")
    score_year=pd.to_datetime(scores.observation_time,unit="ns",utc=True).dt.year
    causal_bounds=(scores.assign(_year=score_year).groupby("_year").observation_time.max()+1_000_000_000).to_dict()
    cov["data_end_causal_bound"]=cov.year.map(causal_bounds).astype("Int64")
    cov["ever_reached_D10"] = (cov.first_D10_available_time.notna() & (
        (cov.regime_end_time.notna() & (cov.first_D10_available_time <= cov.regime_end_time)) |
        (cov.regime_end_time.isna() & (cov.first_D10_available_time <= cov.data_end_causal_bound))))
    cov["seconds_from_regime_start_to_D10"] = (cov.first_D10_available_time - cov.regime_start_time) / 1e9
    cov["seconds_from_D10_to_regime_end"] = (cov.regime_end_time - cov.first_D10_available_time) / 1e9
    cov["D10_same_timestamp_as_regime_end"] = cov.first_D10_available_time.eq(cov.regime_end_time)
    dt = pd.to_datetime(cov.regime_start_time, unit="ns", utc=True).dt.tz_convert("America/Chicago")
    cov["ct_year"] = dt.dt.year
    minute = dt.dt.hour * 60 + dt.dt.minute
    cov["session"] = np.where((minute >= 510) & (minute < 900), "RTH", "ETH")
    cov["atr_bucket"] = pd.qcut(cov.atr, 4, labels=["Q1", "Q2", "Q3", "Q4"], duplicates="drop")
    cov["regime_duration_bucket"] = pd.cut(cov.regime_duration_seconds, [-1,60,300,900,np.inf], labels=["<=1m","1-5m","5-15m",">15m"])
    cov["regime_MFE_bucket"] = pd.cut(cov.regime_mfe, [-np.inf,.5,1,2,np.inf], labels=["<0.5","0.5-1","1-2",">=2"])
    eval_start=pd.Timestamp("2025-03-01",tz="UTC").value
    cov=cov[cov.regime_start_time>=eval_start].copy()
    cov.to_parquet(RESULTS / "regime_d10_coverage.parquet", index=False)
    parts = []
    for dims in (["year"], ["year","direction"], ["year","session"], ["year","atr_bucket"],
                 ["year","regime_duration_bucket"], ["year","regime_MFE_bucket"]):
        s = cov.groupby(dims, observed=True, dropna=False).agg(
            regimes=("regime_id","size"), validly_scored=("valid_score_checkpoint_count",lambda x:int((x>0).sum())),
            reached_d10=("ever_reached_D10","sum"), same_time=("D10_same_timestamp_as_regime_end","sum"),
            right_censored=("right_censored","sum"),
        ).reset_index()
        s["grouping"] = "+".join(dims)
        s["group"] = s[dims].astype(str).agg("|".join, axis=1)
        parts.append(s[["grouping","group","regimes","validly_scored","reached_d10","same_time","right_censored"]])
    pd.concat(parts, ignore_index=True).to_parquet(RESULTS / "regime_d10_coverage_summary.parquet", index=False)


def write_provenance(threshold: float) -> None:
    p = {
        "study_spec": "attached pasted-text.txt; referenced investigation markdown absent",
        "atlas": str(ATLAS), "atlas_sha256": sha256(ATLAS),
        "upstream_manifest": str(MANIFEST), "upstream_manifest_sha256": sha256(MANIFEST),
        "model_artifact": str(MODEL), "model_sha256": sha256(MODEL),
        "threshold": threshold, "threshold_uses_test_rank": False,
        "python": sys.version,
    }
    (AUDIT / "provenance_audit.json").write_text(json.dumps(p, indent=2), encoding="utf-8")


def main():
    model, threshold, features = fit_and_freeze()
    scores = score_evaluation(model, threshold, features)
    build_coverage(scores, threshold)
    write_provenance(threshold)
    print(json.dumps({"threshold": threshold, "score_rows": len(scores)}, indent=2))


if __name__ == "__main__":
    main()
