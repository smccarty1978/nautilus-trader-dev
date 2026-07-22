import importlib.util
from pathlib import Path
import numpy as np

P=Path(__file__).parents[1]/"implementation"/"pipeline.py"
s=importlib.util.spec_from_file_location("strict_long_pipeline",P); m=importlib.util.module_from_spec(s); s.loader.exec_module(m)

def test_exact_feature_contracts_and_mapping():
    c=m.load_contracts(); assert len(c["LONG_STRICT_top25_gbt_v2"])==25; assert len(c["LONG_STRICT_top103_gbt_v2"])==103
    rows=m.load_mapping(c["LONG_STRICT_top103_gbt_v2"]); assert not [r for r in rows if r["status"]=="UNRESOLVED"]
    assert next(r for r in rows if r["long_model_feature"]=="pct_levels_behind_trade")["mapping_type"]=="DIRECTION_NORMALIZED_IDENTITY"

def test_strict_second_boundary_last_permitted_first_prohibited():
    ts=np.array([0,1,2])*1_000_000_000; obs=np.array([1_000_000_000]); idx=m.strict_snap_indices(ts,obs)
    assert idx.tolist()==[0] and ts[idx[0]] < obs[0] and ts[idx[0]+1] == obs[0]

def test_strict_minute_boundary_and_coincident_ordering():
    ts=np.arange(0,66)*1_000_000_000; obs=np.array([60_000_000_000,65_000_000_000])
    rec=m.attachment_timing_trace(ts,obs)
    assert rec[0]=={"observation_time":60_000_000_000,"latest_source_ts_used":59_000_000_000,"latest_1m_bar_close_ts_used":None}
    assert rec[1]=={"observation_time":65_000_000_000,"latest_source_ts_used":64_000_000_000,"latest_1m_bar_close_ts_used":60_000_000_000}

def test_prefix_invariance():
    full=np.arange(100)*1_000_000_000; obs=np.array([10_000_000_000,50_000_000_000])
    assert np.array_equal(m.strict_snap_indices(full,obs),m.strict_snap_indices(full[:51],obs))

def test_authoritative_attachment_boundary_provenance():
    import pandas as pd
    p=m.SOURCE_ATTACH/"attached_long_2025.parquet"
    df=pd.read_parquet(p,columns=["observation_time","latest_source_ts_used","latest_1m_bar_close_ts_used"])
    boundary=df[df.observation_time % (60*1_000_000_000) == 0]
    assert len(boundary)>0
    assert (boundary.latest_source_ts_used < boundary.observation_time).all()
    assert (boundary.latest_1m_bar_close_ts_used.dropna() < boundary.loc[boundary.latest_1m_bar_close_ts_used.notna(),"observation_time"]).all()

def test_complete_one_hot_materialization_and_order():
    import pandas as pd
    features=["x","rolling_5m_high_position__ABOVE","rolling_5m_high_position__BELOW",
              "rolling_5m_high_position__UNAVAILABLE","rolling_5m_high_position__TOUCH"]
    df=pd.DataFrame({"x":[1,2,3,4],"rolling_5m_high_position":["ABOVE","BELOW",None,"TOUCH"]})
    got=m.materialize_frozen_features(df,features)
    assert got[features[1:]].sum(axis=1).tolist()==[1,1,1,1]
    assert got[features[1:]].to_numpy().tolist()==[[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]

def test_one_hot_rejects_unknown_and_overwrites_partial_group():
    import pandas as pd, pytest
    features=["rolling_5m_high_position__ABOVE","rolling_5m_high_position__BELOW",
              "rolling_5m_high_position__UNAVAILABLE","rolling_5m_high_position__TOUCH"]
    with pytest.raises(RuntimeError,match="unknown categories"):
        m.materialize_frozen_features(pd.DataFrame({"rolling_5m_high_position":["SIDEWAYS"]}),features)
    partial=pd.DataFrame({"rolling_5m_high_position":["BELOW"],features[0]:[1]})
    got=m.materialize_frozen_features(partial,features)
    assert got[features].to_numpy().tolist()==[[0,1,0,0]]

def test_tiny_model_fit_reload(tmp_path):
    from sklearn.ensemble import HistGradientBoostingClassifier
    import joblib
    x=np.arange(250,dtype=float).reshape(10,25); y=np.array([0,1]*5)
    model=HistGradientBoostingClassifier(**m.PARAMS).fit(x,y); p=tmp_path/"m.joblib"; joblib.dump(model,p)
    re=joblib.load(p); assert re.classes_.tolist()==[0,1]; assert np.array_equal(model.predict_proba(x),re.predict_proba(x))
