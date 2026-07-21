"""Analyze hC threshold study results for Trigger C + 0.50A stop + lock@+1.00."""
from __future__ import annotations
import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd

RESULTS = Path("studies/pullback_dna/results/hc_study")
MULT    = 20.0
COMM    = 4.06

CONFIGS = [
    ("0.00", "hc000", "Unfiltered"),
    ("0.50", "hc050", "hC>=0.50 (baseline)"),
    ("0.75", "hc075", "hC>=0.75"),
    ("1.00", "hc100", "hC>=1.00"),
]


def pct(v, t):  return 0.0 if t == 0 else 100.0 * v / t
def wr(p):      return pct((p > 0).sum(), len(p)) if len(p) else float("nan")
def ev(p):      return p.mean() if len(p) else float("nan")
def med(p):     return p.median() if len(p) else float("nan")
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
        return "LockFloor" if rsn == "lock_floor" else "DeepRev"
    if mfe < 0.25:  return "FlipNeg"
    if mfe < 1.00:  return "FlipMod"
    if mfe < 2.00:  return "FlipRun"
    return "FlipExp"


def load_all() -> dict[str, pd.DataFrame]:
    dfs = {}
    for floor, slug, label in CONFIGS:
        path = RESULTS / f"hc_study_{slug}.parquet"
        if not path.exists():
            print(f"  MISSING: {path.name}")
            continue
        df = pd.read_parquet(path)
        df["entry_dt"] = pd.to_datetime(df["entry_ts"], unit="ns", utc=True)
        df["year"]     = df["entry_dt"].dt.year
        df["ym"]       = df["entry_dt"].dt.to_period("M").astype(str)
        df["arch"]     = df.apply(classify, axis=1)
        dfs[label]     = df
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
    return dict(
        n          = n,
        wr         = wr(p),
        ev         = ev(p),
        total      = p.sum(),
        pf         = pf(p),
        max_dd     = max_dd(p),
        avg_win    = win["pnl"].mean() if len(win) else float("nan"),
        med_win    = win["pnl"].median() if len(win) else float("nan"),
        avg_los    = los["pnl"].mean() if len(los) else float("nan"),
        med_los    = los["pnl"].median() if len(los) else float("nan"),
        pct_istop  = pct((df["exit_reason"] == "initial_stop").sum(), n),
        pct_lock   = pct((df["exit_reason"] == "lock_floor").sum(), n),
        pct_flip   = pct((df["exit_reason"] == "regime_flip").sum(), n),
        immfail_pct= pct(len(imm), n),
        fexp_pct   = pct(len(fexp), n),
        reach_1atr = pct(df["did_100"].sum(), n),
        reach_1atr_neg = len(lk_neg),
        lock_count = len(lk),
    )


def main() -> None:
    dfs = load_all()
    if not dfs:
        print("No data files found."); return

    # ── COMPARISON TABLE ────────────────────────────────────────────────────
    sep("SUMMARY COMPARISON TABLE")
    print(f"\n  {'Config':<24}  {'n':>5}  {'WR':>6}  {'EV':>8}  "
          f"{'PF':>5}  {'MaxDD':>10}  {'ImmFail':>8}  {'FlipExp':>8}")
    print("  " + "-" * 85)
    for label, df in dfs.items():
        m = metrics(df)
        print(f"  {label:<24}  {m['n']:>5,}  {m['wr']:>5.1f}%  {m['ev']:>+8.1f}  "
              f"{m['pf']:>5.2f}  {m['max_dd']:>+10,.0f}  "
              f"{m['immfail_pct']:>7.1f}%  {m['fexp_pct']:>7.1f}%")

    # ── FULL METRICS PER CONFIG ─────────────────────────────────────────────
    sep("FULL METRICS PER CONFIG")
    for label, df in dfs.items():
        m = metrics(df)
        print(f"\n  [{label}]  n={m['n']:,}  WR={m['wr']:.1f}%  "
              f"EV={m['ev']:+.1f}  TotPnL={m['total']:+,.0f}  "
              f"PF={m['pf']:.2f}  MaxDD={m['max_dd']:+,.0f}")
        print(f"    Winners:  avg={m['avg_win']:+.1f}  median={m['med_win']:+.1f}")
        print(f"    Losers:   avg={m['avg_los']:+.1f}  median={m['med_los']:+.1f}")
        print(f"    Exits:    initial_stop={m['pct_istop']:.1f}%  "
              f"lock_floor={m['pct_lock']:.1f}%  regime_flip={m['pct_flip']:.1f}%")
        print(f"    Diagnos:  ImmFail={m['immfail_pct']:.1f}%  "
              f"FlipExp={m['fexp_pct']:.1f}%  "
              f"reach+1A={m['reach_1atr']:.1f}%  "
              f"lock_arms={m['lock_count']:,}  "
              f"lock_then_neg={m['reach_1atr_neg']:,}")

    # ── EXIT BREAKDOWN ───────────────────────────────────────────────────────
    sep("EXIT BREAKDOWN BY CONFIG")
    print(f"\n  {'Config':<24}  {'initial_stop':>13}  {'lock_floor':>11}  {'regime_flip':>12}")
    print("  " + "-" * 65)
    for label, df in dfs.items():
        n = len(df)
        ist = (df["exit_reason"] == "initial_stop").sum()
        lfl = (df["exit_reason"] == "lock_floor").sum()
        flp = (df["exit_reason"] == "regime_flip").sum()
        print(f"  {label:<24}  "
              f"{ist:>5,} ({pct(ist,n):>4.1f}%)  "
              f"{lfl:>4,} ({pct(lfl,n):>4.1f}%)  "
              f"{flp:>4,} ({pct(flp,n):>4.1f}%)")

    # ── ARCHETYPE TABLE ───────────────────────────────────────────────────────
    sep("ARCHETYPE DISTRIBUTION")
    archs = ["ImmFail", "PartRun", "VShape/Mid", "LockFloor",
             "DeepRev", "FlipNeg", "FlipMod", "FlipRun", "FlipExp"]
    print(f"\n  {'Archetype':<13}", end="")
    for label, _ in dfs.items():
        short = label.replace("(baseline)", "").strip()[:14]
        print(f"  {short:>16}", end="")
    print()
    print("  " + "-" * (13 + 18 * len(dfs)))
    for arch in archs:
        print(f"  {arch:<13}", end="")
        for label, df in dfs.items():
            sub = df[df["arch"] == arch]
            print(f"  {len(sub):>5,} ({pct(len(sub),len(df)):>4.1f}%)", end="")
        print()

    # ── MONTHLY EV ────────────────────────────────────────────────────────────
    sep("MONTHLY EV/TRADE")
    # Collect all months across all configs
    all_months = sorted(set(m for df in dfs.values() for m in df["ym"].unique()))
    header = f"  {'Month':<8}"
    for label, _ in dfs.items():
        short = label.replace("(baseline)", "").strip()[:12]
        print_hdr = True
    print(f"\n  {'Month':<8}", end="")
    for label, _ in dfs.items():
        short = label[:12]
        print(f"  {'n':>4} {'EV':>8}", end="")
    print()
    print("  " + "-" * (8 + 14 * len(dfs)))
    for ym in all_months:
        print(f"  {ym:<8}", end="")
        for label, df in dfs.items():
            sub = df[df["ym"] == ym]
            sp  = sub["pnl"]
            if len(sub) == 0:
                print(f"  {'':>4} {'':>8}", end="")
            else:
                print(f"  {len(sub):>4,} {ev(sp):>+8.1f}", end="")
        print()

    # ── INTERPRETATION QUESTIONS ──────────────────────────────────────────────
    sep("INTERPRETATION")

    labels   = list(dfs.keys())
    mets     = {l: metrics(dfs[l]) for l in labels}

    print("\n  1. Does increasing hC materially reduce ImmediateFail?")
    for l in labels:
        m = mets[l]
        print(f"     {l:<28}: ImmFail={m['immfail_pct']:.1f}%  "
              f"(n_immfail={int(m['immfail_pct']*m['n']/100):.0f})")

    print("\n  2. Does it preserve enough trades to matter?")
    n_base = mets[labels[0]]["n"] if labels else 1
    for l in labels:
        m = mets[l]
        print(f"     {l:<28}: n={m['n']:,}  "
              f"({pct(m['n'], n_base):.0f}% of unfiltered)")

    print("\n  3. Does lock effectiveness improve (reach+1A rate)?")
    for l in labels:
        m = mets[l]
        print(f"     {l:<28}: reach+1A={m['reach_1atr']:.1f}%  "
              f"lock_arms={m['lock_count']:,}  "
              f"lock_then_neg={m['reach_1atr_neg']:,}")

    print("\n  4. EV and PF progression:")
    for l in labels:
        m = mets[l]
        print(f"     {l:<28}: EV={m['ev']:+.1f}  PF={m['pf']:.3f}  "
              f"MaxDD={m['max_dd']:+,.0f}")

    sep("DONE")


if __name__ == "__main__":
    main()
