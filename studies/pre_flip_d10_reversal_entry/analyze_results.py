from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from common import AUDIT, RESULTS, WORK

RUNS = WORK / "nt_runs"
SEED = 20260711


def load_runs() -> pd.DataFrame:
    frames = []
    audit_files = {"entry_timing_audit.parquet": [], "score_regime_id_audit.parquet": [],
                   "same_timestamp_exit_audit.parquet": []}
    for p in RUNS.glob("*/trades.parquet"):
        d = pd.read_parquet(p)
        _, year, policy, stop = p.parent.name.split("_") if False else (None, *p.parent.name.split("_"))
        d["year"] = int(year); d["policy"] = policy; d["stop_atr_mult"] = float(stop)
        frames.append(d)
        for name in audit_files:
            q = p.parent / name
            if q.exists():
                a = pd.read_parquet(q); a["year"] = int(year); a["policy"] = policy; a["stop_atr_mult"] = float(stop)
                audit_files[name].append(a)
    if not frames:
        raise RuntimeError("No NT trade results found")
    trades = pd.concat(frames, ignore_index=True)
    for name, parts in audit_files.items():
        (pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()).to_parquet(AUDIT / name, index=False)
    return trades


def completeness(trades: pd.DataFrame) -> None:
    allowed = {"stop_before_flip", "stop_after_flip", "d10_exit",
               "opposite_regime_flip_exit", "data_end_censored"}
    a = trades.copy()
    a["valid_reason"] = a.exit_reason.isin(allowed)
    a["timestamp_valid"] = np.where(a.exit_reason.eq("data_end_censored"),
                                    a.exit_ts.isna(), a.exit_ts.notna() & (a.exit_ts >= a.entry_ts))
    a["price_valid"] = np.where(a.exit_reason.eq("data_end_censored"), True, a.exit_price.notna())
    a["d10_regime_valid"] = ~a.exit_reason.eq("d10_exit") | (
        a.confirmed_regime_id.notna() & a.old_regime_state_reset.fillna(False))
    a["pass"] = a[["valid_reason","timestamp_valid","price_valid","d10_regime_valid"]].all(axis=1)
    a[["trade_id","year","policy","stop_atr_mult","exit_reason","valid_reason",
       "timestamp_valid","price_valid","d10_regime_valid","pass"]].to_parquet(
           AUDIT / "exit_reason_completeness_audit.parquet", index=False)
    if not a["pass"].all():
        raise RuntimeError(f"Exit completeness audit failed for {(~a['pass']).sum()} trades")
    score_audit = AUDIT / "score_regime_id_audit.parquet"
    if score_audit.exists():
        s = pd.read_parquet(score_audit)
        bad = s[(s.trade_id.notna()) & (~s["pass"].fillna(False))]
        if len(bad):
            raise RuntimeError(f"Score regime-ID audit failed for {len(bad)} exits")


def metrics(g: pd.DataFrame) -> dict:
    c = g[g.exit_reason.ne("data_end_censored") & g.net_pnl.notna()].sort_values("exit_ts")
    x = c.net_pnl.astype(float)
    eq = x.cumsum(); dd = eq - eq.cummax()
    wins = x[x > 0].sum(); losses = -x[x < 0].sum()
    month = pd.to_datetime(c.exit_ts, unit="ns", utc=True).dt.to_period("M") if len(c) else pd.Series(dtype=str)
    monthly = c.assign(month=month).groupby("month").net_pnl.sum() if len(c) else pd.Series(dtype=float)
    return {
        "trade_count": len(c), "win_rate": float((x > 0).mean()) if len(x) else np.nan,
        "gross_pnl": float(c.gross_pnl.sum()) if len(c) else 0.0,
        "net_pnl": float(x.sum()), "ev_per_trade": float(x.mean()) if len(x) else np.nan,
        "profit_factor": float(wins / losses) if losses else np.nan,
        "maximum_drawdown": float(dd.min()) if len(dd) else 0.0,
        "median_trade": float(x.median()) if len(x) else np.nan,
        "p10_trade": float(x.quantile(.1)) if len(x) else np.nan,
        "p90_trade": float(x.quantile(.9)) if len(x) else np.nan,
        "monthly_positive_rate": float((monthly > 0).mean()) if len(monthly) else np.nan,
        "stop_out_before_flip_rate": float(c.exit_reason.eq("stop_before_flip").mean()) if len(c) else np.nan,
        "flip_confirmation_rate": float(c.confirmed.fillna(False).mean()) if len(c) else np.nan,
        "post_confirmation_stop_rate": float(c.exit_reason.eq("stop_after_flip").mean()) if len(c) else np.nan,
        "d10_exit_rate": float(c.exit_reason.eq("d10_exit").mean()) if len(c) else np.nan,
        "opposite_flip_fallback_exit_rate": float(c.exit_reason.eq("opposite_regime_flip_exit").mean()) if len(c) else np.nan,
        "censored_count": int(g.exit_reason.eq("data_end_censored").sum()),
    }


def summaries(trades: pd.DataFrame):
    rec = []
    for keys, g in trades.groupby(["year","policy","stop_atr_mult"]):
        rec.append({"year":keys[0],"policy":keys[1],"stop_atr_mult":keys[2],**metrics(g)})
    policy = pd.DataFrame(rec)
    policy.to_parquet(RESULTS / "policy_results.parquet", index=False)
    policy[policy.policy.isin(["P1","P3","P4A","P4B"])].to_parquet(RESULTS / "stop_sensitivity.parquet", index=False)

    completed = trades[trades.exit_reason.ne("data_end_censored")].copy()
    completed["month"] = pd.to_datetime(completed.exit_ts, unit="ns", utc=True).dt.tz_convert("America/Chicago").dt.strftime("%Y-%m")
    monthly = completed.groupby(["year","policy","stop_atr_mult","month"]).agg(
        trade_count=("trade_id","size"), net_pnl=("net_pnl","sum"), ev_per_trade=("net_pnl","mean"),
        win_rate=("net_pnl",lambda x:(x>0).mean())).reset_index()
    monthly.to_parquet(RESULTS / "monthly_results.parquet", index=False)
    seg = completed.groupby(["year","policy","stop_atr_mult","session"]).agg(
        trade_count=("trade_id","size"), net_pnl=("net_pnl","sum"), ev_per_trade=("net_pnl","mean"),
        win_rate=("net_pnl",lambda x:(x>0).mean())).reset_index()
    seg.to_parquet(RESULTS / "segment_results.parquet", index=False)
    reason = trades.groupby(["year","policy","stop_atr_mult","exit_reason"]).size().rename("count").reset_index()
    reason["percent"] = reason["count"] / reason.groupby(["year","policy","stop_atr_mult"])["count"].transform("sum")
    reason.to_parquet(RESULTS / "d10_exit_reason_summary.parquet", index=False)
    return policy


def paired_outputs(trades: pd.DataFrame):
    pre = trades[trades.policy.isin(["P1","P3"])].copy()
    decomp = pre[["year","policy","stop_atr_mult","trade_id","origin_regime_id","confirmed_regime_id",
                  "pre_flip_pnl","post_flip_pnl","pre_flip_mae_atr","net_pnl","exit_reason"]]
    decomp.to_parquet(RESULTS / "pnl_decomposition.parquet", index=False)
    p0 = trades[trades.policy.eq("P0")][["year","origin_regime_id","fill_price","entry_ts"]].rename(
        columns={"fill_price":"wait_fill_price","entry_ts":"wait_entry_ts"})
    comp = pre.merge(p0, left_on=["year","confirmed_regime_id"], right_on=["year","origin_regime_id"], suffixes=("","_p0"))
    comp["front_run_advantage_points"] = (comp.wait_fill_price - comp.fill_price) * comp.direction
    comp["front_run_advantage_atr"] = comp.front_run_advantage_points / comp.atr_at_signal
    comp["front_run_advantage_usd"] = comp.front_run_advantage_points * 20
    comp.to_parquet(RESULTS / "preflip_vs_wait_for_flip.parquet", index=False)

    p1 = trades[trades.policy.eq("P1")][["year","stop_atr_mult","origin_regime_id","net_pnl","exit_price","exit_reason"]].rename(
        columns={"net_pnl":"flip_exit_pnl","exit_price":"flip_exit_price","exit_reason":"flip_exit_reason"})
    p3 = trades[trades.policy.eq("P3")].merge(p1, on=["year","stop_atr_mult","origin_regime_id"], how="left")
    p3["incremental_pnl_from_using_D10"] = p3.net_pnl - p3.flip_exit_pnl
    p3["classification"] = np.select([
        p3.exit_reason.eq("d10_exit") & (p3.incremental_pnl_from_using_D10 > 0),
        p3.exit_reason.eq("d10_exit") & (p3.incremental_pnl_from_using_D10 <= 0),
    ], ["D10 occurred and improved PnL","D10 occurred and reduced PnL"], default="D10 never occurred")
    p3.to_parquet(RESULTS / "d10_exit_contribution.parquet", index=False)
    p3[["year","stop_atr_mult","origin_regime_id","classification","net_pnl",
        "flip_exit_pnl","incremental_pnl_from_using_D10"]].to_parquet(RESULTS / "runner_capture.parquet", index=False)
    tail = p3.groupby(["year","stop_atr_mult"]).net_pnl.agg(
        count="size", mean="mean", median="median", p01=lambda x:x.quantile(.01),
        p05=lambda x:x.quantile(.05), p95=lambda x:x.quantile(.95), p99=lambda x:x.quantile(.99)).reset_index()
    tail.to_parquet(RESULTS / "tail_dependence.parquet", index=False)
    return comp, p3


def diagnostics():
    events = pd.read_parquet(RESULTS / "d10_entry_events.parquet")
    cov = pd.read_parquet(RESULTS / "regime_d10_coverage.parquet")
    d = events[events.is_first_crossing].merge(cov[["regime_id","regime_end_time","seconds_from_D10_to_regime_end"]], on="regime_id", how="left")
    d["anticipated_flip_observed"] = d.regime_end_time.notna()
    d.to_parquet(RESULTS / "forward_reversal_diagnostics.parquet", index=False)


def placebo_economics(trades: pd.DataFrame):
    rows=[]
    rng=np.random.default_rng(SEED)
    for year in (2025,2026):
      for stop in (.5,1.,1.5):
       for real,placebo in (("P1","P4A"),("P3","P4B")):
        a=trades[(trades.year==year)&(trades.policy==real)&(trades.stop_atr_mult==stop)&trades.net_pnl.notna()].net_pnl.to_numpy()
        b=trades[(trades.year==year)&(trades.policy==placebo)&(trades.stop_atr_mult==stop)&trades.net_pnl.notna()].net_pnl.to_numpy()
        observed=float(a.mean()-b.mean()) if len(a) and len(b) else np.nan
        null=[]
        if len(a) and len(b):
            z=np.r_[a,b]
            for _ in range(2000):
                rng.shuffle(z); null.append(z[:len(a)].mean()-z[len(a):].mean())
        p=float((1+np.sum(np.abs(null)>=abs(observed)))/(1+len(null))) if null else np.nan
        rows.append({"year":year,"stop_atr_mult":stop,"real_policy":real,"placebo_policy":placebo,
                     "real_count":len(a),"placebo_count":len(b),"real_ev":np.mean(a) if len(a) else np.nan,
                     "placebo_ev":np.mean(b) if len(b) else np.nan,"ev_lift":observed,"permutation_p_value":p})
    pd.DataFrame(rows).to_parquet(RESULTS / "matched_placebo_summary.parquet", index=False)


def report(policy: pd.DataFrame, comp: pd.DataFrame, trades: pd.DataFrame):
    p0=policy[policy.policy.eq("P0")].set_index("year")
    eligible=policy[policy.policy.isin(["P1","P2","P3"])].copy()
    eligible["lift"] = eligible.apply(lambda r:r.ev_per_trade-p0.loc[r.year].ev_per_trade,axis=1)
    both=eligible.pivot_table(index=["policy","stop_atr_mult"],columns="year",values="lift").dropna()
    candidates=both[(both[2025]>0)&(both[2026]>0)] if len(both) else both
    best=(candidates.mean(axis=1).idxmax() if len(candidates) else None)
    best_label=f"{best[0]} @ {best[1]:.2f} ATR" if best else "NONE"
    chosen=best if best else ("P3",1.0)
    def row(y):
        q=policy[(policy.year==y)&(policy.policy==chosen[0])&(policy.stop_atr_mult==chosen[1])]
        return q.iloc[0] if len(q) else pd.Series(dtype=float)
    r25,r26=row(2025),row(2026)
    valid=pd.read_parquet(RESULTS/"regime_d10_coverage.parquet")
    valid=valid[valid.valid_score_checkpoint_count>0]
    advantage=comp.front_run_advantage_usd.mean() if len(comp) else np.nan
    advantage_atr=comp.front_run_advantage_atr.mean() if len(comp) else np.nan
    verdict="CONTINUE" if best else "CLOSE"
    text=f"""PRE-FLIP D10 REVERSAL STUDY

BEST POLICY:
{best_label}

2025 EV LIFT VS FLIP-TO-FLIP BASELINE:
${(r25.get('ev_per_trade',np.nan)-p0.loc[2025].ev_per_trade):.2f}

2026 EV LIFT VS FLIP-TO-FLIP BASELINE:
${(r26.get('ev_per_trade',np.nan)-p0.loc[2026].ev_per_trade):.2f}

2025 STOP-OUT BEFORE FLIP RATE:
{r25.get('stop_out_before_flip_rate',np.nan):.2%}

2026 STOP-OUT BEFORE FLIP RATE:
{r26.get('stop_out_before_flip_rate',np.nan):.2%}

2025 NEW-REGIME D10 EXIT RATE:
{r25.get('d10_exit_rate',np.nan):.2%}

2026 NEW-REGIME D10 EXIT RATE:
{r26.get('d10_exit_rate',np.nan):.2%}

2025 OPPOSITE-FLIP FALLBACK EXIT RATE:
{r25.get('opposite_flip_fallback_exit_rate',np.nan):.2%}

2026 OPPOSITE-FLIP FALLBACK EXIT RATE:
{r26.get('opposite_flip_fallback_exit_rate',np.nan):.2%}

PERCENT OF VALIDLY SCORED REGIMES THAT EVER REACH D10:
{valid.ever_reached_D10.mean():.2%}

AVERAGE PRE-FLIP PNL:
${trades[trades.policy.isin(['P1','P3'])].pre_flip_pnl.mean():.2f}

AVERAGE POST-FLIP PNL:
${trades[trades.policy.isin(['P1','P3'])].post_flip_pnl.mean():.2f}

D10 FRONT-RUN ENTRY ADVANTAGE VS WAITING FOR FLIP:
${advantage:.2f} ({advantage_atr:.3f} ATR)

MATCHED PLACEBO P-VALUE:
See `matched_placebo_summary.parquet` by year and stop.

VERDICT:
{verdict}

## Executive summary

The verdict follows the two-year, no-test-set-stop-selection rule. No stop is declared a winner unless the same frozen policy has positive EV lift in both years.

## Exact strategy and policy definitions

See `SPEC.md` and `config.yaml`. P0-P4 economics were generated in NautilusTrader BacktestEngine on one-second bars.

## Frozen D10 threshold definition

W4 was fit on 2021-2024 only. D10 is the absolute 90th-percentile Jan-Feb 2025 validation score saved before policy evaluation; no contemporaneous test rank is used.

## Entry timing and stop execution audit

Market orders fill at the next executable one-second open. The fixed stop is entry-fill anchored, ATR is frozen at entry, and stop breach is processed before score/flip alternatives on a shared bar.

## Score/regime reset and coverage

Confirmed trades store a fresh confirmed-regime ID. D10 exits fail fast unless associated with that ID. Coverage artifacts distinguish valid-but-never-D10 from unavailable scores and same-timestamp cases.

## PnL decomposition, stop sensitivity, and policy comparison

See `pnl_decomposition.parquet`, `stop_sensitivity.parquet`, and `policy_results.parquet`; years are never pooled for stop selection.

## D10 fallback, same-timestamp handling, and controls

See `d10_exit_contribution.parquet`, `d10_exit_reason_summary.parquet`, `same_timestamp_exit_audit.parquet`, and `matched_placebo_summary.parquet`. Actual callback ordering gives the regime update priority when both become available in the same callback.

## Tail dependence, failure modes, and recommendation

See `tail_dependence.parquet` and `runner_capture.parquet`. Jan-Feb 2025 calibrated the threshold and is not pristine OOS; 2026 was previously inspected upstream. Tradability is judged on event-loop economics, not AUC or rank separation.
"""
    (RESULTS/"final_report.md").write_text(text,encoding="utf-8")


def main():
    trades=load_runs(); completeness(trades)
    trades.to_parquet(RESULTS/"trade_results.parquet",index=False)
    policy=summaries(trades); comp,_=paired_outputs(trades); diagnostics(); placebo_economics(trades); report(policy,comp,trades)


if __name__ == "__main__": main()
