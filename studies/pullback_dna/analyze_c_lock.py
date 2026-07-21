"""Analyze CLockStrategy NT results vs offline simulation baseline."""
from __future__ import annotations
import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd

RESULTS = Path("studies/pullback_dna/results")
MULT    = 20.0
COMM    = 4.06


def pct(v, t):  return 0.0 if t == 0 else 100.0 * v / t
def wr(p):      return pct((p > 0).sum(), len(p)) if len(p) else float("nan")
def ev(p):      return p.mean() if len(p) else float("nan")
def pf(p):
    w = p[p > 0].sum(); l = abs(p[p < 0].sum())
    return w / l if l > 0 else float("inf")
def max_dd(p):
    eq = p.cumsum(); return (eq - eq.cummax()).min()
def sep(t="", w=84):
    pad = (w-len(t)-2)//2 if t else 0
    print("\n" + ("="*pad + f" {t} " + "="*pad if t else "-"*w))


def classify(row) -> str:
    rsn = row["exit_reason"]
    mfe = row["max_mfe_atr"]
    if rsn in ("initial_stop", "lock_floor", "sl"):
        did_025 = row.get("did_025", mfe >= 0.25)
        did_050 = row.get("did_050", mfe >= 0.50)
        did_100 = row.get("did_100", mfe >= 1.00)
        if not did_025: return "ImmFail"
        if not did_050: return "PartRun"
        if not did_100: return "VShape/Mid"
        return "LockFloor" if rsn == "lock_floor" else "DeepRev"
    # regime_flip
    if mfe < 0.25: return "FlipNeg"
    if mfe < 1.00: return "FlipMod"
    if mfe < 2.00: return "FlipRun"
    return "FlipExp"


def main() -> None:
    df = pd.read_parquet(RESULTS / "c_lock_2024_2026.parquet")
    df["entry_dt"] = pd.to_datetime(df["entry_ts"], unit="ns", utc=True)
    df["year"]     = df["entry_dt"].dt.year
    df["ym"]       = df["entry_dt"].dt.to_period("M").astype(str)
    df["arch"]     = df.apply(classify, axis=1)

    p = df["pnl"]

    sep("NT RESULTS: TRIGGER C + 0.50A STOP + LOCK@+1.00 (2024-2026)")

    print(f"\n  n={len(df):,}  WR={wr(p):.1f}%  EV={ev(p):+.1f}  "
          f"TotPnL={p.sum():+,.0f}  PF={pf(p):.2f}  MaxDD={max_dd(p):+,.0f}")

    sep("EXIT REASON BREAKDOWN")
    reasons = df["exit_reason"].value_counts()
    total = len(df)
    wins  = df[p > 0]
    loss  = df[p < 0]
    print(f"\n  {'Exit reason':<18}  {'n':>6}  {'%':>6}  {'WR':>6}  {'Avg EV':>9}  {'Avg MFE':>9}")
    for rsn in ["initial_stop", "lock_floor", "regime_flip"]:
        sub = df[df["exit_reason"] == rsn]
        if len(sub) == 0: continue
        sp  = sub["pnl"]
        print(f"  {rsn:<18}  {len(sub):>6,}  {pct(len(sub),total):>5.1f}%  "
              f"{wr(sp):>5.1f}%  {ev(sp):>+9.1f}  "
              f"{sub['max_mfe_atr'].mean():>8.3f}A")

    sep("ARCHETYPE TABLE")
    archs = ["ImmFail","PartRun","VShape/Mid","LockFloor","DeepRev",
             "FlipNeg","FlipMod","FlipRun","FlipExp"]
    print(f"\n  {'Archetype':<14}  {'n':>6}  {'%':>6}  {'WR':>6}  "
          f"{'Avg EV':>9}  {'MFE':>8}  {'MAE':>8}  {'Hold':>7}")
    for arch in archs:
        sub = df[df["arch"] == arch]
        if len(sub) == 0: continue
        sp  = sub["pnl"]
        print(f"  {arch:<14}  {len(sub):>6,}  {pct(len(sub),total):>5.1f}%  "
              f"{wr(sp):>5.1f}%  {ev(sp):>+9.1f}  "
              f"{sub['max_mfe_atr'].mean():>7.3f}A  "
              f"{sub['max_mae_atr'].mean():>7.3f}A  "
              f"{(sub['hold_s']/60).mean():>6.0f}m")

    sep("YEAR-BY-YEAR")
    print(f"\n  {'Year':<6}  {'n':>6}  {'WR':>6}  {'EV':>9}  "
          f"{'TotPnL':>10}  {'PF':>5}  {'MaxDD':>10}")
    for yr in sorted(df["year"].unique()):
        sub = df[df["year"] == yr]; sp = sub["pnl"]
        print(f"  {yr:<6}  {len(sub):>6,}  {wr(sp):>5.1f}%  "
              f"{ev(sp):>+9.1f}  {sp.sum():>+10,.0f}  "
              f"{pf(sp):>5.2f}  {max_dd(sp):>+10,.0f}")
    print(f"  {'Total':<6}  {len(df):>6,}  {wr(p):>5.1f}%  "
          f"{ev(p):>+9.1f}  {p.sum():>+10,.0f}  "
          f"{pf(p):>5.2f}  {max_dd(p):>+10,.0f}")

    sep("MONTHLY EV")
    months = sorted(df["ym"].unique())
    print(f"\n  {'Month':<8}  {'n':>5}  {'WR':>6}  {'EV':>9}  {'TotPnL':>9}")
    for ym in months:
        sub = df[df["ym"] == ym]; sp = sub["pnl"]
        print(f"  {ym:<8}  {len(sub):>5,}  {wr(sp):>5.1f}%  "
              f"{ev(sp):>+9.1f}  {sp.sum():>+9,.0f}")

    sep("LOCK MECHANICS")
    locked    = df[df["lock_armed"]]
    not_lock  = df[~df["lock_armed"]]
    lock_exit = df[df["exit_reason"] == "lock_floor"]
    init_exit = df[df["exit_reason"] == "initial_stop"]
    flip_exit = df[df["exit_reason"] == "regime_flip"]

    print(f"\n  Lock ever armed:     {len(locked):,}  ({pct(len(locked),total):.1f}%)")
    print(f"  Lock floor exits:    {len(lock_exit):,}  ({pct(len(lock_exit),total):.1f}%)")
    print(f"  Initial stop exits:  {len(init_exit):,}  ({pct(len(init_exit),total):.1f}%)")
    print(f"  Regime flip exits:   {len(flip_exit):,}  ({pct(len(flip_exit),total):.1f}%)")

    print(f"\n  Of trades where lock armed ({len(locked):,}):")
    lp = locked["pnl"]
    print(f"    WR={wr(lp):.1f}%  EV={ev(lp):+.1f}  avg MFE={locked['max_mfe_atr'].mean():.2f}A")
    lf = locked[locked["exit_reason"] == "lock_floor"]
    lr = locked[locked["exit_reason"] == "regime_flip"]
    print(f"    Exited via lock floor: {len(lf):,} ({pct(len(lf),len(locked)):.0f}%)  "
          f"avg pnl={lf['pnl'].mean():+.1f}")
    print(f"    Exited via regime flip: {len(lr):,} ({pct(len(lr),len(locked)):.0f}%)  "
          f"avg pnl={lr['pnl'].mean():+.1f}")

    print(f"\n  Avg initial stop loss:  {init_exit['pnl'].mean():+.1f}  "
          f"(theoretical {-0.50*20-COMM:.1f} at exactly 0.50A)")
    print(f"  Avg lock floor gain:    {lock_exit['pnl'].mean():+.1f}  "
          f"(theoretical {0.25*20-COMM:.1f} at exactly 0.25A)")
    if len(flip_exit):
        print(f"  Avg regime flip EV:     {flip_exit['pnl'].mean():+.1f}  "
              f"(WR={wr(flip_exit['pnl']):.1f}%)")

    sep("VS OFFLINE SIMULATION (Jul 2024-Jun 2025 overlap)")
    # Load trigger_C baseline for overlap period
    try:
        tc = pd.read_parquet(RESULTS / "trigger_C.parquet")
        tc["entry_dt"] = pd.to_datetime(tc["entry_ts"], unit="ns", utc=True)
        overlap_start  = pd.Timestamp("2024-07-01", tz="UTC")
        overlap_end    = pd.Timestamp("2025-06-30 23:59:59", tz="UTC")
        tc_ov = tc[(tc["entry_dt"] >= overlap_start) & (tc["entry_dt"] <= overlap_end)]

        nt_ov = df[(df["entry_dt"] >= overlap_start) & (df["entry_dt"] <= overlap_end)]

        print(f"\n  Period: Jul 2024 - Jun 2025")
        print(f"  Trigger C structural (offline sim): n={len(tc_ov):,}  "
              f"EV={tc_ov['pnl'].mean():+.1f}  WR={wr(tc_ov['pnl']):.1f}%")
        print(f"  C + 0.50A + lock@1.00 (offline sim): EV=+9.4  WR=23.2%  "
              f"(from lock_geometry.py)")
        print(f"  C + 0.50A + lock@1.00 (NT actual):   n={len(nt_ov):,}  "
              f"EV={nt_ov['pnl'].mean():+.1f}  WR={wr(nt_ov['pnl']):.1f}%")
    except FileNotFoundError:
        print("  trigger_C.parquet not found for comparison")

    sep("DONE")


if __name__ == "__main__":
    main()
