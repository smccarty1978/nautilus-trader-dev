"""Governed, post-collection descriptive first-P90 warning analysis only."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from research.analysis.identity import canonical_sha256, sha256_file
from research_workflow.first_p90_gate import require_march_gate

NS = 1_000_000_000
HORIZONS = (60, 120, 180, 240, 300, 450, 600)
SCORE_OFFSETS = (15, 30, 60, 90, 120)
KEY = ["regime_start_ns", "direction", "anchor_ts"]


class FirstP90AnalysisError(RuntimeError):
    pass


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FirstP90AnalysisError(f"FIRST_P90_ARTIFACT_MISSING:{path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _age(value: float) -> str:
    return "[300,600)" if value < 600 else "[600,900)" if value < 900 else "[900,1800)" if value < 1800 else ">=1800"


def _tod(ts: int, session_open: int) -> str:
    minute = (ts - session_open) // (60 * NS)
    return "final_30m" if minute >= 360 else f"{minute // 60:02d}:00"


def _assert_2024(frame: pd.DataFrame, timestamp: str) -> None:
    years = pd.to_datetime(frame[timestamp].astype("int64"), unit="ns", utc=True).dt.year
    if not (years == 2024).all():
        raise FirstP90AnalysisError("FIRST_P90_YEAR_NOT_2024")


def _validate(diagnostic: pd.DataFrame) -> None:
    required = set(KEY + ["scheduled_ts", "offset_s", "score", "score_valid", "terminal_reason", "terminal_ts", "market_path_status", "score_path_status", "session_open_ts"])
    missing = required - set(diagnostic.columns)
    if missing: raise FirstP90AnalysisError(f"FIRST_P90_DIAGNOSTIC_SCHEMA_MISSING:{sorted(missing)}")
    if not set(diagnostic.direction.astype(str)).issubset({"LONG", "SHORT"}): raise FirstP90AnalysisError("FIRST_P90_DIRECTION_INVALID")
    _assert_2024(diagnostic, "anchor_ts")
    if diagnostic.duplicated(KEY + ["scheduled_ts"]).any(): raise FirstP90AnalysisError("FIRST_P90_DUPLICATE_GRID")
    terminal = ["terminal_reason", "terminal_ts", "market_path_status", "score_path_status"]
    if any(g[terminal].drop_duplicates().shape[0] != 1 for _, g in diagnostic.groupby(KEY, sort=False)):
        raise FirstP90AnalysisError("FIRST_P90_TERMINAL_INCONSISTENT")


def _anchors(diagnostic: pd.DataFrame, thresholds: dict[str, Any]) -> pd.DataFrame:
    try: p90 = {side: float(v["p90"]) for side, v in thresholds.items()}
    except (KeyError, TypeError, ValueError) as err: raise FirstP90AnalysisError("FIRST_P90_THRESHOLDS_INVALID") from err
    if set(p90) != {"LONG", "SHORT"}: raise FirstP90AnalysisError("FIRST_P90_THRESHOLDS_INVALID")
    result = diagnostic.sort_values("scheduled_ts").groupby(KEY, as_index=False).first()
    result["threshold"] = result.direction.map(p90)
    result["flip_ts"] = result.terminal_ts.where(result.terminal_reason.eq("ACCEPTED_OPPOSING_FLIP"))
    result["time_to_flip_seconds"] = (result.flip_ts-result.anchor_ts)/NS
    result["market_censored"] = result.market_path_status.eq("CENSORED")
    result["age_bucket"] = result.get("regime_age_seconds", pd.Series(300, index=result.index)).fillna(300).map(_age)
    result["quarter"] = pd.to_datetime(result.anchor_ts.astype("int64"),unit="ns",utc=True).dt.quarter.map(lambda q: f"Q{q}")
    result["tod_cell"] = [_tod(int(t), int(o)) for t,o in zip(result.anchor_ts, result.session_open_ts)]
    return result


def _score_summary(anchors: pd.DataFrame, diagnostic: pd.DataFrame, thresholds: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    score = diagnostic.merge(anchors[KEY + ["threshold", "terminal_ts", "market_censored"]], on=KEY, validate="many_to_one")
    score["score_offset_seconds"] = (score.scheduled_ts-score.anchor_ts)/NS
    score["delta_from_p90"] = score.score-score.threshold
    score["at_or_above_p95"] = score.score >= score.direction.map(lambda x: float(thresholds[x]["p95"]))
    score["at_or_above_p97_5"] = score.score >= score.direction.map(lambda x: float(thresholds[x]["p97_5"]))
    summary=[]
    for key, rows in score.groupby(KEY, sort=True):
        rows=rows.sort_values("scheduled_ts"); anchor=anchors[(anchors.regime_start_ns==key[0])&(anchors.direction==key[1])&(anchors.anchor_ts==key[2])].iloc[0]
        terminal_offset=(int(anchor.terminal_ts)-int(anchor.anchor_ts))/NS
        required={x for x in SCORE_OFFSETS if x <= terminal_offset}
        actual=set(rows.loc[rows.score_valid & rows.score.notna(),"score_offset_seconds"].astype(int))
        observed=rows[rows.score_valid & rows.score.notna()]
        falling=observed[observed.score < anchor.threshold]
        fall_ts=None if falling.empty else int(falling.iloc[0].scheduled_ts)
        summary.append({"regime_start_ns":key[0],"direction":key[1],"anchor_ts":key[2],
            "score_path_censored": bool(anchor.score_path_status == "CENSORED") or not required.issubset(actual),
            "max_score":None if observed.empty else float(observed.score.max()), "max_delta_from_p90":None if observed.empty else float((observed.score-anchor.threshold).max()),
            "time_p95_seconds":None if observed[observed.at_or_above_p95].empty else float(observed[observed.at_or_above_p95].iloc[0].score_offset_seconds),
            "time_p97_5_seconds":None if observed[observed.at_or_above_p97_5].empty else float(observed[observed.at_or_above_p97_5].iloc[0].score_offset_seconds),
            "fell_below_p90":not falling.empty,"fall_ts":fall_ts,"recrossed_p90":False if fall_ts is None else bool(((observed.scheduled_ts > fall_ts)&(observed.score >= anchor.threshold)).any())})
    return score, pd.DataFrame(summary)


def _subtypes(anchors: pd.DataFrame, summary: pd.DataFrame) -> pd.DataFrame:
    out=anchors.merge(summary,on=KEY,validate="one_to_one"); labels=[]
    for _, row in out.iterrows():
        full = not row.market_censored and (row.terminal_ts-row.anchor_ts) >= 600*NS
        t=row.time_to_flip_seconds
        if row.market_censored or row.score_path_censored or not full: label="SESSION_CENSORED"
        elif pd.notna(t): label="FAST" if t <= 180 else "LATE" if t <= 300 else "SLOW"
        elif row.fell_below_p90: label="FAILED_WARNING_SCORE_COLLAPSE"
        else: label="FAILED_WARNING_PERSISTENT_HIGH"
        labels.append(label)
    out["warning_subtype"]=labels
    return out


def _incidence(anchors: pd.DataFrame) -> dict[str, Any]:
    payload={"schema_version":1,"horizons_seconds":[*HORIZONS,"RTH"],"populations":{}}
    for name, group in (("pooled",anchors),("LONG",anchors[anchors.direction=="LONG"]),("SHORT",anchors[anchors.direction=="SHORT"])):
        previous=0; rows=[]
        for horizon in HORIZONS:
            observed=group[(~group.market_censored)&((group.terminal_ts-group.anchor_ts)>=horizon*NS)]
            count=int(observed.time_to_flip_seconds.le(horizon).sum()); n=len(observed); increment=count-previous
            rows.append({"horizon_seconds":horizon,"n":n,"cumulative_count":count,"cumulative_rate":count/n if n else None,"increment_count":increment,"increment_rate":increment/n if n else None,"no_flip_count":int(observed.time_to_flip_seconds.isna().sum()),"censor_count":len(group)-n}); previous=count
        payload["populations"][name]=rows
    return payload


def _negative(anchors: pd.DataFrame) -> dict[str, Any]:
    negative=anchors[anchors.time_to_flip_seconds.isna()|anchors.time_to_flip_seconds.gt(180)]
    masks=(("181-240",anchors.time_to_flip_seconds.gt(180)&anchors.time_to_flip_seconds.le(240)),("241-300",anchors.time_to_flip_seconds.gt(240)&anchors.time_to_flip_seconds.le(300)),("301-450",anchors.time_to_flip_seconds.gt(300)&anchors.time_to_flip_seconds.le(450)),("451-600",anchors.time_to_flip_seconds.gt(450)&anchors.time_to_flip_seconds.le(600)),("persistent>600",~anchors.market_censored&anchors.time_to_flip_seconds.isna()&((anchors.terminal_ts-anchors.anchor_ts)>=600*NS)),("no-flip-session",~anchors.market_censored&anchors.time_to_flip_seconds.isna()),("market-censored",anchors.market_censored))
    rows=[]
    for bucket,mask in masks:
        count=int(mask.sum()); rows.append({"bucket":bucket,"n":count,"percent_all":count/len(anchors) if len(anchors) else None,"percent_negative":count/len(negative) if len(negative) else None})
    return {"schema_version":1,"negative_denominator":len(negative),"rows":rows}


def _controls(anchors: pd.DataFrame, observations: pd.DataFrame, score_columns: dict[str,str]) -> dict[str,Any]:
    required={"regime_start_ns","observation_ts","regime_age_seconds","session_open_ts"}
    if not required.issubset(observations): raise FirstP90AnalysisError("FIRST_P90_CONTROL_OBSERVATIONS_SCHEMA_MISSING")
    _assert_2024(observations,"observation_ts"); candidates=[]
    for direction,column in score_columns.items():
        if column not in observations: raise FirstP90AnalysisError("FIRST_P90_CONTROL_SCORE_MISSING")
        x=observations.copy(); x["direction"]=direction; x["score"]=x[column]; candidates.append(x)
    candidates=pd.concat(candidates,ignore_index=True); candidates["age_bucket"]=candidates.regime_age_seconds.map(_age); candidates["tod_cell"]=[_tod(int(t),int(o)) for t,o in zip(candidates.observation_ts,candidates.session_open_ts)]
    selected=[]
    for _,warning in anchors.iterrows():
        before=candidates[(candidates.regime_start_ns==warning.regime_start_ns)&(candidates.direction==warning.direction)&(candidates.age_bucket==warning.age_bucket)&(candidates.tod_cell==warning.tod_cell)&(candidates.observation_ts<warning.anchor_ts)&candidates.score.notna()&(candidates.score<warning.threshold)]
        if not before.empty: selected.append({"cell":f"{warning.direction}|{warning.age_bucket}|{warning.tod_cell}","kind":"firing","score":float(before.sort_values("observation_ts").iloc[-1].score)})
    # Never-fire controls are selected from regimes that contributed no warning at
    # all, using the same frozen directional threshold and the latest valid score
    # below it in each age/TOD cell.  They are not inferred from an outcome label.
    fired_regimes=set(zip(anchors.regime_start_ns, anchors.direction))
    p90_by_direction={side: float(group.threshold.iloc[0]) for side,group in anchors.groupby("direction")}
    for (regime_start, direction, age_bucket, tod_cell), group in candidates.groupby(["regime_start_ns","direction","age_bucket","tod_cell"], sort=True):
        if (regime_start, direction) in fired_regimes: continue
        if direction not in p90_by_direction: continue
        valid=group[group.score.notna() & group.score.lt(p90_by_direction[direction])]
        if not valid.empty:
            selected.append({"cell":f"{direction}|{age_bucket}|{tod_cell}","kind":"never_fire","score":float(valid.sort_values("observation_ts").iloc[-1].score)})
    controls=pd.DataFrame(selected,columns=["cell","kind","score"]); cells=[]
    for cell,warnings in anchors.groupby(anchors.direction+"|"+anchors.age_bucket+"|"+anchors.tod_cell,sort=True):
        ncontrol=int(controls.cell.eq(cell).sum()) if not controls.empty else 0; np90=len(warnings)
        cells.append({"cell":cell,"p90_n":np90,"control_n":ncontrol,"status":"OK" if np90>=30 and ncontrol>=30 else "INSUFFICIENT"})
    return {"schema_version":1,"definition":"firing: latest valid score < P90 in same regime/age/TOD strictly before fire; never_fire: latest valid score < P90 in a regime without a first-P90 fire; cells below 30 are INSUFFICIENT","cells":cells,"selected_controls":controls.to_dict("records")}


def produce_first_p90_warning_horizon(*, study_dir: str|Path, run_dir: str|Path) -> dict[str,Any]:
    study,run=Path(study_dir),Path(run_dir); compiled=_load_json(study/"compiled_study.json"); contract=(compiled.get("contracts") or {}).get("diagnostic_followup") or {}
    gate=require_march_gate(study,expected_first=contract.get("march_first_reference_sha256"),expected_outcome=contract.get("march_outcome_reference_sha256"))
    manifest=_load_json(run/"collection"/"collection_manifest.json")
    if _load_json(run/"status.json").get("status") != "SUCCESS": raise FirstP90AnalysisError("FIRST_P90_COLLECTION_INCOMPLETE")
    diagnostic_path=run/"collection"/"diagnostic_followup.parquet"; observations_path=run/"collection"/"observations.parquet"
    if not diagnostic_path.is_file() or manifest.get("diagnostic_followup",{}).get("sha256") != sha256_file(diagnostic_path): raise FirstP90AnalysisError("FIRST_P90_DIAGNOSTIC_STALE")
    if not observations_path.is_file(): raise FirstP90AnalysisError("FIRST_P90_CONTROL_OBSERVATIONS_MISSING")
    diagnostic=pd.read_parquet(diagnostic_path); _validate(diagnostic); anchors=_anchors(diagnostic,contract.get("thresholds") or {}); score,summary=_score_summary(anchors,diagnostic,contract["thresholds"]); anchors=_subtypes(anchors,summary)
    artifacts,results=study/"artifacts",study/"results"; artifacts.mkdir(exist_ok=True); results.mkdir(exist_ok=True)
    anchors[KEY+["flip_ts","time_to_flip_seconds","market_censored","score_path_censored","warning_subtype","age_bucket","quarter","tod_cell"]].to_parquet(artifacts/"first_p90_time_to_flip_detail.parquet",index=False); score.to_parquet(artifacts/"first_p90_score_evolution.parquet",index=False)
    lineage={"schema_version":1,"data_class":"descriptive_post_warning_diagnostic_unusable_as_model_input","model_changed":"NO","thresholds_changed":"NO","stage2_execution":"NOT_RUN","authorized_years":[2024],"prohibited_years":[2025,2026],"parent_candidates_sha256":contract.get("parent_candidates_sha256"),"parent_observations_sha256":contract.get("parent_observations_sha256"),"frozen_thresholds":contract.get("thresholds"),"march_references":{"first":contract.get("march_first_reference_sha256"),"outcome":contract.get("march_outcome_reference_sha256")},"march_gate":gate,"diagnostic_parquet_sha256":sha256_file(diagnostic_path),"observations_parquet_sha256":sha256_file(observations_path),"collection_manifest_sha256":sha256_file(run/"collection"/"collection_manifest.json"),"analysis_implementation_sha256":sha256_file(Path(__file__))}; lineage["identity_sha256"]=canonical_sha256(lineage)
    payloads={"first_p90_warning_horizon_contract.json":lineage,"first_p90_cumulative_incidence.json":_incidence(anchors),"first_p90_negative_decomposition.json":_negative(anchors),"first_p90_control_comparison.json":_controls(anchors,pd.read_parquet(observations_path),contract.get("score_columns") or {}),"first_p90_warning_subtypes.json":{"schema_version":1,"n":len(anchors),"counts":{k:int(v) for k,v in anchors.warning_subtype.value_counts().sort_index().items()},"quarterly_descriptive":anchors.groupby(["quarter","warning_subtype"]).size().rename("n").reset_index().to_dict("records")}}
    for name,payload in payloads.items(): (artifacts/name).write_text(json.dumps(payload,indent=2,default=str)+"\n",encoding="utf-8")
    (results/"FIRST_P90_WARNING_HORIZON_REPORT.md").write_text("# First P90 warning horizon\n\nDescriptive post-warning diagnostic only. No model, threshold, tuning, Stage-2 execution, or new OOS was performed.\n\n"+f"Warnings: {len(anchors)}. Subtypes: {payloads['first_p90_warning_subtypes.json']['counts']}.\n",encoding="utf-8")
    return {"rows":len(anchors),"identity_sha256":lineage["identity_sha256"],"artifacts":[str(artifacts/name) for name in payloads]+[str(artifacts/"first_p90_time_to_flip_detail.parquet"),str(artifacts/"first_p90_score_evolution.parquet"),str(results/"FIRST_P90_WARNING_HORIZON_REPORT.md")]}
