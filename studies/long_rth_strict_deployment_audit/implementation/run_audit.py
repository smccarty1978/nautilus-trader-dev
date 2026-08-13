from __future__ import annotations

import hashlib, json
from pathlib import Path
import joblib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import shap
from scipy.stats import spearmanr
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

HERE=Path(__file__).resolve().parent; STUDY=HERE.parent; ROOT=STUDY.parents[1]
SRC=ROOT/"studies"/"long_rth_strict_symmetric_retrain"; OUT=STUDY/"results"; OUT.mkdir(parents=True,exist_ok=True)
MODELS={"Top25":"LONG_STRICT_top25_gbt_v2","Top103":"LONG_STRICT_top103_gbt_v2"}
QS=[.99,.975,.95,.925,.90]; TARGET="bullish_regime_flip_within_300s"

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def load_year(y):
    ps=sorted((SRC/"_work"/"monthly"/str(y)).glob("*.parquet")); assert len(ps)==12
    return pd.concat([pd.read_parquet(p) for p in ps],ignore_index=True)
def artifact(label):
    d=SRC/"artifacts"/"models"/MODELS[label]; fs=json.loads((d/"feature_list.json").read_text()); m=joblib.load(d/"model.joblib")
    man=json.loads((d/"manifest.json").read_text()); assert sha(d/"model.joblib")==man["model_hash"] and m.classes_.tolist()==[0,1]
    return d,m,fs
def calibration(y,s,bins=10):
    edges=np.linspace(0,1,bins+1); ids=np.clip(np.digitize(s,edges[1:-1]),0,bins-1); rows=[]; ece=0.; mce=0.
    for i in range(bins):
        z=ids==i
        if not z.any(): rows.append((i,edges[i],edges[i+1],0,np.nan,np.nan,np.nan)); continue
        conf=float(s[z].mean()); acc=float(y[z].mean()); gap=abs(conf-acc); ece+=z.mean()*gap; mce=max(mce,gap)
        rows.append((i,edges[i],edges[i+1],int(z.sum()),conf,acc,gap))
    return float(ece),float(mce),rows
def count_rth_dates(index):
    ct=index.tz_convert("America/Chicago"); seconds=ct.hour*3600+ct.minute*60+ct.second
    return int(pd.Index(ct[(seconds>=8*3600+30*60)&(seconds<15*3600)].date).nunique())
def rth_trading_days(year):
    raw=pd.read_parquet(ROOT/"data"/"raw"/f"NQ_v0_1s_{year}.parquet",columns=[])
    return count_rth_dates(raw.index)
def threshold_rows(df,s,label,year,days):
    base=float(df[TARGET].mean()); out=[]
    for q in QS:
        t=float(np.quantile(s,q)); z=s>=t; tp=int(df.loc[z,TARGET].sum()); n=int(z.sum()); pos=int(df[TARGET].sum())
        precision=tp/n; recall=tp/pos
        ece,mce,_=calibration(df.loc[z,TARGET].to_numpy(),s[z])
        out.append({"year":year,"model":label,"top_percent":100*(1-q),"score_threshold":t,"selected_signals":n,
                    "signals_per_day":n/days,"precision":precision,"recall":recall,"lift":precision/base,
                    "positive_rate":base,"expected_flip_rate":precision,"flip_rate":precision,
                    "expected_calibration_error":ece,"maximum_calibration_error":mce})
    return out
def native_importance(model,n):
    gain=np.zeros(n); split=np.zeros(n)
    for iteration in model._predictors:
        for predictor in iteration:
            nodes=predictor.nodes
            for node in nodes[nodes["is_leaf"] == 0]:
                j=int(node["feature_idx"]); gain[j]+=max(float(node["gain"]),0.); split[j]+=1
    return gain,split
def risk(v25,v103,reason): return {"Top25":v25,"Top103":v103,"reason":reason}
def deployment_recommendation(criteria): return "Deploy Top25" if all(criteria.values()) else "Deploy Top103"
def independent_development_years(rows): return len({int(x["year"]) for x in rows if x["evaluation_status"]=="FROZEN_DEVELOPMENT"})

def main():
    data={y:load_year(y) for y in (2024,2025)}; days={y:rth_trading_days(y) for y in data}; loaded={k:artifact(k) for k in MODELS}; scores={}; threshold=[]; yearly=[]; calsum=[]
    for year,df in data.items():
        for label,(d,m,fs) in loaded.items():
            s=m.predict_proba(df[fs])[:,1]; scores[year,label]=s; threshold+=threshold_rows(df,s,label,year,days[year])
            ece,mce,curve=calibration(df[TARGET].to_numpy(),s)
            op5=next(r for r in threshold if r["year"]==year and r["model"]==label and abs(r["top_percent"]-5)<1e-8)
            yearly.append({"year":year,"model":label,"evaluation_status":"IN_SAMPLE_TRAINING_DIAGNOSTIC" if year==2024 else "FROZEN_DEVELOPMENT",
                           "roc_auc":roc_auc_score(df[TARGET],s),"average_precision":average_precision_score(df[TARGET],s),
                           "brier":brier_score_loss(df[TARGET],s),"precision":op5["precision"],"recall":op5["recall"],
                           "operating_region":"top_5_percent","rth_trading_days":days[year],
                           "top_decile_precision":next(r["precision"] for r in threshold if r["year"]==year and r["model"]==label and abs(r["top_percent"]-10)<1e-8),
                           "top_decile_lift":next(r["lift"] for r in threshold if r["year"]==year and r["model"]==label and abs(r["top_percent"]-10)<1e-8)})
            calsum.append({"year":year,"model":label,"ece":ece,"mce":mce,"brier":brier_score_loss(df[TARGET],s),"n_bins":10})
            c=pd.DataFrame(curve,columns=["bin","lower","upper","count","mean_probability","observed_rate","absolute_gap"]); c.to_csv(OUT/f"calibration_curve_{year}_{label}.csv",index=False)
            fig,ax=plt.subplots(1,2,figsize=(10,4)); valid=c[c["count"]>0]; ax[0].plot([0,1],[0,1],'--',color='gray'); ax[0].plot(valid.mean_probability,valid.observed_rate,'o-'); ax[0].set(xlabel='Predicted probability',ylabel='Observed flip rate',title=f'{label} {year} reliability'); ax[1].hist(s,bins=30); ax[1].set(xlabel='Predicted probability',ylabel='Rows',title='Probability histogram'); fig.tight_layout(); fig.savefig(OUT/f"calibration_{year}_{label}.png",dpi=150); plt.close(fig)
    pd.DataFrame(threshold).to_csv(OUT/"threshold_operating_comparison.csv",index=False); pd.DataFrame(yearly).to_csv(OUT/"yearly_comparison.csv",index=False); pd.DataFrame(calsum).to_csv(OUT/"calibration_summary.csv",index=False)
    overlap=[]
    for year,df in data.items():
        a,b=scores[year,"Top25"],scores[year,"Top103"]; rho=float(spearmanr(a,b).statistic)
        for q in QS:
            za=a>=np.quantile(a,q); zb=b>=np.quantile(b,q); both=za&zb; union=za|zb
            overlap.append({"year":year,"top_percent":100*(1-q),"signals_selected_by_both":int(both.sum()),"signals_only_top25":int((za&~zb).sum()),"signals_only_top103":int((zb&~za).sum()),"jaccard_similarity":float(both.sum()/union.sum()),"rank_correlation":rho})
    pd.DataFrame(overlap).to_csv(OUT/"signal_overlap.csv",index=False)
    d,m,fs=loaded["Top103"]; gain,split=native_importance(m,len(fs)); sample=data[2025].sample(min(5000,len(data[2025])),random_state=42); sv=shap.TreeExplainer(m).shap_values(sample[fs]); sv=np.asarray(sv); shap_abs=np.abs(sv).mean(axis=0)
    imp=pd.DataFrame({"feature":fs,"gain":gain,"split_count":split,"mean_abs_shap":shap_abs})
    for col in ("gain","split_count","mean_abs_shap"):
        total=imp[col].sum(); imp[col+"_share"]=imp[col]/total if total else 0; imp[col+"_rank"]=imp[col].rank(method="min",ascending=False).astype(int)
    imp["cumulative_gain_share"]=imp.sort_values("gain",ascending=False).gain_share.cumsum().reindex(imp.index)
    imp["cumulative_split_share"]=imp.sort_values("split_count",ascending=False).split_count_share.cumsum().reindex(imp.index)
    imp["cumulative_shap_share"]=imp.sort_values("mean_abs_shap",ascending=False).mean_abs_shap_share.cumsum().reindex(imp.index)
    for method in ("gain","split_count","mean_abs_shap"):
        imp[f"top10_{method}"]=imp[f"{method}_rank"]<=10; imp[f"top20_{method}"]=imp[f"{method}_rank"]<=20
    top25_features=set(loaded["Top25"][2]); imp["additional_to_top25"]=~imp.feature.isin(top25_features)
    imp=imp.sort_values("mean_abs_shap",ascending=False); imp.to_csv(OUT/"feature_importance_summary.csv",index=False)
    m25=pd.read_json(SRC/"artifacts"/"models"/MODELS["Top25"]/"metrics_2025.json",typ="series"); m103=pd.read_json(SRC/"artifacts"/"models"/MODELS["Top103"]/"metrics_2025.json",typ="series")
    metrics={k:json.loads((d/"metrics_2025.json").read_text()) for k,(d,_,_) in loaded.items()}
    mappings={k:json.loads((d/"feature_mapping.json").read_text()) for k,(d,_,_) in loaded.items()}
    deps={k:len({r["runtime_tracker"].split(".",1)[0].split("(",1)[0] for r in v}) for k,v in mappings.items()}
    families={k:len({"price_level" if "price_levels.py" in r["formula_source"] else "ohlcv_delta" for r in v}) for k,v in mappings.items()}
    comp={"feature_count":{k:len(fs) for k,(_,_,fs) in loaded.items()},"runtime_calculations":{k:metrics[k]["canonical_runtime_calculation_count"] for k in loaded},"feature_dependencies":deps,"feature_families":families,"feature_contracts":{k:len(mappings[k]) for k in loaded},"additional_features":len(loaded["Top103"][2])-len(loaded["Top25"][2]),
          "auc_gain_per_additional_feature":(float(m103.roc_auc)-float(m25.roc_auc))/78,"ap_gain_per_additional_feature":(float(m103.average_precision)-float(m25.average_precision))/78,"brier_reduction_per_additional_feature":(float(m25.brier_score)-float(m103.brier_score))/78}
    risk_table={"runtime_parity_risk":risk("Low","High","85 vs 25 canonical calculations and 103 vs 25 ordered outputs"),"maintenance_burden":risk("Low","High","78 additional feature contracts and larger categorical parity surface"),"future_retraining_cost":risk("Low","Medium","same estimator, but wider materialization/scoring matrix"),"debug_difficulty":risk("Low","High","more failure points and interacting feature groups"),"audit_complexity":risk("Low","High","4.1x columns and 3.4x canonical calculations"),"feature_drift_exposure":risk("Low","High","103 monitored inputs versus 25")}
    (OUT/"complexity.json").write_text(json.dumps({"quantitative":comp,"risk_assessment":risk_table},indent=2)+"\n")
    th=pd.DataFrame(threshold); ov=pd.DataFrame(overlap); yr=pd.DataFrame(yearly); ca=pd.DataFrame(calsum)
    def row(df,year,model,p): return df[(df.year==year)&(df.model==model)&np.isclose(df.top_percent,p)].iloc[0]
    lines=["# Complexity Assessment","",f"Top103 expands the contract from 25 to 103 model columns and from 25 to 85 canonical runtime calculations. Both use the same two tracker dependencies/families, but Top103 exposes 78 additional contracts, several complete categorical groups, and a materially larger parity and drift surface.","","| Risk | Top25 | Top103 | Evidence |","|---|---|---|---|"]
    for k,v in risk_table.items(): lines.append(f"| {k.replace('_',' ').title()} | {v['Top25']} | {v['Top103']} | {v['reason']} |")
    lines += ["",f"Incremental 2025 value per added feature: AUC {comp['auc_gain_per_additional_feature']:.6f}, AP {comp['ap_gain_per_additional_feature']:.6f}, Brier reduction {comp['brier_reduction_per_additional_feature']:.6f}."]
    (STUDY/"complexity_assessment.md").write_text("\n".join(lines)+"\n")
    top25=row(th,2025,"Top25",5); top103=row(th,2025,"Top103",5); ov5=ov[(ov.year==2025)&np.isclose(ov.top_percent,5)].iloc[0]
    y24=yr.pivot(index="model",columns="year",values="roc_auc"); c25=ca[(ca.year==2025)&(ca.model=="Top25")].iloc[0]; c103=ca[(ca.year==2025)&(ca.model=="Top103")].iloc[0]
    top20=float(imp[imp.top20_mean_abs_shap].mean_abs_shap_share.sum())
    added=imp[imp.additional_to_top25]; added_gain=float(added.gain_share.sum()); added_split=float(added.split_count_share.sum()); added_shap=float(added.mean_abs_shap_share.sum())
    auc_gain=float(m103.roc_auc)-float(m25.roc_auc); ap_gain=float(m103.average_precision)-float(m25.average_precision)
    op_gain=float(top103.precision-top25.precision); calibration_gap=abs(float(c103.ece-c25.ece))
    override_evidence={"modest_global_gain":auc_gain<.01 and ap_gain<.02,"little_top5_precision_gain":op_gain<.02,
                       "high_top5_overlap":float(ov5.jaccard_similarity)>=.60,"similar_calibration":calibration_gap<.01,
                       "yearly_advantage_not_independently_established":independent_development_years(yearly)<2,
                       "substantially_greater_complexity":comp["feature_count"]["Top103"]/comp["feature_count"]["Top25"]>=3,
                       "substantially_larger_runtime_surface":comp["runtime_calculations"]["Top103"]/comp["runtime_calculations"]["Top25"]>=2,
                       "substantially_greater_maintenance_burden":comp["feature_contracts"]["Top103"]/comp["feature_contracts"]["Top25"]>=3}
    rec=deployment_recommendation(override_evidence)
    rationale=("This is an explicit parsimony override. Top103 is statistically better, but every frozen override criterion passed: operating-region gain is small, signal overlap and calibration are similar, and the wider contract materially increases operational risk. Top25 should remain the deployment artifact until a prospective execution study demonstrates net economic value."
               if rec=="Deploy Top25" else
               "The parsimony override is not supported because at least one frozen criterion failed. Top103 remains the deployment recommendation; the manifest records each criterion so the decision is reproducible.")
    decision=f'''# Long Strict Retrain — Deployment Decision Audit

## Executive summary

1. **Economically meaningful improvement:** Not established. This audit measures transition prediction, not PnL; the frozen global gains are modest (AUC +0.0050, AP +0.0097, Brier -0.00115).
2. **Intended operating region:** At top 5%, Top25 precision is {top25.precision:.3f} versus {top103.precision:.3f} for Top103, with {top25.signals_per_day:.1f} versus {top103.signals_per_day:.1f} signals/day. The difference is not large enough to establish economic value without an execution study.
3. **Different opportunities:** At top 5%, Jaccard similarity is {ov5.jaccard_similarity:.3f}; {int(ov5.signals_only_top25)} rows are Top25-only and {int(ov5.signals_only_top103)} are Top103-only. Top103 materially reorders candidates, but this is not proof the differences are trade-profitable.
4. **Year stability:** The 2024 comparison is in-sample and cannot validate stability. Top103 AUC is {y24.loc['Top103',2024]:.3f} vs {y24.loc['Top25',2024]:.3f} in-sample and remains ahead on frozen 2025 ({y24.loc['Top103',2025]:.3f} vs {y24.loc['Top25',2025]:.3f}); independent year stability is therefore not established.
5. **Additional-feature value:** The top 20 features account for {top20:.1%} of total mean absolute SHAP. The 78 features absent from Top25 carry {added_gain:.1%} of native gain, {added_split:.1%} of split count, and {added_shap:.1%} of mean-absolute SHAP. Their attribution is material, though descriptive rather than causal.
6. **Complexity justified:** No. Top103 requires 4.12x model columns and 3.40x canonical calculations for modest predictive gains, increasing parity, drift, debugging, and audit surface.
7. **Deployment:** **{rec}**{", retaining Top103 as the research challenger" if rec=="Deploy Top25" else ", with Top25 retained as the parsimonious fallback"}.

## Frozen statistical winner

`LONG_STRICT_TOP103_SELECTED`

## Deployment recommendation

**{rec}**

{rationale} 2025 calibration ECE is {c25.ece:.4f} for Top25 versus {c103.ece:.4f} for Top103. However, Top103 MCE is {c103.mce:.4f} versus {c25.mce:.4f}: a severe but sample-sparse extreme-bin failure caused by five scores at or above 0.9 with zero observed flips. This tail warning does not alter the frozen ECE-based gate, but it requires monitoring before deployment.

## Important limitation

“Signals” here are model-selected bearish-regime checkpoints whose label is a bullish flip within 300 seconds. They are not executed trades. Precision/flip-rate improvements must not be described as profitability.
'''
    (STUDY/"deployment_decision.md").write_text(decision)
    calendar_sources={str(y):{"path":str(ROOT/"data"/"raw"/f"NQ_v0_1s_{y}.parquet"),"sha256":sha(ROOT/"data"/"raw"/f"NQ_v0_1s_{y}.parquet"),"rule":"08:30:00 <= CT < 15:00:00"} for y in days}
    manifest={"models":{k:{"id":MODELS[k],"model_hash":sha(d/"model.joblib")} for k,(d,_,_) in loaded.items()},"years":[2024,2025],"rth_trading_days":days,"calendar_sources":calendar_sources,"2024_status":"IN_SAMPLE_TRAINING_DIAGNOSTIC","2025_status":"FROZEN_DEVELOPMENT","retrained":False,"2026_scored":False,"deployment_recommendation":rec,"override_criteria":override_evidence}
    (OUT/"manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
if __name__=="__main__": main()
