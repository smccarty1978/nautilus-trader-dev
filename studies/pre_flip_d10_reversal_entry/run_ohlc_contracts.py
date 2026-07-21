"""Full D10 policy replay under the user-authorized 1s OHLC contracts.

PRIMARY: EXPLICIT_NEXT_OPEN_OHLC_RESEARCH_CONTRACT
SENSITIVITY: CLOSE_DETECTED_NEXT_NT_FILL_SENSITIVITY

This is explicitly not NT-native executable validation. Signal/model events are
frozen causal lookup rows; final trade matching is a chronological 1s OHLC replay.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from common import AUDIT, FLIP_ATLAS, RESULTS, ROOT, WORK

PRIMARY = "EXPLICIT_NEXT_OPEN_OHLC_RESEARCH_CONTRACT"
SENSITIVITY = "CLOSE_DETECTED_NEXT_NT_FILL_SENSITIVITY"
STOPS = (0.50, 1.00, 1.50)
MULTIPLIER = 20.0
ROUND_TRIP_COST = 10.0  # $5 commission + one NQ tick, frozen project convention
PERIODS = {
    2025: (pd.Timestamp("2025-03-01", tz="UTC").value,
           pd.Timestamp("2025-12-31 23:59:59", tz="UTC").value),
    2026: (pd.Timestamp("2026-01-01", tz="UTC").value,
           pd.Timestamp("2026-04-29 23:59:59", tz="UTC").value),
}


def raw_path(year: int) -> Path:
    p = ROOT / "data" / "raw" / f"NQ_v0_1s_{year}.parquet"
    if year == 2026:
        p = ROOT / "data" / "raw" / "NQ_v0_1s_2026_ytd.parquet"
    return p


def load_bars(year: int) -> dict[str, np.ndarray]:
    d = pd.read_parquet(raw_path(year), columns=["open", "high", "low", "close"])
    d = d.sort_index()
    ts = d.index.view("int64")
    start, end = PERIODS[year]
    keep = (ts >= start - 7 * 86_400_000_000_000) & (ts <= end)
    d = d.iloc[np.flatnonzero(keep)]
    return {"ts": d.index.view("int64"), **{c: d[c].to_numpy(float) for c in ("open","high","low","close")}}


def load_flips(year: int) -> pd.DataFrame:
    d = pd.read_parquet(FLIP_ATLAS, columns=[
        "observation_time", "opposing_flip_time", "population", "regime", "atr",
    ])
    d = d[d.population.eq("F1")].copy()
    dup = d[d.duplicated("observation_time", keep=False)]
    if len(dup):
        conflicts = dup.groupby("observation_time")[["opposing_flip_time","atr"]].nunique(dropna=False).max(axis=1)
        if (conflicts > 1).any():
            raise RuntimeError("Conflicting duplicate F1 flip rows")
    d = d.drop_duplicates("observation_time").sort_values("observation_time").reset_index(drop=True)
    start, end = PERIODS[year]
    # Flip candidates are evaluation-window only. Raw bars retain warmup, but a
    # prior catalog-year regime is not carried across the documented year gap.
    d = d[(d.observation_time >= start)
          & (d.observation_time <= end)].sort_values("observation_time").reset_index(drop=True)
    cov=pd.read_parquet(RESULTS/"regime_d10_coverage.parquet",columns=["regime_start_time","direction"])
    known=d.observation_time.map(cov.drop_duplicates("regime_start_time").set_index("regime_start_time").direction)
    anchors=np.flatnonzero(known.notna().to_numpy())
    if not len(anchors): raise RuntimeError("No scored-regime direction anchor for F1 chain")
    a=int(anchors[0]);ad=int(known.iloc[a])
    reconstructed=np.array([ad*((-1)**(i-a)) for i in range(len(d))],dtype="int8")
    if not (reconstructed[anchors]==known.iloc[anchors].astype(int).to_numpy()).all():
        raise RuntimeError("F1 alternating direction conflicts with scored-regime anchors")
    next_obs=d.observation_time.shift(-1)
    if len(d)>1 and not (d.opposing_flip_time.iloc[:-1].notna().to_numpy()
                         & d.opposing_flip_time.iloc[:-1].eq(next_obs.iloc[:-1]).to_numpy()).all():
        raise RuntimeError("F1 opposing-flip chain is discontinuous")
    d["_direction"]=reconstructed
    d["direction"] = d._direction
    d["regime_start_time"] = d.observation_time.astype("int64")
    d["regime_id"] = d.direction.astype(str) + ":" + d.regime_start_time.astype(str)
    valid_end = d.opposing_flip_time.notna()
    if not (d.loc[valid_end,"opposing_flip_time"] > d.loc[valid_end,"regime_start_time"]).all():
        raise RuntimeError("Non-forward opposing flip")
    return d


def load_d10(year: int) -> pd.DataFrame:
    d = pd.read_parquet(RESULTS / "d10_entry_events.parquet")
    d = d[d.is_first_crossing].copy()
    # observation_time is a 1s bar open timestamp; score is causal only after
    # that bar completes at +1 second.
    d["available_time"] = d.observation_time.astype("int64") + 1_000_000_000
    start, end = PERIODS[year]
    return d[(d.available_time >= start) & (d.available_time <= end)].sort_values("available_time")


def event_map(d10: pd.DataFrame) -> dict[str, int]:
    return d10.groupby("regime_id", sort=False).available_time.first().astype("int64").to_dict()


def next_open_idx(ts: np.ndarray, decision_ts: int) -> int | None:
    # A decision at the completed prior 1s bar's ts_init is executable at the
    # next bar whose open ts_event equals that boundary.
    if decision_ts < int(ts[0]):
        return None
    i = int(np.searchsorted(ts, decision_ts, side="left"))
    return i if i < len(ts) else None


def session(ts_ns: int) -> str:
    t = pd.Timestamp(ts_ns, unit="ns", tz="UTC").tz_convert("America/Chicago")
    m = t.hour * 60 + t.minute
    return "RTH" if 510 <= m < 900 else "ETH"


def build_candidates(year: int, policy: str, flips: pd.DataFrame,
                     d10: pd.DataFrame, placebo: pd.DataFrame | None) -> list[dict]:
    fmap = flips.set_index("regime_start_time").to_dict("index")
    dmap = event_map(d10)
    rows: list[dict] = []

    if policy in ("P0", "P2"):
        for r in flips.itertuples():
            if not (PERIODS[year][0] <= r.regime_start_time <= PERIODS[year][1]):
                continue
            exit_decision = int(r.opposing_flip_time) if pd.notna(r.opposing_flip_time) else None
            exit_reason = "opposite_regime_flip_exit"
            d10_decision = None
            if policy == "P2":
                dt = dmap.get(r.regime_id)
                # Entry decision/flip update wins a same-timestamp D10. D10 must
                # be strictly after entry and strictly before the opposite flip.
                if dt is not None and dt > r.regime_start_time:
                    d10_decision=int(dt)
                    if exit_decision is None or dt < exit_decision:
                        exit_decision, exit_reason = int(dt), "d10_exit"
            rows.append({
                "origin_regime_id": r.regime_id, "origin_regime_start": int(r.regime_start_time),
                "entry_decision_ts": int(r.regime_start_time), "direction": int(r.direction),
                "atr_at_entry": float(r.atr), "confirmation_ts": int(r.regime_start_time),
                "confirmed_regime_id": r.regime_id, "logical_exit_decision_ts": exit_decision,
                "logical_exit_reason": exit_reason, "natural_exit_decision_ts": (
                    int(r.opposing_flip_time) if pd.notna(r.opposing_flip_time) else None),
                "d10_exit_decision_ts": d10_decision, "matched_treated_regime_id": None,
            })
        return rows

    source = placebo if policy.startswith("P4") else d10
    if source is None:
        return rows
    source = source.copy()
    if "available_time" not in source:
        source["available_time"] = source.observation_time.astype("int64") + 1_000_000_000
    for e in source.sort_values("available_time").itertuples():
        old_start = int(e.regime_start_time)
        old = fmap.get(old_start)
        if old is None or pd.isna(old.get("opposing_flip_time")):
            continue
        confirmation = int(old["opposing_flip_time"])
        if int(e.available_time) >= confirmation:
            continue  # flip update wins same-boundary score; not a pre-flip entry
        confirmed = fmap.get(confirmation)
        if confirmed is None:
            continue
        expected_direction = int(-old["direction"])
        expected_id = f"{expected_direction}:{confirmation}"
        if int(confirmed["direction"]) != expected_direction or confirmed["regime_id"] != expected_id:
            raise RuntimeError("Confirmed-regime reset/identity mismatch")
        natural_exit = (int(confirmed["opposing_flip_time"])
                        if pd.notna(confirmed.get("opposing_flip_time")) else None)
        reason, exit_decision, d10_decision = "opposite_regime_flip_exit", natural_exit, None
        if policy in ("P3", "P4B"):
            confirmed_id = f"{int(-old['direction'])}:{confirmation}"
            dt = dmap.get(confirmed_id)
            if dt is not None and dt > confirmation:
                d10_decision=int(dt)
                if natural_exit is None or dt < natural_exit:
                    reason, exit_decision = "d10_exit", int(dt)
        rows.append({
            "origin_regime_id": e.regime_id, "origin_regime_start": old_start,
            "entry_decision_ts": int(e.available_time), "direction": int(-old["direction"]),
            "atr_at_entry": float(e.atr), "confirmation_ts": confirmation,
            "confirmed_regime_id": f"{int(-old['direction'])}:{confirmation}",
            "logical_exit_decision_ts": exit_decision, "logical_exit_reason": reason,
            "natural_exit_decision_ts": natural_exit, "d10_exit_decision_ts": d10_decision,
            "matched_treated_regime_id": getattr(e,"treated_regime_id",None),
        })
    return rows


def simulate_one(c: dict, bars: dict[str, np.ndarray], stop_mult: float | None,
                 contract: str, year: int, policy: str) -> dict | None:
    ts, op, hi, lo, cl = (bars[k] for k in ("ts","open","high","low","close"))
    ei = next_open_idx(ts, c["entry_decision_ts"])
    if ei is None:
        return None
    entry_px = float(op[ei] if contract == PRIMARY else cl[max(0,ei-1)])
    entry_delay_ns = int(ts[ei] - c["entry_decision_ts"])
    d = int(c["direction"])
    stop_px = (entry_px - d * float(stop_mult) * c["atr_at_entry"]
               if stop_mult is not None else np.nan)
    logical_i = (next_open_idx(ts, c["logical_exit_decision_ts"])
                 if c["logical_exit_decision_ts"] is not None else None)
    natural_i = (next_open_idx(ts,c["natural_exit_decision_ts"])
                 if c.get("natural_exit_decision_ts") is not None else None)
    confirm_i = next_open_idx(ts,c["confirmation_ts"])
    scan_end = logical_i if logical_i is not None else len(ts)
    stop_i = None; stop_fill = None; gap = False
    if stop_mult is not None:
        for i in range(ei, scan_end):
            breached = lo[i] <= stop_px if d == 1 else hi[i] >= stop_px
            if not breached:
                continue
            stop_i = i
            if contract == PRIMARY:
                gap = op[i] <= stop_px if d == 1 else op[i] >= stop_px
                stop_fill = float(op[i] if gap else stop_px)
            else:
                # Touch is known at bar close; the fixture established that the
                # next NT bar-matcher market fill is priced at this completed
                # bar's close and timestamped at the following bar event.
                stop_fill = float(cl[i])
            break

    # Conservative tie: stop discovered on the bar ending at the logical exit
    # decision wins over a D10/flip order executable at that same boundary.
    if stop_i is not None:
        exit_reason = ("stop_before_flip" if ts[stop_i] < c["confirmation_ts"]
                       else "stop_after_flip")
        if contract == PRIMARY:
            exit_ts = int(ts[stop_i])  # exact touch time unknown within this bar
            exit_window_end = int(ts[stop_i] + 1_000_000_000)
        else:
            ni = stop_i + 1
            if ni < len(ts):
                exit_ts = int(ts[ni]);exit_px=stop_fill
            else:
                exit_reason="data_end_censored";exit_ts=None;exit_px=None
            exit_window_end = None
        if contract == PRIMARY: exit_px = stop_fill
        tie = (c["logical_exit_decision_ts"] is not None
               and ts[stop_i] + 1_000_000_000 == c["logical_exit_decision_ts"])
    elif logical_i is not None:
        exit_reason = c["logical_exit_reason"]
        if contract == PRIMARY:
            exit_ts, exit_px = int(ts[logical_i]), float(op[logical_i])
        else:
            # Empirical NT bar matcher convention from the isolated fixture:
            # callback decision -> fill timestamp at next event, price at the
            # completed decision bar close.
            prev = max(0, logical_i - 1)
            exit_ts, exit_px = int(ts[logical_i]), float(cl[prev])
        exit_window_end = None; tie = False; gap = False
    else:
        exit_reason = "data_end_censored"; exit_ts = None; exit_px = None
        exit_window_end = None; tie = False; gap = False

    gross = ((exit_px - entry_px) * d * MULTIPLIER if exit_px is not None else np.nan)
    net = gross - ROUND_TRIP_COST if exit_px is not None else np.nan
    reached_confirmation = (exit_reason != "stop_before_flip" and confirm_i is not None
                            and (exit_ts is None or ts[confirm_i] <= exit_ts))
    wait_px = (float(op[confirm_i] if contract==PRIMARY else cl[max(0,confirm_i-1)])
               if confirm_i is not None else np.nan)
    if exit_px is not None:
        if reached_confirmation:
            pre_flip_pnl=(wait_px-entry_px)*d*MULTIPLIER
            post_flip_pnl=(exit_px-wait_px)*d*MULTIPLIER
        else:
            pre_flip_pnl=gross; post_flip_pnl=0.0
    else:
        pre_flip_pnl=post_flip_pnl=np.nan
    pre_candidates=[]
    if confirm_i is not None: pre_candidates.append(confirm_i-1)
    if stop_i is not None: pre_candidates.append(stop_i-1 if contract==PRIMARY else stop_i)
    if logical_i is not None: pre_candidates.append(logical_i)
    pre_end=min(pre_candidates,default=len(ts)-1)
    if pre_end>=ei:
        if d==1: pre_mae=max(0.0,entry_px-float(np.min(lo[ei:pre_end+1])))
        else: pre_mae=max(0.0,float(np.max(hi[ei:pre_end+1]))-entry_px)
    else: pre_mae=0.0
    if confirm_i is not None and reached_confirmation:
        pre_mae=max(pre_mae, max(0.0,(entry_px-wait_px) if d==1 else (wait_px-entry_px)))
    if contract==PRIMARY and stop_i is not None and exit_px is not None:
        pre_mae=max(pre_mae,max(0.0,(entry_px-exit_px) if d==1 else (exit_px-entry_px)))

    natural_px=np.nan; natural_pnl=np.nan; add_fav=np.nan; adverse_avoided=np.nan;natural_reason=None;natural_fill_ts=None
    if natural_i is not None:
        natural_stop_i=None;natural_stop_fill=None
        if stop_mult is not None:
            for j in range(ei,natural_i):
                if (lo[j]<=stop_px if d==1 else hi[j]>=stop_px):
                    natural_stop_i=j
                    if contract==PRIMARY:
                        through=(op[j]<=stop_px if d==1 else op[j]>=stop_px)
                        natural_stop_fill=float(op[j] if through else stop_px)
                    elif j+1<len(ts): natural_stop_fill=float(cl[j])
                    break
        if natural_stop_i is not None and natural_stop_fill is not None:
            natural_px=natural_stop_fill;natural_reason=("stop_before_flip" if ts[natural_stop_i]<c["confirmation_ts"] else "stop_after_flip")
            natural_fill_ts=(int(ts[natural_stop_i]) if contract==PRIMARY else
                             (int(ts[natural_stop_i+1]) if natural_stop_i+1<len(ts) else None))
            if natural_fill_ts is None: natural_px=np.nan;natural_reason="data_end_censored"
        else:
            natural_px=float(op[natural_i] if contract==PRIMARY else cl[max(0,natural_i-1)])
            natural_reason="opposite_regime_flip_exit"
            natural_fill_ts=int(ts[natural_i])
        natural_pnl=((natural_px-entry_px)*d*MULTIPLIER-ROUND_TRIP_COST if np.isfinite(natural_px) else np.nan)
        if exit_reason=="d10_exit" and logical_i is not None and natural_i>logical_i:
            path_end=(natural_stop_i+(1 if contract==SENSITIVITY else 0)
                      if natural_stop_i is not None else natural_i)
            path_hi=hi[logical_i:path_end];path_lo=lo[logical_i:path_end]
            max_hi=max([exit_px,natural_px]+([float(np.max(path_hi))] if len(path_hi) else []))
            min_lo=min([exit_px,natural_px]+([float(np.min(path_lo))] if len(path_lo) else []))
            if d==1:
                add_fav=max(0.0,max_hi-exit_px)*MULTIPLIER
                adverse_avoided=max(0.0,exit_px-min_lo)*MULTIPLIER
            else:
                add_fav=max(0.0,exit_px-min_lo)*MULTIPLIER
                adverse_avoided=max(0.0,max_hi-exit_px)*MULTIPLIER
    release_ts = (int(ts[stop_i]+1_000_000_000) if stop_i is not None and contract==PRIMARY
                  else exit_ts)
    return {
        **c, "year": year, "policy": policy, "execution_contract": contract,
        "stop_atr_mult": stop_mult, "entry_fill_ts": int(ts[ei]),
        "entry_fill_price": entry_px, "stop_price": stop_px,
        "entry_decision_to_fill_ns":entry_delay_ns,
        "entry_exact_boundary_fill":entry_delay_ns==0,
        "entry_fill_gap_class":("exact_boundary" if entry_delay_ns==0 else
            ("short_market_data_gap_le_60s" if entry_delay_ns<=60_000_000_000 else "extended_market_data_gap_gt_60s")),
        "stop_touch_bar_ts_event": int(ts[stop_i]) if stop_i is not None else None,
        "stop_touch_bar_ts_init": int(ts[stop_i] + 1_000_000_000) if stop_i is not None else None,
        "stop_gap_fill": gap, "same_bar_stop_logical_exit_tie": tie,
        "exit_ts": exit_ts, "exit_touch_window_end": exit_window_end,
        "exit_price": exit_px, "exit_reason": exit_reason,
        "gross_pnl": gross, "net_pnl": net, "session": session(int(ts[ei])),
        "completed": exit_px is not None, "position_release_ts":release_ts,
        "confirmation_fill_ts":int(ts[confirm_i]) if confirm_i is not None else None,
        "confirmation_fill_price":wait_px,"reached_confirmation":reached_confirmation,
        "pre_flip_pnl":pre_flip_pnl,"post_flip_pnl":post_flip_pnl,
        "pre_flip_mae_points":pre_mae,"pre_flip_mae_atr":pre_mae/c["atr_at_entry"],
        "front_run_advantage_points":(wait_px-entry_px)*d if confirm_i is not None else np.nan,
        "front_run_advantage_usd":(wait_px-entry_px)*d*MULTIPLIER if confirm_i is not None else np.nan,
        "front_run_advantage_atr":(wait_px-entry_px)*d/c["atr_at_entry"] if confirm_i is not None else np.nan,
        "natural_exit_fill_ts":natural_fill_ts,
        "natural_exit_fill_price":natural_px,"natural_exit_net_pnl":natural_pnl,"natural_exit_reason":natural_reason,
        "incremental_pnl_from_d10":(net-natural_pnl if exit_reason=="d10_exit" and np.isfinite(natural_pnl) else np.nan),
        "max_additional_favorable_after_d10_usd":add_fav,
        "max_adverse_movement_avoided_usd":adverse_avoided,
        "giveback_avoided_usd":(net-natural_pnl if exit_reason=="d10_exit" and np.isfinite(natural_pnl) else np.nan),
        "runner_truncation_usd":(natural_pnl-net if exit_reason=="d10_exit" and np.isfinite(natural_pnl) and natural_pnl>net else 0.0),
    }


def simulate_policy(candidates: list[dict], bars: dict, year: int, policy: str,
                    stop: float | None, contract: str) -> list[dict]:
    out=[]; active_until=-1
    for c in sorted(candidates, key=lambda x:x["entry_decision_ts"]):
        if c["entry_decision_ts"] < active_until:
            continue
        r=simulate_one(c,bars,stop,contract,year,policy)
        if r is None: continue
        out.append(r)
        active_until = r["position_release_ts"] if r["position_release_ts"] is not None else np.iinfo(np.int64).max
    return out


def main():
    frozen = json.loads((WORK / "frozen_threshold.json").read_text())
    assert frozen["threshold_type"] == "absolute_validation_frozen_score"
    assert frozen["validation_period"] == "2025-01-01..2025-02-28"
    assert frozen["test_rank_used"] is False
    assert STOPS == (0.50, 1.00, 1.50)
    fixture=pd.read_parquet(AUDIT/"execution_contract_comparison.parquet")
    f3=fixture[fixture.contract.eq("Close-detected stop + next market fill")].iloc[0]
    if not (f3.actual_entry_fill_price==20514.25 and f3.stop_fill_price==20508.25):
        raise RuntimeError("Contract 3 fixture provenance changed")
    all_trades=[]
    for year in (2025,2026):
        bars=load_bars(year); flips=load_flips(year); d10=load_d10(year)
        placebo_path=WORK/"placebo_events.parquet"
        placebo=pd.read_parquet(placebo_path) if placebo_path.exists() else None
        if placebo is not None:
            placebo["available_time"]=placebo.observation_time.astype("int64")+1_000_000_000
            start,end=PERIODS[year]
            placebo=placebo[(placebo.available_time>=start)&(placebo.available_time<=end)].copy()
        for policy in ("P0","P1","P2","P3","P4A","P4B"):
            candidates=build_candidates(year,policy,flips,d10,placebo)
            stops=(None,) if policy in ("P0","P2") else STOPS
            for stop in stops:
                for contract in (PRIMARY,SENSITIVITY):
                    all_trades.extend(simulate_policy(candidates,bars,year,policy,stop,contract))
    trades=pd.DataFrame(all_trades)
    if trades.empty: raise RuntimeError("No policy trades generated")
    trades.insert(0,"trade_id",np.arange(1,len(trades)+1))
    for y,(start,end) in PERIODS.items():
        q=trades[trades.year.eq(y)]
        if not ((q.entry_decision_ts>=start)&(q.entry_decision_ts<=end)&
                (q.entry_fill_ts>=start)&(q.entry_fill_ts<=end)).all():
            raise RuntimeError(f"Out-of-period decision/fill in {y}")
    overlap=[]
    for keys,g in trades.groupby(["execution_contract","year","policy","stop_atr_mult"],dropna=False):
        g=g.sort_values("entry_fill_ts"); prev=None
        for r in g.itertuples():
            ok=prev is None or r.entry_decision_ts>=prev
            overlap.append({"execution_contract":keys[0],"year":keys[1],"policy":keys[2],
                "stop_atr_mult":keys[3],"trade_id":r.trade_id,"entry_decision_ts":r.entry_decision_ts,
                "prior_position_release_ts":prev,"pass":ok})
            prev=r.position_release_ts
    overlap=pd.DataFrame(overlap)
    overlap.to_parquet(AUDIT/"position_overlap_audit.parquet",index=False)
    if not overlap["pass"].all(): raise RuntimeError("Position overlap audit failed")
    reset=trades[["trade_id","origin_regime_id","confirmed_regime_id","direction"]].copy()
    reset["confirmed_direction"]=reset.confirmed_regime_id.str.split(":").str[0].astype(int)
    reset["pass"]=reset.confirmed_direction.eq(reset.direction)
    reset.to_parquet(AUDIT/"score_regime_id_audit.parquet",index=False)
    if not reset["pass"].all(): raise RuntimeError("Regime reset audit failed")
    trades[["trade_id","execution_contract","year","policy","entry_decision_ts","entry_fill_ts",
            "entry_decision_to_fill_ns","entry_exact_boundary_fill","entry_fill_gap_class","stop_gap_fill"]].to_parquet(
                AUDIT/"entry_timing_audit.parquet",index=False)
    timing=trades.groupby(["execution_contract","year","entry_fill_gap_class"]).entry_decision_to_fill_ns.agg(
        count="size",min_ns="min",median_ns="median",max_ns="max",
        gap_count=lambda x:(x>0).sum()).reset_index()
    timing.to_parquet(AUDIT/"entry_fill_gap_summary.parquet",index=False)
    if (trades.entry_decision_to_fill_ns<0).any():
        raise RuntimeError("Unexpected decision-to-next-executable-open gap")
    trades.to_parquet(RESULTS/"trade_results.parquet",index=False)
    print(trades.groupby(["execution_contract","year","policy","stop_atr_mult"],dropna=False).size())


if __name__=="__main__": main()
