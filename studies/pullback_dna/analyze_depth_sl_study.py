"""Analyze pullback depth x initial stop width structural test for Trigger C."""
from __future__ import annotations
import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd
import numpy as np

RESULTS = Path("studies/pullback_dna/results/depth_sl_study")

VARIANTS = [
    ("baseline",       "baseline      / 0.50A SL"),
    ("base_075sl",     "baseline      / 0.75A SL"),
    ("depth075_050sl", "depth>=0.75A  / 0.50A SL"),
    ("depth075_075sl", "depth>=0.75A  / 0.75A SL"),
    ("depth100_075sl", "depth>=1.00A  / 0.75A SL"),
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
    sl  = row["initial_stop_atr"]
    # ImmFail: stopped before reaching 25% of the way to lock
    if rsn in ("initial_stop", "lock_floor", "sl"):
        if mfe < 0.25: return "ImmFail"
        if mfe < sl:   return "PartRun"    # survived initial stop zone but stopped before lock range
        if mfe < 1.00: return "VShape/Mid"
        return "LockFloor"
    if mfe < 0.25:  return "FlipNeg"
    if mfe < 1.00:  return "FlipMod"
    if mfe < 2.00:  return "FlipRun"
    return "FlipExp"


def load_all() -> dict[str, pd.DataFrame]:
    dfs = {}
    for slug, label in VARIANTS:
        path = RESULTS / f"depth_sl_{slug}.parquet"
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
    sl_atr = df["initial_stop_atr"].iloc[0] if n else 0.50
    return dict(
        n           = n,
        sl_atr      = sl_atr,
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
        med_depth   = df["max_pb_depth_atr"].median() if "max_pb_depth_atr" in df.columns else float("nan"),
        p25_depth   = df["max_pb_depth_atr"].quantile(0.25) if "max_pb_depth_atr" in df.columns else float("nan"),
    )


def main() -> None:
    dfs = load_all()
    if not dfs:
        print("No data files found."); return

    labels = list(dfs.keys())
    mets   = {l: metrics(dfs[l]) for l in labels}
    n_base = mets[labels[0]]["n"] if labels else 1

    # ── PULLBACK DEPTH DISTRIBUTION (baseline) ────────────────────────────────
    if labels and "max_pb_depth_atr" in dfs[labels[0]].columns:
        sep("BASELINE PULLBACK DEPTH DISTRIBUTION")
        base_df = dfs[labels[0]]
        d_col   = base_df["max_pb_depth_atr"]
        buckets = [0, 0.25, 0.50, 0.75, 1.00, 1.25, 1.50, 2.00, 999]
        print(f"\n  {'Depth range':<18}  {'n':>5}  {'%':>6}  {'cumul%':>7}")
        print("  " + "-" * 42)
        cumul = 0
        for lo, hi in zip(buckets, buckets[1:]):
            sub = base_df[(d_col >= lo) & (d_col < hi)]
            cumul += len(sub)
            label = f"{lo:.2f}A – {hi:.2f}A" if hi < 999 else f"{lo:.2f}A +"
            print(f"  {label:<18}  {len(sub):>5,}  "
                  f"{pct(len(sub), len(base_df)):>5.1f}%  "
                  f"{pct(cumul, len(base_df)):>6.1f}%")
        print(f"\n  Median depth: {d_col.median():.3f}A   "
              f"P25: {d_col.quantile(0.25):.3f}A   "
              f"P75: {d_col.quantile(0.75):.3f}A")

    # ── SUMMARY TABLE ─────────────────────────────────────────────────────────
    sep("SUMMARY COMPARISON TABLE")
    print(f"\n  {'Variant':<30}  {'n':>5}  {'Kept%':>6}  {'WR':>6}  "
          f"{'EV':>8}  {'PF':>5}  {'MaxDD':>10}  {'ImmFail':>8}  {'FlipExp':>7}")
    print("  " + "-" * 105)
    for l in labels:
        m = mets[l]
        print(f"  {l:<30}  {m['n']:>5,}  {pct(m['n'],n_base):>5.1f}%  "
              f"{m['wr']:>5.1f}%  {m['ev']:>+8.1f}  "
              f"{m['pf']:>5.3f}  {m['max_dd']:>+10,.0f}  "
              f"{m['immfail_pct']:>7.1f}%  {m['fexp_pct']:>6.1f}%")

    # ── FULL METRICS ──────────────────────────────────────────────────────────
    sep("FULL METRICS")
    for l in labels:
        m = mets[l]
        print(f"\n  [{l}]")
        print(f"    n={m['n']:,} ({pct(m['n'],n_base):.0f}%)  "
              f"SL={m['sl_atr']:.2f}A  WR={m['wr']:.1f}%  "
              f"EV={m['ev']:+.1f}  TotPnL={m['total']:+,.0f}  "
              f"PF={m['pf']:.3f}  MaxDD={m['max_dd']:+,.0f}")
        print(f"    Winners:  avg={m['avg_win']:+.1f}  median={m['med_win']:+.1f}")
        print(f"    Losers:   avg={m['avg_los']:+.1f}  median={m['med_los']:+.1f}")
        print(f"    Exits:    initial_stop={m['pct_istop']:.1f}%  "
              f"lock_floor={m['pct_lock']:.1f}%  regime_flip={m['pct_flip']:.1f}%")
        print(f"    Diagnos:  ImmFail={m['immfail_pct']:.1f}%  "
              f"FlipExp={m['fexp_pct']:.1f}%  reach+1A={m['reach_1atr']:.1f}%  "
              f"lock_arms={m['lock_count']:,}  lock_neg={m['lock_neg']:,}")
        print(f"    Depth:    median_max_pb={m['med_depth']:.3f}A  "
              f"P25_max_pb={m['p25_depth']:.3f}A")

    # ── EXIT BREAKDOWN ────────────────────────────────────────────────────────
    sep("EXIT BREAKDOWN")
    print(f"\n  {'Variant':<30}  {'initial_stop':>14}  {'lock_floor':>12}  {'regime_flip':>12}")
    print("  " + "-" * 75)
    for l in labels:
        df = dfs[l]; n = len(df)
        ist = (df["exit_reason"] == "initial_stop").sum()
        lfl = (df["exit_reason"] == "lock_floor").sum()
        flp = (df["exit_reason"] == "regime_flip").sum()
        print(f"  {l:<30}  "
              f"{ist:>5,} ({pct(ist,n):>4.1f}%)  "
              f"{lfl:>4,} ({pct(lfl,n):>4.1f}%)  "
              f"{flp:>4,} ({pct(flp,n):>4.1f}%)")

    # ── ARCHETYPE ─────────────────────────────────────────────────────────────
    sep("ARCHETYPE DISTRIBUTION")
    archs = ["ImmFail", "PartRun", "VShape/Mid", "LockFloor",
             "FlipNeg", "FlipMod", "FlipRun", "FlipExp"]
    short_labels = [l[:18] for l in labels]
    print(f"\n  {'Archetype':<12}", end="")
    for sl in short_labels:
        print(f"  {sl:>20}", end="")
    print()
    print("  " + "-" * (12 + 22 * len(labels)))
    for arch in archs:
        print(f"  {arch:<12}", end="")
        for l in labels:
            df = dfs[l]; sub = df[df["arch"] == arch]
            print(f"  {len(sub):>5,} ({pct(len(sub),len(df)):>4.1f}%)", end="")
        print()

    # ── MONTHLY EV ────────────────────────────────────────────────────────────
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
    sep("INTERPRETATION: DECISION CRITERIA")

    print("\n  Criteria: PF > 1.0 = breakeven; PF > 1.10 = meaningful signal")
    print(f"\n  {'Variant':<30}  {'PF':>6}  {'PF>1.0?':>8}  {'PF>1.10?':>9}  {'DD ok?':>7}")
    print("  " + "-" * 70)
    for l in labels:
        m = mets[l]
        pf_ok  = "YES" if m["pf"] >= 1.0  else "no"
        pf110  = "YES" if m["pf"] >= 1.10 else "no"
        dd_ok  = "YES" if m["max_dd"] >= -50_000 else "no"
        print(f"  {l:<30}  {m['pf']:>6.3f}  {pf_ok:>8}  {pf110:>9}  {dd_ok:>7}")

    print("\n  Key question: Does 0.75A SL improve survival without destroying EV?")
    print("  (Compare ImmFail% and initial_stop% between 0.50A and 0.75A variants)")

    print("\n  Depth filter question: Does depth>=0.75A or depth>=1.00A")
    print("  reduce ImmFail% enough to compensate for the trade count loss?")

    # Summary judgment
    print("\n  Summary:")
    best_pf = max(mets[l]["pf"] for l in labels)
    best_l  = max(labels, key=lambda l: mets[l]["pf"])
    any_positive = any(mets[l]["pf"] >= 1.0 for l in labels)
    print(f"    Best PF: {best_pf:.3f} ({best_l})")
    if any_positive:
        positives = [l for l in labels if mets[l]["pf"] >= 1.0]
        print(f"    PF>=1.0 variants: {', '.join(positives)}")
        print(f"    -> Warrant further expansion testing on 2022-2026")
    else:
        print(f"    -> All variants negative. Close Trigger C as non-monetizable in current form.")

    sep("DONE")


if __name__ == "__main__":
    main()
