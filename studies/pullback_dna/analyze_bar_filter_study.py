"""Analyze trigger-bar quality filter study results."""
from __future__ import annotations
import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd

RESULTS = Path("studies/pullback_dna/results/bar_filter_study")

VARIANTS = [
    ("baseline",     "Baseline (none)"),
    ("dir_close",    "dir_close"),
    ("min_body25",   "min_body25"),
    ("strong_close", "strong_close"),
    ("dir_body25",   "dir_body25"),
]


def pct(v, t):  return 0.0 if t == 0 else 100.0 * v / t
def wr(p):      return pct((p > 0).sum(), len(p)) if len(p) else float("nan")
def ev(p):      return p.mean() if len(p) else float("nan")
def pf(p):
    w = p[p > 0].sum(); l = abs(p[p < 0].sum())
    return w / l if l > 0 else float("inf")
def max_dd(p):
    eq = p.cumsum(); return (eq - eq.cummax()).min()
def sep(t="", w=90):
    pad = (w - len(t) - 2) // 2 if t else 0
    print("\n" + ("=" * pad + f" {t} " + "=" * pad if t else "-" * w))


def classify(row) -> str:
    rsn = row["exit_reason"]
    mfe = row["max_mfe_atr"]
    if rsn in ("initial_stop", "lock_floor", "sl"):
        if mfe < 0.25: return "ImmFail"
        if mfe < 0.50: return "PartRun"
        if mfe < 1.00: return "VShape/Mid"
        return "LockFloor"
    if mfe < 0.25:  return "FlipNeg"
    if mfe < 1.00:  return "FlipMod"
    if mfe < 2.00:  return "FlipRun"
    return "FlipExp"


def load_all() -> dict[str, pd.DataFrame]:
    dfs = {}
    for slug, label in VARIANTS:
        path = RESULTS / f"bar_filter_{slug}.parquet"
        if not path.exists():
            print(f"  MISSING: {path.name}")
            continue
        df = pd.read_parquet(path)
        df["entry_dt"] = pd.to_datetime(df["entry_ts"], unit="ns", utc=True)
        df["ym"]   = df["entry_dt"].dt.to_period("M").astype(str)
        df["arch"] = df.apply(classify, axis=1)
        dfs[label] = df
    return dfs


def metrics(df: pd.DataFrame) -> dict:
    p   = df["pnl"]
    n   = len(df)
    win = df[p > 0]
    los = df[p < 0]
    imm  = df[df["arch"] == "ImmFail"]
    fexp = df[df["arch"] == "FlipExp"]
    lk   = df[df["lock_armed"]]
    lk_neg = lk[lk["pnl"] < 0]
    ist  = (df["exit_reason"] == "initial_stop").sum()
    lfl  = (df["exit_reason"] == "lock_floor").sum()
    flp  = (df["exit_reason"] == "regime_flip").sum()
    return dict(
        n           = n,
        wr          = wr(p),
        ev          = ev(p),
        total       = p.sum(),
        pf          = pf(p),
        max_dd      = max_dd(p),
        avg_win     = win["pnl"].mean()    if len(win) else float("nan"),
        med_win     = win["pnl"].median()  if len(win) else float("nan"),
        avg_los     = los["pnl"].mean()    if len(los) else float("nan"),
        med_los     = los["pnl"].median()  if len(los) else float("nan"),
        pct_istop   = pct(ist, n),
        pct_lock    = pct(lfl, n),
        pct_flip    = pct(flp, n),
        immfail_pct = pct(len(imm), n),
        fexp_pct    = pct(len(fexp), n),
        reach_1atr  = pct(df["did_100"].sum(), n),
        lock_count  = len(lk),
        lock_neg    = len(lk_neg),
    )


def main() -> None:
    dfs = load_all()
    if not dfs:
        print("No data files found."); return

    labels = list(dfs.keys())
    mets   = {l: metrics(dfs[l]) for l in labels}
    n_base = mets[labels[0]]["n"] if labels else 1

    # ── SUMMARY TABLE ────────────────────────────────────────────────────────
    sep("SUMMARY COMPARISON TABLE")
    print(f"\n  {'Filter':<20}  {'n':>5}  {'Kept%':>6}  {'WR':>6}  {'EV':>8}  "
          f"{'PF':>5}  {'MaxDD':>10}  {'ImmFail':>8}  {'FlipExp':>7}")
    print("  " + "-" * 92)
    for l in labels:
        m = mets[l]
        print(f"  {l:<20}  {m['n']:>5,}  {pct(m['n'],n_base):>5.1f}%  "
              f"{m['wr']:>5.1f}%  {m['ev']:>+8.1f}  "
              f"{m['pf']:>5.3f}  {m['max_dd']:>+10,.0f}  "
              f"{m['immfail_pct']:>7.1f}%  {m['fexp_pct']:>6.1f}%")

    # ── FULL METRICS ─────────────────────────────────────────────────────────
    sep("FULL METRICS PER FILTER")
    for l in labels:
        m = mets[l]
        print(f"\n  [{l}]  n={m['n']:,} ({pct(m['n'],n_base):.0f}%)  "
              f"WR={m['wr']:.1f}%  EV={m['ev']:+.1f}  "
              f"TotPnL={m['total']:+,.0f}  PF={m['pf']:.3f}  MaxDD={m['max_dd']:+,.0f}")
        print(f"    Winners:  avg={m['avg_win']:+.1f}  median={m['med_win']:+.1f}")
        print(f"    Losers:   avg={m['avg_los']:+.1f}  median={m['med_los']:+.1f}")
        print(f"    Exits:    initial_stop={m['pct_istop']:.1f}%  "
              f"lock_floor={m['pct_lock']:.1f}%  regime_flip={m['pct_flip']:.1f}%")
        print(f"    Diagnos:  ImmFail={m['immfail_pct']:.1f}%  "
              f"FlipExp={m['fexp_pct']:.1f}%  reach+1A={m['reach_1atr']:.1f}%  "
              f"lock_arms={m['lock_count']:,}  lock_then_neg={m['lock_neg']:,}")

    # ── EXIT BREAKDOWN ────────────────────────────────────────────────────────
    sep("EXIT BREAKDOWN")
    print(f"\n  {'Filter':<20}  {'initial_stop':>14}  {'lock_floor':>12}  {'regime_flip':>12}")
    print("  " + "-" * 63)
    for l in labels:
        df = dfs[l]; n = len(df)
        ist = (df["exit_reason"] == "initial_stop").sum()
        lfl = (df["exit_reason"] == "lock_floor").sum()
        flp = (df["exit_reason"] == "regime_flip").sum()
        print(f"  {l:<20}  "
              f"{ist:>5,} ({pct(ist,n):>4.1f}%)  "
              f"{lfl:>4,} ({pct(lfl,n):>4.1f}%)  "
              f"{flp:>4,} ({pct(flp,n):>4.1f}%)")

    # ── ARCHETYPE ────────────────────────────────────────────────────────────
    sep("ARCHETYPE DISTRIBUTION")
    archs = ["ImmFail", "PartRun", "VShape/Mid", "LockFloor",
             "FlipNeg", "FlipMod", "FlipRun", "FlipExp"]
    print(f"\n  {'Archetype':<12}", end="")
    for l in labels:
        print(f"  {l[:17]:>17}", end="")
    print()
    print("  " + "-" * (12 + 19 * len(labels)))
    for arch in archs:
        print(f"  {arch:<12}", end="")
        for l in labels:
            df = dfs[l]; sub = df[df["arch"] == arch]
            print(f"  {len(sub):>5,} ({pct(len(sub),len(df)):>4.1f}%)", end="")
        print()

    # ── MONTHLY EV ───────────────────────────────────────────────────────────
    sep("MONTHLY EV/TRADE")
    all_months = sorted(set(m for df in dfs.values() for m in df["ym"].unique()))
    print(f"\n  {'Month':<8}", end="")
    for l in labels:
        print(f"  {'n':>4} {'EV':>8}", end="")
    print()
    print("  " + "-" * (8 + 14 * len(labels)))
    for ym in all_months:
        print(f"  {ym:<8}", end="")
        for l in labels:
            sub = dfs[l][dfs[l]["ym"] == ym]
            if len(sub) == 0:
                print(f"  {'':>4} {'':>8}", end="")
            else:
                print(f"  {len(sub):>4,} {ev(sub['pnl']):>+8.1f}", end="")
        print()

    # ── INTERPRETATION ────────────────────────────────────────────────────────
    sep("INTERPRETATION")

    print("\n  1. Does any filter materially reduce ImmFail%?")
    base_imm = mets[labels[0]]["immfail_pct"]
    for l in labels:
        m = mets[l]
        delta = m["immfail_pct"] - base_imm
        print(f"     {l:<20}: ImmFail={m['immfail_pct']:.1f}%  "
              f"(delta={delta:+.1f}pp vs baseline)")

    print("\n  2. Trade retention vs EV improvement:")
    for l in labels:
        m = mets[l]
        print(f"     {l:<20}: kept={pct(m['n'],n_base):.0f}%  EV={m['ev']:+.1f}  "
              f"PF={m['pf']:.3f}")

    print("\n  3. Lock effectiveness (reach+1A %):")
    for l in labels:
        m = mets[l]
        print(f"     {l:<20}: reach+1A={m['reach_1atr']:.1f}%  "
              f"arms={m['lock_count']:,}  lock_neg={m['lock_neg']:,}")

    print("\n  4. Best candidate (highest EV with reasonable retention):")
    candidates = [(mets[l]["ev"], pct(mets[l]["n"], n_base), l)
                  for l in labels if pct(mets[l]["n"], n_base) >= 30]
    if candidates:
        candidates.sort(reverse=True)
        best_ev, best_kept, best_l = candidates[0]
        print(f"     -> {best_l}: EV={best_ev:+.1f}  kept={best_kept:.0f}%")
        if best_ev > mets[labels[0]]["ev"]:
            delta = best_ev - mets[labels[0]]["ev"]
            print(f"        Improves baseline by {delta:+.1f}/trade")
        else:
            print(f"        Does NOT improve baseline EV — abandon filter branch")
    else:
        print("     -> All filters with >=30% retention are negative: abandon this branch")

    sep("DONE")


if __name__ == "__main__":
    main()
