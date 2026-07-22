from pathlib import Path
import json, shutil
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

STUDY=Path(__file__).resolve().parent.parent; NEW=STUDY/"results"; OLD=STUDY.parent/"pre_flip_signal_reliability"/"results"
PCTS=[1.0,2.5,5.0]
def ci_delta(a,b,fn=np.median,n=2000):
    x=pd.DataFrame({"a":a,"b":b}).dropna().to_numpy(); rng=np.random.default_rng(42)
    if not len(x): return (np.nan,np.nan,np.nan)
    d=[]
    for _ in range(n):
        idx=rng.integers(0,len(x),len(x)); d.append(fn(x[idx,1])-fn(x[idx,0]))
    d=np.asarray(d)
    return float(fn(x[:,1])-fn(x[:,0])),float(np.quantile(d,.025)),float(np.quantile(d,.975))
def main():
    old=pd.read_csv(OLD/"signal_population.csv"); new=pd.read_csv(NEW/"signal_population.csv")
    o=pd.read_csv(NEW/"signal_population_top25_recomputed.csv"); n=new[new.direction=="long"]
    baseline=old[old.direction=="long"].reset_index(drop=True)
    if not set(baseline.columns).issubset(o.columns): raise RuntimeError("Top25 recomputation missing baseline columns")
    pd.testing.assert_frame_equal(o[baseline.columns].reset_index(drop=True),baseline,check_dtype=False,check_exact=True)
    # Required suffixed copies preserve validated schemas.
    shutil.copy2(NEW/"signal_population.csv",NEW/"signal_population_top103.csv")
    for src,dst in (("threshold_summary.csv","threshold_summary_top103.csv"),("direction_comparison.csv","direction_comparison_top103.csv"),("signal_bucket_summary.csv","bucket_summary_top103.csv")):
        shutil.copy2(NEW/src,NEW/dst)
    th_old=pd.read_csv(OLD/"threshold_summary.csv"); th_new=pd.read_csv(NEW/"threshold_summary.csv"); rows=[]; overlaps=[]
    for pct in PCTS:
        a=o[np.isclose(o.threshold_pct,pct)].copy(); b=n[np.isclose(n.threshold_pct,pct)].copy(); keys=["regime_start_ns","signal_ts"]
        ka=set(map(tuple,a[keys].astype("int64").to_numpy())); kb=set(map(tuple,b[keys].astype("int64").to_numpy())); shared=ka&kb
        common_scores=pd.read_parquet(NEW/"common_checkpoint_scores.parquet"); rho=float(spearmanr(common_scores.top25_score,common_scores.top103_score).statistic)
        overlaps.append({"threshold_pct":pct,"shared_signals":len(shared),"top25_only":len(ka-kb),"top103_only":len(kb-ka),"jaccard_similarity":len(shared)/len(ka|kb),"rank_correlation":rho})
        for label,g in (("Top25",a),("Top103",b)):
            ttf=g.time_to_flip_s.dropna(); rows.append({"threshold_pct":pct,"model":label,"signals_per_day":len(g)/(252*2),"median_seconds_to_flip":ttf.median(),"p90_seconds_to_flip":ttf.quantile(.9),"p95_seconds_to_flip":ttf.quantile(.95),"prob_flip_le_300s":(g.time_to_flip_s<=300).mean(),"prob_flip_le_600s":(g.time_to_flip_s<=600).mean(),"median_remaining_mfe_atr":g.rem_mfe_atr.median(),"median_path_mae_atr":g.path_mae_atr.median(),"median_flip_exit_pnl_pts":g.flip_exit_pnl_pts.median(),"median_captured_movement_pct":g.captured_mfe_pct.median(),"no_flip_le_300":int((~(g.time_to_flip_s<=300)).sum()),"no_flip_le_600":int((~(g.time_to_flip_s<=600)).sum()),"never_flip":int(g.time_to_flip_s.isna().sum()),"bucket_A":int((g.bucket=='Bucket A').sum()),"bucket_B":int((g.bucket=='Bucket B').sum()),"bucket_C":int((g.bucket=='Bucket C').sum())})
    comp=pd.DataFrame(rows); wide=comp.pivot(index="threshold_pct",columns="model"); out=[]
    for pct in PCTS:
        r={"threshold_pct":pct}
        for metric in [c for c in comp.columns if c not in ("threshold_pct","model")]:
            a=float(wide.loc[pct,(metric,"Top25")]); b=float(wide.loc[pct,(metric,"Top103")]); r[metric+"_top25"]=a; r[metric+"_top103"]=b; r[metric+"_abs_change"]=b-a; r[metric+"_relative_change"]=(b-a)/abs(a) if a else np.nan
        out.append(r)
    pd.DataFrame(out).to_csv(NEW/"top25_vs_top103_thresholds.csv",index=False); pd.DataFrame(overlaps).to_csv(NEW/"top25_vs_top103_signal_overlap.csv",index=False)
    # Reliability curve on identical full checkpoint population, pre-selection.
    rel=[]; common=pd.read_parquet(NEW/"common_checkpoint_scores.parquet"); common["time_to_flip_s"]=(common.confirm_flip_ns-common.observation_time)/1e9
    for label,col in (("Top25","top25_score"),("Top103","top103_score")):
        g=common.copy(); g["score_percentile_bin"]=pd.qcut(g[col].rank(method="first"),10,labels=False)+1
        for b,z in g.groupby("score_percentile_bin"): rel.append({"model":label,"percentile_decile":int(b),"checkpoints":len(z),"flip_le_300":(z.time_to_flip_s<=300).mean(),"flip_le_600":(z.time_to_flip_s<=600).mean()})
    pd.DataFrame(rel).to_csv(NEW/"reliability_curves_top25_vs_top103.csv",index=False)
    # Paired shared-signal diagnostics.
    tests=[]
    for pct in PCTS:
        a=o[np.isclose(o.threshold_pct,pct)].set_index("regime_start_ns"); b=n[np.isclose(n.threshold_pct,pct)].set_index("regime_start_ns"); idx=a.index.intersection(b.index); aa=a.loc[idx].copy(); bb=b.loc[idx].copy()
        for horizon in (300,600): aa[f"flip_le_{horizon}"]=(aa.time_to_flip_s<=horizon).astype(float); bb[f"flip_le_{horizon}"]=(bb.time_to_flip_s<=horizon).astype(float)
        for metric in ("time_to_flip_s","rem_mfe_atr","path_mae_atr","flip_exit_pnl_pts","captured_mfe_pct","flip_le_300","flip_le_600"):
            fn=np.mean if metric.startswith("flip_le") else np.median; delta,lo,hi=ci_delta(aa[metric],bb[metric],fn=fn); eff=pd.DataFrame({"a":aa[metric],"b":bb[metric]}).dropna()
            tests.append({"threshold_pct":pct,"metric":metric,"paired_n":len(eff),"top103_minus_top25":delta,"ci95_low":lo,"ci95_high":hi})
    tests_df=pd.DataFrame(tests); tests_df.to_csv(NEW/"paired_statistical_tests.csv",index=False)
    c=pd.DataFrame(out); ov=pd.DataFrame(overlaps); r5=c[c.threshold_pct==5].iloc[0]; o5=ov[ov.threshold_pct==5].iloc[0]
    cc=c.set_index("threshold_pct"); flip=tests_df[tests_df.metric=="flip_le_300"].set_index("threshold_pct"); change=cc.prob_flip_le_300s_abs_change; time=cc.median_seconds_to_flip_abs_change
    canonical=((change>=0).all() and (change>0).sum()>=2 and (flip.ci95_low>0).any() and (time<=0).sum()>=2 and (time<=60).all() and (cc.median_remaining_mfe_atr_abs_change<=.10).all() and (cc.median_path_mae_atr_abs_change<=.10).all())
    rec="Replace it with the Top103 study as the new canonical reference." if canonical else "Continue using the Top25 pre-flip reliability study as the canonical reference."
    report=f'''# Top25 vs Top103 Pre-Flip Reliability Comparison\n\n## Recommendation\n\n**{rec}**\n\nAt Top 5%, Top103 changes flip-within-300s probability by {r5.prob_flip_le_300s_abs_change:+.3f}, median time-to-flip by {r5.median_seconds_to_flip_abs_change:+.1f}s, remaining MFE by {r5.median_remaining_mfe_atr_abs_change:+.3f} ATR, and path MAE by {r5.median_path_mae_atr_abs_change:+.3f} ATR. Signal Jaccard is {o5.jaccard_similarity:.3f}. These are forecasting/path diagnostics, not PnL evidence from an execution policy.\n\nSee `top25_vs_top103_thresholds.csv`, `top25_vs_top103_signal_overlap.csv`, `reliability_curves_top25_vs_top103.csv`, and `paired_statistical_tests.csv`.\n'''
    (STUDY/"top25_vs_top103_comparison.md").write_text(report)
    shutil.copy2(STUDY/"top25_vs_top103_comparison.md",STUDY/"study_report_top103.md")
    (NEW/"audit_packet.json").write_text(json.dumps({"original_study":str(OLD.parent),"long_model":"LONG_STRICT_top103_gbt_v2","short_model":"short_bearish_flip_top25_current_reference","years":[2024,2025],"2026_loaded":False,"methodology_change":"long model only"},indent=2)+"\n")
if __name__=="__main__": main()
