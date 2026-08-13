import importlib.util
from pathlib import Path
import numpy as np
s=importlib.util.spec_from_file_location('a',Path(__file__).parents[1]/'implementation'/'run_audit.py'); m=importlib.util.module_from_spec(s); s.loader.exec_module(m)
def test_calibration_exact():
    y=np.array([0,1,0,1]); p=np.array([.1,.9,.2,.8]); ece,mce,rows=m.calibration(y,p,2); assert np.isclose(ece,.15) and np.isclose(mce,.15)
def test_thresholds_are_frozen(): assert m.QS==[.99,.975,.95,.925,.90]
def test_decision_both_branches():
    assert m.deployment_recommendation({"a":True,"b":True})=="Deploy Top25"
    assert m.deployment_recommendation({"a":True,"b":False})=="Deploy Top103"
def test_independent_years_deduplicates_model_rows():
    rows=[{"year":2025,"evaluation_status":"FROZEN_DEVELOPMENT"},{"year":2025,"evaluation_status":"FROZEN_DEVELOPMENT"},{"year":2024,"evaluation_status":"IN_SAMPLE_TRAINING_DIAGNOSTIC"}]
    assert m.independent_development_years(rows)==1
def test_rth_day_count_includes_days_with_any_rth_bar():
    import pandas as pd
    idx=pd.DatetimeIndex(["2025-01-02 14:30:00Z","2025-01-02 21:30:00Z","2025-01-03 15:00:00Z"])
    assert m.count_rth_dates(idx)==2
def test_native_importance_is_nonnegative_and_complete():
    _,model,fs=m.artifact("Top103"); gain,split=m.native_importance(model,len(fs))
    assert len(gain)==len(split)==103 and (gain>=0).all() and (split>=0).all() and split.sum()>0
