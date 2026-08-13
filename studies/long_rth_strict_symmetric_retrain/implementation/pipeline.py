"""Bounded strict-long HGB retraining pipeline.

Consumes the corrected, causal long-side attachment. It does not run NT, rebuild
signals, or inspect 2026. Dataset outputs are monthly, resumable checkpoints.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import time
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from scipy.stats import pearsonr, spearmanr
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import (average_precision_score, brier_score_loss, log_loss,
                             roc_auc_score)

HERE = Path(__file__).resolve().parent
STUDY = HERE.parent
ROOT = STUDY.parents[1]
CONFIG, WORK, RESULTS, ARTIFACTS = (STUDY / "config", STUDY / "_work",
                                    STUDY / "results", STUDY / "artifacts" / "models")
SOURCE_STUDY = ROOT / "studies" / "long_rth_mirrored_surface_top100_training"
SOURCE_ATTACH = SOURCE_STUDY / "_work"
CANDIDATES = ROOT / "studies" / "runtime_constrained_f3_feature_reduction" / "results" / "candidate_feature_sets.json"
TARGET = "bullish_regime_flip_within_300s"
MODEL_SPECS = {
    "LONG_STRICT_top25_gbt_v2": ("F3_top25_gbt_v1", 25),
    "LONG_STRICT_top103_gbt_v2": ("F3_top100_gbt_v1", 103),
}
PARAMS = {"max_depth": 3, "learning_rate": 0.05, "max_iter": 200, "random_state": 42}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def stable_json_hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def feature_list_hash(features: list[str]) -> str:
    """Exact hash convention frozen by the source reduction study."""
    return hashlib.sha256(json.dumps(features).encode()).hexdigest()


def load_contracts() -> dict[str, list[str]]:
    raw = json.loads(CANDIDATES.read_text(encoding="utf-8"))
    out = {}
    for model_id, (key, expected) in MODEL_SPECS.items():
        item = raw[key]
        features = list(item["features"])
        if item["actual_n_features"] != expected or len(features) != expected or len(set(features)) != expected:
            raise RuntimeError(f"{key}: expected exact {expected}-column ordered contract")
        if feature_list_hash(features) != item["sha256"]:
            raise RuntimeError(f"{key}: frozen feature-list hash mismatch")
        out[model_id] = features
    return out


def load_mapping(features: list[str], exact: bool = False) -> list[dict]:
    """Load the explicit reviewed mapping; never infer semantics from names."""
    path = CONFIG / "long_feature_mapping.json"
    if not path.exists():
        raise RuntimeError("STRICT_LONG_FEATURE_MAPPING_FAILED: reviewed mapping absent")
    rows = json.loads(path.read_text(encoding="utf-8"))
    required = {"source_short_feature", "long_model_feature", "mapping_type",
                "formula_source", "runtime_tracker", "status"}
    allowed = {"IDENTITY", "DIRECTION_NORMALIZED_IDENTITY", "BULL_BEAR_SWAP",
               "HIGH_LOW_SWAP", "ABOVE_BELOW_SWAP", "ONE_HOT_GROUP_MAPPING", "UNRESOLVED"}
    if any(set(r) != required or r["mapping_type"] not in allowed for r in rows):
        raise RuntimeError("STRICT_LONG_FEATURE_MAPPING_FAILED: schema/type")
    by_name = {r["source_short_feature"]: r for r in rows}
    if len(by_name) != len(rows) or not set(features).issubset(by_name) or (exact and set(by_name) != set(features)):
        raise RuntimeError("STRICT_LONG_FEATURE_MAPPING_FAILED: coverage")
    ordered = [by_name[f] for f in features]
    if any(r["status"] != "RESOLVED" for r in ordered):
        raise RuntimeError("STRICT_LONG_FEATURE_MAPPING_FAILED: unresolved")
    return ordered


def init_contracts() -> None:
    CONFIG.mkdir(parents=True, exist_ok=True)
    contracts = load_contracts()
    union = []
    for fs in contracts.values():
        for f in fs:
            if f not in union:
                union.append(f)
    load_mapping(union, exact=True)
    (CONFIG / "model_config.json").write_text(json.dumps({"models": MODEL_SPECS, "hyperparameters": PARAMS,
                                                            "target": TARGET, "train_years": [2021,2022,2023,2024],
                                                            "development_year": 2025}, indent=2) + "\n", encoding="utf-8")


def strict_snap_indices(source_ts: np.ndarray, observations: np.ndarray) -> np.ndarray:
    """Last completed open-labelled bar; equal timestamp is prohibited."""
    return np.searchsorted(source_ts, observations, side="left") - 1


def attachment_timing_trace(source_ts: np.ndarray, observations: np.ndarray) -> list[dict]:
    """Executable ordering contract matching attach_features_long.py:93-178."""
    snap = strict_snap_indices(source_ts, observations)
    lookup = {int(source_ts[i]): int(obs) for i, obs in zip(snap, observations) if i >= 0}
    current_minute = None; last_1m_close = None; records = []
    for bar_ts in map(int, source_ts):
        minute = bar_ts // 60_000_000_000
        if current_minute is None:
            current_minute = minute
        elif minute != current_minute:
            last_1m_close = (current_minute + 1) * 60_000_000_000
            current_minute = minute
        if bar_ts in lookup:
            records.append({"observation_time": lookup[bar_ts], "latest_source_ts_used": bar_ts,
                            "latest_1m_bar_close_ts_used": last_1m_close})
    return records


def materialize_frozen_features(df: pd.DataFrame, features: list[str]) -> pd.DataFrame:
    """Expand frozen complete one-hot groups from causal base categoricals."""
    out = df.copy()
    groups: dict[str, list[tuple[str, str]]] = {}
    for feature in features:
        if "_position__" in feature:
            base, category = feature.split("__", 1)
            groups.setdefault(base, []).append((feature, category))
    for base, members in groups.items():
        if base not in out.columns:
            raise RuntimeError(f"missing categorical source for group: {base}")
        values = out[base].fillna("UNAVAILABLE").astype(str)
        categories = {category for _, category in members}
        unknown = sorted(set(values.unique()) - categories)
        if unknown:
            raise RuntimeError(f"unknown categories for {base}: {unknown}")
        for feature, category in members:
            out[feature] = (values == category).astype("int8")
        if not (out[[feature for feature, _ in members]].sum(axis=1) == 1).all():
            raise RuntimeError(f"non-exclusive/incomplete one-hot group: {base}")
    return out


def validate_source(df: pd.DataFrame, year: int, features: list[str], require_full_year: bool = True) -> None:
    required = set(features) | {"observation_time", "regime_start_ns", "confirm_flip_ns",
                                "prevailing_direction", "entry_direction", "session",
                                "latest_source_ts_used", "latest_1m_bar_close_ts_used"}
    missing = sorted(required - set(df.columns))
    if missing:
        raise RuntimeError(f"{year}: missing required columns: {missing}")
    if set(df.prevailing_direction.unique()) != {-1} or set(df.entry_direction.unique()) != {1}:
        raise RuntimeError(f"{year}: population direction contract failed")
    if set(df.session.unique()) != {"RTH"}:
        raise RuntimeError(f"{year}: non-RTH rows")
    if not (df.confirm_flip_ns > df.observation_time).all():
        raise RuntimeError(f"{year}: invalid/censored completed-regime label horizon")
    if df[["regime_start_ns", "observation_time"]].duplicated().any():
        raise RuntimeError(f"{year}: duplicate checkpoint key")
    if (df.latest_source_ts_used >= df.observation_time).any():
        raise RuntimeError(f"{year}: strict 1s provenance violation")
    one_m = df.latest_1m_bar_close_ts_used.dropna()
    if (one_m >= df.loc[one_m.index, "observation_time"]).any():
        raise RuntimeError(f"{year}: coincident 1m ordering violation")
    manifest = json.loads((SOURCE_STUDY / "results" / "phase3_attach_manifest.json").read_text())
    frozen = manifest["years"][str(year)]
    if frozen["provenance_violations"] != 0 or frozen["output_sha256"] != sha256_file(SOURCE_ATTACH / f"attached_long_{year}.parquet"):
        raise RuntimeError(f"{year}: attachment provenance/hash is not frozen")
    label_manifest = json.loads((SOURCE_STUDY / "results" / "phase2_3_assemble_manifest.json").read_text())
    label_source = label_manifest["years"][str(year)]
    if label_source["censored_rows"] != 0 or (require_full_year and label_source["rows"] != len(df)):
        raise RuntimeError(f"{year}: completed-regime label/censoring contract mismatch")


def build(years: list[int], approve_over_60m: bool = False) -> None:
    init_contracts()
    all_features = load_contracts()["LONG_STRICT_top103_gbt_v2"]
    mapping_hash = sha256_file(CONFIG / "long_feature_mapping.json")
    script_hash = sha256_file(Path(__file__))
    feature_hashes = {k: feature_list_hash(v) for k,v in load_contracts().items()}
    benchmark_path = RESULTS / "gate2_benchmark.json"
    if not benchmark_path.exists():
        raise RuntimeError("Gate 2 benchmark is mandatory before full build")
    gate2 = json.loads(benchmark_path.read_text())
    current_gate2 = {"source_hash": sha256_file(SOURCE_ATTACH / "attached_long_2025.parquet"),
                     "script_hash": script_hash, "mapping_hash": mapping_hash,
                     "feature_list_hashes": feature_hashes}
    if any(gate2.get(k) != v for k,v in current_gate2.items()):
        raise RuntimeError("Gate 2 benchmark causal provenance is stale")
    if gate2.get("projected_full_runtime", 0) > 3600 and not approve_over_60m:
        raise RuntimeError("projected runtime exceeds 60 minutes; explicit --approve-over-60m required")
    WORK.mkdir(parents=True, exist_ok=True)
    for year in years:
        if year not in {2021, 2022, 2023, 2024, 2025}:
            raise RuntimeError("2026 build forbidden; post-freeze diagnostic requires separate authorization")
        t_year = time.perf_counter()
        src = SOURCE_ATTACH / f"attached_long_{year}.parquet"
        df = materialize_frozen_features(pd.read_parquet(src), all_features)
        validate_source(df, year, all_features)
        df[TARGET] = (((df.confirm_flip_ns - df.observation_time) / 1e9) <= 300.0).astype("int8")
        dt = pd.to_datetime(df.observation_time, unit="ns", utc=True).dt.tz_convert("America/Chicago")
        df["month"] = dt.dt.strftime("%Y-%m")
        expected_months = sorted(df["month"].unique().tolist())
        completed, rows = [], 0
        for month, part in df.groupby("month", sort=True):
            out = WORK / "monthly" / str(year) / f"{month}.parquet"
            out.parent.mkdir(parents=True, exist_ok=True)
            keep = ["year", "month", "regime_start_ns", "observation_time", TARGET] + all_features
            month_manifest = out.with_suffix(".manifest.json")
            if out.exists() and month_manifest.exists():
                old = json.loads(month_manifest.read_text())
                expected = {"source_hash": sha256_file(src), "script_hash": script_hash,
                            "mapping_hash": mapping_hash, "feature_list_hashes": feature_hashes}
                if any(old.get(k) != v for k,v in expected.items()) or old.get("output_hash") != sha256_file(out):
                    raise RuntimeError(f"{month}: stale/corrupt resume checkpoint")
            else:
                part[keep].to_parquet(out, index=False, compression="zstd")
                elapsed = time.perf_counter() - t_year
                month_manifest.write_text(json.dumps({"month": month, "source_hash": sha256_file(src),
                    "script_hash": script_hash, "mapping_hash": mapping_hash, "feature_list_hashes": feature_hashes,
                    "output_hash": sha256_file(out), "rows": len(part),
                    "regimes": int(part.regime_start_ns.nunique()),
                    "positive_prevalence": float(part[TARGET].mean()),
                    "missing_values": int(part[all_features].isna().sum().sum()),
                    "elapsed_runtime": elapsed, "rows_per_second": len(part)/elapsed if elapsed else None}, indent=2) + "\n")
            completed.append(month); rows += len(part)
            manifest = {"year": year, "source": str(src), "source_hashes": {str(src): sha256_file(src)},
                        "script_hash": script_hash, "mapping_hash": mapping_hash,
                        "feature_list_hashes": feature_hashes,
                        "expected_months": expected_months, "completed_months": completed, "row_count": rows,
                        "regime_count": int(df[df.month.isin(completed)].regime_start_ns.nunique()),
                        "target_prevalence": float(df[df.month.isin(completed)][TARGET].mean()),
                        "missing_values": int(df[df.month.isin(completed)][all_features].isna().sum().sum()),
                        "elapsed_runtime": time.perf_counter()-t_year,
                        "rows_per_second": rows/(time.perf_counter()-t_year),
                        "projected_full_runtime": (time.perf_counter()-t_year)*len(expected_months)/len(completed)}
            (out.parent / "checkpoint.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def load_years(years: list[int]) -> pd.DataFrame:
    paths = []
    for y in years:
        checkpoint = WORK / "monthly" / str(y) / "checkpoint.json"
        if not checkpoint.exists(): raise RuntimeError(f"{y}: missing checkpoint")
        state = json.loads(checkpoint.read_text())
        current = {"script_hash": sha256_file(Path(__file__)),
                   "mapping_hash": sha256_file(CONFIG / "long_feature_mapping.json"),
                   "feature_list_hashes": {k: feature_list_hash(v) for k,v in load_contracts().items()}}
        if any(state.get(k) != v for k,v in current.items()): raise RuntimeError(f"{y}: stale causal contract")
        if state["completed_months"] != state["expected_months"]: raise RuntimeError(f"{y}: incomplete population")
        yp = sorted((WORK / "monthly" / str(y)).glob("*.parquet"))
        if [p.stem for p in yp] != state["expected_months"]: raise RuntimeError(f"{y}: stale/missing month files")
        for p in yp:
            mm = json.loads(p.with_suffix(".manifest.json").read_text())
            if mm["output_hash"] != sha256_file(p) or any(mm.get(k) != v for k,v in current.items()):
                raise RuntimeError(f"{p}: hash/causal contract mismatch")
        paths.extend(yp)
    if not paths:
        raise RuntimeError("no monthly checkpoints; run build first")
    return pd.concat((pd.read_parquet(p) for p in paths), ignore_index=True)


def metric_block(y, score) -> dict:
    return {"roc_auc": float(roc_auc_score(y, score)), "average_precision": float(average_precision_score(y, score)),
            "log_loss": float(log_loss(y, score, labels=[0,1])), "brier_score": float(brier_score_loss(y, score)),
            "score_mean": float(np.mean(score)), "score_standard_deviation": float(np.std(score))}


def canonical_calculation_count(features: list[str]) -> int:
    return len({f.split("__", 1)[0] if "_position__" in f else f for f in features})


def selected_regimes(df, score, q: float) -> tuple[float, np.ndarray, np.ndarray]:
    threshold = float(np.quantile(score, q))
    mask = score >= threshold
    return threshold, np.flatnonzero(mask), df.loc[mask, "regime_start_ns"].unique()


def train() -> None:
    init_contracts(); RESULTS.mkdir(parents=True, exist_ok=True); ARTIFACTS.mkdir(parents=True, exist_ok=True)
    train_df, dev = load_years([2021,2022,2023,2024]), load_years([2025])
    contracts = load_contracts(); scores = {}; selections = {}
    for model_id, features in contracts.items():
        out = ARTIFACTS / model_id
        if out.exists():
            raise RuntimeError(f"refusing to overwrite model artifact: {out}")
        out.mkdir(parents=True)
        model = HistGradientBoostingClassifier(**PARAMS)
        t0=time.perf_counter(); model.fit(train_df[features], train_df[TARGET]); fit_s=time.perf_counter()-t0
        joblib.dump(model, out / "model.joblib")
        t0=time.perf_counter(); score=model.predict_proba(dev[features])[:,1]; score_s=time.perf_counter()-t0
        if model.classes_.tolist() != [0,1]: raise RuntimeError("unexpected classes")
        scores[model_id]=score
        metrics = metric_block(dev[TARGET], score)
        metrics.update({"feature_count": len(features), "canonical_runtime_calculation_count": canonical_calculation_count(features),
                        "training_rows": len(train_df), "training_regimes": int(train_df.regime_start_ns.nunique()),
                        "development_rows": len(dev), "development_regimes": int(dev.regime_start_ns.nunique()),
                        "positive_prevalence": float(dev[TARGET].mean()), "fit_runtime": fit_s, "score_runtime": score_s})
        monthly={}
        for month,g in dev.assign(_score=score).groupby("month"):
            monthly[month]={"roc_auc":float(roc_auc_score(g[TARGET],g._score)),
                            "average_precision":float(average_precision_score(g[TARGET],g._score))}
        metrics["monthly_metrics"]=monthly
        selections[model_id]={}
        for label,q in (("top_5pct",.95),("top_2_5pct",.975)):
            th, idx, regs=selected_regimes(dev,score,q)
            metrics[label+"_threshold"]=th; metrics[label+"_selected_rows"]=len(idx); metrics[label+"_selected_regimes"]=len(regs)
            selections[model_id][label]={"threshold":th,"indices":idx,"regimes":regs}
        fixture=dev.sample(n=min(2048,len(dev)),random_state=42).sort_index()
        fixture.to_parquet(out/"validation_fixture.parquet",index=False)
        fixture_scores=model.predict_proba(fixture[features])[:,1]; np.save(out/"validation_fixture_scores.npy",fixture_scores)
        mapping=load_mapping(features)
        (out/"feature_list.json").write_text(json.dumps(features,indent=2)+"\n"); (out/"feature_mapping.json").write_text(json.dumps(mapping,indent=2)+"\n")
        metrics["artifact_size"] = int((out/"model.joblib").stat().st_size)
        (out/"metrics_2025.json").write_text(json.dumps(metrics,indent=2)+"\n")
        manifest={"model_id":model_id,"model_class":"HistGradientBoostingClassifier","hyperparameters":PARAMS,"target":TARGET,
                  "population_direction":-1,"trade_direction":1,"strict_timing_contract":"open-labelled source bar ts_event < observation_time",
                  "training_years":[2021,2022,2023,2024],"development_year":2025,"feature_count":len(features),
                  "ordered_feature_list_hash":feature_list_hash(features),"feature_mapping_hash":sha256_file(out/"feature_mapping.json"),
                  "population_builder_hash":sha256_file(SOURCE_STUDY/"implementation"/"build_surface_long.py"),
                  "feature_attachment_hash":sha256_file(SOURCE_STUDY/"implementation"/"attach_features_long.py"),
                  "training_data_hash":stable_json_hash([sha256_file(p) for y in [2021,2022,2023,2024] for p in sorted((WORK/"monthly"/str(y)).glob("*.parquet"))]),
                  "development_data_hash":stable_json_hash([sha256_file(p) for p in sorted((WORK/"monthly"/"2025").glob("*.parquet"))]),
                  "model_hash":sha256_file(out/"model.joblib"),"validation_score_hash":sha256_file(out/"validation_fixture_scores.npy"),
                  "sklearn_version":sklearn.__version__,"numpy_version":np.__version__,"python_version":platform.python_version(),"random_seed":42,
                  "fit_timestamp":datetime.now(timezone.utc).isoformat(),"fit_runtime":fit_s,"artifact_status":"CANDIDATE"}
        (out/"manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
        (out/"README.md").write_text(f"# {model_id}\n\nStrict causal long-side regime-transition timing candidate. Not a profitability model.\n")
    a,b=MODEL_SPECS.keys(); sa,sb=scores[a],scores[b]
    comparison={"score_pearson_correlation":float(pearsonr(sa,sb).statistic),"score_spearman_correlation":float(spearmanr(sa,sb).statistic)}
    for label in ("top_5pct","top_2_5pct"):
        ra=set(map(int,selections[a][label]["regimes"])); rb=set(map(int,selections[b][label]["regimes"])); union=ra|rb
        comparison[label+"_regime_overlap"]=len(ra&rb)/len(union) if union else 1.0
        comparison[label+"_L25_only_selected_regimes"]=sorted(ra-rb); comparison[label+"_L103_only_selected_regimes"]=sorted(rb-ra)
        first={m:dev.iloc[i].observation_time for m,s in ((a,sa),(b,sb)) for i in []}
        qa,qb=selections[a][label]["threshold"],selections[b][label]["threshold"]
        fa=dev.assign(score=sa).query("score >= @qa").groupby("regime_start_ns").observation_time.min()
        fb=dev.assign(score=sb).query("score >= @qb").groupby("regime_start_ns").observation_time.min()
        common=fa.index.intersection(fb.index); comparison[label+"_first_qualifying_checkpoint_differences"]={"common_regimes":len(common),"different":int((fa.loc[common]!=fb.loc[common]).sum())}
    # Regime-level descriptive diagnostics.
    regime_diag={}
    for mid,score in scores.items():
        d=dev.assign(score=score).sort_values(["regime_start_ns","observation_time"])
        ag=d.groupby("regime_start_ns").agg(target=(TARGET,"max"),maximum=("score","max"),p90=("score",lambda x:np.quantile(x,.9)),first=("score","first"),mean=("score","mean"))
        regime_diag[mid]={k:float(roc_auc_score(ag.target,ag[k])) for k in ("maximum","p90","first","mean")}
    comparison["regime_level_roc_auc"]=regime_diag
    (RESULTS/"comparison_2025.json").write_text(json.dumps(comparison,indent=2)+"\n")
    validate_artifacts()
    m25=json.loads((ARTIFACTS/a/"metrics_2025.json").read_text()); m103=json.loads((ARTIFACTS/b/"metrics_2025.json").read_text())
    worst=max(m103["monthly_metrics"][m]["roc_auc"]-m25["monthly_metrics"][m]["roc_auc"] for m in m103["monthly_metrics"])
    insufficient=(max(m25["roc_auc"],m103["roc_auc"]) < .52 or
                  max(m25["average_precision"],m103["average_precision"]) < m25["positive_prevalence"]*1.05)
    effectively_tied=(abs(m25["roc_auc"]-m103["roc_auc"]) <= .0001 and
                      abs(m25["average_precision"]-m103["average_precision"]) <= .0002 and
                      comparison["score_pearson_correlation"] >= .999 and
                      comparison["top_5pct_regime_overlap"] >= .98)
    close=(m25["roc_auc"]-m103["roc_auc"]>=-.003 and m25["average_precision"]-m103["average_precision"]>=-.005 and worst<=.020 and m25["brier_score"]<=m103["brier_score"]+.005)
    if insufficient: decision="LONG_STRICT_MODEL_SIGNAL_INSUFFICIENT"
    elif effectively_tied: decision="LONG_STRICT_MODELS_EFFECTIVELY_TIED"
    elif close: decision="LONG_STRICT_TOP25_SELECTED"
    else: decision="LONG_STRICT_TOP103_SELECTED"
    (RESULTS/"final_decision.json").write_text(json.dumps({"model_decision":decision,"contract_decision":"STRICT_LONG_CONTRACT_VERIFIED","2026_status":"NOT_SCORED"},indent=2)+"\n")


def validate_artifacts() -> None:
    report={}
    for model_id in MODEL_SPECS:
        out=ARTIFACTS/model_id; model=joblib.load(out/"model.joblib"); features=json.loads((out/"feature_list.json").read_text())
        fixture=pd.read_parquet(out/"validation_fixture.parquet"); expected=np.load(out/"validation_fixture_scores.npy")
        actual=model.predict_proba(fixture[features])[:,1]; diff=np.abs(actual-expected)
        result={"max_abs_diff":float(diff.max()),"mean_abs_diff":float(diff.mean()),"feature_order_exact":features==load_contracts()[model_id],
                "classes":model.classes_.tolist(),"positive_class_index":int(np.flatnonzero(model.classes_==1)[0])}
        if result != {"max_abs_diff":0.0,"mean_abs_diff":0.0,"feature_order_exact":True,"classes":[0,1],"positive_class_index":1}:
            raise RuntimeError(f"reproduction failed: {model_id}: {result}")
        report[model_id]=result
    RESULTS.mkdir(parents=True,exist_ok=True); (RESULTS/"reproduction_report.json").write_text(json.dumps(report,indent=2)+"\n")


def benchmark(month: str) -> None:
    year = int(month[:4])
    if year != 2025: raise RuntimeError("Gate 2 benchmark must use one 2025 month")
    t0=time.perf_counter(); features=load_contracts()["LONG_STRICT_top103_gbt_v2"]
    start=pd.Timestamp(f"{month}-01",tz="America/Chicago"); end=start+pd.offsets.MonthBegin(1)
    src=SOURCE_ATTACH/f"attached_long_{year}.parquet"
    part=pd.read_parquet(src,filters=[("observation_time",">=",start.tz_convert("UTC").value),("observation_time","<",end.tz_convert("UTC").value)])
    part=materialize_frozen_features(part,features)
    validate_source(part,year,features,require_full_year=False)
    if part.empty: raise RuntimeError(f"no rows for {month}")
    elapsed=time.perf_counter()-t0
    rep={"month":month,"rows":len(part),"regimes":int(part.regime_start_ns.nunique()),
         "positive_prevalence":float((((part.confirm_flip_ns-part.observation_time)/1e9)<=300).mean()),
         "missing_values":int(part[features].isna().sum().sum()),"elapsed_runtime":elapsed,
         "rows_per_second":len(part)/elapsed,"projected_full_runtime":elapsed*12*5,
         "source_hash":sha256_file(src),"script_hash":sha256_file(Path(__file__)),
         "mapping_hash":sha256_file(CONFIG/"long_feature_mapping.json"),
         "feature_list_hashes":{k:feature_list_hash(v) for k,v in load_contracts().items()}}
    RESULTS.mkdir(parents=True,exist_ok=True); (RESULTS/"gate2_benchmark.json").write_text(json.dumps(rep,indent=2)+"\n")


def main():
    p=argparse.ArgumentParser(); p.add_argument("command",choices=["init","benchmark","build","train","validate"]); p.add_argument("--years",nargs="*",type=int); p.add_argument("--month",default="2025-03"); p.add_argument("--approve-over-60m",action="store_true")
    a=p.parse_args()
    if a.command=="init": init_contracts()
    elif a.command=="benchmark": benchmark(a.month)
    elif a.command=="build": build(a.years or [2021,2022,2023,2024,2025],a.approve_over_60m)
    elif a.command=="train": train()
    else: validate_artifacts()

if __name__ == "__main__": main()
