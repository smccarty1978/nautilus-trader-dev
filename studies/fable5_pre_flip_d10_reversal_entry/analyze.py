"""Consolidate NT runs into the required result/audit artifacts + final report.

Primary economics: NT event-loop fills with stop fills conservatively
repriced to the fill bar's open when the bar gapped through the trigger
(NT itself optimistically fills at trigger — see test_fill_fixture.py).
Raw (unrepriced) economics are reported alongside.

Costs: $5 RT commission + $5 (1 NQ tick) RT slippage allowance per trade.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from studies.fable5_pre_flip_d10_reversal_entry.common import (  # noqa: E402
    AUDIT, COST_RT, ECON_WINDOWS, EXIT_REASONS, NQ_MULT, NS_PER_S, RAW_1S,
    RESULTS, STOP_GRID, WORK, load_frozen_threshold,
)

NT_RUNS = WORK / "nt_runs"


# --------------------------------------------------------------------- loading
def load_runs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    trades, timing, same_ts, skips = [], [], [], []
    for d in sorted(NT_RUNS.iterdir()):
        meta = json.loads((d / "meta.json").read_text())
        for name, acc in [("trades", trades), ("entry_timing", timing),
                          ("same_ts", same_ts), ("skips", skips)]:
            p = d / f"{name}.parquet"
            if not p.exists():
                continue
            df = pd.read_parquet(p)
            if len(df) == 0:
                continue
            df["run_policy"] = meta["policy"]
            df["run_stop"] = meta["stop"]
            df["run_year"] = meta["year"]
            df["run_seed"] = meta.get("seed", 42)
            acc.append(df)
    cat = lambda x: (pd.concat(x, ignore_index=True) if x else pd.DataFrame())
    return cat(trades), cat(timing), cat(same_ts), cat(skips)


def load_1s_opens() -> dict[int, tuple[np.ndarray, np.ndarray, np.ndarray]]:
    out = {}
    for yr, p in RAW_1S.items():
        df = pd.read_parquet(p, columns=["open", "close"])
        out[yr] = (df.index.view(np.int64), df["open"].to_numpy(),
                   df["close"].to_numpy())
    return out


# ------------------------------------------------------------- stop repricing
def reprice_stops(tr: pd.DataFrame, bars: dict) -> pd.DataFrame:
    """Conservative gap repricing: a stop filled on a bar whose OPEN was
    already through the trigger is repriced to that open."""
    tr = tr.copy()
    tr["exit_px_raw"] = tr["exit_px"]
    tr["stop_gap_repriced"] = False
    is_stop = tr["exit_reason"].isin(["stop_before_flip", "stop_after_flip"])
    for i in tr.index[is_stop]:
        yr = int(tr.at[i, "run_year"])
        ts, opens, _ = bars[yr]
        fill_ts = tr.at[i, "exit_fill_ts"]
        if not np.isfinite(fill_ts):
            continue
        # stop fill event ts == fill bar ts_init -> bar ts_event = ts - 1s
        j = np.searchsorted(ts, int(fill_ts) - NS_PER_S, side="left")
        if j >= len(ts) or ts[j] != int(fill_ts) - NS_PER_S:
            continue
        o = float(opens[j])
        d = int(tr.at[i, "entry_dir"])
        stop_px = float(tr.at[i, "stop_px"])
        if (d == 1 and o < stop_px) or (d == -1 and o > stop_px):
            tr.at[i, "exit_px"] = o
            tr.at[i, "stop_gap_repriced"] = True
    tr["pnl_pts"] = (tr["exit_px"] - tr["entry_px"]) * tr["entry_dir"]
    tr["pnl_pts_raw"] = (tr["exit_px_raw"] - tr["entry_px"]) * tr["entry_dir"]
    return tr


# ------------------------------------------------------------------ economics
def add_economics(tr: pd.DataFrame) -> pd.DataFrame:
    tr = tr.copy()
    tr["gross_usd"] = tr["pnl_pts"] * NQ_MULT
    tr["net_usd"] = tr["gross_usd"] - COST_RT
    tr["net_usd_raw"] = tr["pnl_pts_raw"] * NQ_MULT - COST_RT
    # decomposition
    d = tr["entry_dir"]
    confirmed = tr["confirmed"].fillna(False).astype(bool)
    has_cpx = tr["confirm_px"].notna()
    pre = np.where(confirmed & has_cpx,
                   (tr["confirm_px"] - tr["entry_px"]) * d,
                   (tr["exit_px"] - tr["entry_px"]) * d)
    post = np.where(confirmed & has_cpx,
                    (tr["exit_px"] - tr["confirm_px"]) * d, 0.0)
    tr["pre_flip_pnl_usd"] = pre * NQ_MULT
    tr["post_flip_pnl_usd"] = post * NQ_MULT
    tr["month"] = pd.to_datetime(tr["entry_fill_ts"], unit="ns",
                                 utc=True).dt.to_period("M").astype(str)
    return tr


def max_drawdown(net: pd.Series) -> float:
    eq = net.cumsum()
    return float((eq - eq.cummax()).min()) if len(eq) else 0.0


def policy_metrics(g: pd.DataFrame) -> dict:
    comp = g[g["exit_reason"] != "data_end_censored"]
    n = len(comp)
    if n == 0:
        return {"n_trades": 0, "n_censored": int(len(g) - n)}
    pre_flip_kind = comp["pre_flip"].fillna(False).astype(bool)
    confirmed = comp["confirmed"].fillna(False).astype(bool)
    m = {
        "n_trades": n,
        "n_censored": int(len(g) - n),
        "stop_before_flip_rate":
            float((comp["exit_reason"] == "stop_before_flip").mean()),
        "flip_confirmation_rate":
            float(confirmed[pre_flip_kind].mean()) if pre_flip_kind.any()
            else np.nan,
        "stop_after_flip_rate":
            float((comp["exit_reason"] == "stop_after_flip").mean()),
        "d10_exit_rate": float((comp["exit_reason"] == "d10_exit").mean()),
        "opposite_flip_exit_rate":
            float((comp["exit_reason"] == "opposite_regime_flip_exit").mean()),
        "win_rate": float((comp["net_usd"] > 0).mean()),
        "gross_usd": float(comp["gross_usd"].sum()),
        "net_usd": float(comp["net_usd"].sum()),
        "net_usd_raw": float(comp["net_usd_raw"].sum()),
        "ev_per_trade": float(comp["net_usd"].mean()),
        "ev_per_trade_raw": float(comp["net_usd_raw"].mean()),
        "profit_factor":
            float(comp.loc[comp["net_usd"] > 0, "net_usd"].sum()
                  / max(1e-9, -comp.loc[comp["net_usd"] < 0, "net_usd"].sum())),
        "max_drawdown_usd": max_drawdown(
            comp.sort_values("exit_fill_ts")["net_usd"]),
        "median_trade_usd": float(comp["net_usd"].median()),
        "p10_trade_usd": float(comp["net_usd"].quantile(0.10)),
        "p90_trade_usd": float(comp["net_usd"].quantile(0.90)),
        "avg_pre_flip_pnl_usd": float(comp["pre_flip_pnl_usd"].mean()),
        "median_pre_flip_pnl_usd": float(comp["pre_flip_pnl_usd"].median()),
        "avg_post_flip_pnl_usd": float(comp["post_flip_pnl_usd"].mean()),
        "median_post_flip_pnl_usd": float(comp["post_flip_pnl_usd"].median()),
        "avg_preflip_mae_atr": float(comp["preflip_mae_atr"].mean()),
        "median_preflip_mae_atr": float(comp["preflip_mae_atr"].median()),
        "p90_preflip_mae_atr": float(comp["preflip_mae_atr"].quantile(0.9)),
        "n_stop_gap_repriced": int(comp["stop_gap_repriced"].sum()),
    }
    monthly = comp.groupby("month")["net_usd"].sum()
    m["monthly_positive_rate"] = float((monthly > 0).mean()) if len(monthly) else np.nan
    return m


# --------------------------------------------------------------- audits (§13)
def exit_reason_audit(tr: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for i, t in tr.iterrows():
        errs = []
        if t["exit_reason"] not in EXIT_REASONS:
            errs.append("bad_or_missing_exit_reason")
        if t["exit_reason"] != "data_end_censored":
            if not np.isfinite(t.get("exit_fill_ts") or np.nan):
                errs.append("missing_exit_ts")
            elif t["exit_fill_ts"] < t["entry_fill_ts"]:
                errs.append("exit_before_entry")
        if t["exit_reason"] == "d10_exit":
            if t.get("d10_exit_regime_start") != t.get("confirmed_regime_start"):
                errs.append("d10_exit_wrong_regime")
        if errs:
            rows.append({"trade_id": t["trade_id"],
                         "run_policy": t["run_policy"],
                         "run_stop": t["run_stop"],
                         "run_year": t["run_year"],
                         "errors": ",".join(errs)})
    audit = pd.DataFrame(rows)
    summary = pd.DataFrame([{
        "n_trades": len(tr),
        "n_violations": len(audit),
        "reasons_observed": ",".join(sorted(tr["exit_reason"].dropna().unique())),
    }])
    audit_out = pd.concat([summary.assign(trade_id="SUMMARY"), audit],
                          ignore_index=True) if len(audit) else summary
    audit_out.to_parquet(AUDIT / "exit_reason_completeness_audit.parquet",
                         index=False)
    if len(audit):
        raise SystemExit(f"FAIL-FAST: {len(audit)} exit-reason completeness "
                         f"violations — see audit parquet")
    return audit_out


# ---------------------------------------------------- D10 exit contribution §9
def d10_contribution(tr: pd.DataFrame, bars: dict,
                     cov: pd.DataFrame) -> pd.DataFrame:
    """For P2/P3/P4B trades: actual (D10-or-flip) exit vs pure opposite-flip
    exit on the same trades. Categories separate regimes that were validly
    scored but never crossed D10 from regimes with no valid score at all."""
    cov_idx = cov.set_index("regime_start_ns")
    cov_end = cov_idx["regime_end_ns"]
    cov_scored = cov_idx["validly_scored"]
    rows = []
    sub = tr[tr["run_policy"].isin(["P2", "P3", "P4B"])
             & (tr["exit_reason"] != "data_end_censored")]
    for _, t in sub.iterrows():
        yr = int(t["run_year"])
        ts, opens, closes = bars[yr]
        conf_start = t.get("confirmed_regime_start")
        cat = None
        flip_px = np.nan
        extra_mfe = np.nan
        if not t["confirmed"] or pd.isna(conf_start):
            cat = "stopped_before_confirmation"
        else:
            end = cov_end.get(int(conf_start), np.nan)
            if not np.isfinite(end):
                cat = "confirmed_regime_end_unknown"
            else:
                j = np.searchsorted(ts, int(end), side="left") - 1
                if j >= 0:
                    flip_px = float(closes[j])
                if t["exit_reason"] == "d10_exit":
                    # favorable excursion foregone between D10 exit and flip
                    a = np.searchsorted(ts, int(t["exit_fill_ts"]), side="left")
                    b = np.searchsorted(ts, int(end), side="left")
                    if b > a:
                        d = int(t["entry_dir"])
                        seg = closes[a:b]
                        extra = (np.max(seg) - t["exit_px"]) if d == 1 \
                            else (t["exit_px"] - np.min(seg))
                        extra_mfe = float(extra)
                    cat = "d10_exit"
                elif t["exit_reason"] == "opposite_regime_flip_exit":
                    scored = bool(cov_scored.get(int(conf_start), False))
                    cat = ("no_d10_before_flip" if scored
                           else "score_unavailable")
                elif t["exit_reason"] == "stop_after_flip":
                    cat = "stopped_after_confirmation"
        d = int(t["entry_dir"])
        pnl_actual = (t["exit_px"] - t["entry_px"]) * d * NQ_MULT
        pnl_flip = ((flip_px - t["entry_px"]) * d * NQ_MULT
                    if np.isfinite(flip_px) else np.nan)
        rows.append({
            "trade_id": t["trade_id"], "run_policy": t["run_policy"],
            "run_stop": t["run_stop"], "run_year": yr,
            "category": cat,
            "exit_reason": t["exit_reason"],
            "pnl_actual_usd": pnl_actual,
            "pnl_flip_exit_usd": pnl_flip,
            "incremental_usd": (pnl_actual - pnl_flip
                                if np.isfinite(pnl_flip) else np.nan),
            "post_d10_extra_favorable_pts": extra_mfe,
            "d10_improved": (pnl_actual > pnl_flip
                             if np.isfinite(pnl_flip)
                             and t["exit_reason"] == "d10_exit" else None),
        })
    return pd.DataFrame(rows)


# ------------------------------------------------------------------- placebo
def placebo_tests(tr: pd.DataFrame) -> pd.DataFrame:
    rows = []
    pairs = [("P1", "P4A"), ("P3", "P4B")]
    for real_pol, plc_pol in pairs:
        for stop in STOP_GRID:
            for yr in ECON_WINDOWS:
                r = tr[(tr["run_policy"] == real_pol) & (tr["run_stop"] == stop)
                       & (tr["run_year"] == yr)
                       & (tr["exit_reason"] != "data_end_censored")]["net_usd"]
                p = tr[(tr["run_policy"] == plc_pol) & (tr["run_stop"] == stop)
                       & (tr["run_year"] == yr)
                       & (tr["exit_reason"] != "data_end_censored")]["net_usd"]
                if len(r) < 10 or len(p) < 10:
                    continue
                t_w = stats.ttest_ind(r, p, equal_var=False)
                u = stats.mannwhitneyu(r, p, alternative="two-sided")
                rows.append({
                    "real_policy": real_pol, "placebo_policy": plc_pol,
                    "stop": stop, "year": yr,
                    "n_real": len(r), "n_placebo": len(p),
                    "real_ev": float(r.mean()), "placebo_ev": float(p.mean()),
                    "ev_diff": float(r.mean() - p.mean()),
                    "welch_t": float(t_w.statistic),
                    "welch_p": float(t_w.pvalue),
                    "mannwhitney_p": float(u.pvalue),
                })
    return pd.DataFrame(rows)


# ------------------------------------------------------------ tail dependence
def tail_dependence(tr: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (pol, stop, yr), g in tr[tr["exit_reason"] != "data_end_censored"] \
            .groupby(["run_policy", "run_stop", "run_year"]):
        net = g["net_usd"].sort_values(ascending=False)
        total = net.sum()
        n10 = max(1, int(len(net) * 0.1))
        rows.append({
            "run_policy": pol, "run_stop": stop, "run_year": yr,
            "n": len(net), "net_total": float(total),
            "net_excl_top1": float(total - net.iloc[:1].sum()),
            "net_excl_top5": float(total - net.iloc[:5].sum()),
            "net_excl_top10": float(total - net.iloc[:10].sum()),
            "net_excl_top_decile": float(total - net.iloc[:n10].sum()),
            "top_decile_share":
                float(net.iloc[:n10].sum() / total) if total != 0 else np.nan,
        })
    return pd.DataFrame(rows)


# ------------------------------------------------------------------- main
def main() -> None:
    thr_info = load_frozen_threshold()
    tr, timing, same_ts, skips = load_runs()
    if len(tr) == 0:
        raise SystemExit("No NT runs found under _work/nt_runs/")
    bars = load_1s_opens()
    cov = pd.read_parquet(RESULTS / "regime_d10_coverage.parquet")
    events = pd.read_parquet(RESULTS / "d10_entry_events.parquet")

    # ---- fail-fast runtime parity gates (audit pass-2 CRITICAL) ----
    # 1. runtime (catalog-fed) flip stream must exactly match the offline
    #    (raw-fed) regime table; 2. zero score-lookup regime mismatches.
    flip_rows = []
    for d in sorted(NT_RUNS.iterdir()):
        meta = json.loads((d / "meta.json").read_text())
        if meta["mismatch_count"] != 0:
            # Placebo donors on quiet seconds can dispatch just after their
            # donor regime flipped — those must be SKIPPED (benign) and each
            # must appear in the skip log; anything else is identity drift.
            n_stale = 0
            skp = d / "skips.parquet"
            if meta["policy"].startswith("P4") and skp.exists():
                sk = pd.read_parquet(skp)
                if len(sk):
                    n_stale = int((sk["reason"] == "placebo_regime_mismatch").sum())
            if meta["mismatch_count"] != n_stale:
                raise SystemExit(
                    f"FAIL-FAST: {meta['mismatch_count']} regime mismatches "
                    f"in {d.name} but only {n_stale} skip-logged stale "
                    f"placebo triggers")
        fp = d / "flips.parquet"
        if fp.exists():
            f = pd.read_parquet(fp)
            if len(f):
                f["year"] = meta["year"]
                flip_rows.append(f[["year", "flip_ts", "direction"]])
    if flip_rows:
        rt = pd.concat(flip_rows, ignore_index=True).drop_duplicates()
        for yr in ECON_WINDOWS:
            rt_set = set(map(tuple, rt[rt["year"] == yr]
                             [["flip_ts", "direction"]].to_numpy()))
            off = cov[(cov["year"] == yr)]
            off_set = set(zip(off["regime_start_ns"].astype(np.int64),
                              off["direction"].astype(int)))
            missing = off_set - rt_set
            extra = rt_set - off_set
            if missing or extra:
                raise SystemExit(
                    f"FAIL-FAST: runtime/offline flip divergence {yr}: "
                    f"{len(missing)} offline-only, {len(extra)} runtime-only")
    print("Runtime/offline flip parity: exact match both years.")

    tr = reprice_stops(tr, bars)
    tr = add_economics(tr)

    # confirm_px 1s-dispatch-order check (audit pass-2 W3): lag 0 proves the
    # 1s bar ending at the flip boundary processed before the 1m flip. Lag>0
    # is legitimate sparse data (no trade in the final seconds of the flip
    # minute — confirm_px is still the venue's executable last price). The
    # pathological wrong-dispatch-order signature is lag 0 NEVER occurring.
    if "confirm_px_lag_s" in tr.columns:
        lag = tr["confirm_px_lag_s"].dropna()
        if len(lag) > 100 and int((lag == 0).sum()) == 0:
            raise SystemExit("FAIL-FAST: no confirmation ever saw the "
                             "boundary 1s bar — 1m-before-1s dispatch order")
        print(f"confirm_px lag: {float((lag == 0).mean()):.1%} exact-boundary,"
              f" median lag {float(lag.median()):.0f}s (sparse-data gaps)")
    tr.to_parquet(RESULTS / "trade_results.parquet", index=False)

    exit_reason_audit(tr)

    # entry timing audit + offline/NT reconciliation
    if len(timing):
        timing["submit_lag_s"] = (timing["submit_proc_ts"]
                                  - timing["signal_obs"]) / 1e9
        # lag == 1s is the dense-data case; lag > 1s is a checkpoint on a
        # quiet second dispatched at the first bar boundary after it (still
        # causal). lag < 1s would be a lookahead — fail-fast.
        bad = timing[timing["pre_flip"] & (timing["submit_lag_s"] < 1.0)]
        lag_p = timing.loc[timing["pre_flip"], "submit_lag_s"]
        if len(lag_p):
            print(f"entry dispatch lag: {(lag_p == 1.0).mean():.1%} at 1s, "
                  f"median {lag_p.median():.0f}s, p95 {lag_p.quantile(.95):.0f}s")
        rec_rows = []
        for yr in ECON_WINDOWS:
            n_off = int((events["year"] == yr).sum())
            for pol in ("P1", "P3"):
                for stop in STOP_GRID:
                    sub = tr[(tr["run_policy"] == pol) & (tr["run_stop"] == stop)
                             & (tr["run_year"] == yr) & (tr["kind"] == "real")]
                    sk = skips[(skips["run_policy"] == pol)
                               & (skips["run_stop"] == stop)
                               & (skips["run_year"] == yr)] if len(skips) else []
                    rec_rows.append({
                        "year": yr, "policy": pol, "stop": stop,
                        "offline_events": n_off, "nt_actioned": len(sub),
                        "nt_skipped": len(sk),
                        "n_bad_submit_lag": len(bad),
                    })
        timing.to_parquet(AUDIT / "entry_timing_audit.parquet", index=False)
        pd.DataFrame(rec_rows).to_parquet(
            AUDIT / "entry_event_reconciliation.parquet", index=False)

        # fail-fast closure: every offline event must be accounted for in
        # each run as an actioned trade, a logged skip, or a same-ts case
        plc_ev = None
        plc_path = WORK / "placebo_events_seed42.parquet"
        if plc_path.exists():
            plc_ev = pd.read_parquet(plc_path)
        for d in sorted(NT_RUNS.iterdir()):
            meta = json.loads((d / "meta.json").read_text())
            pol, yr = meta["policy"], meta["year"]
            if pol in ("P0", "P2"):
                continue
            if pol.startswith("P4"):
                want = set(plc_ev.loc[plc_ev["year"] == yr, "d10_obs_time"]
                           .astype(np.int64)) if plc_ev is not None else set()
            else:
                want = set(events.loc[events["year"] == yr, "d10_obs_time"]
                           .astype(np.int64))
            seen: set = set()
            t_df = pd.read_parquet(d / "trades.parquet")
            if len(t_df):
                seen |= set(t_df["signal_obs"].astype(np.int64))
                # a confirmed-regime first crossing consumed as a D10 exit
                # is a legitimately-accounted offline event (P3/P4B)
                if "d10_exit_obs" in t_df.columns:
                    seen |= set(t_df["d10_exit_obs"].dropna().astype(np.int64))
            for name in ("skips", "same_ts"):
                p = d / f"{name}.parquet"
                if p.exists():
                    s_df = pd.read_parquet(p)
                    col = "obs"
                    if len(s_df) and col in s_df.columns:
                        seen |= set(s_df[col].dropna().astype(np.int64))
            missing = want - seen
            if missing:
                raise SystemExit(f"FAIL-FAST: {len(missing)} offline events "
                                 f"unaccounted for in {d.name}")
        print("Offline-event closure: every event actioned/skipped/logged "
              "in every run.")
        if len(bad):
            raise SystemExit(f"FAIL-FAST: {len(bad)} pre-flip entries with "
                             f"submit lag < 1s (lookahead)")
    if len(same_ts):
        same_ts.to_parquet(AUDIT / "same_timestamp_exit_audit.parquet",
                           index=False)
    else:
        pd.DataFrame().to_parquet(AUDIT / "same_timestamp_exit_audit.parquet")

    # policy / stop-sensitivity / monthly / segment results
    pol_rows = []
    for (pol, stop, yr), g in tr.groupby(["run_policy", "run_stop", "run_year"]):
        m = policy_metrics(g)
        m.update({"policy": pol, "stop": stop, "year": yr})
        pol_rows.append(m)
    pol_df = pd.DataFrame(pol_rows)
    pol_df.to_parquet(RESULTS / "policy_results.parquet", index=False)
    pol_df[pol_df["policy"].isin(["P1", "P3", "P4A", "P4B"])].to_parquet(
        RESULTS / "stop_sensitivity.parquet", index=False)

    comp = tr[tr["exit_reason"] != "data_end_censored"]
    monthly = comp.groupby(["run_policy", "run_stop", "run_year", "month"]) \
        .agg(n=("net_usd", "size"), net_usd=("net_usd", "sum"),
             win_rate=("net_usd", lambda x: float((x > 0).mean()))) \
        .reset_index()
    monthly.to_parquet(RESULTS / "monthly_results.parquet", index=False)

    from studies.fable5_pre_flip_d10_reversal_entry.common import is_rth
    comp2 = comp.copy()
    comp2["session"] = np.where(
        is_rth(comp2["entry_fill_ts"].to_numpy(dtype=np.int64)), "RTH", "ETH")
    seg_frames = []
    for key in ["entry_dir", "session"]:
        s = comp2.groupby(["run_policy", "run_stop", "run_year", key]) \
            .agg(n=("net_usd", "size"), net_usd=("net_usd", "sum"),
                 ev=("net_usd", "mean")).reset_index() \
            .rename(columns={key: "segment_value"})
        s["segment_value"] = s["segment_value"].astype(str)
        s.insert(3, "segment", key)
        seg_frames.append(s)
    pd.concat(seg_frames, ignore_index=True).to_parquet(
        RESULTS / "segment_results.parquet", index=False)

    # decomposition file (§8)
    dec = comp[comp["run_policy"].isin(["P1", "P3", "P4A", "P4B"])][[
        "trade_id", "run_policy", "run_stop", "run_year", "kind",
        "entry_dir", "confirmed", "exit_reason", "entry_px", "confirm_px",
        "exit_px", "pre_flip_pnl_usd", "post_flip_pnl_usd", "net_usd",
        "preflip_mae_atr", "preflip_mfe_atr", "postflip_mae_atr",
        "postflip_mfe_atr", "signal_obs", "confirm_flip_ts",
    ]].copy()
    dec.to_parquet(RESULTS / "pnl_decomposition.parquet", index=False)

    # D10 exit contribution (§9)
    contrib = d10_contribution(tr, bars, cov)
    contrib.to_parquet(RESULTS / "d10_exit_contribution.parquet", index=False)
    csum = contrib.groupby(["run_policy", "run_stop", "run_year", "category"]) \
        .agg(n=("trade_id", "size"),
             mean_incremental_usd=("incremental_usd", "mean"),
             total_incremental_usd=("incremental_usd", "sum")).reset_index()
    csum.to_parquet(RESULTS / "d10_exit_reason_summary.parquet", index=False)

    # runner capture (§9/§15)
    rc = contrib[contrib["category"] == "d10_exit"].groupby(
        ["run_policy", "run_stop", "run_year"]).agg(
        n_d10_exits=("trade_id", "size"),
        mean_foregone_pts=("post_d10_extra_favorable_pts", "mean"),
        p90_foregone_pts=("post_d10_extra_favorable_pts",
                          lambda x: x.quantile(0.9)),
        mean_incremental_usd=("incremental_usd", "mean"),
        pct_improved=("d10_improved", lambda x: float(pd.Series(x).mean())),
    ).reset_index()
    rc.to_parquet(RESULTS / "runner_capture.parquet", index=False)

    # placebo + tail
    plc = placebo_tests(tr)
    plc.to_parquet(RESULTS / "matched_placebo_summary.parquet", index=False)
    tail = tail_dependence(tr)
    tail.to_parquet(RESULTS / "tail_dependence.parquet", index=False)

    print("Wrote all result artifacts.")
    print(pol_df[["policy", "stop", "year", "n_trades", "ev_per_trade",
                  "net_usd", "win_rate"]].to_string(index=False))


if __name__ == "__main__":
    main()
