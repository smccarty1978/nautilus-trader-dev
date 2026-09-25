"""Challenge episodes inside active 1m V_A regimes, their causal context, responses and outcomes.

Inputs (extract.py, parity-checked): artifacts/LIFECYCLE_1S.parquet, LIFECYCLE_1M.parquet, REGIME_LEDGER.parquet and the
audited timeline (entry, exit, ATR, blocks). Definitions: REGIME_LIFECYCLE_DEFINITION.md, CHALLENGE_FEATURE_DEFINITIONS.md.

All prices are in FAVOURABLE coordinates x = dir * price (a long's high is favourable; a short's low is), so every
regime reads like a long. A = audited entry ATR (atr_entry_1m) of the regime.

Episode (threshold k): armed at regime start; onset = first 1s bar whose adverse extreme is >= k*A below the running
favourable extreme M (M starts at the flip close P0); the episode resolves NEW_EXTREME when a later 1s bar trades above
the onset extreme M_c, or TRANSITION when the regime flips first. A new extreme re-arms; deepening inside an open
episode is the same episode.

Causality at onset time tc (the onset bar's ts_init): 1s bars with ts_init <= tc, 1m bars with ts_init <= tc (their
EMA state is the last completed engine update), HTF state as of the last HTF bucket closed at or before tc, ledger
regimes that ended at or before S. Outcomes use bars after tc through the terminal flip T and the audited exit.

    python studies/nq_regime_challenge_lifecycle_2023/challenge.py
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASE = HERE.parents[1].name.split("-")[0]
OUT = HERE / "artifacts"
TL = ROOT / f"{BASE}-nq_post_entry_path_mechanism_2023" / "studies" / "nq_post_entry_path_mechanism_2023" / "artifacts" / "TRADE_EVENT_TIMELINE.parquet"
SPLIT = ROOT / f"{BASE}-nq_target_a_constrained_stationary_2023" / "studies" / "nq_target_a_constrained_stationary_2023" / "artifacts" / "TEMPORAL_SPLIT_2023.json"
NS = 1_000_000_000
KS = (0.25, 0.5, 0.75, 1.0, 1.5, 2.0)          # 1.5 / 2.0 = multi-candle, human-visible pullbacks
CP_KS = (0.5, 1.0)
CLOCK = (15, 30, 60, 120, 180, 300, 480, 720)
COST_PTS = 0.725


def first(mask: np.ndarray, start: int = 0) -> int:
    """Index of the first True at or after start, -1 if none."""
    if start >= len(mask):
        return -1
    i = int(np.argmax(mask[start:]))
    return start + i if mask[start + i] else -1


def run_len_tail(b: np.ndarray) -> int:
    """Number of consecutive True values at the end of b."""
    if len(b) == 0 or not b[-1]:
        return 0
    z = np.flatnonzero(~b)
    return len(b) if len(z) == 0 else len(b) - 1 - int(z[-1])


def max_run(b: np.ndarray) -> int:
    best = cur = 0
    for x in b:
        cur = cur + 1 if x else 0
        best = max(best, cur)
    return best


def bar_stats(o, h, l, c, A, prefix):
    """1m candle morphology in favourable coordinates (o,h,l,c already favourable: h >= o,c >= l)."""
    n = len(c)
    if n == 0:
        return {f"{prefix}_{k}": np.nan for k in ("bars", "body_mean_pts", "body_med_pts", "dir_frac", "big_frac", "max_consec_dir",
                                                    "overlap", "wick_frac", "range_mean_pts")} | {f"{prefix}_bars": 0}
    body = c - o
    rng = np.maximum(h - l, 1e-9)
    ov = np.nan
    if n >= 2:
        inter = np.minimum(h[1:], h[:-1]) - np.maximum(l[1:], l[:-1])
        ov = float(np.mean(np.clip(inter, 0, None) / np.minimum(rng[1:], rng[:-1])))
    return {f"{prefix}_bars": n, f"{prefix}_body_mean_pts": float(body.mean()), f"{prefix}_body_med_pts": float(np.median(body)),
            f"{prefix}_dir_frac": float((body > 0).mean()), f"{prefix}_big_frac": float((np.abs(body) >= 0.5 * A).mean()),
            f"{prefix}_max_consec_dir": max_run(body > 0), f"{prefix}_overlap": ov,
            f"{prefix}_wick_frac": float(np.mean(1 - np.abs(body) / rng)), f"{prefix}_range_mean_pts": float(rng.mean())}


def main() -> None:
    t_start = time.time()
    tl = pd.read_parquet(TL).sort_values("t0_ns").reset_index(drop=True)
    split = json.loads(SPLIT.read_text(encoding="utf-8"))
    blk_a = set(split["blocks"]["development_train"]["session_list"])
    tl["block"] = np.where(tl.session.isin(blk_a), "A", "B")
    tl["exit_px"] = tl.entry_price + tl.dir * tl.terminal_gross_atr * tl.atr
    life = pd.read_parquet(OUT / "LIFECYCLE_1S.parquet")
    m = pd.read_parquet(OUT / "LIFECYCLE_1M.parquet")
    led = pd.read_parquet(OUT / "REGIME_LEDGER.parquet")
    mts = m.ts.to_numpy()
    M1 = {k: m[k].to_numpy() for k in ("o", "h", "l", "c", "v", "e3h", "e9h", "e3l", "e9l") + tuple(
        f"{p}_{tf}" for tf in ("5m", "15m", "1h") for p in ("dir", "start", "e3h", "e9h", "e3l", "e9l"))}
    led_start, led_end = led.start_ns.to_numpy(), led.end_ns.to_numpy()
    groups = {k: g for k, g in life.groupby("regime_start_ns", sort=False)}
    t_load = time.time() - t_start

    ev_rows, cp_rows = [], []
    t1 = time.time()
    for r in tl.itertuples():
        S, T, d, A = int(r.regime_start_ns), int(r.terminal_ts), int(r.dir), float(r.atr)
        g = groups[S]
        t = g.t.to_numpy().astype(np.int64)
        if d > 0:
            fo, fh, fl, fc = (g[k].to_numpy().astype(float) for k in ("o", "h", "l", "c"))
        else:
            fo, fh, fl, fc = (-g[k].to_numpy().astype(float) for k in ("o", "l", "h", "c"))
        v = g.v.to_numpy().astype(float)
        iS = int(np.searchsorted(mts, S))                         # 1m bar that closed at S (the detection bar)
        P0 = d * M1["c"][iS]
        M = np.maximum.accumulate(np.maximum(fh, P0))
        D = (M - fl) / A
        exit_x = d * r.exit_px
        # regime-level context fixed at S: prior ledger regimes that ended at or before S (last 6), in favourable coords
        j = int(np.searchsorted(led_end, S, side="right"))
        prior = led.iloc[max(0, j - 6):j]
        turn_x = d * np.concatenate([prior.fav_ext.to_numpy(), prior.start_close.to_numpy()])
        same = prior[prior.dir == d]
        prev_same_ext = d * same.fav_ext.iat[-1] if len(same) else np.nan
        # 1m bars of this regime window (engine state), favourable coordinates
        ia, ib = int(np.searchsorted(mts, S - 60 * 60 * NS, side="right")), int(np.searchsorted(mts, T, side="right"))
        mo, mh, ml, mc = ((M1["o"], M1["h"], M1["l"], M1["c"]) if d > 0 else (-M1["o"], -M1["l"], -M1["h"], -M1["c"]))
        lower3 = (M1["e3l"] if d > 0 else -M1["e3h"])
        lower9 = (M1["e9l"] if d > 0 else -M1["e9h"])
        upper9 = (M1["e9h"] if d > 0 else -M1["e9l"])
        mid3 = d * (M1["e3h"] + M1["e3l"]) / 2
        mid9 = d * (M1["e9h"] + M1["e9l"]) / 2
        thr = np.minimum(lower3, lower9)                           # a completed close below both flips the regime
        tf_state = {tf: (d * M1[f"dir_{tf}"], M1[f"start_{tf}"]) for tf in ("5m", "15m", "1h")}
        thr5 = (np.minimum(M1["e3l_5m"], M1["e9l_5m"]) if d > 0 else -np.maximum(M1["e3h_5m"], M1["e9h_5m"]))

        for k in KS:
            s, n, prev = 0, 0, None
            while True:
                ic = first(D >= k, s)
                if ic < 0:
                    break
                n += 1
                Mc = M[ic]
                iM = first(M >= Mc)                              # when the onset extreme was first made
                pc = Mc - k * A                                  # touch level
                jr = first(fh > Mc, ic + 1)
                end = jr if jr >= 0 else len(t)
                seg_lo = fl[ic:end]
                ideep = ic + int(np.argmin(seg_lo)) if len(seg_lo) else ic
                max_depth = (Mc - fl[ideep]) / A
                tc = S + int(t[ic]) * NS
                # ---- impulse: from the lowest point since the previous episode's deepest point (or regime start) to iM
                anchor = prev["ideep"] if prev is not None else 0
                if iM > anchor:
                    ilo = anchor + int(np.argmin(fl[anchor:iM + 1]))
                    imp_lo = min(fl[ilo], P0) if prev is None else fl[ilo]
                else:
                    ilo, imp_lo = anchor, (P0 if prev is None else fl[anchor])
                t_imp0 = int(t[ilo]) if prev is not None or iM > 0 else 0
                imp_pts = Mc - imp_lo
                imp_dur = max(int(t[iM]) - t_imp0, 1)
                path = np.abs(np.diff(fc[ilo:iM + 1])).sum()
                vol_imp = v[ilo:iM + 1].sum() / imp_dur
                half = ilo + (iM - ilo) // 2
                v1, v2 = v[ilo:half + 1].sum(), v[half + 1:iM + 1].sum()
                # ---- challenge window iM..ic
                ch_dur = max(int(t[ic] - t[iM]), 1)
                ch_path = np.abs(np.diff(fc[iM:ic + 1])).sum()
                vol_ch = v[iM:ic + 1].sum() / ch_dur

                def ret(x):
                    q = int(np.searchsorted(t, t[ic] - x, side="right")) - 1
                    return (fc[ic] - (fc[q] if q >= 0 else P0)) / A
                w0 = max(0, int(np.searchsorted(t, t[ic] - 120)))
                rv120 = float(np.sqrt(np.sum(np.diff(fc[w0:ic + 1]) ** 2)))
                # ---- 1m bars completed at or before tc
                jb = int(np.searchsorted(mts, tc, side="right")) - 1
                imp_bars = np.arange(max(int(np.searchsorted(mts, S + t_imp0 * NS, side="right")), ia), min(int(np.searchsorted(mts, S + int(t[iM]) * NS + 60 * NS, side="right")), jb + 1))
                ch_bars = np.arange(int(np.searchsorted(mts, S + int(t[iM]) * NS, side="right")), jb + 1)
                recent = np.arange(max(ia, jb - 9), jb + 1)
                body_recent = mc[recent] - mo[recent]
                row = {"regime_start_ns": S, "k": k, "n": n, "tc_ns": tc, "t_onset_s": int(t[ic]), "dir": d, "atr_pts": A,
                       # A maturity
                       "mfe_A": (Mc - P0) / A, "mfe_pts": Mc - P0, "mae_A": (P0 - min(fl[:ic + 1].min(), P0)) / A,
                       "loc_close_A": (fc[ic] - P0) / A, "loc_touch_A": (pc - P0) / A, "since_ext_s": int(t[ic] - t[iM]),
                       "n_prior": n - 1, "deepest_prior_A": prev["deepest_so_far"] if prev is not None else np.nan,
                       "since_prev_onset_s": int(t[ic]) - prev["t_onset"] if prev is not None else np.nan,
                       "frac_time_below_0p25": float(np.mean(D[:ic + 1] >= 0.25)),
                       "prog_last_A": (Mc - prev["Mc"]) / A if prev is not None else np.nan,
                       "prev_rec_time_s": prev["t_res"] if prev is not None else np.nan,
                       "prev_max_depth_A": prev["max_depth"] if prev is not None else np.nan,
                       # B impulse
                       "imp_A": imp_pts / A, "imp_pts": imp_pts, "imp_dur_s": imp_dur, "imp_eff": imp_pts / path if path > 0 else np.nan,
                       "imp_speed_A_min": imp_pts / A / (imp_dur / 60), "imp_vol_rate": vol_imp,
                       "imp_vol_accel": (v2 / max(iM - half, 1)) / (v1 / max(half - ilo + 1, 1)) if v1 > 0 else np.nan,
                       **bar_stats(mo[imp_bars], mh[imp_bars], ml[imp_bars], mc[imp_bars], A, "imp"),
                       # C challenge morphology
                       "depth_pts": k * A, "retrace_frac": k * A / imp_pts if imp_pts > 0 else np.nan, "ch_dur_s": ch_dur,
                       "ch_vel_A_min": k / (ch_dur / 60), "ch_eff": (Mc - fc[ic]) / ch_path if ch_path > 0 else np.nan,
                       "ch_vol_rate": vol_ch, "ch_vol_ratio": vol_ch / vol_imp if vol_imp > 0 else np.nan,
                       "ret15_A": ret(15), "ret30_A": ret(30), "ret60_A": ret(60), "ret120_A": ret(120), "rv120_pts": rv120,
                       "ch_adv_bars": int((mc[ch_bars] < mo[ch_bars]).sum()), "consec_adv_bars": run_len_tail(body_recent < 0),
                       "max_adv_bar_A": float(np.max(mo[ch_bars] - mc[ch_bars]) / A) if len(ch_bars) else np.nan,
                       **bar_stats(mo[ch_bars], mh[ch_bars], ml[ch_bars], mc[ch_bars], A, "ch"),
                       # D EMA / band geometry at the last completed 1m bar
                       "dist_flip_A": (fc[ic] - thr[jb]) / A, "dist_flip_touch_A": (pc - thr[jb]) / A,
                       "pen_ema3": float(fc[ic] < lower3[jb]), "pen_ema9": float(fc[ic] < lower9[jb]),
                       "closes_thru_ema3_last3": int(np.sum(mc[jb - 2:jb + 1] < lower3[jb - 2:jb + 1])),
                       "band_w_A": (M1["e9h"][jb] - M1["e9l"][jb]) / A, "band_w_chg5": (M1["e9h"][jb] - M1["e9l"][jb]) / (M1["e9h"][jb - 5] - M1["e9l"][jb - 5]),
                       "band_pos": (fc[ic] - lower9[jb]) / (upper9[jb] - lower9[jb]) if upper9[jb] != lower9[jb] else np.nan,
                       "slope3_A": (mid3[jb] - mid3[jb - 3]) / A, "slope9_A": (mid9[jb] - mid9[jb - 3]) / A,
                       "slope9_chg_A": ((mid9[jb] - mid9[jb - 3]) - (mid9[jb - 3] - mid9[jb - 6])) / A, "ema_sep_A": (mid3[jb] - mid9[jb]) / A,
                       # E level memory
                       "n_turns_0p25": int(np.sum(np.abs(turn_x - pc) <= 0.25 * A)), "n_turns_0p5": int(np.sum(np.abs(turn_x - pc) <= 0.5 * A)),
                       "n_turns_1p0": int(np.sum(np.abs(turn_x - pc) <= 1.0 * A)),
                       "ext_vs_prev_same_regime_A": (Mc - prev_same_ext) / A,
                       "stalled_at_prior_regime_ext": float(abs(Mc - prev_same_ext) <= 0.25 * A) if np.isfinite(prev_same_ext) else np.nan,
                       "touch_vs_prev_deep_A": (pc - prev["deep_x"]) / A if prev is not None else np.nan,
                       "n_prior_deeps_near_touch_0p25": sum(abs(x - pc) <= 0.25 * A for x in (prev["deeps"] if prev else [])),
                       "n_prior_deeps_near_touch_0p5": sum(abs(x - pc) <= 0.5 * A for x in (prev["deeps"] if prev else [])),
                       "n_marginal_ext": sum(1 for p in (prev["progs"] if prev else []) if p < 0.25),
                       # G session / volatility (1m bars up to jb)
                       "rv30_pts": float(np.std(np.diff(M1["c"][max(0, jb - 30):jb + 1]))), "vol30_per_min": float(M1["v"][max(0, jb - 29):jb + 1].mean()),
                       }
                # F HTF evolution
                for tf, (al, st_) in tf_state.items():
                    row[f"{tf}_aligned"] = float(al[jb] == 1)
                    row[f"{tf}_aligned_at_start"] = float(al[iS] == 1)
                    row[f"{tf}_flips_since_start"] = int(np.sum(np.diff(st_[iS:jb + 1]) != 0))
                    row[f"{tf}_age_min"] = (tc - st_[jb]) / NS / 60
                row["5m_dist_flip_A"] = (fc[ic] - thr5[jb]) / A
                # ---- outcomes from onset
                hi_after = fh[ic + 1:].max() if ic + 1 < len(t) else -np.inf
                row.update({"res_new_ext": float(jr >= 0), "t_res_s": int(t[jr] - t[ic]) if jr >= 0 else np.nan,
                            "max_depth_A": max_depth, "deepen_0p5": float(max_depth >= k + 0.5), "deepen_1p0": float(max_depth >= k + 1.0),
                            "rec50": float(first(fh >= Mc - 0.5 * k * A, ic + 1) >= 0), "rec75": float(first(fh >= Mc - 0.25 * k * A, ic + 1) >= 0),
                            "new_prog_A": (max(hi_after, Mc) - Mc) / A if jr >= 0 else 0.0,
                            "rem_mfe_A": (max(hi_after, pc) - pc) / A, "hold_A": (exit_x - pc) / A,
                            "t_to_flip_s": (T - tc) / NS, "final_gross_A": r.terminal_gross_atr, "block": r.block, "session": r.session})
                for x in (0.25, 0.5, 1.0, 2.0):
                    row[f"new_{str(x).replace('.', 'p')}A"] = float(row["new_prog_A"] >= x)
                ev_rows.append(row)
                # ---- response checkpoints (primary threshold only)
                if k in CP_KS:
                    alive_end = len(t)
                    def cp_candles(t_ext_ns, jj):
                        bars = np.arange(int(np.searchsorted(mts, t_ext_ns, side="right")), jj + 1)
                        body = mc[bars] - mo[bars]
                        below3 = mc[bars] < lower3[bars]
                        return {"cp_bars_since_ext": len(bars), "cp_adv_bars": int((body < 0).sum()),
                                "cp_adv_bar_frac": float((body < 0).mean()) if len(bars) else np.nan,
                                "cp_consec_adv": run_len_tail(body < 0), "cp_closes_below_ema3": int(below3.sum()),
                                "cp_ema3_recaptured": float(below3.any() and not below3[-1]),
                                "cp_max_adv_body_A": float((-body).max() / A) if len(bars) else np.nan,
                                "cp_overlap": bar_stats(mo[bars], mh[bars], ml[bars], mc[bars], A, "x")["x_overlap"],
                                "cp_band_w_chg": (M1["e9h"][jj] - M1["e9l"][jj]) / (M1["e9h"][jb] - M1["e9l"][jb]),
                                "cp_slope9_A": (mid9[jj] - mid9[jj - 3]) / A, "cp_ema_sep_A": (mid3[jj] - mid9[jj]) / A}

                    def cp_row(ix, label, kind):
                        if ix < 0 or ix >= alive_end:
                            return
                        tcp = S + int(t[ix]) * NS
                        jj = int(np.searchsorted(mts, tcp, side="right")) - 1
                        deep_so_far = fl[ic:ix + 1].min()
                        resolved = jr >= 0 and jr <= ix
                        rr = {"regime_start_ns": S, "n": n, "cp": label, "cp_kind": kind, "cp_s": int(t[ix] - t[ic]), "status": "RESOLVED" if resolved else "OPEN",
                              "depth_now_A": (Mc - fc[ix]) / A, "max_depth_so_far_A": (Mc - deep_so_far) / A,
                              "rec_frac": (fc[ix] - deep_so_far) / (Mc - deep_so_far) if Mc > deep_so_far else np.nan,
                              "dist_flip_A": (fc[ix] - thr[jj]) / A, "above_ema3": float(fc[ix] >= lower3[jj]),
                              "recaptured_ema3": float(fc[ix] >= lower3[jj] and np.any(mc[max(jb - 1, ia):jj + 1] < lower3[max(jb - 1, ia):jj + 1])),
                              "n_touch_crosses": int(np.sum(np.diff((fl[ic:ix + 1] <= pc).astype(int)) == 1)),
                              "vol_rate_since": v[ic:ix + 1].sum() / max(int(t[ix] - t[ic]), 1), "imp_vol_rate": vol_imp,
                              "new_lows_0p1": int(np.sum(np.diff(np.minimum.accumulate(fl[ic:ix + 1])) < -0.1 * A)),
                              # completed 1m candles since the favourable extreme (what the chart shows by now)
                              **cp_candles(S + int(t[iM]) * NS, jj),
                              "mfe_A": (Mc - P0) / A, "age_s": int(t[ix]), "atr_pts": A, "k": k,
                              "cp_new_ext": float(jr >= 0 and jr > ix), "cp_hold_A": (exit_x - fc[ix]) / A,
                              "cp_rem_mfe_A": ((fh[ix + 1:].max() if ix + 1 < len(t) else fc[ix]) - fc[ix]) / A,
                              "cp_t_to_flip_s": (T - tcp) / NS, "block": r.block}
                        cp_rows.append(rr)
                    cp_rows_before = len(cp_rows)
                    for x in CLOCK:
                        q = int(np.searchsorted(t, t[ic] + x, side="right")) - 1
                        if t[ic] + x <= (T - S) // NS:
                            cp_row(q, f"+{x}s", "clock")
                    run_lo = np.minimum.accumulate(fl[ic:end]) if end > ic else np.array([])
                    if len(run_lo):
                        span = Mc - run_lo
                        rec = (fc[ic:end] - run_lo) / np.where(span > 0, span, np.nan)
                        for f_, lab in ((0.5, "EV_REC50"), (0.75, "EV_REC75")):
                            q = first(rec >= f_)
                            cp_row(ic + q if q >= 0 else -1, lab, "event")
                        q = first((Mc - fl[ic:end]) / A >= k + 0.5)
                        cp_row(ic + q if q >= 0 else -1, "EV_DEEPEN_0p5", "event")
                        q = first((mc[int(np.searchsorted(mts, tc, side="right")):ib + 1] < lower3[int(np.searchsorted(mts, tc, side="right")):ib + 1]))
                        if q >= 0:                        # first completed 1m close through EMA3-low after onset (no flip yet)
                            tq = (mts[int(np.searchsorted(mts, tc, side="right")) + q] - S) // NS
                            cp_row(int(np.searchsorted(t, tq, side="right")) - 1 if tq < (T - S) // NS else -1, "EV_CLOSE_THRU_EMA3", "event")
                        q = first(fh[ic:end] >= Mc - 0.1 * A)
                        cp_row(ic + q if q >= 0 else -1, "EV_MFE_RETEST", "event")
                    for rr in cp_rows[cp_rows_before:]:
                        rr["episode_depth_final_A"] = max_depth
                # ---- carry sequence memory
                deeps = (prev["deeps"] if prev else []) + [fl[ideep]]
                progs = (prev["progs"] if prev else []) + ([(Mc - prev["Mc"]) / A] if prev else [])
                prev = {"Mc": Mc, "ideep": ideep, "deep_x": fl[ideep], "t_onset": int(t[ic]), "max_depth": max_depth,
                        "t_res": int(t[jr] - t[ic]) if jr >= 0 else np.nan,
                        "deepest_so_far": max(max_depth, prev["deepest_so_far"]) if prev else max_depth, "deeps": deeps, "progs": progs}
                if jr < 0:
                    break
                s = jr
    t_ev = time.time() - t1
    ev = pd.DataFrame(ev_rows)
    et = pd.to_datetime(ev.tc_ns, unit="ns", utc=True).dt.tz_convert("America/New_York")
    ev["min_since_open"] = (et.dt.hour * 60 + et.dt.minute + et.dt.second / 60) - 570
    ev["min_to_close"] = 960 - (et.dt.hour * 60 + et.dt.minute + et.dt.second / 60)
    ev["opening_drive"] = (ev.min_since_open < 30).astype(float)
    ev["n_challenges_regime"] = ev.groupby(["regime_start_ns", "k"]).n.transform("max")
    ev["is_last"] = (ev.n == ev.n_challenges_regime).astype(float)
    cp = pd.DataFrame(cp_rows)
    ev.to_parquet(OUT / "CHALLENGE_EVENTS.parquet", index=False)
    cp.to_parquet(OUT / "CHALLENGE_CHECKPOINTS.parquet", index=False)
    run = {"n_regimes": len(tl), "episodes_by_k": ev.k.value_counts().sort_index().to_dict(), "checkpoint_rows": len(cp),
           "runtime_s": {"load": round(t_load, 1), "episodes_features_checkpoints": round(t_ev, 1), "total": round(time.time() - t_start, 1)}}
    (OUT / "CHALLENGE_RUN.json").write_text(json.dumps(run, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(run, indent=1, default=str))


if __name__ == "__main__":
    main()
