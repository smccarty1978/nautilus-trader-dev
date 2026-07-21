from __future__ import annotations
import json
import pandas as pd
from common import AUDIT, RESULTS, WORK
from run_ohlc_contracts import PRIMARY


def main():
    t=pd.read_parquet(RESULTS/"trade_results.parquet")
    pol=pd.read_parquet(RESULTS/"policy_results.parquet")
    pre_all=pd.read_parquet(RESULTS/"pnl_decomposition.parquet")
    pre=pre_all[pre_all.execution_contract.eq(PRIMARY)&pre_all.policy.isin(["P1","P3"])].copy()
    cov=pd.read_parquet(RESULTS/"regime_d10_coverage.parquet")
    events=pd.read_parquet(RESULTS/"d10_entry_events.parquet")
    fwd=events[events.is_first_crossing].merge(cov[["regime_id","regime_end_time","seconds_from_D10_to_regime_end","right_censored"]],on="regime_id",how="left")
    fwd["reversal_observed"]=fwd.regime_end_time.notna();fwd.to_parquet(RESULTS/"forward_reversal_diagnostics.parquet",index=False)
    scored=cov.valid_score_checkpoint_count.gt(0)
    availability=pd.DataFrame([{"regimes":len(cov),"validly_scored":int(scored.sum()),"score_unavailable":int((~scored).sum()),
        "valid_scored_ever_d10":int((scored&cov.ever_reached_D10).sum()),"valid_scored_never_d10":int((scored&~cov.ever_reached_D10).sum()),
        "d10_same_timestamp_as_end":int(cov.D10_same_timestamp_as_regime_end.sum()),"right_censored":int(cov.right_censored.sum())}])
    availability.to_parquet(RESULTS/"d10_exit_availability_summary.parquet",index=False)
    st=t[t.same_bar_stop_logical_exit_tie].copy();st["same_timestamp_case"]="stop_and_logical_exit"
    sf=t[t.d10_exit_decision_ts.notna()&t.d10_exit_decision_ts.eq(t.natural_exit_decision_ts)].copy();sf["same_timestamp_case"]="d10_and_opposite_flip"
    pd.concat([st,sf],ignore_index=True).to_parquet(AUDIT/"same_timestamp_exit_audit.parquet",index=False)
    primary=pol[pol.execution_contract.eq(PRIMARY)];base=primary[primary.policy.eq("P0")].set_index("year").ev_per_trade
    lift=primary[primary.policy.isin(["P1","P3"])].copy();lift["lift"]=lift.apply(lambda r:r.ev_per_trade-base.loc[r.year],axis=1)
    piv=lift.pivot_table(index=["policy","stop_atr_mult"],columns="year",values="lift").dropna();qual=piv[(piv[2025]>0)&(piv[2026]>0)] if len(piv) else piv
    mean_pre=pre.pre_flip_pnl.mean();mean_post=pre.post_flip_pnl.mean()
    verdict="REPAIR" if len(qual) else "CLOSE"
    threshold=json.loads((WORK/"frozen_threshold.json").read_text())["threshold"]
    focus=lift[lift.policy.isin(["P1","P3"])]
    def span(year,col,frame=focus):
        x=frame.loc[frame.year.eq(year),col].dropna()
        if not len(x): raise RuntimeError(f"Missing final header metric {year}/{col}")
        return f"{x.min():.4f} to {x.max():.4f}"
    placebo=pd.read_parquet(RESULTS/"matched_placebo_summary.parquet")
    pp=placebo[placebo.execution_contract.eq(PRIMARY)].paired_sign_randomization_p_value.dropna()
    if not len(pp): raise RuntimeError("Missing matched placebo p-values")
    gaps=pd.read_parquet(AUDIT/"entry_fill_gap_summary.parquet")
    ext=gaps[gaps.entry_fill_gap_class.eq("extended_market_data_gap_gt_60s")]
    design_bal=pd.read_parquet(RESULTS/"matched_placebo_balance.parquet")
    exec_bal=pd.read_parquet(RESULTS/"executed_pair_balance.parquet")
    sections=["PRE-FLIP D10 REVERSAL STUDY","","PRIMARY CONTRACT:",PRIMARY,"","VALIDATION STATUS:","1-SECOND OHLC RESEARCH SIMULATION; NOT NT-NATIVE EXECUTABLE VALIDATION","",
      "BEST POLICY:","NONE (no test-set optimization)","","2025 EV LIFT VS FLIP-TO-FLIP BASELINE:",span(2025,"lift"),"","2026 EV LIFT VS FLIP-TO-FLIP BASELINE:",span(2026,"lift"),"",
      "2025 STOP-OUT BEFORE FLIP RATE:",span(2025,"stop_out_before_flip_rate",primary[primary.policy.isin(["P1","P3"])]),"","2026 STOP-OUT BEFORE FLIP RATE:",span(2026,"stop_out_before_flip_rate",primary[primary.policy.isin(["P1","P3"])]),"","2025 NEW-REGIME D10 EXIT RATE:",span(2025,"d10_exit_rate",primary[primary.policy.isin(["P2","P3"])]),"","2026 NEW-REGIME D10 EXIT RATE:",span(2026,"d10_exit_rate",primary[primary.policy.isin(["P2","P3"])]),"",
      "2025 OPPOSITE-FLIP FALLBACK EXIT RATE:",span(2025,"opposite_flip_fallback_exit_rate",primary[primary.policy.isin(["P2","P3"])]),"","2026 OPPOSITE-FLIP FALLBACK EXIT RATE:",span(2026,"opposite_flip_fallback_exit_rate",primary[primary.policy.isin(["P2","P3"])]),"",
      "PERCENT OF VALIDLY SCORED REGIMES THAT EVER REACH D10:",f"{cov.loc[scored,'ever_reached_D10'].mean():.2%}","","AVERAGE PRE-FLIP PNL:",f"${mean_pre:.2f}","","AVERAGE POST-FLIP PNL:",f"${mean_post:.2f}","",
      "D10 FRONT-RUN ENTRY ADVANTAGE VS WAITING FOR FLIP:",f"${pre.front_run_advantage_usd.mean():.2f} ({pre.front_run_advantage_atr.mean():.3f} ATR)","","MATCHED PLACEBO P-VALUE:",(f"{pp.min():.4f} to {pp.max():.4f} across frozen cells" if len(pp) else "unavailable"),"","VERDICT:",verdict,"",
      "1. Executive summary","","Primary: explicit next-open OHLC research simulation. Stop wins same-bar ties. Contract 3 is sensitivity only. No 2026 parameter selection. Headline PnL and front-run statistics use primary P1/P3 trades only.","",
      "2. Exact strategy and policy definitions","","See SPEC.md and config.yaml.","","3. Frozen D10 threshold definition","",f"Absolute Jan-Feb 2025 validation-frozen W4 90th percentile: {threshold:.12f}.","",
      "4. Entry timing audit","",f"See audit/entry_timing_audit.parquet. Extended >60s gap cells total {int(ext['count'].sum())} trade rows; maximum delay {int(ext.max_ns.max())/1e9:.0f}s. These are first-available opens across documented market-data closures.","","5. Stop execution audit","","Entry-bar stop enabled; worse-open gap rule; exact intrabar touch order unknown.","","6. Score and regime-ID reset audit","","See audit/score_regime_id_audit.parquet.","",
      "7. Regime-level D10 coverage","",availability.to_string(index=False),"","8. D10 entry diagnostics","","See forward_reversal_diagnostics.parquet.","","9. Pre-flip versus post-flip PnL decomposition","","See pnl_decomposition.parquet and preflip_vs_wait_for_flip.parquet.","",
      "10. Stop sensitivity","",primary[primary.policy.isin(["P1","P3"])].to_string(index=False),"","11. Policy comparison","",primary.to_string(index=False),"","12. D10 exit versus opposite-flip fallback","","See d10_exit_contribution.parquet and d10_exit_reason_summary.parquet.","",
      "13. Same-timestamp event analysis","",f"Stop/logical-exit tie count: {int(t.same_bar_stop_logical_exit_tie.sum())}.","","14. Matched placebo controls","",f"See matched_placebo_summary, pairs, and balance artifacts. Maximum absolute design SMD: {design_bal.standardized_mean_difference.abs().max():.3f}; executed-pair SMD: {exec_bal.standardized_mean_difference.abs().max():.3f}.","","15. Tail dependence and runner capture","","See tail_dependence.parquet and runner_capture.parquet.","",
      "16. Failure modes","","No tick/quote path; intrabar ordering unknown; Contract 2 stop price is an OHLC assumption; Contract 3 sensitivity only; zero-exit months count non-positive.","","17. Decision recommendation","",f"{verdict}. Research conclusion only, not executable validation or parameter selection."]
    (RESULTS/"final_report.md").write_text("\n".join(sections),encoding="utf-8")
    required=["d10_entry_events.parquet","regime_d10_coverage.parquet","regime_d10_coverage_summary.parquet","forward_reversal_diagnostics.parquet","preflip_vs_wait_for_flip.parquet","policy_results.parquet","trade_results.parquet","monthly_results.parquet","segment_results.parquet","stop_sensitivity.parquet","pnl_decomposition.parquet","d10_exit_contribution.parquet","d10_exit_reason_summary.parquet","matched_placebo_summary.parquet","runner_capture.parquet","tail_dependence.parquet","final_report.md"]
    m=pd.DataFrame([{"file":x,"exists":(RESULTS/x).exists(),"size":(RESULTS/x).stat().st_size if (RESULTS/x).exists() else 0} for x in required]);m.to_parquet(AUDIT/"output_manifest_audit.parquet",index=False)
    if not m.exists.all() or not (m["size"]>0).all(): raise RuntimeError("Required output manifest failed")
    required_cols={"policy_results.parquet":{"execution_contract","year","policy","stop_atr_mult","ev_per_trade"},
        "segment_results.parquet":{"year","direction","session","stop_atr_mult","exit_reason"},
        "pnl_decomposition.parquet":{"pre_flip_pnl","post_flip_pnl","pre_flip_mae_atr","front_run_advantage_usd"},
        "d10_exit_contribution.parquet":{"natural_exit_net_pnl","incremental_pnl_from_d10","classification"}}
    schema=[]
    for fn,cols in required_cols.items():
        actual=set(pd.read_parquet(RESULTS/fn).columns);ok=cols<=actual
        schema.append({"file":fn,"required_columns":sorted(cols),"pass":ok})
    s=pd.DataFrame(schema);s.to_parquet(AUDIT/"output_schema_audit.parquet",index=False)
    if not s["pass"].all(): raise RuntimeError("Output schema audit failed")
    cells=pol.groupby(["execution_contract","year","policy"],dropna=False).size()
    expected={(c,y,p) for c in pol.execution_contract.unique() for y in (2025,2026) for p in ("P0","P1","P2","P3","P4A","P4B")}
    missing=expected-set(cells.index)
    pd.DataFrame([{"missing_cell":str(x)} for x in sorted(missing)],columns=["missing_cell"]).to_parquet(AUDIT/"output_cell_audit.parquet",index=False)
    if missing: raise RuntimeError(f"Missing policy cells: {missing}")


if __name__=="__main__":main()
