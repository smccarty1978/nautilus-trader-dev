"""MFE Conversion Test (1s precision) — can we harvest the move before the round-trip?

The Bar-4 entry HAS forward reach (56% reach +1 ATR MFE) but hold-to-flip gives it all
back (avg MFE 2.26 ATR → realized −0.07). This tests whether an active exit can convert
the proven move into realized PnL:

  Entry: Bar 4 open (causal — Model B features end Bar 3).
  Initial stop:  1.0 / 1.25 / 1.5 ATR.
  Arm when MFE reaches:  +0.75 / +1.0 / +1.5 ATR.
  Action once armed:  take full profit (PT) / move stop to BE / trail peak−0.5 / peak−0.75.
  Exit cap:  Bar 10 / Bar 15 / opposite flip.
  → 3 × 3 × 4 × 3 = 108 cells, plus passive baselines.

ALL arm/trail/BE/stop detection is on 1s bars (REQUIRED — 1m arming sign-flips this study
class, memory: level_momentum_be_arming_timing_artifact). Intrabar sequencing is
ADVERSE-FIRST (conservative): the in-force stop is checked against the bar's low/high
BEFORE the bar's high/low updates the running peak, so a trailing stop never benefits
from a peak it was not yet armed to. PT = limit fill at pt_px (no favorable slip); stops
= conservative at_or_worse_close fill − adverse slip; cap = 1m close − adverse slip.

A parity check re-simulates a sample via an independent scalar walk (replay-vs-runtime
gate ≤ $5/tr median, per safe_replay framework).

    python studies/regime_dna_knn/mfe_conversion_test.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import early_health_filter as E  # noqa: E402
import progressive_separability as P  # noqa: E402
from rejection_power import MODEL_B, gbm  # noqa: E402
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from utils.safe_replay import round_protect_to_tick  # noqa: E402
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
OUT = Path("studies/regime_dna_knn/results")
NS = 1_000_000_000
MULT = 20.0; TICK = 0.25; COMM = 5.0; ENTRY = 0.5 * TICK; EXIT = 1.0 * TICK
ENTRY_T = 180 * NS                      # Bar 4 open = +180s from flip close
SL_INIT = [1.0, 1.25, 1.5]
ARM = [0.75, 1.0, 1.5]
ACTIONS = ["pt", "be", "trail0.5", "trail0.75"]
TRAIL = {"trail0.5": 0.5, "trail0.75": 0.75}
CAPS = [("Bar10", 10), ("Bar15", 15), ("flip", None)]


def rtick(px, d):
    return round_protect_to_tick(float(px), int(d)) if np.isscalar(px) else \
        np.array([round_protect_to_tick(float(p), int(dd)) for p, dd in zip(px, d)])


def load():
    cap = pd.read_parquet(OUT / "early_health_capsule.parquet")
    df = E.compute_labels_features(cap).reset_index(drop=True)
    M = P.build(df); H, L, C, O, V, n = M
    d = df.direction.values.astype(float); atr = df.atr_base.values.astype(float)
    yr = df.year.values; lab = df.label.values
    # Model B pQ for OOS survivors (for optional filter stack)
    XB = P.feats_through(df, M, 3)[MODEL_B].values
    alive = n >= 4
    is_m = alive & (yr < 2025); oos_m = alive & (yr >= 2025)
    yQ = (lab == "QuickFailure").astype(int)
    pQ_oos = gbm(XB[is_m], yQ[is_m], XB[oos_m])
    cap1m = df.loc[oos_m, ["regime_id", "year", "label"]].copy()
    cap1m["entry"] = O[oos_m, 4]               # Bar 4 open
    cap1m["d"] = d[oos_m]; cap1m["atr"] = atr[oos_m]; cap1m["n_post"] = n[oos_m]
    cap1m["pc10"] = C[oos_m, np.minimum(n[oos_m], 10)]
    cap1m["pc15"] = C[oos_m, np.minimum(n[oos_m], 15)]
    # W2 fix: terminal opposite-flip close = last post bar, EXACT for any regime length
    # (the build() matrix caps at col 61; long regimes would otherwise mis-price the flip cap).
    cap1m["pcflip"] = df.loc[oos_m, "post_c"].apply(lambda x: float(x[-1])).values
    cap1m["pQ"] = pQ_oos
    paths = pd.read_parquet(OUT / "survivor_1s_paths.parquet")
    m = cap1m.merge(paths[["regime_id", "p1s_t", "p1s_h", "p1s_l", "p1s_c"]],
                    on="regime_id", how="inner")
    return m


def build_arrays(m):
    """Per trade: slice 1s path to t>=ENTRY_T, pad to common length. Returns
    H,L,C (Ntr×Lmax float32, NaN pad), T (ns offset), and scalar vectors."""
    Hl, Ll, Cl, Tl = [], [], [], []
    maxlen = 0
    rows = []
    for r in m.itertuples(index=False):
        t = np.asarray(r.p1s_t, dtype=np.int64)
        if t.size == 0:
            continue
        sel = t >= ENTRY_T
        if not sel.any():
            continue
        Hl.append(np.asarray(r.p1s_h, dtype=np.float32)[sel])
        Ll.append(np.asarray(r.p1s_l, dtype=np.float32)[sel])
        Cl.append(np.asarray(r.p1s_c, dtype=np.float32)[sel])
        Tl.append(t[sel])
        maxlen = max(maxlen, int(sel.sum()))
        rows.append(r)
    Ntr = len(rows)
    H = np.full((Ntr, maxlen), np.nan, np.float32)
    L = np.full((Ntr, maxlen), np.nan, np.float32)
    Cc = np.full((Ntr, maxlen), np.nan, np.float32)
    T = np.full((Ntr, maxlen), np.iinfo(np.int64).max, np.int64)
    for i in range(Ntr):
        k = Hl[i].size
        H[i, :k] = Hl[i]; L[i, :k] = Ll[i]; Cc[i, :k] = Cl[i]; T[i, :k] = Tl[i]
    g = pd.DataFrame(rows)
    return H, L, Cc, T, g


def replay_core(H, L, C, T, d, atr, fill, sl_init, arm, action):
    """Vectorized 1s replay of one core policy (no exit cap). Returns (exit_px, exit_t,
    reason_code) per trade; reason 0=none(rode out), 1=init_stop, 2=protect, 3=pt."""
    Ntr, Lmax = H.shape
    init_stop = rtick(fill - d * sl_init * atr, d)
    arm_pts = arm * atr
    peak = fill.copy()                                  # running favorable extreme px
    armed = np.zeros(Ntr, bool)
    protect = np.full(Ntr, np.nan)
    exit_px = np.full(Ntr, np.nan); exit_t = np.full(Ntr, -1, np.int64)
    reason = np.zeros(Ntr, np.int8)
    done = np.zeros(Ntr, bool)
    pt_px = fill + d * arm_pts                          # for action 'pt'
    for j in range(Lmax):
        hj = H[:, j]; lj = L[:, j]; cj = C[:, j]; tj = T[:, j]
        valid = ~np.isnan(hj) & ~done
        if not valid.any():
            continue
        # (a) in-force stop = protect if armed&set else init_stop
        eff = np.where(armed & ~np.isnan(protect), protect, init_stop)
        hit = valid & np.where(d == 1, lj <= eff, hj >= eff)
        if hit.any():
            f = np.where(d == 1, np.minimum(eff, cj), np.maximum(eff, cj))
            exit_px[hit] = f[hit] - d[hit] * EXIT
            exit_t[hit] = tj[hit]
            reason[hit] = np.where(armed[hit], 2, 1)
            done[hit] = True
            valid = valid & ~hit
        # (c) update running peak with this bar's extreme (after stop check = adverse-first)
        peak = np.where(valid & (d == 1), np.maximum(peak, hj),
                        np.where(valid & (d == -1), np.minimum(peak, lj), peak))
        fav = (peak - fill) * d
        # (d) arming
        newarm = valid & ~armed & (fav >= arm_pts)
        if newarm.any():
            if action == "pt":
                exit_px[newarm] = pt_px[newarm]          # limit fill, no slip
                exit_t[newarm] = tj[newarm]; reason[newarm] = 3; done[newarm] = True
            else:
                if action == "be":
                    pr = fill.copy()
                else:
                    pr = peak - d * TRAIL[action] * atr
                pr = rtick(pr, d)
                protect[newarm] = pr[newarm]; armed[newarm] = True
                # same-bar arm+stop check (price may have dipped to protect intrabar)
                sb = newarm & np.where(d == 1, lj <= protect, hj >= protect)
                if sb.any():
                    f = np.where(d == 1, np.minimum(protect, cj), np.maximum(protect, cj))
                    exit_px[sb] = f[sb] - d[sb] * EXIT
                    exit_t[sb] = tj[sb]; reason[sb] = 2; done[sb] = True
    return exit_px, exit_t, reason


def apply_caps(exit_px, exit_t, reason, fill, d, g):
    """For each exit cap, combine core trigger (if it fired at/before cap) with a
    passive exit at the cap's 1m close. Returns dict cap_name -> pnl array."""
    out = {}
    npost = g.n_post.values
    for cname, cbars in CAPS:
        if cbars is None:
            cap_t = npost * 60 * NS
            cap_px = g.pcflip.values
        else:
            cap_t = np.full(len(g), cbars * 60 * NS, np.int64)
            cap_px = (g.pc10 if cbars == 10 else g.pc15).values
        used_core = (reason > 0) & (exit_t <= cap_t)
        ex = np.where(used_core, exit_px, cap_px - d * EXIT)
        pnl = (ex - fill) * d * MULT - COMM
        out[cname] = pnl
    return out


def scalar_one(hh, ll, cc, tt, d, atr, fill, sl_init, arm, action, cap_bars, cappx, npost):
    """Independent scalar re-sim of ONE trade+policy (parity reference)."""
    init_stop = round_protect_to_tick(fill - d * sl_init * atr, int(d))
    arm_pts = arm * atr; peak = fill; armed = False; protect = None
    cap_t = (cap_bars if cap_bars else npost) * 60 * NS
    ex_px = None; ex_t = None; rs = 0
    for j in range(len(hh)):
        if np.isnan(hh[j]):
            break
        h, l, c, t = hh[j], ll[j], cc[j], tt[j]
        eff = protect if (armed and protect is not None) else init_stop
        if (d == 1 and l <= eff) or (d == -1 and h >= eff):
            f = min(eff, c) if d == 1 else max(eff, c)
            ex_px = f - d * EXIT; ex_t = t; rs = 2 if armed else 1; break
        peak = max(peak, h) if d == 1 else min(peak, l)
        fav = (peak - fill) * d
        if not armed and fav >= arm_pts:
            if action == "pt":
                ex_px = fill + d * arm_pts; ex_t = t; rs = 3; break
            protect = round_protect_to_tick(fill if action == "be" else peak - d * TRAIL[action] * atr, int(d))
            armed = True
            if (d == 1 and l <= protect) or (d == -1 and h >= protect):
                f = min(protect, c) if d == 1 else max(protect, c)
                ex_px = f - d * EXIT; ex_t = t; rs = 2; break
    if rs > 0 and ex_t <= cap_t:
        ex = ex_px
    else:
        ex = cappx - d * EXIT
    return (ex - fill) * d * MULT - COMM


def stats(pnl, yr):
    return dict(n=len(pnl), win=(pnl > 0).mean() * 100, net=pnl.mean(),
               n25=pnl[yr == 2025].mean(), n26=pnl[yr == 2026].mean())


def main():
    print("Loading 1m capsule + Model B + 1s paths ...")
    m = load()
    print(f"OOS survivors with usable 1s path: {len(m):,}")
    H, L, C, T, g = build_arrays(m)
    print(f"Replay arrays: {H.shape[0]:,} trades × {H.shape[1]:,} 1s cols")
    d = g.d.values.astype(float); atr = g.atr.values.astype(float)
    fill = (g.entry.values + d * ENTRY)
    yr = g.year.values
    pQ = g.pQ.values
    keep40 = pQ <= np.quantile(pQ, 0.60)                 # reject worst 40% by QF risk

    # ---- passive baselines (entry → cap close, no stop/arm) ----
    base = {}
    for cname, cbars in CAPS:
        cap_px = g.pcflip.values if cbars is None else (g.pc10 if cbars == 10 else g.pc15).values
        base[cname] = (cap_px - d * EXIT - fill) * d * MULT - COMM

    # ---- 108-cell grid ----
    grid = []      # (sl, arm, action, cap, stats, statsFiltered)
    for sl in SL_INIT:
        for a in ARM:
            for act in ACTIONS:
                ex_px, ex_t, rs = replay_core(H, L, C, T, d, atr, fill, sl, a, act)
                caps = apply_caps(ex_px, ex_t, rs, fill, d, g)
                for cname, _ in CAPS:
                    pnl = caps[cname]
                    grid.append((sl, a, act, cname, stats(pnl, yr),
                                 stats(pnl[keep40], yr[keep40])))

    # ---- parity gate (independent scalar walk on a sample) ----
    rng_idx = np.argsort(g.regime_id.values)[:: max(1, len(g) // 500)][:500]
    sl_p, a_p, act_p = 1.25, 1.0, "trail0.5"
    ex_px, ex_t, rs = replay_core(H, L, C, T, d, atr, fill, sl_p, a_p, act_p)
    vec_flip = apply_caps(ex_px, ex_t, rs, fill, d, g)["flip"]
    diffs = []
    for i in rng_idx:
        sc = scalar_one(H[i], L[i], C[i], T[i], d[i], atr[i], fill[i], sl_p, a_p, act_p,
                        None, g.pcflip.values[i], g.n_post.values[i])
        diffs.append(abs(sc - vec_flip[i]))
    parity = float(np.median(diffs)); parity_max = float(np.max(diffs))

    # ---- report ----
    R = ["# MFE Conversion Test (1s precision) — harvest the move before the round-trip?", "",
         f"OOS 2025-26 Bar-4-entry survivors with 1s path: **{len(g):,}**. Entry = Bar 4 open. "
         "All arm/trail/BE/stop detection on **1s bars** (REQUIRED — 1m arming sign-flips this study "
         "class). Intrabar = adverse-first. PT = limit fill (no slip); stops = at_or_worse_close − slip; "
         "cap = 1m close − slip. Costs $20/pt, $5 RT, 0.5t/1.0t slip.", "",
         f"**Parity gate (replay-vs-runtime, scalar re-sim of {len(rng_idx)} trades, "
         f"SL{sl_p}/arm{a_p}/{act_p}/flip):** median |Δ| = ${parity:.2f}/tr, max ${parity_max:.2f} "
         f"→ {'PASS ✅ (≤ $5)' if parity <= 5 else 'FAIL ❌ (> $5)'}.", "",
         "## Passive baselines (entry → cap close, no active exit)",
         "| Cap | n | Win% | Net/tr | 2025 | 2026 |", "| --- | --- | --- | --- | --- | --- |"]
    for cname, _ in CAPS:
        s = stats(base[cname], yr)
        R.append(f"| {cname} | {s['n']:,} | {s['win']:.1f}% | ${s['net']:+.2f} | "
                 f"${s['n25']:+.2f} | ${s['n26']:+.2f} |")

    R += ["", "## Conversion grid — net $/trade (pooled OOS), unfiltered Bar-4 population", "",
          "Cell = mean net $/tr. ✅ = net-positive in BOTH 2025 and 2026.", "",
          "| Init SL | Arm | Action | Bar10 | Bar15 | flip |", "| --- | --- | --- | --- | --- | --- |"]
    by_key = {}
    for sl, a, act, cname, s, sf in grid:
        by_key[(sl, a, act, cname)] = (s, sf)
    best = None
    for sl in SL_INIT:
        for a in ARM:
            for act in ACTIONS:
                cells = []
                for cname, _ in CAPS:
                    s, _ = by_key[(sl, a, act, cname)]
                    both = s['n25'] > 0 and s['n26'] > 0
                    cells.append(f"${s['net']:+.2f}{' ✅' if both else ''}")
                    if best is None or s['net'] > best[0]:
                        best = (s['net'], sl, a, act, cname, s)
                R.append(f"| {sl} | {a} | {act} | {cells[0]} | {cells[1]} | {cells[2]} |")

    # both-year winners (unfiltered + filtered)
    win_u = [(sl, a, act, c, s) for (sl, a, act, c, s, sf) in grid if s['n25'] > 0 and s['n26'] > 0]
    win_f = [(sl, a, act, c, sf) for (sl, a, act, c, s, sf) in grid if sf['n25'] > 0 and sf['n26'] > 0]

    R += ["", "## Win%/detail for the best pooled cell + both-year survivors", ""]
    bs = best[5]
    R.append(f"- Best pooled cell: **SL{best[1]} / arm{best[2]} / {best[3]} / {best[4]}** → "
             f"${bs['net']:+.2f}/tr (win {bs['win']:.1f}%, 2025 ${bs['n25']:+.2f}, 2026 ${bs['n26']:+.2f}).")
    R.append(f"- Both-year-positive cells (unfiltered): **{len(win_u)} / 108**.")
    R.append(f"- Both-year-positive cells (reject worst 40% by Model B QF risk): **{len(win_f)} / 108**.")
    if win_u:
        for sl, a, act, c, s in sorted(win_u, key=lambda w: -w[4]['net'])[:8]:
            R.append(f"  - SL{sl}/arm{a}/{act}/{c}: ${s['net']:+.2f}/tr (25 ${s['n25']:+.2f}, 26 ${s['n26']:+.2f})")

    R += ["", "## Verdict", ""]
    if parity > 5:
        R.append("> [!CAUTION]\n> Parity gate FAILED — vectorized replay diverges from scalar re-sim. "
                 "Numbers not trustworthy until reconciled.")
    elif win_u or win_f:
        R.append(f"> [!TIP]\n> **Conversion works in {len(win_u)} unfiltered / {len(win_f)} filtered cells "
                 "(both years positive, 1s precision).** Active profit capture DOES harvest part of the move "
                 "the regime-flip exit hands back. Strongest cells above — next gate is NT BacktestEngine "
                 "streaming (live-style) before any deployment claim.")
    else:
        R.append("> [!WARNING]\n> **NO — even with 1s-precision active exits, no cell is net-positive in both "
                 "years.** The move is real but un-harvestable: arming after the trade proves itself is already "
                 "too late (the round-trip beats the trail), and tight initial stops bleed the adverse-path "
                 "trades. The conversion problem is structural, not a tuning miss. Consistent with "
                 "[[post_bar3_survivor_not_monetizable]] — entries have reach, exits fail.")
    (OUT / "mfe_conversion_test.md").write_text("\n".join(R), encoding="utf-8")
    print(f"\nWrote mfe_conversion_test.md")
    print(f"Parity median |Δ|=${parity:.2f} max=${parity_max:.2f}")
    print(f"Both-year-positive: unfiltered {len(win_u)}/108, filtered {len(win_f)}/108")
    print(f"Best pooled: SL{best[1]}/arm{best[2]}/{best[3]}/{best[4]} = ${best[0]:+.2f}/tr "
          f"(25 ${bs['n25']:+.2f}, 26 ${bs['n26']:+.2f})")


if __name__ == "__main__":
    main()
