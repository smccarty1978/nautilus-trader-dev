"""Conditional future-value atlas -- 2023 DEVELOPMENT sessions only; descriptive, no model of any kind.

Question: at the same checkpoint and the same current location (P&L from entry), does path history, MTF state or
structural context change the FORWARD distribution measured from the checkpoint price?

Inputs: _work/PATH_EXT.parquet, TRADE_CTX.parquet, CHAINS.parquet (extract.py, all parity-checked), the audited
TRADE_EVENT_TIMELINE, the atlas T0 frame (context), TEMPORAL_SPLIT_2023 (train / validation blocks).

Features at checkpoint c use only bars with t <= c (in-trade) and regimes with start <= T0 + c.
Outcomes use only bars with t > c.
  *_tr   trade-censored: stops at the terminal opposite 1m flip (what the trade experiences)
  *_px   price-only: continues past the terminal flip (up to 1800 s after it, >300 s gap censors) -- isolates price
         information from the mechanics of the flip exit

    python studies/nq_conditional_future_value_2023/future_value.py
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
ROOT, BASE = REPO.parent, REPO.name.split("-")[0]
TL = ROOT / f"{BASE}-nq_post_entry_path_mechanism_2023" / "studies" / "nq_post_entry_path_mechanism_2023" / "artifacts" / "TRADE_EVENT_TIMELINE.parquet"
ATLAS = ROOT / f"{BASE}-nq_mtf_regime_structural_geometry_atlas" / "studies" / "nq_mtf_regime_structural_geometry_atlas" / "artifacts" / "atlas_2023_frame.parquet"
SPLIT = ROOT / f"{BASE}-nq_target_a_constrained_stationary_2023" / "studies" / "nq_target_a_constrained_stationary_2023" / "artifacts" / "TEMPORAL_SPLIT_2023.json"
WORK, OUT = HERE / "_work", HERE / "artifacts"
NS = 1_000_000_000

PRIMARY = [180, 300, 480, 720, 1200]
CHECKPOINTS = [60, 120, *PRIMARY, 1800]
HYST, SWING = 0.10, 0.50
LOC_EDGES = [-np.inf, -1.0, -0.5, -0.25, 0.0, 0.25, 0.5, 0.75, 1.0, 1.5, np.inf]
MIN_STRATUM = 150
MIN_GROUP = 10
B_BOOT, SEED = 400, 20260925
N_PERM = 5
RACES = [(0.25, 0.25), (0.5, 0.25), (0.5, 0.5), (1.0, 0.5)]
T_START = time.time()
TIMINGS: dict[str, float] = {}


def lap(name, t0):
    TIMINGS[name] = round(time.time() - t0, 2)
    return time.time()


NEITHER = -1.0


def race(hi_f, lo_f, a, b, cur):
    """first-passage from the checkpoint price: +a before -b.  1 / 0 / nan (same-bar tie) / NEITHER."""
    up = np.flatnonzero(hi_f >= cur + a - 1e-9)
    dn = np.flatnonzero(lo_f >= b - cur - 1e-9)
    iu = up[0] if len(up) else None
    idn = dn[0] if len(dn) else None
    if iu is None and idn is None:
        return NEITHER
    if iu is not None and idn is not None and iu == idn:
        return np.nan
    return 1.0 if (idn is None or (iu is not None and iu < idn)) else 0.0


# ============================================================================ per-trade reduction
def reduce(tl, p, chains, ctx):
    rows = []
    rs_arr = p.regime_start_ns.to_numpy()
    starts = np.flatnonzero(np.r_[True, rs_arr[1:] != rs_arr[:-1]])
    ends = np.r_[starts[1:], len(rs_arr)]
    T = p.t.to_numpy(np.int64)
    HI, LO, C, V, POST = (p[k].to_numpy() for k in ("hi", "lo", "c", "v", "post"))
    info = tl.set_index("regime_start_ns")
    ch = {(rs, tf): (g.start_ns.to_numpy(), g.dir.to_numpy()) for (rs, tf), g in chains.groupby(["regime_start_ns", "tf"])}
    prevol = ctx.set_index("regime_start_ns").pre_vol_per_s
    for s0, e0 in zip(starts, ends):
        rs = int(rs_arr[s0])
        r = info.loc[rs]
        D, t0ns, d = int(r.D), int(r.t0_ns), int(r.dir)
        t, hi, lo, c, v, post = T[s0:e0], HI[s0:e0].astype(float), LO[s0:e0].astype(float), C[s0:e0].astype(float), V[s0:e0].astype(float), POST[s0:e0]
        k = int((~post).sum())                       # in-trade rows are a prefix
        ti, hii, loi, ci = t[:k], hi[:k], lo[:k], c[:k]
        rmfe = np.maximum.accumulate(np.maximum(hii, 0)) if k else np.zeros(0)
        rmae = np.maximum.accumulate(np.maximum(loi, 0)) if k else np.zeros(0)
        hold = np.maximum(np.diff(np.append(ti, D)).astype(float), 0)
        above = np.concatenate([[0], np.cumsum(hold * (ci > 0))])
        below = np.concatenate([[0], np.cumsum(hold * (ci < 0))])
        plen = np.cumsum(np.abs(np.diff(np.concatenate([[0.0], ci]))))
        maxpb = np.maximum.accumulate(rmfe - ci) if k else np.zeros(0)
        cross = np.zeros(k, np.int32)
        swings = np.zeros(k, np.int32)
        pivot_t = np.zeros(k, np.int64)
        st, nc = 0, 0
        direc, hi_e, lo_e, m, pv = 0, 0.0, 0.0, 0, 0
        for i in range(k):
            x = ci[i]
            s = 1 if x >= HYST else (-1 if x <= -HYST else st)
            if st != 0 and s != st:
                nc += 1
            st = s
            cross[i] = nc
            if direc >= 0:
                hi_e = max(hi_e, x)
            if direc <= 0:
                lo_e = min(lo_e, x)
            if direc >= 0 and hi_e - x >= SWING:
                m += int(direc == 1)
                direc, lo_e, pv = -1, x, ti[i]
            elif direc <= 0 and x - lo_e >= SWING:
                m += int(direc == -1)
                direc, hi_e, pv = 1, x, ti[i]
            swings[i] = m
            pivot_t[i] = pv
        newm = (np.concatenate([[True], rmfe[1:] > rmfe[:-1]]) & (hii > 0)) if k else np.zeros(0, bool)
        last_new = np.maximum.accumulate(np.where(newm, ti, -1)) if k else np.zeros(0, np.int64)
        tch = {tf: ch.get((rs, tf)) for tf in ("5m", "15m", "1h")}

        def dir_at(tf, ts):
            v_ = tch[tf]
            if v_ is None:
                return np.nan
            j = int(np.searchsorted(v_[0], ts, side="right")) - 1
            return float(v_[1][j]) if j >= 0 else np.nan

        a0 = {tf: dir_at(tf, t0ns) for tf in ("5m", "15m", "1h")}
        for cp in CHECKPOINTS:
            if D <= cp:
                break
            i = int(np.searchsorted(ti, cp, side="right")) - 1

            def c_at(s):
                j = int(np.searchsorted(ti, s, side="right")) - 1
                return ci[j] if j >= 0 else 0.0
            if i >= 0:
                cur, mfe, mae = ci[i], rmfe[i], rmae[i]
                ab = above[i] + (cp - ti[i]) * (ci[i] > 0)
                be = below[i] + (cp - ti[i]) * (ci[i] < 0)
                pl, cr, sw, mpb = plen[i], cross[i], swings[i], maxpb[i]
                since = cp - last_new[i] if last_new[i] >= 0 else cp
                sage = cp - pivot_t[i]
            else:
                cur = mfe = mae = ab = be = pl = mpb = 0.0
                cr = sw = 0
                since = sage = cp
            w = (ti > cp - 120) & (ti <= cp)
            rv = float(np.sqrt(np.square(np.diff(ci[w])).sum())) if w.sum() > 1 else 0.0
            vol_ratio = float(V[s0:s0 + k][w].sum() / 120 / prevol.loc[rs]) if prevol.loc[rs] > 0 else np.nan
            rec = {"regime_start_ns": rs, "cp": cp, "cur": cur, "mfe_c": mfe, "mae_c": mae, "pullback_c": mfe - cur, "max_pullback_c": mpb,
                   "cross_c": int(cr), "cross_pm": cr / (cp / 60), "eff_c": cur / pl if pl > 0 else 0.0, "pathlen_pm": pl / (cp / 60),
                   "frac_above": ab / cp, "frac_below": be / cp, "balance": min(ab, be) / cp, "since_new_mfe": since,
                   "ret30": cur - c_at(cp - 30), "ret60": cur - c_at(cp - 60), "ret120": cur - c_at(cp - 120), "swings_c": int(sw),
                   "swing_age": sage, "rv120": rv, "vol_ratio120": vol_ratio, "term_remaining_s": D - cp}
            for x in (0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0):
                rec[f"reached_{x:g}"] = int(mfe >= x - 1e-9)
            n_al, n_ch = 0.0, 0.0
            for tf in ("5m", "15m", "1h"):
                dn = dir_at(tf, t0ns + cp * NS)
                rec[f"aligned_now_{tf}"] = float(dn == d) if not np.isnan(dn) else np.nan
                rec[f"changed_{tf}"] = float(dn != a0[tf]) if not (np.isnan(dn) or np.isnan(a0[tf])) else np.nan
                n_al += rec[f"aligned_now_{tf}"]
                n_ch += rec[f"changed_{tf}"]
            rec["n_aligned_now"] = n_al
            rec["n_changed"] = n_ch
            rec["rel_now"] = "".join("A" if rec[f"aligned_now_{tf}"] == 1 else "O" for tf in ("5m", "15m", "1h")) if not np.isnan(n_al) else None
            # ---- forward outcomes
            ft = t > cp
            fin = ft & ~post
            hf, lf = hi[fin], lo[fin]
            rec["rem_mfe_tr"] = max(float(hf.max()) - cur, 0.0) if len(hf) else 0.0
            rec["rem_mae_tr"] = max(float(lf.max()) + cur, 0.0) if len(lf) else 0.0
            rec["term_fwd"] = float(r.terminal_gross_atr) - cur
            rec["ttt_s"] = D - cp
            for h in (120, 300, 600):
                rec[f"term_{h}"] = int(D - cp <= h)
            rec["new_mfe_tr"] = int(len(hf) > 0 and hf.max() > mfe + 1e-9)
            rec["recover_entry_tr"] = int(len(hf) > 0 and hf.max() >= -1e-9) if cur < 0 else np.nan
            rec["return_entry_tr"] = int(len(lf) > 0 and lf.max() >= -1e-9) if cur > 0 else np.nan
            hp, lp = hi[ft], lo[ft]
            for a, b in RACES:
                rp = race(hp, lp, a, b, cur)
                rec[f"race_{a:g}_{b:g}_px"] = np.nan if rp == NEITHER else rp        # price-only: unresolved -> excluded
                rr = race(hf, lf, a, b, cur)
                rec[f"race_{a:g}_{b:g}_tr"] = 0.0 if rr == NEITHER else rr           # trade: terminal flip first = not won
            f6 = ft & (t <= cp + 600)
            cover = t[ft].max() >= cp + 590 if ft.any() else False
            rec["fwd600_mfe_px"] = max(float(hi[f6].max()) - cur, 0.0) if cover and f6.any() else np.nan
            rec["fwd600_mae_px"] = max(float(lo[f6].max()) + cur, 0.0) if cover and f6.any() else np.nan
            rec["fwd600_ret_px"] = float(c[f6][-1]) - cur if cover and f6.any() else np.nan
            rows.append(rec)
    return pd.DataFrame(rows)


# ============================================================================ location strata
def loc_strata(cur: pd.Series) -> tuple[pd.Series, list]:
    """suggested edges, adjacent bins merged until every stratum has >= MIN_STRATUM rows"""
    edges = list(LOC_EDGES)
    while True:
        cnt = pd.cut(cur, edges, right=False).value_counts(sort=False).to_numpy()
        small = np.flatnonzero(cnt < MIN_STRATUM)
        if len(small) == 0 or len(edges) <= 3:
            break
        j = small[0]
        # merge bin j with its smaller neighbour
        if j == 0:
            edges.pop(1)
        elif j == len(cnt) - 1:
            edges.pop(-2)
        else:
            edges.pop(j if cnt[j - 1] <= cnt[j + 1] else j + 1)
    return pd.cut(cur, edges, right=False).astype(str), edges


# ============================================================================ stratified contrast + session bootstrap
class Booter:
    def __init__(self, sess_codes: np.ndarray, n_sess: int, rng):
        self.sess = sess_codes
        self.W = rng.multinomial(n_sess, np.full(n_sess, 1 / n_sess), size=B_BOOT).astype(float)

    def stratified(self, y, grp, strat, mask=None):
        """grp: 1 = HIGH, 0 = LOW, -1 = neither. Returns (delta, se, delta_loso, n_used)."""
        m = (grp >= 0) & ~np.isnan(y)
        if mask is not None:
            m &= mask
        y, g, s, se_ = y[m], grp[m], strat[m], self.sess[m]
        if len(y) == 0:
            return np.nan, np.nan, np.nan, 0
        su, sidx = np.unique(s, return_inverse=True)
        cell = sidx * 2 + g
        nc = len(su) * 2
        cnt = np.bincount(cell, minlength=nc).reshape(-1, 2)
        ok = (cnt >= MIN_GROUP).all(axis=1)
        if not ok.any():
            return np.nan, np.nan, np.nan, 0
        sm = np.bincount(cell, weights=y, minlength=nc).reshape(-1, 2)
        diff = sm[:, 1] / np.maximum(cnt[:, 1], 1) - sm[:, 0] / np.maximum(cnt[:, 0], 1)
        wts = np.where(ok, cnt.sum(axis=1), 0).astype(float)
        delta = float((wts * diff).sum() / wts.sum())
        contrib = np.abs(wts * diff)
        wl = wts.copy()
        wl[np.argmax(contrib)] = 0
        loso = float((wl * diff).sum() / wl.sum()) if wl.sum() > 0 else np.nan
        # session bootstrap: per-session cell sums / counts
        S = np.zeros((self.W.shape[1], nc))
        N = np.zeros((self.W.shape[1], nc))
        np.add.at(S, (se_, cell), y)
        np.add.at(N, (se_, cell), 1)
        Sb, Nb = self.W @ S, self.W @ N
        with np.errstate(invalid="ignore", divide="ignore"):
            mb = (Sb / Nb).reshape(B_BOOT, -1, 2)
        db = mb[:, :, 1] - mb[:, :, 0]
        db = np.where(np.isnan(db), diff[None, :], db)
        deltas = (db * wts[None, :]).sum(axis=1) / wts.sum()
        return delta, float(np.std(deltas, ddof=1)), loso, int(cnt[ok].sum())


def split_groups(x: np.ndarray, strat: np.ndarray, kind: str) -> np.ndarray:
    g = np.full(len(x), -1, np.int8)
    if kind == "bin":
        g[x == 0] = 0
        g[x == 1] = 1
        return g
    for s in np.unique(strat):
        m = (strat == s) & ~np.isnan(x)
        if m.sum() < 2 * MIN_GROUP:
            continue
        q1, q2 = np.quantile(x[m], [1 / 3, 2 / 3])
        lo = m & (x <= q1)
        hi = m & ((x > q1) if q1 == q2 else (x >= q2))
        if lo.sum() and hi.sum():
            g[lo], g[hi] = 0, 1
    return g


PROB_OUT = ["race_0.25_0.25_px", "race_0.5_0.25_px", "race_0.5_0.5_px", "race_1_0.5_px", "race_0.5_0.5_tr", "race_1_0.5_tr",
            "term_120", "term_300", "term_600", "new_mfe_tr", "recover_entry_tr", "return_entry_tr"]
A_OUT = ["rem_mfe_tr", "rem_mae_tr", "term_fwd", "fwd600_mfe_px", "fwd600_mae_px", "fwd600_ret_px"]
THR = {**{o: 0.05 for o in PROB_OUT}, **{o: 0.10 for o in A_OUT}}
PATH_VARS = {"mfe_c": "cont", "mae_c": "cont", "pullback_c": "cont", "max_pullback_c": "cont", "cross_c": "cont", "cross_pm": "cont",
             "eff_c": "cont", "pathlen_pm": "cont", "frac_above": "cont", "frac_below": "cont", "balance": "cont", "since_new_mfe": "cont",
             "ret30": "cont", "ret60": "cont", "ret120": "cont", "swings_c": "cont", "swing_age": "cont", "rv120": "cont",
             "vol_ratio120": "cont", "chop_score": "cont"}
CHOP_VARS = ["cross_c", "cross_pm", "eff_c", "pathlen_pm", "balance", "since_new_mfe", "swings_c", "chop_score", "frac_above", "frac_below"]
CTX_VARS = {"is_long": "bin", "aao": "bin", "aligned_now_5m": "bin", "aligned_now_15m": "bin", "aligned_now_1h": "bin",
            "changed_5m": "bin", "changed_15m": "bin", "changed_1h": "bin", "n_aligned_now": "cont", "t0_n_aligned": "cont"}


def classify(r: pd.Series) -> str:
    thr = THR[r.outcome]
    d, se, dt, dv, st, sv, loso = r.delta, r.se, r.d_train, r.d_val, r.se_train, r.se_val, r.delta_loso
    if np.isnan(d) or np.isnan(se):
        return "UNDERPOWERED"
    sig = abs(d) >= 1.96 * se
    same = np.sign(dt) == np.sign(d) and np.sign(dv) == np.sign(d)
    similar = same and min(abs(dt), abs(dv)) >= 0.5 * max(abs(dt), abs(dv))
    loso_ok = not np.isnan(loso) and np.sign(loso) == np.sign(d) and abs(loso) >= 0.5 * abs(d)
    if sig and abs(d) >= thr and similar and loso_ok:
        return "REPLICATED_MATERIAL"
    if sig and same:
        return "DIRECTIONALLY_REPLICATED_WEAK"
    if not np.isnan(st) and abs(dt) >= 1.96 * st and abs(dt) >= thr and not same:
        return "DISCOVERY_ONLY"
    if 2.8 * se > thr:
        return "UNDERPOWERED"
    return "NO_RESIDUAL_INFORMATION"


def run_effects(fv, varspec, family, booter, tmask, rng=None, permute=False, strat_col="loc"):
    rows = []
    for cp, g in fv.groupby("cp"):
        idx = g.index.to_numpy()
        strat = g[strat_col].to_numpy()
        for var, kind in varspec.items():
            x = g[var].to_numpy(float)
            if permute:
                x = x.copy()
                for s in np.unique(strat):
                    m = np.flatnonzero(strat == s)
                    x[m] = x[rng.permutation(m)]
            grp = split_groups(x, strat, kind)
            for o in PROB_OUT + A_OUT:
                y = g[o].to_numpy(float)
                full = np.ones(len(g), bool)
                d, se, loso, n = booter[cp].stratified(y, grp, strat, full)
                dt, st_, _, _ = booter[cp].stratified(y, grp, strat, tmask[idx])
                dv, sv, _, _ = booter[cp].stratified(y, grp, strat, ~tmask[idx])
                rows.append({"cp": cp, "family": family, "variable": var, "outcome": o, "strata": strat_col, "n_used": n, "delta": d, "se": se,
                             "ci_lo": d - 1.96 * se, "ci_hi": d + 1.96 * se, "mde80": 2.8 * se, "d_train": dt, "se_train": st_, "d_val": dv,
                             "se_val": sv, "delta_loso": loso})
    out = pd.DataFrame(rows)
    if len(out):
        out["class"] = out.apply(classify, axis=1)
        out["threshold"] = out.outcome.map(THR)
    return out


def main():
    t = time.time()
    tl = pd.read_parquet(TL)
    tl["D"] = (tl.terminal_ts - tl.t0_ns) // NS
    split = json.loads(SPLIT.read_text(encoding="utf-8"))
    tr_s = set(split["blocks"]["development_train"]["session_list"])
    va_s = set(split["blocks"]["development_validation"]["session_list"])
    assert set(tl.session) <= tr_s | va_s
    p = pd.read_parquet(WORK / "PATH_EXT.parquet")
    chains = pd.read_parquet(WORK / "CHAINS.parquet")
    ctx = pd.read_parquet(WORK / "TRADE_CTX.parquet")
    atlas = pd.read_parquet(ATLAS)
    struct_cols = [c for c in atlas.columns if c.startswith(("sd_", "ad_", "cur_pos_"))]
    at = atlas[["regime_start_ns", "mtf_state", "rel_code", *struct_cols]]
    t = lap("load", t)

    fv = reduce(tl, p, chains, ctx)
    t = lap("reduce_paths_and_checkpoints", t)
    fv = fv.merge(tl[["regime_start_ns", "session", "dir"]], on="regime_start_ns").merge(at, on="regime_start_ns", how="left", validate="m:1")
    assert fv.mtf_state.notna().all()
    fv["block"] = np.where(fv.session.isin(tr_s), "train", "val")
    fv["is_long"] = (fv.dir == 1).astype(float)
    fv["aao"] = (fv.rel_code == "AAO").astype(float)
    fv["t0_n_aligned"] = fv.rel_code.str.count("A").astype(float)
    locs = {}
    parts = []
    for cp, g in fv.groupby("cp"):
        g = g.copy()
        g["loc"], locs[cp] = loc_strata(g.cur)
        g["loc_fine"] = pd.cut(g.cur, np.arange(-3.0, 4.01, 0.1), right=False).astype(str)
        # chop composite: mean within-location-stratum percentile rank of the chop dimensions
        comps = []
        for col, sign in (("cross_pm", 1), ("eff_c", -1), ("pathlen_pm", 1), ("balance", 1), ("since_new_mfe", 1)):
            comps.append((g[col] * sign).groupby(g["loc"]).rank(pct=True))
        g["chop_score"] = np.mean(comps, axis=0)
        parts.append(g)
    fv = pd.concat(parts, ignore_index=True)
    OUT.mkdir(exist_ok=True)
    fv.drop(columns=struct_cols).to_parquet(OUT / "CHECKPOINT_FUTURE_VALUE.parquet", index=False)

    # ---------------------------------------------------------------- populations + location baselines
    n0 = len(tl)
    pop = []
    for cp, g in fv.groupby("cp"):
        pop.append({"cp_s": cp, "primary": cp in PRIMARY, "n_alive": len(g), "frac_alive": len(g) / n0, "n_train": int((g.block == "train").sum()),
                    "n_val": int((g.block == "val").sum()), "cur_p25": g.cur.quantile(.25), "cur_p50": g.cur.median(), "cur_p75": g.cur.quantile(.75),
                    "mfe_p50": g.mfe_c.median(), "mae_p50": g.mae_c.median(), "term_remaining_p50_s": g.term_remaining_s.median(),
                    **{f"pct_reached_{x:g}": 100 * g[f"reached_{x:g}"].mean() for x in (0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0)},
                    "strata_edges": json.dumps([None if not np.isfinite(e) else e for e in locs[cp]])})
    pd.DataFrame(pop).to_csv(OUT / "CHECKPOINT_POPULATIONS.csv", index=False)
    base = []
    for (cp, lc), g in fv.groupby(["cp", "loc"]):
        r = {"cp_s": cp, "loc": lc, "n": len(g), "cur_mean": g.cur.mean()}
        for o in PROB_OUT + A_OUT:
            r[o] = g[o].mean()
        for a, b in RACES:
            r[f"driftless_{a:g}_{b:g}"] = b / (a + b)
        r["rem_mfe_tr_p50"], r["rem_mfe_tr_p90"] = g.rem_mfe_tr.median(), g.rem_mfe_tr.quantile(.9)
        r["term_fwd_p10"], r["term_fwd_p50"], r["term_fwd_p90"] = g.term_fwd.quantile(.1), g.term_fwd.median(), g.term_fwd.quantile(.9)
        r["ttt_p50_s"] = g.ttt_s.median()
        base.append(r)
    base = pd.DataFrame(base)
    base.to_csv(OUT / "LOCATION_BASELINES.csv", index=False)
    t = lap("populations_baselines", t)

    # ---------------------------------------------------------------- stratified effects
    rng = np.random.default_rng(SEED)
    sess_codes, sess_u = pd.factorize(fv.session)
    booter = {}
    for cp, g in fv.groupby("cp"):
        booter[cp] = Booter(sess_codes[g.index.to_numpy()], len(sess_u), rng)
    tmask = (fv.block == "train").to_numpy()
    struct_spec = {c: "cont" for c in struct_cols}
    eff = pd.concat([run_effects(fv, PATH_VARS, "path", booter, tmask),
                     run_effects(fv, CTX_VARS, "context_mtf", booter, tmask),
                     run_effects(fv, struct_spec, "context_structure", booter, tmask),
                     run_effects(fv, {k: v for k, v in PATH_VARS.items() if k in ("mfe_c", "cross_c", "eff_c", "chop_score", "since_new_mfe", "ret60")},
                                 "path_fine_loc", booter, tmask, strat_col="loc_fine")], ignore_index=True)
    t = lap("stratified_effects", t)
    # context after location AND path: strata = location x running-MFE tercile
    parts = []
    for cp, g in fv.groupby("cp"):
        q = g.groupby("loc").mfe_c.transform(lambda s: pd.qcut(s.rank(method="first"), 3, labels=False))
        parts.append(g["loc"] + "|m" + q.astype(str))
    fv["loc_mfe"] = pd.concat(parts)
    eff2 = pd.concat([run_effects(fv, CTX_VARS, "context_mtf_after_path", booter, tmask, strat_col="loc_mfe"),
                      run_effects(fv, struct_spec, "context_structure_after_path", booter, tmask, strat_col="loc_mfe")], ignore_index=True)
    eff = pd.concat([eff, eff2], ignore_index=True)
    t = lap("context_after_path_effects", t)

    # within-stratum permutation null: how many of each class arise with NO residual information
    nul = []
    for k in range(N_PERM):
        for fam, spec, sc in (("path", PATH_VARS, "loc"), ("context_mtf", CTX_VARS, "loc"), ("context_structure", struct_spec, "loc")):
            e = run_effects(fv, spec, fam, booter, tmask, rng=rng, permute=True, strat_col=sc)
            for (cp, cl), n in e.groupby(["cp", "class"]).size().items():
                nul.append({"perm": k, "family": fam, "cp": cp, "class": cl, "n": n})
    nul = pd.DataFrame(nul)
    t = lap("permutation_null_x%d" % N_PERM, t)

    # categorical context: T0 mtf_state (16), T0 rel_code (8), current alignment code (8) -- excess dispersion within location
    cat_rows = []
    for cp, g in fv.groupby("cp"):
        for col in ("mtf_state", "rel_code", "rel_now"):
            for o in ("race_0.5_0.5_px", "race_1_0.5_px", "term_300", "term_fwd", "rem_mfe_tr", "fwd600_ret_px"):
                gg = g[g[col].notna() & g[o].notna()]
                y = gg[o].to_numpy(float)
                for sc in ("loc", "loc_mfe"):
                    e = gg.groupby(sc)[o].transform("mean").to_numpy()
                    v = gg.groupby(sc)[o].transform("var").fillna(0).to_numpy()

                    def stat(labels):
                        s, rms, nn = 0.0, 0.0, 0
                        for lab in np.unique(labels):
                            m = labels == lab
                            if m.sum() < 50:
                                continue
                            vv = v[m].sum()
                            s += (y[m].sum() - e[m].sum()) ** 2 / vv if vv > 0 else 0
                            rms += m.sum() * (y[m].mean() - e[m].mean()) ** 2
                            nn += m.sum()
                        return s, np.sqrt(rms / nn) if nn else np.nan
                    lab = gg[col].to_numpy()
                    s_obs, r_obs = stat(lab)
                    sn = []
                    strat = gg[sc].to_numpy()
                    for _ in range(30):
                        lp = lab.copy()
                        for s_ in np.unique(strat):
                            m = np.flatnonzero(strat == s_)
                            lp[m] = lp[rng.permutation(m)]
                        sn.append(stat(lp))
                    sn = np.array(sn)
                    cat_rows.append({"cp": cp, "context": col, "outcome": o, "strata": sc, "n": len(gg), "dispersion_obs": s_obs,
                                     "dispersion_null_mean": sn[:, 0].mean(), "dispersion_null_p95": np.quantile(sn[:, 0], .95),
                                     "ratio": s_obs / sn[:, 0].mean(), "p_perm": float((sn[:, 0] >= s_obs).mean()),
                                     "rms_dev_obs": r_obs, "rms_dev_null": sn[:, 1].mean()})
    cat = pd.DataFrame(cat_rows)
    t = lap("categorical_context_dispersion", t)

    # ---------------------------------------------------------------- central test: same location, different history
    central = []
    for cp in (300, 480, 720, 1200):
        g = fv[(fv.cp == cp) & (fv.cur < 0) & (fv.cur >= -0.75)]
        A = (g.mfe_c < 0.25) & (g.cross_c >= 2)            # never developed, crossed entry repeatedly
        Bm = (g.mfe_c >= 0.75)                              # developed, now pulling back to below entry
        for name, m in (("A_undeveloped_choppy", A), ("B_developed_pullback", Bm), ("all_in_band", pd.Series(True, index=g.index))):
            h = g[m]
            r = {"cp": cp, "band": "[-0.75A, 0)", "group": name, "n": len(h), "n_train": int((h.block == "train").sum()), "n_val": int((h.block == "val").sum()),
                 "cur_mean": h.cur.mean(), "mfe_mean": h.mfe_c.mean(), "cross_mean": h.cross_c.mean()}
            for o in PROB_OUT + A_OUT + ["ttt_s"]:
                r[o] = h[o].mean()
                r[o + "_train"] = h[h.block == "train"][o].mean()
                r[o + "_val"] = h[h.block == "val"][o].mean()
            central.append(r)
        # location-matched difference B - A with session bootstrap
        grp = np.where(Bm, 1, np.where(A, 0, -1)).astype(np.int8)
        strat = g["loc_fine"].to_numpy()
        sub = Booter(sess_codes[g.index.to_numpy()], len(sess_u), rng)
        for o in PROB_OUT + A_OUT + ["ttt_s"]:
            d, se, loso, n = sub.stratified(g[o].to_numpy(float), grp, strat)
            dt, st_, _, _ = sub.stratified(g[o].to_numpy(float), grp, strat, (g.block == "train").to_numpy())
            dv, sv, _, _ = sub.stratified(g[o].to_numpy(float), grp, strat, (g.block == "val").to_numpy())
            central.append({"cp": cp, "band": "[-0.75A, 0)", "group": "DELTA_B_minus_A_fine_loc_matched", "outcome": o, "n": n, "delta": d, "se": se,
                            "d_train": dt, "d_val": dv})
    central = pd.DataFrame(central)
    t = lap("central_test", t)

    # ---------------------------------------------------------------- write
    eff.to_parquet(OUT / "CONDITIONAL_PATH_EFFECTS.parquet", index=False)
    eff[eff.family.str.startswith("path") & eff.variable.isin(CHOP_VARS)].to_csv(OUT / "CHOP_CONDITIONAL_EFFECTS.csv", index=False)
    eff[eff.family.str.startswith("context")].to_csv(OUT / "CONTEXT_CONDITIONAL_EFFECTS.csv", index=False)
    cat.to_csv(OUT / "CONTEXT_CATEGORICAL_DISPERSION.csv", index=False)
    central.to_csv(OUT / "CENTRAL_TEST.csv", index=False)
    nul.to_csv(OUT / "PERMUTATION_NULL_CLASS_COUNTS.csv", index=False)
    obs = eff[eff.family.isin(["path", "context_mtf", "context_structure"])].groupby(["family", "cp", "class"]).size().rename("observed").reset_index()
    nm = nul.groupby(["family", "cp", "class"]).n.sum().div(N_PERM).rename("null_mean").reset_index()
    info = obs.merge(nm, on=["family", "cp", "class"], how="outer").fillna(0)
    info.to_csv(OUT / "INFORMATION_BY_CHECKPOINT.csv", index=False)
    TIMINGS["total"] = round(time.time() - T_START, 1)
    (OUT / "RUN_TIMINGS.json").write_text(json.dumps({"timings_s": TIMINGS, "path_rows": len(p), "checkpoint_rows": len(fv),
                                                        "n_effects": len(eff), "bootstrap_reps": B_BOOT, "n_perm": N_PERM}, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(TIMINGS, indent=1))


if __name__ == "__main__":
    main()
