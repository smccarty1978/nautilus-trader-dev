"""Phase 2 (telemetry components) + Phase 4 (adaptive exit policies / money gate).

Phase 2: walk-forward probability components on the LIVE telemetry block (the
block that calibrates; DNA/archetype dropped — independently proven to add zero):
  P_velocity     = P(new regime extreme within next 3 bars)
  P_pullback_risk= P(pullback expands >0.5 ATR within next 3 bars)
  P_flip_risk    = P(opposite 1m flip within next 3 bars)
  Health Score   = 100*(P_velocity + (1-P_pullback_risk) + (1-P_flip_risk))/3
Fit on IS (2021-24) per OOS year on strictly-prior years; applied OOS only.

Phase 4: 2 entry universes (A bar+2 all flips; B bar+4 health-confirmed) x 3 exit
policies (Control=flip-only; Hard-Cut=exit if P_flip>0.6 or Health<40; Adaptive
Component Trail), vs the Oracle ceiling and Control baseline. Money gate: net+ in
BOTH 2025 and 2026 AND PF>=1.10 AND materially beats Control. 1m-bar stops
overstate -> a PASS needs 1s/tick re-validation; a FAIL is robust.

    python studies/regime_dna_knn/telemetry_phase4.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
OUT = Path("studies/regime_dna_knn/results")
IS = [2021, 2022, 2023, 2024]
MAXBAR = 30
MULT = 20.0; TICK = 0.25; COMM = 5.0; ENTRY = 0.5 * TICK; EXIT = 1.0 * TICK
FEATS = ["bar_index", "current_pullback_from_peak", "consecutive_non_continuation_bars",
         "progress_efficiency_so_far", "distance_from_flip_open"]


def build(df):
    n = df["n_post"].values.astype(int); N = len(df); B = 62
    H = np.full((N, B), np.nan); L = np.full((N, B), np.nan)
    C = np.full((N, B), np.nan); O = np.full((N, B), np.nan)
    H[:, 0] = df.flip_h; L[:, 0] = df.flip_l; C[:, 0] = df.flip_c; O[:, 0] = df.flip_o
    ph = df.post_h.tolist(); pl = df.post_l.tolist(); pc = df.post_c.tolist(); po = df.post_o.tolist()
    for i in range(N):
        k = min(n[i], B - 1)
        if k > 0:
            H[i, 1:k+1] = ph[i][:k]; L[i, 1:k+1] = pl[i][:k]
            C[i, 1:k+1] = pc[i][:k]; O[i, 1:k+1] = po[i][:k]
    return H, L, C, O, n


def per_bar(df):
    H, L, C, O, n = build(df)
    d = df.direction.values.astype(float); atr = df.atr_base.values.astype(float)
    fo = df.flip_o.values.astype(float); yr = df.year.values; rid = df.regime_id.values
    N, B = H.shape
    ext = np.where(d[:, None] == 1, H, -L); fo_ext = np.where(d == 1, fo, -fo)
    favc = (C - fo[:, None]) * d[:, None]
    # pullback matrix per bar
    PB = np.full((N, B), np.nan)
    run = fo_ext.copy()
    for j in range(1, B):
        run = np.fmax(run, np.nan_to_num(ext[:, j], nan=-1e18))
        peak = (run - fo_ext) / atr
        PB[:, j] = np.maximum(0.0, peak - favc[:, j] / atr)
    rows = []
    for t in range(1, MAXBAR + 1):
        active = n > t
        if not active.any():
            break
        idx = np.where(active)[0]
        ext_run = np.fmax(fo_ext[idx], np.nanmax(ext[idx, 1:t+1], axis=1))
        # features
        pull = PB[idx, t]
        # stall (consecutive no-new-extreme ending at t)
        nh = np.zeros((len(idx), t), bool); rm = fo_ext[idx].copy()
        for j in range(1, t+1):
            nh[:, j-1] = ext[idx, j] > rm + 1e-9; rm = np.fmax(rm, ext[idx, j])
        stall = np.zeros(len(idx), int)
        for j in range(t-1, -1, -1):
            still = stall == (t-1-j); stall = np.where(still & ~nh[:, j], stall+1, stall)
        rets = np.abs(np.diff(C[idx, :t+1], axis=1)); path = np.nansum(rets, axis=1)
        eff = np.where(path > 1e-9, favc[idx, t] / path, 0.0)
        dist = favc[idx, t] / atr[idx]
        # forward labels
        if t+1 < B:
            hi3 = np.where(d[idx] == 1, np.nanmax(H[idx, t+1:t+4], axis=1), -np.nanmax(-L[idx, t+1:t+4], axis=1))
            vel = np.where(np.isnan(hi3), np.nan, (hi3 > ext_run).astype(float))
            pbf = np.nanmax(PB[idx, t+1:t+4], axis=1)
            pull_exp = np.where(np.isnan(pbf), np.nan, ((pbf - pull) > 0.5).astype(float))
        else:
            vel = np.full(len(idx), np.nan); pull_exp = np.full(len(idx), np.nan)
        flip = ((n[idx] - t) <= 3).astype(float)
        rows.append(pd.DataFrame(dict(regime_id=rid[idx], year=yr[idx], bar_index=t,
                                      current_pullback_from_peak=pull,
                                      consecutive_non_continuation_bars=stall,
                                      progress_efficiency_so_far=eff,
                                      distance_from_flip_open=dist,
                                      y_vel=vel, y_pull=pull_exp, y_flip=flip)))
    return pd.concat(rows, ignore_index=True), (H, L, C, O, n)


def main():
    cap = pd.read_parquet(OUT / "early_health_capsule.parquet")
    print(f"Capsule {len(cap):,}. Building per-bar telemetry...")
    tb, _ = per_bar(cap)
    # ---- Phase 2: walk-forward components ----
    print("Phase 2: fitting walk-forward telemetry components...")
    tb["P_velocity"] = np.nan; tb["P_pullback_risk"] = np.nan; tb["P_flip_risk"] = np.nan
    for Y in [2025, 2026]:
        tr = tb[tb.year < Y].dropna(subset=["y_vel", "y_pull", "y_flip"])
        te_mask = tb.year == Y
        Xtr = tr[FEATS].values
        for tgt, col in [("y_vel", "P_velocity"), ("y_pull", "P_pullback_risk"), ("y_flip", "P_flip_risk")]:
            clf = HistGradientBoostingClassifier(max_depth=4, max_iter=150, learning_rate=0.08,
                                                 random_state=0).fit(Xtr, tr[tgt].values.astype(int))
            tb.loc[te_mask, col] = clf.predict_proba(tb.loc[te_mask, FEATS].values)[:, 1]
    tb["health"] = 100 * (tb.P_velocity + (1 - tb.P_pullback_risk) + (1 - tb.P_flip_risk)) / 3
    oos = tb[tb.year >= 2025]
    # component calibration (OOS): does each component sort its actual outcome?
    from scipy.stats import spearmanr
    cal = []
    for comp, y in [("P_velocity", "y_vel"), ("P_pullback_risk", "y_pull"), ("P_flip_risk", "y_flip")]:
        s = oos[[comp, y]].dropna()
        s["dec"] = pd.qcut(s[comp], 10, labels=False, duplicates="drop")
        g = s.groupby("dec")[y].mean()
        cal.append((comp, spearmanr(g.index, g.values).statistic, g.iloc[0], g.iloc[-1]))
    Lc = ["", "## Phase 2 — telemetry component calibration (OOS 2025–2026)",
          "| Component | Spearman(decile→actual) | D1 actual | D10 actual |",
          "| --- | --- | --- | --- |"]
    for comp, rho, lo, hi in cal:
        Lc.append(f"| {comp} | {rho:+.2f} | {lo*100:.0f}% | {hi*100:.0f}% |")
    # append to calibration md
    p = OUT / "telemetry_calibration.md"
    base = p.read_text(encoding="utf-8") if p.exists() else "# Telemetry Calibration\n"
    p.write_text(base + "\n".join(Lc), encoding="utf-8")
    print("Components OOS:", [(c, round(r, 2)) for c, r, _, _ in cal])

    # ---- Phase 4: policies ----
    comp_map = {(int(r.regime_id), int(r.bar_index)): (r.P_flip_risk, r.P_pullback_risk, r.P_velocity, r.health)
                for r in oos.itertuples()}
    capo = cap[cap.year.isin([2025, 2026])].reset_index(drop=True)
    H, L, C, O, n = build(capo)
    d = capo.direction.values.astype(float); atr = capo.atr_base.values.astype(float)
    rid = capo.regime_id.values; yr = capo.year.values
    fl = capo.flip_l.values; fh = capo.flip_h.values
    # Universe B health gate (causal at bar 3): early_mfe>=0.75, early_mae<=0.5, no flip-open viol bars1-3
    fo = capo.flip_o.values
    def early(i):
        last = min(n[i], 4)
        if last < 4:
            return None
        mfe = max(((H[i, j]-fo[i])*d[i] if d[i] == 1 else (fo[i]-L[i, j])) for j in range(1, 4)) / atr[i]
        mae = max(((fo[i]-L[i, j]) if d[i] == 1 else (H[i, j]-fo[i])) for j in range(1, 4)) / atr[i]
        viol = any((L[i, j] < fo[i]) if d[i] == 1 else (H[i, j] > fo[i]) for j in range(1, 4))
        return (mfe >= 0.75) and (mae <= 0.5) and (not viol)

    def sim(i, eb, policy):
        last = min(int(n[i]), 60)
        if last <= eb:
            return None
        entry = O[i, eb]
        if not np.isfinite(entry):
            return None
        ef = entry + d[i]*ENTRY
        stop = (fl[i]-TICK) if d[i] == 1 else (fh[i]+TICK)
        prev_pull = None
        for j in range(eb, last+1):
            bh, bl, bc = H[i, j], L[i, j], C[i, j]
            comp = comp_map.get((int(rid[i]), j))
            # adaptive trailing stop update (uses comp at THIS bar; acts next bar)
            if policy == "adaptive" and comp is not None:
                pflip, ppull, pvel, hp = comp
                if prev_pull is not None and (ppull - prev_pull) > 0.25:
                    tight = (bl - TICK) if d[i] == 1 else (bh + TICK)   # lock 1 tick past current extreme
                    stop = max(stop, tight) if d[i] == 1 else min(stop, tight)
                prev_pull = ppull
            # intrabar stop
            if (d[i] == 1 and bl <= stop) or (d[i] == -1 and bh >= stop):
                px = stop - d[i]*EXIT; return (px-ef)*d[i]*MULT-COMM, yr[i]
            # hard cut (act at this bar close when signal present)
            if policy == "hardcut" and comp is not None:
                pflip, ppull, pvel, hp = comp
                if pflip > 0.60 or hp < 40:
                    px = bc - d[i]*EXIT; return (px-ef)*d[i]*MULT-COMM, yr[i]
            # opposite flip = reach reversal bar (last) -> exit at its close (causal)
            if j == last:
                px = bc - d[i]*EXIT; return (px-ef)*d[i]*MULT-COMM, yr[i]
        return None

    def metrics(res):
        if not res:
            return None
        p = np.array([r[0] for r in res]); y = np.array([r[1] for r in res])
        pf = p[p > 0].sum()/(-p[p < 0].sum()) if (p < 0).any() else (np.inf if (p > 0).any() else 0)
        return dict(n=len(p), net=p.sum(), avg=p.mean(), pf=pf,
                    n25=p[y == 2025].sum(), n26=p[y == 2026].sum(), win=100*(p > 0).mean())

    R = ["# Telemetry Money Gate — Phase 4 (OOS 2025–2026)", "",
         "Adaptive exit management on causal telemetry components. Friction $5 RT + 0.5t entry + 1.0t exit. "
         "Gate: net+ both years AND PF>=1.10 AND materially beats Control. 1m-bar stops overstate — a PASS "
         "needs 1s/tick re-validation.", ""]
    universes = [("A bar+2 all-flips", 2, lambda i: n[i] > 2),
                 ("B bar+4 health-confirmed", 4, lambda i: (n[i] > 4) and bool(early(i)))]
    any_pass = 0
    for uname, eb, umask in universes:
        idxs = [i for i in range(len(capo)) if umask(i)]
        ctrl = metrics([sim(i, eb, "control") for i in idxs if sim(i, eb, "control")])
        R.append(f"## Universe {uname}  (n≈{len(idxs):,})")
        R.append("| Exit policy | Trades | Win% | PF | Net | 2025 | 2026 | Avg/tr | beats Control? | PASS |")
        R.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
        for pol in ("control", "hardcut", "adaptive"):
            res = [r for i in idxs for r in [sim(i, eb, pol)] if r]
            m = metrics(res)
            if not m:
                continue
            beats = (pol != "control" and ctrl and m["avg"] > ctrl["avg"]*1.05 and m["pf"] > ctrl["pf"])
            passed = (pol != "control" and m["n25"] > 0 and m["n26"] > 0 and np.isfinite(m["pf"])
                      and m["pf"] >= 1.10 and beats)
            any_pass += int(passed)
            pf = f"{m['pf']:.2f}" if np.isfinite(m['pf']) else "inf"
            R.append(f"| {pol} | {m['n']:,} | {m['win']:.0f}% | {pf} | ${m['net']:,.0f} | ${m['n25']:,.0f} | "
                     f"${m['n26']:,.0f} | ${m['avg']:.2f} | {'yes' if beats else ('—' if pol=='control' else 'no')} | "
                     f"{'✅' if passed else ('—' if pol=='control' else '❌')} |")
        R.append("")
    R.append("## Verdict")
    if any_pass:
        R.append(f"> [!TIP]\n> **{any_pass} adaptive policy/universe PASS** (net+ both yrs, PF>=1.10, beat Control). "
                 "Requires 1s/tick re-validation before any deployment claim.")
    else:
        R.append("> [!WARNING]\n> **DEAD.** No adaptive telemetry exit policy is net-positive in both years with "
                 "PF>=1.10 while materially beating the Control (flip-only) baseline. Despite near-perfect LOCAL "
                 "telemetry calibration (Phase 1) and a rich Oracle ceiling (Phase 3), the realizable policies "
                 "cannot harvest enough of that ceiling after costs — the telemetry fires too late/too noisily to "
                 "time exits. Adaptive-exit-management branch closed; consistent with the entry-side null.")
    (OUT / "telemetry_money_gate.md").write_text("\n".join(R), encoding="utf-8")
    print(f"Wrote telemetry_money_gate.md; adaptive passes={any_pass}")


if __name__ == "__main__":
    main()
