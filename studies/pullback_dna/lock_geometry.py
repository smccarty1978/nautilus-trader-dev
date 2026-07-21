"""Profit-lock overlay study for Trigger C entries.

Tests 5 management policies against 2 fixed initial stops
(0.25 ATR and 0.50 ATR from entry), on the Jul 2024-Jun 2025 window.

Policies
--------
P1  No lock         (baseline for each stop level)
P2  BE at +0.50A    move SL to entry once +0.50A MFE reached
P3  BE at +0.75A    move SL to entry once +0.75A MFE reached
P4  Lock +0.25A     at +1.00A MFE, floor at +0.25A profit
P5  Lock +0.50A     at +1.50A MFE, floor at +0.50A profit

Simulation accuracy
-------------------
Initial stop (EXACT for sl-exits, CONSERVATIVE for flip-exits):
  If exit_reason=="sl" and stop_atr < sl_risk_atr: fixed stop fires first — EXACT
  If exit_reason=="regime_flip" and max_mae_atr >= stop_atr: stop assumed to
    fire (conservative — timing of MAE vs MFE is unknown).

Profit lock for surviving trades:
  P2 (BE at +0.50): EXACT via after_050_revisit_entry flag.
    If did_050 AND after_050_revisit_entry: BE fires → pnl = -COMM.
    If did_050 AND NOT after_050_revisit_entry: trade never revisited entry → original.
    This correctly handles cases where price revisited entry THEN recovered (lock fires,
    runner gains lost — which max() would incorrectly preserve).

  P3 (BE at +0.75), P4, P5: APPROXIMATE via max(pnl, floor_pnl) for qualifying trades.
    This understates lock benefit for cases where the floor stop truly fires (the trade
    would have exited at floor, not at the original regime exit). Direction of
    approximation error noted in output.

Usage:
    python studies/pullback_dna/lock_geometry.py
"""
from __future__ import annotations
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd

RESULTS = Path("studies/pullback_dna/results")
MULT    = 20.0
COMM    = 4.06

START   = pd.Timestamp("2024-07-01", tz="UTC")
END     = pd.Timestamp("2025-06-30 23:59:59", tz="UTC")

INITIAL_STOPS  = [0.25, 0.50]
# (lock_at_atr, floor_atr, label, exact_method)
LOCK_POLICIES  = [
    (None,  None,  "P1 No lock",      True ),
    (0.50,  0.00,  "P2 BE@+0.50",     True ),   # exact via after_050_revisit_entry
    (0.75,  0.00,  "P3 BE@+0.75",     False),   # approx
    (1.00,  0.25,  "P4 lock@+1.00",   False),   # approx
    (1.50,  0.50,  "P5 lock@+1.50",   False),   # approx
]


# ── Helpers ────────────────────────────────────────────────────────────────────

def pct(v, t):  return 0.0 if t == 0 else 100.0 * v / t
def wr(p):      return pct((p > 0).sum(), len(p)) if len(p) else float("nan")
def ev(p):      return p.mean()                   if len(p) else float("nan")
def pf(p):
    w = p[p > 0].sum(); l = abs(p[p < 0].sum())
    return w / l if l > 0 else float("inf")
def max_dd(p):
    eq = p.cumsum(); return (eq - eq.cummax()).min()

def sep(title="", w=88):
    if title:
        pad = (w - len(title) - 2) // 2
        print("\n" + "=" * pad + f" {title} " + "=" * pad)
    else:
        print("\n" + "-" * w)


# ── Archetype (original structural classification) ─────────────────────────────

def classify_orig(row) -> str:
    rsn = row["exit_reason"]
    if rsn == "sl":
        if not row["did_025"]: return "ImmediateFail"
        if not row["did_050"]: return "PartialRun"
        if not row["did_100"]:
            return "VShapeFail" if row["after_050_revisit_entry"] else "MidReverse"
        return "DeepReverse"
    mfe = row["max_mfe_atr"]
    if mfe < 0.25: return "FlipNegative"
    if mfe < 1.00: return "FlipModerate"
    if mfe < 2.00: return "FlipRunner"
    return "FlipExpansion"


# ── Step 1: apply fixed initial stop ──────────────────────────────────────────

def apply_initial_stop(df: pd.DataFrame, stop_atr: float) -> pd.DataFrame:
    """Returns df with sim_pnl, sim_stop_hit, sim_uncertain added.
    Exact for SL-exit trades; conservative for regime-flip exits."""
    out = df.copy()
    stop_pnl = -(stop_atr * out["atr_base"] * MULT) - COMM

    out["sim_pnl"]       = out["pnl"]
    out["sim_stop_hit"]  = False
    out["sim_uncertain"] = False

    # SL-exit: exact
    sl  = out["exit_reason"] == "sl"
    hit = sl & (stop_atr < out["sl_risk_atr"])
    out.loc[hit, "sim_pnl"]      = stop_pnl[hit]
    out.loc[hit, "sim_stop_hit"] = True

    # Regime-flip: conservative
    fl  = out["exit_reason"] == "regime_flip"
    fhit= fl & (out["max_mae_atr"] >= stop_atr)
    out.loc[fhit, "sim_pnl"]       = stop_pnl[fhit]
    out.loc[fhit, "sim_stop_hit"]  = True
    out.loc[fhit, "sim_uncertain"] = True

    return out


# ── Step 2: apply profit-lock overlay to surviving trades ─────────────────────

def apply_lock(sim: pd.DataFrame, lock_at_atr, floor_atr) -> pd.DataFrame:
    """Applies profit lock to trades that survived the initial stop."""
    if lock_at_atr is None:
        return sim

    out = sim.copy()
    alive = ~out["sim_stop_hit"]   # trades not stopped by initial stop

    floor_pnl_series = (floor_atr * out["atr_base"] * MULT) - COMM

    if lock_at_atr == 0.50:
        # EXACT: after_050_revisit_entry tells us whether BE fired
        did_lock = alive & out["did_050"]
        # BE fires: price revisited entry after reaching +0.50
        be_fires = did_lock & out["after_050_revisit_entry"]
        out.loc[be_fires, "sim_pnl"] = -COMM
        # Note: if did_050 and NOT after_050_revisit_entry: price never came back,
        # original outcome preserved (even if that's a loss — e.g. FlipNegative
        # that peaked at 0.49 would have did_050=False; FlipNegative with
        # did_050=True but no revisit is rare — trade didn't pull back to entry).
    else:
        # APPROXIMATE: if reached lock level and pnl < floor, assume floor fires.
        # Overstates performance for: trade hits lock floor, recovers to positive.
        # Understates for: trade hits lock floor, we exit, then would have recovered.
        if lock_at_atr == 0.75:
            did_lock = alive & (out["max_mfe_atr"] >= 0.75)
        elif lock_at_atr == 1.00:
            did_lock = alive & out["did_100"]
        elif lock_at_atr == 1.50:
            did_lock = alive & out["did_150"]
        else:
            raise ValueError(f"Unknown lock_at_atr={lock_at_atr}")

        worse_than_floor = out["sim_pnl"] < floor_pnl_series
        lock_fires = did_lock & worse_than_floor
        out.loc[lock_fires, "sim_pnl"] = floor_pnl_series[lock_fires]

    return out


# ── Metrics ────────────────────────────────────────────────────────────────────

def compute_metrics(label: str, df_orig: pd.DataFrame, sim: pd.DataFrame,
                    initial_stop: float | None, lock_at: float | None) -> dict:
    p       = sim["sim_pnl"]
    alive   = ~sim["sim_stop_hit"] if "sim_stop_hit" in sim.columns else pd.Series([True]*len(sim))
    winners = p[p > 0]
    losers  = p[p < 0]

    # Exit category counts
    if "sim_stop_hit" in sim.columns:
        initial_stop_n = sim["sim_stop_hit"].sum()
    else:
        initial_stop_n = 0

    # For lock analysis: how many alive trades hit the lock level
    if lock_at is not None and lock_at == 0.50:
        lock_armed = alive & sim["did_050"]
        lock_fired = alive & sim["did_050"] & sim["after_050_revisit_entry"]
    elif lock_at is not None:
        col = {0.75: None, 1.00: "did_100", 1.50: "did_150"}.get(lock_at)
        if col:
            lock_armed = alive & sim[col]
        else:
            lock_armed = alive & (sim["max_mfe_atr"] >= lock_at)
        # Approximate lock fires = those whose pnl was improved
        lock_fired = (sim["sim_pnl"] > sim["pnl"]) & alive
    else:
        lock_armed = pd.Series([False]*len(sim))
        lock_fired = pd.Series([False]*len(sim))

    regime_exit_n = (alive & (sim["exit_reason"] == "regime_flip")).sum() \
                    if lock_at is None else \
                    (alive & (sim["exit_reason"] == "regime_flip") & ~lock_fired).sum()

    # FlipExpansion survivors (not stopped by initial stop, not stopped by lock before expanding)
    flip_exp_surv = (alive &
                     (sim["exit_reason"] == "regime_flip") &
                     (sim["max_mfe_atr"] >= 2.0) &
                     (sim["sim_pnl"] > 0)).sum()

    return {
        "label":           label,
        "initial_stop":    initial_stop,
        "lock_at":         lock_at,
        "n":               len(sim),
        "wr":              wr(p),
        "ev":              ev(p),
        "total_pnl":       p.sum(),
        "pf":              pf(p),
        "max_dd":          max_dd(p),
        "avg_winner":      winners.mean() if len(winners) else float("nan"),
        "med_winner":      winners.median() if len(winners) else float("nan"),
        "avg_loser":       losers.mean()  if len(losers)  else float("nan"),
        "med_loser":       losers.median() if len(losers) else float("nan"),
        "init_stop_pct":   pct(initial_stop_n, len(sim)),
        "lock_armed_pct":  pct(lock_armed.sum(), len(sim)),
        "lock_fired_pct":  pct(lock_fired.sum(), len(sim)),
        "regime_exit_pct": pct(regime_exit_n, len(sim)),
        "flip_exp_surv":   flip_exp_surv,
        "flip_exp_pct":    pct(flip_exp_surv, len(sim)),
    }


# ── Reporting ──────────────────────────────────────────────────────────────────

def report_headline(rows: list[dict]) -> None:
    sep("HEADLINE: INITIAL STOP x LOCK POLICY")

    print(f"\n  {'Label':<28}  {'n':>6}  {'WR':>6}  {'EV':>8}  "
          f"{'TotPnL':>9}  {'PF':>5}  {'MaxDD':>10}  {'FlipExp%':>9}")
    last_stop = None
    for r in rows:
        if r["initial_stop"] != last_stop:
            print()
            last_stop = r["initial_stop"]
        s = r['initial_stop']
        lbl = "  struct" if s is None else f"  {s:.2f}A init"
        print(f"  {r['label']:<28}  {r['n']:>6,}  {r['wr']:>5.1f}%  "
              f"{r['ev']:>+8.1f}  {r['total_pnl']:>+9,.0f}  "
              f"{r['pf']:>5.2f}  {r['max_dd']:>+10,.0f}  "
              f"{r['flip_exp_pct']:>8.1f}%")


def report_exit_breakdown(rows: list[dict]) -> None:
    sep("EXIT BREAKDOWN")

    print(f"\n  {'Label':<28}  {'InitStop%':>10}  {'LockFired%':>11}  "
          f"{'RegExit%':>9}  {'AvgLoss':>9}  {'AvgWin':>9}")
    last_stop = None
    for r in rows:
        if r["initial_stop"] != last_stop:
            print()
            last_stop = r["initial_stop"]
        print(f"  {r['label']:<28}  {r['init_stop_pct']:>9.1f}%  "
              f"{r['lock_fired_pct']:>10.1f}%  "
              f"{r['regime_exit_pct']:>8.1f}%  "
              f"{r['avg_loser']:>+9.1f}  "
              f"{r['avg_winner']:>+9.1f}")


def report_monthly(df: pd.DataFrame, all_sims: list[tuple[str, pd.DataFrame]]) -> None:
    sep("MONTHLY EV BREAKDOWN")

    months = sorted(df["ym"].unique())
    labels = ["Structural"] + [lbl for lbl, _ in all_sims]

    # Print in two tables: 0.25A stop group and 0.50A stop group
    groups = {
        "Structural + 0.25A initial stop policies":
            [("Structural", df)] + [(l, s) for l, s in all_sims if "0.25A" in l],
        "Structural + 0.50A initial stop policies":
            [("Structural", df)] + [(l, s) for l, s in all_sims if "0.50A" in l],
    }

    for grp_title, grp_sims in groups.items():
        print(f"\n  -- {grp_title} --")
        hdrs = [f"{'Month':<8}"] + [f"{l[:12]:>13}" for l, _ in grp_sims]
        print("  " + "  ".join(hdrs))
        for ym in months:
            cols = []
            for lbl, sim in grp_sims:
                col = "pnl" if lbl == "Structural" else "sim_pnl"
                sub = sim[sim["ym"] == ym]
                cols.append(f"{sub[col].mean():>+13.1f}")
            print(f"  {ym:<8}  " + "  ".join(cols))
        print()
        total_cols = []
        for lbl, sim in grp_sims:
            col = "pnl" if lbl == "Structural" else "sim_pnl"
            total_cols.append(f"{sim[col].mean():>+13.1f}")
        print(f"  {'TOTAL':<8}  " + "  ".join(total_cols))


def report_runner_leakage(df: pd.DataFrame, sims_025: list, sims_050: list) -> None:
    sep("RUNNER LEAKAGE: TRADES THAT REACHED +1.0A MFE BUT ENDED NEGATIVE")

    print("\n  Without ANY lock or stop intervention:")
    leakers = df[(df["max_mfe_atr"] >= 1.0) & (df["pnl"] < 0)]
    print(f"    {len(leakers):,} trades reached +1.0A MFE, ended negative  "
          f"({pct(len(leakers),len(df)):.1f}% of all trades)")
    if len(leakers):
        print(f"    avg max_mfe: {leakers['max_mfe_atr'].mean():.2f}A  "
              f"avg pnl: {leakers['pnl'].mean():+.1f}  "
              f"avg final_mae: {leakers['max_mae_atr'].mean():.2f}A")

    for stop_lbl, sims in [("0.25A initial stop", sims_025), ("0.50A initial stop", sims_050)]:
        print(f"\n  With {stop_lbl} (no lock):")
        no_lock_sim = sims[0][1]  # P1
        alive = ~no_lock_sim["sim_stop_hit"]
        leak = no_lock_sim[alive & (no_lock_sim["max_mfe_atr"] >= 1.0) & (no_lock_sim["sim_pnl"] < 0)]
        print(f"    {len(leak):,} surviving trades reached +1.0A MFE, ended negative  "
              f"({pct(len(leak), alive.sum()):.1f}% of survivors)")
        if len(leak):
            print(f"    avg max_mfe: {leak['max_mfe_atr'].mean():.2f}A  "
                  f"avg sim_pnl: {leak['sim_pnl'].mean():+.1f}")
        for plbl, lock_sim in sims[1:]:  # P2-P5
            lock_alive = ~lock_sim["sim_stop_hit"]
            still_leak = lock_sim[lock_alive & (lock_sim["max_mfe_atr"] >= 1.0) & (lock_sim["sim_pnl"] < 0)]
            print(f"    {plbl}: {len(still_leak):,} still leak  "
                  f"({pct(len(still_leak),lock_alive.sum()):.1f}% of survivors)")


def report_be_050_exact(df: pd.DataFrame) -> None:
    """Deep dive on the exact BE-at-+0.50 data we have."""
    sep("EXACT BE@+0.50 ANALYSIS (via after_050_revisit_entry)")

    did50 = df[df["did_050"]]
    revisit = did50[did50["after_050_revisit_entry"]]
    no_rev  = did50[~did50["after_050_revisit_entry"]]
    not_did = df[~df["did_050"]]

    print(f"\n  Total window trades: {len(df):,}")
    print(f"  Reached +0.50A MFE:        {len(did50):,}  ({pct(len(did50),len(df)):.1f}%)")
    print(f"    Then revisited entry:    {len(revisit):,}  ({pct(len(revisit),len(did50)):.1f}% of those)")
    print(f"    Did NOT revisit entry:   {len(no_rev):,}  ({pct(len(no_rev),len(did50)):.1f}% of those)")
    print(f"  Never reached +0.50A MFE:  {len(not_did):,}")

    print(f"\n  Breakdown of revisit-entry group (BE would fire):")
    print(f"    avg pnl WITHOUT BE: {revisit['pnl'].mean():+.1f}  "
          f"median: {revisit['pnl'].median():+.1f}")
    print(f"    pnl WITH BE:   {-COMM:+.1f}  (exit at entry, pay commission)")
    print(f"    avg improvement: {-COMM - revisit['pnl'].mean():+.1f}/trade")
    print(f"    Archetypes in revisit group:")
    for arch, cnt in revisit["orig_arch"].value_counts().items():
        print(f"      {arch:<20}: {cnt:>4,}  ({pct(cnt,len(revisit)):.1f}%)")

    print(f"\n  Breakdown of no-revisit group (BE never fires):")
    print(f"    avg pnl: {no_rev['pnl'].mean():+.1f}  median: {no_rev['pnl'].median():+.1f}")
    print(f"    Archetypes:")
    for arch, cnt in no_rev["orig_arch"].value_counts().items():
        print(f"      {arch:<20}: {cnt:>4,}  ({pct(cnt,len(no_rev)):.1f}%)")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print("Loading trigger_C.parquet ...")
    df_all = pd.read_parquet(RESULTS / "trigger_C.parquet")
    df_all["entry_dt"]  = pd.to_datetime(df_all["entry_ts"], unit="ns", utc=True)
    df_all["orig_arch"] = df_all.apply(classify_orig, axis=1)
    df_all["ym"]        = df_all["entry_dt"].dt.to_period("M").astype(str)

    mask = (df_all["entry_dt"] >= START) & (df_all["entry_dt"] <= END)
    df   = df_all[mask].copy().reset_index(drop=True)
    print(f"  Window {START.date()} to {END.date()}: {len(df):,} trades")

    # Structural baseline (no fixed stop, no lock)
    df["sim_pnl"]      = df["pnl"]
    df["sim_stop_hit"] = False

    # Build all 10 combinations
    all_rows: list[dict]                      = []
    all_sims: list[tuple[str, pd.DataFrame]]  = []
    sims_025: list[tuple[str, pd.DataFrame]]  = []
    sims_050: list[tuple[str, pd.DataFrame]]  = []

    for init_stop in INITIAL_STOPS:
        stopped = apply_initial_stop(df, init_stop)

        for lock_at, floor_at, lock_lbl, exact in LOCK_POLICIES:
            sim   = apply_lock(stopped, lock_at, floor_at)
            label = f"{init_stop:.2f}A | {lock_lbl}"
            r     = compute_metrics(label, df, sim, init_stop, lock_at)
            all_rows.append(r)
            all_sims.append((label, sim))
            if init_stop == 0.25:
                sims_025.append((label, sim))
            else:
                sims_050.append((label, sim))

    # Structural row for comparison
    struct_r = compute_metrics("Structural | P1 No lock", df, df, None, None)
    struct_r["init_stop_pct"]   = 0.0
    struct_r["lock_fired_pct"]  = 0.0
    struct_r["regime_exit_pct"] = pct((df["exit_reason"] == "regime_flip").sum(), len(df))

    combined_rows = [struct_r] + all_rows

    report_headline(combined_rows)
    report_exit_breakdown(combined_rows)
    report_monthly(df, all_sims)
    report_runner_leakage(df, sims_025, sims_050)
    report_be_050_exact(df)

    sep("KEY CANDIDATES RANKED BY EV")
    ranked = sorted(combined_rows, key=lambda r: r["ev"], reverse=True)
    print(f"\n  {'Rank':<5}  {'Label':<40}  {'EV':>8}  {'PF':>5}  {'MaxDD':>10}")
    for i, r in enumerate(ranked[:8], 1):
        print(f"  {i:<5}  {r['label']:<40}  {r['ev']:>+8.1f}  {r['pf']:>5.2f}  "
              f"{r['max_dd']:>+10,.0f}")

    sep("DONE")


if __name__ == "__main__":
    main()
