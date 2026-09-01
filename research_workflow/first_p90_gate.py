"""Fail-closed March parity gate for anchored first-P90 diagnostic runs."""
from __future__ import annotations
import hashlib, json
from pathlib import Path
import pandas as pd
from research_workflow.first_p90_warning import MARCH_IDENTITY_FIELDS, MARCH_OUTCOME_FIELDS

class FirstP90MarchGateError(RuntimeError): pass
def _sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def _keys(*dfs):
    return [c for c in ("direction","regime_id","regime_start_ns","checkpoint_index","anchor_ts","scheduled_ts","research_first_P90_ts","nt_first_P90_ts") if all(c in x for x in dfs)]
def _dupes(df, keys): return int(df.duplicated(keys, keep=False).sum()) if keys else len(df)

def evaluate_march_gate(study_dir, actual, *, pinned_first, pinned_outcome, expected_first_sha256=None, expected_outcome_sha256=None):
    """Fail closed on any reference hash, identity, duplicate, or outcome mismatch."""
    study, actual, first, outcome = map(Path, (study_dir, actual, pinned_first, pinned_outcome))
    result={"schema_version":2,"status":"FAIL","actual_path":str(actual),"reference_first_path":str(first),"reference_outcome_path":str(outcome)}
    for label,path,expected in (("reference_first",first,expected_first_sha256),("reference_outcome",outcome,expected_outcome_sha256)):
        if not path.is_file(): result["reason"]=f"{label.upper()}_MISSING"; break
        result[f"{label}_sha256"]=_sha(path)
        if expected and result[f"{label}_sha256"] != expected: result["reason"]=f"{label.upper()}_HASH_MISMATCH"; break
    else:
        if not actual.is_file(): result["reason"]="MARCH_EXTRACTION_MISSING"
        else:
            result["actual_sha256"]=_sha(actual); got,exp,out=pd.read_parquet(actual),pd.read_parquet(first),pd.read_parquet(outcome)
            # Exact identity means every identity component emitted by the pinned
            # reference must also be emitted by the extraction.  Intersecting the
            # columns would allow an extractor to silently drop checkpoint identity.
            expected_identity=[c for c in MARCH_IDENTITY_FIELDS if c in exp]
            keys=expected_identity if all(c in got for c in expected_identity) else []
            okeys=expected_identity if all(c in out and c in got for c in expected_identity) else []
            result["identity_columns"]=keys; result["outcome_identity_columns"]=okeys
            result["actual_rows"],result["expected_rows"]=len(got),len(exp)
            counts={str(k):int(v) for k,v in exp.direction.value_counts().items()} if "direction" in exp else {}
            result["expected_direction_counts"]=counts; result["duplicate_actual"],result["duplicate_reference"]=_dupes(got,keys),_dupes(exp,keys)
            aset=set(map(tuple,got[keys].itertuples(index=False,name=None))) if keys else set(); eset=set(map(tuple,exp[keys].itertuples(index=False,name=None))) if keys else set()
            result["missing_identity_count"],result["extra_identity_count"]=len(eset-aset),len(aset-eset)
            identity=bool(keys) and len(got)==len(exp)==239 and counts=={"LONG":115,"SHORT":124} and not any(result[k] for k in ("duplicate_actual","duplicate_reference","missing_identity_count","extra_identity_count"))
            cols=MARCH_OUTCOME_FIELDS
            result["outcome_columns"]=[c for c in cols if c in got and c in out]
            if okeys and len(result["outcome_columns"])==len(cols):
                left=got[okeys+list(cols)].sort_values(okeys).reset_index(drop=True); right=out[okeys+list(cols)].sort_values(okeys).reset_index(drop=True)
                result["outcome_mismatch_count"]=0 if left.equals(right) else max(len(left),len(right))
            else: result["outcome_mismatch_count"]=1
            result["status"]="PASS" if identity and result["outcome_mismatch_count"]==0 else "FAIL"
            result["reason"]="PASS" if result["status"]=="PASS" else ("FIRST_FIRE_IDENTITY_MISMATCH" if not identity else "FIRST_180_OUTCOME_MISMATCH")
    p=study/"artifacts"/"first_p90_march_gate.json"; p.parent.mkdir(exist_ok=True); p.write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8"); return result

def require_march_gate(study_dir, *, expected_first=None, expected_outcome=None):
    p=Path(study_dir)/"artifacts"/"first_p90_march_gate.json"
    if not p.is_file(): raise FirstP90MarchGateError("FIRST_P90_MARCH_GATE_REQUIRED")
    d=json.loads(p.read_text()); actual=Path(d.get("actual_path", ""))
    if d.get("status")!="PASS": raise FirstP90MarchGateError("FIRST_P90_MARCH_GATE_FAILED")
    if not actual.is_file() or d.get("actual_sha256") != _sha(actual): raise FirstP90MarchGateError("FIRST_P90_MARCH_GATE_STALE")
    for label, expected in (("reference_first", expected_first), ("reference_outcome", expected_outcome)):
        ref=Path(d.get(f"{label}_path", ""))
        if expected and (not ref.is_file() or d.get(f"{label}_sha256") != expected or _sha(ref) != expected):
            raise FirstP90MarchGateError("FIRST_P90_MARCH_GATE_STALE")
    return d
