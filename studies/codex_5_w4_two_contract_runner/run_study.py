"""Run fixed two-contract PT1 plus frozen-horizon runner diagnostics."""
from __future__ import annotations

import argparse, hashlib, json, re
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
STUDY = Path(__file__).resolve().parent
RESULTS, WORK, AUDIT = STUDY / "results", STUDY / "_work", STUDY / "audit"
CONFIG_PATH, FREEZE_PATH = STUDY / "config.json", STUDY / "input_freeze.json"
PRE_AUDIT, PRE_AUTH = AUDIT / "pre_execution_audit.md", AUDIT / "pre_execution_authorization.json"
BRACKET = ROOT / "studies" / "codex_5_w4_symmetric_bracket_race"
POLICY = ROOT / "studies" / "codex_5_w4_multi_candidate_reentry"
RAW = {2025: ROOT / "data" / "raw" / "NQ_v0_1s_2025.parquet",
       2026: ROOT / "data" / "raw" / "NQ_v0_1s_2026_ytd.parquet"}
NS, MULTIPLIER, COST = 1_000_000_000, 20.0, 10.0
for d in (RESULTS, WORK, AUDIT): d.mkdir(parents=True, exist_ok=True)


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def script_sha256(): return sha(Path(__file__).resolve())


def input_hashes():
    return {"bracket_results": sha(BRACKET/"results"/"w4_symmetric_bracket_results.parquet"),
        "bracket_trade_diffs": sha(BRACKET/"results"/"w4_symmetric_bracket_trade_diffs.parquet"),
        "bracket_tail_diagnostics": sha(BRACKET/"results"/"w4_symmetric_bracket_tail_diagnostics.parquet"),
        "bracket_completion_audit": sha(BRACKET/"audit"/"completion_audit.md"),
        "bracket_manifest": sha(BRACKET/"results"/"run_manifest.json"),
        "policy_a_results": sha(POLICY/"results"/"multi_candidate_policy_results.parquet"),
        "policy_a_opportunities": sha(POLICY/"results"/"multi_candidate_opportunity_results.parquet"),
        "policy_a_completion_audit": sha(POLICY/"audit"/"completion_audit.md"),
        "policy_a_manifest": sha(POLICY/"results"/"run_manifest.json"),
        "raw_2025": sha(RAW[2025]), "raw_2026": sha(RAW[2026])}


def require_authorization():
    if not PRE_AUDIT.exists() or not PRE_AUTH.exists(): raise RuntimeError("missing authorization")
    text = PRE_AUDIT.read_text(encoding="utf-8")
    if not (re.search(r"^\*\*Status:\*\*\s+\*\*PASS", text, re.M) and
            re.search(r"^\*\*Findings:\*\*\s+\*\*0 CRITICAL, 0 WARNING\*\*\s*$", text, re.M)):
        raise RuntimeError("audit not clean")
    auth=json.loads(PRE_AUTH.read_text())
    expected={"status":"PASS","script_sha256":script_sha256(),"config_sha256":sha(CONFIG_PATH),
              "freeze_sha256":sha(FREEZE_PATH),"audit_sha256":sha(PRE_AUDIT)}
    if any(auth.get(k)!=v for k,v in expected.items()): raise RuntimeError("stale authorization")


def validate_contract():
    c=json.loads(CONFIG_PATH.read_text()); f=json.loads(FREEZE_PATH.read_text())
    if f.get("status")!="FROZEN_BEFORE_NEW_CODE_EXECUTION" or input_hashes()!=f.get("input_sha256"):
        raise RuntimeError("freeze mismatch")
    if f.get("population_count")!=4383 or f.get("population_count_by_year")!={"2025":3246,"2026":1137}:
        raise RuntimeError("population mismatch")
    expected=[("V0",None,None),("V75_25",.75,.25),("V100_50",1.0,.5)]
    if [(x.get("variant_id"),x.get("arm_atr"),x.get("floor_atr")) for x in c["variants"]]!=expected:
        raise RuntimeError("variant change")
    fixed={"population_count":4383,"pt1_atr":1.25,"initial_stop_atr":1.25,
      "arm_activation":"after_arming_bar_for_later_bars",
      "pt_and_active_floor_same_bar":"pt1_first_floor_deferred",
      "initial_sl_with_favorable_event_same_bar":"initial_sl_first",
      "initial_stop_gap_fill":"adverse_open_for_both_contracts",
      "stop_exit_bar_excursion":"exclude_entire_ambiguous_exit_bar",
      "floor_and_tail_level_same_bar":"unordered_mark_ambiguous",
      "horizon_same_timestamp_order":"horizon_open_before_bar_range","runner_exists_from_entry":True,
      "runner_horizon_before_pt1":"runner_exits_horizon_contract1_continues_bracket",
      "multiplier_usd_per_point":20.0,"cost_per_contract_rt_usd":10.0,
      "development_year":2025,"selection_isolated_year":2026}
    if any(c.get(k)!=v for k,v in fixed.items()): raise RuntimeError("contract changed")
    return c


def validate_raw(raw):
    if not isinstance(raw.index,pd.DatetimeIndex) or raw.index.tz is None or not raw.index.is_monotonic_increasing or raw.index.has_duplicates:
        raise RuntimeError("raw timestamps")
    o,h,l,c=(raw[x].to_numpy(float) for x in ("open","high","low","close"))
    if not np.isfinite(np.c_[o,h,l,c]).all() or np.any(h<np.maximum(o,c)) or np.any(l>np.minimum(o,c)):
        raise RuntimeError("raw geometry")


def primary_population(year):
    d=pd.read_parquet(BRACKET/"results"/"w4_symmetric_bracket_trade_diffs.parquet")
    d=d[(d.year==year)&(d.bracket_atr==1.25)&(d.tie_policy=="conservative")].sort_values("entry_fill_ts").reset_index(drop=True)
    if len(d)!={2025:3246,2026:1137}[year] or d.outcome.eq("unresolved").any():
        raise RuntimeError("primary bracket reconciliation")
    return d


def reconcile_policy_a(pop,year):
    p=pd.read_parquet(POLICY/"results"/"multi_candidate_opportunity_results.parquet")
    p=p[(p.policy_id=="R0")&(p.executed)&(p.year==year)].sort_values("entry_fill_ts").reset_index(drop=True)
    b=pop.sort_values("entry_fill_ts").reset_index(drop=True)
    if len(p)!={2025:3246,2026:1137}[year] or p.entry_fill_ts.duplicated().any():
        raise RuntimeError("Policy A population count/uniqueness")
    exact=(np.array_equal(p.entry_fill_ts.to_numpy(np.int64),b.entry_fill_ts.to_numpy(np.int64)) and
           np.array_equal(p.entry_direction.to_numpy(int),b.entry_direction.to_numpy(int)) and
           np.array_equal(p.actual_entry_session.astype(str).to_numpy(),b.session.astype(str).to_numpy()) and
           np.allclose(p.entry_fill_px.to_numpy(float),b.entry_fill_open.to_numpy(float),rtol=0,atol=0) and
           np.allclose(p.atr_at_checkpoint.to_numpy(float),b.atr_at_checkpoint.to_numpy(float),rtol=0,atol=0))
    if not exact: raise RuntimeError("Policy A entry reconciliation")
    agg=pd.read_parquet(POLICY/"results"/"multi_candidate_policy_results.parquet")
    a=agg[(agg.policy_id=="R0")&(agg.split_type=="year")&(agg.split_value.astype(str)==str(year))]
    if len(a)!=1 or int(a.iloc[0].trades_executed)!=len(p) or not np.isclose(float(a.iloc[0].total_net_pnl_usd),p.net_pnl_usd.sum()):
        raise RuntimeError("Policy A aggregate reconciliation")
    return p.set_index(p.entry_fill_ts.to_numpy(np.int64),drop=False)


def stop_fill(direction, stop, open_px):
    return open_px if ((direction==1 and open_px<=stop) or (direction==-1 and open_px>=stop)) else stop


def contract1_fill_and_gross(t,resolution_open):
    exit_px=(float(t.pt_px) if t.outcome=="pt_first" else
             stop_fill(int(t.entry_direction),float(t.sl_px),float(resolution_open)))
    gross=int(t.entry_direction)*(exit_px-float(t.entry_fill_open))*MULTIPLIER
    return exit_px,gross


def run_runner(t, raw, arm_atr, floor_atr):
    ts=raw.index.view(np.int64); o=raw.open.to_numpy(float); h=raw.high.to_numpy(float); l=raw.low.to_numpy(float)
    entry=float(t.entry_fill_open); atr=float(t.atr_at_checkpoint); direction=int(t.entry_direction)
    start=int(np.searchsorted(ts,int(t.entry_fill_ts),side="left")); horizon=int(np.searchsorted(ts,int(t.scheduled_exit_decision_ts),side="left"))
    res=int(np.searchsorted(ts,int(t.resolution_ts),side="left")); pt=float(t.pt_px); sl=float(t.sl_px)
    if start>=len(ts) or horizon>=len(ts) or res>=len(ts): raise RuntimeError("path boundary")
    floor=entry+direction*floor_atr*atr if floor_atr is not None else np.nan
    armed=False; active_from=len(ts)+1; arm_ts=pd.NA; pt_hit=False; pt_i=None
    exit_i=None; exit_px=np.nan; reason=None; pt_floor_deferred=False; arm_floor_deferred=False; horizon_floor_same=False
    max_fav=0.0
    for i in range(start, min(max(horizon,res)+1,len(ts))):
        now=int(ts[i]); open_px=float(o[i])
        if i==horizon:
            high=float(h[i]); low=float(l[i])
            horizon_floor_same=bool((low<=floor if direction==1 else high>=floor) if armed and i>=active_from else False)
            exit_i=i; exit_px=open_px; reason="runner_regime_flip_exit"; break
        contract_event=(i==res)
        if contract_event and t.outcome=="sl_first":
            exit_i=i; exit_px=stop_fill(direction,sl,open_px); reason="runner_initial_sl_exit"; break
        high=float(h[i]); low=float(l[i])
        favorable=max((high-entry) if direction==1 else (entry-low),0.0)/atr
        floor_touch=(low<=floor if direction==1 else high>=floor) if armed and i>=active_from else False
        pt_event=bool(contract_event and t.outcome=="pt_first")
        if pt_event:
            pt_hit=True; pt_i=i
            if floor_touch: pt_floor_deferred=True
        elif floor_touch:
            exit_i=i; exit_px=stop_fill(direction,floor,open_px); reason="runner_floor_exit"; break
        max_fav=max(max_fav,favorable)
        if arm_atr is not None and not armed and favorable>=arm_atr:
            armed=True; arm_ts=now; active_from=i+1
            raw_floor_touch=(low<=floor if direction==1 else high>=floor)
            arm_floor_deferred=bool(raw_floor_touch)
    if exit_i is None:
        raise RuntimeError("runner did not exit")
    gross=direction*(float(exit_px)-entry)*MULTIPLIER
    hold=(int(ts[exit_i])-int(t.entry_fill_ts))/NS
    realized_atr=direction*(float(exit_px)-entry)/atr
    giveback=max_fav-realized_atr
    return {"runner_exit_ts":int(ts[exit_i]),"runner_exit_px":float(exit_px),"runner_exit_reason":reason,
      "runner_gross_pnl_usd":gross,"runner_net_pnl_usd":gross-COST,"runner_hold_s":hold,
      "runner_realized_pnl_atr":realized_atr,"runner_max_available_mfe_atr":max_fav,
      "runner_giveback_atr":giveback,"floor_armed":armed,"floor_armed_ts":arm_ts,
      "floor_px":floor,"pt1_hit_before_runner_exit":bool(pt_i is not None and pt_i<=exit_i),
      "pt_floor_same_bar_deferred":pt_floor_deferred,"arm_floor_same_bar_deferred":arm_floor_deferred,
      "horizon_floor_same_timestamp":horizon_floor_same}


def first_favorable_touch_ts(t, raw, level_atr):
    ts=raw.index.view(np.int64); h=raw.high.to_numpy(float); l=raw.low.to_numpy(float)
    a=int(np.searchsorted(ts,int(t.entry_fill_ts),side="left")); b=int(np.searchsorted(ts,int(t.scheduled_exit_decision_ts),side="left"))
    if a>=b: return pd.NA
    entry=float(t.entry_fill_open); atr=float(t.atr_at_checkpoint); d=int(t.entry_direction)
    hits=np.flatnonzero(h[a:b]>=entry+level_atr*atr) if d==1 else np.flatnonzero(l[a:b]<=entry-level_atr*atr)
    return int(ts[a+int(hits[0])]) if len(hits) else pd.NA


def floor_before_touch(floor_exit,exit_ts,touch_ts):
    """Return ordered floor-before-level label plus an OHLC same-bar ambiguity flag."""
    if not floor_exit: return False,False
    if pd.isna(touch_ts): return True,False
    if int(exit_ts)==int(touch_ts): return pd.NA,True
    return bool(int(exit_ts)<int(touch_ts)),False


def simulate_year(year,raw,config):
    pop=primary_population(year); rows=[]; tails=[]; protective=[]
    policy_a=reconcile_policy_a(pop,year)
    frozen_tail=pd.read_parquet(BRACKET/"results"/"w4_symmetric_bracket_tail_diagnostics.parquet")
    frozen_tail=frozen_tail[frozen_tail.year==year].set_index("trade_id")
    for t in pop.itertuples(index=False):
        s=pd.Series(t._asdict()); v0=run_runner(s,raw,None,None); ft=frozen_tail.loc[t.trade_id]
        pa=policy_a.loc[int(t.entry_fill_ts)]
        touch2=first_favorable_touch_ts(s,raw,2.0); touch3=first_favorable_touch_ts(s,raw,3.0); touch4=first_favorable_touch_ts(s,raw,4.0)
        res_i=int(np.searchsorted(raw.index.view(np.int64),int(t.resolution_ts),side="left"))
        if res_i>=len(raw): raise RuntimeError("contract1 resolution boundary")
        contract1_exit_px,contract1_gross=contract1_fill_and_gross(t,float(raw.open.iloc[res_i]))
        for v in config["variants"]:
            r=v0 if v["variant_id"]=="V0" else run_runner(s,raw,v["arm_atr"],v["floor_atr"])
            total=contract1_gross+r["runner_gross_pnl_usd"]-2*COST
            final_ts=max(int(t.resolution_ts),int(r["runner_exit_ts"]))
            base={"variant_id":v["variant_id"],"year":year,"trade_id":t.trade_id,"entry_direction":int(t.entry_direction),
              "direction":t.direction,"session":t.session,"entry_fill_ts":int(t.entry_fill_ts),"entry_fill_open":float(t.entry_fill_open),
              "atr_at_checkpoint":float(t.atr_at_checkpoint),"contract1_outcome":t.outcome,"pt1_hit":bool(t.pt_first),
              "full_sl_first":bool(t.sl_first),"contract1_exit_ts":int(t.resolution_ts),"contract1_exit_px":contract1_exit_px,
              "contract1_gross_pnl_usd":contract1_gross,
              "contract1_net_pnl_usd":contract1_gross-COST,"total_costs_usd":2*COST,"total_net_pnl_usd":total,
              "pure_bracket_net_pnl_usd":float(t.net_pnl_usd),"policy_a_net_pnl_usd":float(pa.net_pnl_usd),
              "policy_a_exit_ts":int(pa.exit_fill_ts),"policy_a_exit_reason":str(pa.exit_reason),
              "final_exit_ts":final_ts,**r}
            rows.append(base)
            max_available=float(ft.max_total_mfe_atr)
            max_dollar=max_available*float(t.atr_at_checkpoint)*MULTIPLIER
            capture=r["runner_gross_pnl_usd"]/max_dollar if max_dollar>0 else np.nan
            full_giveback=max_available-r["runner_realized_pnl_atr"]
            pt_tail_available=bool(ft.primary_resolution_before_horizon and t.pt_first)
            floor_exit=bool(r["runner_exit_reason"]=="runner_floor_exit")
            before2,same2=floor_before_touch(floor_exit,r["runner_exit_ts"],touch2)
            before3,same3=floor_before_touch(floor_exit,r["runner_exit_ts"],touch3)
            before4,same4=floor_before_touch(floor_exit,r["runner_exit_ts"],touch4)
            tails.append({**{k:base[k] for k in ("variant_id","year","trade_id","direction","session","pt1_hit")},
              "pt_tail_available":pt_tail_available,
              "reached_2a":ft.reached_2a if pt_tail_available else pd.NA,
              "reached_3a":ft.reached_3a if pt_tail_available else pd.NA,
              "reached_4a":ft.reached_4a if pt_tail_available else pd.NA,
              "runner_floor_before_2a":before2 if pt_tail_available else pd.NA,
              "floor_2a_same_bar_ambiguous":same2,"floor_3a_same_bar_ambiguous":same3,
              "floor_4a_same_bar_ambiguous":same4,
              "additional_mfe_after_pt1_atr":ft.additional_mfe_after_pt_atr if pt_tail_available else np.nan,
              "max_available_runner_mfe_atr":max_available,"runner_giveback_atr":full_giveback,
              "runner_giveback_usd":full_giveback*float(t.atr_at_checkpoint)*MULTIPLIER,
              "runner_capture_ratio":capture,
              "pt_returned_to_entry_before_2a":ft.pt_first_then_immediate_reversal if pt_tail_available else pd.NA,
              "entry_2a_same_bar_ambiguous":ft.pt_post_resolution_entry_2a_same_bar_ambiguous if pt_tail_available else False})
            if v["variant_id"]!="V0":
                diff=r["runner_gross_pnl_usd"]-v0["runner_gross_pnl_usd"]
                protective.append({"variant_id":v["variant_id"],"year":year,"trade_id":t.trade_id,
                  "floor_armed":r["floor_armed"],"floor_exit":r["runner_exit_reason"]=="runner_floor_exit",
                  "runner_pnl_change_vs_v0_usd":diff,"pnl_saved_vs_v0_usd":max(diff,0),"pnl_lost_vs_v0_usd":min(diff,0),
                  "future_2a_runner_clipped":pd.NA if same2 else bool(not pd.isna(touch2) and before2),
                  "future_3a_runner_clipped":pd.NA if same3 else bool(not pd.isna(touch3) and before3),
                  "future_4a_runner_clipped":pd.NA if same4 else bool(not pd.isna(touch4) and before4),
                  "floor_2a_same_bar_ambiguous":same2,"floor_3a_same_bar_ambiguous":same3,
                  "floor_4a_same_bar_ambiguous":same4,
                  "regime_flip_giveback_avoided":diff>0,"v0_runner_gross_pnl_usd":v0["runner_gross_pnl_usd"],
                  "protected_runner_gross_pnl_usd":r["runner_gross_pnl_usd"]})
    trades=pd.DataFrame(rows)
    trades["floor_armed_ts"]=pd.array(trades["floor_armed_ts"],dtype="Int64")
    return trades,pd.DataFrame(tails),pd.DataFrame(protective)


def dd(g,pnl_col="total_net_pnl_usd",exit_col="final_exit_ts"):
    x=g.sort_values([exit_col,"entry_fill_ts"])[pnl_col].to_numpy(float); e=np.cumsum(x); p=np.maximum.accumulate(np.r_[0,e])[:-1]
    return float(np.max(p-e)) if len(x) else 0.0


def masks(d):
    return [("combined","ALL",pd.Series(True,index=d.index)),("year","2025",d.year==2025),("year","2026",d.year==2026),
      ("direction","long_fade",d.entry_direction==1),("direction","short_fade",d.entry_direction==-1),
      ("session","ETH",d.session=="ETH"),("session","RTH",d.session=="RTH"),
      ("direction_session","long_ETH",(d.entry_direction==1)&(d.session=="ETH")),
      ("direction_session","long_RTH",(d.entry_direction==1)&(d.session=="RTH")),
      ("direction_session","short_ETH",(d.entry_direction==-1)&(d.session=="ETH")),
      ("direction_session","short_RTH",(d.entry_direction==-1)&(d.session=="RTH"))]


def summarize(d):
    out=[]
    for v in ("V0","V75_25","V100_50"):
      p=d[d.variant_id==v].reset_index(drop=True)
      for st,sv,m in masks(p):
        g=p[m]; w=g[g.total_net_pnl_usd>0]; l=g[g.total_net_pnl_usd<0]
        out.append({"variant_id":v,"split_type":st,"split_value":sv,"trade_count":len(g),"total_net_pnl_usd":g.total_net_pnl_usd.sum(),
          "mean_net_pnl_per_entry_usd":g.total_net_pnl_usd.mean(),"profit_factor":w.total_net_pnl_usd.sum()/(-l.total_net_pnl_usd.sum()),
          "win_rate":(g.total_net_pnl_usd>0).mean(),"max_closed_trade_sequence_drawdown_usd":dd(g),"pt1_hit_rate":g.pt1_hit.mean(),
          "full_sl_first_rate":g.full_sl_first.mean(),"runner_average_net_pnl_usd":g.runner_net_pnl_usd.mean(),
          "runner_win_rate":(g.runner_net_pnl_usd>0).mean(),"runner_stop_out_rate":g.runner_exit_reason.str.contains("sl|floor").mean(),
          "runner_regime_flip_exit_rate":g.runner_exit_reason.eq("runner_regime_flip_exit").mean(),"average_winner_usd":w.total_net_pnl_usd.mean(),
          "average_loser_usd":l.total_net_pnl_usd.mean(),"total_costs_usd":g.total_costs_usd.sum(),"average_runner_hold_s":g.runner_hold_s.mean(),
          "median_runner_giveback_atr":g.runner_giveback_atr.median(),"p75_runner_giveback_atr":g.runner_giveback_atr.quantile(.75),
          "contract1_net_contribution_usd":g.contract1_net_pnl_usd.sum(),"runner_net_contribution_usd":g.runner_net_pnl_usd.sum(),
          "pnl_pt1_hit_trades_usd":g.loc[g.pt1_hit,"total_net_pnl_usd"].sum(),"pnl_sl_first_trades_usd":g.loc[g.full_sl_first,"total_net_pnl_usd"].sum(),
          "runner_net_after_pt1_contribution_usd":g.loc[g.pt1_hit_before_runner_exit,"runner_net_pnl_usd"].sum(),
          "runner_positive_after_pt1_count":int((g.pt1_hit_before_runner_exit&(g.runner_net_pnl_usd>0)).sum()),
          "runner_positive_exit_count":int((g.runner_net_pnl_usd>0).sum()),
          "runner_made_pt1_winner_larger_count":int((g.pt1_hit_before_runner_exit&(g.runner_net_pnl_usd>0)).sum()),
          "runner_reduced_total_count":int((g.runner_net_pnl_usd<0).sum()),
          "runner_reduced_pt1_trade_count":int((g.pt1_hit_before_runner_exit&(g.runner_net_pnl_usd<0)).sum()),
          "pt_floor_same_bar_deferred_count":int(g.pt_floor_same_bar_deferred.sum()),
          "arm_floor_same_bar_deferred_count":int(g.arm_floor_same_bar_deferred.sum()),
          "horizon_floor_same_timestamp_count":int(g.horizon_floor_same_timestamp.sum())})
    return pd.DataFrame(out)


def summarize_baselines(d):
    """Emit exact, reconciled one-contract baselines on the identical entries."""
    p=d[d.variant_id=="V0"].reset_index(drop=True); out=[]
    specs=(("BASELINE_POLICY_A","policy_a_net_pnl_usd","policy_a_exit_ts",False),
           ("BASELINE_PURE_1_25_BRACKET","pure_bracket_net_pnl_usd","contract1_exit_ts",True))
    for policy,pnl_col,exit_col,has_pt in specs:
      for st,sv,m in masks(p):
        g=p[m]; pnl=g[pnl_col]; wins=pnl[pnl>0]; losses=pnl[pnl<0]
        out.append({"variant_id":policy,"split_type":st,"split_value":sv,"trade_count":len(g),
          "total_net_pnl_usd":pnl.sum(),"mean_net_pnl_per_entry_usd":pnl.mean(),
          "profit_factor":wins.sum()/(-losses.sum()),"win_rate":(pnl>0).mean(),
          "max_closed_trade_sequence_drawdown_usd":dd(g,pnl_col,exit_col),
          "pt1_hit_rate":g.pt1_hit.mean() if has_pt else np.nan,
          "full_sl_first_rate":g.full_sl_first.mean() if has_pt else np.nan,
          "average_winner_usd":wins.mean(),"average_loser_usd":losses.mean(),
          "total_costs_usd":len(g)*COST,"contract1_net_contribution_usd":pnl.sum(),
          "runner_net_contribution_usd":0.0})
    return pd.DataFrame(out)


def protective_output(detail):
    """Append fixed aggregate diagnostics while preserving trade-level evidence."""
    detail=detail.copy(); detail.insert(0,"row_type","trade")
    summaries=[]
    for variant in ("V75_25","V100_50"):
      p=detail[detail.variant_id==variant]
      for split_type,split_value,mask in (("combined","ALL",pd.Series(True,index=p.index)),
                                           ("year","2025",p.year==2025),("year","2026",p.year==2026)):
        g=p[mask]; saved=g.loc[g.runner_pnl_change_vs_v0_usd>0,"runner_pnl_change_vs_v0_usd"]
        lost=g.loc[g.runner_pnl_change_vs_v0_usd<0,"runner_pnl_change_vs_v0_usd"]
        summaries.append({"row_type":"summary","variant_id":variant,"year":pd.NA,"trade_id":pd.NA,
          "split_type":split_type,"split_value":split_value,"trade_count":len(g),
          "floor_armed_count":int(g.floor_armed.sum()),"floor_exit_count":int(g.floor_exit.sum()),
          "average_pnl_saved_vs_v0_usd":saved.mean(),"average_pnl_lost_vs_v0_usd":lost.mean(),
          "total_pnl_saved_vs_v0_usd":saved.sum(),"total_pnl_lost_vs_v0_usd":lost.sum(),
          "future_2a_runner_clipped_count":int(g.future_2a_runner_clipped.sum()),
          "future_3a_runner_clipped_count":int(g.future_3a_runner_clipped.sum()),
          "future_4a_runner_clipped_count":int(g.future_4a_runner_clipped.sum()),
          "floor_2a_same_bar_ambiguous_count":int(g.floor_2a_same_bar_ambiguous.sum()),
          "floor_3a_same_bar_ambiguous_count":int(g.floor_3a_same_bar_ambiguous.sum()),
          "floor_4a_same_bar_ambiguous_count":int(g.floor_4a_same_bar_ambiguous.sum()),
          "regime_flip_giveback_avoided_count":int(g.regime_flip_giveback_avoided.sum()),
          "net_protective_stop_contribution_usd":g.runner_pnl_change_vs_v0_usd.sum()})
    return pd.concat([detail,pd.DataFrame(summaries)],ignore_index=True,sort=False)


def dependency_2025(): return {"runner":script_sha256(),"config":sha(CONFIG_PATH),"freeze":sha(FREEZE_PATH),"audit":sha(PRE_AUDIT),"auth":sha(PRE_AUTH),"raw":sha(RAW[2025])}
def require_2025():
    p=WORK/"reconciliation_2025.json"
    if not p.exists(): raise RuntimeError("2025 required")
    s=json.loads(p.read_text())
    if s["blocking_errors"] or s["dependency_2025"]!=dependency_2025(): raise RuntimeError("2025 seal")
    for n,h in s["artifacts"].items():
        if sha(WORK/n)!=h: raise RuntimeError("artifact changed")


def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--year",type=int,choices=(2025,2026),required=True); a=ap.parse_args()
    require_authorization(); c=validate_contract()
    if a.year==2026: require_2025()
    raw=pd.read_parquet(RAW[a.year],columns=["open","high","low","close","volume"]); validate_raw(raw)
    trades,tails,protective=simulate_year(a.year,raw,c)
    paths={f"trade_diffs_{a.year}.parquet":trades,f"tail_{a.year}.parquet":tails,f"protective_{a.year}.parquet":protective}
    for n,d in paths.items(): d.to_parquet(WORK/n,index=False)
    seal={"year":a.year,"blocking_errors":0,"population":trades.trade_id.nunique(),"dependency_2025":dependency_2025(),"artifacts":{n:sha(WORK/n) for n in paths}}
    (WORK/f"reconciliation_{a.year}.json").write_text(json.dumps(seal,indent=2))
    if a.year==2026:
      ta=pd.concat([pd.read_parquet(WORK/"trade_diffs_2025.parquet"),trades],ignore_index=True)
      tl=pd.concat([pd.read_parquet(WORK/"tail_2025.parquet"),tails],ignore_index=True)
      pr=pd.concat([pd.read_parquet(WORK/"protective_2025.parquet"),protective],ignore_index=True)
      policy_results=pd.concat([summarize(ta),summarize_baselines(ta)],ignore_index=True,sort=False)
      outputs={"w4_pt_runner_policy_results.parquet":policy_results,"w4_pt_runner_trade_diffs.parquet":ta,
        "w4_pt_runner_tail_diagnostics.parquet":tl,"w4_pt_runner_protective_stop_diagnostics.parquet":protective_output(pr)}
      for n,d in outputs.items(): d.to_parquet(RESULTS/n,index=False)
      m={"status":"OUTPUTS_COMPLETE_PENDING_REPORT_AND_COMPLETION_AUDIT","population":4383,"runner_sha256":script_sha256(),
         "config_sha256":sha(CONFIG_PATH),"freeze_sha256":sha(FREEZE_PATH),"output_sha256":{n:sha(RESULTS/n) for n in outputs}}
      (RESULTS/"run_manifest.json").write_text(json.dumps(m,indent=2))
    print(a.year,dict(trades.groupby("variant_id").total_net_pnl_usd.sum()))
if __name__=="__main__": main()
