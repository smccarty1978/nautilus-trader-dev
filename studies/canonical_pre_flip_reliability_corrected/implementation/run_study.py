from __future__ import annotations

import inspect
import json
import math
import gc
import os
import sys
from pathlib import Path

import joblib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml
from scipy.stats import mannwhitneyu, norm
from sklearn.calibration import calibration_curve
from sklearn.metrics import (average_precision_score, brier_score_loss,
                             precision_recall_curve, roc_auc_score, roc_curve)

ROOT = Path(__file__).resolve().parents[3]
STUDY = Path(__file__).resolve().parents[1]
RESULTS = STUDY / "results"
PLOTS = RESULTS / "plots"
CFG = yaml.safe_load((STUDY / "config.yaml").read_text())
KEY = ["regime_start_ns", "observation_time"]
EVENT_SOURCE_COLUMNS = {"confirm_flip_ns"}
FORBIDDEN_EVENT_TOKENS = ("exit_ts", "hit_opposing_flip", "trade_survival", "stop_loss", "profit_target")

BULL_ART = ROOT / "studies/freeze_reduced_flip_model_artifacts/artifacts/short_bearish_flip_top25_current_reference"
BEAR_ART = ROOT / "studies/freeze_long_strict_models_v2/artifacts/LONG_STRICT_top25_gbt_v2"
BULL_WORK = ROOT / "studies/short_rth_pure_flip_prediction_enriched/_work"
BULL_SURFACE_BUILDER = ROOT / "studies/short_rth_entry_surface_backfill/entry_surface.py"
BEAR_WORK = ROOT / "studies/long_rth_strict_symmetric_retrain/_work/monthly"
BEAR_ATTACHED = ROOT / "studies/long_rth_mirrored_surface_top100_training/_work"
RAW = {y: ROOT / f"data/raw/NQ_v0_1s_{y}.parquet" for y in CFG["years"]}
TARGET = "flip_le_300"


def assert_event_integrity() -> None:
    if EVENT_SOURCE_COLUMNS != {"confirm_flip_ns"}:
        raise RuntimeError("EVENT_CONTRACT_VIOLATION: event source is not pure confirm_flip_ns")
    src = inspect.getsource(build_events).lower()
    if any(token in src for token in FORBIDDEN_EVENT_TOKENS):
        raise RuntimeError("EVENT_CONTRACT_VIOLATION: policy-conditioned token in event builder")


def build_events(df: pd.DataFrame) -> pd.DataFrame:
    if set(df.columns) != set(KEY + ["confirm_flip_ns"]):
        raise RuntimeError("EVENT_CONTRACT_VIOLATION: event builder received non-contract columns")
    out = df.copy()
    out["seconds_to_flip"] = (out["confirm_flip_ns"] - out["observation_time"]) / 1e9
    if not (out["seconds_to_flip"] > 0).all():
        raise RuntimeError("confirmed flip must be strictly after observation")
    out["flip_le_300"] = out["seconds_to_flip"] <= 300.0
    out["flip_le_600"] = out["seconds_to_flip"] <= 600.0
    return out


def assert_keys(df: pd.DataFrame, name: str) -> None:
    if df[KEY].isna().any().any() or df.duplicated(KEY).any():
        raise RuntimeError(f"{name}: duplicate or null checkpoint key")


def assert_same_keys(a: pd.DataFrame, b: pd.DataFrame, an: str, bn: str) -> None:
    assert_keys(a, an); assert_keys(b, bn)
    ai, bi = pd.MultiIndex.from_frame(a[KEY]), pd.MultiIndex.from_frame(b[KEY])
    if len(ai) != len(bi) or not ai.equals(bi):
        raise RuntimeError(f"{an}/{bn}: checkpoint key mismatch")


def feature_order(path: Path) -> list[str]:
    csv = path / "feature_order.csv"
    return pd.read_csv(csv).feature_name.tolist() if csv.exists() else json.loads((path / "feature_list.json").read_text())


def rth_mask(ns: pd.Series) -> pd.Series:
    t = pd.to_datetime(ns, unit="ns", utc=True).dt.tz_convert("America/Chicago").dt.time
    return (t >= pd.Timestamp("08:30:00").time()) & (t < pd.Timestamp("15:15:00").time())


def load_direction(direction: str, model, features: list[str]) -> pd.DataFrame:
    frames = []
    for year in CFG["years"]:
        if direction == "bullish_fade":
            d = pd.read_parquet(BULL_WORK / f"prepared_{year}.parquet")
            direction_col = next((c for c in ("prevailing_direction", "regime_direction", "current_regime_direction") if c in d), None)
            if direction_col is not None:
                valid_direction = set(d[direction_col].dropna().astype(int).unique()) == {1}
            else:
                builder = BULL_SURFACE_BUILDER.read_text(encoding="utf-8")
                lineage_guard = "if direction != 1:" in builder and '"prevailing_direction": direction' in builder
                valid_direction = lineage_guard and set(d.entry_direction.dropna().astype(int).unique()) == {-1}
            if not valid_direction: raise RuntimeError(f"Bullish {year}: prevailing-direction contract failed")
            d = d.loc[rth_mask(d.observation_time)].reset_index(drop=True)
            d = d.rename(columns={"entry_px": "checkpoint_px"})
        else:
            monthly = sorted((BEAR_WORK / str(year)).glob("*.parquet"))
            if len(monthly) != 12:
                raise RuntimeError(f"Bearish {year}: incomplete monthly population")
            d = pd.concat((pd.read_parquet(p) for p in monthly), ignore_index=True)
            attached = pd.read_parquet(BEAR_ATTACHED / f"attached_long_{year}.parquet",
                columns=KEY + ["confirm_flip_ns", "fill_px", "atr_at_entry", "prevailing_direction"])
            attached = attached.loc[rth_mask(attached.observation_time)].reset_index(drop=True)
            assert_same_keys(d[KEY], attached[KEY], f"Bearish monthly {year}", f"Bearish attached {year}")
            d = d.merge(attached, on=KEY, how="left", validate="one_to_one").rename(columns={"fill_px": "checkpoint_px"})
            if set(d.prevailing_direction.dropna().astype(int).unique()) != {-1}:
                raise RuntimeError(f"Bearish {year}: prevailing-direction contract failed")
        assert_keys(d, f"{direction} {year}")
        missing_columns = sorted(set(features)-set(d.columns))
        if missing_columns: raise RuntimeError(f"{direction} {year}: missing feature columns {missing_columns}")
        required_nonnull = ["confirm_flip_ns", "checkpoint_px", "atr_at_entry"]
        if d[required_nonnull].isna().any().any():
            raise RuntimeError(f"{direction} {year}: missing required event/economic values")
        event_frame = build_events(d[KEY + ["confirm_flip_ns"]])
        d["seconds_to_flip"] = event_frame["seconds_to_flip"].to_numpy()
        d["flip_le_300"] = event_frame["flip_le_300"].to_numpy()
        d["flip_le_600"] = event_frame["flip_le_600"].to_numpy()
        d["score"] = model.predict_proba(d[features])[:, 1]
        d["year"] = year; d["direction"] = direction
        d = d[KEY + ["confirm_flip_ns","checkpoint_px","atr_at_entry","seconds_to_flip",
                     "flip_le_300","flip_le_600","score","year","direction"]].copy()
        frames.append(d)
    return pd.concat(frames, ignore_index=True).sort_values("observation_time").reset_index(drop=True)


def verify_parity(bull: pd.DataFrame, bear_model, bear_features: list[str]) -> dict:
    ref = pd.read_parquet(BULL_ART / "score_reference_2025.parquet")
    b25 = bull[bull.year == 2025]
    assert_same_keys(b25[KEY], ref[KEY], "Bullish scored 2025", "Bullish frozen reference")
    merged = b25[KEY + ["score"]].merge(ref[KEY + ["score"]], on=KEY, suffixes=("_new", "_ref"), validate="one_to_one")
    bd = float(np.abs(merged.score_new - merged.score_ref).max())
    fixture = pd.read_parquet(BEAR_ART / "validation_fixture.parquet")
    expected = np.load(BEAR_ART / "validation_fixture_scores.npy")
    ld = float(np.abs(bear_model.predict_proba(fixture[bear_features])[:, 1] - expected).max())
    if bd != 0 or ld != 0:
        raise RuntimeError(f"artifact parity failure: bullish={bd}, bearish={ld}")
    return {"bullish_max_abs_diff": bd, "bearish_max_abs_diff": ld}


def manual_trace(d: pd.DataFrame, direction: str) -> None:
    rows = []
    for label in (1, 0):
        for r in d[d[TARGET].astype(int) == label].sort_values(KEY).head(50).itertuples(index=False):
            seconds = (r.confirm_flip_ns-r.observation_time)/1e9
            calc = int(0 < seconds <= 300)
            rows.append({"expected_class": label, "regime_start_ns": int(r.regime_start_ns),
                         "observation_time": int(r.observation_time), "confirm_flip_ns": int(r.confirm_flip_ns),
                         "seconds_to_flip": seconds, "stored_event": int(r.flip_le_300),
                         "arithmetic_event": calc, "verified": calc == int(r.flip_le_300)})
    out = pd.DataFrame(rows)
    if len(out) != 100 or not out.verified.all(): raise RuntimeError(f"{direction}: manual trace failed")
    out.to_csv(STUDY / f"manual_trace_{'bullish' if direction == 'bullish_fade' else 'bearish'}.csv", index=False)


def metrics(d: pd.DataFrame) -> list[dict]:
    rows = []
    for year_label, g in [("combined_2024_2025", d)] + [(str(y), d[d.year == y]) for y in CFG["years"]]:
        y, p = g[TARGET].astype(int), g.score
        rows.append({"direction": g.direction.iloc[0], "period": year_label, "rows": len(g),
                     "base_rate": float(y.mean()), "roc_auc": float(roc_auc_score(y,p)),
                     "average_precision": float(average_precision_score(y,p)),
                     "brier": float(brier_score_loss(y,p))})
    return rows


def first_signals(d: pd.DataFrame) -> dict[float, pd.DataFrame]:
    out = {}
    keep = KEY + ["confirm_flip_ns","checkpoint_px","atr_at_entry","seconds_to_flip","flip_le_300","flip_le_600","score","year","direction"]
    for pct in CFG["threshold_percentiles"]:
        q = float(np.percentile(d.score, 100-pct))
        s = d[d.score >= q].sort_values("observation_time").groupby("regime_start_ns", as_index=False).first()
        s = s[keep]
        s["top_pct"] = pct; s["threshold"] = q
        out[float(pct)] = s
    return out


def threshold_rows(signal_sets: dict[float,pd.DataFrame], n_days: int, direction: str) -> list[dict]:
    rows=[]
    for pct,s in signal_sets.items():
        t=s.seconds_to_flip
        rows.append({"direction":direction,"top_pct":pct,"threshold":float(s.threshold.iloc[0]),"signals":len(s),
            "signals_per_day":len(s)/n_days,"flip_le_300":float(s.flip_le_300.mean()),"flip_le_600":float(s.flip_le_600.mean()),
            "median_seconds":float(t.median()),"mean_seconds":float(t.mean()),"p75_seconds":float(t.quantile(.75)),
            "p90_seconds":float(t.quantile(.90)),"p95_seconds":float(t.quantile(.95))})
    return rows


def reliability_rows(d: pd.DataFrame, signal_sets: dict[float,pd.DataFrame], direction: str) -> list[dict]:
    rows=[]
    dec=pd.qcut(d.score,10,labels=False,duplicates="drop")
    for b,g in d.groupby(dec):
        rows.append({"direction":direction,"curve_type":"decile_checkpoint","bucket":int(b)+1,"top_pct":np.nan,
                     "count":len(g),"mean_score":float(g.score.mean()),"flip_le_300":float(g.flip_le_300.mean()),
                     "flip_le_600":float(g.flip_le_600.mean()),"lift_300":float(g.flip_le_300.mean()/d.flip_le_300.mean())})
    for pct,s in signal_sets.items():
        rows.append({"direction":direction,"curve_type":"percentile_first_signal","bucket":np.nan,"top_pct":pct,
                     "count":len(s),"mean_score":float(s.score.mean()),"flip_le_300":float(s.flip_le_300.mean()),
                     "flip_le_600":float(s.flip_le_600.mean()),"lift_300":float(s.flip_le_300.mean()/d.flip_le_300.mean())})
    return rows


def curve_artifacts(d: pd.DataFrame, direction: str) -> None:
    y,p=d[TARGET].astype(int).to_numpy(),d.score.to_numpy()
    fpr,tpr,_=roc_curve(y,p); prec,rec,_=precision_recall_curve(y,p)
    obs,pred=calibration_curve(y,p,n_bins=CFG["calibration_bins"],strategy="quantile")
    pd.DataFrame({"fpr":fpr,"tpr":tpr}).to_csv(RESULTS/f"roc_{direction}.csv",index=False)
    pd.DataFrame({"recall":rec,"precision":prec}).to_csv(RESULTS/f"pr_{direction}.csv",index=False)
    pd.DataFrame({"mean_probability":pred,"observed_rate":obs}).to_csv(RESULTS/f"calibration_{direction}.csv",index=False)
    fig,ax=plt.subplots(1,3,figsize=(14,4)); ax[0].plot(fpr,tpr);ax[0].plot([0,1],[0,1],'--',c='gray');ax[0].set(title='ROC',xlabel='FPR',ylabel='TPR')
    ax[1].plot(rec,prec);ax[1].set(title='Precision–recall',xlabel='Recall',ylabel='Precision')
    ax[2].plot([0,1],[0,1],'--',c='gray');ax[2].plot(pred,obs,'o-');ax[2].set(title='Calibration',xlabel='Mean score',ylabel='Observed rate')
    fig.suptitle(direction);fig.tight_layout();fig.savefig(PLOTS/f"forecast_curves_{direction}.png",dpi=150);plt.close(fig)


def timing_rows(signal_sets: dict[float,pd.DataFrame], direction: str) -> list[dict]:
    rows=[]; width=CFG["timing_bin_seconds"]; maxs=CFG["timing_max_seconds"]
    edges=np.arange(0,maxs+width,width)
    for pct,s in signal_sets.items():
        t=s.seconds_to_flip.to_numpy(); n=len(t); at_risk=n
        for lo,hi in zip(edges[:-1],edges[1:]):
            events=int(((t>lo)&(t<=hi)).sum()); survival=float((t>hi).mean());cdf=1-survival
            hazard=events/at_risk if at_risk else np.nan
            rows.append({"direction":direction,"top_pct":pct,"bin_start_s":lo,"bin_end_s":hi,"count":events,
                         "cdf":cdf,"survival":survival,"hazard":hazard,"at_risk":at_risk,
                         "median":float(np.median(t)),"q25":float(np.quantile(t,.25)),"q75":float(np.quantile(t,.75)),
                         "p90":float(np.quantile(t,.90)),"p95":float(np.quantile(t,.95))})
            at_risk-=events
    return rows


def timing_plot(signal_sets:dict[float,pd.DataFrame],direction:str)->None:
    s=signal_sets[2.5];t=np.sort(s.seconds_to_flip.to_numpy());edges=np.arange(0,CFG["timing_max_seconds"]+CFG["timing_bin_seconds"],CFG["timing_bin_seconds"])
    counts,_=np.histogram(t,bins=edges);cdf=np.searchsorted(t,edges[1:],side="right")/len(t);survival=1-cdf
    at_risk=len(t)-np.concatenate(([0],np.cumsum(counts[:-1])));hazard=np.divide(counts,at_risk,out=np.zeros_like(counts,dtype=float),where=at_risk>0)
    fig,ax=plt.subplots(2,2,figsize=(11,8));ax[0,0].hist(t,bins=edges);ax[0,0].set(title="Timing histogram",xlabel="Seconds to confirmed flip")
    ax[0,1].step(edges[1:],cdf,where="post");ax[0,1].set(title="CDF",xlabel="Seconds",ylim=(0,1))
    ax[1,0].step(edges[1:],survival,where="post");ax[1,0].set(title="Survival",xlabel="Seconds",ylim=(0,1))
    ax[1,1].step(edges[1:],hazard,where="post");ax[1,1].set(title="Discrete hazard per 30s bin",xlabel="Seconds",ylim=(0,max(.01,float(hazard.max())*1.1)))
    fig.suptitle(f"{direction} — Top 2.5% first signals");fig.tight_layout();fig.savefig(PLOTS/f"timing_{direction}_top2_5.png",dpi=150);plt.close(fig)


def raw_arrays(year: int) -> dict[str,np.ndarray]:
    b=pd.read_parquet(RAW[year],columns=["open","high","low","close"])
    ts=b.index.astype("int64").to_numpy() if b.index.name=="ts_event" else pd.to_datetime(b.pop("ts_event"),utc=True).astype("int64").to_numpy()
    if np.any(np.diff(ts)<=0): raise RuntimeError(f"raw {year}: timestamps not strictly increasing")
    return {"ts":ts,**{c:b[c].to_numpy() for c in ("open","high","low","close")}}


def economic_events(signal_sets:dict[float,pd.DataFrame],direction:str,bars:dict[int,dict]) -> pd.DataFrame:
    rows=[]
    for pct,s in signal_sets.items():
        for r in s.itertuples(index=False):
            a=bars[int(r.year)];ts=a["ts"];rs=np.searchsorted(ts,r.regime_start_ns,"left");prefix_end=np.searchsorted(ts,r.observation_time,"left");st=np.searchsorted(ts,r.observation_time,"right");en=np.searchsorted(ts,r.confirm_flip_ns,"left")
            if not (rs<st<en<=len(ts)): raise RuntimeError(f"empty/invalid economic path for {direction} {r.regime_start_ns} {r.observation_time}")
            if prefix_end<=rs: raise RuntimeError(f"empty pre-checkpoint path for {direction} {r.regime_start_ns} {r.observation_time}")
            rh=a["high"][rs:en];rl=a["low"][rs:en];pre_h=a["high"][rs:prefix_end];pre_l=a["low"][rs:prefix_end];h=a["high"][st:en];l=a["low"][st:en];terminal=a["close"][en-1];origin=a["open"][rs]
            origin_lag_s=(ts[rs]-r.regime_start_ns)/1e9;start_lag_s=(ts[st]-r.observation_time)/1e9;end_lag_s=(r.confirm_flip_ns-(ts[en-1]+1_000_000_000))/1e9
            gaps=int(np.sum(np.diff(ts[st:en])>1_000_000_000))
            if direction=="bullish_fade":
                total=max(0,float(rh.max()-origin));captured=max(0,float(pre_h.max()-origin));remaining=max(0,float(h.max()-r.checkpoint_px));adverse=max(0,float(h.max()-r.checkpoint_px));pnl=float(r.checkpoint_px-terminal)
            else:
                total=max(0,float(origin-rl.min()));captured=max(0,float(origin-pre_l.min()));remaining=max(0,float(r.checkpoint_px-l.min()));adverse=max(0,float(r.checkpoint_px-l.min()));pnl=float(terminal-r.checkpoint_px)
            rows.append({"direction":direction,"top_pct":pct,"regime_start_ns":r.regime_start_ns,"observation_time":r.observation_time,
                         "remaining_prevailing_mfe_points":remaining,"countertrend_mae_points":adverse,"mark_pnl_points":pnl,
                         "captured_mfe_pct":100*captured/total if total>0 else np.nan,"remaining_atr":remaining/r.atr_at_entry,
                         "countertrend_mae_atr":adverse/r.atr_at_entry,"mark_pnl_atr":pnl/r.atr_at_entry,
                         "origin_observed_bar_lag_s":origin_lag_s,"first_observed_bar_lag_s":start_lag_s,
                         "terminal_mark_lag_s":end_lag_s,"interior_gap_count":gaps})
    return pd.DataFrame(rows)


def bootstrap_median_diff(a:np.ndarray,b:np.ndarray,rng)->tuple[float,float,float]:
    diff=float(np.median(a)-np.median(b)); reps=[]
    for _ in range(CFG["bootstrap_repetitions"]):
        reps.append(np.median(rng.choice(a,len(a),replace=True))-np.median(rng.choice(b,len(b),replace=True)))
    return diff,float(np.quantile(reps,.025)),float(np.quantile(reps,.975))


def comparison_rows(bs:dict,ls:dict,be:pd.DataFrame,le:pd.DataFrame)->list[dict]:
    rng=np.random.default_rng(CFG["random_seed"]);rows=[]
    for pct in CFG["threshold_percentiles"]:
        b,l=bs[float(pct)],ls[float(pct)];p1,p2=b.flip_le_300.mean(),l.flip_le_300.mean();pooled=(b.flip_le_300.sum()+l.flip_le_300.sum())/(len(b)+len(l));se=math.sqrt(pooled*(1-pooled)*(1/len(b)+1/len(l)));z=(p1-p2)/se if se else np.nan;pz=2*norm.sf(abs(z)) if np.isfinite(z) else np.nan
        td,tlo,thi=bootstrap_median_diff(b.seconds_to_flip.to_numpy(),l.seconds_to_flip.to_numpy(),rng)
        eb,el=be[be.top_pct==pct],le[le.top_pct==pct];ed,elo,ehi=bootstrap_median_diff(eb.mark_pnl_atr.to_numpy(),el.mark_pnl_atr.to_numpy(),rng)
        rd,rlo,rhi=bootstrap_median_diff(eb.remaining_atr.to_numpy(),el.remaining_atr.to_numpy(),rng)
        ad,alo,ahi=bootstrap_median_diff(eb.countertrend_mae_atr.to_numpy(),el.countertrend_mae_atr.to_numpy(),rng)
        bc=eb.captured_mfe_pct.dropna().to_numpy();lc=el.captured_mfe_pct.dropna().to_numpy()
        if len(bc)==0 or len(lc)==0: raise RuntimeError(f"Top {pct}: captured-MFE comparison has no defined ratios")
        cd,clo,chi=bootstrap_median_diff(bc,lc,rng)
        rows.append({"top_pct":pct,"bullish_signals":len(b),"bearish_signals":len(l),"bullish_flip_le_300":p1,"bearish_flip_le_300":p2,
                     "flip_rate_diff_bull_minus_bear":p1-p2,"flip_rate_z_pvalue":pz,"median_timing_diff_s":td,"timing_diff_ci_low":tlo,"timing_diff_ci_high":thi,
                     "timing_mannwhitney_pvalue":float(mannwhitneyu(b.seconds_to_flip,l.seconds_to_flip).pvalue),
                     "bullish_remaining_atr":float(eb.remaining_atr.median()),"bearish_remaining_atr":float(el.remaining_atr.median()),
                     "bullish_mae_atr":float(eb.countertrend_mae_atr.median()),"bearish_mae_atr":float(el.countertrend_mae_atr.median()),
                     "remaining_atr_diff_bull_minus_bear":rd,"remaining_atr_diff_ci_low":rlo,"remaining_atr_diff_ci_high":rhi,
                     "remaining_atr_mannwhitney_pvalue":float(mannwhitneyu(eb.remaining_atr,el.remaining_atr).pvalue),
                     "mae_atr_diff_bull_minus_bear":ad,"mae_atr_diff_ci_low":alo,"mae_atr_diff_ci_high":ahi,
                     "mae_atr_mannwhitney_pvalue":float(mannwhitneyu(eb.countertrend_mae_atr,el.countertrend_mae_atr).pvalue),
                     "captured_mfe_pct_diff_bull_minus_bear":cd,"captured_mfe_pct_diff_ci_low":clo,"captured_mfe_pct_diff_ci_high":chi,
                     "captured_mfe_pct_mannwhitney_pvalue":float(mannwhitneyu(bc,lc).pvalue),
                     "bullish_mark_pnl_atr":float(eb.mark_pnl_atr.median()),"bearish_mark_pnl_atr":float(el.mark_pnl_atr.median()),
                     "mark_pnl_diff_bull_minus_bear":ed,"mark_pnl_diff_ci_low":elo,"mark_pnl_diff_ci_high":ehi,
                     "mark_pnl_mannwhitney_pvalue":float(mannwhitneyu(eb.mark_pnl_atr,el.mark_pnl_atr).pvalue)})
    return rows


def write_report(metric_df,threshold,comparison,econ_summary,parity):
    bm=metric_df.query("direction=='bullish_fade' and period=='2025'").iloc[0];lm=metric_df.query("direction=='bearish_fade' and period=='2025'").iloc[0]
    b25=threshold.query("direction=='bullish_fade' and top_pct==2.5").iloc[0];l25=threshold.query("direction=='bearish_fade' and top_pct==2.5").iloc[0];c25=comparison.query("top_pct==2.5").iloc[0]
    earlier="Bullish Fade" if b25.median_seconds<l25.median_seconds else "Bearish Fade"
    calibrated="Bullish Fade" if bm.brier<lm.brier else "Bearish Fade"
    forecast_asym=abs(c25.flip_rate_diff_bull_minus_bear)>0.05 and c25.flip_rate_z_pvalue<.05
    canonical="Bullish Fade Top25" if bm.roc_auc>lm.roc_auc else "Bearish Fade Top25"
    report=f"""# Canonical Corrected Pre-Flip Reliability Report

## Verdict

Both directions are evaluated exclusively on pure confirmed regime flips. Forecast quality and immediate-entry survival are separate; this study makes no execution-survival claim. The Bullish artifact has a disclosed inherited one-second feature look-ahead while Bearish is strict-causal, so cross-direction differences are artifact comparisons and cannot establish structural market asymmetry.

At Top 2.5%, Bullish Fade has {b25.flip_le_300:.1%} flip≤300 reliability (median {b25.median_seconds:.0f}s) and Bearish Fade has {l25.flip_le_300:.1%} (median {l25.median_seconds:.0f}s). The flip-rate difference is {c25.flip_rate_diff_bull_minus_bear:+.1%} (two-proportion p={c25.flip_rate_z_pvalue:.3g}).

2025 development metrics: Bullish AUC/AP/Brier {bm.roc_auc:.4f}/{bm.average_precision:.4f}/{bm.brier:.4f}; Bearish {lm.roc_auc:.4f}/{lm.average_precision:.4f}/{lm.brier:.4f}. 2024 is in-sample and combined thresholds are retained only for continuity with the superseded reliability study.

## Executive answers

1. **Bullish reliability:** Top 1/2.5/5/10/25% results are in `threshold_summary.csv`; Top 2.5% is {b25.flip_le_300:.1%} within 300s and {b25.flip_le_600:.1%} within 600s.
2. **Bearish reliability:** Top 2.5% is {l25.flip_le_300:.1%} within 300s and {l25.flip_le_600:.1%} within 600s.
3. **Earlier warnings:** {earlier} at Top 2.5% by median time to confirmed flip.
4. **Stronger calibration:** {calibrated} on 2025 Brier score.
5. **Larger remaining MFE:** {'Bullish Fade' if c25.bullish_remaining_atr>c25.bearish_remaining_atr else 'Bearish Fade'} at Top 2.5%.
6. **Greater adverse excursion:** {'Bullish Fade' if c25.bullish_mae_atr>c25.bearish_mae_atr else 'Bearish Fade'} at Top 2.5%.
7. **Asymmetry source:** {'The artifacts differ materially in forecasting at Top 2.5%, but the Bullish timing defect prevents a structural market interpretation.' if forecast_asym else 'No material Top-2.5% artifact forecasting asymmetry is established; path economics remain separate.'}
8. **Exit-signal sufficiency:** Both show useful enrichment, but neither is an executable exit policy; timing reliability must be consumed as a probabilistic warning, not a guaranteed exit trigger.
9. **Canonical benchmark:** Both Top25 artifacts form the requested event-corrected directional pair; {canonical} is the stronger 2025 discrimination reference. Bullish remains provisional and non-causal until rebuilt.
10. **Pure events only:** Yes. Events use only `confirm_flip_ns` joined by the frozen checkpoint key; policy-conditioned substitutions are prohibited and guarded.

## Forecast versus execution

Forecast question: did the opposing confirmed regime flip occur in the horizon? Execution question: would an immediate countertrend order survive the intervening path? Only the first is a reliability label. `economic_summary.csv` contains non-executable path marks for context.

## Reproduction and integrity

Bullish frozen-reference max prediction difference: {parity['bullish_max_abs_diff']:.1e}; Bearish fixture difference: {parity['bearish_max_abs_diff']:.1e}. No 2026 input was opened.
"""
    report_tmp=STUDY/"canonical_reliability_report.md.tmp"
    report_tmp.write_text(report,encoding="utf-8")
    report_tmp.replace(STUDY/"canonical_reliability_report.md")


def main():
    if any("2026" in str(p) for p in [BULL_WORK,BEAR_WORK,BEAR_ATTACHED,*RAW.values()]):raise RuntimeError("sealed 2026 path in active inputs")
    RESULTS.mkdir(parents=True,exist_ok=True);PLOTS.mkdir(parents=True,exist_ok=True);assert_event_integrity()
    bm=joblib.load(BULL_ART/"model.joblib");lm=joblib.load(BEAR_ART/"model.joblib");bf=feature_order(BULL_ART);lf=feature_order(BEAR_ART)
    bull=load_direction("bullish_fade",bm,bf);bear=load_direction("bearish_fade",lm,lf);parity=verify_parity(bull,lm,lf)
    manual_trace(bull,"bullish_fade");manual_trace(bear,"bearish_fade")
    metric_df=pd.DataFrame(metrics(bull)+metrics(bear));metric_df.to_csv(RESULTS/"model_metrics.csv",index=False)
    bs,ls=first_signals(bull),first_signals(bear)
    bull_days=len(set(pd.to_datetime(bull.observation_time,unit="ns",utc=True).dt.tz_convert("America/Chicago").dt.date));bear_days=len(set(pd.to_datetime(bear.observation_time,unit="ns",utc=True).dt.tz_convert("America/Chicago").dt.date))
    threshold=pd.DataFrame(threshold_rows(bs,bull_days,"bullish_fade")+threshold_rows(ls,bear_days,"bearish_fade"));threshold.to_csv(STUDY/"threshold_summary.csv",index=False)
    reliability=pd.DataFrame(reliability_rows(bull,bs,"bullish_fade")+reliability_rows(bear,ls,"bearish_fade"));reliability.to_csv(STUDY/"reliability_curves.csv",index=False)
    curve_artifacts(bull,"bullish_fade");curve_artifacts(bear,"bearish_fade")
    timing=pd.DataFrame(timing_rows(bs,"bullish_fade")+timing_rows(ls,"bearish_fade"));timing.to_csv(STUDY/"timing_distribution.csv",index=False)
    timing_plot(bs,"bullish_fade");timing_plot(ls,"bearish_fade")
    del bull,bear;gc.collect()
    be_parts=[];le_parts=[]
    for year in CFG["years"]:
        bars={year:raw_arrays(year)}
        bs_year={pct:s[s.year==year].copy() for pct,s in bs.items()}
        ls_year={pct:s[s.year==year].copy() for pct,s in ls.items()}
        be_parts.append(economic_events(bs_year,"bullish_fade",bars));le_parts.append(economic_events(ls_year,"bearish_fade",bars))
        del bars;gc.collect()
    be=pd.concat(be_parts,ignore_index=True);le=pd.concat(le_parts,ignore_index=True);events=pd.concat([be,le],ignore_index=True);events.to_parquet(RESULTS/"economic_events.parquet",index=False)
    economic=events.groupby(["direction","top_pct"]).agg(signals=("mark_pnl_atr","size"),remaining_mfe_points_median=("remaining_prevailing_mfe_points","median"),remaining_atr_median=("remaining_atr","median"),countertrend_mae_atr_median=("countertrend_mae_atr","median"),mark_pnl_atr_median=("mark_pnl_atr","median"),captured_mfe_pct_median=("captured_mfe_pct","median")).reset_index();economic.to_csv(STUDY/"economic_summary.csv",index=False)
    comparison=pd.DataFrame(comparison_rows(bs,ls,be,le));comparison.to_csv(STUDY/"bullish_vs_bearish_top25.csv",index=False)
    write_report(metric_df,threshold,comparison,economic,parity)
    (RESULTS/"parity.json").write_text(json.dumps(parity,indent=2)+"\n")
    required=[STUDY/x for x in ["canonical_reliability_report.md","threshold_summary.csv","timing_distribution.csv","reliability_curves.csv","economic_summary.csv","bullish_vs_bearish_top25.csv","manual_trace_bullish.csv","manual_trace_bearish.csv"]]+[STUDY/"audit/audit.md"]
    missing=[str(x) for x in required if not x.exists()]
    if missing:raise RuntimeError(f"missing deliverables: {missing}")


if __name__=="__main__":
    main()
    sys.stdout.flush();sys.stderr.flush()
    os._exit(0)  # Windows native parquet/OpenMP pools can linger after all checked outputs close.
