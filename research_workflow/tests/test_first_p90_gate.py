import json
import pandas as pd
import pytest
from research_workflow.first_p90_gate import evaluate_march_gate, require_march_gate, FirstP90MarchGateError

def test_gate_rejects_missing_and_identity_mismatch(tmp_path):
    (tmp_path/'artifacts').mkdir(); ref=tmp_path/'ref.parquet'; out=tmp_path/'out.parquet'
    df=pd.DataFrame({'regime_start_ns':range(239),'checkpoint_index':range(239),'direction':['LONG']*115+['SHORT']*124,'flip_ts':range(239),'time_to_flip_seconds':range(239),'target_flip_within_horizon':[1]*239,'censored':[False]*239,'censor_reason':[None]*239,'disposition':['LABELED_POSITIVE']*239})
    df.to_parquet(ref); df.assign(checkpoint_index=0).to_parquet(out)
    assert evaluate_march_gate(tmp_path,out,pinned_first=ref,pinned_outcome=ref)['status']=='FAIL'
    with pytest.raises(FirstP90MarchGateError): require_march_gate(tmp_path)

def test_gate_requires_exact_239_identity(tmp_path):
    (tmp_path/'artifacts').mkdir(); ref=tmp_path/'ref.parquet'; out=tmp_path/'out.parquet'
    df=pd.DataFrame({'regime_start_ns':range(239),'checkpoint_index':range(239),'direction':['LONG']*115+['SHORT']*124,'flip_ts':range(239),'time_to_flip_seconds':range(239),'target_flip_within_horizon':[1]*239,'censored':[False]*239,'censor_reason':[None]*239,'disposition':['LABELED_POSITIVE']*239})
    df.to_parquet(ref); df.to_parquet(out)
    assert evaluate_march_gate(tmp_path,out,pinned_first=ref,pinned_outcome=ref)['status']=='PASS'


def test_gate_rejects_dropped_reference_identity_component(tmp_path):
    (tmp_path/'artifacts').mkdir(); ref=tmp_path/'ref.parquet'; out=tmp_path/'out.parquet'
    df=pd.DataFrame({'regime_start_ns':range(239),'checkpoint_index':range(239),'direction':['LONG']*115+['SHORT']*124,'flip_ts':range(239),'time_to_flip_seconds':range(239),'target_flip_within_horizon':[1]*239,'censored':[False]*239,'censor_reason':[None]*239,'disposition':['LABELED_POSITIVE']*239})
    df.to_parquet(ref); df.drop(columns=['checkpoint_index']).to_parquet(out)
    assert evaluate_march_gate(tmp_path,out,pinned_first=ref,pinned_outcome=ref)['status']=='FAIL'
