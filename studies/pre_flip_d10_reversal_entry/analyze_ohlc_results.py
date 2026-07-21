"""Reporting for the authorized OHLC research contracts; no trade matching here."""
from __future__ import annotations

import json
import numpy as np
import pandas as pd

from common import AUDIT, RESULTS, WORK
from run_ohlc_contracts import PRIMARY, SENSITIVITY


def metrics(g: pd.DataFrame) -> dict:
    c=g[g.completed & g.net_pnl.notna()].sort_values("exit_ts")
    x=c.net_pnl.astype(float); eq=pd.Series(np.r_[0.0,x.cumsum().to_numpy()]); dd=eq-eq.cummax()
    pos=x[x>0].sum(); neg=-x[x<0].sum()
    return {"trade_count":len(c),"censored_count":int((~g.completed).sum()),
        "win_rate":float((x>0).mean()) if len(x) else np.nan,
        "gross_pnl":float(c.gross_pnl.sum()),"net_pnl":float(x.sum()),
        "ev_per_trade":float(x.mean()) if len(x) else np.nan,
        "profit_factor":float(pos/neg) if neg else np.nan,
        "maximum_drawdown":float(dd.min()) if len(dd) else 0.0,
        "median_trade":float(x.median()) if len(x) else np.nan,
        "p10_trade":float(x.quantile(.1)) if len(x) else np.nan,
        "p90_trade":float(x.quantile(.9)) if len(x) else np.nan,
        "stop_out_before_flip_rate":float(c.exit_reason.eq("stop_before_flip").mean()) if len(c) else np.nan,
        "flip_confirmation_rate":float(c.reached_confirmation.mean()) if len(c) else np.nan,
        "post_confirmation_stop_rate":float(c.exit_reason.eq("stop_after_flip").mean()) if len(c) else np.nan,
        "d10_exit_rate":float(c.exit_reason.eq("d10_exit").mean()) if len(c) else np.nan,
        "opposite_flip_fallback_exit_rate":float(c.exit_reason.eq("opposite_regime_flip_exit").mean()) if len(c) else np.nan,
        "same_bar_tie_count":int(c.same_bar_stop_logical_exit_tie.sum()),
        "same_bar_tie_rate":float(c.same_bar_stop_logical_exit_tie.mean()) if len(c) else np.nan}


def completeness(t: pd.DataFrame):
    allowed={"stop_before_flip","stop_after_flip","d10_exit","opposite_regime_flip_exit","data_end_censored"}
    a=t[["trade_id","execution_contract","year","policy","stop_atr_mult","entry_fill_ts","exit_ts","exit_reason","completed"]].copy()
    a["valid_reason"]=a.exit_reason.isin(allowed)
    a["valid_time"]=(~a.completed & a.exit_ts.isna()) | (a.completed & a.exit_ts.notna() & (a.exit_ts>=a.entry_fill_ts))
    a["pass"]=a.valid_reason & a.valid_time
    a.to_parquet(AUDIT/"exit_reason_completeness_audit.parquet",index=False)
    if not a["pass"].all(): raise RuntimeError("exit completeness audit failed")


def main():
    t=pd.read_parquet(RESULTS/"trade_results.parquet")
    completeness(t)
    rec=[]
    for k,g in t.groupby(["execution_contract","year","policy","stop_atr_mult"],dropna=False):
        rec.append({"execution_contract":k[0],"year":k[1],"policy":k[2],"stop_atr_mult":k[3],**metrics(g)})
    pol=pd.DataFrame(rec)
    pol.to_parquet(RESULTS/"policy_results.parquet",index=False)
    pol[pol.policy.isin(["P1","P3","P4A","P4B"])].to_parquet(RESULTS/"stop_sensitivity.parquet",index=False)
    pol[pol.policy.eq("P0")].to_parquet(RESULTS/"flip_to_flip_baseline.parquet",index=False)

    c=t[t.completed].copy()
    ct=pd.to_datetime(c.exit_ts,unit="ns",utc=True).dt.tz_convert("America/Chicago")
    c["month"]=ct.dt.strftime("%Y-%m")
    monthly=c.groupby(["execution_contract","year","policy","stop_atr_mult","month"],dropna=False).agg(
        trade_count=("trade_id","size"),net_pnl=("net_pnl","sum"),ev_per_trade=("net_pnl","mean"),
        win_rate=("net_pnl",lambda x:(x>0).mean())).reset_index()
    grids=[]
    for k in t[["execution_contract","year","policy","stop_atr_mult"]].drop_duplicates().itertuples(index=False):
        months=(pd.period_range("2025-03","2025-12",freq="M").astype(str) if k.year==2025
                else pd.period_range("2026-01","2026-04",freq="M").astype(str))
        grids.extend({"execution_contract":k.execution_contract,"year":k.year,"policy":k.policy,
                      "stop_atr_mult":k.stop_atr_mult,"month":m} for m in months)
    monthly=pd.DataFrame(grids).merge(monthly,how="left",on=["execution_contract","year","policy","stop_atr_mult","month"])
    monthly[["trade_count","net_pnl"]]=monthly[["trade_count","net_pnl"]].fillna(0)
    monthly.to_parquet(RESULTS/"monthly_results.parquet",index=False)
    monthly_pos=monthly.assign(positive=monthly.net_pnl>0).groupby(
        ["execution_contract","year","policy","stop_atr_mult"],dropna=False).positive.mean().rename("monthly_positive_rate").reset_index()
    pol_month=pol.merge(monthly_pos,how="left")
    pol_month[pol_month.policy.isin(["P1","P3","P4A","P4B"])].to_parquet(RESULTS/"stop_sensitivity.parquet",index=False)

    seg=c.groupby(["execution_contract","year","policy","direction","session","stop_atr_mult","exit_reason"],dropna=False).agg(
        trade_count=("trade_id","size"),gross_pnl=("gross_pnl","sum"),net_pnl=("net_pnl","sum"),
        ev_per_trade=("net_pnl","mean"),win_rate=("net_pnl",lambda x:(x>0).mean()),
        tie_count=("same_bar_stop_logical_exit_tie","sum")).reset_index()
    seg.to_parquet(RESULTS/"segment_results.parquet",index=False)
    reason=t.groupby(["execution_contract","year","policy","direction","session","stop_atr_mult","exit_reason"],dropna=False).size().rename("count").reset_index()
    denom=reason.groupby(["execution_contract","year","policy","direction","session","stop_atr_mult"],dropna=False)["count"].transform("sum")
    reason["percent"]=reason["count"]/denom
    reason.to_parquet(RESULTS/"d10_exit_reason_summary.parquet",index=False)
    t[t.same_bar_stop_logical_exit_tie].to_parquet(RESULTS/"same_bar_ties.parquet",index=False)

    pre=t[t.policy.isin(["P1","P3","P4A","P4B"])].copy()
    decomp_cols=["trade_id","execution_contract","year","policy","direction","session","stop_atr_mult",
        "origin_regime_id","confirmation_ts","confirmation_fill_ts","confirmation_fill_price",
        "reached_confirmation","pre_flip_mae_points","pre_flip_mae_atr","pre_flip_pnl","post_flip_pnl",
        "gross_pnl","net_pnl","front_run_advantage_points","front_run_advantage_usd","front_run_advantage_atr","exit_reason"]
    pre[decomp_cols].to_parquet(RESULTS/"pnl_decomposition.parquet",index=False)
    pre[["trade_id","execution_contract","year","policy","direction","session","stop_atr_mult",
         "origin_regime_id","entry_fill_ts","entry_fill_price","confirmation_fill_ts","confirmation_fill_price",
         "front_run_advantage_points","front_run_advantage_usd","front_run_advantage_atr","reached_confirmation"]].to_parquet(
             RESULTS/"preflip_vs_wait_for_flip.parquet",index=False)

    dx=t[t.policy.isin(["P2","P3","P4B"])].copy()
    coverage=pd.read_parquet(RESULTS/"regime_d10_coverage.parquet",columns=["regime_id","valid_score_checkpoint_count","ever_reached_D10"])
    dx=dx.merge(coverage,left_on="confirmed_regime_id",right_on="regime_id",how="left")
    dx["classification"]=np.select([
        dx.valid_score_checkpoint_count.fillna(0).eq(0),
        dx.d10_exit_decision_ts.eq(dx.natural_exit_decision_ts) & dx.d10_exit_decision_ts.notna(),
        dx.d10_exit_decision_ts.isna(),
        dx.exit_reason.str.startswith("stop") & dx.d10_exit_decision_ts.notna(),
        dx.exit_reason.eq("d10_exit") & (dx.incremental_pnl_from_d10>0),
        dx.exit_reason.eq("d10_exit") & (dx.incremental_pnl_from_d10<=0),
    ],["score unavailable","D10 occurred at same timestamp as flip","D10 never occurred",
       "stopped before D10","D10 occurred and improved PnL","D10 occurred and reduced PnL"],default="opposite flip before D10")
    contrib_cols=["trade_id","execution_contract","year","policy","direction","session","stop_atr_mult",
        "origin_regime_id","confirmed_regime_id","d10_exit_decision_ts","logical_exit_decision_ts",
        "natural_exit_decision_ts","exit_reason","net_pnl","natural_exit_net_pnl","incremental_pnl_from_d10",
        "max_additional_favorable_after_d10_usd","max_adverse_movement_avoided_usd","giveback_avoided_usd",
        "runner_truncation_usd","valid_score_checkpoint_count","ever_reached_D10","classification"]
    dx[contrib_cols].to_parquet(RESULTS/"d10_exit_contribution.parquet",index=False)
    dx[contrib_cols].to_parquet(RESULTS/"runner_capture.parquet",index=False)
    eligible=dx[(dx.policy.eq("P2"))|dx.reached_confirmation].copy()
    avail=eligible.groupby(["execution_contract","year","policy","direction","session","stop_atr_mult"],dropna=False).agg(
        confirmed_trades=("trade_id","size"),d10_exits=("exit_reason",lambda x:x.eq("d10_exit").sum()),
        opposite_flip_without_d10=("classification",lambda x:x.isin(["D10 never occurred","opposite flip before D10","D10 occurred at same timestamp as flip"]).sum()),
        stopped_after_confirmation=("exit_reason",lambda x:x.eq("stop_after_flip").sum()),
        score_unavailable=("classification",lambda x:x.eq("score unavailable").sum()),
        data_end_censored=("exit_reason",lambda x:x.eq("data_end_censored").sum()),
        d10_same_timestamp_flip=("classification",lambda x:x.eq("D10 occurred at same timestamp as flip").sum())).reset_index()
    for col in ["d10_exits","opposite_flip_without_d10","stopped_after_confirmation","score_unavailable","data_end_censored"]:
        avail[col+"_percent"]=avail[col]/avail.confirmed_trades
    avail.to_parquet(RESULTS/"confirmed_trade_d10_availability.parquet",index=False)
    tail=c.groupby(["execution_contract","year","policy","stop_atr_mult"],dropna=False).net_pnl.agg(
        count="size",mean="mean",median="median",p01=lambda x:x.quantile(.01),p05=lambda x:x.quantile(.05),
        p95=lambda x:x.quantile(.95),p99=lambda x:x.quantile(.99)).reset_index()
    tail.to_parquet(RESULTS/"tail_dependence.parquet",index=False)

    placebo=[]; pair_rows=[]; rng=np.random.default_rng(20260711)
    for contract in (PRIMARY,SENSITIVITY):
      for year in (2025,2026):
       for stop in (.5,1.,1.5):
        for real,control in (("P1","P4A"),("P3","P4B")):
         ar=c[(c.execution_contract==contract)&(c.year==year)&(c.policy==real)&(c.stop_atr_mult==stop)]
         br=c[(c.execution_contract==contract)&(c.year==year)&(c.policy==control)&(c.stop_atr_mult==stop)]
         pairs=br.merge(ar[["origin_regime_id","net_pnl","atr_at_entry","front_run_advantage_atr"]],left_on="matched_treated_regime_id",right_on="origin_regime_id",suffixes=("_placebo","_real"))
         diff=(pairs.net_pnl_real-pairs.net_pnl_placebo).to_numpy(float)
         if len(diff):
             null=np.array([(diff*rng.choice([-1,1],size=len(diff))).mean() for _ in range(5000)])
             obs=float(diff.mean()); p=float((1+(np.abs(null)>=abs(obs)).sum())/(len(null)+1))
         else: obs=p=np.nan
         a=ar.net_pnl; b=br.net_pnl
         placebo.append({"execution_contract":contract,"year":year,"stop_atr_mult":stop,"real_policy":real,"placebo_policy":control,
             "real_count":len(a),"placebo_count":len(b),"paired_count":len(diff),"unpaired_real_count":len(a)-len(diff),
             "unpaired_placebo_count":len(b)-len(diff),"real_ev":a.mean(),"placebo_ev":b.mean(),"ev_lift":a.mean()-b.mean(),
             "paired_ev_lift":obs,"paired_sign_randomization_p_value":p,"seed":20260711})
         if len(pairs):
             pairs["execution_contract"]=contract;pairs["year"]=year;pairs["stop_atr_mult"]=stop
             pairs["real_policy"]=real;pairs["placebo_policy"]=control
             pair_rows.append(pairs)
    placebo_df=pd.DataFrame(placebo)
    placebo_df.to_parquet(RESULTS/"matched_placebo_summary.parquet",index=False)
    if len(placebo_df)!=24 or not (placebo_df.paired_count>0).all(): raise RuntimeError("Required placebo pair cell missing")
    pair_df=pd.concat(pair_rows,ignore_index=True) if pair_rows else pd.DataFrame()
    pair_df.to_parquet(RESULTS/"matched_placebo_pairs.parquet",index=False)
    exec_balance=[]
    for k,g in pair_df.groupby(["execution_contract","year","stop_atr_mult","real_policy"]):
        for f in ("atr_at_entry","front_run_advantage_atr"):
            a=g[f+"_real"].astype(float);b=g[f+"_placebo"].astype(float);den=np.sqrt((a.var()+b.var())/2)
            exec_balance.append({"execution_contract":k[0],"year":k[1],"stop_atr_mult":k[2],"policy":k[3],
                "feature":f,"real_mean":a.mean(),"placebo_mean":b.mean(),"standardized_mean_difference":(a.mean()-b.mean())/den if den else 0.0})
    pd.DataFrame(exec_balance).to_parquet(RESULTS/"executed_pair_balance.parquet",index=False)
    bal=WORK/"placebo_balance.parquet"
    if bal.exists(): pd.read_parquet(bal).to_parquet(RESULTS/"matched_placebo_balance.parquet",index=False)

    primary=pol[pol.execution_contract.eq(PRIMARY)]
    baseline=primary[primary.policy.eq("P0")][["year","ev_per_trade"]].set_index("year").ev_per_trade
    lines=["PRE-FLIP D10 REVERSAL STUDY","","PRIMARY CONTRACT:",PRIMARY,"",
        "VALIDATION STATUS:","1-SECOND OHLC RESEARCH SIMULATION; NOT NT-NATIVE EXECUTABLE VALIDATION","",
        "PARAMETER SELECTION:","NONE. 2026 was not used to select threshold, stop, or policy.","",
        "STOP GRID:","0.50 ATR, 1.00 ATR, 1.50 ATR only","",
        "BEST POLICY:","NONE (all test policies reported without test-set optimization)","",
        "EXECUTIVE SUMMARY","",
        "The main results use explicit next-1s-open entries and fill-anchored OHLC stop labels. Exact intrabar touch order is not claimed. Stop wins any same-bar stop/logical-exit tie. Contract 3 is sensitivity only.","",
        "POLICY RESULTS","",primary.to_string(index=False),"",
        "REGIME-FLIP BASELINE","",primary[primary.policy.eq("P0")].to_string(index=False),"",
        "BREAKDOWNS","","See segment_results.parquet for every year × direction × RTH/ETH × stop × exit reason.","",
        "LIMITATIONS","","No tick/quote path is available. Stop fills at the trigger (or worse entry-bar/bar-open gap) are explicit OHLC research assumptions. This is not an NT-validated strategy."]
    (RESULTS/"final_report.md").write_text("\n".join(lines),encoding="utf-8")


if __name__=="__main__": main()
