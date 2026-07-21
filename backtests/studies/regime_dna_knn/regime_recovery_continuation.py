"""Recovery Continuation Study — can the pullback→recovery be monetized as a CONTINUATION ADD?

The pullback-lifecycle study showed exit-EV ≈ hold-EV at every pullback depth (a flat
1-contract liquidation surface). But that does NOT test the trade the thesis describes:
keep the base on, and when a pullback RECOVERS (reclaims the prior peak), ADD a unit and
harvest the extension with a profit target — which avoids the flip give-back the base
position suffers.

For each FIRST pullback-of-X event (peak already >=1 ATR; X in 0.25/0.5/0.75/1.0 ATR) that
RECOVERS (price reclaims the prior running peak P_X), the reclaim is the ADD entry (stop-buy
at P_X). Measured forward to the 1m flip, for the ADD:
  - P(+0.5 / +1.0 / +2.0 ATR extension beyond P_X)
  - median extension (MFE beyond P_X) and median adverse (MAE below P_X) after recovery
  - median time to +0.5 ATR extension
  - NET $/add for: TP=0.5 ATR, TP=1.0 ATR, trail 0.5 ATR (else exit at flip)

All 1s, adverse-first intrabar (a trail/SL touch is checked before the bar's peak updates).
TP = limit fill at the target (no favorable slip); flip/trail = adverse slip. Add is a
separate 1-unit round trip: $5 RT, 0.5t entry / 1.0t exit slip. OOS 2025-26.

Decisive read: if the ADD is net-positive (both years), especially for the shallow/high-
recovery pullbacks, the continuation signal MONETIZES via pyramiding — even though plain
exit-vs-hold was flat. If the add EV is ~0/negative after costs, the extension after
recovery is too small to harvest and price-only is exhausted (→ order-flow next).

    python studies/regime_dna_knn/regime_recovery_continuation.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import early_health_filter as E  # noqa: E402
import progressive_separability as P  # noqa: E402
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
OUT = Path("studies/regime_dna_knn/results")
NS = 1_000_000_000
MULT = 20.0; TICK = 0.25; COMM = 5.0; ENTRY = 0.5 * TICK; EXIT = 1.0 * TICK
ENTRY_T = 180 * NS
TREND = 1.0
LEVELS = [0.25, 0.50, 0.75, 1.00]
EXT = [0.5, 1.0, 2.0]              # extension thresholds beyond P_X
TRAIL = 0.5


def analyze(r):
    t = np.asarray(r.p1s_t, np.int64)
    sel = t >= ENTRY_T
    if sel.sum() < 3:
        return []
    h = np.asarray(r.p1s_h)[sel]; l = np.asarray(r.p1s_l)[sel]; c = np.asarray(r.p1s_c)[sel]
    tt = t[sel]
    T_flip = r.n * 60 * NS
    inwin = tt <= T_flip
    h, l, c, tt = h[inwin], l[inwin], c[inwin], tt[inwin]
    if h.size < 3:
        return []
    e = r.entry; d = r.d; a = r.atr
    peak_px = np.maximum.accumulate(h) if d == 1 else np.minimum.accumulate(l)
    fav_exc = (peak_px - e) * d / a
    adverse = l if d == 1 else h
    dd = (peak_px - adverse) * d / a
    healthy = fav_exc >= TREND
    flip_c = r.flip_c
    out = []
    for X in LEVELS:
        ev = np.where(healthy & (dd >= X))[0]
        if ev.size == 0:
            continue
        i = ev[0]
        P_X = peak_px[i]                                   # the prior peak to reclaim
        # recovery = first future bar whose favorable extreme reaches P_X (causal reclaim;
        # >=/<= matches a stop-buy filling on exact touch — audit W1)
        fav_ext = h[i + 1:] if d == 1 else l[i + 1:]
        rc = np.where(fav_ext >= P_X if d == 1 else fav_ext <= P_X)[0]
        rec = bool(rc.size)
        row = dict(X=X, year=r.year, recovered=rec)
        if rec:
            j = i + 1 + rc[0]                              # reclaim (ADD entry) bar
            add_fill = P_X + d * ENTRY                     # stop-buy at the reclaimed level
            fh = h[j:]; fl = l[j:]; ft = tt[j:]            # forward window from the add (incl.)
            # extension beyond P_X (MFE) and adverse below P_X (MAE), ATR — per direction
            if d == 1:
                ext_mfe = max((fh.max() - P_X) / a, 0.0)   # favorable = higher highs
                ext_mae = max((P_X - fl.min()) / a, 0.0)   # adverse = lows below P_X
            else:
                ext_mfe = max((P_X - fl.min()) / a, 0.0)   # favorable = lower lows
                ext_mae = max((fh.max() - P_X) / a, 0.0)   # adverse = highs above P_X
            row["ext_mfe"] = ext_mfe; row["ext_mae"] = ext_mae
            # P(extension) + time to +0.5
            for X2 in EXT:
                lvl = P_X + d * X2 * a
                hit = (fh >= lvl) if d == 1 else (fl <= lvl)
                row[f"ext{X2}"] = bool(hit.any())
            lvl05 = P_X + d * 0.5 * a
            hit05 = np.where(fh >= lvl05 if d == 1 else fl <= lvl05)[0]
            row["t_ext05"] = (ft[hit05[0]] - ft[0]) / NS if hit05.size else np.nan
            # NET $/add policies (TP=0.5, TP=1.0, trail 0.5, else flip)
            for tp in (0.5, 1.0):
                lvl = P_X + d * tp * a
                hit = np.where(fh >= lvl if d == 1 else fl <= lvl)[0]
                if hit.size:
                    ex = lvl                              # limit fill at TP
                else:
                    ex = flip_c - d * EXIT                # ride to flip
                row[f"net_tp{tp}"] = (ex - add_fill) * d * MULT - COMM
            # trail 0.5 (adverse-first intrabar), else flip
            row["net_trail"] = _trail(fh, fl, d, a, add_fill, P_X, flip_c)
        out.append((X, row))
    return out


def _trail(fh, fl, d, a, add_fill, P_X, flip_c):
    peak = P_X
    exit_px = None
    for k in range(len(fh)):
        hi = fh[k] if d == 1 else fl[k]          # this-bar favorable extreme
        lo = fl[k] if d == 1 else fh[k]          # this-bar adverse extreme
        protect = peak - d * TRAIL * a
        # adverse-first: check trail stop against prior peak's protect before updating peak
        if (d == 1 and lo <= protect) or (d == -1 and lo >= protect):
            exit_px = protect - d * EXIT
            break
        peak = max(peak, hi) if d == 1 else min(peak, hi)
    if exit_px is None:
        exit_px = flip_c - d * EXIT
    return (exit_px - add_fill) * d * MULT - COMM


def main():
    cap = pd.read_parquet(OUT / "early_health_capsule.parquet")
    df = E.compute_labels_features(cap).reset_index(drop=True)
    M = P.build(df); H, L, C, O, V, n = M
    d = df.direction.values.astype(float); atr = df.atr_base.values.astype(float)
    entry = O[:, 4]
    # exact terminal opposite-flip close (last post bar) — correct for any regime length
    # (build() matrix caps at col 61; long regimes would otherwise misprice ride-to-flip — audit W2)
    flip_c = df.post_c.apply(lambda x: float(x[-1])).values
    base = pd.DataFrame({"regime_id": df.regime_id.values, "entry": entry, "d": d,
                         "atr": atr, "n": n, "flip_c": flip_c, "year": df.year.values})
    paths = pd.read_parquet(OUT / "survivor_1s_paths.parquet")
    m = base.merge(paths[["regime_id", "p1s_t", "p1s_h", "p1s_l", "p1s_c"]],
                   on="regime_id", how="inner")
    print(f"OOS survivors w/ 1s path: {len(m):,}")

    recs = {X: [] for X in LEVELS}
    for r in m.itertuples(index=False):
        for X, row in analyze(r):
            recs[X].append(row)

    def agg(X):
        rl = recs[X]
        if not rl:
            return None
        D = pd.DataFrame(rl)
        rec = D[D.recovered]
        nrec = len(rec)
        o = dict(n_event=len(D), rec_rate=D.recovered.mean()*100, n_add=nrec)
        if nrec:
            for X2 in EXT:
                o[f"pext{X2}"] = rec[f"ext{X2}"].mean()*100
            o["ext_med"] = rec.ext_mfe.median(); o["mae_med"] = rec.ext_mae.median()
            o["t05"] = rec.t_ext05.median()
            for pol in ("net_tp0.5", "net_tp1.0", "net_trail"):
                o[pol] = rec[pol].mean()
                o[pol+"_25"] = rec[rec.year == 2025][pol].mean()
                o[pol+"_26"] = rec[rec.year == 2026][pol].mean()
        return o

    A = {X: agg(X) for X in LEVELS}

    R = ["# Recovery Continuation Study — monetize the pullback→recovery as a continuation ADD?", "",
         "OOS 2025-26. Bar-4 trades reaching +1 ATR, first pullback-of-X event that RECOVERS (reclaims the "
         "prior peak P_X) → ADD a unit at the reclaim. Forward to the 1m flip. Add = separate 1-unit round trip "
         "($5 RT, 0.5t/1.0t slip). 1s, adverse-first. TP = limit (no fav slip).", "",
         "## Recovery & extension (over RECOVERIES — the trades where you'd actually add)",
         "| Pullback X | #adds | recovery% | P(+0.5 ext) | P(+1.0 ext) | P(+2.0 ext) | median ext (ATR) | median adverse (ATR) | median t→+0.5 |",
         "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for X in LEVELS:
        o = A[X]
        if not o or not o.get("n_add"):
            continue
        R.append(f"| {X:.2f} | {o['n_add']:,} | {o['rec_rate']:.0f}% | {o['pext0.5']:.0f}% | {o['pext1.0']:.0f}% | "
                 f"{o['pext2.0']:.0f}% | {o['ext_med']:.2f} | {o['mae_med']:.2f} | {o['t05']:.0f}s |")

    R += ["", "## Net $/add (over recoveries), with year split",
          "| Pullback X | TP=0.5 | (25/26) | TP=1.0 | (25/26) | trail 0.5 | (25/26) |",
          "| --- | --- | --- | --- | --- | --- | --- |"]
    for X in LEVELS:
        o = A[X]
        if not o or not o.get("n_add"):
            continue
        R.append(f"| {X:.2f} | ${o['net_tp0.5']:+.0f} | ({o['net_tp0.5_25']:+.0f}/{o['net_tp0.5_26']:+.0f}) | "
                 f"${o['net_tp1.0']:+.0f} | ({o['net_tp1.0_25']:+.0f}/{o['net_tp1.0_26']:+.0f}) | "
                 f"${o['net_trail']:+.0f} | ({o['net_trail_25']:+.0f}/{o['net_trail_26']:+.0f}) |")

    # verdict: best add policy net-positive in BOTH years at any depth?
    winners = []
    for X in LEVELS:
        o = A[X]
        if not o or not o.get("n_add"):
            continue
        for pol, lbl in (("net_tp0.5", "TP=0.5"), ("net_tp1.0", "TP=1.0"), ("net_trail", "trail0.5")):
            if o[pol+"_25"] > 0 and o[pol+"_26"] > 0:
                winners.append((X, lbl, o[pol], o[pol+"_25"], o[pol+"_26"]))
    R += ["", "## Verdict", ""]
    if winners:
        best = max(winners, key=lambda w: w[2])
        R.append(f"**{len(winners)} add policy×depth cells net-positive in BOTH years.** Best: pullback "
                 f"{best[0]:.2f} + {best[1]} → **${best[2]:+.0f}/add** (2025 {best[3]:+.0f}, 2026 {best[4]:+.0f}).")
        R.append("> [!TIP]\n> **The continuation ADD monetizes what flat exit-vs-hold could not.** Conditioning "
                 "on recovery and harvesting the extension with a profit target (avoiding the flip give-back the "
                 "base position eats) is net-positive both years. This is a real pyramiding edge — next gate is a "
                 "live-style NT strategy (base + add, single book) on 1s/tick before any deployment claim.")
    else:
        # report the best (least-bad) for context
        flat = []
        for X in LEVELS:
            o = A[X]
            if o and o.get("n_add"):
                for pol in ("net_tp0.5", "net_tp1.0", "net_trail"):
                    flat.append((X, pol, o[pol]))
        bx, bp, bv = max(flat, key=lambda z: z[2]) if flat else (np.nan, "-", np.nan)
        R.append(f"No add policy×depth is net-positive in BOTH years. Best pooled: {bp} @ {bx:.2f} = ${bv:+.0f}/add.")
        R.append("> [!WARNING]\n> **The continuation ADD does NOT monetize either.** Even conditioning on "
                 "recovery and taking profit on the extension, the add does not clear costs both years. The "
                 "extension after recovery is real (median ext above) but too small / too often pre-empted by the "
                 "adverse excursion to harvest after friction. This closes the price-only continuation angle too: "
                 "recovery probability is monotone and real, but neither liquidation NOR pyramiding converts it. "
                 "Order-flow (absorption vs exhaustion) is the next rational input. "
                 "[[price_pullback_severity_monetarily_inert]]")
    (OUT / "regime_recovery_continuation.md").write_text("\n".join(R), encoding="utf-8")
    print("Wrote regime_recovery_continuation.md")
    for X in LEVELS:
        o = A[X]
        if o and o.get("n_add"):
            print(f"  X={X:.2f}: adds={o['n_add']:,} rec={o['rec_rate']:.0f}% extMed={o['ext_med']:.2f} "
                  f"TP0.5=${o['net_tp0.5']:+.0f}({o['net_tp0.5_25']:+.0f}/{o['net_tp0.5_26']:+.0f}) "
                  f"TP1.0=${o['net_tp1.0']:+.0f} trail=${o['net_trail']:+.0f}")


if __name__ == "__main__":
    main()
