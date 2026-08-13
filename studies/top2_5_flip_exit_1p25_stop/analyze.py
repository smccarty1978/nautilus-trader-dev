from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[2];STUDY=Path(__file__).resolve().parent
SOURCE=ROOT/"studies/canonical_checkpoint_population/results/canonical_checkpoint_population.parquet"
EXPECTED="d6e5b71e6244cd7ed19161862211e1c3f8bc668c1c7db7cd7fe81b5d25de8121"
KEY=["direction","regime_start_ns","observation_time"]
STOP=1.25;DOLLARS_PER_POINT=20.0

def sha256(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):h.update(b)
    return h.hexdigest()

def summarize(g:pd.DataFrame)->dict:
    wins=g.pnl_nq_dollars>0;losses=g.pnl_nq_dollars<0
    gross_win=float(g.loc[wins,"pnl_nq_dollars"].sum());gross_loss=float(-g.loc[losses,"pnl_nq_dollars"].sum())
    statuses=set(g.artifact_causal_status);causal_status=(next(iter(statuses)) if len(statuses)==1 else "MIXED_INCLUDES_PROVISIONAL")
    return {"causal_status":causal_status,"entries":len(g),"stopouts":int(g.stop_triggered.sum()),"stopout_rate":float(g.stop_triggered.mean()),
            "wins":int(wins.sum()),"losses":int(losses.sum()),"breakeven":int((g.pnl_nq_dollars==0).sum()),"win_rate":float(wins.mean()),
            "mean_pnl_atr":float(g.pnl_atr.mean()),"median_pnl_atr":float(g.pnl_atr.median()),"total_pnl_points":float(g.pnl_points.sum()),
            "mean_pnl_nq_dollars":float(g.pnl_nq_dollars.mean()),"median_pnl_nq_dollars":float(g.pnl_nq_dollars.median()),
            "total_pnl_nq_dollars":float(g.pnl_nq_dollars.sum()),"profit_factor":gross_win/gross_loss if gross_loss else np.inf}

def main()->None:
    if sha256(SOURCE)!=EXPECTED:raise RuntimeError("canonical input hash mismatch")
    cols=KEY+["year","is_first_top_2_5","to_flip_path_available","atr_at_checkpoint","mae_to_flip_atr","checkpoint_to_flip_close_atr","checkpoint_price","flip_close_price","confirm_flip_ns","artifact_causal_status"]
    source=pd.read_parquet(SOURCE,columns=cols)
    expected_status={"bullish_fade":"PROVISIONAL_KNOWN_1S_LOOKAHEAD","bearish_fade":"STRICT_CAUSAL"}
    actual=source.groupby("direction").artifact_causal_status.unique().to_dict()
    if any(list(actual.get(k,[]))!=[v] for k,v in expected_status.items()):raise RuntimeError(f"causal provenance mismatch: {actual}")
    d=source[source.is_first_top_2_5&source.to_flip_path_available].copy()
    if d.duplicated(KEY).any() or d[KEY].isna().any().any():raise RuntimeError("key defect")
    if int(source.is_first_top_2_5.sum())!=len(d):raise RuntimeError("selected Top-2.5 population contains unavailable flip path")
    if set(d.year)!={2024,2025} or d[["atr_at_checkpoint","mae_to_flip_atr","checkpoint_to_flip_close_atr"]].isna().any().any():raise RuntimeError("population/value defect")
    d["stop_atr"]=STOP;d["survives_stop"]=d.mae_to_flip_atr<STOP;d["stop_triggered"]=~d.survives_stop
    d["pnl_atr"]=np.where(d.survives_stop,d.checkpoint_to_flip_close_atr,-STOP)
    d["pnl_points"]=d.pnl_atr*d.atr_at_checkpoint;d["pnl_nq_dollars"]=d.pnl_points*DOLLARS_PER_POINT
    rows=[]
    for direction,g in d.groupby("direction",sort=True):rows.append({"scope":direction,"year":"all",**summarize(g)})
    rows.append({"scope":"combined","year":"all",**summarize(d)})
    for (direction,year),g in d.groupby(["direction","year"],sort=True):rows.append({"scope":direction,"year":year,**summarize(g)})
    out=STUDY/"results";out.mkdir(parents=True,exist_ok=True);d.to_parquet(out/"trades.parquet",index=False,compression="zstd")
    summary=pd.DataFrame(rows);summary.to_csv(out/"summary.csv",index=False)
    main=summary[summary.year.astype(str)=="all"]
    report="# Top-2.5% First-Signal: 1.25 ATR Stop / Confirmed-Flip Exit\n\n"+main.to_markdown(index=False)+"\n\n"
    report+=("This is an independent per-signal, policy-conditioned path estimate using checkpoint price and confirmed-flip close. "
             "It is not an executable portfolio backtest and excludes commissions, slippage, latency, and overlap constraints. "
             "Bullish selection remains provisional with its disclosed inherited one-second feature look-ahead; therefore the combined scope is also provisional. "
             "Top-2.5 thresholds are retrospective combined-2024-2025 strata, not walk-forward thresholds, so 2024 detail uses the later 2025 score distribution.\n")
    (STUDY/"report.md").write_text(report,encoding="utf-8")

if __name__=="__main__":main()
