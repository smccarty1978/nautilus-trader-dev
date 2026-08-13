from __future__ import annotations

import gc
import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import yaml

ROOT = Path(__file__).resolve().parents[3]
STUDY = Path(__file__).resolve().parents[1]
RESULTS = STUDY / "results"
WORK = STUDY / "_work"
CFG = yaml.safe_load((STUDY / "config.yaml").read_text())
YEARS = tuple(CFG["years"])
KEY = ["direction", "regime_start_ns", "observation_time"]
EVENT_INPUT = ["regime_start_ns", "observation_time", "confirm_flip_ns"]

BULL_ART = ROOT / "studies/freeze_reduced_flip_model_artifacts/artifacts/short_bearish_flip_top25_current_reference"
BEAR_ART = ROOT / "studies/freeze_long_strict_models_v2/artifacts/LONG_STRICT_top25_gbt_v2"
BULL_WORK = ROOT / "studies/short_rth_pure_flip_prediction_enriched/_work"
BEAR_WORK = ROOT / "studies/long_rth_strict_symmetric_retrain/_work/monthly"
BEAR_ATTACHED = ROOT / "studies/long_rth_mirrored_surface_top100_training/_work"
RAW = {y: ROOT / f"data/raw/NQ_v0_1s_{y}.parquet" for y in YEARS}
TIMELINE_MODULE = ROOT / "studies/CODEX_5_X_weakness_atlas_repair/CODEX_5_X_run_established_fade.py"
ATLAS_DIR = ROOT / "studies/CODEX_5_X_weakness_atlas_repair/_work/CODEX_5_X_repaired_years"

FORBIDDEN_OUTPUT_TOKENS = ("stop", "target", "exit_ts", "hit_opposing", "trade_survival",
                           "policy", "simulated_trade", "profit_target")
NS = 1_000_000_000


def sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda:f.read(1024*1024),b""):h.update(block)
    return h.hexdigest()


def feature_list_hash(features:list[str])->str:
    return hashlib.sha256(json.dumps(features).encode()).hexdigest()


def validate_frozen_inputs(bf:list[str],lf:list[str])->dict:
    bull=json.loads((BULL_ART/"manifest.json").read_text());bear=json.loads((BEAR_ART/"manifest.json").read_text())
    if sha256(BULL_ART/"model.joblib")!=bull["model_artifact_sha256"] or feature_list_hash(bf)!=bull["raw_feature_list_sha256"]:
        raise RuntimeError("Bullish frozen artifact/hash contract failed")
    if sha256(BEAR_ART/"model.joblib")!=bear["model_hash"] or feature_list_hash(lf)!=bear["ordered_feature_list_hash"]:
        raise RuntimeError("Bearish frozen artifact/hash contract failed")
    monthly={}
    for year in YEARS:
        bull_source=BULL_WORK/f"prepared_{year}.parquet";frozen=CFG["bullish_prepared_inputs"][year]
        if int(pq.ParquetFile(bull_source).metadata.num_rows)!=frozen["rows"] or sha256(bull_source)!=frozen["sha256"]:
            raise RuntimeError(f"Bullish {year}: exact frozen source mismatch")
        cp=json.loads((BEAR_WORK/str(year)/"checkpoint.json").read_text());paths=sorted((BEAR_WORK/str(year)).glob("*.parquet"))
        if cp["completed_months"]!=cp["expected_months"] or [p.stem for p in paths]!=cp["expected_months"]:
            raise RuntimeError(f"Bearish {year}: incomplete monthly checkpoint")
        if cp["feature_list_hashes"]["LONG_STRICT_top25_gbt_v2"]!=feature_list_hash(lf):raise RuntimeError("Bearish feature contract stale")
        source=BEAR_ATTACHED/f"attached_long_{year}.parquet"
        if cp["source_hashes"][str(source)]!=sha256(source):raise RuntimeError(f"Bearish {year}: attached source hash mismatch")
        rows=0
        for p in paths:
            mm=json.loads(p.with_suffix(".manifest.json").read_text())
            if mm["output_hash"]!=sha256(p):raise RuntimeError(f"{p}: monthly output hash mismatch")
            rows+=int(mm["rows"])
        if rows!=cp["row_count"]:raise RuntimeError(f"Bearish {year}: monthly row count mismatch")
        monthly[str(year)]={"checkpoint_sha256":sha256(BEAR_WORK/str(year)/"checkpoint.json"),"rows":rows}
    return {"bullish_manifest_sha256":sha256(BULL_ART/"manifest.json"),"bearish_manifest_sha256":sha256(BEAR_ART/"manifest.json"),"bearish_monthly":monthly}


def parquet_uncompressed_bytes(path:Path)->int:
    meta=pq.ParquetFile(path).metadata
    return sum(meta.row_group(i).total_byte_size for i in range(meta.num_row_groups))


def conservative_memory_bound_mb()->float:
    sources=[*(BULL_WORK/f"prepared_{y}.parquet" for y in YEARS),*(BEAR_ATTACHED/f"attached_long_{y}.parquet" for y in YEARS),*RAW.values()]
    sources.extend(p for y in YEARS for p in (BEAR_WORK/str(y)).glob("*.parquet"))
    source_bytes=sum(parquet_uncompressed_bytes(p) for p in sources)
    max_raw_rows=max(pq.ParquetFile(RAW[y]).metadata.num_rows for y in YEARS);tree_n=1<<(max_raw_rows-1).bit_length()
    max_population_rows=max(CFG["bullish_prepared_inputs"][y]["rows"]+json.loads((BEAR_WORK/str(y)/"checkpoint.json").read_text())["row_count"] for y in YEARS)
    interval_count=1+len(CFG["fixed_horizons_seconds"])+len(CFG["post_flip_horizons_seconds"])+1
    # Two copies of every uncompressed source (although years are processed serially),
    # exact max/min tree storage, 96 bytes of query scratch per row/interval,
    # then a 25% allocator/DataFrame/index safety margin.
    estimate=1.25*(2*source_bytes+2*tree_n*12+max_population_rows*interval_count*96)
    return estimate/(1024**2)


def assert_keys(df:pd.DataFrame,keys:list[str],name:str)->None:
    if df[keys].isna().any().any() or df.duplicated(keys).any():raise RuntimeError(f"{name}: null/duplicate key")


def assert_same_keys(a:pd.DataFrame,b:pd.DataFrame,keys:list[str],an:str,bn:str)->None:
    assert_keys(a,keys,an);assert_keys(b,keys,bn)
    ai=pd.MultiIndex.from_frame(a[keys]);bi=pd.MultiIndex.from_frame(b[keys])
    if len(ai)!=len(bi) or not ai.equals(bi):raise RuntimeError(f"{an}/{bn}: key mismatch")


def feature_order(path:Path)->list[str]:
    p=path/"feature_order.csv"
    return pd.read_csv(p).feature_name.tolist() if p.exists() else json.loads((path/"feature_list.json").read_text())


def rth_mask(ns:pd.Series)->pd.Series:
    t=pd.to_datetime(ns,unit="ns",utc=True).dt.tz_convert("America/Chicago").dt.time
    return (t>=pd.Timestamp(CFG["rth_start"]).time())&(t<pd.Timestamp(CFG["rth_end_exclusive"]).time())


def build_events(df:pd.DataFrame)->pd.DataFrame:
    if list(df.columns)!=EVENT_INPUT:raise RuntimeError("event builder received non-contract columns")
    out=df.copy();out["seconds_to_flip"]=(out.confirm_flip_ns-out.observation_time)/NS
    if not (out.seconds_to_flip>0).all():raise RuntimeError("non-positive confirmed-flip horizon")
    out["flip_le_300"]=out.seconds_to_flip<=300;out["flip_le_600"]=out.seconds_to_flip<=600
    return out


def load_and_score_year(direction:str,year:int,model,features:list[str])->pd.DataFrame:
    if direction=="bullish_fade":
        d=pd.read_parquet(BULL_WORK/f"prepared_{year}.parquet")
        if set(d.entry_direction.astype(int).unique())!={-1}:raise RuntimeError("Bullish direction contract failed")
        d=d.loc[rth_mask(d.observation_time)].reset_index(drop=True)
        missing=set(features)-set(d.columns)
        if missing:raise RuntimeError(f"Bullish missing model features: {sorted(missing)}")
        score=model.predict_proba(d[features])[:,1]
        slim=d[["regime_start_ns","observation_time","confirm_flip_ns","entry_px","atr_at_entry"]].copy()
        slim=slim.rename(columns={"entry_px":"checkpoint_price","atr_at_entry":"atr_at_checkpoint"})
        trade_direction=-1
    else:
        monthly=sorted((BEAR_WORK/str(year)).glob("*.parquet"))
        if len(monthly)!=12:raise RuntimeError(f"Bearish {year}: incomplete monthly matrix")
        matrix=pd.concat((pd.read_parquet(p) for p in monthly),ignore_index=True)
        missing=set(features)-set(matrix.columns)
        if missing:raise RuntimeError(f"Bearish missing model features: {sorted(missing)}")
        score=model.predict_proba(matrix[features])[:,1]
        attached=pd.read_parquet(BEAR_ATTACHED/f"attached_long_{year}.parquet",
            columns=["regime_start_ns","observation_time","confirm_flip_ns","fill_px","atr_at_checkpoint","prevailing_direction"])
        attached=attached.loc[rth_mask(attached.observation_time)].reset_index(drop=True)
        assert_same_keys(matrix,attached,["regime_start_ns","observation_time"],f"Bear matrix {year}",f"Bear attached {year}")
        if set(attached.prevailing_direction.astype(int).unique())!={-1}:raise RuntimeError("Bearish direction contract failed")
        slim=attached.drop(columns="prevailing_direction").rename(columns={"fill_px":"checkpoint_price"})
        trade_direction=1
        del matrix,attached
    events=build_events(slim[EVENT_INPUT])
    slim["seconds_to_flip"]=events.seconds_to_flip.to_numpy();slim["flip_le_300"]=events.flip_le_300.to_numpy();slim["flip_le_600"]=events.flip_le_600.to_numpy()
    observed_years=set(pd.to_datetime(slim.observation_time,unit="ns",utc=True).dt.year.unique())
    if observed_years!={year}:raise RuntimeError(f"{direction} {year}: observation calendar-year mismatch {observed_years}")
    slim["direction"]=direction;slim["year"]=year;slim["artifact_name"]=("BULLISH_FADE_TO_BEARISH_FLIP_TOP25_GBT_V1" if trade_direction<0 else "BEARISH_FADE_TO_BULLISH_FLIP_TOP25_GBT_V2")
    slim["artifact_causal_status"]=("PROVISIONAL_KNOWN_1S_LOOKAHEAD" if trade_direction<0 else "STRICT_CAUSAL")
    slim["known_feature_lookahead_seconds"]=(1.0 if trade_direction<0 else 0.0)
    slim["trade_direction"]=trade_direction;slim["model_score"]=score
    if slim[["checkpoint_price","atr_at_checkpoint"]].isna().any().any() or not np.isfinite(slim[["checkpoint_price","atr_at_checkpoint"]]).all().all() or not (slim.atr_at_checkpoint>0).all():raise RuntimeError(f"{direction} {year}: invalid checkpoint price/ATR")
    slim=slim.sort_values(["regime_start_ns","observation_time"]).reset_index(drop=True)
    slim["checkpoint_sequence"]=slim.groupby("regime_start_ns").cumcount()+1
    slim["regime_age_seconds"]=(slim.observation_time-slim.regime_start_ns)/NS
    assert_keys(slim,KEY,f"{direction} {year}")
    return slim


def add_score_buckets(d:pd.DataFrame)->pd.DataFrame:
    out=[]
    for direction,g in d.groupby("direction",sort=False):
        g=g.copy();g["score_percentile"]=g.model_score.rank(method="average",pct=True)*100
        thresholds={p:float(np.percentile(g.model_score,100-p)) for p in CFG["score_top_percentiles"]}
        for p,q in thresholds.items():
            suffix=str(p).replace(".0","").replace(".","_")
            flag=f"is_top_{suffix}";first=f"is_first_top_{suffix}"
            g[flag]=g.model_score>=q
            first_idx=(g[g[flag]].sort_values("observation_time").groupby("regime_start_ns").head(1).index)
            g[first]=False;g.loc[first_idx,first]=True
        conditions=[g.is_top_1,g.is_top_2_5,g.is_top_5,g.is_top_10,g.is_top_25]
        g["top_bucket"]=np.select(conditions,["top_1","top_2_5","top_5","top_10","top_25"],default="below_top_25")
        g["selected_first_signal"]=g.is_first_top_1|g.is_first_top_2_5|g.is_first_top_5|g.is_first_top_10|g.is_first_top_25
        out.append(g)
    return pd.concat(out,ignore_index=True)


def verify_parity(d:pd.DataFrame,bear_model,bear_features:list[str])->dict:
    b=d[(d.direction=="bullish_fade")&(d.year==2025)]
    ref=pd.read_parquet(BULL_ART/"score_reference_2025.parquet")
    assert_same_keys(b,ref,["regime_start_ns","observation_time"],"Bull score","Bull ref")
    m=b[["regime_start_ns","observation_time","model_score"]].merge(ref[["regime_start_ns","observation_time","score"]],on=["regime_start_ns","observation_time"],validate="one_to_one")
    bd=float(np.abs(m.model_score-m.score).max())
    fixture=pd.read_parquet(BEAR_ART/"validation_fixture.parquet");expected=np.load(BEAR_ART/"validation_fixture_scores.npy")
    ld=float(np.abs(bear_model.predict_proba(fixture[bear_features])[:,1]-expected).max())
    if bd!=0 or ld!=0:raise RuntimeError(f"prediction parity failure {bd}/{ld}")
    return {"bullish_reference_max_abs_diff":bd,"bearish_fixture_max_abs_diff":ld}


def load_raw(year:int)->tuple[pd.DataFrame,dict[str,np.ndarray]]:
    raw=pd.read_parquet(RAW[year]);
    if raw.index.name!="ts_event":raise RuntimeError(f"raw {year}: ts_event index required")
    ts=raw.index.astype("int64").to_numpy();
    if np.any(np.diff(ts)<=0):raise RuntimeError(f"raw {year}: timestamps not strictly increasing")
    raw_years=set(pd.to_datetime(ts,unit="ns",utc=True).year)
    if raw_years!={year}:raise RuntimeError(f"raw {year}: calendar-year mismatch {raw_years}")
    return raw,{"ts":ts,**{c:raw[c].to_numpy(dtype=float) for c in ("open","high","low","close")}}


def canonical_timeline(year:int,raw:pd.DataFrame)->pd.DataFrame:
    module_dir=str(TIMELINE_MODULE.parent)
    if module_dir not in sys.path:sys.path.insert(0,module_dir)
    spec=importlib.util.spec_from_file_location("_canonical_timeline",TIMELINE_MODULE);mod=importlib.util.module_from_spec(spec);sys.modules[spec.name]=mod;spec.loader.exec_module(mod)
    t=mod.canonical_regime_timeline(year,raw)
    upstream=str(ROOT/"studies/regime_sequence_chop_context")
    if upstream not in sys.path:sys.path.insert(0,upstream)
    from reproduce_regimes import aggregate_and_run_regimes
    minute=aggregate_and_run_regimes(raw,"1m")
    atr_map=minute.set_index("close_ts").atr
    t["atr_at_confirmed_flip"]=t.regime_start_ns.map(atr_map)
    if t.atr_at_confirmed_flip.isna().any() or not (t.atr_at_confirmed_flip>0).all():raise RuntimeError(f"{year}: invalid canonical flip ATR")
    return t


class RangeTree:
    def __init__(self,values:np.ndarray,mode:str):
        self.n=1<<(len(values)-1).bit_length();neutral=-np.inf if mode=="max" else np.inf
        self.values=np.full(2*self.n,neutral,dtype=np.float64);self.indices=np.full(2*self.n,-1,dtype=np.int32);self.mode=mode
        self.values[self.n:self.n+len(values)]=values;self.indices[self.n:self.n+len(values)]=np.arange(len(values),dtype=np.int32)
        start=self.n//2
        while start>=1:
            parents=np.arange(start,2*start,dtype=np.int64);a=2*parents;b=a+1
            choose=(self.values[a]>=self.values[b]) if mode=="max" else (self.values[a]<=self.values[b])
            src=np.where(choose,a,b);self.values[parents]=self.values[src];self.indices[parents]=self.indices[src];start//=2
    def query(self,left:np.ndarray,right:np.ndarray)->tuple[np.ndarray,np.ndarray]:
        l=left.astype(np.int64)+self.n;r=right.astype(np.int64)+self.n;neutral=-np.inf if self.mode=="max" else np.inf
        best=np.full(len(l),neutral);idx=np.full(len(l),-1,dtype=np.int32)
        while np.any(l<r):
            active=l<r
            ml=active&(l&1).astype(bool);pos=np.minimum(l,len(self.values)-1);cand=self.values[pos];ci=self.indices[pos];cmp=(cand>best) if self.mode=="max" else (cand<best);better=ml&(cmp|((cand==best)&(ci>=0)&((idx<0)|(ci<idx))));best[better]=cand[better];idx[better]=ci[better];l=(l+ml.astype(np.int64))//2
            mr=active&(r&1).astype(bool);r=r-mr.astype(np.int64);pos=np.minimum(r,len(self.values)-1);cand=self.values[pos];ci=self.indices[pos];cmp=(cand>best) if self.mode=="max" else (cand<best);better=mr&(cmp|((cand==best)&(ci>=0)&((idx<0)|(ci<idx))));best[better]=cand[better];idx[better]=ci[better];r//=2
        return best,idx


def validate_range_tree_contract()->None:
    # Power-of-two length exercises terminal [N,N); repeated minima/maxima span nodes.
    values=np.array([3.,1.,7.,1.,2.,9.,4.,9.])
    left=[];right=[]
    for l in range(len(values)+1):
        for r in range(l,len(values)+1):left.append(l);right.append(r)
    left=np.asarray(left);right=np.asarray(right)
    for mode in ("max","min"):
        got,idx=RangeTree(values,mode).query(left,right);neutral=-np.inf if mode=="max" else np.inf
        for k,(l,r) in enumerate(zip(left,right)):
            if l==r:
                expected=neutral;expected_idx=-1
            else:
                slice_=values[l:r];expected=(slice_.max() if mode=="max" else slice_.min());expected_idx=l+int(np.flatnonzero(slice_==expected)[0])
            if got[k]!=expected or idx[k]!=expected_idx:raise RuntimeError(f"RangeTree contract failure {mode} [{l},{r}): {got[k]}/{idx[k]} != {expected}/{expected_idx}")


def validate_direct_slice_parity(intervals:list[tuple],a:dict[str,np.ndarray],high:np.ndarray,low:np.ndarray,hi:np.ndarray,li:np.ndarray,n_rows:int)->None:
    for block,(name,left,right,_,_,available) in enumerate(intervals):
        candidates=np.unique(np.concatenate((np.flatnonzero(~available),np.linspace(0,n_rows-1,min(257,n_rows),dtype=int))))
        offset=block*n_rows
        for row in candidates:
            l=int(left[row]);r=int(right[row]);k=offset+row
            if not available[row]:
                if hi[k]!=-1 or li[k]!=-1:raise RuntimeError(f"{name} row {row}: unavailable range returned extrema")
                continue
            hs=a["high"][l:r];ls=a["low"][l:r];eh=float(hs.max());el=float(ls.min())
            ehi=l+int(np.flatnonzero(hs==eh)[0]);eli=l+int(np.flatnonzero(ls==el)[0])
            if high[k]!=eh or low[k]!=el or hi[k]!=ehi or li[k]!=eli:raise RuntimeError(f"{name} row {row}: segment/direct slice mismatch")


def build_intervals(d:pd.DataFrame,timeline:pd.DataFrame,ts:np.ndarray)->tuple[pd.DataFrame,list[tuple]]:
    d=d.copy();obs=d.observation_time.to_numpy(np.int64);flip=d.confirm_flip_ns.to_numpy(np.int64);coverage_end=int(ts[-1]+NS)
    starts=np.searchsorted(ts,obs,side="right");flip_end=np.searchsorted(ts,flip,side="left")
    intervals=[("to_flip",starts,flip_end,obs,flip,np.ones(len(d),bool))]
    for h in CFG["fixed_horizons_seconds"]:
        endpoint=obs+h*NS;intervals.append((f"fixed_{h}",starts,np.searchsorted(ts,endpoint,side="left"),obs,endpoint,np.ones(len(d),bool)))
    post_start=np.searchsorted(ts,flip,side="right")
    for h in CFG["post_flip_horizons_seconds"]:
        endpoint=flip+h*NS;intervals.append((f"post_{h}",post_start,np.searchsorted(ts,endpoint,side="left"),flip,endpoint,np.ones(len(d),bool)))
    assert_keys(timeline,["regime_start_ns"],"canonical timeline")
    timeline_keys=set(timeline.regime_start_ns.astype("int64"));missing=set(map(int,np.unique(flip)))-timeline_keys
    if missing:raise RuntimeError(f"confirmed flips absent from canonical timeline: {len(missing)}")
    indexed=timeline.set_index("regime_start_ns");d["next_opposing_confirm_flip_ns"]=d.confirm_flip_ns.map(indexed.regime_end_ns)
    next_valid=d.next_opposing_confirm_flip_ns.notna().to_numpy();censored=d.confirm_flip_ns.map(indexed.end_censored).fillna(False).astype(bool).to_numpy()
    if not np.array_equal(~next_valid,censored):raise RuntimeError("next-flip null is not canonical trailing censoring")
    mapped_next=d.next_opposing_confirm_flip_ns.to_numpy();next_endpoint=np.where(next_valid,mapped_next,flip).astype(np.int64);next_end=np.searchsorted(ts,next_endpoint,side="left")
    intervals.append(("post_next_flip",post_start,np.where(next_valid,next_end,post_start),flip,next_endpoint,next_valid))
    checked=[]
    for name,l,r,start_boundary,end_boundary,valid_expected in intervals:
        structural=(start_boundary>=ts[0])&(r<=len(ts))&(end_boundary<=coverage_end)
        if name!="post_next_flip" and not structural.all():raise RuntimeError(f"{name}: truncated or out-of-range intervals")
        available=structural&(r>l)&valid_expected
        if name=="post_next_flip" and not np.array_equal(structural&valid_expected,valid_expected):raise RuntimeError("next-flip interval completeness mismatch")
        checked.append((name,l,r,start_boundary,end_boundary,available))
    return d,checked


def query_paths(d:pd.DataFrame,a:dict[str,np.ndarray],timeline:pd.DataFrame)->pd.DataFrame:
    ts=a["ts"];d,intervals=build_intervals(d,timeline,ts);left=np.concatenate([x[1] for x in intervals]);right=np.concatenate([x[2] for x in intervals])
    gap_prefix=np.concatenate(([0],np.cumsum(np.diff(ts)>NS)))
    high_tree=RangeTree(a["high"],"max");high,hi=high_tree.query(left,right);del high_tree;gc.collect()
    low_tree=RangeTree(a["low"],"min");low,li=low_tree.query(left,right);del low_tree;gc.collect()
    validate_direct_slice_parity(intervals,a,high,low,hi,li,len(d))
    offset=0;trade=d.trade_direction.to_numpy(float);px=d.checkpoint_price.to_numpy(float);atr=d.atr_at_checkpoint.to_numpy(float)
    for name,l,r,start_boundary,end_boundary,valid in intervals:
        sl=slice(offset,offset+len(d));hv,lv,hidx,lidx=high[sl],low[sl],hi[sl],li[sl];offset+=len(d)
        first_lag=np.full(len(d),np.nan);terminal_lag=np.full(len(d),np.nan);gap_count=np.full(len(d),np.nan)
        first_lag[valid]=(ts[l[valid]]-start_boundary[valid])/NS;terminal_lag[valid]=(end_boundary[valid]-(ts[r[valid]-1]+NS))/NS
        gap_count[valid]=gap_prefix[r[valid]-1]-gap_prefix[l[valid]]
        d[f"{name}_path_available"]=valid;d[f"{name}_first_bar_lag_s"]=first_lag;d[f"{name}_terminal_bar_lag_s"]=terminal_lag;d[f"{name}_interior_gap_count"]=gap_count
        baseline=px if name.startswith("to_flip") or name.startswith("fixed") else None
        if baseline is None:
            baseline=d.flip_close_price.to_numpy(float)
        fav=np.where(trade>0,hv-baseline,baseline-lv);adv=np.where(trade>0,baseline-lv,hv-baseline)
        if name=="to_flip":
            d["mfe_to_flip_atr"]=np.where(valid,np.maximum(fav,0)/atr,np.nan);d["mae_to_flip_atr"]=np.where(valid,np.maximum(adv,0)/atr,np.nan)
            fav_idx=np.where(trade>0,hidx,lidx);adv_idx=np.where(trade>0,lidx,hidx)
            d["mfe_timestamp"]=np.where(valid&(fav_idx>=0),ts[np.maximum(fav_idx,0)],np.nan);d["mae_timestamp"]=np.where(valid&(adv_idx>=0),ts[np.maximum(adv_idx,0)],np.nan)
        elif name.startswith("fixed"):
            h=name.split("_")[1];d[f"mfe_{h}s_atr"]=np.where(valid,np.maximum(fav,0)/atr,np.nan);d[f"mae_{h}s_atr"]=np.where(valid,np.maximum(adv,0)/atr,np.nan)
        elif name=="post_next_flip":
            d["post_flip_mfe_until_next_flip_atr"]=np.where(valid,np.maximum(fav,0)/atr,np.nan);d["post_flip_mae_until_next_flip_atr"]=np.where(valid,np.maximum(adv,0)/atr,np.nan)
        else:
            h=name.split("_")[1];d[f"post_flip_mfe_{h}s_atr"]=np.where(valid,np.maximum(fav,0)/atr,np.nan);d[f"post_flip_mae_{h}s_atr"]=np.where(valid,np.maximum(adv,0)/atr,np.nan)
    return d


def attach_flip_provenance(d:pd.DataFrame,a:dict[str,np.ndarray],timeline:pd.DataFrame)->pd.DataFrame:
    ts=a["ts"];d=d.copy();flip=d.confirm_flip_ns.to_numpy(np.int64);mstart=np.searchsorted(ts,flip-60*NS,"left");mend=np.searchsorted(ts,flip,"left")
    if np.any(mend<=mstart):raise RuntimeError("empty confirming-minute path")
    d["flip_open_price"]=a["open"][mstart];d["flip_close_price"]=a["close"][mend-1]
    atr_map=timeline.set_index("regime_start_ns").atr_at_confirmed_flip
    d["atr_at_confirmed_flip"]=d.confirm_flip_ns.map(atr_map);d["atr_confirm_source_observation_time"]=d.confirm_flip_ns
    d["atr_confirm_source_gap_seconds"]=0.0
    if d[["atr_at_confirmed_flip","atr_confirm_source_observation_time"]].isna().any().any():raise RuntimeError("missing confirmed-flip ATR provenance")
    d["checkpoint_to_flip_close_atr"]=d.trade_direction*(d.flip_close_price-d.checkpoint_price)/d.atr_at_checkpoint
    return d


def schema_json(df:pd.DataFrame)->dict:
    descriptions={
        "model_score":"Frozen artifact positive-class probability.","score_percentile":"Within-direction combined-2024-2025 empirical percentile (0-100).",
        "atr_at_confirmed_flip":"Wilder ATR(14) from the completed canonical 1m bar whose close timestamp is the confirmed flip.",
        "artifact_causal_status":"Frozen-artifact causal provenance; Bullish is provisional with known 1s look-ahead, Bearish is strict causal.",
        "mfe_to_flip_atr":"Maximum favorable excursion in hypothetical trade direction, checkpoint to confirmed flip, normalized by checkpoint ATR.",
        "mae_to_flip_atr":"Maximum adverse excursion against hypothetical trade direction, checkpoint to confirmed flip, normalized by checkpoint ATR.",
    }
    return {"primary_key":KEY,"rows":len(df),"columns":[{"name":c,"dtype":str(df[c].dtype),"nullable":bool(df[c].isna().any()),"description":descriptions.get(c,"")} for c in df.columns],
            "atr_denominator":"atr_at_checkpoint","nq_dollars_per_point":CFG["nq_dollars_per_point"],"event_source":"confirm_flip_ns only"}


def quality_report(df:pd.DataFrame,parity:dict,inputs:dict)->str:
    counts=df.groupby(["direction","year"]).size().rename("rows").reset_index();missing=pd.DataFrame({"column":df.columns,"missing":df.isna().sum().to_numpy(),"missing_pct":100*df.isna().mean().to_numpy()})
    return "# Canonical Checkpoint Population Quality Report\n\n## Status\n\nBuild validation passed. This is a policy-neutral descriptive artifact; no strategy or exit conclusion is made.\n\n## Row counts\n\n"+counts.to_markdown(index=False)+"\n\n## Prediction parity\n\n```json\n"+json.dumps(parity,indent=2)+"\n```\n\n## Missingness\n\n"+missing.to_markdown(index=False)+"\n\n## Provenance\n\n```json\n"+json.dumps(inputs,indent=2)+"\n```\n"


def main()->None:
    if YEARS!=(2024,2025):raise RuntimeError(f"sealed population must be exactly 2024-2025, got {YEARS}")
    if CFG["sealed_year"] in YEARS or any("2026" in str(p) for p in [*RAW.values(),BULL_WORK,BEAR_WORK,BEAR_ATTACHED]):raise RuntimeError("2026 access forbidden")
    RESULTS.mkdir(parents=True,exist_ok=True);WORK.mkdir(parents=True,exist_ok=True);validate_range_tree_contract()
    bm=joblib.load(BULL_ART/"model.joblib");lm=joblib.load(BEAR_ART/"model.joblib");bf=feature_order(BULL_ART);lf=feature_order(BEAR_ART)
    frozen_inputs=validate_frozen_inputs(bf,lf);global_memory_estimate=conservative_memory_bound_mb()
    if global_memory_estimate>CFG["max_estimated_peak_memory_mb"]:raise RuntimeError(f"conservative peak {global_memory_estimate:.0f} MB exceeds configured bound")
    scored=[]
    for year in YEARS:
        scored.append(load_and_score_year("bullish_fade",year,bm,bf));gc.collect();scored.append(load_and_score_year("bearish_fade",year,lm,lf));gc.collect()
    base=add_score_buckets(pd.concat(scored,ignore_index=True));parity=verify_parity(base,lm,lf);del scored,bm,lm;gc.collect()
    part_paths=[];memory_estimates={}
    for year in YEARS:
        y=base[base.year==year].copy();raw,a=load_raw(year);timeline=canonical_timeline(year,raw);del raw;gc.collect()
        memory_estimates[str(year)]=global_memory_estimate
        y=attach_flip_provenance(y,a,timeline);y=query_paths(y,a,timeline)
        part=WORK/f"canonical_checkpoint_population_{year}.parquet";tmp=part.with_suffix(".parquet.tmp");y.to_parquet(tmp,index=False,compression="zstd");tmp.replace(part);part_paths.append(part)
        del a,timeline,y;gc.collect()
    out=pd.concat((pd.read_parquet(p) for p in part_paths),ignore_index=True).sort_values(KEY).reset_index(drop=True)
    assert_keys(out,KEY,"final population")
    if len(out)!=len(base):raise RuntimeError(f"silent row loss {len(base)}->{len(out)}")
    forbidden=[c for c in out.columns if any(t in c.lower() for t in FORBIDDEN_OUTPUT_TOKENS)]
    if forbidden:raise RuntimeError(f"policy fields in output: {forbidden}")
    out_path=RESULTS/"canonical_checkpoint_population.parquet";tmp=out_path.with_suffix(".parquet.tmp");out.to_parquet(tmp,index=False,compression="zstd");tmp.replace(out_path)
    schema=schema_json(out);(RESULTS/"canonical_checkpoint_population_schema.json").write_text(json.dumps(schema,indent=2)+"\n",encoding="utf-8")
    inputs={"years":list(YEARS),"bullish_model_sha256":sha256(BULL_ART/"model.joblib"),"bearish_model_sha256":sha256(BEAR_ART/"model.joblib"),"raw_sha256":{str(y):sha256(RAW[y]) for y in YEARS},"frozen_inputs":frozen_inputs,"estimated_peak_memory_mb":memory_estimates,"configured_memory_bound_mb":CFG["max_estimated_peak_memory_mb"],"output_sha256":sha256(out_path)}
    (STUDY/"canonical_checkpoint_population_quality_report.md").write_text(quality_report(out,parity,inputs),encoding="utf-8")


if __name__=="__main__":main()
