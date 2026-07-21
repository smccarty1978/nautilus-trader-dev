from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import numpy as np
import pandas as pd

P=Path(__file__).resolve().parents[1]/"run_study.py"; S=spec_from_file_location("runner",P); mod=module_from_spec(S); S.loader.exec_module(mod)
NS=1_000_000_000; BASE=1_700_000_000_000_000_000

def bars(n=15):
    idx=pd.to_datetime(BASE+np.arange(n,dtype=np.int64)*NS,utc=True)
    return pd.DataFrame({"open":100.,"high":100.25,"low":99.75,"close":100.,"volume":1.},index=idx)

def keep_above_long_floor(raw,start,stop):
    raw.iloc[start:stop,raw.columns.get_loc("open")]=102.
    raw.iloc[start:stop,raw.columns.get_loc("high")]=102.5
    raw.iloc[start:stop,raw.columns.get_loc("low")]=101.5
    raw.iloc[start:stop,raw.columns.get_loc("close")]=102.

def trade(outcome="pt_first",res=5,horizon=10,direction=1):
    return pd.Series({"entry_fill_ts":BASE+NS,"entry_fill_open":100.,"atr_at_checkpoint":4.,"entry_direction":direction,
      "scheduled_exit_decision_ts":BASE+horizon*NS,"resolution_ts":BASE+res*NS,"outcome":outcome,
      "pt_px":105. if direction==1 else 95.,"sl_px":95. if direction==1 else 105.})

def test_v0_pt_then_horizon_runner():
    raw=bars(); raw.iloc[10,raw.columns.get_loc("open")]=103.
    r=mod.run_runner(trade(),raw,None,None)
    assert r["runner_exit_reason"]=="runner_regime_flip_exit" and r["runner_exit_px"]==103.

def test_initial_sl_exits_runner_before_horizon():
    r=mod.run_runner(trade(outcome="sl_first",res=4),bars(),None,None)
    assert r["runner_exit_reason"]=="runner_initial_sl_exit" and r["runner_exit_px"]==95.

def test_long_initial_sl_adverse_gap_uses_open_and_excludes_exit_bar_mfe():
    raw=bars(); raw.iloc[4,raw.columns.get_loc("open")]=94.; raw.iloc[4,raw.columns.get_loc("high")]=110.
    raw.iloc[4,raw.columns.get_loc("low")]=93.; raw.iloc[4,raw.columns.get_loc("close")]=100.
    r=mod.run_runner(trade(outcome="sl_first",res=4),raw,None,None)
    assert r["runner_exit_px"]==94. and r["runner_max_available_mfe_atr"]<2.5

def test_short_initial_sl_adverse_gap_uses_open():
    raw=bars(); raw.iloc[4,raw.columns.get_loc("open")]=106.; raw.iloc[4,raw.columns.get_loc("high")]=107.
    r=mod.run_runner(trade(outcome="sl_first",res=4,direction=-1),raw,None,None)
    assert r["runner_exit_px"]==106.

def test_contract1_uses_same_adverse_gap_fill_as_runner():
    long_px,long_gross=mod.contract1_fill_and_gross(trade(outcome="sl_first"),94.)
    short_px,short_gross=mod.contract1_fill_and_gross(trade(outcome="sl_first",direction=-1),106.)
    assert (long_px,long_gross)==(94.,-120.)
    assert (short_px,short_gross)==(106.,-120.)

def test_horizon_before_contract_resolution_exits_runner_only_at_horizon():
    raw=bars(); raw.iloc[6,raw.columns.get_loc("open")]=101.
    r=mod.run_runner(trade(res=9,horizon=6),raw,None,None)
    assert r["runner_exit_ts"]==BASE+6*NS and r["runner_exit_reason"]=="runner_regime_flip_exit"

def test_arm_bar_floor_touch_is_deferred_until_later_bar():
    raw=bars(); raw.iloc[2,raw.columns.get_loc("high")]=103.; raw.iloc[2,raw.columns.get_loc("low")]=100.5
    raw.iloc[3,raw.columns.get_loc("low")]=100.5
    r=mod.run_runner(trade(res=7),raw,.75,.25)
    assert r["arm_floor_same_bar_deferred"] and r["runner_exit_ts"]==BASE+3*NS

def test_pt_and_active_floor_same_bar_defers_floor():
    raw=bars(); raw.iloc[2,raw.columns.get_loc("high")]=103.; raw.iloc[2,raw.columns.get_loc("low")]=100.5
    keep_above_long_floor(raw,3,5)
    raw.iloc[5,raw.columns.get_loc("high")]=105.; raw.iloc[5,raw.columns.get_loc("low")]=100.5
    raw.iloc[6,raw.columns.get_loc("low")]=100.5
    r=mod.run_runner(trade(res=5),raw,.75,.25)
    assert r["pt_floor_same_bar_deferred"] and r["runner_exit_ts"]==BASE+6*NS

def test_horizon_open_precedes_floor_range():
    raw=bars(); raw.iloc[2,raw.columns.get_loc("high")]=103.; raw.iloc[10,raw.columns.get_loc("low")]=99.
    keep_above_long_floor(raw,3,10)
    raw.iloc[10,raw.columns.get_loc("open")]=102.
    r=mod.run_runner(trade(res=5),raw,.75,.25)
    assert r["horizon_floor_same_timestamp"] and r["runner_exit_px"]==102.
    assert r["runner_max_available_mfe_atr"]<2.5

def test_floor_exit_bar_favorable_extreme_is_excluded_from_mfe():
    raw=bars(); raw.iloc[2,raw.columns.get_loc("high")]=103.
    raw.iloc[3,raw.columns.get_loc("high")]=110.; raw.iloc[3,raw.columns.get_loc("low")]=100.5
    r=mod.run_runner(trade(res=7),raw,.75,.25)
    assert r["runner_exit_reason"]=="runner_floor_exit"
    assert r["runner_max_available_mfe_atr"]==.75

def test_short_floor_geometry():
    raw=bars(); raw.iloc[2,raw.columns.get_loc("low")]=96.
    raw.iloc[3,raw.columns.get_loc("open")]=97.; raw.iloc[3,raw.columns.get_loc("close")]=97.
    raw.iloc[3,raw.columns.get_loc("high")]=99.5; raw.iloc[3,raw.columns.get_loc("low")]=96.5
    r=mod.run_runner(trade(res=7,direction=-1),raw,1.,.5)
    assert r["runner_exit_reason"]=="runner_floor_exit" and r["runner_exit_px"]==98.

def test_adverse_gap_floor_fill():
    assert mod.stop_fill(1,101.,100.)==100.
    assert mod.stop_fill(-1,99.,100.)==100.

def test_first_favorable_touch_excludes_horizon_bar():
    raw=bars(); raw.iloc[10,raw.columns.get_loc("high")]=110.
    assert pd.isna(mod.first_favorable_touch_ts(trade(),raw,2.))

def test_long_floor_and_2a_same_bar_is_unordered():
    raw=bars(); raw.iloc[2,raw.columns.get_loc("high")]=103.
    raw.iloc[3,raw.columns.get_loc("high")]=108.; raw.iloc[3,raw.columns.get_loc("low")]=100.5
    t=trade(res=7); r=mod.run_runner(t,raw,.75,.25); touch=mod.first_favorable_touch_ts(t,raw,2.)
    ordered,ambiguous=mod.floor_before_touch(True,r["runner_exit_ts"],touch)
    assert pd.isna(ordered) and ambiguous

def test_short_floor_and_2a_same_bar_is_unordered():
    raw=bars(); raw.iloc[2,raw.columns.get_loc("low")]=97.
    raw.iloc[3,raw.columns.get_loc("low")]=92.; raw.iloc[3,raw.columns.get_loc("high")]=99.5
    t=trade(res=7,direction=-1); r=mod.run_runner(t,raw,.75,.25); touch=mod.first_favorable_touch_ts(t,raw,2.)
    ordered,ambiguous=mod.floor_before_touch(True,r["runner_exit_ts"],touch)
    assert pd.isna(ordered) and ambiguous
