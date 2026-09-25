"""T0-segment path atlas -- 2023 DEVELOPMENT sessions only; descriptive, no model of any kind.

Inputs (all pre-existing, audited):
  _work/PATH_1S.parquet                       per-trade 1s path (extract_paths.py, parity 0/42,168)
  nq_post_entry_path_mechanism_2023 TRADE_EVENT_TIMELINE  population, entry, ATR, terminal bound, gross P&L
  nq_mtf_regime_structural_geometry_atlas atlas_2023_frame  complete T0 taxonomy (mtf_state, rel_code, side, 51 b_* dims)
  nq_target_a_constrained_stationary_2023 TEMPORAL_SPLIT_2023 development_train (154) / development_validation (51)

The final 20% of 2023 is never loaded; 2024+ never touched.

    python studies/nq_t0_segment_path_atlas_2023/path_atlas.py
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
PATHS = HERE / "_work" / "PATH_1S.parquet"
TOUCH = pd.read_parquet(HERE / "_work" / "FIRST_TOUCH.parquet").set_index("regime_start_ns")   # kernel price-level arithmetic
OUT = HERE / "artifacts"

FAV = [0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0]
ADV = [0.25, 0.5, 1.0]
# clock checkpoints (s after T0) chosen from the empirical terminal-duration quantiles (P10 165, P25 285, P50 585,
# P75 1065, P90 1725): dense early where failures concentrate, spanning past P90
CHECKPOINTS = [30, 60, 120, 180, 300, 480, 720, 1080, 1800]
QUICK_S = 225            # end of the undeveloped-trade hazard ramp == median failure duration (see DURATION section)
QUICK_SENS = [165, 345]
EPS = 1e-5             # float32 A-unit tolerance for level touches (ticks are >= ~0.01A)
HYST = 0.10              # entry-crossing hysteresis band (A)
SWING = 0.50             # zigzag reversal threshold for a "meaningful" swing (A)
MIN_N, SPARSE_N = 150, 300
N_SHIFTS, SHIFT_SEED = 60, 20260925
CUR_BINS = [-np.inf, -0.5, -0.25, 0, 0.25, 0.5, 1.0, 1.5, 2.0, np.inf]
MFE_BINS = [-np.inf, 0.25, 0.5, 1.0, 1.5, 2.0, np.inf]
T_START = time.time()
TIMINGS: dict[str, float] = {}


def lap(name: str, t0: float) -> float:
    TIMINGS[name] = round(time.time() - t0, 2)
    return time.time()


def lbl(x: float) -> str:
    return f"{x:g}".replace(".", "p")


# ============================================================================ per-trade path reduction
def reduce_paths(tl: pd.DataFrame, p: pd.DataFrame):
    trades, cps, evs = [], [], []
    D_of = dict(zip(tl.regime_start_ns, tl.D))
    for rs, g in p.groupby("regime_start_ns", sort=False):
        D = int(D_of[rs])
        t = g["t"].to_numpy(np.int64)
        hi = g["hi"].to_numpy(float)
        lo = g["lo"].to_numpy(float)
        c = g["c"].to_numpy(float)
        n = len(t)
        rmfe = np.maximum.accumulate(np.maximum(hi, 0))
        rmae = np.maximum.accumulate(np.maximum(lo, 0))
        hold = np.diff(np.append(t, D)).astype(float)
        hold = np.maximum(hold, 0)
        above_cum = np.concatenate([[0], np.cumsum(hold * (c > 0))])       # time above entry BEFORE row i
        below_cum = np.concatenate([[0], np.cumsum(hold * (c < 0))])
        pathlen = np.cumsum(np.abs(np.diff(np.concatenate([[0.0], c]))))
        # entry crossings with a +-HYST band
        cross = np.zeros(n, np.int32)
        state, k = 0, 0
        for i in range(n):
            s = 1 if c[i] >= HYST else (-1 if c[i] <= -HYST else state)
            if state != 0 and s != state:
                k += 1
            state = s
            cross[i] = k
        # zigzag swings on closes: count reversals of an established leg by >= SWING
        swings = np.zeros(n, np.int32)
        direc, hi_e, lo_e, m = 0, 0.0, 0.0, 0
        for i in range(n):
            x = c[i]
            if direc >= 0:
                hi_e = max(hi_e, x)
            if direc <= 0:
                lo_e = min(lo_e, x)
            if direc >= 0 and hi_e - x >= SWING:
                m += int(direc == 1)
                direc, lo_e = -1, x
            elif direc <= 0 and x - lo_e >= SWING:
                m += int(direc == -1)
                direc, hi_e = 1, x
            swings[i] = m
        new_mfe = np.concatenate([[True], rmfe[1:] > rmfe[:-1]]) & (hi > 0)
        last_new = np.where(new_mfe, t, -1)
        last_new = np.maximum.accumulate(last_new)

        def first(mask):
            idx = np.flatnonzero(mask)
            return int(idx[0]) if len(idx) else None

        trow = TOUCH.loc[rs]
        touch_t = {**{("f", x): trow[f"t_fav_{lbl(x)}"] for x in FAV}, **{("a", x): trow[f"t_adv_{lbl(x)}"] for x in ADV}}
        mfe = float(rmfe[-1]) if n else 0.0
        mae = float(rmae[-1]) if n else 0.0
        rec = {"regime_start_ns": rs, "mfe": mfe, "mae": mae, "n_bars": n,
               "t_mfe": float(t[first(hi >= mfe)]) if n and mfe > 0 else 0.0,
               "crossings": int(cross[-1]) if n else 0, "swings": int(swings[-1]) if n else 0,
               "pathlen": float(pathlen[-1]) if n else 0.0, "disp": float(c[-1]) if n else 0.0,
               "frac_above": float(above_cum[-1] / D), "frac_below": float(below_cum[-1] / D)}
        rec["efficiency"] = rec["disp"] / rec["pathlen"] if rec["pathlen"] > 0 else 0.0
        rec["pullback_final"] = mfe - rec["disp"]
        ft = {}
        for x in FAV:
            i = first(t == touch_t[("f", x)]) if not np.isnan(touch_t[("f", x)]) else None
            ft[("f", x)] = i
            rec[f"t_fav_{lbl(x)}"] = float(t[i]) if i is not None else np.nan
        for x in ADV:
            i = first(t == touch_t[("a", x)]) if not np.isnan(touch_t[("a", x)]) else None
            ft[("a", x)] = i
            rec[f"t_adv_{lbl(x)}"] = float(t[i]) if i is not None else np.nan
        trades.append(rec)

        # ---- clock checkpoints (information through bars with t <= c)
        for j, cp in enumerate(CHECKPOINTS):
            if D <= cp:
                break
            nxt = CHECKPOINTS[j + 1] if j + 1 < len(CHECKPOINTS) else None
            i = int(np.searchsorted(t, cp, side="right")) - 1
            if i >= 0:
                cur, cm, ca = c[i], rmfe[i], rmae[i]
                ab = above_cum[i] + (cp - t[i]) * (c[i] > 0)
                be = below_cum[i] + (cp - t[i]) * (c[i] < 0)
                cr, sw, pl = cross[i], swings[i], pathlen[i]
                since = cp - last_new[i] if last_new[i] >= 0 else cp
            else:
                cur = cm = ca = ab = be = pl = 0.0
                cr = sw = 0
                since = cp

            def cur_at(s):
                ii = int(np.searchsorted(t, s, side="right")) - 1
                return c[ii] if ii >= 0 else 0.0

            cps.append({"regime_start_ns": rs, "cp": cp, "cur": cur, "mfe_c": cm, "mae_c": ca, "pullback_c": cm - cur,
                        "cross_c": int(cr), "cross_per_min_c": cr / (cp / 60), "swings_c": int(sw),
                        "eff_c": cur / pl if pl > 0 else 0.0, "frac_above_c": ab / cp, "frac_below_c": be / cp,
                        "since_new_mfe_c": since, "ret30": cur - cur_at(cp - 30), "ret60": cur - cur_at(cp - 60),
                        "term_next": int(nxt is not None and D <= nxt), "next_cp": nxt if nxt is not None else np.nan})

        # ---- event anchors: first touch of +x
        for k, x in enumerate([0.25, 0.5, 1.0, 1.5, 2.0, 3.0]):
            i = ft[("f", x)]
            if i is None:
                continue
            y = {0.25: 0.5, 0.5: 1.0, 1.0: 1.5, 1.5: 2.0, 2.0: 3.0, 3.0: 4.0}[x]
            iy = ft[("f", y)]
            rj = first(lo[i + 1:] >= 0)
            iret = i + 1 + rj if rj is not None else None
            if iy is not None and iret is not None:
                nxt_first = int(iy < iret)
                ret_first = int(iret < iy)
            else:
                nxt_first = int(iy is not None)
                ret_first = int(iret is not None and iy is None)
            evs.append({"regime_start_ns": rs, "level": x, "t_touch": float(t[i]), "mae_before": float(rmae[i]),
                        "cross_before": int(cross[i]), "eff_before": c[i] / pathlen[i] if pathlen[i] > 0 else 0.0,
                        "next_level": y, "next_before_return": nxt_first, "return_before_next": ret_first,
                        "reach_next": int(iy is not None), "return_to_entry": int(iret is not None),
                        "t_to_next": float(t[iy] - t[i]) if iy is not None else np.nan})
    return pd.DataFrame(trades), pd.DataFrame(cps), pd.DataFrame(evs)


# ============================================================================ phenotypes
def phenotype(df: pd.DataFrame, runner: float = 2.0, quick: int = QUICK_S, fail: float = 0.5) -> pd.Series:
    out = np.where(df.mfe >= runner, "RUNNER", np.where(df.mfe >= fail, "PARTIAL",
                   np.where(df.D <= quick, "QUICK_FAIL", "SLOW_FAIL")))
    return pd.Series(out, index=df.index)


PHEN = ["QUICK_FAIL", "SLOW_FAIL", "PARTIAL", "RUNNER"]


def qs(x, q):
    x = pd.Series(x).dropna()
    return float(x.quantile(q)) if len(x) else np.nan


def seg_signature(d: pd.DataFrame) -> dict:
    r = {"N": len(d), "sessions": d.session.nunique(), "n_train": int((d.block == "train").sum()), "n_val": int((d.block == "val").sum())}
    for ph in PHEN:
        r[f"pct_{ph}"] = 100 * float((d.phen == ph).mean())
    for R in (1.0, 3.0):
        r[f"pct_RUNNER_{lbl(R)}A"] = 100 * float((d.mfe >= R).mean())
    for Q in QUICK_SENS:
        r[f"pct_QUICK_FAIL_{Q}s"] = 100 * float(((d.mfe < 0.5) & (d.D <= Q)).mean())
    r["win_pct"] = 100 * float(d.win.mean())
    r["mean_gross_A"] = float(d.terminal_gross_atr.mean())
    for v, name in (("D", "dur_s"), ("mfe", "mfe"), ("mae", "mae")):
        for q in (0.5, 0.75, 0.9):
            r[f"{name}_p{int(q*100)}"] = qs(d[v], q)
    for x in (0.5, 1.0, 1.5, 2.0, 3.0):
        r[f"p_fav_{lbl(x)}"] = 100 * float(d[f"t_fav_{lbl(x)}"].notna().mean())
        r[f"t_fav_{lbl(x)}_p50"] = qs(d[f"t_fav_{lbl(x)}"], 0.5)
        r[f"t_fav_{lbl(x)}_p75"] = qs(d[f"t_fav_{lbl(x)}"], 0.75)
    for x in (0.5, 1.0):
        a, f = d[f"t_adv_{lbl(x)}"], d[f"t_fav_{lbl(x)}"]
        r[f"p_adv_{lbl(x)}_first"] = 100 * float((a.notna() & (f.isna() | (a < f))).mean())
    r["t_mfe_p50"] = qs(d.t_mfe, 0.5)
    r["mfe_to_term_p50"] = qs(d.D - d.t_mfe, 0.5)
    r["crossings_mean"] = float(d.crossings.mean())
    r["crossings_per_min_p50"] = qs(d.crossings / (d.D / 60), 0.5)
    r["swings_mean"] = float(d.swings.mean())
    r["efficiency_p50"] = qs(d.efficiency, 0.5)
    r["frac_above_p50"] = qs(d.frac_above, 0.5)
    r["frac_below_p50"] = qs(d.frac_below, 0.5)
    r["pullback_final_p50"] = qs(d.pullback_final, 0.5)
    r["giveback_frac_p50"] = qs((d.pullback_final / d.mfe).where(d.mfe >= 0.5), 0.5)
    return r


# ============================================================================ cluster-robust contrasts
def cluster_diff(y: np.ndarray, s: np.ndarray, sess: np.ndarray):
    """y mean in s vs rest, session-clustered SE (influence-function sandwich)."""
    n1, n0 = s.sum(), (~s).sum()
    if n1 == 0 or n0 == 0:
        return np.nan, np.nan
    m1, m0 = y[s].mean(), y[~s].mean()
    e = y - np.where(s, m1, m0)
    psi = np.where(s, e / n1, -e / n0)
    v = float(np.square(np.bincount(sess, weights=psi)).sum())
    return m1 - m0, (m1 - m0) / np.sqrt(v) if v > 0 else np.nan


def build_segments(tr: pd.DataFrame, attrs: pd.DataFrame, dims: list[str]):
    """list of (family, dim, bucket, parent_label, member_mask, parent_mask)."""
    segs = []
    allm = np.ones(len(tr), bool)
    for fam, col in (("F1_mtf_state", "mtf_state"), ("F2_rel_code", "rel_code"), ("F3_side", "side")):
        for v in sorted(attrs[col].dropna().unique()):
            segs.append((fam, col, str(v), "ALL", (attrs[col] == v).to_numpy(), allm))
    for col in dims:
        for v in sorted(attrs[col].dropna().unique()):
            segs.append(("F4_structural_1d", col, str(v), "ALL", (attrs[col] == v).to_numpy(), allm))
    for st in sorted(attrs.mtf_state.unique()):
        pm = (attrs.mtf_state == st).to_numpy()
        if pm.sum() < SPARSE_N:
            continue
        for col in dims:
            for v in sorted(attrs.loc[pm, col].dropna().unique()):
                mm = pm & (attrs[col] == v).to_numpy()
                if mm.sum() >= MIN_N:
                    segs.append(("F5_state_x_structural", col, f"{st} :: {v}", st, mm, pm))
    return segs


OUTCOMES = {"QUICK_FAIL": lambda d: (d.phen == "QUICK_FAIL").to_numpy(float),
            "SLOW_FAIL": lambda d: (d.phen == "SLOW_FAIL").to_numpy(float),
            "PARTIAL": lambda d: (d.phen == "PARTIAL").to_numpy(float),
            "RUNNER": lambda d: (d.phen == "RUNNER").to_numpy(float),
            "log_dur": lambda d: np.log(d.D.to_numpy(float)),
            "gross": lambda d: d.terminal_gross_atr.to_numpy(float),
            "cross_per_min": lambda d: (d.crossings / (d.D / 60)).to_numpy(float)}
MAT_PP = {"QUICK_FAIL": 5, "SLOW_FAIL": 5, "PARTIAL": 5, "RUNNER": 5}


def contrasts(tr: pd.DataFrame, segs, ys: dict):
    sess = pd.factorize(tr.session)[0]
    tmask = (tr.block == "train").to_numpy()
    rows = []
    for fam, col, b, parent, mm, pm in segs:
        r = {"family": fam, "dim": col, "segment": b, "parent": parent, "N": int(mm.sum()), "N_rest": int(pm.sum() - mm.sum())}
        for k, y in ys.items():
            d, z = cluster_diff(y[pm], mm[pm], sess[pm])
            dt, _ = cluster_diff(y[pm & tmask], mm[pm & tmask], sess[pm & tmask])
            dv, _ = cluster_diff(y[pm & ~tmask], mm[pm & ~tmask], sess[pm & ~tmask])
            sc = 100 if k in MAT_PP else 1
            r[f"d_{k}"], r[f"z_{k}"], r[f"dtrain_{k}"], r[f"dval_{k}"] = d * sc, z, dt * sc, dv * sc
        rows.append(r)
    return pd.DataFrame(rows)


def flag_material(c: pd.DataFrame) -> pd.DataFrame:
    c = c.copy()
    for k, pp in MAT_PP.items():
        big = (c[f"d_{k}"].abs() >= pp) & (c[f"z_{k}"].abs() >= 2.5) & (c.N >= MIN_N) & (c.N_rest >= MIN_N)   # no degenerate rest
        rep = big & (np.sign(c[f"dtrain_{k}"]) == np.sign(c[f"d_{k}"])) & (np.sign(c[f"dval_{k}"]) == np.sign(c[f"d_{k}"])) \
            & (c[f"dval_{k}"].abs() >= pp / 2)
        c[f"mat_{k}"], c[f"rep_{k}"] = big, rep
    return c


# ============================================================================ dispersion vs circular-shift null
def dispersion(y: np.ndarray, e: np.ndarray, v: np.ndarray, groups: list[np.ndarray]) -> float:
    """sum over segments of (O-E)^2 / V (a chi-square-like excess dispersion); groups are boolean masks."""
    s = 0.0
    for m in groups:
        if m.sum() < MIN_N:
            continue
        vv = v[m].sum()
        if vv > 0:
            s += (y[m].sum() - e[m].sum()) ** 2 / vv
    return s


def shifted(attrs: pd.DataFrame, k: int) -> pd.DataFrame:
    return pd.DataFrame(np.roll(attrs.to_numpy(), k, axis=0), columns=attrs.columns, index=attrs.index)


def family_groups(attrs: pd.DataFrame, fam: str, dims: list[str], keep: np.ndarray | None = None):
    cols = {"F1_mtf_state": ["mtf_state"], "F2_rel_code": ["rel_code"], "F3_side": ["side"], "F4_structural_1d": dims}[fam]
    out = []
    for col in cols:
        a = attrs[col].to_numpy()
        for v in pd.unique(a[pd.notna(a)]):
            m = a == v
            out.append(m if keep is None else m[keep])
    return out


def main() -> None:
    t = time.time()
    tl = pd.read_parquet(TL)
    tl["D"] = (tl.terminal_ts - tl.t0_ns) // 10**9
    split = json.loads(SPLIT.read_text(encoding="utf-8"))
    tr_s, va_s = set(split["blocks"]["development_train"]["session_list"]), set(split["blocks"]["development_validation"]["session_list"])
    tl["block"] = np.where(tl.session.isin(tr_s), "train", np.where(tl.session.isin(va_s), "val", "OUT"))
    assert (tl.block != "OUT").all()
    atlas = pd.read_parquet(ATLAS)
    dims = [c for c in atlas.columns if c.startswith("b_")]
    at = atlas[["regime_start_ns", "mtf_state", "rel_code", "side", "dir_1m", *dims]]
    p = pd.read_parquet(PATHS)
    t = lap("load_inputs", t)

    trades, cps, evs = reduce_paths(tl, p)
    t = lap("reduce_paths_1s", t)
    audited = tl.set_index("regime_start_ns")[[c for c in tl.columns if c.startswith(("t_fav_", "t_adv_"))]]
    tl = tl.drop(columns=[c for c in tl.columns if c.startswith(("t_fav_", "t_adv_", "reach_"))])
    tr = tl.merge(trades, on="regime_start_ns", how="left").merge(at, on="regime_start_ns", how="left", validate="1:1")
    assert tr.mtf_state.notna().all() and (tr.dir_1m == tr.dir).all() and len(tr) == 6024
    for col in ("mfe", "mae", "crossings", "swings", "pathlen", "disp", "efficiency", "pullback_final", "t_mfe", "frac_above", "frac_below"):
        tr[col] = tr[col].fillna(0.0)
    # parity: recomputed first touches equal the audited timeline
    par = {x: int(((tr[f"t_fav_{lbl(x)}"].fillna(-1)) != audited.loc[tr.regime_start_ns, f"t_fav_{f'{x:.1f}'.replace('.', 'p')}"].fillna(-1).to_numpy()).sum())
           for x in (0.5, 1.0, 1.5, 2.0, 3.0)}
    assert sum(par.values()) == 0, par
    tr = tr.sort_values("t0_ns").reset_index(drop=True)
    tr["phen"] = phenotype(tr)
    OUT.mkdir(exist_ok=True)
    tr.drop(columns=[c for c in tr.columns if c.startswith("chain_") or c.startswith("first_trans") or c.startswith("t_first")]).to_parquet(OUT / "PATH_ATLAS_TRADES.parquet", index=False)

    # ---------------------------------------------------------------- 1. lifecycle distributions
    qv = [0.1, 0.25, 0.5, 0.75, 0.9, 0.95]
    rows = []

    def drow(name, x, pop):
        x = pd.Series(x).dropna()
        rows.append({"quantity": name, "population": pop, "n": len(x), **{f"p{int(q*100)}": float(x.quantile(q)) for q in qv}})
    for name, m in (("all", np.ones(len(tr), bool)), *[(ph, (tr.phen == ph).to_numpy()) for ph in PHEN]):
        d = tr[m]
        drow("T0_to_terminal_s", d.D, name)
        for x in (0.25, 0.5, 1.0, 1.5, 2.0, 3.0):
            drow(f"T0_to_fav_{lbl(x)}A_s (reached)", d[f"t_fav_{lbl(x)}"], name)
        drow("T0_to_max_MFE_s", d.t_mfe, name)
        drow("max_MFE_to_terminal_s", d.D - d.t_mfe, name)
    dur = pd.DataFrame(rows)
    dur.to_csv(OUT / "DURATION_DISTRIBUTIONS.csv", index=False)
    # hazard of terminal flip per minute boundary, overall / undeveloped (running MFE < 0.5A) / developed
    hz = []
    p = p.sort_values(["regime_start_ns", "t"])
    p["rmfe"] = p.groupby("regime_start_ns").hi.cummax()
    Dm = tr.set_index("regime_start_ns").D
    phm = tr.set_index("regime_start_ns").phen
    for m in range(0, 40):
        c0 = 0 if m == 0 else 45 + 60 * (m - 1)
        rm = p[p.t <= c0].groupby("regime_start_ns").rmfe.last().reindex(Dm.index).fillna(0)
        alive = Dm > c0
        nxt = alive & (Dm <= (45 if m == 0 else c0 + 60))
        und = rm < 0.5
        hz.append({"t_s": c0, "alive": int(alive.sum()), "hazard_all": float(nxt[alive].mean()),
                   "alive_undeveloped": int((alive & und).sum()), "hazard_undeveloped": float(nxt[alive & und].mean()) if (alive & und).sum() else np.nan,
                   "alive_developed": int((alive & ~und).sum()), "hazard_developed": float(nxt[alive & ~und].mean()) if (alive & ~und).sum() else np.nan,
                   "survival": float(alive.mean())})
    hz = pd.DataFrame(hz)
    hz.to_csv(OUT / "TERMINAL_HAZARD.csv", index=False)
    t = lap("lifecycle_distributions", t)

    # ---------------------------------------------------------------- 2. segments: signatures + contrasts
    attrs = tr[["mtf_state", "rel_code", "side", *dims]].reset_index(drop=True)
    segs = build_segments(tr, attrs, dims)
    ys = {k: f(tr) for k, f in OUTCOMES.items()}
    sig_rows = []
    for fam, col, b, parent, mm, pm in segs:
        sig_rows.append({"family": fam, "dim": col, "segment": b, "parent": parent, **seg_signature(tr[mm])})
    sig = pd.DataFrame(sig_rows)
    parent_sig = pd.DataFrame([{"family": "F0_all", "dim": "-", "segment": "ALL", "parent": "-", **seg_signature(tr)}])
    con = flag_material(contrasts(tr, segs, ys))
    seg_tab = pd.concat([parent_sig, sig.merge(con, on=["family", "dim", "segment", "parent"], how="left", suffixes=("", "_c"))], ignore_index=True)
    seg_tab["sparse"] = seg_tab.N < SPARSE_N
    seg_tab["suppressed"] = seg_tab.N < MIN_N
    t = lap("segment_signatures_contrasts", t)

    # circular-shift null: expected number of material / replicated flags per family
    rng = np.random.default_rng(SHIFT_SEED)
    shifts = rng.integers(500, len(tr) - 500, N_SHIFTS)
    null_counts = []
    for k in shifts:
        sa = shifted(attrs, int(k))
        cn = flag_material(contrasts(tr, build_segments(tr, sa, dims), ys))
        for fam, g in cn.groupby("family"):
            null_counts.append({"shift": int(k), "family": fam, "n_seg": int(((g.N >= MIN_N) & (g.N_rest >= MIN_N)).sum()),
                                **{f"mat_{o}": int(g[f"mat_{o}"].sum()) for o in MAT_PP}, **{f"rep_{o}": int(g[f"rep_{o}"].sum()) for o in MAT_PP}})
    nullc = pd.DataFrame(null_counts)
    flag_summary = []
    for fam, g in con.groupby("family"):
        ng = nullc[nullc.family == fam]
        for o in MAT_PP:
            for kind in ("mat", "rep"):
                obs = int(g[f"{kind}_{o}"].sum())
                flag_summary.append({"family": fam, "outcome": o, "kind": kind, "n_segments": int(((g.N >= MIN_N) & (g.N_rest >= MIN_N)).sum()), "observed": obs,
                                     "null_mean": float(ng[f"{kind}_{o}"].mean()), "null_p95": float(ng[f"{kind}_{o}"].quantile(0.95)),
                                     "p_shift": float((ng[f"{kind}_{o}"] >= obs).mean())})
    flag_summary = pd.DataFrame(flag_summary)
    flag_summary.to_csv(OUT / "FLAG_COUNTS_VS_NULL.csv", index=False)
    t = lap("circular_shift_null_flags_x%d" % N_SHIFTS, t)

    # replication of segment deviations: train-block vs val-block correlation (N>=MIN_N segments), per family
    rep_rows = []
    for fam, g in con[(con.N >= MIN_N) & (con.N_rest >= MIN_N)].groupby("family"):
        for o in list(MAT_PP) + ["log_dur", "gross", "cross_per_min"]:
            a, b = g[f"dtrain_{o}"], g[f"dval_{o}"]
            ok = a.notna() & b.notna()
            rep_rows.append({"family": fam, "outcome": o, "n_segments": int(ok.sum()),
                             "spearman_train_vs_val": float(a[ok].corr(b[ok], method="spearman")) if ok.sum() > 3 else np.nan,
                             "pearson_train_vs_val": float(a[ok].corr(b[ok])) if ok.sum() > 3 else np.nan})
    rep = pd.DataFrame(rep_rows)
    # same statistic under the shift null (first 20 shifts)
    nrep = []
    for k in shifts[:20]:
        cn = contrasts(tr, [s for s in build_segments(tr, shifted(attrs, int(k)), dims)], ys)
        for fam, g in cn[(cn.N >= MIN_N) & (cn.N_rest >= MIN_N)].groupby("family"):
            for o in list(MAT_PP) + ["log_dur", "gross", "cross_per_min"]:
                a, b = g[f"dtrain_{o}"], g[f"dval_{o}"]
                ok = a.notna() & b.notna()
                nrep.append({"family": fam, "outcome": o, "r": float(a[ok].corr(b[ok], method="spearman")) if ok.sum() > 3 else np.nan})
    nrep = pd.DataFrame(nrep).groupby(["family", "outcome"]).r.agg(null_mean="mean", null_p95=lambda x: x.quantile(0.95)).reset_index()
    rep = rep.merge(nrep, on=["family", "outcome"], how="left")
    rep.to_csv(OUT / "SEGMENT_REPLICATION.csv", index=False)
    t = lap("train_vs_val_replication", t)

    # ---------------------------------------------------------------- 3. transitions (clock + event)
    cps = cps.merge(tr[["regime_start_ns", "mfe", "phen", "terminal_gross_atr", "D"]], on="regime_start_ns")
    cps["ev_runner"] = (cps.mfe >= 2).astype(float)
    cps["ev_partial_plus"] = (cps.mfe >= 0.5).astype(float)
    cps["term_loss"] = (cps.terminal_gross_atr < 0).astype(float)
    cps["loc"] = pd.cut(cps.cur, CUR_BINS).astype(str) + "|" + pd.cut(cps.mfe_c, MFE_BINS).astype(str)
    evs = evs.merge(tr[["regime_start_ns", "mfe", "terminal_gross_atr"]], on="regime_start_ns")
    evs["ev_runner"] = (evs.mfe >= 2).astype(float)
    evs["term_loss"] = (evs.terminal_gross_atr < 0).astype(float)
    evs["ev_3A"] = (evs.mfe >= 3).astype(float)
    idx_of = pd.Series(np.arange(len(tr)), index=tr.regime_start_ns)
    cps["ti"] = idx_of.loc[cps.regime_start_ns].to_numpy()
    evs["ti"] = idx_of.loc[evs.regime_start_ns].to_numpy()

    strat_bins = {"cur": CUR_BINS, "mfe_c": MFE_BINS, "mae_c": [-np.inf, 0.25, 0.5, 0.75, 1.0, 1.5, np.inf],
                  "pullback_c": [-np.inf, 0.1, 0.25, 0.5, 1.0, 1.5, np.inf], "cross_per_min_c": [-np.inf, 0.01, 0.5, 1, 2, np.inf],
                  "eff_c": [-np.inf, -0.2, -0.05, 0.05, 0.2, np.inf], "frac_above_c": [-0.01, 0.2, 0.4, 0.6, 0.8, 1.01],
                  "since_new_mfe_c": [-1, 15, 60, 180, 600, np.inf], "ret30": [-np.inf, -0.25, -0.05, 0.05, 0.25, np.inf],
                  "ret60": [-np.inf, -0.25, -0.05, 0.05, 0.25, np.inf], "swings_c": [-1, 0, 1, 3, np.inf]}
    trans = []
    for cp, g in cps.groupby("cp"):
        for sv, bins in strat_bins.items():
            gb = g.groupby(pd.cut(g[sv], bins), observed=True)
            for b, h in gb:
                if len(h) < 30:
                    continue
                trans.append({"anchor_type": "clock", "anchor": f"{cp}s", "family": "ALL", "segment": "ALL", "stratifier": sv, "stratum": str(b),
                              "n": len(h), "p_term_next_interval": 100 * h.term_next.mean(), "p_eventual_runner": 100 * h.ev_runner.mean(),
                              "p_eventual_partial_plus": 100 * h.ev_partial_plus.mean(), "p_terminal_loss": 100 * h.term_loss.mean(),
                              "p_runner_if_not_yet": 100 * h.ev_runner[h.mfe_c < 2].mean() if (h.mfe_c < 2).any() else np.nan})
        for fam, col in (("F1_mtf_state", "mtf_state"), ("F2_rel_code", "rel_code")):
            seg = tr[col].to_numpy()[g.ti.to_numpy()]
            for v in np.unique(seg):
                h0 = g[seg == v]
                for b, h in h0.groupby(pd.cut(h0.cur, CUR_BINS), observed=True):
                    if len(h) < 30:
                        continue
                    trans.append({"anchor_type": "clock", "anchor": f"{cp}s", "family": fam, "segment": v, "stratifier": "cur", "stratum": str(b),
                                  "n": len(h), "p_term_next_interval": 100 * h.term_next.mean(), "p_eventual_runner": 100 * h.ev_runner.mean(),
                                  "p_eventual_partial_plus": 100 * h.ev_partial_plus.mean(), "p_terminal_loss": 100 * h.term_loss.mean(),
                                  "p_runner_if_not_yet": 100 * h.ev_runner[h.mfe_c < 2].mean() if (h.mfe_c < 2).any() else np.nan})
    for lv, g in evs.groupby("level"):
        for fam, col in (("ALL", None), ("F1_mtf_state", "mtf_state"), ("F2_rel_code", "rel_code")):
            seg = np.array(["ALL"] * len(g)) if col is None else tr[col].to_numpy()[g.ti.to_numpy()]
            for v in np.unique(seg):
                h = g[seg == v]
                if len(h) < 30:
                    continue
                trans.append({"anchor_type": "event", "anchor": f"+{lv:g}A", "family": fam, "segment": v, "stratifier": "-", "stratum": "-",
                              "n": len(h), "p_next_before_return": 100 * h.next_before_return.mean(), "p_return_before_next": 100 * h.return_before_next.mean(),
                              "p_reach_next": 100 * h.reach_next.mean(), "p_eventual_runner": 100 * h.ev_runner.mean(), "p_eventual_3A": 100 * h.ev_3A.mean(),
                              "p_terminal_loss": 100 * h.term_loss.mean(), "t_touch_p50": float(h.t_touch.median()), "t_to_next_p50": float(h.t_to_next.median())})
    trans = pd.DataFrame(trans)
    t = lap("transition_tables", t)

    # ---- does the T0 segment still matter once the state is known?  excess dispersion vs circular-shift null
    def seg_matter(frame, ycol, loc_col, anchor, anchor_type, pre_mask=None):
        g = frame if pre_mask is None else frame[pre_mask]
        y = g[ycol].to_numpy(float)
        ti = g.ti.to_numpy()
        pooled = np.full(len(y), y.mean())
        if loc_col is not None:
            e_loc = g.groupby(loc_col)[ycol].transform("mean").to_numpy(float)
        res = []
        for fam in ("F1_mtf_state", "F2_rel_code", "F4_structural_1d"):
            def stat(att):
                grp = [m[ti] for m in family_groups(att, fam, dims)]
                out = {"raw": dispersion(y, pooled, pooled * (1 - pooled), grp)}
                if loc_col is not None:
                    out["loc_adj"] = dispersion(y, e_loc, e_loc * (1 - e_loc), grp)
                # effect size: N-weighted RMS deviation (pp), raw and adjusted
                wr, wa, nn = 0.0, 0.0, 0
                for m in grp:
                    if m.sum() < MIN_N:
                        continue
                    wr += m.sum() * (y[m].mean() - y.mean()) ** 2
                    if loc_col is not None:
                        wa += m.sum() * (y[m].mean() - e_loc[m].mean()) ** 2
                    nn += m.sum()
                out["rms_raw_pp"] = 100 * np.sqrt(wr / nn) if nn else np.nan
                out["rms_adj_pp"] = 100 * np.sqrt(wa / nn) if nn and loc_col is not None else np.nan
                return out
            obs = stat(attrs)
            nul = pd.DataFrame([stat(shifted(attrs, int(k))) for k in shifts[:30]])
            r = {"anchor_type": anchor_type, "anchor": anchor, "outcome": ycol, "family": fam, "n": len(y), "base_rate_pct": 100 * y.mean()}
            for key in obs:
                r[f"{key}_obs"] = obs[key]
                r[f"{key}_null_mean"] = float(nul[key].mean())
                r[f"{key}_null_p95"] = float(nul[key].quantile(0.95))
                r[f"{key}_ratio"] = obs[key] / float(nul[key].mean()) if nul[key].mean() > 0 else np.nan
                r[f"{key}_p_shift"] = float((nul[key] >= obs[key]).mean())
            res.append(r)
        return res

    sm = []
    tr_ti = pd.DataFrame({"ti": np.arange(len(tr)), "RUNNER": ys["RUNNER"], "QUICK_FAIL": ys["QUICK_FAIL"],
                          "SLOW_FAIL": ys["SLOW_FAIL"], "fail": (tr.mfe < 0.5).to_numpy(float), "term_loss": (tr.terminal_gross_atr < 0).to_numpy(float)})
    for o in ("RUNNER", "QUICK_FAIL", "SLOW_FAIL", "term_loss"):
        sm += seg_matter(tr_ti, o, None, "T0", "T0")
    for cp, g in cps.groupby("cp"):
        if cp not in (60, 180, 300, 480, 720, 1080):
            continue
        sm += seg_matter(g, "ev_runner", "loc", f"{cp}s", "clock", pre_mask=(g.mfe_c < 2).to_numpy())
        sm += seg_matter(g, "term_next", "loc", f"{cp}s", "clock")
        sm += seg_matter(g, "term_loss", "loc", f"{cp}s", "clock")
    for lv, g in evs.groupby("level"):
        if lv > 2:
            continue
        g = g.copy()
        g["tbin"] = pd.qcut(g.t_touch, 4, duplicates="drop").astype(str)
        sm += seg_matter(g, "ev_runner" if lv < 2 else "ev_3A", "tbin", f"+{lv:g}A", "event")
        sm += seg_matter(g, "next_before_return", "tbin", f"+{lv:g}A", "event")
    sm = pd.DataFrame(sm)
    sm.to_csv(OUT / "SEGMENT_MATTERS_BY_STATE.csv", index=False)
    t = lap("segment_vs_state_dispersion", t)

    # ---- chop increment: do chop metrics move outcomes within the same location stratum?
    chop_rows = []
    for cp, g in cps.groupby("cp"):
        if cp not in (120, 180, 300, 480, 720, 1080):
            continue
        g = g[g.mfe_c < 2].copy()
        for ycol in ("ev_runner", "term_next", "term_loss"):
            e = g.groupby("loc")[ycol].transform("mean")
            for sv in ("cross_per_min_c", "eff_c", "frac_above_c", "swings_c", "since_new_mfe_c", "ret30", "ret60", "pullback_c", "mae_c"):
                try:
                    q = pd.qcut(g[sv].rank(method="first"), 3, labels=["T1_low", "T2_mid", "T3_high"])
                except ValueError:
                    continue
                for b in ("T1_low", "T3_high"):
                    m = (q == b).to_numpy()
                    chop_rows.append({"cp": cp, "outcome": ycol, "variable": sv, "tercile": b, "n": int(m.sum()),
                                      "raw_pct": 100 * g[ycol][m].mean(), "loc_expected_pct": 100 * e[m].mean(),
                                      "excess_pp": 100 * (g[ycol][m].mean() - e[m].mean())})
    chop = pd.DataFrame(chop_rows)
    chop.to_csv(OUT / "CHOP_INCREMENT_OVER_LOCATION.csv", index=False)
    # chop signature of phenotypes at equal age: trades alive at cp with running MFE < 0.5 -- eventual SLOW_FAIL vs develop later
    sig_ph = []
    for cp, g in cps.groupby("cp"):
        g = g[g.mfe_c < 0.5]
        for ph, h in g.groupby("phen"):
            sig_ph.append({"cp": cp, "eventual_phenotype": ph, "n": len(h), "cross_per_min_p50": h.cross_per_min_c.median(),
                           "swings_mean": h.swings_c.mean(), "eff_p50": h.eff_c.median(), "frac_above_p50": h.frac_above_c.median(),
                           "cur_p50": h.cur.median(), "mae_p50": h.mae_c.median(), "mfe_p50": h.mfe_c.median()})
    pd.DataFrame(sig_ph).to_csv(OUT / "UNDEVELOPED_CHOP_SIGNATURE_BY_EVENTUAL_PHENOTYPE.csv", index=False)
    t = lap("chop_measurement", t)

    # ---------------------------------------------------------------- write
    seg_tab.to_parquet(OUT / "PATH_ATLAS_SEGMENTS.parquet", index=False)
    keep = ["family", "dim", "segment", "parent", "N", "sessions", "sparse", *[f"pct_{p_}" for p_ in PHEN], "pct_RUNNER_1A", "pct_RUNNER_3A",
            "win_pct", "mean_gross_A", "dur_s_p50", "dur_s_p75", "dur_s_p90", "mfe_p50", "mae_p50",
            *[f"d_{o}" for o in MAT_PP], *[f"z_{o}" for o in MAT_PP], *[f"rep_{o}" for o in MAT_PP]]
    seg_tab[keep].to_csv(OUT / "PHENOTYPE_BY_SEGMENT.csv", index=False)
    seg_tab[["family", "dim", "segment", "N", "crossings_mean", "crossings_per_min_p50", "swings_mean", "efficiency_p50", "frac_above_p50",
             "frac_below_p50", "pullback_final_p50", "giveback_frac_p50", "t_mfe_p50", "mfe_to_term_p50"]].to_csv(OUT / "CHOP_METRICS_BY_SEGMENT.csv", index=False)
    trans.to_parquet(OUT / "PATH_ATLAS_TRANSITIONS.parquet", index=False)
    trans[trans.anchor_type == "clock"].dropna(axis=1, how="all").to_csv(OUT / "CLOCK_TRANSITIONS.csv", index=False)
    trans[trans.anchor_type == "event"].dropna(axis=1, how="all").to_csv(OUT / "EVENT_TRANSITIONS.csv", index=False)
    TIMINGS["total"] = round(time.time() - T_START, 1)
    (OUT / "RUN_TIMINGS.json").write_text(json.dumps({"timings_s": TIMINGS, "n_trades": len(tr), "n_segments": len(segs),
                                                        "n_shifts": N_SHIFTS, "first_touch_parity": par}, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(TIMINGS, indent=1))


if __name__ == "__main__":
    main()
