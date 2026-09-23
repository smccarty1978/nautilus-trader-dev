"""Post-entry path information vs mechanical nulls -- 2023 DEVELOPMENT sessions only; no model of any kind.

  build     exact first-touch anchors (+0.25 .. +1.5A, +2.0A for the giveback/terminal analysis), causal
            anchor features, the causal 1m flip-trigger primitive (dual-EMA engine replayed on catalog 1m
            bars, parity-checked against every audited flip), the fixed-price race outcome (+2A before -1A),
            the terminal race outcome (+2A before the opposite 1m flip), and two per-event simulated nulls:
              N2  fixed race  -- driftless (sign-symmetrised) 30 s block bootstrap of the preceding 60 min
                                 of real 1s bars, same OHLC touch semantics;
              N3  terminal    -- the SAME simulated paths aggregated to 1m bars and fed through the SAME
                                 dual-EMA engine, initialised with the real engine state at the anchor.
            N1 (analytic, driftless continuous) = (x + 1) / 3 needs no simulation.
  analyze   descriptive comparisons under the frozen DESIGN.json (written after build, before analyze).

Entry is never redefined (original T0 executable entry, atr_entry_1m). No final-20% row, label or bar is read:
bars are loaded per development session and the engine replay stops at the development boundary.
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
ROOT, BASE = REPO.parent, REPO.name.split("-")[0]
PATHSTUDY = ROOT / f"{BASE}-nq_post_entry_path_mechanism_2023" / "studies" / "nq_post_entry_path_mechanism_2023"
sys.path.insert(1, str(PATHSTUDY))
import path_mechanism as pm  # noqa: E402  (reused, audited loader + chain helpers; not modified)

OUT = HERE / "artifacts"
CATALOG = pm.CATALOG
BAR_1S, BAR_1M = pm.BAR_TYPE, "NQ.XCME-1-MINUTE-LAST-EXTERNAL"
NS = pm.NS
ANCHORS = [0.25, 0.5, 0.75, 1.0, 1.25, 1.5]
GIVEBACK_ANCHORS = [1.0, 1.5, 2.0]
ARM = {0.25: "fp_fav_0p25", 0.5: "fp_fav_0p50", 0.75: "fp_fav_0p75", 1.0: "fp_fav_1p00", 1.5: "fp_fav_1p50", 2.0: "fp_fav_2p00"}
DEV_END_UTC = "2023-10-17 22:00"      # Globex open of the first final-block session (2023-10-18); never read past it
ENGINE_WARMUP_START = "2022-12-20"
K_SIM, BLOCK, POOL_S, SIM_CAP_S, SIM_SEED = 64, 30, 3600, 7200, 20260926
A3, A9 = 2.0 / 4.0, 2.0 / 10.0


def sha_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def lbl(x):
    return f"{x:.2f}".replace(".", "p")


# ----------------------------------------------------------------------------- engine replay
def replay_engine():
    from features.trackers.regime_dual_ema import DualEmaRegimeTracker
    from utils.runner.data import CausalDataLoader
    bars = CausalDataLoader(CATALOG).load_bars(BAR_1M, pd.Timestamp(ENGINE_WARMUP_START, tz="UTC"), pd.Timestamp(DEV_END_UTC, tz="UTC"))
    tr = DualEmaRegimeTracker()
    rows = []
    for b in bars:
        u = tr.observe(b.high.as_double(), b.low.as_double(), b.close.as_double())
        rows.append((b.ts_init, u.regime, u.flipped, u.ema_short_low, u.ema_long_low, u.ema_short_high, u.ema_long_high,
                     b.high.as_double(), b.low.as_double(), b.close.as_double()))
    return pd.DataFrame(rows, columns=["ts", "regime", "flipped", "e3l", "e9l", "e3h", "e9h", "bh", "bl", "bc"])


# ----------------------------------------------------------------------------- simulation (vectorised over K paths)
def simulate(pool, rng, start_close, ep, d, atr, t0, close_ns, minute_end0, part, eng, lev2, levm1, mfe0=None):
    """pool: (n,4) rel O/H/L/C vs previous close. part: partial current minute (o,h,l,c or None).
    eng: (e3l,e9l,e3h,e9h). Returns per-path fixed outcome (1/0/nan) and terminal (reach2 before flip, giveback)."""
    K = K_SIM
    S = int(min((close_ns - t0) // NS, SIM_CAP_S))
    if S <= 0 or len(pool) < BLOCK:
        return None
    nblk = S // BLOCK + 2
    starts = rng.integers(0, len(pool) - BLOCK + 1, size=(K, nblk))
    signs = rng.choice([-1.0, 1.0], size=(K, nblk))
    idx = (starts[:, :, None] + np.arange(BLOCK)[None, None, :]).reshape(K, -1)[:, :S]
    sg = np.repeat(signs, BLOCK, axis=1)[:, :S]
    c = np.full(K, start_close)
    fixed = np.full(K, np.nan)
    e3l, e9l, e3h, e9h = (np.full(K, v) for v in eng)
    flipped = np.zeros(K, bool)
    reach2 = np.zeros(K, bool)
    exit_px = np.full(K, np.nan)
    need_exit = np.zeros(K, bool)
    if part is None:
        mo = mh = ml = None
    else:
        mo, mh, ml = np.full(K, part[0]), np.full(K, part[1]), np.full(K, part[2])
    econ = mfe0 is not None                                    # residual-capture extension: consumes NO extra random draws
    if econ:
        mfe = np.full(K, float(mfe0))
        flip_close = np.full(K, np.nan)
        flip_t = np.full(K, np.nan)
    t = t0
    for s in range(S):
        t += NS
        r = pool[idx[:, s]]
        g = sg[:, s]
        ro, rc = r[:, 0] * g, r[:, 3] * g
        rh = np.where(g > 0, r[:, 1], -r[:, 2])
        rl = np.where(g > 0, r[:, 2], -r[:, 1])
        O, H, L, C = c + ro, c + rh, c + rl, c + rc
        if need_exit.any():
            exit_px[need_exit] = O[need_exit]
            need_exit[:] = False
        hit2 = (H >= lev2) if d > 0 else (L <= lev2)
        hitm1 = (L <= levm1) if d > 0 else (H >= levm1)
        pend = np.isnan(fixed)
        fixed[pend & hit2 & ~hitm1] = 1.0
        fixed[pend & hitm1 & ~hit2] = 0.0
        fixed[pend & hit2 & hitm1] = -1.0                      # ambiguous same-bar
        if mo is None:
            mo, mh, ml = O.copy(), H.copy(), L.copy()
        else:
            mh, ml = np.maximum(mh, H), np.minimum(ml, L)
        minute_close = (t >= minute_end0) and ((t - minute_end0) % (60 * NS) == 0)
        live = ~flipped
        if econ:                                               # MFE runs through the flip bar inclusive
            fav_now = (H - ep) / atr if d > 0 else (ep - L) / atr
            mfe = np.where(live, np.maximum(mfe, fav_now), mfe)
        if minute_close:
            e3h = np.where(live, A3 * mh + (1 - A3) * e3h, e3h)
            e9h = np.where(live, A9 * mh + (1 - A9) * e9h, e9h)
            e3l = np.where(live, A3 * ml + (1 - A3) * e3l, e3l)
            e9l = np.where(live, A9 * ml + (1 - A9) * e9l, e9l)
            flip_now = live & (((C < e3l) & (C < e9l)) if d > 0 else ((C > e3h) & (C > e9h)))
            reach2 |= live & hit2 & ~flip_now                  # a touch at the flip close itself is not "before" the flip
            flipped |= flip_now
            need_exit |= flip_now
            if econ:
                flip_close[flip_now] = C[flip_now]
                flip_t[flip_now] = (t - t0) / NS
            mo = mh = ml = None
        else:
            reach2 |= live & hit2
        c = C
        if (~np.isnan(fixed)).all() and flipped.all() and not need_exit.any():
            break
    fixed[fixed < 0] = np.nan
    no_flip = ~flipped
    exit_px[no_flip] = c[no_flip]                              # truncated at the sim horizon / session close
    win = ((exit_px - ep) * d > 0)
    out = {"p_fixed": float(np.nanmean(fixed)) if (~np.isnan(fixed)).any() else np.nan,
           "fixed_resolved": int((~np.isnan(fixed)).sum()),
           "p_term_reach2": float(reach2.mean()),
           "p_giveback_given_reach2": float((reach2 & ~win).sum() / reach2.sum()) if reach2.any() else np.nan,
           "p_term_win": float(win.mean()), "sim_unflipped": int(no_flip.sum())}
    if econ:
        ok = flipped & ~np.isnan(exit_px) & ~need_exit          # paths that flipped AND filled at the next open
        pnl = (exit_px - ep) * d / atr
        gb = mfe - pnl
        dec = (flip_close - ep) * d / atr
        with np.errstate(invalid="ignore", divide="ignore"):
            frac = np.where(mfe > 0, gb / mfe, np.nan)
        m = ok
        out.update({"econ_n_flipped": int(m.sum()),
                    "econ_final_pnl": float(pnl[m].mean()) if m.any() else np.nan,
                    "econ_final_mfe": float(mfe[m].mean()) if m.any() else np.nan,
                    "econ_add_mfe": float((mfe[m] - mfe0).mean()) if m.any() else np.nan,
                    "econ_giveback": float(gb[m].mean()) if m.any() else np.nan,
                    "econ_frac_surrendered": float(np.nanmean(frac[m])) if m.any() and np.isfinite(frac[m]).any() else np.nan,
                    "econ_p_exit_below_entry": float((pnl[m] <= 0).mean()) if m.any() else np.nan,
                    "econ_p_giveback_ge_1A": float((gb[m] >= 1.0).mean()) if m.any() else np.nan,
                    "econ_boundary_component": float((mfe[m] - dec[m]).mean()) if m.any() else np.nan,
                    "econ_fill_gap": float((pnl[m] - dec[m]).mean()) if m.any() else np.nan,
                    "econ_term_s": float(flip_t[m].mean()) if m.any() else np.nan})
    return out


# ----------------------------------------------------------------------------- per-session build
def build_session(sess, part_df, eng_sess, seed, econ=False):
    from utils.runner.data import CausalDataLoader
    loader = CausalDataLoader(CATALOG)
    start = pd.Timestamp(int(part_df["t0_ns"].min()), tz="UTC") - pd.Timedelta(seconds=POOL_S + 60)
    end = pd.Timestamp(int(part_df["session_close_ts"].max()), tz="UTC") + pd.Timedelta(seconds=5)
    bars = loader.load_bars(BAR_1S, start, end)
    ti = np.fromiter((b.ts_init for b in bars), dtype=np.int64, count=len(bars))
    te = np.fromiter((b.ts_event for b in bars), dtype=np.int64, count=len(bars))
    op = np.fromiter((b.open.as_double() for b in bars), dtype=float, count=len(bars))
    hi = np.fromiter((b.high.as_double() for b in bars), dtype=float, count=len(bars))
    lo = np.fromiter((b.low.as_double() for b in bars), dtype=float, count=len(bars))
    cl = np.fromiter((b.close.as_double() for b in bars), dtype=float, count=len(bars))
    prev_c = np.concatenate([[op[0]], cl[:-1]])
    rel = np.column_stack([op - prev_c, hi - prev_c, lo - prev_c, cl - prev_c])
    ets_eng = eng_sess["ts"].to_numpy()
    rng = np.random.default_rng(seed)
    rng2 = np.random.default_rng(seed + 1_000_000)             # econ-only stream: never touches the original draws
    out, par = [], {lbl(x): [0, 0] for x in ARM}
    timeline, epar = [], {"exit_price": [0, 0], "pnl": [0, 0], "flip_close_vs_1m": [0, 0], "threshold_vs_engine": [0, 0]}
    ets_idx = {int(v): k for k, v in enumerate(ets_eng)}
    for r in part_df.itertuples():
        T0, T, d, atr, ep = int(r.t0_ns), int(r.terminal_ts), int(r.dir), float(r.atr), float(r.entry_price)
        close_ns = int(r.session_close_ts)
        i0 = int(np.searchsorted(ti, T0, side="right"))
        iend = int(np.searchsorted(ti, close_ns, side="right"))
        sti, sh, sl, sc = ti[i0:iend], hi[i0:iend], lo[i0:iend], cl[i0:iend]
        gaps = np.diff(np.concatenate([[int(te[i0])], sti]))
        gi = np.flatnonzero(gaps > pm.MAX_GAP_NS)
        first_gap = int(gi[0]) if len(gi) else len(sti)
        fav = (sh - ep) / atr if d > 0 else (ep - sl) / atr
        adv = (ep - sl) / atr if d > 0 else (sh - ep) / atr
        lev2, levm1 = ep + d * 2.0 * atr, ep - d * 1.0 * atr
        hit2 = (sh >= lev2) if d > 0 else (sl <= lev2)
        hitm1 = (sl <= levm1) if d > 0 else (sh >= levm1)
        curA = (sc - ep) * d / atr
        if econ:
            kT = int(np.searchsorted(sti, T, side="right")) - 1           # the flip bar's last 1s bar
            final_mfe = float(fav[: kT + 1].max())
            dec_loc = float(curA[kT])
            exit_px = float(op[i0 + kT + 1])
            epar["exit_price"][0] += 1
            epar["exit_price"][1] += int(exit_px != float(r.terminal_exit_price))
            epar["pnl"][0] += 1
            epar["pnl"][1] += int(abs((exit_px - ep) * d / atr - float(r.terminal_gross_atr)) > 1e-9)
            eT = eng_sess.iloc[ets_idx[T]]
            epar["flip_close_vs_1m"][0] += 1
            epar["flip_close_vs_1m"][1] += int(float(sc[kT]) != float(eT.bc))
            # trigger timeline over completed minutes inside the trade (pre-bar bound vs realized threshold)
            k_first = int(np.searchsorted(ets_eng, int(sti[0]), side="left"))
            for km in range(max(k_first, 2), ets_idx[T] + 1):
                prv, cur_r, pp = eng_sess.iloc[km - 1], eng_sess.iloc[km], eng_sess.iloc[km - 2]
                if d > 0:
                    pre = min(prv.e3l, prv.e9l)
                    thr = min(A3 * cur_r.bl + (1 - A3) * prv.e3l, A9 * cur_r.bl + (1 - A9) * prv.e9l)
                    by_thr = bool(cur_r.bc < thr)
                    pre_prev = min(pp.e3l, pp.e9l)
                else:
                    pre = max(prv.e3h, prv.e9h)
                    thr = max(A3 * cur_r.bh + (1 - A3) * prv.e3h, A9 * cur_r.bh + (1 - A9) * prv.e9h)
                    by_thr = bool(cur_r.bc > thr)
                    pre_prev = max(pp.e3h, pp.e9h)
                eng_flip = bool(cur_r.flipped) and int(cur_r.regime) == -d
                epar["threshold_vs_engine"][0] += 1
                epar["threshold_vs_engine"][1] += int(by_thr != eng_flip)
                kk = int(np.searchsorted(sti, int(cur_r.ts), side="right"))
                mfe_m = float(fav[:kk].max()) if kk else 0.0
                pre_rel = (pre - ep) * d / atr
                timeline.append({"regime_start_ns": r.regime_start_ns, "ts": int(cur_r.ts), "dir": d, "atr": atr,
                                 "close_A": (cur_r.bc - ep) * d / atr, "mfe_A": mfe_m,
                                 "ema3_boundary_A": ((prv.e3l if d > 0 else prv.e3h) - ep) * d / atr,
                                 "ema9_boundary_A": ((prv.e9l if d > 0 else prv.e9h) - ep) * d / atr,
                                 "pre_bar_bound_A": pre_rel, "realized_threshold_A": (thr - ep) * d / atr,
                                 "price_to_trigger_A": (cur_r.bc - pre) * d / atr, "mfe_to_trigger_A": mfe_m - pre_rel,
                                 "trigger_move_1bar_A": pre_rel - (pre_prev - ep) * d / atr,
                                 "gross_pnl_A": (cur_r.bc - ep) * d / atr, "flip_by_threshold": by_thr, "engine_flip": eng_flip})
        anchor_list = sorted(set(ANCHORS) | set(GIVEBACK_ANCHORS)) + ([0.0, 3.0] if econ else [])
        for x in anchor_list:
            lev = ep + d * x * atr
            touch = (sh >= lev) if d > 0 else (sl <= lev)
            idx = np.flatnonzero(touch[:first_gap])
            t_hit = int(sti[idx[0]]) if len(idx) else None
            if x in ARM:                                       # parity vs the audited kernel arm (all resolved rows)
                arm = ARM[x]
                disp = getattr(r, f"{arm}_disposition")
                par[lbl(x)][0] += 1
                if disp == "POSITIVE":
                    par[lbl(x)][1] += int(t_hit is None or (t_hit - int(te[i0])) / NS != getattr(r, f"{arm}_resolution_seconds"))
                else:
                    par[lbl(x)][1] += int(t_hit is not None)
            if x == 0.0:                                        # econ-only T0 anchor: the entry bar itself
                t_hit, idx = int(sti[0]), np.array([0])
            if t_hit is None or t_hit >= T:
                continue
            j = int(idx[0])
            ev = {"regime_start_ns": r.regime_start_ns, "session": sess, "anchor": x, "dir": d, "t_touch": t_hit}
            # --- causal anchor features (through the touch bar) ---
            ev["time_to_anchor_s"] = (t_hit - int(te[i0])) / NS
            ev["mfe_through"] = float(fav[: j + 1].max())
            ev["cur"] = float(curA[j])
            ev["pullback_from_mfe"] = ev["mfe_through"] - ev["cur"]
            ev["mae_before"] = max(float(adv[: j + 1].max()), 0.0)
            ev["adv1_before"] = int(hitm1[: j + 1].any())

            def cur_at(tq):
                k = int(np.searchsorted(sti, tq, side="right")) - 1
                return 0.0 if k < 0 else float(curA[k])
            for w in (15, 30, 60):
                ev[f"ret{w}"] = ev["cur"] - cur_at(t_hit - w * NS)
            closes = np.concatenate([[ep], sc[: j + 1]])
            steps = np.abs(np.diff(closes)).sum() / atr
            ev["path_eff"] = ev["cur"] / steps if steps > 0 else 0.0
            sgn = np.sign(curA[: j + 1])
            sgn = sgn[sgn != 0]
            ev["n_cross"] = int((np.diff(sgn) != 0).sum()) if len(sgn) > 1 else 0
            k60 = int(np.searchsorted(sti, t_hit - 60 * NS, side="right"))
            seg = np.concatenate([[ep if k60 == 0 else sc[k60 - 1]], sc[k60: j + 1]])
            ev["rv60"] = float(np.sqrt((np.diff(seg) ** 2).sum()) / atr)
            ev["accel"] = ev["ret15"] - (ev["ret60"] - ev["ret15"]) / 3.0
            ev["fav_share"] = ev["mfe_through"] / (ev["mfe_through"] + ev["mae_before"]) if (ev["mfe_through"] + ev["mae_before"]) > 0 else 0.5
            ct = pd.Timestamp(t_hit, tz="UTC").tz_convert("America/Chicago")
            ev["tod_min"] = ct.hour * 60 + ct.minute - (8 * 60 + 30)
            ev["time_to_close_s"] = (close_ns - t_hit) / NS
            # --- causal flip-trigger primitive: engine state after the last COMPLETED minute ---
            m = int(np.searchsorted(ets_eng, t_hit, side="right")) - 1
            e = eng_sess.iloc[m]
            trig = min(e.e3l, e.e9l) if d > 0 else max(e.e3h, e.e9h)
            ev["trig_rel_entry"] = (trig - ep) * d / atr
            ev["dist_to_trig"] = ev["cur"] - ev["trig_rel_entry"]
            m60 = int(np.searchsorted(ets_eng, t_hit - 60 * NS, side="right")) - 1
            e60 = eng_sess.iloc[m60]
            trig60 = min(e60.e3l, e60.e9l) if d > 0 else max(e60.e3h, e60.e9h)
            ev["trig_move60"] = ev["trig_rel_entry"] - (trig60 - ep) * d / atr
            ev["engine_regime_ok"] = int(e.regime == d)
            # --- real outcomes ---
            fx = np.nan
            if not ev["adv1_before"] or x >= 2.0:
                h2, hm = hit2[j:], hitm1[j:]
                k2 = int(np.argmax(h2)) if h2.any() else None
                km = int(np.argmax(hm)) if hm.any() else None
                if k2 is None and km is None:
                    fx = np.nan                               # unresolved by the session close
                elif km is None or (k2 is not None and k2 < km):
                    fx = 1.0
                elif k2 is None or km < k2:
                    fx = 0.0
                else:
                    fx = -1.0                                  # same-bar ambiguous
            ev["fixed_outcome"] = fx if x < 2.0 else np.nan
            ev["fixed_eligible"] = int(x < 2.0 and not ev["adv1_before"])
            ev["term_reach2"] = int(r.reach_fav_2p0)
            ev["win"] = int(r.win)
            # --- simulated nulls from the touch bar's close ---
            decided = bool(x < 2.0 and hit2[j])                # the touch bar itself already reached +2A
            pool_idx = (ti > t_hit - POOL_S * NS) & (ti <= t_hit)
            pool = rel[pool_idx]
            minute_end0 = int(ets_eng[m]) + 60 * NS
            ib = int(np.searchsorted(ti, int(ets_eng[m]), side="right"))
            ie = i0 + j + 1
            part = (op[ib], hi[ib:ie].max(), lo[ib:ie].min()) if ie > ib else None
            original = x in ANCHORS or x in GIVEBACK_ANCHORS
            mfe0 = ev["mfe_through"] if econ else None
            sim = None if (decided or not original) else simulate(pool, rng, float(sc[j]), ep, d, atr, t_hit, close_ns, minute_end0, part,
                                                                  (e.e3l, e.e9l, e.e3h, e.e9h), lev2, levm1, mfe0)
            if decided:
                sim = {"p_fixed": 1.0 if not hitm1[j] else np.nan, "fixed_resolved": K_SIM, "p_term_reach2": 1.0,
                       "p_giveback_given_reach2": np.nan, "p_term_win": np.nan, "sim_unflipped": 0}
            if econ and (decided or not original):
                s2 = simulate(pool, rng2, float(sc[j]), ep, d, atr, t_hit, close_ns, minute_end0, part,
                              (e.e3l, e.e9l, e.e3h, e.e9h), lev2, levm1, mfe0)
                if s2 is not None:
                    keep = {k: v for k, v in s2.items() if k.startswith("econ_")}
                    if not original:
                        keep.update({k: v for k, v in s2.items() if not k.startswith("econ_")})
                    sim = {**({} if sim is None else sim), **keep}
            if econ:
                ev["real_final_pnl"] = float(r.terminal_gross_atr)
                ev["real_final_mfe"] = final_mfe
                ev["real_add_mfe"] = final_mfe - ev["mfe_through"]
                ev["real_giveback"] = final_mfe - ev["real_final_pnl"]
                ev["real_frac_surrendered"] = ev["real_giveback"] / final_mfe if final_mfe > 0 else np.nan
                ev["real_exit_below_entry"] = int(ev["real_final_pnl"] <= 0)
                ev["real_giveback_ge_1A"] = int(ev["real_giveback"] >= 1.0)
                ev["real_boundary_component"] = final_mfe - dec_loc
                ev["real_fill_gap"] = ev["real_final_pnl"] - dec_loc
                ev["real_term_s"] = (T - t_hit) / NS
                ev["mfe_to_trig"] = ev["mfe_through"] - ev["trig_rel_entry"]
                for back in (1, 2):
                    if m - back >= 0:
                        eb = eng_sess.iloc[m - back]
                        tb = min(eb.e3l, eb.e9l) if d > 0 else max(eb.e3h, eb.e9h)
                        ev[f"catchup{back}"] = ev["trig_rel_entry"] - (tb - ep) * d / atr
                    else:
                        ev[f"catchup{back}"] = np.nan
            for k2, v2 in (sim or {}).items():
                ev[f"null_{k2}"] = v2
            ev["null_decided_by_touch_bar"] = int(decided)
            out.append(ev)
    if econ:
        return out, par, timeline, epar
    return out, par


def stage_build(workers: int) -> None:
    from joblib import Parallel, delayed
    f, pop, split = pm.load_dev()
    tl = pd.read_parquet(PATHSTUDY / "artifacts" / "TRADE_EVENT_TIMELINE.parquet")
    tl_sha = sha_file(PATHSTUDY / "artifacts" / "TRADE_EVENT_TIMELINE.parquet")
    eng = replay_engine()
    flips = eng[eng["flipped"]]
    fset = dict(zip(flips["ts"].astype("int64"), flips["regime"]))
    eng_par = {"t0_flip_reproduced": int(sum(fset.get(int(s)) == dd for s, dd in zip(tl.regime_start_ns, tl.dir))),
               "terminal_flip_reproduced": int(sum(int(t) in fset for t in tl.terminal_ts)), "trades": len(tl)}
    if eng_par["t0_flip_reproduced"] != len(tl) or eng_par["terminal_flip_reproduced"] != len(tl):
        raise SystemExit(f"INVALID_EXPERIMENT: engine replay parity failed {eng_par}")
    arms = pop[["regime_start_ns", "session_close_ts"] + [c for a in ARM.values() for c in (f"{a}_disposition", f"{a}_resolution_seconds")]]
    tj = tl.merge(arms, on="regime_start_ns", how="left")
    jobs = []
    for i, (sess, part) in enumerate(tj.groupby("session")):
        lo_ts = int(part["t0_ns"].min()) - (POOL_S + 120) * NS
        hi_ts = int(part["session_close_ts"].max())
        es = eng[(eng["ts"] >= lo_ts - 3600 * NS) & (eng["ts"] <= hi_ts)].reset_index(drop=True)
        jobs.append((sess, part, es, SIM_SEED + i))
    res = Parallel(n_jobs=workers, verbose=5)(delayed(build_session)(*a) for a in jobs)
    events = pd.DataFrame([e for evs, _ in res for e in evs])
    par = {}
    for _, p in res:
        for k, (n, mm) in p.items():
            par.setdefault(k, [0, 0])
            par[k][0] += n
            par[k][1] += mm
    blocks = {s: "discovery" for s in split["blocks"]["development_train"]["session_list"]}
    blocks.update({s: "replication" for s in split["blocks"]["development_validation"]["session_list"]})
    events["block"] = events["session"].map(blocks)
    OUT.mkdir(parents=True, exist_ok=True)
    events.to_csv(OUT / "EVENT_LEVEL.csv", index=False)
    events.to_parquet(OUT / "EVENT_LEVEL.parquet", index=False)
    audit = {"kind": "mechanical_null_build_audit", "trades": len(tl), "events": len(events),
             "events_by_anchor": events["anchor"].value_counts().sort_index().to_dict(),
             "reused": {"TRADE_EVENT_TIMELINE.parquet": tl_sha, "fields_reused": ["t0_ns", "entry_price", "entry_ts", "atr", "terminal_ts", "win", "reach_fav_2p0", "dir", "session"]},
             "newly_computed_from_1s": ["anchor first touches incl. +0.25/+0.75/+1.25", "all anchor features", "fixed-race outcome", "N2/N3 nulls"],
             "engine_replay": {"tracker": "features/trackers/regime_dual_ema.py DualEmaRegimeTracker(3, 9, 14) on NQ.XCME-1-MINUTE-LAST-EXTERNAL",
                               "window": [ENGINE_WARMUP_START, DEV_END_UTC], "parity": eng_par},
             "flip_trigger_definition": "long: min(EMA3_low, EMA9_low); short: max(EMA3_high, EMA9_high); engine state after the last COMPLETED 1m bar at or before the instant. A flip needs a completed 1m close beyond BOTH EMAs after they absorb that bar's own low/high, so this level is the loosest close that could flip; intrabar prices never flip.",
             "first_touch_parity_vs_kernel_arms": {k: {"compared": n, "mismatch": mm} for k, (n, mm) in par.items()},
             "not_kernel_verified": ["+1.25A (no kernel arm)"],
             "engine_state_matches_trade_dir_at_anchor": float(events["engine_regime_ok"].mean()),
             "null_sim": {"K": K_SIM, "block_s": BLOCK, "pool": f"the preceding {POOL_S} s of real 1s bars (causal), sign-symmetrised per block", "cap_s": SIM_CAP_S, "seed": SIM_SEED},
             "final_20pct_loaded": False}
    audit["PASS"] = all(mm == 0 for _, mm in par.values()) and audit["engine_state_matches_trade_dir_at_anchor"] == 1.0
    (OUT / "BUILD_AUDIT.json").write_text(json.dumps(audit, indent=2, sort_keys=True, default=pm._jsonable) + "\n", encoding="utf-8")
    print(json.dumps(audit, indent=1, default=pm._jsonable))
    if not audit["PASS"]:
        raise SystemExit("INVALID_EXPERIMENT: build parity failed")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["build"])
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()
    stage_build(a.workers)
