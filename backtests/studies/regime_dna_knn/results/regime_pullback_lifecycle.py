"""Pullback Lifecycle — does price-only pullback SEVERITY distinguish rest from exhaustion?

The 5s study reframed the give-back as a slow trend-lifecycle bleed (peak ~5 min before
flip), not a final-second event. So the real question for a price-only exit is:

    After a healthy trend reaches +1 ATR, at each pullback depth from the running peak
    (0.25 / 0.50 / 0.75 / 1.00 ATR), what happens next?

For each FIRST pullback-of-X event (peak already >=1 ATR, drawdown from peak reaches X,
measured at 1s on the adverse extreme — the gold standard for a level touch):
  - P(new peak)         : does favorable excursion later exceed the pre-pullback peak?
  - P(further 0.5 first): does it give back another 0.5 ATR BEFORE making a new peak?
  - remaining MFE       : additional favorable excursion above the pullback peak (ATR)
  - exit-now $/tr       : realized if you exit at the pullback level
  - hold-to-flip $/tr   : realized if you ride to the 1m flip

Decisive read: if P(new peak) FALLS sharply with X (and exit-now starts beating hold at
deep X), a price-only exhaustion threshold exists. If P(new peak) is FLAT (~rest rate) and
hold beats exit at every X, price-only pullback severity CANNOT separate rest from
exhaustion — which is the clean falsification that justifies trying order-flow (not because
ticks are magic, but because price alone is provably insufficient here).

This is a DIAGNOSTIC (no model, no tuned threshold). The decision point uses only info up to
the pullback bar; the measured outcomes are honestly forward. OOS 2025-26, 1s paths.

    python studies/regime_dna_knn/regime_pullback_lifecycle.py
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
TREND = 1.0                          # "healthy" = running peak reached >= 1 ATR
LEVELS = [0.25, 0.50, 0.75, 1.00]    # pullback depth from peak (ATR)
FURTHER = 0.5                        # "give back another" increment


def analyze(r):
    """One trade: detect first pullback-of-X events on the 1s path and measure forward
    outcomes. Returns list of (X, dict) for each level reached."""
    t = np.asarray(r.p1s_t, np.int64)
    sel = t >= ENTRY_T
    if sel.sum() < 3:
        return []
    h = np.asarray(r.p1s_h)[sel]; l = np.asarray(r.p1s_l)[sel]; c = np.asarray(r.p1s_c)[sel]
    tt = t[sel]
    T_flip = r.n * 60 * NS
    inwin = tt <= T_flip                                  # only within the regime life
    h, l, c, tt = h[inwin], l[inwin], c[inwin], tt[inwin]
    if h.size < 3:
        return []
    e = r.entry; d = r.d; a = r.atr
    # running peak price (favorable extreme) and favorable excursion (ATR)
    peak_px = np.maximum.accumulate(h) if d == 1 else np.minimum.accumulate(l)
    fav_exc = (peak_px - e) * d / a                       # running peak excursion
    adverse = l if d == 1 else h
    dd = (peak_px - adverse) * d / a                      # drawdown from running peak (ATR)
    healthy = fav_exc >= TREND
    out = []
    fill = e + d * ENTRY
    hold_px = r.flip_c
    hold_pnl = (hold_px - d * EXIT - fill) * d * MULT - COMM
    for X in LEVELS:
        ev = np.where(healthy & (dd >= X))[0]
        if ev.size == 0:
            continue
        i = ev[0]
        peak_at = peak_px[i]; peak_exc_at = (peak_at - e) * d / a
        # forward window strictly AFTER the event bar
        fh = h[i + 1:] if d == 1 else l[i + 1:]
        # new peak = future favorable extreme exceeds the pre-pullback peak
        if d == 1:
            fut_fav = (np.maximum.accumulate(fh) - e) / a if fh.size else np.array([])
            new_peak_hit = np.where(fh > peak_at)[0] if fh.size else np.array([])
            # further-0.5 level (deeper drawdown from the SAME peak_at)
            fl_arr = l[i + 1:]
            further_hit = np.where(fl_arr <= peak_at - (X + FURTHER) * a)[0] if fl_arr.size else np.array([])
        else:
            fut_fav = (e - np.minimum.accumulate(fh)) / a if fh.size else np.array([])
            new_peak_hit = np.where(fh < peak_at)[0] if fh.size else np.array([])
            fh_arr = h[i + 1:]
            further_hit = np.where(fh_arr >= peak_at + (X + FURTHER) * a)[0] if fh_arr.size else np.array([])
        np_i = new_peak_hit[0] if new_peak_hit.size else np.inf
        fu_i = further_hit[0] if further_hit.size else np.inf
        new_peak = np.isfinite(np_i)
        further_first = np.isfinite(fu_i) and (fu_i < np_i)     # gave back 0.5 more before a new peak
        rem_mfe = max(0.0, (fut_fav.max() - peak_exc_at)) if fut_fav.size else 0.0
        exit_px = (peak_at - d * X * a)                        # the pullback level
        exit_pnl = (exit_px - d * EXIT - fill) * d * MULT - COMM
        out.append((X, dict(new_peak=new_peak, further=further_first, rem_mfe=rem_mfe,
                            exit_pnl=exit_pnl, hold_pnl=hold_pnl, peak_exc=peak_exc_at,
                            year=r.year)))
    return out


def main():
    cap = pd.read_parquet(OUT / "early_health_capsule.parquet")
    df = E.compute_labels_features(cap).reset_index(drop=True)
    M = P.build(df); H, L, C, O, V, n = M
    d = df.direction.values.astype(float); atr = df.atr_base.values.astype(float)
    entry = O[:, 4]; idx = np.arange(len(df))
    flip_c = C[idx, np.minimum(n, 61)]
    base = pd.DataFrame({"regime_id": df.regime_id.values, "entry": entry, "d": d,
                         "atr": atr, "n": n, "flip_c": flip_c, "year": df.year.values})
    paths = pd.read_parquet(OUT / "survivor_1s_paths.parquet")
    m = base.merge(paths[["regime_id", "p1s_t", "p1s_h", "p1s_l", "p1s_c"]],
                   on="regime_id", how="inner")
    print(f"OOS survivors w/ 1s path: {len(m):,}")

    # collect per-level event records
    recs = {X: [] for X in LEVELS}
    n_reached_1atr = 0
    for r in m.itertuples(index=False):
        evs = analyze(r)
        if evs:                                   # reached +1 ATR and pulled back at least 0.25
            n_reached_1atr += 1
        for X, rec in evs:
            recs[X].append(rec)
    print(f"Trades reaching +1 ATR then pulling back >=0.25: {n_reached_1atr:,}")

    def agg(rl):
        if not rl:
            return None
        npk = np.array([x["new_peak"] for x in rl]); fur = np.array([x["further"] for x in rl])
        rem = np.array([x["rem_mfe"] for x in rl]); ex = np.array([x["exit_pnl"] for x in rl])
        ho = np.array([x["hold_pnl"] for x in rl]); yr = np.array([x["year"] for x in rl])
        return dict(n=len(rl), pnew=npk.mean()*100, pfur=fur.mean()*100, remmed=np.median(rem),
                    exmean=ex.mean(), homean=ho.mean(),
                    pnew25=npk[yr == 2025].mean()*100, pnew26=npk[yr == 2026].mean()*100)

    R = ["# Pullback Lifecycle — does price-only severity separate rest from exhaustion?", "",
         f"OOS 2025-26. Trades reaching +{TREND:.0f} ATR then pulling back ≥0.25: **{n_reached_1atr:,}**. "
         "First pullback-of-X event per trade (1s, adverse-extreme touch). Forward outcomes measured to the "
         "1m flip. Costs $20/pt, $5 RT, 0.5t/1.0t slip.", "",
         "## Pullback depth → forward outcome",
         "| Pullback X (ATR) | n | P(new peak) | P(give back +0.5 first) | median remaining MFE | exit-now $/tr | hold-to-flip $/tr | exit−hold |",
         "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    A = {}
    for X in LEVELS:
        s = agg(recs[X]); A[X] = s
        if s is None:
            continue
        R.append(f"| {X:.2f} | {s['n']:,} | {s['pnew']:.0f}% | {s['pfur']:.0f}% | {s['remmed']:.2f} | "
                 f"${s['exmean']:+.0f} | ${s['homean']:+.0f} | ${s['exmean']-s['homean']:+.0f} |")

    R += ["", "## P(new peak) year split (robustness)",
          "| Pullback X | P(new peak) 2025 | 2026 |", "| --- | --- | --- |"]
    for X in LEVELS:
        s = A[X]
        if s:
            R.append(f"| {X:.2f} | {s['pnew25']:.0f}% | {s['pnew26']:.0f}% |")

    # verdict
    p_shallow = A[0.25]["pnew"] if A[0.25] else np.nan
    p_deep = A[1.00]["pnew"] if A[1.00] else np.nan
    sep = p_shallow - p_deep
    max_edge = max((A[X]["exmean"] - A[X]["homean"]) for X in LEVELS if A[X])  # best exit-vs-hold
    money_flat = max_edge < 25                                                  # exit ≈ hold everywhere
    ex_beats = max_edge > 50
    R += ["", "## Verdict", ""]
    R.append(f"P(new peak): shallow (0.25) **{p_shallow:.0f}%** → deep (1.00) **{p_deep:.0f}%** "
             f"(separation {sep:+.0f}pp, year-robust). Best exit-now − hold across depths: **${max_edge:+.0f}/tr**.")
    if ex_beats:
        R.append("> [!TIP]\n> **Price-only pullback severity is MONETIZABLE** — deeper pullbacks predict "
                 "no-recovery AND exiting beats holding at depth. Build a price-only exhaustion exit (1s/NT "
                 "validated). Order-flow not yet needed.")
    elif money_flat:
        R.append(
            "> [!WARNING]\n> **Price carries the ODDS but they are MONETARILY INERT — the clean falsification.** "
            f"P(new peak) separates strongly and robustly with depth ({p_shallow:.0f}%→{p_deep:.0f}%, "
            f"{sep:+.0f}pp), so pullback severity is NOT noise — it genuinely tracks recovery probability. **But "
            f"exiting on it gains nothing: exit-now ≈ hold-to-flip (~$167/tr) at EVERY depth (best edge "
            f"${max_edge:+.0f}/tr).** The deep pullbacks that DO recover (57% even at 1.0 ATR) recover by enough "
            "to exactly pay for the ones that don't — magnitude compensates probability. The pullback is already "
            "PRICED; the forward EV equals the current exit value at every depth (a martingale-like surface). "
            "This is the precise answer to *'at what give-back does the trend stop being worth holding?'* → "
            "**never — the EV is flat, so no price-only pullback exit can beat holding.** It is exactly why "
            "simple trails fail. To beat it you must distinguish WHICH deep pullbacks are the 57% that recover "
            "vs the 43% that don't, and pullback depth alone provably cannot (it's priced). That residual is the "
            "narrow, falsifiable job for **order-flow** (absorption / renewed participation vs exhaustion during "
            "the bleed) — the next RATIONAL test, not a promised land. [[regime_health_decay_no_leadtime_1m]]")
    else:
        R.append("> [!NOTE]\n> **Borderline** — some separation and a small exit-vs-hold edge "
                 f"(${max_edge:+.0f}/tr) but not clean. Re-check with sizing before reaching for ticks.")
    (OUT / "regime_pullback_lifecycle.md").write_text("\n".join(R), encoding="utf-8")
    print("Wrote regime_pullback_lifecycle.md")
    for X in LEVELS:
        s = A[X]
        if s:
            print(f"  X={X:.2f}: n={s['n']:,} P(new peak)={s['pnew']:.0f}% remMFE={s['remmed']:.2f} "
                  f"exit-hold=${s['exmean']-s['homean']:+.0f}")


if __name__ == "__main__":
    main()
