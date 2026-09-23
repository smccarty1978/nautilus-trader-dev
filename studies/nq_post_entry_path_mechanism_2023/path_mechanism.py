"""Post-entry path mechanism discovery -- 2023 DEVELOPMENT sessions only (first 80%); no model of any kind.

  timeline  build the causal per-trade event timeline + checkpoint / event-anchored state from the audited
            frame and the raw 1s catalog; parity-check every reconstructed primitive against the audited
            kernel outputs; write the frozen ANALYSIS_PLAN (groups, checkpoints, variables, subsets,
            decision rule) BEFORE any group comparison is computed.
  analyze   descriptive group comparisons under the frozen plan.

Entry is NEVER redefined: every excursion is measured from the original T0 executable entry price, in
atr_entry_1m (the audited outcome ATR). The final 20% of 2023 sessions is never loaded (bars or rows).

    python studies/nq_post_entry_path_mechanism_2023/path_mechanism.py timeline|analyze
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))

from research.analysis.diagnostic_ops import globex_trading_day  # noqa: E402

OUT = HERE / "artifacts"
ROOT, BASE = REPO.parent, REPO.name.split("-")[0]
MERGED = ROOT / f"{BASE}-nq_mtf_structural_predictive_ranking" / "studies" / "nq_mtf_structural_predictive_ranking" / "_work" / "controller" / "merged"
CONSTRAINED = ROOT / f"{BASE}-nq_target_a_constrained_stationary_2023" / "studies" / "nq_target_a_constrained_stationary_2023" / "artifacts"
DEVSTUDY = ROOT / f"{BASE}-nq_t0_development_reach_2023" / "studies" / "nq_t0_development_reach_2023" / "artifacts"
ATLAS = ROOT / f"{BASE}-nq_mtf_regime_structural_geometry_atlas" / "studies" / "nq_mtf_regime_structural_geometry_atlas" / "artifacts"
CATALOG = Path("C:/Users/Scott McCarty/Projects/Nautilus Trader/data/catalog/NQ_1S_V2_GLOBEX")
BAR_TYPE = "NQ.XCME-1-SECOND-LAST-EXTERNAL"
KEY = ["observation_ts", "regime_start_ns", "checkpoint_index"]
NS = 1_000_000_000
EXPECT_SHA = {"candidates.parquet": "475209b46caf48b674d66833f56005c8fc6c6436f34c8aa50626da7d07300842",
              "observations.parquet": "98e03dc4a2cf01b44d05c45d84b81af5768848142216945cfd133e13d66303b6"}
MAX_GAP_NS = 300 * NS

FAV = [0.5, 1.0, 1.5, 2.0, 3.0]
ADV = [0.5, 1.0]
ARM = {("fav", 0.5): "fp_fav_0p50", ("fav", 1.0): "fp_fav_1p00", ("fav", 1.5): "fp_fav_1p50", ("fav", 2.0): "fp_fav_2p00",
       ("fav", 3.0): "fp_fav_3p00", ("adv", 0.5): "fp_adv_0p50", ("adv", 1.0): "fp_adv_1p00"}
TFS = ["5m", "15m", "1h"]
# canonical collector checkpoints: observation k is 15*(k+1) s after the 1m flip; T0 = k 0 -> elapsed 15*k s
CHECKPOINTS_S = [0, 30, 60, 120, 180, 285]      # k = 0, 2, 4, 8, 12, 19 (285 s = last canonical checkpoint)
BOOT_REPS, BOOT_SEED = 1000, 20260925


def sha_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _jsonable(v):
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.floating):
        return None if not np.isfinite(v) else float(v)
    if isinstance(v, np.bool_):
        return bool(v)
    if isinstance(v, np.ndarray):
        return v.tolist()
    raise TypeError(type(v))


def write_json(name, payload) -> str:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(payload, indent=2, sort_keys=True, default=_jsonable) + "\n", encoding="utf-8")
    return sha_file(OUT / name)


def write_table(name, df) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT / f"{name}.csv", index=False)
    df.to_parquet(OUT / f"{name}.parquet", index=False)


def lbl(x: float) -> str:
    return f"{x:.1f}".replace(".", "p")


# ----------------------------------------------------------------------------- frame (development sessions only)
def load_dev():
    if {n: sha_file(MERGED / n) for n in EXPECT_SHA} != EXPECT_SHA:
        raise SystemExit("INVALID_EXPERIMENT: audited frame hash differs")
    split = json.loads((CONSTRAINED / "TEMPORAL_SPLIT_2023.json").read_text(encoding="utf-8"))
    dev_sessions = set(split["blocks"]["development_train"]["session_list"]) | set(split["blocks"]["development_validation"]["session_list"])
    c = pd.read_parquet(MERGED / "candidates.parquet")
    o = pd.read_parquet(MERGED / "observations.parquet")
    dup = [col for col in o.columns if col in c.columns and col not in KEY]
    f = c.merge(o.drop(columns=dup), on=KEY, how="inner")
    f = f[pd.to_datetime(f["observation_ts"], unit="ns", utc=True).dt.year == 2023]
    f["session"] = globex_trading_day(f["observation_ts"])
    f = f[f["session"].isin(dev_sessions)].copy()          # final 20% and 2024 never pass this line
    t0 = f[f["checkpoint_index"] == 0].copy()
    t0["bound_ts"] = np.where(t0["terminal_flip_disposition"] == "LABELED_POSITIVE", t0["terminal_flip_ts"],
                              np.where(t0["terminal_flip_censor_reason"] == "SESSION_END", t0["session_close_ts"], np.nan))
    g = t0["terminal_gross_pnl_atr"]
    pop = t0[g.notna()].copy()
    pop["win"] = (pop["terminal_gross_pnl_atr"] > 0).astype(int)
    return f, pop, split


# ----------------------------------------------------------------------------- regime chains
def build_links(f: pd.DataFrame, tf: str):
    dir_of, link, conflicts = {}, {}, 0
    for s, dcur, ps, pdir in f[[f"start_ns_{tf}", f"dir_{tf}", f"prior_start_ns_{tf}", f"prior_dir_{tf}"]].itertuples(index=False):
        for k, v in ((s, dcur), (ps, pdir)):
            if pd.isna(k):
                continue
            if int(k) in dir_of and dir_of[int(k)] != v:
                conflicts += 1
            dir_of[int(k)] = v
        if not pd.isna(ps):
            if int(s) in link and link[int(s)] != int(ps):
                conflicts += 1
            link[int(s)] = int(ps)
    return dir_of, link, conflicts


def chain_for(obs_ts, obs_start, dir_of, link, s0, T):
    """Regimes (start, dir) current at some point in [T0, T]: walk back from the first observation >= T."""
    j = int(np.searchsorted(obs_ts, T, side="left"))
    if j >= len(obs_ts):
        return None, "NO_OBSERVATION_AFTER_TERMINAL_IN_SESSION"
    cur, chain = int(obs_start[j]), []
    while cur > s0:
        chain.append(cur)
        if cur not in link:
            return None, "CHAIN_BROKEN"
        cur = link[cur]
    if cur != s0:
        return None, "CHAIN_INCONSISTENT"
    chain.append(s0)
    chain = sorted(c for c in chain if c <= T)
    return [(c, dir_of[c]) for c in chain], "EXACT"


def state_at(chain, t):
    """Direction and start of the regime current at time t (start <= t: a regime is known at its detection close)."""
    starts = [c for c, _ in chain]
    i = int(np.searchsorted(starts, t, side="right")) - 1
    return chain[i]


# ----------------------------------------------------------------------------- timeline stage
def stage_timeline() -> None:
    from utils.runner.data import CausalDataLoader
    f, pop, split = load_dev()
    links = {tf: build_links(f, tf) for tf in TFS}
    fs = f.sort_values("observation_ts")
    obs = {tf: {k: (g["observation_ts"].to_numpy(), g[f"start_ns_{tf}"].to_numpy()) for k, g in fs.groupby("session")} for tf in TFS}
    loader = CausalDataLoader(CATALOG)

    tl_rows, cp_rows, ev_rows, chains = [], [], [], {}
    parity = {f"{s}_{lbl(x)}": {"compared": 0, "mismatch": 0} for s, xs in (("fav", FAV), ("adv", ADV)) for x in xs}
    parity["entry_price"] = {"compared": 0, "mismatch": 0}
    for sess, part in pop.groupby("session"):
        start = pd.Timestamp(int(part["observation_ts"].min()), tz="UTC") - pd.Timedelta(seconds=5)
        end = pd.Timestamp(int(part["session_close_ts"].max()), tz="UTC") + pd.Timedelta(seconds=5)
        bars = loader.load_bars(BAR_TYPE, start, end)
        ti = np.fromiter((b.ts_init for b in bars), dtype=np.int64, count=len(bars))
        te = np.fromiter((b.ts_event for b in bars), dtype=np.int64, count=len(bars))
        op = np.fromiter((b.open.as_double() for b in bars), dtype=float, count=len(bars))
        hi = np.fromiter((b.high.as_double() for b in bars), dtype=float, count=len(bars))
        lo = np.fromiter((b.low.as_double() for b in bars), dtype=float, count=len(bars))
        cl = np.fromiter((b.close.as_double() for b in bars), dtype=float, count=len(bars))
        for r in part.itertuples():
            T0, T, d, atr = int(r.observation_ts), int(r.bound_ts), int(r.dir_1m), float(r.atr_entry_1m)
            close_ns = int(r.session_close_ts)
            i0 = int(np.searchsorted(ti, T0, side="right"))
            iend = int(np.searchsorted(ti, close_ns, side="right"))         # bars closing at or before the session close
            ep, ets = op[i0], int(te[i0])
            parity["entry_price"]["compared"] += 1
            parity["entry_price"]["mismatch"] += int(ep != r.executable_entry_price or ets != r.executable_entry_ts)
            sti, sh, sl, sc = ti[i0:iend], hi[i0:iend], lo[i0:iend], cl[i0:iend]
            gaps = np.diff(np.concatenate([[ets], sti]))
            gap_idx = np.flatnonzero(gaps > MAX_GAP_NS)
            first_gap = int(gap_idx[0]) if len(gap_idx) else len(sti)
            fav_x = (sh - ep) / atr if d > 0 else (ep - sl) / atr          # per-bar favourable excursion (A)
            adv_x = (ep - sl) / atr if d > 0 else (sh - ep) / atr
            rec = {"regime_start_ns": r.regime_start_ns, "session": sess, "dir": d, "t0_ns": T0, "entry_ts": ets,
                   "entry_price": ep, "atr": atr, "terminal_ts": T, "win": int(r.win), "terminal_gross_atr": float(r.terminal_gross_pnl_atr)}
            touch = {}
            for side, xs in (("fav", FAV), ("adv", ADV)):
                for x in xs:
                    lvl = ep + d * x * atr if side == "fav" else ep - d * x * atr        # kernel level arithmetic
                    hit = ((sh >= lvl) if d > 0 else (sl <= lvl)) if side == "fav" else ((sl <= lvl) if d > 0 else (sh >= lvl))
                    idx = np.flatnonzero(hit[:first_gap])
                    t_hit = int(sti[idx[0]]) if len(idx) else None
                    touch[(side, x)] = t_hit
                    # parity vs the audited kernel resolution (all resolved rows, before or after the terminal flip)
                    arm = ARM[(side, x)]
                    disp = getattr(r, f"{arm}_disposition")
                    want = "POSITIVE" if side == "fav" else "NEGATIVE"
                    key = f"{side}_{lbl(x)}"
                    parity[key]["compared"] += 1
                    if disp == want:
                        parity[key]["mismatch"] += int(t_hit is None or (t_hit - ets) / NS != getattr(r, f"{arm}_resolution_seconds"))
                    else:
                        parity[key]["mismatch"] += int(t_hit is not None)
                    before = t_hit is not None and t_hit < T
                    rec[f"t_{key}"] = (t_hit - T0) / NS if before else np.nan        # seconds after T0, before terminal only
                    rec[f"reach_{key}"] = int(before)
            # MTF chains
            ok = True
            for tf in TFS:
                dir_of, link, _ = links[tf]
                ch, status = chain_for(*obs[tf][sess], dir_of, link, int(getattr(r, f"start_ns_{tf}")), T)
                rec[f"chain_{tf}"] = status
                if ch is None:
                    ok = False
                    continue
                chains[(r.regime_start_ns, tf)] = ch
                d0 = ch[0][1] if ch[0][0] <= T0 else None
                rec[f"aligned_T0_{tf}"] = int(state_at(ch, T0)[1] == d)
                inside = [(s, dd) for s, dd in ch if T0 < s < T]
                rec[f"n_trans_{tf}"] = len(inside)
                if inside:
                    rec[f"t_first_trans_{tf}"] = (inside[0][0] - T0) / NS
                    rec[f"first_trans_into_{tf}"] = int(inside[0][1] == d)
                into = [s for s, dd in inside if dd == d]
                rec[f"t_first_into_{tf}"] = (into[0] - T0) / NS if into else np.nan
            rec["chains_exact"] = int(ok)
            tl_rows.append(rec)

            # clock checkpoints (information through c: bars with ts_init <= c, regimes with start <= c)
            prev = None
            for e in CHECKPOINTS_S:
                c = T0 + e * NS
                n = int(np.searchsorted(sti[:first_gap], c, side="right"))
                mfe = float(fav_x[:n].max()) if n else 0.0
                mae = float(adv_x[:n].max()) if n else 0.0
                cur = float(((sc[n - 1] - ep) * d) / atr) if n else 0.0
                cp = {"regime_start_ns": r.regime_start_ns, "elapsed_s": e, "alive": int(T > c), "mfe": max(mfe, 0.0),
                      "mae": max(mae, 0.0), "cur": cur}
                cp["fav_share"] = cp["mfe"] / (cp["mfe"] + cp["mae"]) if (cp["mfe"] + cp["mae"]) > 0 else 0.5
                cp["mfe_rate"] = cp["mfe"] / (e / 60) if e else 0.0
                cp["mae_rate"] = cp["mae"] / (e / 60) if e else 0.0
                cp["d_mfe"] = cp["mfe"] - prev["mfe"] if prev else 0.0
                cp["d_mae"] = cp["mae"] - prev["mae"] if prev else 0.0
                cp["fav_expand_adv_stall"] = int(cp["d_mfe"] > 0 and cp["d_mae"] == 0) if prev else 0
                cp["adv_expand_fav_stall"] = int(cp["d_mae"] > 0 and cp["d_mfe"] == 0) if prev else 0
                for tf in TFS:
                    ch = chains.get((r.regime_start_ns, tf))
                    if ch is None:
                        cp[f"aligned_{tf}"] = np.nan
                        cp[f"trans_{tf}"] = np.nan
                        cp[f"s_since_trans_{tf}"] = np.nan
                        continue
                    s_now, d_now = state_at(ch, c)
                    cp[f"aligned_{tf}"] = int(d_now == d)
                    cp[f"trans_{tf}"] = int(s_now > T0)
                    cp[f"s_since_trans_{tf}"] = (c - s_now) / NS if s_now > T0 else np.nan
                cp["n_htf_aligned"] = np.nansum([cp[f"aligned_{tf}"] for tf in TFS]) if ok else np.nan
                cp_rows.append(cp)
                prev = cp

            # event-anchored state at first touch of +0.5/+1/+1.5/+2 (information through the touch bar)
            for x in (0.5, 1.0, 1.5, 2.0):
                t_hit = touch[("fav", x)]
                if t_hit is None or t_hit >= T:
                    continue
                n = int(np.searchsorted(sti, t_hit, side="right"))
                ev = {"regime_start_ns": r.regime_start_ns, "event": f"fav_{lbl(x)}", "t_since_t0_s": (t_hit - T0) / NS,
                      "mae_through_touch": max(float(adv_x[:n].max()), 0.0),
                      "adv0p5_before": int(touch[("adv", 0.5)] is not None and touch[("adv", 0.5)] <= t_hit),
                      "adv1_before": int(touch[("adv", 1.0)] is not None and touch[("adv", 1.0)] <= t_hit)}
                prev_x = {0.5: None, 1.0: 0.5, 1.5: 1.0, 2.0: 1.5}[x]
                ev["s_from_prev_level"] = (t_hit - touch[("fav", prev_x)]) / NS if prev_x else (t_hit - T0) / NS
                for tf in TFS:
                    ch = chains.get((r.regime_start_ns, tf))
                    if ch is None:
                        ev[f"aligned_{tf}"] = np.nan
                        ev[f"trans_{tf}"] = np.nan
                        continue
                    s_now, d_now = state_at(ch, t_hit)
                    ev[f"aligned_{tf}"] = int(d_now == d)
                    ev[f"trans_{tf}"] = int(s_now > T0)
                ev_rows.append(ev)

    tl = pd.DataFrame(tl_rows)
    cp = pd.DataFrame(cp_rows)
    ev = pd.DataFrame(ev_rows)
    # parity 2: chain-derived MTF directions vs every audited candidate checkpoint row of the trade
    mtf_par = {tf: {"compared": 0, "mismatch": 0} for tf in TFS}
    rows = f[f["regime_start_ns"].isin(tl["regime_start_ns"])]
    for rs, g in rows.groupby("regime_start_ns"):
        for tf in TFS:
            ch = chains.get((rs, tf))
            if ch is None:
                continue
            for ts, dd in g[["observation_ts", f"dir_{tf}"]].itertuples(index=False):
                if ts > ch[-1][0] and ts > int(tl.loc[tl.regime_start_ns == rs, "terminal_ts"].iloc[0]):
                    continue
                mtf_par[tf]["compared"] += 1
                mtf_par[tf]["mismatch"] += int(state_at(ch, int(ts))[1] != dd)
    # parity 3: reach-before-terminal equals the audited label (development rows of the prior study)
    lab = pd.read_parquet(DEVSTUDY / "labels.parquet")
    j = tl.merge(lab, on="regime_start_ns", how="left")
    label_par = {k: int((j[f"reach_{k}"] != j[v]).sum()) for k, v in (("fav_2p0", "fav2"), ("fav_3p0", "fav3"), ("adv_0p5", "adv0p5"), ("adv_1p0", "adv1"))}
    label_par["win_vs_target_A"] = int((j["win"] != j["target_A"]).sum())
    label_par["f5_into_vs_prior_label_on_exact"] = int(((~j["t_first_into_5m"].isna()).astype(int) != j["f5_label"])[j["f5_status"] == "EXACT"].sum())
    conflicts = {tf: links[tf][2] for tf in TFS}
    total = sum(v["mismatch"] for v in parity.values()) + sum(v["mismatch"] for v in mtf_par.values()) + sum(label_par.values()) + sum(conflicts.values())
    audit = {"kind": "trade_path_timeline_audit", "population": "2023 development sessions (first 80%, 205 sessions), audited Target-A-eligible T0 trades",
             "n_trades": len(tl), "sessions": int(tl["session"].nunique()), "final_20pct_loaded": False, "years_touched": [2023],
             "entry_definition": "original T0 executable entry: OPEN of the first 1s bar with ts_init > T0 observation; entry instant = that bar's ts_event; unchanged",
             "atr": "atr_entry_1m (audited outcome ATR)",
             "event_semantics": {
                 "price_touch": "first 1s bar (entry bar included) whose HIGH/LOW reaches entry +/- k*ATR (kernel arithmetic); time = that bar's close (ts_init); a >300 s bar gap before the touch censors",
                 "before_terminal": "touch time strictly before the terminal opposite 1m flip (atlas convention)",
                 "htf_transition": "a regime's start_ns = its detection bar close; known at that instant; first transition = first regime starting strictly inside (T0 observation, terminal flip); INTO if its dir == trade dir",
                 "checkpoint_state": "at c = T0 + e: bars with ts_init <= c, regimes with start <= c; e in %s s (canonical collector checkpoints k=0,2,4,8,12,19)" % CHECKPOINTS_S,
                 "event_anchored_state": "at a first-touch bar: bars through that bar (inclusive), regimes with start <= touch time",
                 "ties": "a 5m/15m/1h detection close and a 1s touch bar close at the same second are 'at or before' each other; counted separately"},
             "parity": {"price_first_touch_vs_kernel_resolution_seconds": parity, "mtf_chain_vs_candidate_rows": mtf_par,
                        "labels_vs_prior_audited_labels": label_par, "regime_link_conflicts": conflicts},
             "chain_status": {tf: tl[f"chain_{tf}"].value_counts().to_dict() for tf in TFS},
             "mismatch_total": total, "PASS": total == 0,
             "missing_primitives": ["collector checkpoint rows are gappy (32% of trades miss some k); structural state after T0 is therefore not used -- path state is rebuilt from 1s bars, MTF state from exact regime chains",
                                    "checkpoints stop at 285 s after T0 (collector max_age 300 s)"]}
    write_json("TRADE_PATH_TIMELINE_AUDIT.json", audit)
    write_table("TRADE_EVENT_TIMELINE", tl)
    write_table("CHECKPOINT_STATE", cp)
    write_table("EVENT_ANCHORED_STATE", ev)
    print(json.dumps({k: audit[k] for k in ("n_trades", "sessions", "mismatch_total", "parity", "chain_status")}, indent=1, default=_jsonable))
    if not audit["PASS"]:
        raise SystemExit("INVALID_EXPERIMENT: timeline parity failed")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["timeline", "analyze"])
    {"timeline": stage_timeline}.get(ap.parse_args().stage, lambda: (_ for _ in ()).throw(SystemExit("analyze: plan must be frozen first")))()
